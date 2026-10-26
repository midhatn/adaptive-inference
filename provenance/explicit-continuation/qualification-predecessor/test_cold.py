"""Harness boundaries with actual TaskStore/Mailbox and fake lifecycle only."""
import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
import os
from types import SimpleNamespace
import unittest
from unittest import mock

import installed_desktop_qualification as q
import json
from test_desktop_installation import profile_value
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from adaptive_inference.desktop.hermes.control_bridge import Controls
from adaptive_inference.desktop.hermes.service_stop import StopAtPause,ProductStop,WorkerStopBinding


def args_for(run):
    profile=run.parent/'fixture-profile.json'
    profile.write_text(json.dumps(profile_value(run.parent)),encoding='utf-8')
    return SimpleNamespace(run=run,profile=profile,case='cold')

NOW='2026-10-24T20:00:00Z'


class Child:
    def __init__(self,pid=9001):self.pid=pid;self.code=None;self.done=threading.Event();self.wait_calls=0
    def poll(self):return self.code
    def wait(self):
        self.wait_calls+=1
        if not self.done.wait(5):raise TimeoutError('fixture child was not released')
        return self.code
    def finish(self,code):self.code=code;self.done.set()
    def kill(self):raise AssertionError('No product kill')
    def terminate(self):raise AssertionError('No product terminate')


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.case=q.ColdUIQualification(args_for(self.root/'case'))
        c=self.case;c.root.mkdir();c.work=c.root/'hermes-task';(c.work/'work').mkdir(parents=True)
        c.store=q.TaskStore(c.work/'task.sqlite3')
        c.identity=q.DemandIdentity('cold-registration','cold-task','fixture-owner',NOW)
        prepare_task(c.store,c.identity,q.PROMPT,'native-fixture',
            metadata={'model':q.MODEL,'quality':q.QUALITY,'deadline_clock':q.CLOCK_ID},max_attempts=8)
        c.registry=q.DemandRegistry((q.Registration(c.store,c.identity),));c.capability=object()
        c.box=q.Mailbox(c.registry,c.identity.registration_id,requester_capability=c.capability)
        c.original=c.checkpoint();c.deadline=q.execution_now()+900
        self.context=c.store.claim(c.identity.task_id,expected_revision=c.original.revision)
        self.owned=self.context.__enter__();self.addCleanup(self.release_owner)
        state=deepcopy(self.owned.checkpoint.state);state['deadline_monotonic']=c.deadline
        state['deadline_clock']=q.CLOCK_ID
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        c.box.submit(c.capability,q.INITIAL_PAUSE,'pause');c.box.consume(self.owned,updated_at_utc=NOW)
        c.worker=Child();self.addCleanup(c.worker.finish,2)
        c.host=SimpleNamespace(adapter=SimpleNamespace(launch_intent=None,started_owner=False),
            gateway=SimpleNamespace(_runtime_context=None,history=deque(maxlen=256),
                scheduler=SimpleNamespace(active=None,pending=0,uncertain=False,closing=False)),
            controller=SimpleNamespace(fault=None,events=deque([{'cold_parked':True}],maxlen=256)),closed=False)
        c.gui=SimpleNamespace(process=Child(9002));self.addCleanup(c.gui.process.finish,0)
        self.lifecycle={'stop_requested':False,'stop_confirmed':False}
        c.transport=SimpleNamespace(_records={},lifecycle=lambda:dict(self.lifecycle),_stop_task=None)
        c.runtime=SimpleNamespace(status=lambda:{'host_phase':'parked','demand':'paused'})
        async def stopped():return {'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}
        c.facade=SimpleNamespace(cooperative_stop=stopped)

    def release_owner(self):
        if self.context is not None:self.context.__exit__(None,None,None);self.context=None

    async def gui_pause(self,request_id='gui-pause'):
        c=self.case;c.box.submit(c.capability,request_id,'pause');c.box.consume(self.owned,updated_at_utc=NOW)
        async def complete():return c.box.status(request_id)
        task=asyncio.create_task(complete());await task
        c.transport._records[request_id]={'command':'pause','outcome':'known','task':task}

    async def manual_stop(self):
        self.lifecycle.update(stop_requested=True,stop_confirmed=True)
        self.case.transport._stop_task=asyncio.create_task(asyncio.sleep(0))

    async def test_actual_paused_ack_precedes_any_gui_readiness(self):
        value=self.case.paused_ack()
        self.assertTrue(value['ack']['owner_acknowledged'])
        self.assertEqual(value['checkpoint']['owner_epoch'],self.owned.checkpoint.owner_epoch)
        self.assertFalse((self.case.work/f'bootstrap-{self.case.worker.pid}.json').exists())

    async def test_manual_gui_pause_then_stop_drives_no_resume(self):
        c=self.case;await self.gui_pause();run=asyncio.create_task(c.interact())
        for _ in range(100):
            if (c.root/'status.private.json').exists():break
            await asyncio.sleep(.01)
        self.assertTrue(q.read(c.root/'status.private.json')['gui_pause_acknowledged'])
        await self.manual_stop();await asyncio.wait_for(run,1)
        self.assertTrue(c.result['gui_pause_observed_before_stop'])
        self.assertEqual([r['command'] for r in c.box.snapshot().requests],['pause','pause'])
        self.assertEqual(c.checkpoint().state['requests'],0)

    async def test_stop_without_separately_observed_gui_pause_refuses(self):
        await self.manual_stop()
        with self.assertRaisesRegex(RuntimeError,'GUI Pause ACK'):await self.case.interact()

    async def test_pause_ack_seen_only_after_stop_does_not_qualify(self):
        await self.gui_pause();await self.manual_stop()
        with self.assertRaisesRegex(RuntimeError,'GUI Pause ACK'):await self.case.interact()

    async def test_resume_or_foreign_control_id_refuses_cold_trial(self):
        c=self.case;c.box.submit(c.capability,'unexpected-resume','resume')
        with self.assertRaisesRegex(RuntimeError,'no Resume'):q.gui_controls(c.transport,c.box,c.stop_id)
        self.assertIsNone(c.host.adapter.launch_intent)

    async def test_no_work_rejects_unknown_operation(self):
        c=self.case;self.owned.begin_operation('effect',details={'unknown':True},expected_revision=self.owned.checkpoint.revision)
        with self.assertRaisesRegex(RuntimeError,'unknown work'):q.no_work(c.checkpoint(),c.original,c.deadline,c.host,c.work)

    async def test_no_work_rejects_artifact_and_actual_runtime_launch_intent(self):
        c=self.case;(c.work/'work/report.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'artifact'):q.no_work(c.checkpoint(),c.original,c.deadline,c.host,c.work)
        (c.work/'work/report.json').unlink();c.host.adapter.launch_intent={'attempt':1}
        with self.assertRaisesRegex(RuntimeError,'runtime evidence'):q.no_work(c.checkpoint(),c.original,c.deadline,c.host,c.work)

    async def test_retained_wait_cancellation_does_not_kill_or_lose_child(self):
        c=self.case;c.handles=[c.worker]
        wait=asyncio.create_task(c.join_child(c.worker));await asyncio.sleep(.02);wait.cancel()
        with self.assertRaises(asyncio.CancelledError):await wait
        self.assertFalse(c.waits[c.worker.pid].done());c.worker.finish(4)
        self.assertEqual(await c.join_child(c.worker),4);self.assertEqual(c.worker.wait_calls,1)

    async def test_retained_join_collects_failed_sibling_without_abandoning_other(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def failed():raise OSError('fixture complete failure')
        async def pending():entered.set();await release.wait();return 'joined'
        tasks=[asyncio.create_task(failed()),asyncio.create_task(pending())]
        wait=asyncio.create_task(q.join_retained(tasks));await entered.wait();await asyncio.sleep(.01)
        self.assertFalse(wait.done());release.set();result=await wait
        self.assertIsInstance(result[0],OSError);self.assertEqual(result[1],'joined')

    async def test_no_new_deadline_or_quality_on_repeated_paused_observation(self):
        c=self.case;before=c.checkpoint()
        for _ in range(3):c.paused_ack()
        self.assertEqual(c.checkpoint(),before)
        self.assertEqual(before.metadata['quality'],q.QUALITY)

    async def test_failed_trial_with_no_gui_can_clean_after_known_worker_exit(self):
        c=self.case;c.facade=c.gui=c.runtime=c.transport=c.listener=None
        c.handles=[c.worker];events=[]
        def request(cap):events.append('request_stop');c.worker.finish(4)
        async def join(*,timeout):return {'worker_joined':True,'safe_checkpoint':True}
        c.stop_binding=SimpleNamespace(request_stop=request,join=join,_work=None);c.worker_cap=object()
        async def close(*,timeout_s):
            self.assertEqual(c.worker.poll(),4);self.assertTrue(c.waits[c.worker.pid].done())
            events.append('host_close');return {'closed':True}
        c.host.close=close
        await c.dispose(True)
        self.assertEqual(events,['request_stop','host_close'])
        self.assertTrue(c.result['retained_obligations_joined'])
        self.assertFalse(c.result['qualification_case_passed'])

    async def test_diagnostic_write_failure_cannot_skip_retained_child_join(self):
        c=q.ColdUIQualification(args_for(self.root/'diagnostic-failure'))
        child=Child(9010);self.addCleanup(child.finish,2)
        async def prepare():c.handles.append(child);raise OSError('fixture primary failure')
        async def dispose(failed):raise OSError('fixture cleanup remains unresolved')
        c.prepare=prepare;c.dispose=dispose
        real_save=q.rec.save
        def broken_diagnostic(path,value):
            if Path(path).name=='unresolved.private.json':raise PermissionError('fixture diagnostic failure')
            return real_save(path,value)
        with mock.patch.object(q,'verify_closure',return_value={'fixture':True}),mock.patch.object(q.rec,'save',side_effect=broken_diagnostic):
            run=asyncio.create_task(c.run())
            for _ in range(100):
                if child.wait_calls:break
                await asyncio.sleep(.01)
            self.assertEqual(child.wait_calls,1);self.assertFalse(run.done())
            child.finish(2);result=await asyncio.wait_for(run,1)
        self.assertFalse(result['case_checks_and_cleanup_passed'])
        self.assertIn('diagnostic_write_error',result)

    async def test_launch_log_failure_keeps_exact_worker_reference(self):
        c=self.case;child=Child(9020);self.addCleanup(child.finish,2)
        with mock.patch.object(q.installed.subprocess,'Popen',return_value=child), \
                mock.patch.object(c,'event',side_effect=OSError('fixture event log failure')):
            with self.assertRaises(OSError):c.launch(['fixture-only'],'worker')
        self.assertIs(c.worker,child);self.assertIs(c.handles[-1],child)
        for stream in c.logs:stream.close()

    async def terminal_fixture(self):
        c=self.case;await self.gui_pause();c.worker.pid=os.getpid()
        c.stop_binding=WorkerStopBinding(c.worker,c.work,c.box,requester_capability=c.capability,
            capability=object(),stop_request_id=c.stop_id,original=c.original,
            deadline_monotonic=c.deadline,model=q.MODEL,quality=q.QUALITY,fence=lambda:None,
            deadline_clock=q.CLOCK_ID)
        controls=Controls(c.box,deadline=c.deadline,utc_now=lambda:NOW,deadline_clock=q.CLOCK_ID)
        db=SimpleNamespace(resolve_resume_session_id=lambda sid:sid,get_messages_as_conversation=lambda *a,**kw:[])
        recovery=q.rec.Recovery(self.owned,db,c.work/'work',c.work,controls=controls)
        controls.safe_boundary=StopAtPause(recovery,c.stop_id)
        c.box.submit(c.capability,c.stop_id,'pause')
        with self.assertRaises(ProductStop) as caught:recovery.bootstrap_controls()
        result={'passed':False,'controlled':True,'control_state':'stopped','completed':False,
            'service_stopped':True,'service_stop':caught.exception.receipt,'provider_calls':0,
            'model':q.MODEL,'quality':q.QUALITY,'owner_epoch':self.owned.checkpoint.owner_epoch}
        self.release_owner();c.worker.finish(4)
        q.rec.save(c.work/f'result-{c.worker.pid}.json',result)
        c.initial_events=deepcopy(list(c.host.controller.events));c.host.closed=True
        c.host.gateway.scheduler.closing=True;c.job=SimpleNamespace(active_process_ids=lambda:{os.getpid()})
        c.result.update(retained_obligations_joined=True,gui_cleanup={'closed':True,'faults':[]},
            listener_cleanup={'clean_close':True},transport_cleanup={'closed':True},
            cleanup={'closed':True,'primary_error':None,'cleanup_error':None,'controller_fault':None},
            source={'fixture_source':True})
        return result

    async def test_terminal_gate_uses_actual_released_checkpoint_and_stop_receipt(self):
        await self.terminal_fixture();c=self.case
        with mock.patch.object(q,'verify_closure',return_value=c.result['source']):c.validate_terminal()
        self.assertTrue(c.result['owner_released']);self.assertTrue(c.result['full_handoff_ledger'])
        self.assertEqual(c.result['worker_exit_code'],4);self.assertEqual(c.result['provider_calls'],0)
        self.assertEqual(c.result['task_status'],'pending');self.assertFalse(c.result['task_completed'])

    async def test_terminal_gate_rejects_nonzero_provider_count(self):
        worker=await self.terminal_fixture();c=self.case;worker['provider_calls']=1
        q.rec.save(c.work/f'result-{c.worker.pid}.json',worker)
        with self.assertRaisesRegex(RuntimeError,'unverified work'):c.validate_terminal()

    async def test_cleanup_exception_still_joins_separate_gui_obligation(self):
        c=q.ColdUIQualification(args_for(self.root/'gui-failure'))
        entered,release=asyncio.Event(),asyncio.Event()
        async def join_gui(*,timeout_s):
            entered.set();await release.wait()
            return {'pending_pipe_operations':0,'pipe_handles_closed':True,'process_handle_closed':True,
                    'verifier_handle_closed':True,'child_retained':True,'child_exit_observed':True}
        c.gui=SimpleNamespace(_start_task=None,_bound=True,_io=[],join=join_gui)
        async def prepare():raise OSError('fixture primary error')
        async def dispose(failed):raise OSError('fixture early cleanup error')
        c.prepare=prepare;c.dispose=dispose
        with mock.patch.object(q,'verify_closure',return_value={'fixture':True}):
            run=asyncio.create_task(c.run());await entered.wait()
            self.assertFalse(run.done());release.set();result=await asyncio.wait_for(run,1)
        self.assertTrue(result['gui_cleanup']['child_exit_observed'])
        self.assertFalse(result['case_checks_and_cleanup_passed'])

    async def test_listener_setup_and_handler_cleanup_are_retained_obligations(self):
        c=self.case;c.facade=c.runtime=c.stop_binding=c.gui=c.transport=None
        entered,release=asyncio.Event(),asyncio.Event()
        async def stream_cleanup():entered.set();await release.wait();return 'closed'
        task=asyncio.create_task(stream_cleanup())
        c.listener=SimpleNamespace(_driver=None,_close_task=None,
            _record={'setup':task,'handler':None,'cleanup':task},lifecycle=lambda:{'resources_closed':False})
        wait=asyncio.create_task(q.join_retained(c.obligations()));await entered.wait()
        self.assertFalse(wait.done());self.assertFalse(c.control_io_released())
        release.set();self.assertEqual(await wait,['closed'])


class SourceTests(unittest.TestCase):
    def test_source_closure_matches_clone_stable_lf_bytes(self):
        manifest=q.read(q.HERE/'source-manifest.json')
        self.assertEqual(set(manifest['files']),
            {'qualify.py','test_cold.py','test_full.py','test_expiry.py','README.md','source-lineage.json'})
        for name in {*manifest['files'],'source-manifest.json'}:
            self.assertNotIn(b'\r\n',(q.HERE/name).read_bytes(),name)
        with mock.patch.object(q,'package_identity',return_value={'fixture':'installed'}):
            result=q.verify_closure()
        self.assertEqual(result['files'],6)
        self.assertEqual(result['installed_package'],{'fixture':'installed'})

    def test_preserved_acceptance_methods_match_frozen_predecessor(self):
        import ast
        import hashlib
        from ast_preservation import preservation_dump
        tree=ast.parse((q.HERE/'qualify.py').read_text())
        functions={}
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                functions[node.name]=node
            elif isinstance(node,ast.ClassDef):
                for method in node.body:
                    if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        functions[node.name+'.'+method.name]=method
        for name, expected in q.read(q.HERE/'source-lineage.json')['preserved_methods'].items():
            node=functions[name]
            class Names(ast.NodeTransformer):
                def visit_Attribute(self,node):
                    if isinstance(node.value,ast.Name) and (node.value.id,node.attr) in (
                            ('prior','complete_ledger'),('cold','verify_closure')):
                        return ast.Name(id=node.attr,ctx=ast.Load())
                    return self.generic_visit(node)
            actual=hashlib.sha256(preservation_dump(Names().visit(node)).encode()).hexdigest()
            self.assertEqual(actual,expected,name)

    def test_cold_scenario_never_calls_kill_or_private_helper(self):
        import ast
        tree=ast.parse((q.HERE/'qualify.py').read_text())
        cold=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ColdUIQualification')
        calls=[node.func for node in ast.walk(cold) if isinstance(node,ast.Call)]
        self.assertFalse(any(isinstance(node,ast.Attribute) and node.attr in ('kill','terminate','joined') for node in calls))
        self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom)) and 'qualification_helpers' in ast.unparse(n) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Call) and ast.unparse(n.func).startswith('sys.path.') for n in ast.walk(tree)))
        self.assertIs(q.ColdUIQualification.__bases__[0],q.DesktopComposition)
        self.assertIs(q.FullUIQualification.safe_report,q.ValidationChecks.safe_report)

    def test_qualification_cleanup_keeps_product_gate_before_scenario_gate(self):
        calls=[]
        case=object.__new__(q.ColdUIQualification)
        case.validate_terminal=lambda:calls.append('scenario')
        with mock.patch.object(q.DesktopComposition,'validate_cleanup',lambda self:calls.append('product')):
            case.validate_cleanup()
        self.assertEqual(calls,['product','scenario'])

    def test_execute_requires_full_completion_and_records_teardown_after_run(self):
        for kind,completed,passed in [('cold',False,True),('full',False,False),('full',True,True)]:
            with self.subTest(kind=kind,completed=completed):
                calls=[]
                async def run():
                    calls.append('run')
                    return {'case_checks_and_cleanup_passed':True,'task_completed':completed}
                factory=lambda args:SimpleNamespace(run=run)
                thread=SimpleNamespace(start=lambda:calls.append('guard-start'))
                with mock.patch.object(q,'ColdUIQualification',factory),mock.patch.object(q,'FullUIQualification',factory), \
                        mock.patch.object(q.threading,'Thread',return_value=thread) as guard, \
                        mock.patch.object(q.rec,'save') as save:
                    result=q.execute(SimpleNamespace(case=kind,run=Path('fixture')))
                guard.assert_called_once_with(target=q.hard_deadline,args=(1800,),daemon=True)
                self.assertEqual(calls,['guard-start','run'])
                self.assertTrue(result['asyncio_teardown_completed'])
                self.assertIs(result['qualification_case_passed'],passed)
                save.assert_called_once_with(Path('fixture')/'result.private.json',result)

    def test_hard_watchdog_has_no_report_io_dependency(self):
        calls=[];q.hard_deadline(.01,wait=lambda seconds:calls.append(('wait',seconds)),
                                      terminate=lambda code:calls.append(('exit',code)))
        self.assertEqual(calls,[('wait',.01),('exit',124)])

    def test_full_ledger_never_accepts_rolled_over_tail(self):
        events=deque([{'initial':True}],maxlen=256);prefix=deepcopy(list(events))
        events.extend({'i':i} for i in range(256))
        with self.assertRaises(RuntimeError):q.complete_ledger(events,prefix)


if __name__=='__main__':unittest.main(verbosity=2)
