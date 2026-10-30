# SPDX-License-Identifier: Apache-2.0
"""Explicit same-host task handover using TaskAdmission and retained lifecycles.

Task/session/GUI identities are never rewritten. The existing prepare command,
paused worker bootstrap, TaskStore claim and cooperative Stop own every effect.
No task is queued or resumed automatically. See docs/task-spec.md and the Python
3.11 asyncio shielding guidance: retaining a task is separate from joining it.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import secrets
import uuid

from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.execution_clock import CLOCK_ID, execution_now
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.task_store import TaskStore
from adaptive_inference.desktop.control_transport import PreparedTask, ControlTransport, Refused, credential
from adaptive_inference.desktop.desktop_controls import DesktopControlLifecycle
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.serial_listener import SerialListener
from adaptive_inference.desktop.task_admission import TaskAdmission, MAX_ADMISSIONS
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.run_recovery import MODEL, QUALITY
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding


EPISODE_FIELDS = ('work','plan','store','identity','registry','capability','box','original',
    'deadline','first_ready','worker','worker_cap','stop_binding','stop_id','gui','facade',
    'runtime','continuation','transport','transport_cap','listener','task_spec_path',
    'task_spec_sha256','task_inputs','worker_exit_verified')


class TaskHandoverAdapter:
    """One immutable endpoint's view of the shared host coordinator."""
    def __init__(self, coordinator, runtime):
        self.coordinator, self.runtime = coordinator, runtime

    def projection(self):
        return self.coordinator.projection(self.runtime)

    async def select_task(self, payload, *, intent_valid):
        return await self.coordinator.retain(
            lambda: self.coordinator.select(self.runtime, payload, intent_valid))

    async def open_selected_task(self, grant, *, intent_valid):
        return await self.coordinator.retain(
            lambda: self.coordinator.open(self.runtime, grant, intent_valid))

    async def lookup_task(self, payload):
        return await self.coordinator.lookup(self.runtime, payload)


class HostTaskHandover:
    def __init__(self, composition):
        self.composition = composition
        self.records, self.episodes, self.tasks = {}, [], set()
        self.current = self.active_record = None
        self.authority = self.owner = self.claim = None
        self.selection_revision = 0
        self.transitioning = self.stopping = False
        self._stop = self._receipt = None
        self._fencing = False
        self._serial = asyncio.Lock()
        self._database_serial = asyncio.Lock()
        self._database_tasks = set()
        self._failure_drains = []

    def adapter(self, runtime):
        return TaskHandoverAdapter(self, runtime)

    def capture_initial(self):
        if self.episodes:
            raise RuntimeError('Initial episode already retained')
        c = self.composition
        self.current = {name: getattr(c, name) for name in EPISODE_FIELDS}
        self.current['facade'].service = self
        self.episodes.append(self.current)

    def episode(self, runtime):
        for episode in self.episodes:
            if episode['runtime'] is runtime:
                return episode
        raise Refused('task_blocked')

    def live(self, runtime, intent_valid):
        c = self.composition
        return (not self.stopping and not c.host.closing and not c.host.closed
                and not runtime._stopping and intent_valid() is True)

    def projection(self, runtime):
        phase, request_id = 'unavailable', None
        rows = [r for r in self.records.values() if r['runtime'] is runtime]
        if rows:
            record = rows[-1]
            phase, request_id = record['phase'], record['request']['request_id']
        elif (self.current is not None and runtime is self.current['runtime']
                and not self.stopping and not self.transitioning
                and self.selection_revision < MAX_ADMISSIONS):
            try:
                value = runtime.status()
                if value['task_status'] == 'accepted' or value['demand'] == 'cancelled':
                    phase = 'available'
            except Exception:
                pass  # No fresh status means no new admission.
        return {'phase': phase, 'request_id': request_id,
                'selection_revision': self.selection_revision}

    def reply(self, record):
        grant = record['reservation']
        if grant is None:
            return None
        return {'request_id': record['request']['request_id'],
                'predecessor_task_id': record['runtime'].prepared.task_id,
                'task_id': grant['payload']['task_id'],
                'selection_revision': grant['selection_revision'], 'phase': record['phase']}

    async def retain(self, operation):
        task = asyncio.create_task(operation())
        self.tasks.add(task)
        def done(value):
            if not value.cancelled():
                value.exception()
            self.tasks.discard(value)
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def database(self, function):
        async def run():
            async with self._database_serial:
                return await asyncio.to_thread(function)
        task = asyncio.create_task(run())
        self._database_tasks.add(task)
        task.add_done_callback(self._database_tasks.discard)
        return await asyncio.shield(task)

    async def drain(self, runtime):
        while runtime._pending or runtime._continuation_tasks:
            values = tuple(runtime._pending | runtime._continuation_tasks)
            await asyncio.gather(*(asyncio.shield(task) for task in values))
            await asyncio.sleep(0)

    def _authority(self):
        if self.authority is not None:
            return
        c = self.composition
        directory = c.root/'tasks'
        directory.mkdir(exist_ok=False)
        authority = TaskAdmission(TaskStore(c.root/'admission.sqlite3'),
            host_generation=c.host_epoch, tasks_root=directory,
            initial_task_id=self.current['runtime'].prepared.task_id,
            initial_run=self.current['work'])
        self.authority = authority
        checkpoint = authority.store.load(authority.task_id)
        self.claim = authority.store.claim(authority.task_id,
            expected_revision=checkpoint.revision, owner_id=c.host_epoch)
        self.owner = self.claim.__enter__()

    async def lookup(self, runtime, request):
        record = self.records.get(request['request_id'])
        if record is None:
            return None
        if record['runtime'] is not runtime or record['request'] != request:
            raise Refused('conflicting_request_id')
        if record['payload'] is not None:
            grant = await self.database(lambda: self.authority.lookup(record['payload']))
            if record['reservation'] is not None and grant != record['reservation']:
                raise RuntimeError('Historical task reservation changed')
            if grant is not None:
                record['reservation'] = grant
            record['resolved'] = True
        return self.reply(record)

    async def select(self, runtime, request, intent_valid):
        async with self._serial:
            if request['request_id'] in self.records:
                return await self.lookup(runtime, request)
            if (self.current is None or runtime is not self.current['runtime']
                    or self.transitioning or not self.live(runtime, intent_valid)
                    or len(self.records) >= MAX_ADMISSIONS):
                raise Refused('task_blocked')
            runtime._require_execution({key: request[key] for key in ('execution_id','execution_generation')})
            await runtime.refresh()
            status = runtime.status()
            if (status['task_revision'] != request['expected_task_revision']
                    or request['expected_selection_revision'] != self.selection_revision
                    or not (status['task_status'] == 'accepted' or status['demand'] == 'cancelled')):
                raise Refused('task_unavailable')
            c = self.composition
            self.current.update({name: getattr(c, name) for name in EPISODE_FIELDS})
            record = {'runtime': runtime, 'request': deepcopy(request), 'payload': None,
                'reservation': None, 'resolved': True, 'phase': 'reserved',
                'prepared': False, 'started': False, 'launch_attempted': False,
                'prepare_child': None, 'child': None, 'episode': None,
                'prepare_operation': None, 'launch_operation': None, 'release': None}
            self.records[request['request_id']] = record
            self.transitioning = True
            runtime.retire_task()
            try:
                await self.drain(runtime)
                if not self.live(runtime, intent_valid):
                    raise Refused('task_blocked')
                # Leave the normal demand observer active until real parking.
                record['release'] = await c.continuation_release(request, intent_valid, task_handover=True)
                if not self.live(runtime, intent_valid):
                    raise Refused('task_blocked')
                def reserve():
                    self._authority()
                    from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
                    if type(c.stop_binding) is SelectedWorkerStopBinding:
                        self.authority.retain_execution_binding(c.stop_binding)
                    if self.active_record is not None:
                        old = self.active_record
                        try:
                            self.authority.finish(self.owner, old['reservation'],
                                execution_id=request['execution_id'], task_revision=request['expected_task_revision'],
                                cleanup_sha256=rec.digest(record['release']), operation_id=old['launch_operation'])
                        except BaseException:
                            # A committed handback can lose its return. Observe
                            # that exact row only; never repeat finish or reserve.
                            status = self.authority.status()
                            rows = [row for row in status['admissions'] if row['reservation']==old['reservation']]
                            if (len(rows)==1 and rows[0]['phase']=='released'
                                    and rows[0]['release']['execution_id']==request['execution_id']
                                    and rows[0]['release']['revision']==request['expected_task_revision']
                                    and rows[0]['release']['cleanup_sha256']==rec.digest(record['release'])
                                    and status['operation'] is None and not status['requires_reconciliation']):
                                old['released'] = True
                                self.active_record = None
                            raise
                        old['released'] = True
                        self.active_record = None
                    source = {key: request[key] for key in ('task_spec_path','task_spec_sha256','task_inputs')}
                    spec = TaskSpec.read(source['task_spec_path'], source['task_spec_sha256'])
                    spec.verify_inputs(Path(source['task_inputs']))
                    payload = self.authority.request(command_id=request['request_id'],
                        expected_selection_revision=request['expected_selection_revision'],
                        predecessor_execution_id=request['execution_id'],
                        predecessor_revision=request['expected_task_revision'], spec=spec,
                        arrived_at_utc=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), source=source)
                    record['payload'], record['resolved'] = payload, False
                    return self.authority.reserve(self.owner, payload,
                        predecessor_cleanup_sha256=rec.digest(record['release']))
                grant = await self.database(reserve)
                record['reservation'], record['resolved'] = grant, True
                return self.reply(record)
            except BaseException:
                record['phase'] = 'blocked'
                if record['payload'] is not None and not record['resolved']:
                    try:
                        await self.lookup(runtime, request)
                    except Exception:
                        pass
                raise
            finally:
                # The durable reservation remains a Stop obligation between
                # select and open. No child is inferred from a missing record.
                if record['reservation'] is None:
                    self.transitioning = False

    async def open(self, runtime, reply, intent_valid):
        record = self.records.get(reply['request_id'])
        if record is None or record['runtime'] is not runtime or self.reply(record) != reply:
            raise Refused('task_blocked')
        if record['started']:
            return self.reply(record)
        record['started'] = True
        try:
            if not self.live(runtime, intent_valid):
                record['phase'] = 'blocked'; return self.reply(record)
            record['phase'] = 'preparing'
            await self.prepare_episode(record)
            if not self.live(runtime, intent_valid):
                record['phase'] = 'blocked'; return self.reply(record)
            await self.launch_episode(record)
            if not self.live(runtime, intent_valid):
                record['phase'] = 'blocked'; return self.reply(record)
            c, episode = self.composition, record['episode']
            # Retire the old endpoint before B can bind the shared intent gate.
            self.current['transport'].retire_task(self.current['transport_cap'], reply['request_id'])
            c.host._control_rebinding = True
            try:
                await self.drain(runtime)
                controller = c.host.controller
                async with controller.lock:
                    async with controller._demand_lock:
                        record['observation'] = await episode['runtime']._database(
                            episode['runtime']._observe, lambda value: value)
                        if not self.live(runtime, intent_valid):
                            record['phase'] = 'blocked'; return self.reply(record)
                        c.host.commit_task_runtime(runtime, episode['runtime'], record, self)
            finally:
                c.host._control_rebinding = False
            await self.open_view(record)
            if not self.live(runtime, intent_valid):
                record['phase'] = 'blocked'; return self.reply(record)
            record['phase'] = 'opened'
            return self.reply(record)
        except BaseException as error:
            record['phase'] = 'blocked'
            episode = record['episode']
            if (self.stopping and episode is not None and episode['facade'] is not None
                    and episode['facade']._gui_stop_aborted
                    and error is episode['gui'].primary_error):
                return self.reply(record)  # Cleanup still checks the exact abort reason and joins.
            raise
        finally:
            self.transitioning = False

    async def _until(self, predicate, child, seconds, *, deadline=None):
        limit = min(execution_now()+seconds, float('inf') if deadline is None else deadline)
        while True:
            value = predicate()
            if value:
                return value
            if child is not None and child.poll() is not None:
                raise RuntimeError('Retained task child exited before its required boundary')
            if execution_now() >= limit:
                raise TimeoutError('Task handover phase deadline')
            await asyncio.sleep(.05)

    async def prepare_episode(self, record):
        c, grant = self.composition, record['reservation']
        payload = grant['payload']; source = payload['source']
        record['prepare_operation'] = await self.database(
            lambda: self.authority.begin(self.owner, grant, action='prepare'))
        identity_path = c.root/('task-demand-'+grant['payload_sha256'][:24]+'.json')
        await self.database(lambda: rec.save(identity_path, {key:payload['demand_identity'][key]
            for key in ('registration_id','task_id','owner_id','arrived_at_utc')}))
        command = [str(c.profile.worker_python), '-I', '-B', '-m',
            'adaptive_inference.desktop.hermes.run_recovery', 'prepare', '--run', payload['run'],
            '--profile', str(c.profile_path), '--profile-sha256', c.profile_sha256,
            '--package-identity', str(c.root/'installed-package.private.json'), '--control-case', 'complete',
            '--task-spec', source['task_spec_path'], '--task-spec-sha256', source['task_spec_sha256'],
            '--task-inputs', source['task_inputs'], '--task-id', payload['task_id'],
            '--session-id', payload['session_id'], '--demand-identity', str(identity_path),
            '--demand-identity-sha256', rec.digest(identity_path.read_bytes())]
        before = len(c.handles)
        try:
            c.launch(command, 'prepare-task-'+str(grant['selection_revision']))
        finally:
            if len(c.handles) == before+1:
                record['prepare_child'] = c.handles[-1]
        child = record['prepare_child']
        await self._until(lambda: child.poll() is not None, None, 60)
        if await c.join_child(child) != 0:
            raise RuntimeError('Fresh task preparation failed')
        await self.database(lambda: self.authority.prepared(self.owner, grant,
            operation_id=record['prepare_operation']))
        record['prepared'] = True
        self.selection_revision = grant['selection_revision']
        self.active_record = record

    async def launch_episode(self, record):
        c, grant = self.composition, record['reservation']
        payload = grant['payload']; work = Path(payload['run'])
        from adaptive_inference.desktop.composition import read, INITIAL_PAUSE, no_work
        from adaptive_inference.desktop.gui_launch import OwnedUILaunch
        from adaptive_inference.desktop.continuation_host import HostContinuation
        plan = await self.database(lambda: read(work/'plan.json'))
        store = TaskStore(work/'task.sqlite3')
        identity = DemandIdentity(**plan['demand_identity'])
        registry = DemandRegistry((Registration(store, identity),))
        capability = object(); mailbox = Mailbox(registry, identity.registration_id, requester_capability=capability)
        original = await self.database(lambda: store.load(identity.task_id))
        deadline = execution_now()+900
        episode = {'work':work,'plan':plan,'store':store,'identity':identity,'registry':registry,
            'capability':capability,'box':mailbox,'original':original,'deadline':deadline,
            'first_ready':work/'controller-ready-1.json','worker':None,'worker_cap':object(),
            'stop_binding':None,'stop_id':'task-stop-'+grant['payload_sha256'][:24],
            'gui':None,'facade':None,'runtime':None,'continuation':None,'transport':None,
            'transport_cap':object(),'listener':None,'worker_exit_verified':False,
            'task_spec_path':Path(payload['source']['task_spec_path']),
            'task_spec_sha256':payload['source']['task_spec_sha256'],
            'task_inputs':Path(payload['source']['task_inputs'])}
        record['episode'] = episode
        # Retain before any launch, diagnostics or binding may fail.
        self.episodes.append(episode)
        record['launch_operation'] = await self.database(lambda: self.authority.begin(self.owner, grant, action='launch'))
        await self.database(lambda: mailbox.submit(capability, INITIAL_PAUSE, 'pause'))
        command = [plan['base_python'],'-I','-B','-m','adaptive_inference.desktop.hermes.run_recovery',
            'worker','--run',str(work),'--controller-ready',str(episode['first_ready']),
            '--gateway-instance',c.host.gateway.instance,'--deadline-monotonic',str(deadline),
            '--stop-request-id',episode['stop_id']]
        record['launch_attempted'] = True
        before = len(c.handles)
        try:
            c.launch(command, 'worker-task-'+str(grant['selection_revision']))
        finally:
            if len(c.handles) == before+1:
                child = record['child'] = episode['worker'] = c.handles[-1]
                episode['stop_binding'] = WorkerStopBinding(child,work,mailbox,requester_capability=capability,
                    capability=episode['worker_cap'],stop_request_id=episode['stop_id'],original=original,
                    deadline_monotonic=deadline,model=MODEL,quality=QUALITY,fence=self.fence,deadline_clock=CLOCK_ID)
                episode['gui'] = OwnedUILaunch(api=c.launch_api)
                prepared = PreparedTask(c.host_epoch,identity.task_id,original.prompt)
                episode['facade'] = DesktopControlLifecycle(c.host,prepared,worker_stop=episode['stop_binding'],
                    worker_capability=episode['worker_cap'],gui=episode['gui'],shutdown_timeout_s=120)
                episode['facade'].service = self
                episode['facade']._gui_optional_unstarted = True
                runtime = episode['runtime'] = MailboxRuntime(prepared,mailbox,requester_capability=capability,
                    gate=c.gate,intent_capability=c.intent_cap,lifecycle=episode['facade'])
                episode['continuation'] = HostContinuation(c,runtime)
        if self.stopping:
            self.fence()
            return
        child = episode['worker']; handle = c.launch_api.handle(child)
        observed = c.launch_api.identity(handle)
        if (c.launch_api.in_job(handle,c.job._HANDLE) is not True
                or observed[0] != child.pid or child.poll() is not None):
            raise RuntimeError('New task child is not live in the retained containing job')
        record['retained_child_identity'] = {'pid':observed[0], 'creation_time_100ns':observed[1],
                                            'containing_job_verified':True}
        def paused():
            snapshot = mailbox.snapshot(); ack = snapshot.status(INITIAL_PAUSE)
            if not ack['owner_acknowledged']:
                return None
            if ack['outcome'] != 'applied' or snapshot.target.owner_epoch is None or child.poll() is not None:
                raise RuntimeError('New task lacks exact live paused owner ACK')
            no_work(snapshot.target,original,deadline,c.host,work,cold=False)
            c.assert_continuation_parked(record['release'])
            return {'checkpoint':asdict(snapshot.target),'ack':ack}
        # SQLite reads remain off the host event loop and bounded by this phase.
        limit = min(execution_now()+60,deadline)
        while True:
            if self.stopping:
                return
            value = await self.database(paused)
            if self.stopping:
                return
            if value:
                record['paused'] = value; break
            if child.poll() is not None or execution_now() >= limit:
                raise RuntimeError('New task paused bootstrap did not complete')
            await asyncio.sleep(.05)
        await runtime.refresh()

    def commit_episode(self, record):
        episode = record['episode']; c = self.composition
        if episode not in self.episodes or episode['runtime'] is not c.host.control_runtime:
            raise RuntimeError('New task episode is not the selected host runtime')
        self.current = episode
        for name in EPISODE_FIELDS:
            setattr(c,name,episode[name])
        record['rebound'] = True
        c.result['task_completed'] = c.result['execution_expired'] = False
        c.result.pop('worker_outcome',None)
        for name in ('semantic_validation','validated_artifacts','artifacts','task_spec_sha256'):
            c.result.pop(name,None)
        c.result['task_selection_revision'] = self.selection_revision

    async def open_view(self, record):
        from adaptive_inference.desktop.composition import HERE, no_work
        from adaptive_inference.desktop.gui_launch import LaunchSpec, CHILD_SOURCES
        from adaptive_inference.desktop.control_client import Bootstrap
        from adaptive_inference.desktop.installation import sha
        c, episode = self.composition, record['episode']
        runtime = episode['runtime']; prepared = runtime.prepared
        transport = episode['transport'] = ControlTransport(prepared,runtime,
            capability=episode['transport_cap'],runner_credential='local-no-key',
            cooperative_progress=c.progress,handover=self.adapter(runtime))
        listener = episode['listener'] = SerialListener(transport)
        # Reflect retained endpoint objects before the first fallible start.
        c.transport,c.listener,c.transport_cap = transport,listener,episode['transport_cap']
        endpoint = listener.start()
        bootstrap = Bootstrap(c.host_epoch,'session-'+uuid.uuid4().hex,prepared.task_id,prepared.objective,
            credential(),endpoint[0],endpoint[1],'AdaptiveInference.'+uuid.uuid4().hex,secrets.randbelow(2**31-1)+1)
        spec = LaunchSpec(c.profile.host_python,c.profile.host_python_sha256,HERE/'run_gui.py',
            tuple((name,sha(HERE.parent/name)) for name in sorted(CHILD_SOURCES)))
        def bind(binding, verifier, supplied):
            episode['facade'].bind_window(binding,verifier,supplied)
            transport.bind_session(episode['transport_cap'],binding.session_id,supplied.token)
            return True
        def launch_ready():
            c.assert_continuation_parked(record['release'])
            return not self.stopping and not c.host.closing and episode['worker'].poll() is None
        await episode['gui'].start(spec,bootstrap,containing_job=c.job._HANDLE,launch_ready=launch_ready,
            bind_session=bind,revoke_session=runtime.window_closed,timeout_s=10)
        await self._until(lambda: transport._ready or self.stopping,episode['worker'],30,deadline=episode['deadline'])
        if self.stopping:
            return
        snapshot = await runtime._database(runtime._observe,runtime._install)
        no_work(snapshot.target,episode['original'],episode['deadline'],c.host,episode['work'],cold=False)
        record['ready'] = {'paused_owner_acknowledged':True,'task_id':prepared.task_id,
            'selection_revision':self.selection_revision,'gui_binding':asdict(episode['gui'].binding)}

    def fence(self):
        self.stopping = True
        if self._fencing:
            return
        self._fencing = True
        c = self.composition
        try:
            c.gate.deactivate(c.intent_cap)
            for episode in self.episodes:
                runtime,facade = episode['runtime'],episode['facade']
                if runtime is not None:
                    runtime._stopping = True
                if facade is not None:
                    facade._fence_local()
                transport = episode['transport']
                if transport is not None and not transport.lifecycle()['stop_requested']:
                    transport._request_stop()
                gui = episode['gui']
                if gui is not None and gui._start_task is not None and not gui._bound:
                    if facade is not None and getattr(gui,'primary_error',None) is None:
                        facade._gui_stop_aborted = True
                    gui.abort_startup()
            if c.host is not None:
                c.host.closing = True
                c.host.gateway.scheduler.closing = True
        finally:
            self._fencing = False

    async def cooperative_stop(self):
        if self._stop is None:
            self.fence()
            self._stop = asyncio.create_task(self._finish_stop())
        return deepcopy(await asyncio.shield(self._stop))

    async def _finish_stop(self):
        c = self.composition
        errors = []
        while self.tasks or self._database_tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.tasks | self._database_tasks)),
                                 return_exceptions=True)
        if any(not row['resolved'] for row in self.records.values()):
            errors.append('Task reservation outcome remains unresolved')
        for episode in self.episodes:
            runtime = episode['runtime']
            if runtime is not None:
                await self.drain(runtime)
            transport = episode['transport']
            if transport is not None:
                await asyncio.gather(*(asyncio.shield(task) for task in
                    getattr(transport,'_mutation_tasks',lambda:())()),return_exceptions=True)
        # Staging/launch failures never borrow A's safe worker receipt.
        for record in self.records.values():
            if record['reservation'] is None:
                continue
            if record['prepare_operation'] is None and record['episode'] is None:
                await self.database(lambda r=record: self.authority.abandon(self.owner,r['reservation'],
                    cleanup_sha256=rec.digest(r['release'])))
                record['phase'] = 'abandoned'
            elif not record['prepared']:
                errors.append('Task preparation outcome remains unresolved')
        for episode in self.episodes:
            facade = episode['facade']
            if facade is None:
                binding = episode['stop_binding']
                if binding is not None:
                    binding.request_stop(episode['worker_cap'])
                    while not (await binding.join(timeout=2))['worker_joined']:
                        await asyncio.sleep(.05)
                errors.append('Task launch lacks a complete retained lifecycle')
                continue
            try:
                await facade._finish_stop(close_host=False)
                if not facade._worker_safe() or not facade._gui_safe() or facade._faults:
                    errors.append('A retained task/window did not confirm cooperative cleanup')
            except BaseException as error:
                errors.append(type(error).__name__)
        for child in c.handles:
            await c.join_child(child)
        errors.extend(self.episode_faults())
        if errors:
            raise RuntimeError('; '.join(errors))
        cleanup = await c.host.close(timeout_s=180)
        if (cleanup.get('closed') is not True or any(cleanup.get(k) is not None
                for k in ('primary_error','cleanup_error','controller_fault'))):
            raise RuntimeError('Shared native host cleanup is unconfirmed')
        c.result['cleanup'] = cleanup
        if self.active_record is not None:
            record = self.active_record
            episode = record['episode']
            binding = None if episode is None else (c.stop_binding if episode is self.current else episode['stop_binding'])
            continuation = None
            if episode is not None and episode['facade']._selected is not None and episode['facade']._selected['binding'] is None:
                binding,continuation = None,episode['continuation']
            arguments = {'cleanup_sha256':rec.digest(cleanup),'operation_id':record['launch_operation'],'binding':binding}
            if continuation is not None:
                arguments['continuation'] = continuation
            await self.database(lambda: self.authority.stop(self.owner,record['reservation'],**arguments))
        if self.claim is not None:
            await self.database(lambda: self.claim.__exit__(None,None,None))
            self.claim = self.owner = None
        self._receipt = {'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}
        for episode in self.episodes:
            episode['facade'].native_receipt = cleanup
        return self._receipt

    def episode_faults(self):
        errors = []
        for episode in self.episodes:
            runtime,transport = episode['runtime'],episode['transport']
            if runtime is not None:
                if runtime._faults or runtime._pending or runtime._continuation_tasks:
                    errors.append('Retained runtime operation failed or remains pending')
                continuation = runtime._continuation
                if continuation is not None and any(not row['authorization_resolved'] for row in continuation.records.values()):
                    errors.append('Retained continuation authorization is unresolved')
            if transport is not None:
                if getattr(transport,'_faults',None) or any(row['outcome']=='unknown'
                        for row in getattr(transport,'_records',{}).values()):
                    errors.append('Retained transport operation is unresolved')
                mutations = getattr(transport,'_mutation_tasks',lambda:())()
                if any(not task.done() for task in mutations):
                    errors.append('Retained transport mutation is pending')
        return errors

    async def dispose(self, failed):
        c = self.composition
        await self.cooperative_stop()
        # Per-view cleanup uses existing methods without changing current task
        # aliases. Old transports already share the same completed Stop owner.
        errors = []
        for episode in self.episodes:
            gui,listener,transport = episode['gui'],episode['listener'],episode['transport']
            if gui is not None:
                receipt = await gui.join(timeout_s=2)
                episode['gui_cleanup'] = receipt
            if listener is not None:
                value = await listener.aclose(timeout=2)
                while not value['resources_closed']:
                    value = await listener.aclose(timeout=2)
                episode['listener_cleanup'] = value
            if transport is not None:
                value = await transport.aclose(timeout=2)
                while not value['closed']:
                    value = await transport.aclose(timeout=2)
                episode['transport_cleanup'] = value
                errors.extend(await asyncio.gather(*(asyncio.shield(t) for t in
                    (transport._stop_task,transport._close_task) if t is not None),return_exceptions=True))
        for child in c.handles:
            await c.join_child(child)
        c.result['retained_obligations_joined'] = True
        if any(isinstance(value,BaseException) for value in errors):
            raise RuntimeError('Retained endpoint shutdown failed')
        if self.episode_faults() or any(not episode['transport'].lifecycle().get('stop_confirmed')
                for episode in self.episodes if episode['transport'] is not None):
            raise RuntimeError('A retained endpoint did not confirm shared Stop')
        for name in ('gui_cleanup','listener_cleanup','transport_cleanup'):
            c.result[name] = deepcopy(self.current[name])
        c.result['all_retained_process_exits'] = [{'pid':child.pid,'exit_code':child.poll()} for child in c.handles]
        c.result['task_episodes'] = [{'task_id':episode['runtime'].prepared.task_id,
            'gui_cleanup':episode['gui_cleanup'],'listener_cleanup':episode['listener_cleanup'],
            'transport_cleanup':episode['transport_cleanup']} for episode in self.episodes]

    async def failure_cleanup(self):
        """Join all retained episodes even when a sibling's proof failed.

        This is physical containment cleanup only. It cannot return a successful
        product Stop or reconcile an unknown admission operation.
        """
        self.fence()
        c = self.composition
        failures = []
        while self.tasks or self._database_tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.tasks | self._database_tasks)),
                                 return_exceptions=True)
        async def drain_worker(binding):
            while binding.worker.poll() is None:
                await binding.join(timeout=2)
            work = getattr(binding,'_work',None)
            if work is not None:
                await asyncio.shield(work)

        async def drain_view(episode):
            gui = episode['gui']
            if gui is not None:
                if gui._start_task is not None and not gui._bound:
                    gui.abort_startup()
                while True:
                    receipt = await gui.join(timeout_s=2)
                    if (receipt['pending_pipe_operations']==0 and receipt['pipe_handles_closed']
                            and receipt['process_handle_closed'] and receipt['verifier_handle_closed']
                            and (not receipt['child_retained'] or receipt['child_exit_observed'])):
                        episode['gui_cleanup'] = receipt
                        break
                    await asyncio.sleep(.05)
            listener,transport = episode['listener'],episode['transport']
            if listener is not None:
                listener.close()
            if transport is not None:
                while True:
                    receipt = await transport.aclose(timeout=2)
                    if receipt['handlers']==0 and receipt['pending_connections']==0 and transport._close_task.done():
                        break
            if listener is not None:
                while not (await listener.aclose(timeout=2))['resources_closed']:
                    await asyncio.sleep(.05)
            runtime = episode['runtime']
            if runtime is not None:
                await asyncio.gather(*(asyncio.shield(task) for task in
                    (*runtime._pending,*runtime._continuation_tasks,runtime._stop_task) if task is not None),
                    return_exceptions=True)
        # Start every retained obligation before awaiting an uncertain sibling.
        # A's unresolved GUI handle must not delay B's Stop, worker join, GUI
        # close or endpoint drain. These tasks remain owned even if this waiter
        # is cancelled; an unfinished drain never permits native close below.
        for episode in self.episodes:
            binding = c.stop_binding if episode is self.current else episode['stop_binding']
            if binding is not None:
                try:
                    binding.request_stop(binding._capability)
                    self._failure_drains.append(asyncio.create_task(drain_worker(binding)))
                except BaseException as error:
                    failures.append(type(error).__name__)
            self._failure_drains.append(asyncio.create_task(drain_view(episode)))
        self._failure_drains.extend(asyncio.create_task(c.join_child(child)) for child in c.handles)
        drained = await asyncio.gather(*(asyncio.shield(task) for task in self._failure_drains),
                                       return_exceptions=True)
        errors = [value for value in drained if isinstance(value,BaseException)]
        if errors:
            raise BaseExceptionGroup('Retained episode cleanup failed',errors)
        if c.host is not None:
            c.result['failure_cleanup'] = await c.host.close(timeout_s=180)
        if self.claim is not None:
            await self.database(lambda:self.claim.__exit__(None,None,None))
            self.claim = self.owner = None  # Existing unfinished-effect fence survives release.
        c.result['task_handover_failure_cleanup'] = {'episodes_joined':len(self.episodes),
            'failures':failures,'product_stop_confirmed':False}

    def validate_cleanup(self):
        if self._receipt != {'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}:
            raise RuntimeError('Shared host Stop is unconfirmed')
        if self.episode_faults():
            raise RuntimeError('Retained episode has unresolved operations')
        for episode in self.episodes:
            if (not episode['facade']._worker_safe() or not episode['facade']._gui_safe()
                    or not episode.get('listener_cleanup',{}).get('clean_close')
                    or not episode.get('transport_cleanup',{}).get('closed')):
                raise RuntimeError('A retained task episode is not cleanly closed')
