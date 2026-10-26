"""Paused-expiry scenario observations; real SQLite and retained fake tasks only."""
import asyncio
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import installed_desktop_qualification as q
from installed_desktop_cold_tests import HarnessTests,NOW,args_for
from installed_desktop_full_tests import FullUIBoundaries


class PausedExpiryBoundaries(unittest.IsolatedAsyncioTestCase):
    release_owner=HarnessTests.release_owner
    resume=FullUIBoundaries.resume
    apply_gui_pause=HarnessTests.gui_pause

    async def asyncSetUp(self):
        await FullUIBoundaries.asyncSetUp(self)
        prior=self.case
        case=q.PausedExpiryQualification(args_for(self.root/'unused-fresh-expiry'))
        case.__dict__.update(prior.__dict__)
        case.args.case='expiry'
        case.product_interaction=None
        case.gui_pauses=[]
        self.case=case
        self.release_product=asyncio.Event()
        self.case.product_interaction=asyncio.create_task(self.release_product.wait())
        self.addAsyncCleanup(self.finish_product)

    async def finish_product(self):
        self.release_product.set()
        await asyncio.gather(self.case.product_interaction,return_exceptions=True)

    async def paused(self):
        _,owner=await self.resume('actual-gui-resume')
        sequence=self.case.status('actual-gui-resume')['sequence']
        await self.apply_gui_pause('actual-gui-pause')
        return sequence,owner

    async def test_genuine_pause_requires_current_authenticated_owner_ack(self):
        c=self.case;sequence,owner=await self.paused();before=c.box.snapshot()
        ack=c.gui_pause(sequence,owner)
        self.assertEqual(ack['request_id'],'actual-gui-pause')
        self.assertTrue(ack['owner_acknowledged']);self.assertEqual(ack['outcome'],'applied')
        self.assertEqual(c.box.snapshot(),before)
        self.assertEqual(before.target.state['deadline_monotonic'],c.deadline)
        self.assertNotIn(q.REPORT_PAUSE,{row['request_id'] for row in before.requests})

    async def test_internal_pause_without_transport_record_is_not_gui_input(self):
        c=self.case;sequence,owner=await self.paused()
        del c.transport._records['actual-gui-pause']
        self.assertIsNone(c.gui_pause(sequence,owner))

    async def test_pending_pause_does_not_borrow_previous_ack(self):
        c=self.case;sequence,owner=await self.paused()
        c.box.submit(c.capability,'later-pause','pause')
        async def finished():return c.box.status('later-pause')
        task=asyncio.create_task(finished());await task
        c.transport._records['later-pause']={'command':'pause','outcome':'known','task':task}
        self.assertIsNone(c.gui_pause(sequence,owner))

    async def test_later_resume_or_stale_sequence_cannot_reuse_pause(self):
        c=self.case;sequence,owner=await self.paused()
        self.assertIsNone(c.gui_pause(sequence+1,owner))
        await self.resume('later-gui-resume')
        self.assertIsNone(c.gui_pause(sequence,owner))

    async def test_wrong_owner_or_revoked_session_refuses_pause_proof(self):
        c=self.case;sequence,owner=await self.paused()
        with self.assertRaisesRegex(RuntimeError,'current safe paused owner'):
            c.gui_pause(sequence,'wrong-owner')
        c.facade.session_is_live=lambda _:False
        with self.assertRaisesRegex(RuntimeError,'authenticated session'):
            c.gui_pause(sequence,owner)

    async def test_unknown_or_failed_retained_mutation_is_not_pause_success(self):
        c=self.case;sequence,owner=await self.paused()
        record=c.transport._records['actual-gui-pause'];record['outcome']='unknown'
        self.assertIsNone(c.gui_pause(sequence,owner))
        async def failed():raise OSError('retained mutation failed')
        task=asyncio.create_task(failed())
        with self.assertRaises(OSError):await task
        record.update(outcome='known',task=task)
        with self.assertRaisesRegex(OSError,'retained mutation failed'):c.gui_pause(sequence,owner)

    async def test_product_failure_precedes_apparently_successful_predicate(self):
        c=self.case;self.release_product.set();await c.product_interaction
        async def failed():raise RuntimeError('actual product failure')
        c.product_interaction=asyncio.create_task(failed())
        with self.assertRaises(RuntimeError):await c.product_interaction
        called=[]
        with self.assertRaisesRegex(RuntimeError,'actual product failure'):
            await c.observe_until(lambda:called.append(True) or True)
        self.assertEqual(called,[])

    async def test_expected_expiry_is_observed_without_new_budget(self):
        c=self.case;c.deadline=q.execution_now()-1;original=c.deadline
        self.assertEqual(await c.observe_until(lambda:'observed'),'observed')
        self.assertEqual(c.deadline,original)
        with self.assertRaisesRegex(TimeoutError,'900second task deadline'):
            await c.observe_until(lambda:True,before_deadline=True)

    async def test_monitor_yields_and_cancellation_keeps_product_task_retained(self):
        c=self.case;seen=asyncio.Event()
        monitor=asyncio.create_task(c.observe_until(lambda:False))
        async def control_progress():seen.set()
        control=asyncio.create_task(control_progress())
        await asyncio.wait_for(seen.wait(),1);await control
        monitor.cancel()
        with self.assertRaises(asyncio.CancelledError):await monitor
        self.assertFalse(c.product_interaction.done())
        with mock.patch.object(q.FullUIQualification,'obligations',return_value=[]):
            self.assertEqual(c.obligations(),[c.product_interaction])

    async def test_early_stop_and_gui_exit_do_not_count_as_expiry(self):
        c=self.case;self.lifecycle['stop_requested']=True
        with self.assertRaisesRegex(RuntimeError,'Stop interrupted'):
            await c.observe_until(lambda:True)
        self.lifecycle['stop_requested']=False;c.gui.process.finish(0)
        with self.assertRaisesRegex(RuntimeError,'GUI exited'):
            await c.observe_until(lambda:True)

    async def test_scenario_runs_exact_product_interaction_once(self):
        c=self.case;await self.finish_product();c.product_interaction=None
        self.release_product=asyncio.Event();started=asyncio.Event();calls=[]
        async def product(actual):
            self.assertIs(actual,c);calls.append('product');started.set()
            await self.release_product.wait()
            c.result['lifecycle']={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}
        async def scenario():
            await started.wait();self.assertIsNotNone(c.product_interaction)
            self.lifecycle.update(stop_requested=True,stop_confirmed=True)
            self.release_product.set()
        c.observe_expiry_scenario=scenario
        with mock.patch.object(q.DesktopComposition,'interact',product):await c.interact()
        self.assertEqual(calls,['product']);self.assertTrue(c.product_interaction.done())
        self.assertEqual(c.worker.wait_calls,0)

    async def test_failed_scenario_keeps_exact_product_task_for_cleanup(self):
        c=self.case;await self.finish_product();c.product_interaction=None
        self.release_product=asyncio.Event();started=asyncio.Event()
        async def product(actual):started.set();await self.release_product.wait()
        async def scenario():await started.wait();raise RuntimeError('scenario failed')
        c.observe_expiry_scenario=scenario
        with mock.patch.object(q.DesktopComposition,'interact',product):
            with self.assertRaisesRegex(RuntimeError,'scenario failed'):await c.interact()
        retained=c.product_interaction
        self.assertFalse(retained.done())
        with mock.patch.object(q.FullUIQualification,'obligations',return_value=[]):
            self.assertIn(retained,c.obligations())
        self.release_product.set();await retained

    async def test_park_requires_native_release_and_open_idle_service(self):
        c=self.case
        proof={'owner_id':'native-owner','released':True,'cleanup_confirmed':True,'port_free':True,
               'retained_processes':2,'confirmed_process_exits':2}
        class Controller:
            state='parked';identity={'owner_id':'native-owner'}
            events=deque([{'cold_parked':True},{'release':proof}],maxlen=256)
            def __call__(self):return False
        c.host.controller=Controller();c.initial_events=[{'cold_parked':True}]
        with mock.patch.object(q.time,'monotonic',return_value=1000), \
                mock.patch.object(q,'execution_now',return_value=1008):
            observation=c.observe_parked()
        self.assertEqual(observation['release'],proof);self.assertFalse(observation['host_closed'])
        self.assertEqual(observation['at_monotonic'],1000)
        self.assertEqual(observation['at_deadline_clock'],1008)
        self.assertEqual(observation['deadline_clock'],q.CLOCK_ID)
        for change in ('host_closed','scheduler_closing','pending','unconfirmed'):
            with self.subTest(change=change):
                c.host.closed=change=='host_closed'
                c.host.gateway.scheduler.closing=change=='scheduler_closing'
                c.host.gateway.scheduler.pending=int(change=='pending')
                proof['confirmed_process_exits']=1 if change=='unconfirmed' else 2
                with self.assertRaisesRegex(RuntimeError,'normal idle release'):c.observe_parked()

    async def test_restoring_is_not_an_observed_park(self):
        self.case.host.controller.state='restoring'
        self.assertIsNone(self.case.observe_parked())

    async def test_readiness_keeps_local_observation_and_shared_deadline_separate(self):
        c=self.case;c.progress=object()
        c.host.snapshot=lambda:{'controller':{'admission_allowed':True}}
        c.gate=SimpleNamespace(_revision=1,_binding=None)
        async def ready(actual,child,path):self.assertIs(actual,c)
        with mock.patch.object(q.DesktopComposition,'ready',ready), \
                mock.patch.object(q.time,'monotonic',return_value=1000), \
                mock.patch.object(q,'execution_now',return_value=1008):
            await c.ready(c.worker,c.root/'unused-readiness')
        row=c.result['cooperative_readiness_observations'][0]
        self.assertEqual((row['started_monotonic'],row['finished_monotonic']),(1000,1000))
        self.assertEqual(row['finished_deadline_clock'],1008)
        self.assertEqual(row['deadline_clock'],q.CLOCK_ID)

class ExpiryCaseSelectionTests(unittest.TestCase):
    def test_expiry_execute_requires_specific_success_and_pending_task(self):
        for valid,expired,completed,cleanup,expected in (
                (True,True,False,True,True),(False,True,False,True,False),
                (True,False,False,True,False),(True,True,True,True,False),
                (True,True,False,False,False)):
            with self.subTest(valid=valid,expired=expired,completed=completed,cleanup=cleanup):
                async def run():return {'case_checks_and_cleanup_passed':cleanup,'task_completed':completed,
                    'expiry_case_checks_passed':valid,'execution_expired':expired}
                factory=lambda args:SimpleNamespace(run=run)
                with mock.patch.object(q,'PausedExpiryQualification',factory), \
                        mock.patch.object(q.threading,'Thread') as guard,mock.patch.object(q.rec,'save'):
                    result=q.execute(SimpleNamespace(case='expiry',run=Path('fixture')))
                guard.assert_called_once_with(target=q.hard_deadline,args=(1800,),daemon=True)
                self.assertIs(result['qualification_case_passed'],expected)
                self.assertIs(result['task_completed'],completed)


class ExpiryProofTests(unittest.IsolatedAsyncioTestCase):
    """Real mailbox seal, existing recovery receipts and retained child fixture."""
    asyncSetUp=PausedExpiryBoundaries.asyncSetUp
    finish_product=PausedExpiryBoundaries.finish_product
    release_owner=HarnessTests.release_owner
    resume=FullUIBoundaries.resume
    apply_gui_pause=HarnessTests.gui_pause

    async def sealed(self):
        from adaptive_inference.control_mailbox import execution_outcome
        from adaptive_inference.desktop.hermes.service_stop import CLOCK_EXPIRY_RECEIPT_SCHEMA
        from test_desktop_report_feedback import NativeDB
        c=self.case
        # Synthetic fixture time only: the live scenario never changes this
        # absolute deadline or substitutes a shorter qualification budget.
        c.deadline=q.execution_now()-2
        state=deepcopy(self.owned.checkpoint.state);state['deadline_monotonic']=c.deadline
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        _,owner=await self.resume('actual-gui-resume')
        session=self.owned.checkpoint.state['session_id']
        db=NativeDB(c.work/'native-fixture.sqlite3');self.addCleanup(db.close)
        db.append({'role':'user','content':q.PROMPT})
        controller=q.rec.Recovery(self.owned,db,c.work/'work',c.work,
            controls=SimpleNamespace(poll=lambda owned:None))
        controller.barrier=lambda label:None
        def provider(request,**callbacks):
            operation=callbacks['begin']('fixture-attempt')
            callbacks['completed'](operation)
            return 'fixture model response'
        controller.provider=SimpleNamespace(execute=provider)
        controller.llm({},None,session_id=session)
        args={'path':'report.json','content':json.dumps(q.REPORT)}
        db.append({'role':'assistant','content':None,'tool_calls':[{'id':'write-once','type':'function',
            'function':{'name':'write_file','arguments':json.dumps(args)}}]})
        def effect(value):
            (c.work/'work/report.json').write_text(value['content'],encoding='utf-8')
            return json.dumps({'verified':True})
        result=controller.tool('write_file',args,effect,session_id=session,tool_call_id='write-once')
        self.assertIsNone(controller.fatal)
        db.append({'role':'tool','tool_call_id':'write-once','content':result})
        controller.control_safe_point()
        await self.apply_gui_pause('actual-gui-pause')
        c.gui_pauses=[c.gui_pause(c.status('actual-gui-resume')['sequence'],owner)]
        c.before=c.checkpoint();snapshot=c.box.snapshot()
        c.paused_prefix={'requests':list(snapshot.requests),'receipts':list(snapshot.receipts)}
        c.report_hash=q.sha(c.work/'work/report.json')
        c.effects=(c.work/'effect-receipts.jsonl').read_bytes()
        c.wires=[{'model':q.MODEL,'quality':q.QUALITY,'class':'normal','finished_at':1}]
        q.rec.save(c.work/'wire-observations.json',c.wires)
        marker=c.box.seal_paused_execution(self.owned,deadline_monotonic=c.deadline,
            pause_observed_at_monotonic=c.deadline-1,
            observed_pause=c.box.paused_execution_observation(self.owned),
            sealed_at_monotonic=c.deadline+.5,deadline_clock=q.CLOCK_ID)
        self.release_owner();cp=c.checkpoint()
        self.assertEqual(execution_outcome(cp.state),marker)
        proof={'schema':CLOCK_EXPIRY_RECEIPT_SCHEMA,'task_id':cp.task_id,
            'registration_id':c.identity.registration_id,'pid':c.worker.pid,
            'owner_epoch':marker['owner_epoch'],'revision':cp.revision,
            'state_sha256':q.rec.digest(cp.state),'native_history_sha256':q.rec.digest(cp.state['native_history']),
            **{key:marker[key] for key in ('deadline_monotonic','deadline_clock','pause_observed_at_monotonic',
                'sealed_at_monotonic','pause_request_id','pause_sequence','control_prefix_sha256')},
            'task_completed':False}
        c.plan={'sdk_revision':'fixture-sdk','deadline_clock':q.CLOCK_ID}
        final={'model':q.MODEL,'quality':q.QUALITY,'fixture':False,'sdk_revision':c.plan['sdk_revision'],
            'passed':False,'completed':False,'controlled':True,'control_state':'paused',
            'control_reason':'paused_budget_expired','provider_calls':1,'context':q.CONTEXT,
            'owner_epoch':owner,'paused_expiry':proof}
        q.rec.save(c.work/f'result-{c.worker.pid}.json',final)
        c.result.update(execution_expired=True,worker_outcome='paused_budget_expired',task_completed=False)
        c.stop_binding=q.WorkerStopBinding(c.worker,c.work,c.box,requester_capability=c.capability,
            capability=object(),stop_request_id=c.stop_id,original=c.original,
            deadline_monotonic=c.deadline,model=q.MODEL,quality=q.QUALITY,fence=lambda:None,
            deadline_clock=q.CLOCK_ID)
        c.handles=[c.worker]
        c.worker.finish(5)
        self.assertEqual(await c.join_child(c.worker),5)
        return cp,final

    async def test_real_seal_and_join_preserve_pending_task_report_and_history(self):
        expected,final=await self.sealed();c=self.case
        cp,result=c.verify_expired_progress()
        self.assertEqual(cp,expected);self.assertEqual(result,final)
        self.assertEqual(cp.state['status'],'pending');self.assertIsNone(cp.owner_epoch)
        self.assertFalse(c.result['task_completed']);self.assertEqual(c.worker.wait_calls,1)
        self.assertEqual(c.box.snapshot().requests[-1]['request_id'],'actual-gui-pause')

    async def test_shared_clock_preserves_strict_order_despite_legacy_clock_skew(self):
        expected,_=await self.sealed();c=self.case
        # Reproduce the differing host/worker clock domains without waiting or
        # granting tolerance: only the declared shared clock may order the seal.
        with mock.patch.object(q.time,'monotonic',return_value=c.deadline-8), \
                mock.patch.object(q,'execution_now',return_value=c.deadline+3):
            self.assertEqual(c.verify_expired_progress()[0],expected)
        with mock.patch.object(q.time,'monotonic',return_value=c.deadline+100), \
                mock.patch.object(q,'execution_now',return_value=c.deadline+.25):
            with self.assertRaisesRegex(RuntimeError,'genuine Pause prefix'):
                c.verify_expired_progress()

    async def test_missing_or_wrong_plan_and_receipt_clock_domain_refuses(self):
        await self.sealed();c=self.case
        for value in (None,'windows-gettickcount64-seconds-v1'):
            with self.subTest(location='plan',value=value):
                if value is None:c.plan.pop('deadline_clock')
                else:c.plan['deadline_clock']=value
                with self.assertRaisesRegex(RuntimeError,'genuine Pause prefix'):
                    c.verify_expired_progress()
                c.plan['deadline_clock']=q.CLOCK_ID
        path=c.work/f'result-{c.worker.pid}.json';saved=q.read(path)
        for value in (None,'windows-gettickcount64-seconds-v1'):
            altered=deepcopy(saved)
            if value is None:altered['paused_expiry'].pop('deadline_clock')
            else:altered['paused_expiry']['deadline_clock']=value
            q.rec.save(path,altered)
            with self.subTest(location='receipt',value=value),self.assertRaises(q.rec.RecoveryStop):
                c.verify_expired_progress()
        q.rec.save(path,saved)

    async def test_result_file_or_exit_without_retained_join_cannot_qualify(self):
        await self.sealed();c=self.case;joined=c.waits.pop(c.worker.pid)
        with self.assertRaisesRegex(RuntimeError,'retained join'):c.verify_expired_progress()
        c.waits[c.worker.pid]=joined
        for key,value in (('execution_expired',False),('task_completed',True),('worker_outcome','task_completed')):
            old=c.result[key];c.result[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,'retained join'):c.verify_expired_progress()
            c.result[key]=old

    async def test_changed_report_or_extra_effect_is_not_saved_progress(self):
        await self.sealed();c=self.case;report=c.work/'work/report.json';original=report.read_bytes()
        report.write_text('{}',encoding='utf-8')
        with self.assertRaises(q.rec.ReconciliationRequired):c.stop_binding._verify_exit(5)
        report.write_bytes(original)
        (c.work/'effect-receipts.jsonl').write_bytes(c.effects+c.effects)
        with self.assertRaisesRegex(RuntimeError,'single-write'):c.verify_expired_progress()

    async def test_wrong_native_history_receipt_and_deadline_do_not_qualify(self):
        await self.sealed();c=self.case;path=c.work/f'result-{c.worker.pid}.json';saved=q.read(path)
        for key,value in (('native_history_sha256','0'*64),('deadline_monotonic',c.deadline+1)):
            altered=deepcopy(saved);altered['paused_expiry'][key]=value;q.rec.save(path,altered)
            with self.subTest(key=key),self.assertRaises(q.rec.RecoveryStop):c.verify_expired_progress()
        q.rec.save(path,saved)
        c.paused_prefix['requests'].append({'request_id':'unobserved','sequence':4,'command':'resume'})
        with self.assertRaisesRegex(RuntimeError,'genuine Pause prefix'):c.verify_expired_progress()

    async def test_code_five_with_cleanup_error_is_not_verified_expiry(self):
        await self.sealed();c=self.case;path=c.work/f'result-{c.worker.pid}.json';saved=q.read(path)
        for key in ('cleanup_error','expiry_finalization_failed','error'):
            altered=deepcopy(saved);altered[key]='fixture failure';q.rec.save(path,altered)
            with self.subTest(key=key),self.assertRaises(q.rec.RecoveryStop):c.verify_expired_progress()
        q.rec.save(path,saved);c.worker.finish(2)
        with self.assertRaisesRegex(RuntimeError,'retained join'):c.verify_expired_progress()

    async def test_changed_wire_quality_or_request_accounting_refuses(self):
        await self.sealed();c=self.case;path=c.work/'wire-observations.json'
        altered=deepcopy(c.wires);altered[0]['model']='different';q.rec.save(path,altered)
        with self.assertRaisesRegex(RuntimeError,'quality, accounting'):c.verify_expired_progress()
        q.rec.save(path,c.wires)
        final=q.read(c.work/f'result-{c.worker.pid}.json');final['provider_calls']=2
        q.rec.save(c.work/f'result-{c.worker.pid}.json',final)
        with self.assertRaisesRegex(RuntimeError,'quality, accounting'):c.verify_expired_progress()


if __name__=='__main__':unittest.main()
