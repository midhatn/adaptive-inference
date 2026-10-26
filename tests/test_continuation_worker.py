"""Selected real worker flow with actual SQLite and synthetic SDK components.

No model, provider HTTP, live process, host release or installed SDK acceptance.
The original expiry fixture supplies the unchanged setup/control test boundary.
"""
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference import task_store
from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.desktop.hermes import recovery as rec, run_recovery as worker, service_stop
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority
from adaptive_inference.desktop.hermes.continuation_worker import SelectedWorker, selected_worker, scope_for
import test_desktop_expiry_worker as existing
import test_desktop_report_feedback as feedback
import test_continuation_storage as storage_fixtures


class SelectedWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = existing.WorkerExpiryTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.run, self.store = self.f.run, self.f.store
        self.host = 'same-live-host'
        self.original_bytes = (self.run/'plan.json').read_bytes()

    def seed_report(self):
        db = existing.ClosingDB(self.run/'home/state.db')
        try:
            db.append({'role': 'user', 'content': worker.PROMPT})
            self.write_args = {'path': 'report.json', 'content': json.dumps(feedback.REPORT)}
            db.append({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'old-write',
                'type': 'function', 'function': {'name': 'write_file', 'arguments': json.dumps(self.write_args)}}]})
            cp = self.store.load('orders-report')
            with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
                controls = SimpleNamespace(poll=lambda owned: None)
                controller = rec.Recovery(owned, db, self.run/'work', self.run, controls=controls)
                def write(args):
                    (self.run/'work/report.json').write_text(args['content'], encoding='utf-8')
                    return json.dumps({'verified': True})
                result = controller.tool('write_file', self.write_args, write,
                                         session_id='native', tool_call_id='old-write')
                self.assertIsNone(controller.fatal)
                db.append({'role': 'tool', 'tool_call_id': 'old-write', 'content': result})
                controller.control_safe_point()
        finally:
            db.close()

    def authorize(self, *, report=False, requests=0):
        if report: self.seed_report()
        if requests:
            rows=[storage_fixtures.ContinuationTests.wire_row(None,index+1) for index in range(requests)]
            for row in rows:
                row.update(model=worker.MODEL,quality=worker.QUALITY,
                           url=self.f.plan['gateway']+'/chat/completions')
            rec.save(self.run/'wire-observations.json',rows)
            cp=self.store.load('orders-report')
            with self.store.claim(cp.task_id,expected_revision=cp.revision) as owned:
                state=deepcopy(owned.checkpoint.state)
                state.update(requests=requests,attempts=requests,admission_attempts=requests)
                owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        self.assertEqual(self.f.invoke(), 5)
        self.old = self.store.load('orders-report')
        self.old_rows = self.raw_old()
        self.old_result = (self.run/f'result-{os.getpid()}.json').read_bytes()
        if not (self.run/'wire-observations.json').exists():
            (self.run/'wire-observations.json').write_text('[]', encoding='utf-8')
        self.scope = scope_for(self.run, self.f.plan, self.original_bytes)
        self.authority = ContinuationAuthority(self.store, 'orders-report', self.scope,
                                               host_generation=self.host, clock=lambda: self.f.now)
        self.identity = DemandIdentity('successor-registration', 'orders-report.run-1', 'worker', existing.NOW)
        self.payload = self.authority.request(command_id='continue-click-1', predecessor_id=self.old.task_id,
            predecessor_revision=self.old.revision, predecessor_seal_sha256=rec.digest(self.old.state[EXECUTION_OUTCOME]),
            successor_id=self.identity.task_id, identity=self.identity, host_generation=self.host,
            release_evidence_sha256=rec.digest('Synthetic release evidence; no physical release claim'))
        cp = self.store.load(self.authority.task_id)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            self.grant = self.authority.authorize(owned, self.payload)
        self.grant_file = self.run/'selected-grant.json'
        rec.save(self.grant_file, self.grant)
        self.f.args.continuation_grant = self.grant_file
        self.f.args.host_generation = self.host
        self.f.args.deadline_monotonic = self.grant['deadline_monotonic']
        self.cap = object()
        self.box = Mailbox(DemandRegistry((Registration(self.store, self.identity),)),
                           self.identity.registration_id, requester_capability=self.cap)
        self.box.submit(self.cap, 'successor-pause', 'pause')
        self.f.args.stop_request_id = 'successor-pause'
        self.diagnostics = self.run/'executions'/self.identity.task_id

    def raw_old(self):
        with closing(sqlite3.connect(self.store.path)) as db:
            return (db.execute('SELECT * FROM tasks WHERE task_id=?', ('orders-report',)).fetchall(),
                    db.execute('SELECT * FROM history WHERE task_id=? ORDER BY revision', ('orders-report',)).fetchall())

    def unchanged_original(self):
        self.assertEqual(self.raw_old(), self.old_rows)
        self.assertEqual((self.run/'plan.json').read_bytes(), self.original_bytes)
        self.assertEqual((self.run/f'result-{os.getpid()}.json').read_bytes(), self.old_result)

    def result(self):
        return json.loads((self.diagnostics/f'result-{os.getpid()}.json').read_bytes())

    def assert_fenced(self):
        cp = self.store.load(self.authority.task_id)
        self.assertIsNone(cp.owner_epoch)
        self.assertIsNotNone(cp.operation)
        self.assertTrue(cp.requires_reconciliation)
        restored = ContinuationAuthority(self.store, 'orders-report', self.scope,
                                         host_generation=self.host, clock=lambda: self.f.now)
        self.assertEqual(restored.lookup(self.payload), self.grant)
        with self.store.claim(cp.task_id,expected_revision=cp.revision) as owned:
            with self.assertRaisesRegex(task_store.ReconciliationRequired,'unfinished worker lifecycle'):
                restored.authorize(owned,self.payload)
        with mock.patch.object(worker, 'setup', side_effect=AssertionError('SDK setup must not repeat')) as setup:
            with self.assertRaises(task_store.ReconciliationRequired): worker.worker(self.f.args)
        setup.assert_not_called()
        self.unchanged_original()

    def assert_owned(self):
        for task_id in (self.authority.task_id, self.identity.task_id):
            cp = self.store.load(task_id)
            self.assertIsNotNone(cp.owner_epoch)
            with self.assertRaises(task_store.TaskBusyError):
                with self.store.claim(task_id, expected_revision=cp.revision): pass
        self.assertIsNotNone(self.store.load(self.authority.task_id).operation)
        self.assertEqual(self.authority.lookup(self.payload), self.grant)

    def ready(self):
        self.box.submit(self.cap, 'derived-resume', 'resume')
        self.f.args.stop_request_id = None
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        self.f.args.controller_ready = self.diagnostics/'controller-ready.json'
        self.f.args.gateway_instance = 'same-gateway'
        row = {'ready': True, 'model': worker.MODEL, 'quality': worker.QUALITY,
               'gateway': self.f.plan['gateway'], 'gateway_instance': 'same-gateway',
               'observed_at': time.time(), 'selected_execution': {'execution_id': self.identity.task_id,
                   'execution_generation': self.grant['execution_generation']}}
        rec.save(self.f.args.controller_ready, row)
        return row

    def normal_patches(self):
        outer = self
        class Boundary:
            def __init__(self, run, fixture): self.run=run; self.rows=[]; self.steps={'parent':0}; self.seen=set()
        base = SimpleNamespace(Boundary=Boundary, REPORT=feedback.REPORT, snapshot=lambda agent: {'fixture': True},
                               git=lambda *a: worker.SDK_REV if a[0]=='rev-parse' else '')
        class Agent:
            def __init__(self, **kw):
                outer.assert_owned(); outer.agent_kwargs=kw
                self.session_id=kw['session_id']; self._session_db=kw['session_db']
                self._active_session_turn_lease_holder=None
            def run_conversation(self, prompt, conversation_history):
                outer.assert_owned(); outer.resumed_history=deepcopy(conversation_history)
                return {'completed': True, 'final_response': 'Existing report verified'}
            def close(self): outer.assert_owned(); outer.agent_closed=True
        sdk = ModuleType('run_agent'); sdk.AIAgent=Agent
        plugins = ModuleType('hermes_cli.plugins')
        plugins.get_plugin_manager=lambda: SimpleNamespace(_plugins={'recovery-checkpoint': SimpleNamespace(enabled=True,error=None)})
        interrupt = ModuleType('tools.interrupt'); interrupt.is_interrupted=lambda: False
        class Provider:
            def __init__(self, **kwargs):
                outer.assert_owned(); outer.provider_created=True
                boundary=kwargs['boundary']
                outer.boundary_projection=(deepcopy(boundary.rows),dict(boundary.steps),set(boundary.seen))
            def close(self): outer.assert_owned(); outer.provider_closed=True
        return (mock.patch.object(worker, 'setup', return_value=(rec,base)),
                mock.patch.dict(sys.modules, {'run_agent': sdk, 'hermes_cli.plugins': plugins, 'tools.interrupt': interrupt}),
                mock.patch('adaptive_inference.desktop.hermes.admission.Provider', Provider))

    def test_selected_stop_keeps_plan_predecessor_and_shared_state(self):
        self.authorize(report=True)
        report = (self.run/'work/report.json').read_bytes()
        effects = (self.run/'effect-receipts.jsonl').read_bytes()
        self.assertEqual(self.f.invoke(), service_stop.STOP_EXIT)
        result = self.result()
        self.assertTrue(result['service_stopped']); self.assertTrue(result['continuation_cleanup_verified'])
        self.assertFalse(result['passed']); self.assertFalse(result['completed'])
        self.assertEqual(result['selected_execution'], {'logical_task_id':'orders-report',
            'execution_id':self.identity.task_id,'execution_generation':1})
        self.assertIsNone(self.store.load(self.authority.task_id).operation)
        self.assertIsNone(self.store.load(self.identity.task_id).owner_epoch)
        self.assertEqual((self.run/'work/report.json').read_bytes(), report)
        self.assertEqual((self.run/'effect-receipts.jsonl').read_bytes(), effects)
        self.unchanged_original()

    def test_selected_expiry_closes_and_seals_only_successor(self):
        self.authorize(report=True); self.f.args.stop_request_id=None
        self.f.now=self.grant['deadline_monotonic']-.25
        self.assertEqual(self.f.invoke(), service_stop.PAUSED_EXPIRY_EXIT)
        cp = self.store.load(self.identity.task_id)
        self.assertIn(EXECUTION_OUTCOME, cp.state); self.assertEqual(cp.state['status'],'pending')
        self.assertTrue(self.result()['continuation_cleanup_verified'])
        self.assertIsNone(self.store.load(self.authority.task_id).operation)
        self.unchanged_original()

    def test_normal_completion_holds_both_claims_through_close_and_result(self):
        self.authorize(report=True); self.ready()
        original_save = rec.save
        def save(path, value):
            if Path(path).name.startswith('result-'):
                self.assert_owned(); self.assertTrue(self.agent_closed); self.assertTrue(self.provider_closed)
            return original_save(path,value)
        self.assertEqual(self.f.invoke(patches=(*self.normal_patches(), mock.patch.object(rec,'save',side_effect=save))),0)
        self.assertEqual(self.resumed_history,self.old.state['native_history'])
        self.assertEqual(self.agent_kwargs['session_id'],'native')
        self.assertEqual(self.agent_kwargs['cwd'],str(self.run/'work'))
        self.assertEqual(self.agent_kwargs['session_db'].db_path,self.run/'home/state.db')
        self.assertEqual(self.store.load(self.identity.task_id).state['status'],'accepted')
        self.assertTrue(self.result()['passed']); self.assertEqual(self.result()['provider_calls'],0)
        self.assertIsNone(self.store.load(self.authority.task_id).operation)
        self.unchanged_original()

    def test_cumulative_wire_counts_and_body_identities_reach_provider_unchanged(self):
        self.authorize(report=True,requests=2);self.ready()
        raw=(self.run/'wire-observations.json').read_bytes();rows=json.loads(raw)
        self.assertEqual(self.f.invoke(patches=self.normal_patches()),0)
        self.assertEqual(self.boundary_projection,(rows,{'parent':2},{row['body_sha256'] for row in rows}))
        state=self.store.load(self.identity.task_id).state
        self.assertEqual((state['requests'],state['attempts'],state['admission_attempts']),(2,2,2))
        self.assertEqual((self.run/'wire-observations.json').read_bytes(),raw)
        self.unchanged_original()

    def test_wire_mutation_after_result_cannot_complete_lifetime(self):
        self.authorize(requests=2);actual=rec.save
        def changed(path,value):
            actual(path,value)
            if Path(path).name.startswith('result-'):
                rows=json.loads((self.run/'wire-observations.json').read_bytes())
                rows[0]['response_sha256']=rec.digest('changed response')
                actual(self.run/'wire-observations.json',rows)
        with self.assertRaisesRegex(task_store.ReconciliationRequired,'Inherited wire prefix changed'):
            self.f.invoke(patches=(mock.patch.object(rec,'save',side_effect=changed),))
        self.assert_fenced()

    def test_failed_setup_leaves_durable_fence_and_historical_lookup(self):
        self.authorize()
        def fail(*args): self.assert_owned(); raise RuntimeError('setup failed')
        with self.assertRaisesRegex(RuntimeError,'setup failed'):
            self.f.invoke(patches=(mock.patch.object(worker,'setup',side_effect=fail),))
        self.assert_fenced()

    def test_failed_close_cannot_release_authority_for_duplicate_launch(self):
        self.authorize()
        outer=self
        class Broken(existing.ClosingDB):
            def close(self):
                outer.assert_owned(); super().close(); raise OSError('selected close failed')
        with self.assertRaisesRegex(task_store.ReconciliationRequired,'cleanup is unconfirmed'):
            self.f.invoke(database=Broken)
        self.assertTrue(self.result()['cleanup_errors'])
        self.assert_fenced()

    def test_result_write_failure_keeps_cleanup_fenced(self):
        self.authorize()
        original_save=rec.save
        def fail(path,value):
            if Path(path).name.startswith('result-'):
                self.assert_owned(); raise OSError('selected result publication failed')
            return original_save(path,value)
        with self.assertRaisesRegex(OSError,'publication failed'):
            self.f.invoke(patches=(mock.patch.object(rec,'save',side_effect=fail),))
        self.assert_fenced()

    def test_error_after_result_replace_still_fences(self):
        self.authorize(); original_save=rec.save
        def fail(path,value):
            original_save(path,value)
            if Path(path).name.startswith('result-'): raise OSError('after selected replacement')
        with self.assertRaisesRegex(OSError,'after selected'):
            self.f.invoke(patches=(mock.patch.object(rec,'save',side_effect=fail),))
        self.assertTrue(self.result()['continuation_cleanup_verified'])
        self.assert_fenced()

    def test_expiry_effect_receipt_mutation_after_close_is_refused(self):
        self.authorize(report=True); self.f.args.stop_request_id=None
        self.f.now=self.grant['deadline_monotonic']-.25
        actual=service_stop.close_safe_resources
        def changed(*args,**kwargs):
            proof=actual(*args,**kwargs)
            (self.run/'effect-receipts.jsonl').write_text('[]\n',encoding='utf-8')
            return proof
        with self.assertRaisesRegex(task_store.ReconciliationRequired,'cleanup is unconfirmed'):
            self.f.invoke(patches=(mock.patch.object(service_stop,'close_safe_resources',side_effect=changed),))
        self.assertNotIn('paused_expiry', self.result())
        self.assert_fenced()

    def test_effect_mutation_after_result_cannot_complete_lifetime(self):
        self.authorize(report=True); actual=rec.save
        def changed(path,value):
            actual(path,value)
            if Path(path).name.startswith('result-'):
                (self.run/'effect-receipts.jsonl').write_text('',encoding='utf-8')
        with self.assertRaisesRegex(task_store.ReconciliationRequired,'Physical effect receipts'):
            self.f.invoke(patches=(mock.patch.object(rec,'save',side_effect=changed),))
        self.assert_fenced()

    def test_native_history_mismatch_refused_before_provider(self):
        self.authorize(report=True)
        db=existing.ClosingDB(self.run/'home/state.db')
        db.append({'role':'assistant','content':'unexpected native row'});db.close()
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            with self.assertRaisesRegex(task_store.ReconciliationRequired,'cleanup is unconfirmed'): self.f.invoke()
        provider.assert_not_called(); self.assert_fenced()

    def test_changed_artifact_refused_before_provider(self):
        self.authorize(report=True)
        (self.run/'work/report.json').write_text('{}',encoding='utf-8')
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            with self.assertRaisesRegex(task_store.ReconciliationRequired,'cleanup is unconfirmed'): self.f.invoke()
        provider.assert_not_called(); self.assert_fenced()

    def test_old_generation_ready_refused_before_provider(self):
        self.authorize(); row=self.ready(); row['selected_execution']['execution_generation']=0
        rec.save(self.f.args.controller_ready,row)
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            self.assertEqual(self.f.invoke(),2)
        provider.assert_not_called()
        self.assertIn('another selected execution',self.result()['error'])
        self.assertIsNone(self.store.load(self.authority.task_id).operation)
        self.unchanged_original()

    def test_readiness_path_from_original_execution_refused(self):
        self.authorize(); row=self.ready()
        self.f.args.controller_ready=self.run/'controller-ready.json';rec.save(self.f.args.controller_ready,row)
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            self.assertEqual(self.f.invoke(),2)
        provider.assert_not_called();self.assertIn('execution directory',self.result()['error'])
        self.unchanged_original()

    def test_boolean_execution_generation_is_not_an_integer_ready_grant(self):
        self.authorize();row=self.ready();row['selected_execution']['execution_generation']=True
        rec.save(self.f.args.controller_ready,row)
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            self.assertEqual(self.f.invoke(),2)
        provider.assert_not_called();self.assertIn('another selected execution',self.result()['error'])

    def test_duplicate_readiness_key_refused_before_provider(self):
        self.authorize();row=self.ready()
        raw=json.dumps(row)
        self.f.args.controller_ready.write_text(raw[:-1]+',"selected_execution":'+json.dumps(row['selected_execution'])+'}')
        with mock.patch('adaptive_inference.desktop.hermes.admission.Provider',side_effect=AssertionError('provider forbidden')) as provider:
            self.assertEqual(self.f.invoke(),2)
        provider.assert_not_called();self.assertEqual(self.result()['error_type'],'ValueError')

    def test_busy_callback_refuses_concurrent_cleanup_and_keeps_fence(self):
        self.authorize(); release=threading.Event();entered=threading.Event();threads=[]
        actual=service_stop.StopAtPause.__call__
        def stop(callback,owned,boundary):
            try:return actual(callback,owned,boundary)
            except service_stop.ProductStop:
                def hold():
                    with callback.recovery.lock: entered.set();release.wait(10)
                thread=threading.Thread(target=hold);threads.append(thread);thread.start()
                # StopAtPause runs while Recovery holds its RLock; start the
                # holder only after that owner unwinds, immediately before close.
                raise
        actual_cleanup=__import__('adaptive_inference.desktop.hermes.pause_activity',fromlist=['PauseActivity']).PauseActivity.cleanup_scope
        from adaptive_inference.desktop.hermes.pause_activity import PauseActivity
        def cleanup(activity,*args,**kwargs):
            self.assertTrue(entered.wait(2)); return actual_cleanup(activity,*args,**kwargs)
        try:
            with self.assertRaisesRegex(task_store.ReconciliationRequired,'cleanup is unconfirmed'):
                self.f.invoke(patches=(mock.patch.object(service_stop.StopAtPause,'__call__',stop),
                    mock.patch.object(PauseActivity,'cleanup_scope',cleanup)))
            self.assertIn('still owns recovery',self.result()['cleanup_errors'][0]['message'])
            self.assert_fenced()
        finally:
            release.set()
            for thread in threads:thread.join(2);self.assertFalse(thread.is_alive())
            for db in self.f.opened:
                if not db.close_calls: db.close()

    def test_completed_write_reused_with_same_session_and_physical_receipt(self):
        self.authorize(report=True)
        before=(self.run/'effect-receipts.jsonl').read_bytes()
        # The existing Recovery duplicate-effect mechanism is exercised under
        # both actual claims, without dispatching a provider or SDK conversation.
        with self.assertRaisesRegex(task_store.ReconciliationRequired,'did not finish'):
            with selected_worker(self.run,self.grant,host_generation=self.host,
                    deadline=self.grant['deadline_monotonic'],clock=lambda:self.f.now) as selected:
                db=existing.ClosingDB(self.run/'home/state.db')
                try:
                    selected.verify_native(db)
                    db.append({'role':'assistant','content':None,'tool_calls':[{'id':'retry-write','type':'function',
                        'function':{'name':'write_file','arguments':json.dumps(self.write_args)}}]})
                    controller=rec.Recovery(selected.owned,db,self.run/'work',self.run,
                        controls=SimpleNamespace(poll=lambda owned:None))
                    dispatch=mock.Mock(side_effect=AssertionError('Completed effect must not repeat'))
                    answer=controller.tool('write_file',self.write_args,dispatch,session_id='native',tool_call_id='retry-write')
                    dispatch.assert_not_called();self.assertIsNone(controller.fatal)
                    db.append({'role':'tool','tool_call_id':'retry-write','content':answer})
                    controller.control_safe_point();selected.verify_native(db)
                    self.assertTrue(selected.owned.checkpoint.state['tools'][-1]['reused'])
                    self.assertEqual((self.run/'effect-receipts.jsonl').read_bytes(),before)
                finally:db.close()
        self.assert_fenced()

    def test_changed_original_plan_refused_before_setup(self):
        self.authorize(); (self.run/'plan.json').write_bytes(self.original_bytes+b'\n')
        with mock.patch.object(worker,'setup',side_effect=AssertionError('setup forbidden')) as setup:
            with self.assertRaises(task_store.ReconciliationRequired): worker.worker(self.f.args)
        setup.assert_not_called()
        self.assertIsNone(self.store.load(self.authority.task_id).operation)


if __name__=='__main__':unittest.main()
