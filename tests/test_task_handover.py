"""Actual SQLite and preparation; fake child/native/window boundaries."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_store import TaskStore
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.desktop import task_handover as handover, installation
from adaptive_inference.desktop.desktop_controls import ControlledDesktopHost, DesktopControlLifecycle
from adaptive_inference.desktop.control_transport import PreparedTask, Refused
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.hermes import run_recovery as worker, recovery as rec
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from adaptive_inference.desktop.ui_intent import UIIntentGate, UIBinding, VerifiedUIObservation
from adaptive_inference.desktop.profile import WindowsProfile
from test_desktop_lifecycle import Worker, GUI, Host
from test_desktop_composition import Child, make_case
from test_task_admission import spec, UTC


class Endpoint:
    def __init__(self): self.retired=None; self._stop_task=None; self.stopped=False
    def retire_task(self, cap, request): self.retired=request
    def lifecycle(self): return {'stop_requested':self.stopped}
    def _request_stop(self): self.stopped=True
    async def aclose(self,timeout=2):
        self._close_task=asyncio.create_task(asyncio.sleep(0)); await self._close_task
        return {'handlers':0,'pending_connections':0,'closed':True}


class Window(GUI):
    def __init__(self, *, api=None):
        super().__init__(); self._start_task=None; self._bound=False
        self._io=[]; self.process=None; self.release.set()
    def abort_startup(self): pass
    def session_live(self,session_id):
        return self.binding is not None and session_id==self.binding.session_id and not self.revoked
    def window_live(self,session_id): return self.session_live(session_id)
    def revoke_session(self,session_id):
        assert session_id==self.binding.session_id
        self.revoked=True
    async def start(self,spec,bootstrap,*,containing_job,launch_ready,bind_session,revoke_session,timeout_s):
        assert launch_ready() is True
        self._start_task=asyncio.create_task(asyncio.sleep(0)); await self._start_task
        self.process=Child(88)
        self.binding=UIBinding(bootstrap.host_epoch,bootstrap.session_id,bootstrap.task_id,102,204,305)
        assert bind_session(self.binding,self.verifier,bootstrap) is True
        self._bound=True
        self.bootstrap=bootstrap


class Listener:
    port=18000
    def __init__(self,transport): self.transport=transport; self.closed=False
    def start(self):
        Listener.port+=1
        return '127.0.0.1',Listener.port
    def close(self): self.closed=True
    async def aclose(self,timeout=2):
        self.closed=True; return {'resources_closed':True,'clean_close':True}


class HandoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        c=self.c=make_case(self.root); c.root.mkdir(); c.work=c.root/'initial'
        (c.work/'work').mkdir(parents=True)
        c.host_epoch='host'; c.task_spec_path=self.root/'initial-task.json'
        c.task_inputs=self.root; c.task_spec_sha256='a'*64
        c.store=TaskStore(c.work/'task.sqlite3')
        c.identity=DemandIdentity('initial-demand','task','host',UTC)
        initial=spec('The first independent task.')
        meta={**initial.metadata(),'pre_effect_validator':initial.validator_identity(),
            'deadline_clock':CLOCK_ID,'model':worker.MODEL,'quality':worker.QUALITY}
        c.original=prepare_task(c.store,c.identity,initial.prompt,'initial-session',metadata=meta)
        with c.store.claim(c.identity.task_id,expected_revision=c.original.revision) as owner:
            state=deepcopy(owner.checkpoint.state); state['status']='accepted'; state['output']='Done.'
            owner.save_checkpoint(state,expected_revision=owner.checkpoint.revision)
        c.registry=DemandRegistry((Registration(c.store,c.identity),))
        c.capability=object(); c.box=Mailbox(c.registry,c.identity.registration_id,requester_capability=c.capability)
        c.worker=Child(code=0); c.handles.append(c.worker); c.worker_cap=object()
        self.w=Worker(); self.w.release.set(); c.stop_binding=self.w
        self.w.worker=c.worker; self.w._capability=c.worker_cap
        c.gui=Window(); c.facade=None; c.host=Host(self.w,c.gui)
        c.host.gateway.instance='retained-gateway'
        c.host.control_runtime=None; c.host._control_thread=threading.current_thread()
        c.host._control_loop=asyncio.get_running_loop(); c.host._control_rebinding=False
        c.host.retired_control_runtimes=[]
        c.host.controller.lock=asyncio.Lock(); c.host.controller._demand_lock=asyncio.Lock()
        c.host.controller.state='parked'; c.host.controller.tool=None; c.host.controller.identity=None
        c.host.commit_task_runtime=lambda *a:ControlledDesktopHost.commit_task_runtime(c.host,*a)
        c.host.adapter=SimpleNamespace(_barrier=object(),_cold_start_error=None,_startup_failure=None)
        c.intent_cap=object(); c.gate=UIIntentGate(host_epoch='host',capability=c.intent_cap,
            verify_current=lambda b:VerifiedUIObservation(b,time.monotonic(),True,True))
        prepared=PreparedTask('host','task',initial.prompt)
        c.facade=DesktopControlLifecycle(c.host,prepared,worker_stop=self.w,worker_capability=c.worker_cap,
            gui=c.gui,shutdown_timeout_s=3)
        c.facade.bind_window(c.gui.binding,c.gui.verifier,SimpleNamespace(host_epoch='host',task_id='task',
            session_id='session',objective=initial.prompt))
        c.runtime=MailboxRuntime(prepared,c.box,requester_capability=c.capability,
            gate=c.gate,intent_capability=c.intent_cap,lifecycle=c.facade,max_age_s=3)
        await c.runtime.refresh(); c.host.control_runtime=c.runtime
        c.transport=Endpoint(); c.transport_cap=object(); c.listener=None
        c.plan={}; c.deadline=1.; c.first_ready=c.work/'ready.json'; c.continuation=None
        c.installed={}; c.launch_api=SimpleNamespace(handle=lambda p:p,identity=lambda h:(h.pid,300),in_job=lambda *a:True)
        c.job=SimpleNamespace(_HANDLE=1)
        c.profile_path=self.root/'profile.json'; c.profile_path.write_text('{}'); c.profile_sha256=rec.digest(b'{}')
        c.profile=SimpleNamespace(worker_python=Path('fixture-python'),host_python=Path('fixture-host'),
            worker_python_sha256='a'*64,host_python_sha256='b'*64,
            hermes_source=self.root/'sdk',hermes_site_packages=self.root,gateway=SimpleNamespace(port=18100))
        rec.save(c.root/'installed-package.private.json',{})
        self.inputs=self.root/'inputs'; self.inputs.mkdir()
        self.new_spec=spec('Explain a second independent idea.')
        self.spec_path=self.root/'next.json'; self.spec_path.write_text(json.dumps(self.new_spec.data),encoding='utf-8')
        self.coordinator=c.handover=handover.HostTaskHandover(c); self.coordinator.capture_initial()
        self.initial_runtime=c.runtime; self.old=c.checkpoint()
        self.release={'worker_joined':True,'worker_pid':c.worker.pid,'exit_code':0,'outcome':'task_completed',
            'execution_id':'task','native':{'owner_id':None,'release':None}}
        async def released(request,intent_valid,*,task_handover=False):
            self.assertTrue(task_handover); self.assertFalse(c.host._control_rebinding)
            await c.join_child(c.worker); return deepcopy(self.release)
        c.continuation_release=released
        c.assert_continuation_parked=lambda value:self.assertEqual(value,self.release)
        self.claims=[]; self.owners={}

    async def asyncTearDown(self):
        for claim in self.claims: claim.__exit__(None,None,None)
        if self.coordinator.claim is not None:
            self.coordinator.claim.__exit__(None,None,None); self.coordinator.claim=None
        for child in self.c.handles:
            if child.poll() is None: child.finish(0)
            await self.c.join_child(child)
        for episode in self.coordinator.episodes:
            facade=episode['facade']
            if facade is not None and facade._wake is not None: await facade._wake

    def request(self, request_id='new-one'):
        return {'request_id':request_id,'session_id':'session','host_epoch':'host','task_id':'task',
            'method':'new_task','execution_id':'task','execution_generation':0,
            'expected_task_revision':self.old.revision,'expected_selection_revision':0,
            'task_spec_path':str(self.spec_path),'task_spec_sha256':rec.digest(self.spec_path.read_bytes()),
            'task_inputs':str(self.inputs)}

    async def reserve(self):
        return await self.coordinator.select(self.initial_runtime,self.request(),lambda:True)

    def real_prepare(self, command, label):
        if 'prepare' not in command: raise AssertionError('Only preparation command expected')
        values=dict(zip(command[command.index('prepare')+1::2],command[command.index('prepare')+2::2]))
        args=SimpleNamespace(**{k[2:].replace('-','_'):v for k,v in values.items()},
            fixture=False,fixture_scenario='normal',validate_report_before_write=False)
        for name in ('run','profile','package_identity','task_spec','task_inputs','demand_identity'):
            setattr(args,name,Path(getattr(args,name)))
        base=SimpleNamespace(git=lambda *a:worker.SDK_REV if a[0]=='rev-parse' else '',config=lambda work:{'cwd':str(work)})
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(worker,'verify_execution_clock'))
            stack.enter_context(mock.patch.object(WindowsProfile,'load',return_value=self.c.profile))
            stack.enter_context(mock.patch.object(installation,'package_identity',return_value={'files':{}}))
            stack.enter_context(mock.patch.object(installation,'verify_interpreter',return_value=self.c.profile.worker_python))
            stack.enter_context(mock.patch.object(installation,'verify_sdk',return_value=self.c.profile.hermes_source))
            stack.enter_context(mock.patch.object(worker,'setup',return_value=(rec,base)))
            worker.prepare(args)
        child=Child(pid=42,code=0); self.c.handles.append(child); return child

    async def test_select_sqlite_preserves_predecessor_and_exact_source(self):
        grant=await self.reserve(); record=self.coordinator.records['new-one']
        self.assertEqual(grant['phase'],'reserved'); self.assertEqual(self.c.checkpoint(),self.old)
        self.assertTrue(self.initial_runtime._task_retired)
        self.assertEqual(await self.coordinator.lookup(self.initial_runtime,self.request()),grant)
        self.assertEqual(record['payload']['source']['task_spec_sha256'],self.request()['task_spec_sha256'])
        self.assertFalse(Path(record['payload']['run']).exists())
        altered=self.request(); altered['task_inputs']=str(self.root)
        with self.assertRaises(Refused): await self.coordinator.lookup(self.initial_runtime,altered)

    async def test_lost_reserve_reply_is_resolved_without_regrant_or_launch(self):
        original=handover.TaskAdmission.reserve
        def lost(*args,**kwargs): original(*args,**kwargs); raise OSError('lost return')
        with mock.patch.object(handover.TaskAdmission,'reserve',new=lost):
            with self.assertRaises(OSError): await self.reserve()
        record=self.coordinator.records['new-one']
        self.assertTrue(record['resolved']); self.assertIsNotNone(record['reservation'])
        self.assertEqual((await self.coordinator.lookup(self.initial_runtime,self.request()))['phase'],'blocked')
        self.assertFalse(record['started']); self.assertEqual(len(self.c.handles),1)

    async def test_real_prepare_cli_inherits_reserved_identity_and_new_session(self):
        await self.reserve(); record=self.coordinator.records['new-one']
        with mock.patch.object(self.c,'launch',side_effect=self.real_prepare): await self.coordinator.prepare_episode(record)
        cp=TaskStore(Path(record['payload']['run'])/'task.sqlite3').load(record['payload']['task_id'])
        self.assertEqual(cp.prompt,self.new_spec.prompt); self.assertEqual(cp.revision,0)
        self.assertEqual(cp.state['session_id'],record['payload']['session_id'])
        self.assertEqual(TaskSpec.from_metadata(cp.metadata),self.new_spec)
        self.assertEqual(cp.metadata[NAMESPACE],record['payload']['demand_identity'])
        self.assertNotEqual(cp.task_id,self.old.task_id); self.assertNotEqual(cp.state['session_id'],self.old.state['session_id'])
        self.assertEqual(self.c.checkpoint(),self.old); self.assertIs(self.c.runtime,self.initial_runtime)

    async def test_stop_after_reservation_abandons_without_preparation(self):
        await self.reserve(); record=self.coordinator.records['new-one']
        result=await self.coordinator.cooperative_stop()
        self.assertFalse(result['uncertain']); self.assertEqual(record['phase'],'abandoned')
        self.assertFalse(Path(record['payload']['run']).exists()); self.assertEqual(self.c.host.closes,1)
        self.assertEqual(await self.coordinator.cooperative_stop(),result); self.assertEqual(self.c.host.closes,1)

    async def test_stop_after_prepared_keeps_pristine_task_pending(self):
        await self.reserve(); record=self.coordinator.records['new-one']; record['started']=True
        with mock.patch.object(self.c,'launch',side_effect=self.real_prepare): await self.coordinator.prepare_episode(record)
        store=TaskStore(Path(record['payload']['run'])/'task.sqlite3'); before=store.load(record['payload']['task_id'])
        result=await self.coordinator.cooperative_stop()
        self.assertFalse(result['uncertain']); self.assertEqual(store.load(before.task_id),before)
        self.assertEqual(self.coordinator.authority.status()['admissions'][-1]['phase'],'stopped')

    async def test_failed_preparation_retained_not_old_safe_receipt(self):
        await self.reserve(); record=self.coordinator.records['new-one']; record['started']=True
        record['prepare_operation']=await self.coordinator.database(lambda:self.coordinator.authority.begin(
            self.coordinator.owner,record['reservation'],action='prepare'))
        with self.assertRaisesRegex(RuntimeError,'preparation outcome'): await self.coordinator.cooperative_stop()
        self.assertFalse(self.c.host.closed); self.assertIsNotNone(self.coordinator.owner.checkpoint.operation)

    async def test_old_callbacks_do_not_deactivate_new_task_intent(self):
        old=self.initial_runtime; binding=UIBinding('host','new-session','new-task',102,203,304)
        self.c.gate.bind(self.c.intent_cap,binding)
        self.c.gate.activate(self.c.intent_cap,session_id='new-session',task_id='new-task')
        revision=self.c.gate._revision; active=self.c.gate._active
        old.retire_task(); await old.refresh(); old.deactivate_intent(); old.window_closed('session')
        self.assertEqual(self.c.gate._revision,revision); self.assertEqual(self.c.gate._active,active)
        with self.assertRaises(Refused): await old.submit_control('old-resume','resume')
        self.assertFalse(await old.resume_authority('old-resume'))
        with self.assertRaises(Refused): await old.continue_selected({},intent_valid=lambda:True)
        with self.assertRaises(Refused): await old.lookup_continuation({})

    async def test_old_read_error_does_not_clear_new_intent_but_service_stop_does(self):
        old=self.initial_runtime; binding=UIBinding('host','new-session','new-task',102,203,304)
        self.c.gate.bind(self.c.intent_cap,binding)
        self.c.gate.activate(self.c.intent_cap,session_id='new-session',task_id='new-task')
        revision=self.c.gate._revision
        with mock.patch.object(old,'_observe',side_effect=OSError('database failure')):
            with self.assertRaises(OSError): await old.refresh()
        await asyncio.sleep(0)
        self.assertEqual(self.c.gate._revision,revision); self.assertIsNotNone(self.c.gate._active)
        self.coordinator.fence(); self.assertIsNone(self.c.gate._active)

    async def test_changed_source_refuses_before_prepare(self):
        request=self.request(); self.spec_path.write_text('{}')
        with self.assertRaises(ValueError): await self.coordinator.select(self.initial_runtime,request,lambda:True)
        self.assertEqual(self.c.checkpoint(),self.old); self.assertEqual(len(self.c.handles),1)

    async def test_old_read_joins_without_global_rebind_latch(self):
        entered,release=threading.Event(),threading.Event(); observe=self.initial_runtime._observe
        def slow(*args): entered.set(); release.wait(3); return observe(*args)
        with mock.patch.object(self.initial_runtime,'_observe',side_effect=slow):
            refresh=asyncio.create_task(self.initial_runtime.refresh()); await asyncio.to_thread(entered.wait,2)
            select=asyncio.create_task(self.reserve()); await asyncio.sleep(.02)
            self.assertFalse(select.done()); self.assertFalse(self.c.host._control_rebinding)
            release.set(); await refresh; await select

    def paused_worker(self, command, label):
        if 'prepare' in command:
            return self.real_prepare(command,label)
        run=Path(command[command.index('--run')+1])
        deadline=float(command[command.index('--deadline-monotonic')+1])
        plan=json.loads((run/'plan.json').read_text(encoding='utf-8'))
        store=TaskStore(run/'task.sqlite3'); identity=DemandIdentity(**plan['demand_identity'])
        registry=DemandRegistry((Registration(store,identity),)); cap=object()
        mailbox=Mailbox(registry,identity.registration_id,requester_capability=cap)
        claim=store.claim(identity.task_id,expected_revision=store.load(identity.task_id).revision)
        owned=claim.__enter__(); self.claims.append(claim)
        self.owners[identity.task_id]=(owned,claim)
        state=deepcopy(owned.checkpoint.state); state['deadline_monotonic']=deadline
        owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        mailbox.consume(owned,updated_at_utc=UTC)
        child=Child(pid=43); self.c.handles.append(child); return child

    async def test_real_prepare_paused_bootstrap_atomic_rebind_and_new_gate(self):
        grant=await self.reserve(); record=self.coordinator.records['new-one']
        old_runtime=self.initial_runtime; old_box=self.c.box
        original_start=Window.start
        async def window_start(gui,*args,**kwargs):
            await original_start(gui,*args,**kwargs)
            runtime=record['episode']['runtime']; transport=record['episode']['transport']
            self.assertTrue(runtime.window_ready(gui.binding.session_id)); transport._ready=True
        with mock.patch.object(self.c,'launch',side_effect=self.paused_worker), \
                mock.patch('adaptive_inference.desktop.gui_launch.OwnedUILaunch',Window), \
                mock.patch.object(Window,'start',new=window_start), \
                mock.patch.object(handover,'SerialListener',Listener):
            result=await self.coordinator.open(old_runtime,grant,lambda:True)
        self.assertEqual(result['phase'],'opened'); self.assertEqual(self.coordinator.selection_revision,1)
        self.assertEqual(self.c.runtime.selected_execution(),{'execution_id':result['task_id'],'execution_generation':0})
        self.assertEqual(old_runtime.prepared.task_id,'task'); self.assertEqual(self.c.runtime.prepared.objective,self.new_spec.prompt)
        cp=self.c.box.snapshot().target
        self.assertEqual(cp.state[NAMESPACE]['state'],'paused'); self.assertEqual(cp.state['requests'],0)
        self.assertEqual([r['command'] for r in self.c.box.snapshot().requests],['pause'])
        self.assertIsNone(self.c.gate._active); self.assertEqual(len(self.coordinator.episodes),2)
        revision=self.c.gate._revision; old_runtime.window_closed('session'); await old_runtime.refresh()
        self.assertEqual(self.c.gate._revision,revision)
        before=len(self.c.handles)
        self.assertEqual(await self.coordinator.lookup(old_runtime,self.request()),result)
        self.assertEqual(len(self.c.handles),before)

    async def open_grant(self, runtime, grant):
        original_start=Window.start
        async def start(gui,*args,**kwargs):
            await original_start(gui,*args,**kwargs)
            self.assertTrue(self.c.runtime.window_ready(gui.binding.session_id)); self.c.transport._ready=True
        # The protocol component separately tests the authenticated wire path;
        # this exact record is its private handoff to retire_task.
        transport=self.c.transport
        if not isinstance(transport,Endpoint):
            record={'command':'new_task','grant':grant,'task':None,'outcome':'pending'}
            transport._records[grant['request_id']]=record; transport._opening=record
        with mock.patch.object(self.c,'launch',side_effect=self.paused_worker), \
                mock.patch('adaptive_inference.desktop.gui_launch.OwnedUILaunch',Window), \
                mock.patch.object(Window,'start',new=start), mock.patch.object(handover,'SerialListener',Listener):
            result=await self.coordinator.open(runtime,grant,lambda:True)
        if not isinstance(transport,Endpoint):
            record['outcome']='known'; transport._opening=None
        return result

    def complete_current(self):
        c=self.c; owned,claim=self.owners[c.runtime.prepared.task_id]
        c.registry.transition(c.identity.registration_id,owned,'fulfilled',
            expected_revision=owned.checkpoint.revision,updated_at_utc=UTC,reason='CPU fixture completed answer')
        state=deepcopy(owned.checkpoint.state); state['status']='accepted'; state['output']='Completed fixture answer.'
        owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        claim.__exit__(None,None,None); self.claims.remove(claim); c.worker.finish(0)
        self.release['execution_id']=c.runtime.prepared.task_id
        self.release['worker_pid']=c.worker.pid

    async def test_two_new_tasks_same_host_and_global_stop_preserve_all_episodes(self):
        host,gateway=self.c.host,self.c.host.gateway
        grant=await self.reserve(); await self.open_grant(self.initial_runtime,grant)
        first_new=self.c.runtime; self.complete_current(); await first_new.refresh()
        request=self.request('new-two')
        request.update(task_id=first_new.prepared.task_id,session_id=self.c.gui.binding.session_id,
            execution_id=first_new.prepared.task_id,expected_task_revision=self.c.checkpoint().revision,
            expected_selection_revision=1)
        grant=await self.coordinator.select(first_new,request,lambda:True)
        await self.open_grant(first_new,grant)
        self.assertIs(self.c.host,host); self.assertIs(self.c.host.gateway,gateway)
        self.assertEqual(self.coordinator.selection_revision,2); self.assertEqual(len(self.coordinator.episodes),3)
        self.assertNotEqual(self.c.runtime.prepared.task_id,first_new.prepared.task_id)
        self.assertEqual(self.c.box.snapshot().demand['state'],'paused')
        self.complete_current()
        # Inject only native/agent exit verification. All actual task admission,
        # mailbox, ownership, claims, lifecycle joins and host ordering run.
        with mock.patch.object(handover.WorkerStopBinding,'_verify_exit',return_value='task_completed'):
            result=await self.coordinator.cooperative_stop()
            await asyncio.gather(*(e['transport']._stop_task for e in self.coordinator.episodes
                if e['transport'] is not None and e['transport']._stop_task is not None))
        self.assertFalse(result['uncertain']); self.assertEqual(host.closes,1)
        self.assertTrue(all(e['facade']._worker_safe() and e['facade']._gui_safe() for e in self.coordinator.episodes))
        self.assertEqual(self.coordinator.authority.status()['admissions'][-1]['phase'],'stopped')
        self.assertEqual(self.coordinator.authority.status()['admissions'][0]['phase'],'released')

    async def test_stopping_projection_remains_available_without_new_admission(self):
        self.coordinator.fence()
        self.initial_runtime._clock=lambda:time.monotonic()+100
        self.assertEqual(self.initial_runtime.status()['waiting_reason'],'stop_requested')
        with self.assertRaises(Exception): await self.initial_runtime.submit_control('late-resume','resume')

    async def test_stop_waits_for_inflight_preparation_then_preserves_unlaunched_task(self):
        grant=await self.reserve(); entered,release=asyncio.Event(),asyncio.Event()
        prepare=self.coordinator.prepare_episode
        async def paused(record):
            entered.set(); await release.wait(); await prepare(record)
        with mock.patch.object(self.coordinator,'prepare_episode',side_effect=paused), \
                mock.patch.object(self.c,'launch',side_effect=self.real_prepare):
            opening=asyncio.create_task(self.coordinator.adapter(self.initial_runtime).open_selected_task(grant,intent_valid=lambda:True))
            await entered.wait(); stopping=asyncio.create_task(self.coordinator.cooperative_stop())
            await asyncio.sleep(.02); self.assertFalse(stopping.done()); self.assertEqual(self.c.host.closes,0)
            release.set()
            self.assertEqual((await asyncio.wait_for(opening,3))['phase'],'blocked')
            result=await asyncio.wait_for(stopping,3)
        self.assertFalse(result['uncertain']); self.assertEqual(len(self.c.handles),2)
        self.assertEqual(self.coordinator.authority.status()['admissions'][-1]['phase'],'stopped')

    async def test_lost_handback_return_does_not_replay_finish_or_poison_later_stop(self):
        grant=await self.reserve(); await self.open_grant(self.initial_runtime,grant)
        runtime=self.c.runtime; self.complete_current(); await runtime.refresh()
        request=self.request('new-two'); request.update(task_id=runtime.prepared.task_id,
            session_id=self.c.gui.binding.session_id,execution_id=runtime.prepared.task_id,
            expected_task_revision=self.c.checkpoint().revision,expected_selection_revision=1)
        original=handover.TaskAdmission.finish
        def lost(*args,**kwargs): original(*args,**kwargs); raise OSError('handback return lost')
        with mock.patch.object(handover.TaskAdmission,'finish',new=lost):
            with self.assertRaises(OSError): await self.coordinator.select(runtime,request,lambda:True)
        self.assertIsNone(self.coordinator.active_record)
        self.assertEqual(self.coordinator.authority.status()['admissions'][-1]['phase'],'released')
        self.assertEqual(len(self.coordinator.episodes),2)
        with mock.patch.object(handover.WorkerStopBinding,'_verify_exit',return_value='task_completed'):
            result=await self.coordinator.cooperative_stop()
            await asyncio.gather(*(e['transport']._stop_task for e in self.coordinator.episodes
                if e['transport'] is not None and e['transport']._stop_task is not None))
        self.assertFalse(result['uncertain']); self.assertEqual(self.c.host.closes,1)

    async def test_old_runtime_failure_is_retained_after_all_episode_joins(self):
        grant=await self.reserve(); await self.open_grant(self.initial_runtime,grant)
        self.complete_current()
        self.initial_runtime._faults.add('database_operation_failed')
        with mock.patch.object(handover.WorkerStopBinding,'_verify_exit',return_value='task_completed'):
            with self.assertRaisesRegex(RuntimeError,'runtime operation failed'):
                await self.coordinator.cooperative_stop()
            await asyncio.gather(*(e['transport']._stop_task for e in self.coordinator.episodes
                if e['transport'] is not None and e['transport']._stop_task is not None))
        self.assertEqual(self.c.host.closes,0)
        self.assertTrue(all(e['facade']._worker_safe() and e['facade']._gui_safe() for e in self.coordinator.episodes))
        self.assertIsNone(self.coordinator._receipt)
        with mock.patch.object(handover.WorkerStopBinding,'_verify_exit',return_value='task_completed'):
            await self.coordinator.failure_cleanup()
        self.assertEqual(self.c.host.closes,1)
        self.assertTrue(self.c.listener.closed)
        self.assertTrue(self.coordinator.authority.status()['requires_reconciliation'])
        self.assertFalse(self.c.result['task_handover_failure_cleanup']['product_stop_confirmed'])

    async def test_intentional_gui_start_abort_requires_exact_reason_and_full_join(self):
        from adaptive_inference.desktop.gui_launch import StartupError
        facade=self.c.facade; gui=self.c.gui
        facade._gui_stop_aborted=True
        gui.primary_error=StartupError('Startup was fenced before session binding'); gui.cleanup_error=None
        facade.gui_receipt={**gui.result,'startup_aborted':True,'faults':['startup_failed']}
        self.assertTrue(facade._gui_safe())
        facade.gui_receipt['pipe_handles_closed']=False; self.assertFalse(facade._gui_safe())
        facade.gui_receipt['pipe_handles_closed']=True; gui.primary_error=StartupError('Unrelated failure')
        self.assertFalse(facade._gui_safe())

    async def test_final_cleanup_accepts_only_scoped_stop_abort_keeps_original_fault(self):
        from adaptive_inference.desktop.gui_launch import StartupError
        c=self.c; facade=c.facade; gui=c.gui
        facade._gui_stop_aborted=True
        gui.primary_error=StartupError('Startup was fenced before session binding'); gui.cleanup_error=None
        gui.result.update(startup_aborted=True,faults=['startup_failed'])
        await self.coordinator.cooperative_stop()
        c.stop_binding._verify_exit=lambda code:'task_completed'
        c.job.active_process_ids=lambda:{os.getpid()}
        episode=self.coordinator.current
        episode.update(gui_cleanup=deepcopy(facade.gui_receipt),listener_cleanup={'clean_close':True},
                       transport_cleanup={'closed':True})
        c.result.update(retained_obligations_joined=True,gui_cleanup=episode['gui_cleanup'],
            listener_cleanup=episode['listener_cleanup'],transport_cleanup=episode['transport_cleanup'])
        with mock.patch('adaptive_inference.desktop.composition.package_identity'):
            c.validate_cleanup()
            gui.primary_error=StartupError('unrelated error')
            with self.assertRaises(RuntimeError):c.validate_cleanup()
        self.assertEqual(c.result['gui_cleanup']['faults'],['startup_failed'])

    async def test_stop_after_child_bootstrap_before_gui_joins_exact_new_binding(self):
        grant=await self.reserve(); record=self.coordinator.records['new-one']
        database=self.coordinator.database
        async def stop_on_paused_read(function):
            result=await database(function)
            if function.__name__=='paused':
                self.coordinator.fence()
                identity=record['episode']['identity']
                owned,claim=self.owners[identity.task_id]
                claim.__exit__(None,None,None); self.claims.remove(claim)
                record['child'].finish(4)
            return result
        with mock.patch.object(self.c,'launch',side_effect=self.paused_worker), \
                mock.patch.object(self.coordinator,'database',side_effect=stop_on_paused_read):
            reply=await self.coordinator.open(self.initial_runtime,grant,lambda:True)
        self.assertEqual(reply['phase'],'blocked'); self.assertIs(self.c.runtime,self.initial_runtime)
        self.assertIsNone(record['episode']['gui']._start_task)
        with mock.patch.object(handover.WorkerStopBinding,'_verify_exit',return_value='service_stopped'):
            result=await self.coordinator.cooperative_stop()
        self.assertFalse(result['uncertain'])
        # The existing Stop binding joins, then the composition verifies its own
        # retained Popen ledger. Both waits target this exact object.
        self.assertEqual(record['child'].waits,2); self.assertTrue(self.c.waits[record['child']].done())
        self.assertEqual(record['episode']['store'].load(record['episode']['identity'].task_id).state['status'],'pending')


class FailureFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_old_gui_retains_itself_without_starving_new_episode(self):
        calls=[]; repeated=asyncio.Event(); release=asyncio.Event()
        class Binding:
            def __init__(self,name):
                self.name=name; self._capability=object(); self.worker=SimpleNamespace(poll=lambda:0)
            def request_stop(self,cap):
                self.assertion=cap is self._capability
                if not self.assertion:raise AssertionError('Wrong retained capability')
                calls.append('stop-'+self.name)
        class View:
            _start_task=None; _bound=True
            def __init__(self,name): self.name=name; self.count=0
            async def join(self,timeout_s=2):
                self.count+=1
                if self.name=='A' and self.count==2:repeated.set()
                calls.append('gui-'+self.name)
                return {'pending_pipe_operations':0,'pipe_handles_closed':True,'process_handle_closed':True,
                    'verifier_handle_closed':self.name=='B' or release.is_set(),
                    'child_retained':True,'child_exit_observed':True}
        second=Binding('B'); composition=SimpleNamespace(stop_binding=second,handles=[],host=None,result={})
        owner=handover.HostTaskHandover(composition)
        old,new=Listener(None),Listener(None)
        owner.episodes=[{'stop_binding':Binding('A'),'gui':View('A'),'listener':old,'transport':None,'runtime':None},
                        {'stop_binding':second,'gui':View('B'),'listener':new,'transport':None,'runtime':None}]
        owner.current=owner.episodes[1]; owner.fence=lambda:None
        cleanup=asyncio.create_task(owner.failure_cleanup())
        try:
            await asyncio.wait_for(repeated.wait(),1)
            self.assertIn('stop-B',calls); self.assertIn('gui-B',calls); self.assertTrue(new.closed)
            self.assertFalse(old.closed); self.assertFalse(cleanup.done()); self.assertIsNone(owner._receipt)
            self.assertTrue(owner._failure_drains); self.assertNotIn('task_handover_failure_cleanup',composition.result)
        finally:
            release.set(); await asyncio.wait_for(cleanup,2)
        self.assertTrue(old.closed); self.assertTrue(all(task.done() for task in owner._failure_drains))
        self.assertFalse(composition.result['task_handover_failure_cleanup']['product_stop_confirmed'])
