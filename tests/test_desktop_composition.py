"""Shared installed composition ownership/ordering fixtures, no GUI or model."""
import asyncio
from collections import deque
from copy import deepcopy
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

WORKTREE_SRC = r"D:\AI\Milestone-20261024-Handoff\pending-tool-recovery-work\src"
WORKTREE_TESTS = r"D:\AI\Milestone-20261024-Handoff\pending-tool-recovery-work\tests"
if os.path.isdir(WORKTREE_SRC) and WORKTREE_SRC not in sys.path:
    sys.path.append(WORKTREE_SRC)
if os.path.isdir(WORKTREE_TESTS) and WORKTREE_TESTS not in sys.path:
    sys.path.append(WORKTREE_TESTS)

from adaptive_inference.desktop import composition as q
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from test_desktop_installation import profile_value
from adaptive_inference.task_spec import TaskSpec, BUDGET


def custom_spec():
    return TaskSpec({'schema':'adaptive.task-spec.v1',
        'prompt':'Write a short welcome message to greeting.txt using write_file.',
        'inputs':[], 'outputs':[{'name':'greeting.txt','required':True,'format':'text','max_chars':500}],
        'budget':dict(BUDGET),'validation':{'validator':None}})


def make_case(root):
    profile=root/'profile.json';profile.write_text(json.dumps(profile_value(root)),encoding='utf-8')
    return q.DesktopComposition(profile,root/'run')


class Child:
    def __init__(self,pid=41,code=None):
        self.pid=pid;self.code=code;self.done=threading.Event();self.waits=0
        if code is not None:self.done.set()
    def poll(self):return self.code
    def wait(self):
        self.waits+=1
        if not self.done.wait(3):raise TimeoutError('Fixture child not released')
        return self.code
    def finish(self,code):self.code=code;self.done.set()
    def kill(self):raise AssertionError('No product kill')
    def terminate(self):raise AssertionError('No product terminate')


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.case=make_case(self.root);self.case.root.mkdir()

    async def test_noncanonical_parent_is_rejected_until_explicitly_resolved(self):
        nested=self.root/'nested';nested.mkdir()
        parent=nested/'..'
        with self.assertRaisesRegex(ValueError,'non-redirected parent'):
            q.DesktopComposition(self.case.profile_path,parent/'fresh-run')
        case=q.DesktopComposition(self.case.profile_path,parent.resolve()/'fresh-run')
        self.assertEqual(case.root,self.root/'fresh-run')
        self.assertFalse(case.root.exists())

    async def test_diagnostic_failure_still_retains_worker_and_log(self):
        c=self.case;child=Child()
        with mock.patch.object(q.subprocess,'Popen',return_value=child), \
                mock.patch.object(c,'event',side_effect=OSError('diagnostic failed')):
            with self.assertRaises(OSError):c.launch(['fixture'],'worker')
        self.assertIs(c.worker,child);self.assertEqual(c.handles,[child])
        self.assertEqual(len(c.logs),1)
        child.finish(2)
        self.assertEqual(await c.join_child(child),2)
        for stream in c.logs:stream.close()

    async def test_cancelled_wait_retains_exact_child_without_signal(self):
        c=self.case;child=Child();c.handles.append(child)
        task=asyncio.create_task(c.join_child(child));await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(c.waits[child].done())
        child.finish(0)
        self.assertEqual(await c.join_child(child),0)
        self.assertEqual(child.waits,1)

    async def test_reused_pid_cannot_borrow_another_retained_child_wait(self):
        c=self.case;old=Child(41,5);new=Child(41)
        c.handles.extend((old,new))
        self.assertEqual(await c.join_child(old),5)
        task=asyncio.create_task(c.join_child(new))
        try:
            await asyncio.sleep(.02);self.assertFalse(task.done())
            self.assertIsNot(c.waits[old],c.waits[new])
        finally:new.finish(0)
        self.assertEqual(await task,0);self.assertEqual(old.waits,1);self.assertEqual(new.waits,1)

    async def test_join_retained_collects_sibling_error_and_waits_other(self):
        release=asyncio.Event()
        async def fail():raise ValueError('fixture')
        async def pending():await release.wait();return 'joined'
        one=asyncio.create_task(fail());two=asyncio.create_task(pending())
        join=asyncio.create_task(q.join_retained([one,two,two]))
        await asyncio.sleep(.01);self.assertFalse(join.done())
        release.set();result=await join
        self.assertIsInstance(result[0],ValueError);self.assertEqual(result[1],'joined')

    async def test_initial_pause_checkpoint_is_unchanged_before_gui(self):
        c=self.case;c.work=c.root/'hermes-task';(c.work/'work').mkdir(parents=True)
        c.store=q.TaskStore(c.work/'task.sqlite3')
        c.identity=q.DemandIdentity('registration','orders-report','worker','2026-10-25T10:00:00Z')
        prepare_task(c.store,c.identity,q.PROMPT,'session',metadata={'model':q.MODEL,'quality':q.QUALITY,
                     'deadline_clock':q.CLOCK_ID})
        c.registry=q.DemandRegistry((q.Registration(c.store,c.identity),));c.capability=object()
        c.box=q.Mailbox(c.registry,c.identity.registration_id,requester_capability=c.capability)
        c.original=c.checkpoint();c.deadline=q.execution_now()+900;c.worker=Child()
        c.host=SimpleNamespace(adapter=SimpleNamespace(launch_intent=None,started_owner=False),
            gateway=SimpleNamespace(_runtime_context=None,history=[],scheduler=SimpleNamespace(
                active=None,pending=0,uncertain=False)),controller=SimpleNamespace(fault=None))
        with c.store.claim(c.identity.task_id,expected_revision=c.original.revision) as owned:
            state=deepcopy(owned.checkpoint.state);state['deadline_monotonic']=c.deadline
            owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
            c.submit(q.INITIAL_PAUSE,'pause');c.box.consume(owned,updated_at_utc='2026-10-25T10:00:00Z')
            before=c.checkpoint();value=c.paused_ack()
            self.assertTrue(value['ack']['owner_acknowledged']);self.assertEqual(before,c.checkpoint())
            c.host.adapter.launch_intent={'unexpected':True}
            with self.assertRaises(RuntimeError):c.paused_ack()

    async def test_failed_prepare_without_children_records_failure_and_closes(self):
        c=self.case;c.root.rmdir()
        with mock.patch.object(c,'prepare',side_effect=RuntimeError('invalid deployment')):
            result=await c.run()
        self.assertFalse(result['clean_stop']);self.assertFalse(result['task_completed'])
        self.assertEqual(result['all_retained_process_exits'],[])
        self.assertEqual(result['primary_error']['type'],'RuntimeError')

    async def test_completed_host_outlives_task_deadline_until_real_stop(self):
        await self._completed_host()

    async def test_completed_custom_task_exposes_format_only_validation(self):
        await self._completed_host(custom=True)
        self.assertEqual(self.case.result['semantic_validation'],'not_checked')
        self.assertEqual(self.case.result['validated_artifacts'],[])
        self.assertEqual(self.case.result['artifacts'],{'greeting.txt':q.rec.digest(b'Welcome!')})

    async def _completed_host(self,custom=False):
        c=self.case;c.deadline=q.execution_now()-1;c.worker=Child(code=0)
        c.handles=[c.worker];c.worker_exit_verified=False
        c.stop_binding=SimpleNamespace(_verify_exit=lambda code:'task_completed')
        if custom:
            spec=custom_spec();c.task_spec_path=self.root/'task.json'
            work=self.root/'work';work.mkdir();(work/'greeting.txt').write_bytes(b'Welcome!')
            checkpoint=SimpleNamespace(prompt=spec.prompt,max_attempts=8,
                metadata={**spec.metadata(),'pre_effect_validator':spec.validator_identity()},
                state={'output':'Created greeting.txt.','tools':[{'name':'write_file',
                    'args':{'path':'greeting.txt'},'artifact_sha256':q.rec.digest(b'Welcome!')}]})
            c.stop_binding.mailbox=SimpleNamespace(snapshot=lambda:SimpleNamespace(target=checkpoint))
            c.stop_binding.run=self.root
        async def refresh():pass
        async def stopped():return dict(worker_joined=True,host_closed=True,uncertain=False,fault=None)
        c.runtime=SimpleNamespace(refresh=refresh,_transitioning=False)
        c.facade=SimpleNamespace(cooperative_stop=stopped)
        c.host=SimpleNamespace(controller=SimpleNamespace(fault=None))
        c.gui=SimpleNamespace(process=Child(42))
        state={'stop_requested':False,'stop_confirmed':False}
        c.transport=SimpleNamespace(lifecycle=lambda:dict(state),_stop_task=None)
        task=asyncio.create_task(c.interact())
        for _ in range(100):
            if c.result['task_completed']:
                break
            await asyncio.sleep(.01)
        self.assertFalse(task.done());self.assertTrue(c.result['task_completed'])
        state.update(stop_requested=True,stop_confirmed=True)
        c.transport._stop_task=asyncio.create_task(asyncio.sleep(0))
        await asyncio.wait_for(task,1)
        self.assertTrue(c.result['lifecycle']['host_closed'])

    async def test_expired_active_task_still_refuses_more_work(self):
        c=self.case;c.deadline=q.execution_now()-1;c.worker=Child()
        # The successor reads the existing runtime before distinguishing an
        # observed Pause from active expiry. Supply that actual active shape.
        cp=SimpleNamespace(state={'status':'pending','phase':'ready',
            'deadline_monotonic':c.deadline,'pending_request':None},operation=None,
            requires_reconciliation=False)
        c.runtime=SimpleNamespace(refresh=mock.AsyncMock(),_transitioning=False,_cache=SimpleNamespace(snapshot=
            SimpleNamespace(target=cp,demand={'state':'active'},requests=(),receipts=())))
        c.transport=SimpleNamespace(lifecycle=lambda:{'stop_requested':False})
        # A ready active checkpoint is not a supported admission wait. Detailed
        # wait identity/prefix checks use real bindings in the safe-wait tests.
        with mock.patch.object(c,'_admission_wait_expiry_candidate',
                               new=mock.AsyncMock(return_value=False)) as wait_candidate:
            with self.assertRaises(TimeoutError):await c.interact()
        wait_candidate.assert_awaited_once()

    async def test_prepare_order_uses_one_job_and_real_initial_pause(self):
        await self._prepare_order()

    async def test_custom_prompt_reaches_task_and_gui_with_same_cold_start_order(self):
        spec=custom_spec();path=self.root/'task.json';path.write_bytes(json.dumps(spec.data).encode())
        inputs=self.root/'inputs';inputs.mkdir()
        self.case=q.DesktopComposition(self.case.profile_path,self.root/'custom-run',task_spec=path,task_inputs=inputs)
        self.case.root.mkdir()
        await self._prepare_order(spec)

    async def test_saved_task_reuses_progress_deadline_and_fresh_paused_owner(self):
        from adaptive_inference.desktop import saved_tasks
        spec = custom_spec(); work = self.root/'saved-task'
        (work/'work').mkdir(parents=True)
        identity=q.DemandIdentity('registration','saved-task','worker','2026-10-25T10:00:00Z')
        boot={'source':saved_tasks.BOOT_SOURCE,'boot_utc':'2026-11-01T08:12:13.1234567Z','computer_name':'fixture'}
        context=saved_tasks.bind_context(saved_tasks.new_context(q.sha(self.case.profile_path),
            {'version':'fixture','files':{}},boot),work)
        store=q.TaskStore(work/'task.sqlite3')
        cp=prepare_task(store,identity,spec.prompt,'saved-native-session',metadata={
            'model':q.MODEL,'quality':q.QUALITY,'deadline_clock':q.CLOCK_ID,**spec.metadata(),
            'pre_effect_validator':spec.validator_identity(),saved_tasks.CONTEXT:context})
        deadline=q.execution_now()+600
        with store.claim(cp.task_id,expected_revision=cp.revision) as owned:
            state=deepcopy(owned.checkpoint.state)
            state.update(deadline_monotonic=deadline,requests=2,attempts=1,admission_attempts=3,
                         native_history=[{'role':'user','content':spec.prompt}],output='Saved progress.')
            owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        q.rec.save(work/'plan.json',{'task_id':cp.task_id,'demand_identity':q.asdict(identity),
            'deadline_clock':q.CLOCK_ID,'base_python':str(self.case.profile.worker_python),
            'gateway':'http://127.0.0.1:18100/v1','pins':{},'task_spec':spec.data,'task_spec_sha256':spec.sha256,
            saved_tasks.CONTEXT:context})
        old=(work/'controller-ready-1.json');old.write_text('{"old":true}')
        self.case=q.DesktopComposition(self.case.profile_path,self.root/'reopened',saved_task=work)
        self.case.root.mkdir()
        with mock.patch.object(saved_tasks,'observe_boot',return_value=boot):
            await self._prepare_order(spec,reopened=True)
        self.assertEqual(self.case.deadline,deadline)
        self.assertEqual(self.case.original.state['requests'],2)
        self.assertEqual(self.case.original.state['output'],'Saved progress.')
        self.assertNotEqual(self.case.first_ready,old)
        self.assertEqual(old.read_text(),'{"old":true}')
        self.assertEqual(self.case.stop_binding.diagnostics,self.case.saved_diagnostics)

    async def test_it_m2_01_automatic_recovery_compiler_harness(self):
        """IT-M2-01: End-to-end DesktopComposition.interact automatic recovery with real TaskStore and Mailbox."""
        from test_compiler_task_spec import compiler_data
        c = self.case
        c.work = self.root / 'run'
        c.work.mkdir(parents=True, exist_ok=True)
        (c.work / 'work').mkdir(parents=True, exist_ok=True)
        spec = TaskSpec(compiler_data())
        c.plan = {
            'task_id': 'task-it-1',
            'base_python': os.path.abspath(q.sys.executable),
            'gateway': 'http://127.0.0.1:8000/v1',
            'task_spec': spec.data,
            'task_spec_sha256': spec.sha256,
        }
        c.task_spec_path = None
        c.compiler_kind = 'compiler'
        c.compiler_bindings = {}
        c.compiler_bindings_history = []
        c.compiler_generations = {}
        c.recovery_records = {}
        c.worker_replacements_count = 0
        c.deadline = q.execution_now() + 600.0
        c.capability = object()
        c.host_epoch = 'epoch-it'
        c.first_ready = c.work / 'controller-ready-1.json'
        c.reopen_context = None
        c.saved = None
        c.qualification_hold_after_report = False

        # Set up real TaskStore SQLite & DemandRegistry & Mailbox
        db_path = c.work / 'task.sqlite3'
        store = q.TaskStore(db_path)
        identity = q.DemandIdentity('reg-it-1', 'task-it-1', 'worker', '2026-11-08T00:00:00Z')
        c.identity = SimpleNamespace(task_id='task-it-1', registration_id='reg-it-1')
        cp = store.create('task-it-1', spec.prompt, max_attempts=8, metadata={
            q.NAMESPACE: identity.metadata(),
            'model': q.MODEL, 'quality': q.QUALITY, 'deadline_clock': q.CLOCK_ID, **spec.metadata()
        })
        registry = q.DemandRegistry((q.Registration(store, identity),))
        c.registry = registry
        mailbox = q.Mailbox(registry, 'reg-it-1', requester_capability=c.capability)

        # Advance checkpoint to simulate in-flight effect operation
        with store.claim('task-it-1', expected_revision=cp.revision) as owned:
            registry.transition('reg-it-1', owned, 'active', expected_revision=owned.checkpoint.revision, updated_at_utc='2026-11-08T00:00:00Z')
            st = deepcopy(owned.checkpoint.state)
            st.update(status='pending', attempts=1)
            effect = owned.begin_operation('effect', details={'tool': 'clang-cl'}, state=st, expected_revision=owned.checkpoint.revision)
            op_id = effect.operation['id']

        worker_1 = Child(pid=501, code=86)
        c.handles = [worker_1]
        c.worker = worker_1
        c.worker_exit_verified = False

        c.stop_binding = SimpleNamespace(
            worker=worker_1,
            mailbox=mailbox,
            run=c.work,
            request_id='stop-it-1',
            _verify_exit=lambda code: 'task_completed' if code == 0 else 'unexpected_exit'
        )
        c.stop_id = 'stop-it-1'

        receipt_data = {
            'operation_id': op_id,
            'tool': 'clang-cl',
            'units': 5,
            'owned_processes_exited': True,
            'returncode': 0
        }
        bound_state = {'bound': True}
        compiler_host = SimpleNamespace(
            lifecycle=lambda: dict(bound_state),
            terminal_receipt=mock.AsyncMock(return_value=receipt_data),
            retire=mock.AsyncMock(),
            bind=mock.AsyncMock(),
            interrupt=mock.Mock()
        )
        async def fake_retire(timeout=30):
            bound_state['bound'] = False
        compiler_host.retire.side_effect = fake_retire
        c.compiler_host = compiler_host

        worker_2 = Child(pid=502, code=None)
        replacement_binding = SimpleNamespace(
            worker=worker_2,
            mailbox=mailbox,
            run=c.work,
            _capability=object(),
            request_id='stop-it-2',
            _verify_exit=lambda code: 'task_completed' if code == 0 else 'unexpected_exit'
        )

        def mock_launch(cmd, label):
            if 'reconcile' in label:
                reconciler = Child(pid=601, code=0)
                c.handles.append(reconciler)
                # Repair real SQLite checkpoint via reconcile_operation
                latest = store.load('task-it-1')
                with store.claim('task-it-1', expected_revision=latest.revision) as owned:
                    st = deepcopy(owned.checkpoint.state)
                    st.update(phase='ready', status='pending')
                    owned.reconcile_operation(op_id, resolution='completed', result=receipt_data, state=st, expected_revision=owned.checkpoint.revision)
                return reconciler
            elif 'worker' in label:
                boot_path = c.worker_diagnostics() / f'bootstrap-{worker_2.pid}.json'
                boot_path.parent.mkdir(parents=True, exist_ok=True)
                boot_path.write_text(json.dumps({
                    'pid': worker_2.pid,
                    'task_id': c.identity.task_id,
                    'registration_id': c.identity.registration_id,
                    'deadline_monotonic': c.deadline,
                    'deadline_clock': q.CLOCK_ID,
                    'owner_epoch': 'epoch-it'
                }))
                c.handles.append(worker_2)
                return worker_2
            ch = Child(pid=701, code=0)
            c.handles.append(ch)
            return ch

        c.launch = mock.Mock(side_effect=mock_launch)
        def fake_bind_worker_stop():
            c.stop_binding = replacement_binding
            c.worker_cap = replacement_binding._capability
        c.bind_worker_stop = fake_bind_worker_stop
        def fake_replace(expected, cb):
            cb()
            return replacement_binding
        c.facade = SimpleNamespace(
            replace_recovered_worker=mock.Mock(side_effect=fake_replace),
            cooperative_stop=mock.AsyncMock(return_value={'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None})
        )
        c.checkpoint = mock.Mock(return_value=SimpleNamespace(
            revision=5,
            owner_epoch='epoch-it',
            prompt=spec.prompt,
            metadata=spec.metadata(),
            state=deepcopy(cp.state)
        ))
        c.assert_original = mock.Mock()
        c.host = SimpleNamespace(
            closing=False, closed=False,
            controller=SimpleNamespace(fault=None, identity={'owner_id': 'ctrl-it'}),
            gateway=SimpleNamespace(instance='inst-it'),
            wait_ready=mock.AsyncMock()
        )
        c.gui = SimpleNamespace(process=Child(pid=42))
        transport_state = {'stop_requested': False, 'stop_confirmed': False}
        c.transport = SimpleNamespace(lifecycle=lambda: dict(transport_state), _stop_task=None)
        c.runtime = SimpleNamespace(
            refresh=mock.AsyncMock(), _transitioning=False,
            prepared=SimpleNamespace(task_id=c.identity.task_id),
            selected_execution=lambda: {'execution_id': c.identity.task_id}
        )
        c.bind_compiler_worker = mock.AsyncMock()

        interact_task = asyncio.create_task(c.interact())
        # Let interact() run through worker_1 joining and recovery
        await asyncio.sleep(0.05)
        self.assertIn((501, op_id), c.recovery_records)
        self.assertIs(c.worker, worker_2)

        # Now simulate worker_2 completing cleanly
        worker_2.finish(0)
        # Wait for interact to observe worker_2 completion
        for _ in range(50):
            if c.result['task_completed']:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(c.result['task_completed'])

        # End interact via stop
        transport_state.update(stop_requested=True, stop_confirmed=True)
        c.transport._stop_task = asyncio.create_task(asyncio.sleep(0))
        await asyncio.wait_for(interact_task, timeout=2.0)

        # Verify real SQLite store was repaired
        final_cp = store.load('task-it-1')
        self.assertIsNone(final_cp.operation)
        self.assertFalse(final_cp.requires_reconciliation)
        self.assertEqual(final_cp.state['status'], 'pending')
        self.assertEqual(final_cp.state['phase'], 'ready')

    async def _prepare_order(self,spec=None,reopened=False):
        from adaptive_inference.desktop import owned_job, activity, cold_start, desktop_controls, gui_launch
        c=self.case;events=[];children=set();owned_context=[]
        job=SimpleNamespace(_HANDLE=object(),contain_current_process=lambda:events.append('own-job'),
            active_process_ids=lambda:{os.getpid(),*children})
        prepare_child=Child(101,0);worker=Child(102)
        original_join=c.join_child
        async def joined(child):
            value=await original_join(child);children.discard(child.pid);events.append('join-prepare');return value
        c.join_child=joined
        def launch(command,label):
            if label=='prepare':
                self.assertFalse(reopened,'Saved task must not invoke fresh prepare')
                self.assertEqual(events,['own-job'])
                c.work.mkdir();(c.work/'work').mkdir()
                task_id='orders-report' if spec is None else command[command.index('--task-id')+1]
                if spec is None:self.assertIn('--validate-report-before-write',command)
                else:
                    self.assertNotIn('--validate-report-before-write',command)
                    self.assertEqual(command[command.index('--task-spec-sha256')+1],q.sha(c.task_spec_path))
                    self.assertEqual(command[command.index('--task-inputs')+1],str(c.task_inputs))
                identity=q.DemandIdentity('registration',task_id,'worker','2026-10-25T10:00:00Z')
                store=q.TaskStore(c.work/'task.sqlite3')
                prepare_task(store,identity,q.PROMPT if spec is None else spec.prompt,'session',
                    metadata={'model':q.MODEL,'quality':q.QUALITY,'deadline_clock':q.CLOCK_ID,
                              **({} if spec is None else spec.metadata())})
                q.rec.save(c.work/'plan.json',{'demand_identity':q.asdict(identity),'task_id':task_id,
                    **({} if spec is None else {'task_spec':spec.data,'task_spec_sha256':spec.sha256}),
                    'deadline_clock':q.CLOCK_ID,
                    'base_python':str(c.profile.worker_python),'gateway':'http://127.0.0.1:18100/v1'})
                events.append('prepare');child=prepare_child
            else:
                self.assertEqual(events[-1],'parked-host')
                if reopened:
                    self.assertEqual(command[command.index('--deadline-monotonic')+1],str(c.original.state['deadline_monotonic']))
                    self.assertEqual(command[command.index('--diagnostics')+1],str(c.saved_diagnostics))
                self.assertIn('-m',command);self.assertNotIn('--canonical',command)
                cp=c.store.load(c.identity.task_id)
                context=c.store.claim(cp.task_id,expected_revision=cp.revision)
                owned=context.__enter__();owned_context.append(context)
                state=deepcopy(owned.checkpoint.state);state['deadline_monotonic']=c.deadline
                owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
                c.box.consume(owned,updated_at_utc='2026-10-25T10:00:00Z')
                events.append('paused-worker');child=worker
            c.handles.append(child);children.add(child.pid);return child
        c.launch=launch
        class Adapter:
            launch_intent=None;started_owner=False
            def __init__(self,**kw):
                self.job=kw['job'];self.max_runtime_seconds=kw['max_runtime_seconds']
        class Host:
            closing=False;started_at=None
            def __init__(self,*a,**kw):
                self.adapter=kw['adapter'];self.job=kw['job']
                self.gateway=SimpleNamespace(instance='gateway',_runtime_context=None,history=[],
                    scheduler=SimpleNamespace(active=None,pending=0,uncertain=False))
                self.controller=SimpleNamespace(events=deque([{'parked':True}],maxlen=256),fault=None)
            async def start(self,**kw):
                self_outer.assertEqual(self.job.active_process_ids(),{os.getpid()})
                self_outer.assertIs(self.job,self.adapter.job)
                self.started_at=time.monotonic();events.append('parked-host')
            def attach_control_runtime(self,value):events.append('attach-runtime')
        class Runtime:
            def __init__(self,*a,**kw):pass
            async def refresh(self):pass
            def configure_continuation(self,value):pass
        class Transport:
            _ready=True
            def __init__(self,*a,**kw):pass
            def bind_session(self,*a):events.append('bind-session')
        class Listener:
            def __init__(self,*a):pass
            def start(self):events.append('listener');return ('127.0.0.1',12345)
        class GUI:
            def __init__(self,**kw):self.binding=None;self.verifier=object();self.process=Child(103)
            async def start(self,spec,bootstrap,**kw):
                self_outer.assertIs(kw['containing_job'],job._HANDLE)
                self_outer.assertEqual(spec.interpreter,c.profile.host_python)
                self_outer.assertEqual(bootstrap.objective,c.original.prompt)
                self_outer.assertEqual(bootstrap.task_id,c.original.task_id)
                self_outer.assertTrue(kw['launch_ready']())
                from adaptive_inference.desktop.ui_intent import UIBinding
                self.binding=UIBinding(bootstrap.host_epoch,bootstrap.session_id,bootstrap.task_id,1,103,2)
                kw['bind_session'](self.binding,self.verifier,bootstrap);events.append('gui')
        self_outer=self
        api=SimpleNamespace(handle=lambda child:child,identity=lambda child:(child.pid,5),in_job=lambda *a:True)
        facade=SimpleNamespace(bind_window=lambda *a:None,window_closed=lambda *a:None,verify_current=lambda *a:None)
        try:
            with mock.patch.object(q,'os',SimpleNamespace(name='nt',getpid=os.getpid)), \
                    mock.patch.object(q,'sys',SimpleNamespace(version_info=(3,11,9))), \
                    mock.patch.object(q,'verify_interpreter'), mock.patch.object(q,'verify_sdk'), \
                    mock.patch.object(q,'verify_execution_clock',return_value=q.CLOCK_ID), \
                    mock.patch.object(q,'package_identity',return_value={'version':'fixture','files':{}}), \
                    mock.patch('adaptive_inference.desktop.owned_job',job), \
                    mock.patch.object(activity,'WindowsActivityReader',return_value=object()), \
                    mock.patch.object(cold_start,'ColdStartAdapter',Adapter), \
                    mock.patch.object(desktop_controls,'ControlledDesktopHost',Host), \
                    mock.patch.object(desktop_controls,'DesktopControlLifecycle',return_value=facade), \
                    mock.patch.object(gui_launch,'WindowsLaunchAPI',return_value=api), \
                    mock.patch.object(gui_launch,'OwnedUILaunch',GUI), \
                    mock.patch.object(q,'MailboxRuntime',Runtime), \
                    mock.patch.object(q,'ControlTransport',Transport), \
                    mock.patch.object(q,'SerialListener',Listener):
                await c.prepare()
            self.assertEqual(events,['own-job',*([] if reopened else ['prepare','join-prepare']),'parked-host',
                'paused-worker','attach-runtime','listener','bind-session','gui'])
            self.assertIs(c.job,job)
            self.assertTrue(c.paused_ack()['ack']['owner_acknowledged'])
        finally:
            for context in owned_context:context.__exit__(None,None,None)
            for lock in c.reopen_locks:lock.close()


class LifetimeTests(unittest.TestCase):
    def test_custom_input_options_require_a_pair_and_reject_bad_spec_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();case=make_case(root)
            path=root/'task.json';path.write_text('{"schema":1,"schema":2}',encoding='utf-8')
            with mock.patch.object(q.subprocess,'Popen') as launch:
                for options in ({'task_spec':path},{'task_inputs':root},
                                {'task_spec':path,'task_inputs':root}):
                    with self.subTest(options=options),self.assertRaises(ValueError):
                        q.DesktopComposition(case.profile_path,root/'run',**options)
                launch.assert_not_called()

    def test_ordinary_execute_has_no_lifetime_watchdog(self):
        async def run():return {'clean_stop':True}
        case=SimpleNamespace(run=run)
        with mock.patch.object(q,'DesktopComposition',return_value=case), \
                mock.patch.object(q.threading,'Thread') as thread, mock.patch.object(q.rec,'save'):
            self.assertTrue(q.execute('profile','state')['clean_stop'])
        thread.assert_not_called()

    def test_only_explicit_qualification_arms_original_no_io_guard(self):
        async def run():return {'clean_stop':True}
        with mock.patch.object(q,'DesktopComposition',return_value=SimpleNamespace(run=run)), \
                mock.patch.object(q.threading,'Thread') as thread, mock.patch.object(q.rec,'save'):
            q.execute('profile','state',qualification_timeout_s=1800)
            thread.assert_called_once_with(target=q.hard_deadline,args=(1800,),daemon=True)
            thread.return_value.start.assert_called_once()
            with self.assertRaises(ValueError):q.execute('profile','state',qualification_timeout_s=1801)


if __name__=='__main__':unittest.main()
