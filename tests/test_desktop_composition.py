"""Shared installed composition ownership/ordering fixtures, no GUI or model."""
import asyncio
from collections import deque
from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop import composition as q
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from test_desktop_installation import profile_value


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
        self.assertFalse(c.waits[child.pid].done())
        child.finish(0)
        self.assertEqual(await c.join_child(child),0)
        self.assertEqual(child.waits,1)

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
        c=self.case;c.deadline=q.execution_now()-1;c.worker=Child(code=0)
        c.handles=[c.worker];c.worker_exit_verified=False
        c.stop_binding=SimpleNamespace(_verify_exit=lambda code:'task_completed')
        async def refresh():pass
        async def stopped():return dict(worker_joined=True,host_closed=True,uncertain=False,fault=None)
        c.runtime=SimpleNamespace(refresh=refresh)
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
        c.runtime=SimpleNamespace(refresh=mock.AsyncMock(),_cache=SimpleNamespace(snapshot=
            SimpleNamespace(target=cp,demand={'state':'active'},requests=(),receipts=())))
        c.transport=SimpleNamespace(lifecycle=lambda:{'stop_requested':False})
        with self.assertRaises(TimeoutError):await c.interact()

    async def test_prepare_order_uses_one_job_and_real_initial_pause(self):
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
                self.assertEqual(events,['own-job'])
                c.work.mkdir();(c.work/'work').mkdir()
                identity=q.DemandIdentity('registration','orders-report','worker','2026-10-25T10:00:00Z')
                store=q.TaskStore(c.work/'task.sqlite3')
                prepare_task(store,identity,q.PROMPT,'session',metadata={'model':q.MODEL,'quality':q.QUALITY,
                             'deadline_clock':q.CLOCK_ID})
                q.rec.save(c.work/'plan.json',{'demand_identity':q.asdict(identity),
                    'deadline_clock':q.CLOCK_ID,
                    'base_python':str(c.profile.worker_python),'gateway':'http://127.0.0.1:18100/v1'})
                events.append('prepare');child=prepare_child
            else:
                self.assertEqual(events[-1],'parked-host')
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
            self.assertEqual(events,['own-job','prepare','join-prepare','parked-host',
                'paused-worker','attach-runtime','listener','bind-session','gui'])
            self.assertIs(c.job,job)
            self.assertTrue(c.paused_ack()['ack']['owner_acknowledged'])
        finally:
            for context in owned_context:context.__exit__(None,None,None)


class LifetimeTests(unittest.TestCase):
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
