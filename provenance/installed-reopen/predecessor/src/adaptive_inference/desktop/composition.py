# SPDX-License-Identifier: Apache-2.0
"""One installed Windows host/worker/GUI composition of the accepted lifecycle.

Dedicated process only. No work occurs on import. An explicit bounded file task
(or the retained orders example) starts paused and requires genuine GUI Resume.
Unknown child/pipe obligations remain retained; exit124 is an emergency failure,
never a clean Stop or completed task.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import traceback
import uuid

from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore
from adaptive_inference.control_mailbox import Mailbox, execution_outcome
from adaptive_inference.execution_clock import CLOCK_ID, execution_now, verify_execution_clock
from adaptive_inference.handoff import ToolRequirements
from adaptive_inference.desktop.installation import package_identity, sha, verify_interpreter, verify_sdk
from adaptive_inference.desktop.profile import WindowsProfile, COOPERATIVE_POLICY
from adaptive_inference.desktop.control_transport import PreparedTask, ControlTransport, credential
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime, ExpiredObservation
from adaptive_inference.desktop.ui_intent import UIIntentGate
from adaptive_inference.desktop.serial_listener import SerialListener
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.run_recovery import MODEL, QUALITY, PROMPT
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding, STOP_EXIT

HERE = Path(__file__).resolve().parent
INITIAL_PAUSE = 'initial-pause-before-bootstrap'
TITLE = 'Adaptive inference'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def diagnostic(exc):
    chain=[];seen=set();cause=exc
    while cause is not None and id(cause) not in seen and len(chain)<16:
        seen.add(id(cause))
        row={'type':type(cause).__name__,'message':str(cause)}
        for key in ('sqlite_errorcode','sqlite_errorname','winerror','errno'):
            value=getattr(cause,key,None)
            if type(value) in (int,str):row[key]=value
        chain.append(row);cause=cause.__cause__ or cause.__context__
    return {'type':type(exc).__name__,'message':str(exc),'chain':chain,
            'traceback':''.join(traceback.format_exception(exc))}

def hard_deadline(seconds=1800, *, wait=time.sleep, terminate=os._exit):
    # No receipt/log/file IO: blocked or failed diagnostics cannot prevent exit.
    # This daemon remains armed through asyncio and interpreter teardown.
    wait(seconds)
    terminate(124)

def complete_ledger(events,prefix):
    rows=deepcopy(list(events));maximum=getattr(events,'maxlen',None)
    # A full deque cannot prove whether append discarded a prefix. Conservatively
    # refuse even the exactly-full case; no shared controller change is needed.
    if (not prefix or type(maximum) is not int or len(rows)>=maximum
            or rows[:len(prefix)]!=prefix):
        raise RuntimeError('Controller ledger prefix missing or bounded buffer full')
    return rows

def no_work(cp,original,deadline,host,work, *, cold=True):
    """Read-only actual checkpoint/runtime gate, used before GUI and at terminal."""
    if (cp.prompt!=original.prompt or cp.metadata!=original.metadata or cp.max_attempts!=original.max_attempts
            or cp.state['messages']!=original.state['messages']
            or cp.state.get('deadline_monotonic')!=deadline or cp.state['status']!='pending'
            or cp.state['phase']!='ready' or cp.operation is not None or cp.requires_reconciliation
            or cp.state['requests'] or cp.state['attempts'] or cp.state['admission_attempts']
            or cp.state['tools'] or cp.state['native_history'] or cp.state['pending_request'] is not None
            or cp.state['admission_deferrals'] or cp.state[NAMESPACE]['state']!='paused'):
        raise RuntimeError('Paused original task contains new/unknown work or changed accounting')
    gateway=host.gateway;scheduler=gateway.scheduler
    if cold and (host.adapter.launch_intent is not None or host.adapter.started_owner
            or gateway._runtime_context is not None or gateway.history or scheduler.active is not None
            or scheduler.pending or scheduler.uncertain or host.controller.fault is not None):
        raise RuntimeError('Cold zero-work runtime evidence differs')
    from adaptive_inference.task_spec import TaskSpec
    spec = TaskSpec.from_metadata(cp.metadata)
    outputs = ['report.json'] if spec is None else [row['name'] for row in spec.data['outputs']]
    for filename in ('effect-receipts.jsonl','wire-observations.json', *(f'work/{name}' for name in outputs)):
        path=work/filename
        if path.exists() and path.read_bytes().strip() not in (b'',b'[]'):
            raise RuntimeError('Unexpected provider/effect artifact in cold trial')

async def join_retained(tasks):
    """Join every known obligation even when a sibling failed; never cancel it."""
    unique={id(task):task for task in tasks if task is not None}
    if not unique:return []
    return await asyncio.gather(*(asyncio.shield(task) for task in unique.values()),return_exceptions=True)


class DesktopComposition:
    """Shared lifecycle; qualification scenarios may extend its existing seams."""
    def __init__(self, profile_path, run, *, qualification_hold_after_report=False,
                 task_spec=None, task_inputs=None):
        self.profile_path = Path(profile_path).resolve(strict=True)
        self.profile_sha256 = sha(self.profile_path)
        self.profile = WindowsProfile.load(self.profile_path)
        if type(qualification_hold_after_report) is not bool:
            raise TypeError('Qualification hold must be an explicit boolean')
        self.qualification_hold_after_report = qualification_hold_after_report
        if (task_spec is None) != (task_inputs is None):
            raise ValueError('Task specification and input directory must be supplied together')
        self.task_spec_path = self.task_inputs = self.task_spec_sha256 = None
        if task_spec is not None:
            from adaptive_inference.task_spec import TaskSpec, MAX_SPEC_BYTES
            self.task_spec_path = Path(task_spec).resolve(strict=True)
            self.task_inputs = Path(task_inputs).resolve(strict=True)
            if not self.task_spec_path.is_file() or not self.task_inputs.is_dir():
                raise ValueError('Explicit task specification file and input directory required')
            with self.task_spec_path.open('rb') as stream:
                raw = stream.read(MAX_SPEC_BYTES + 1)
            # Decode now, before retaining any process. Preparation independently
            # verifies these same bytes and stages the declared input files.
            TaskSpec.from_bytes(raw)
            self.task_spec_sha256 = rec.digest(raw)
            if qualification_hold_after_report:
                raise ValueError('The orders report qualification hold cannot select another task')
        self.root = Path(run).absolute()
        if self.root.exists() or not self.root.parent.is_dir() or self.root.parent.resolve() != self.root.parent:
            raise ValueError('Use a fresh run directory under an existing non-redirected parent')
        self.handles=[]; self.logs=[]; self.waits={}; self.host=self.job=self.worker=None
        self.gui=self.facade=self.runtime=self.transport=self.listener=self.stop_binding=None
        self.deadline=self.original=self.initial_events=None
        self.progress=None; self.stop_id='service-stop-'+uuid.uuid4().hex
        self.result={'schema':'adaptive.desktop.windows-orders.result.v1', 'clean_stop':False,
                     'task_completed':False, 'execution_expired':False,
                     'model':MODEL, 'quality':deepcopy(QUALITY)}
        if self.task_spec_path is not None:
            self.result['schema'] = 'adaptive.desktop.windows-file-task.result.v1'
        self.worker_exit_verified=False
        self.continuation = None
        self.handover = None

    def launch(self, command, label):
        stream=(self.root/(label+'.log')).open('wb'); self.logs.append(stream)
        before=len(self.handles)
        try:
            child=subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, cwd=self.root,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.handles.append(child)
            self.event('worker_launched',label=label,pid=child.pid)
            return child
        finally:
            if label=='worker' and len(self.handles)==before+1:
                self.worker=self.handles[-1]

    def event(self,kind,**fields):
        value={'kind':kind,'at_monotonic':time.monotonic(),**fields}
        with (self.root/'events.private.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,allow_nan=False)+'\n');stream.flush()

    async def until(self,predicate,child=None,timeout=240):
        limit=min(execution_now()+timeout,self.deadline or float('inf'))
        while True:
            value=predicate()
            if value:return value
            if child is not None and child.poll() is not None:
                raise RuntimeError('Owned worker exited before required boundary; see retained log')
            if execution_now()>=limit:raise TimeoutError('Qualification boundary deadline')
            if self.host and self.host.controller.fault:raise RuntimeError('Controller fault: '+str(self.host.controller.fault))
            await asyncio.sleep(.05)

    def remaining(self):
        remaining=self.deadline-execution_now()
        if remaining<=0:raise TimeoutError('Original900second task deadline exhausted')
        return remaining

    def status(self,request_id):return self.box.status(request_id)

    def submit(self,request_id,command):
        receipt=self.box.submit(self.capability,request_id,command)
        self.event('control_recorded',**receipt);return receipt

    async def ack(self,request_id,child):
        receipt=await self.until(lambda:self.status(request_id) if self.status(request_id)['owner_acknowledged'] else None,child)
        if receipt['outcome']!='applied':raise RuntimeError('Required user control was rejected')
        self.event('control_acknowledged',**receipt)
        return receipt

    def checkpoint(self):return self.store.load(self.identity.task_id)

    def assert_original(self,cp):
        if (cp.prompt!=self.original.prompt or cp.metadata!=self.original.metadata
                or cp.state['messages'][0]!=self.original.state['messages'][0]
                or cp.state.get('deadline_monotonic')!=self.deadline
                or cp.state.get('deadline_clock')!=CLOCK_ID):
            raise RuntimeError('Original identity, objective or deadline changed')

    async def ready(self,child,path):
        await self.until(lambda:(self.work/f'bootstrap-{child.pid}.json').exists(),child)
        boot=read(self.work/f'bootstrap-{child.pid}.json');cp=self.checkpoint()
        self.assert_original(cp)
        if (boot['pid']!=child.pid or boot['task_id']!=self.identity.task_id
                or boot['registration_id']!=self.identity.registration_id
                or boot['deadline_monotonic']!=self.deadline or boot.get('deadline_clock')!=CLOCK_ID
                or boot['owner_epoch']!=cp.owner_epoch):
            raise RuntimeError('Bootstrap receipt is not the retained owner')
        if not self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Readiness waiting lacks actual trusted durable demand')
        self.event('demand_before_readiness',pid=child.pid,revision=cp.revision)
        await self.host.wait_ready(timeout_s=min(240,self.remaining()))
        rec.save(path,{'ready':True,'model':MODEL,'quality':QUALITY,'gateway':self.plan['gateway'],
            'gateway_instance':self.host.gateway.instance,'observed_at':time.time()})
        self.event('controller_ready',pid=child.pid,owner_id=self.host.controller.identity['owner_id'])

    def bind_worker_stop(self):
        if self.stop_binding is None:
            self.worker_cap=object()
            self.stop_binding=WorkerStopBinding(self.worker,self.work,self.box,requester_capability=self.capability,
                capability=self.worker_cap,stop_request_id=self.stop_id,original=self.original,
                deadline_monotonic=self.deadline,model=MODEL,quality=QUALITY,fence=self.fence,
                deadline_clock=CLOCK_ID)

    async def join_child(self,child):
        if child not in self.handles:raise RuntimeError('Cannot adopt a child for cleanup')
        task=self.waits.get(child)
        if task is None:
            # The retained object owns the OS handle; a reused PID must never
            # borrow the completed wait of an earlier process in this host.
            task=self.waits[child]=asyncio.create_task(asyncio.to_thread(child.wait))
        code=await asyncio.shield(task)
        self.event('retained_process_exit',pid=child.pid,exit_code=code,terminated=False)
        return code

    def fence(self):
        if self.facade is not None:self.facade.fence_admission()
        elif self.host is not None:
            self.host.closing=True;self.host.gateway.scheduler.closing=True

    def paused_ack(self):
        snapshot=self.box.snapshot();ack=snapshot.status(INITIAL_PAUSE);cp=snapshot.target
        if ack['outcome']!='applied' or ack['owner_acknowledged'] is not True:return None
        if type(cp.owner_epoch) is not str or len(cp.owner_epoch)!=32:return None
        if self.worker.poll() is not None:raise RuntimeError('Worker exited before paused ownership proof')
        no_work(cp,self.original,self.deadline,self.host,self.work)
        if snapshot.demand is None or snapshot.demand['state']!='paused':raise RuntimeError('No durable paused demand')
        return {'ack':ack,'checkpoint':asdict(cp),'worker_pid':self.worker.pid}

    def bind_gui(self,binding,verifier,bootstrap):
        self.facade.bind_window(binding,verifier,bootstrap)
        self.transport.bind_session(self.transport_cap,binding.session_id,bootstrap.token)
        return True

    def obligations(self):
        tasks=[]
        if self.facade is not None:tasks += [self.facade._wake,self.facade._stop,*self.facade._joins]
        if self.runtime is not None:tasks += [self.runtime._stop_task,*tuple(self.runtime._pending),
                                             *tuple(self.runtime._continuation_tasks)]
        if self.stop_binding is not None:tasks += [self.stop_binding._work]
        if self.gui is not None:tasks += [self.gui._start_task,*self.gui._io]
        if self.listener is not None:
            tasks += [self.listener._driver,self.listener._close_task]
            if self.listener._record is not None:
                tasks += [self.listener._record.get(key) for key in ('setup','handler','cleanup')]
        if self.transport is not None:
            tasks += [self.transport._stop_task,self.transport._close_task,*tuple(self.transport._handlers)]
            tasks += [row.get('task') for row in self.transport._records.values()]
            tasks += [row.get('cleanup') for row in self.transport._connections.values()]
        return tasks

    def control_io_released(self):
        listener_ok=(self.listener is None or self.listener.lifecycle()['resources_closed'] is True)
        transport_ok=(self.transport is None or not self.transport._handlers and not self.transport._connections
            and self.transport._close_task is not None and self.transport._close_task.done()
            and not self.transport._close_task.cancelled())
        return listener_ok and transport_ok

    async def join_gui_resources(self):
        if self.gui is None:return
        if self.gui._start_task is not None and not self.gui._bound:self.gui.abort_startup()
        while True:
            receipt=await self.gui.join(timeout_s=2)
            if (receipt['pending_pipe_operations']==0 and receipt['pipe_handles_closed']
                    and receipt['process_handle_closed'] and receipt['verifier_handle_closed']
                    and (not receipt['child_retained'] or receipt['child_exit_observed'])):
                self.result['gui_cleanup']=receipt
                return
            await asyncio.sleep(.05)

    async def dispose_control_io(self):
        if self.listener is not None:
            while True:
                value=await self.listener.aclose(timeout=2)
                if value['resources_closed']:break
                await asyncio.sleep(.05)
            self.result['listener_cleanup']=value
        if self.transport is not None:
            while True:
                value=await self.transport.aclose(timeout=2)
                if (value['handlers']==0 and value['pending_connections']==0
                        and self.transport._close_task.done()):break
                await asyncio.sleep(.05)
            self.result['transport_cleanup']=value

    async def dispose(self,failed):
        """Cooperative cleanup only. Live/unknown obligations stay retained."""
        if getattr(self,'handover',None) is not None:
            return await self.handover.dispose(failed)
        self.fence()
        if self.worker is not None and self.stop_binding is None:self.bind_worker_stop()
        if self.transport is not None:
            self.transport._request_stop()  # Trusted failure cleanup; no network command or auto Resume.
            await asyncio.shield(self.transport._stop_task)
        elif self.stop_binding is not None:
            self.stop_binding.request_stop(self.worker_cap)
            while self.worker.poll() is None:await self.stop_binding.join(timeout=2)
        # Failed startup closes only its owned input when safe. A started GUI
        # sees stop_requested through the still-live listener and exits.
        await self.join_gui_resources()
        for child in self.handles:await self.join_child(child)
        # The listener must remain usable for the GUI's final close reply, but
        # its live accept driver cannot be joined until acceptance is fenced.
        if self.listener is not None:self.listener.close()
        errors=await join_retained(self.obligations())
        self.result['retained_obligations_joined']=True
        if any(isinstance(value,BaseException) for value in errors):
            self.result['joined_obligation_errors']=[diagnostic(value) for value in errors if isinstance(value,BaseException)]
        if self.host is not None:
            # Even a failed trial may safely clean native resources once every
            # actual retained child and pipe/handle obligation is positively joined.
            self.result['cleanup']=await self.host.close(timeout_s=180)
        await self.dispose_control_io()
        self.result['all_retained_process_exits']=[{'pid':child.pid,'exit_code':child.poll()} for child in self.handles]

    async def prepare(self):
        # Verify installation and explicit deployment inputs before owning any
        # child. Windows APIs/native modules are imported only on this path.
        if os.name != 'nt' or sys.version_info[:3] != (3, 11, 9):
            raise RuntimeError('This first desktop profile requires full Windows CPython 3.11.9')
        verify_execution_clock()
        profile = self.profile
        verify_interpreter(profile.host_python, profile.host_python_sha256, current=True)
        verify_interpreter(profile.worker_python, profile.worker_python_sha256)
        verify_sdk(profile.hermes_source)
        self.installed = package_identity()
        if sha(self.profile_path) != self.profile_sha256:
            raise RuntimeError('Deployment profile changed')
        rec.save(self.root/'installed-package.private.json', self.installed)
        self.result['package_version'] = self.installed['version']
        from adaptive_inference.desktop import owned_job
        from adaptive_inference.desktop.activity import WindowsActivityReader
        from adaptive_inference.desktop.cold_start import ColdStartAdapter
        from adaptive_inference.desktop.desktop_controls import ControlledDesktopHost, DesktopControlLifecycle
        from adaptive_inference.desktop.foreground_policy import ForegroundPolicy
        from adaptive_inference.desktop.gui_launch import OwnedUILaunch, WindowsLaunchAPI, LaunchSpec, CHILD_SOURCES
        from adaptive_inference.desktop.control_client import Bootstrap

        self.job = owned_job
        self.job.contain_current_process()
        self.work = self.root/'hermes-task'
        prepare_command = [str(profile.worker_python), '-I', '-B', '-m',
            'adaptive_inference.desktop.hermes.run_recovery', 'prepare', '--run', str(self.work),
            '--profile', str(self.profile_path), '--profile-sha256', self.profile_sha256,
            '--package-identity', str(self.root/'installed-package.private.json'),
            '--control-case', 'complete']
        if self.task_spec_path is None:
            prepare_command.append('--validate-report-before-write')
        else:
            prepare_command.extend(['--task-spec', str(self.task_spec_path),
                '--task-spec-sha256', self.task_spec_sha256, '--task-inputs', str(self.task_inputs),
                '--task-id', 'task-'+uuid.uuid4().hex, '--session-id', 'adaptive-'+uuid.uuid4().hex])
        child = self.launch(prepare_command, 'prepare')
        await self.until(lambda:child.poll() is not None, timeout=60)
        if await self.join_child(child) != 0:
            raise RuntimeError('Fresh paused-task preparation failed; see prepare.log')
        self.plan = read(self.work/'plan.json')
        self.store = TaskStore(self.work/'task.sqlite3')
        self.identity = DemandIdentity(**self.plan['demand_identity'])
        self.registry = DemandRegistry((Registration(self.store,self.identity),))
        self.capability = object()
        self.box = Mailbox(self.registry, self.identity.registration_id, requester_capability=self.capability)
        self.original = self.checkpoint()
        if (self.plan.get('deadline_clock')!=CLOCK_ID or self.original.metadata.get('deadline_clock')!=CLOCK_ID
                or self.original.state.get('deadline_clock')!=CLOCK_ID):
            raise RuntimeError('Fresh installed task lacks the explicit execution clock')
        rec.save(self.root/'original-checkpoint.private.json', asdict(self.original))
        self.submit(INITIAL_PAUSE, 'pause')
        self.host_epoch = 'desktop-'+uuid.uuid4().hex
        self.intent_cap = object()
        self.gate = UIIntentGate(host_epoch=self.host_epoch, capability=self.intent_cap,
            verify_current=lambda binding:None if self.facade is None else self.facade.verify_current(binding))
        if profile.foreground_policy == COOPERATIVE_POLICY:
            from adaptive_inference.desktop.ui_progress import CooperativeProgress
            self.progress = CooperativeProgress(self.gate, self.intent_cap)
        self.result['foreground_policy_id'] = profile.foreground_policy
        owner = dict(profile.owner)
        self.reader = WindowsActivityReader()
        adapter = ColdStartAdapter(**owner, job=self.job, max_runtime_seconds=None)
        self.host = ControlledDesktopHost(owner, profile.gateway, self.root/'host',
            ForegroundPolicy(ui_intent=self.gate, cooperative_progress=self.progress),
            demand=self.registry, restore_requirements=ToolRequirements(3,3,250), adapter=adapter,
            reader=self.reader, job=self.job, max_runtime_seconds=None, idle_grace_s=30, runtime_timing=True)
        await self.host.start(timeout_s=30)
        self.initial_events = deepcopy(list(self.host.controller.events))
        complete_ledger(self.host.controller.events, self.initial_events)
        if adapter.launch_intent is not None or adapter.started_owner or self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Cold host unexpectedly loaded before paused owner bootstrap')
        self.deadline = execution_now()+900
        self.result['deadline_monotonic'] = self.deadline
        self.result['deadline_clock'] = CLOCK_ID
        self.first_ready = self.work/'controller-ready-1.json'
        command = [self.plan['base_python'], '-I', '-B', '-m',
            'adaptive_inference.desktop.hermes.run_recovery', 'worker', '--run', str(self.work),
            '--controller-ready', str(self.first_ready), '--gateway-instance', self.host.gateway.instance,
            '--deadline-monotonic', str(self.deadline), '--stop-request-id', self.stop_id]
        if self.qualification_hold_after_report:
            command.append('--qualification-hold-after-report')
        self.worker = self.launch(command, 'worker')
        self.bind_worker_stop()
        self.launch_api = WindowsLaunchAPI()
        handle = self.launch_api.handle(self.worker)
        self.worker_identity = self.launch_api.identity(handle)
        if (self.launch_api.in_job(handle,self.job._HANDLE) is not True
                or self.worker_identity[0] != self.worker.pid or self.worker.poll() is not None):
            raise RuntimeError('Retained installed worker is not live in this exact containing job')
        self.result['retained_worker_identity'] = {'pid':self.worker_identity[0],
            'creation_time_100ns':self.worker_identity[1], 'containing_job_verified':True}
        paused = await self.until(self.paused_ack, self.worker, timeout=60)
        rec.save(self.root/'paused-before-gui.private.json', paused)
        self.gui = OwnedUILaunch(api=self.launch_api)
        prepared = PreparedTask(self.host_epoch,self.identity.task_id,self.original.prompt)
        self.facade = DesktopControlLifecycle(self.host,prepared,worker_stop=self.stop_binding,
            worker_capability=self.worker_cap,gui=self.gui,shutdown_timeout_s=120)
        self.runtime = MailboxRuntime(prepared,self.box,requester_capability=self.capability,
            gate=self.gate,intent_capability=self.intent_cap,lifecycle=self.facade)
        await self.runtime.refresh()
        self.host.attach_control_runtime(self.runtime)
        from adaptive_inference.desktop.continuation_host import HostContinuation
        self.continuation = HostContinuation(self,self.runtime)
        from adaptive_inference.desktop.task_handover import HostTaskHandover
        self.handover = HostTaskHandover(self)
        self.transport_cap = object()
        self.transport = ControlTransport(prepared,self.runtime,capability=self.transport_cap,
            runner_credential='local-no-key',cooperative_progress=self.progress,
            handover=self.handover.adapter(self.runtime))
        self.listener = SerialListener(self.transport)
        endpoint = self.listener.start()
        self.handover.capture_initial()
        bootstrap = Bootstrap(self.host_epoch,'session-'+uuid.uuid4().hex,self.identity.task_id,self.original.prompt,
            credential(),endpoint[0],endpoint[1],'AdaptiveInference.'+uuid.uuid4().hex,secrets.randbelow(2**31-1)+1)
        spec = LaunchSpec(profile.host_python,profile.host_python_sha256,HERE/'run_gui.py',
            tuple((name,sha(HERE.parent/name)) for name in sorted(CHILD_SOURCES)))
        await self.gui.start(spec,bootstrap,containing_job=self.job._HANDLE,
            launch_ready=lambda:self.host.started_at is not None and not self.host.closing
                and self.host.adapter.launch_intent is None and self.paused_ack() is not None,
            bind_session=self.bind_gui,revoke_session=self.facade.window_closed,timeout_s=10)
        await self.until(lambda:self.transport._ready,self.worker,timeout=30)
        no_work(self.checkpoint(),self.original,self.deadline,self.host,self.work)
        self.result['retained_gui_binding'] = asdict(self.gui.binding)
        rec.save(self.root/'ready.private.json',{'ready':True,'gui_pid':self.gui.process.pid,
            'worker_pid':self.worker.pid,'task_id':self.identity.task_id,'paused_owner_acknowledged':True,
            'model_started':False,'instructions':'Resume to run the task. Pause pauses at a safe boundary. Stop closes this session.'})

    async def _paused_expiry_candidate(self):
        # Reuse the runtime's retained off-loop coherent read; no new database
        # observer or blocking SQLite work is introduced on the host loop.
        await self.runtime.refresh()
        snapshot = self.runtime._cache.snapshot
        cp = snapshot.target
        marker = execution_outcome(cp.state)
        return (cp.state['status'] == 'pending' and cp.operation is None
            and not cp.requires_reconciliation and cp.state.get('deadline_monotonic') == self.deadline
            and cp.state.get('deadline_clock') == CLOCK_ID
            and cp.state.get('phase') in ('ready','waiting_admission')
            and cp.state.get('pending_request') is None
            and snapshot.demand is not None and snapshot.demand['state'] == 'paused'
            and bool(snapshot.requests) and len(snapshot.requests) == len(snapshot.receipts)
            and snapshot.requests[-1]['command'] == 'pause' and snapshot.receipts[-1]['outcome'] == 'applied'
            and (marker is None or marker['deadline_monotonic'] == self.deadline))

    async def _admission_wait_expiry_candidate(self):
        # Like the paused path this retains finalization, never authorizes work.
        from adaptive_inference.control_mailbox import ControlBlocked
        await self.runtime.refresh()
        snapshot = self.runtime._cache.snapshot
        cp = snapshot.target
        if (cp.task_id != self.stop_binding.original.task_id
                or cp.state.get('deadline_monotonic') != self.deadline
                or cp.state.get('deadline_clock') != CLOCK_ID):
            return False
        # Pure immutable binding checks; durable selected lifetime verification
        # still belongs to the exact exit verifier after the retained join.
        self.stop_binding._admission_wait_identity(cp)
        try:
            self.stop_binding.mailbox.admission_wait_candidate(snapshot, allow_sealed=True)
        except ControlBlocked:
            return False
        return True

    def assert_continuation_parked(self, release):
        controller,scheduler = self.host.controller,self.host.gateway.scheduler
        owner = None if controller.identity is None else controller.identity['owner_id']
        if (controller.state != 'parked' or controller.fault is not None or controller.tool is not None
                or scheduler.active is not None or scheduler.pending or scheduler.uncertain
                or owner != release['native']['owner_id']
                or self.host.adapter._barrier is None
                or self.host.adapter._cold_start_error is not None or self.host.adapter._startup_failure is not None):
            raise RuntimeError('Continuation requires the same verified parked native owner')
        if owner is not None and self.host.adapter._released != release['native']['release']:
            raise RuntimeError('Parked release identity changed before selection')

    async def continuation_release(self, request, intent_valid, *, task_handover=False):
        from adaptive_inference.desktop.control_transport import Refused
        from adaptive_inference.desktop.hermes.service_stop import PAUSED_EXPIRY_EXIT, WAIT_EXPIRY_EXIT
        child,binding = self.worker,self.stop_binding
        if request['execution_id'] != binding.original.task_id:
            raise Refused('stale_execution')
        limit=execution_now()+120
        while child.poll() is None:
            if self.runtime._stopping or not intent_valid():raise Refused('continuation_blocked')
            if execution_now()>=limit:raise TimeoutError('Previous worker has not released')
            await asyncio.sleep(.05)
        code=await self.join_child(child)
        if not task_handover and code not in (PAUSED_EXPIRY_EXIT, WAIT_EXPIRY_EXIT):
            raise Refused('continuation_unavailable')
        outcome=await asyncio.to_thread(binding._verify_exit,code)
        expired = {PAUSED_EXPIRY_EXIT: 'paused_budget_expired',
                   WAIT_EXPIRY_EXIT: 'admission_wait_budget_expired'}
        allowed = ('task_completed','task_cancelled') if task_handover else (expired[code],)
        if outcome not in allowed:raise Refused('continuation_unavailable')
        while self.host.controller.state!='parked':
            if self.runtime._stopping or not intent_valid():raise Refused('continuation_blocked')
            if self.host.controller.fault or execution_now()>=limit:
                raise RuntimeError('Previous native owner did not reach verified parking')
            await asyncio.sleep(.05)
        async with self.host.controller.lock:
            adapter,controller=self.host.adapter,self.host.controller
            def parked():
                if (adapter._barrier is None or adapter._cold_start_error is not None
                        or adapter._startup_failure is not None):
                    raise RuntimeError('Native startup/release ownership is unresolved')
                state=adapter.driver.status()
                adapter._stopped_identity(state)
                if adapter.driver.owner_idle() is not True or adapter.driver.port_free(18098) is not True:
                    raise RuntimeError('Native owner or backend port is still occupied')
                owner=None if controller.identity is None else controller.identity['owner_id']
                proof=deepcopy(adapter._released)
                if owner is None:
                    if adapter.started_owner or not adapter._cold_prepared or adapter.parked_observation is None:
                        raise RuntimeError('Cold native parking is not proven')
                elif (type(proof) is not dict or proof.get('owner_id')!=owner
                        or any(proof.get(key) is not True for key in ('released','cleanup_confirmed','port_free'))
                        or type(proof.get('retained_processes')) is not int or proof['retained_processes']<1
                        or proof.get('confirmed_process_exits')!=proof['retained_processes']):
                    raise RuntimeError('Exact retained native release is missing')
                return {'owner_id':owner,'release':proof,'status_sha256':rec.digest(state),
                        'owner_lock_idle':True,'backend_port_free':True,'startup_barrier_held':True}
            native=await adapter._call(parked)
            release={'worker_joined':True,'worker_pid':child.pid,'exit_code':code,'outcome':outcome,
                     'native':native,'execution_id':request['execution_id']}
            self.assert_continuation_parked(release)
        return release

    async def launch_continuation(self, record, coordinator, intent_valid):
        from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding,selection
        grant=record['grant'];suffix=grant['payload_sha256'][:24]
        record.update(pause_id='continue-pause-'+suffix,resume_id='continue-resume-'+suffix,
                      stop_id='continue-stop-'+suffix)
        diagnostics=self.work/'executions'/grant['payload']['successor_id']
        record['diagnostics']=diagnostics
        def files():
            diagnostics.mkdir(parents=True,exist_ok=False)
            path=diagnostics/'grant.json';rec.save(path,grant)
            return path
        path=await asyncio.to_thread(files)
        if not coordinator.live(intent_valid):return
        await self.runtime.submit_control(record['pause_id'],'pause',execution=selection(grant),_transition=True)
        if not coordinator.live(intent_valid):return
        self.first_ready=diagnostics/'controller-ready.json'
        command=[self.plan['base_python'],'-I','-B','-m','adaptive_inference.desktop.hermes.run_recovery',
            'worker','--run',str(self.work),'--continuation-grant',str(path),
            '--host-generation',self.runtime.prepared.host_epoch,'--controller-ready',str(self.first_ready),
            '--gateway-instance',self.host.gateway.instance,'--deadline-monotonic',str(grant['deadline_monotonic']),
            '--stop-request-id',record['stop_id']]
        # The original trial's report hold is not inherited: this click supplies
        # one fresh Resume, and existing artifact/receipt verification still wins.
        record['launch_attempted']=True
        before=len(self.handles)
        try:
            self.launch(command,'worker-continue-'+str(grant['execution_generation']))
        finally:
            if len(self.handles)==before+1:
                child=self.handles[-1]
                record['child']=child;self.worker=child
                capability=object()
                binding=SelectedWorkerStopBinding(child,self.work,record['mailbox'],
                    requester_capability=record['requester'],capability=capability,
                    stop_request_id=record['stop_id'],original=record['original'],
                    deadline_monotonic=grant['deadline_monotonic'],model=MODEL,quality=QUALITY,
                    fence=self.fence,deadline_clock=CLOCK_ID,grant=grant,authority=record['authority'])
                self.facade.bind_selected_worker(record,binding,capability)
                self.stop_binding,self.worker_cap,self.stop_id=binding,capability,record['stop_id']
                self.worker_exit_verified=False
        child=record['child']
        handle=self.launch_api.handle(child)
        observed=self.launch_api.identity(handle)
        if self.launch_api.in_job(handle,self.job._HANDLE) is not True or observed[0]!=child.pid or child.poll() is not None:
            raise RuntimeError('Selected child is not live in the retained containing job')
        record['retained_child_identity']={'pid':observed[0],'creation_time_100ns':observed[1],
                                           'containing_job_verified':True}
        await self.wait_continuation_ack(record,record['pause_id'],intent_valid)

    async def wait_continuation_ack(self,record,request_id,intent_valid):
        child,mailbox=record['child'],record['mailbox']
        def install(observation):
            try:
                self.runtime._install(observation)
            except ExpiredObservation:
                # Read only: retain prior cache/intent, use no ACK from this read.
                # A fresh read must still pass every binding/history check.
                return False
            return True
        while True:
            if self.runtime._stopping or not intent_valid():return None
            if child.poll() is not None or execution_now()>=record['grant']['deadline_monotonic']:
                raise RuntimeError('Selected worker did not acknowledge before its deadline')
            fresh=await self.runtime._database(lambda:self.runtime._observe(mailbox),install)
            if self.runtime._stopping or not intent_valid():return None
            if child.poll() is not None or execution_now()>=record['grant']['deadline_monotonic']:
                raise RuntimeError('Selected worker did not acknowledge before its deadline')
            if fresh:
                snapshot=self.runtime._cache.snapshot
                ack=snapshot.status(request_id)
                if ack['owner_acknowledged']:
                    if (ack['outcome']!='applied' or snapshot.target.owner_epoch is None
                            or snapshot.target.task_id!=record['grant']['payload']['successor_id']
                            or child.poll() is not None):
                        raise RuntimeError('Selected control lacks exact live owner acknowledgement')
                    return ack
            await asyncio.sleep(.05)

    async def ready_continuation(self,record,intent_valid):
        from adaptive_inference.desktop.continuation_host import selection
        child=record['child'];boot_path=record['diagnostics']/f'bootstrap-{child.pid}.json'
        # Keep the existing readiness bound, independent of a fresh task budget.
        limit=min(execution_now()+240,record['grant']['deadline_monotonic'])
        record['readiness_deadline_monotonic']=limit
        while True:
            if self.runtime._stopping or not intent_valid():return
            if child.poll() is not None:
                raise RuntimeError('Selected readiness exceeded the retained worker lifetime')
            if execution_now()>=limit:raise TimeoutError('Selected readiness boundary deadline')
            if self.host.controller.fault:raise RuntimeError('Controller fault during selected readiness')
            if boot_path.exists() and self.host.controller():break
            await asyncio.sleep(.05)
        mailbox=record['mailbox']
        await self.runtime._database(lambda:self.runtime._observe(mailbox),self.runtime._install)
        if self.runtime._stopping or not intent_valid():return
        boot=await asyncio.to_thread(read,boot_path)
        cp=self.runtime._cache.snapshot.target
        if (boot['pid']!=child.pid or boot['task_id']!=cp.task_id
                or boot['registration_id']!=record['identity'].registration_id
                or boot['owner_epoch']!=cp.owner_epoch or boot['deadline_clock']!=CLOCK_ID
                or boot['deadline_monotonic']!=record['grant']['deadline_monotonic']):
            raise RuntimeError('Selected bootstrap identity differs from its retained owner')
        if self.runtime._stopping or not intent_valid() or not self.host.controller():return
        value={'ready':True,'model':MODEL,'quality':QUALITY,'gateway':self.plan['gateway'],
               'gateway_instance':self.host.gateway.instance,'observed_at':time.time(),
               'selected_execution':selection(record['grant'])}
        await asyncio.to_thread(rec.save,self.first_ready,value)

    async def interact(self):
        # No invented admission or automatic Resume: the worker's saved demand,
        # host capacity and authenticated GUI intent must agree first.
        while not self.transport.lifecycle()['stop_requested']:
            if getattr(self,'handover',None) is not None and self.handover.transitioning:
                await asyncio.sleep(.05)
                continue
            selected = None if self.continuation is None else self.continuation.current
            if self.runtime._transitioning or selected is not None and selected['child'] is None:
                if self.gui.process.poll() is not None:
                    raise RuntimeError('GUI exited without confirmed Stop')
                await asyncio.sleep(.05)
                continue
            code = self.worker.poll()
            if code is None:
                if execution_now() >= self.deadline:
                    if (not await self._paused_expiry_candidate()
                            and not await self._admission_wait_expiry_candidate()):
                        self.remaining()
                else:
                    self.remaining()
            if code is not None and not self.worker_exit_verified:
                await self.join_child(self.worker)
                outcome = self.stop_binding._verify_exit(code)
                self.worker_exit_verified = True
                self.result['worker_outcome'] = outcome
                if outcome == 'task_completed' and self.task_spec_path is not None:
                    cp = self.stop_binding.mailbox.snapshot().target
                    spec = rec.task_contract(cp)
                    if spec is None:
                        raise RuntimeError('Completed user task lost its declared contract')
                    self.result.update(spec.completion(self.stop_binding.run/'work',cp.state['tools'],cp.state['output']))
                    self.result['task_spec_sha256'] = spec.sha256
                self.result['task_completed'] = outcome == 'task_completed'
                self.result['execution_expired'] = outcome in ('paused_budget_expired', 'admission_wait_budget_expired')
                await self.runtime.refresh()
            if (selected is None and code is None and not self.first_ready.exists()
                    and (self.work/f'bootstrap-{self.worker.pid}.json').exists()
                    and self.registry.observe(self.identity.registration_id).eligible
                    and self.host.controller()):
                await self.ready(self.worker,self.first_ready)
            if self.gui.process.poll() is not None:
                raise RuntimeError('GUI exited without confirmed Stop')
            if self.host.controller.fault:
                raise RuntimeError('Controller fault: '+str(self.host.controller.fault))
            await asyncio.sleep(.1)
        await asyncio.shield(self.transport._stop_task)
        if not self.transport.lifecycle()['stop_confirmed']:
            raise RuntimeError('Stop is not confirmed')
        self.result['lifecycle'] = await self.facade.cooperative_stop()
        if self.result['lifecycle'] != {'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}:
            raise RuntimeError('Cooperative Stop lacks exact verified closure')

    def validate_cleanup(self):
        if getattr(self,'handover',None) is not None:
            self.handover.validate_cleanup()
        selected = None if self.continuation is None else self.continuation.current
        if selected is not None and selected['child'] is None:
            self.continuation.verify_unlaunched(selected)
        else:
            self.stop_binding._verify_exit(self.worker.poll())
        if (self.result.get('joined_obligation_errors')
                or self.result.get('retained_obligations_joined') is not True
                or self.result.get('gui_cleanup',{}).get('closed') is not True
                or getattr(self,'handover',None) is None and self.result.get('gui_cleanup',{}).get('faults') != []
                or not self.result.get('listener_cleanup',{}).get('clean_close')
                or not self.result.get('transport_cleanup',{}).get('closed')):
            raise RuntimeError('Child, pipe or control ownership is not cleanly joined')
        if self.job.active_process_ids() != {os.getpid()}:
            raise RuntimeError('Actual containing job still has children')
        cleanup = self.result['cleanup']
        if (not self.host.closed or self.host.controller.fault
                or cleanup.get('closed') is not True
                or any(cleanup.get(k) is not None for k in ('primary_error','cleanup_error','controller_fault'))):
            raise RuntimeError('Native cleanup has a fault')
        package_identity(self.installed)

    async def run(self):
        if self.root.is_relative_to(HERE.parent):
            raise ValueError('Run state must be outside the installed package')
        self.root.mkdir(exist_ok=False)
        try:
            await self.prepare()
            await self.interact()
        except BaseException as error:
            self.result['primary_error'] = diagnostic(error)
        try:
            await self.dispose('primary_error' in self.result)
            if 'primary_error' not in self.result:
                self.validate_cleanup()
        except BaseException as error:
            self.result['cleanup_error'] = diagnostic(error)
            # Preserve the accepted failure path: uncertain retained operations
            # are never abandoned just because the caller's wait expired.
            try:
                rec.save(self.root/'unresolved.private.json',self.result)
            except BaseException as failure:
                self.result['diagnostic_write_error'] = diagnostic(failure)
            try:
                if getattr(self,'handover',None) is not None:
                    await self.handover.failure_cleanup()
                await self.join_gui_resources()
                if self.listener is not None:
                    self.listener.close()
                await join_retained(self.obligations())
                for child in self.handles:
                    await self.join_child(child)
                try:
                    if self.host is not None:
                        self.result['failure_cleanup'] = await self.host.close(timeout_s=180)
                    await self.dispose_control_io()
                except BaseException as failure:
                    self.result['failure_cleanup_error'] = diagnostic(failure)
                    if not self.control_io_released():
                        raise RuntimeError('Control listener/stream ownership remains unresolved') from failure
                if self.job is not None:
                    while True:
                        try:
                            if self.job.active_process_ids() == {os.getpid()}:
                                break
                        except BaseException as failure:
                            self.result.setdefault('job_observation_error',diagnostic(failure))
                        await asyncio.sleep(1)
            except BaseException as failure:
                self.result['retention_error'] = diagnostic(failure)
                try:
                    rec.save(self.root/'retention-failure.private.json',self.result)
                except BaseException:
                    pass
                while True:
                    try:
                        await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        continue
        if self.progress is not None:
            try:
                self.result['cooperative_foreground_final'] = self.progress.snapshot()
            except Exception as error:
                self.result['cooperative_diagnostic_error'] = diagnostic(error)
        self.result['clean_stop'] = not any(k in self.result for k in ('primary_error','cleanup_error'))
        for stream in self.logs:
            stream.close()
        rec.save(self.root/'result.private.json',self.result)
        return self.result


def execute(profile_path, run, *, qualification_timeout_s=None, task_spec=None, task_inputs=None):
    # Ordinary host lifetime is persistent, as in PersistentDesktopHost. Only a
    # caller explicitly running a qualification may arm its emergency bound.
    # Unknown ordinary cleanup remains retained; it is never reported clean.
    if qualification_timeout_s is not None:
        if type(qualification_timeout_s) is not int or qualification_timeout_s != 1800:
            raise ValueError('The accepted qualification guard is exactly 1800 seconds')
        threading.Thread(target=hard_deadline,args=(qualification_timeout_s,),daemon=True).start()
    options = {} if task_spec is None and task_inputs is None else {'task_spec':task_spec,'task_inputs':task_inputs}
    result = asyncio.run(DesktopComposition(profile_path,run,**options).run())
    result['asyncio_teardown_completed'] = True
    rec.save(Path(run)/'result.private.json',result)
    return result
