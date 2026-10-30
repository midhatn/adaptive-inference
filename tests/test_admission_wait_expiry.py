"""Original worker admission expiry; real SQLite, no actual SDK/model/process."""
from copy import deepcopy
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import (
    ACKS, EXECUTION_OUTCOME, WAIT_EXPIRY_SCHEMA, ControlBlocked, execution_outcome)
from adaptive_inference.desktop.hermes import recovery as rec, service_stop
from adaptive_inference.desktop.hermes.control_bridge import Controls, prepare_task
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.task_store import TaskStore, OwnershipError, ReconciliationRequired
from adaptive_inference.execution_clock import CLOCK_ID
from test_desktop_paused_expiry import ClosingDB, NOW
import safe_wait_fixture as fixture


class WorkerWaitTests(unittest.TestCase):
    exercise = fixture.SafeWaitCases.exercise
    preserve = fixture.SafeWaitCases.preserve
    verify_exit = fixture.SafeWaitCases.verify_exit
    record = fixture.SafeWaitCases.record
    test_stop_before_deadline_is_acknowledged_without_dispatch = fixture.SafeWaitCases.test_stop_before_deadline_is_acknowledged_without_dispatch
    test_cancel_before_deadline_stays_distinct = fixture.SafeWaitCases.test_cancel_before_deadline_stays_distinct

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        fixture.OUTPUT = Path(temp.name).resolve()
        fixture.SafeWaitCases.setUp(self)

    def common_preservation(self):
        cp, f = self.cp, self.fixture
        self.assertEqual((cp.prompt, cp.metadata, cp.max_attempts),
                         (f.original.prompt, f.original.metadata, 8))
        self.assertEqual(cp.state['session_id'], 'native')
        self.assertEqual(cp.state['deadline_monotonic'], 900.0)
        self.assertEqual(cp.state['deadline_clock'], CLOCK_ID)
        self.assertEqual((cp.state['status'], cp.state['phase']), ('pending', 'waiting_admission'))
        self.assertEqual(cp.state['pending_request'], self.pending)
        self.assertEqual(cp.state['native_history'], self.before_wait['native_history'])
        self.assertEqual(cp.state['native_history'], self.history)
        self.assertEqual(len(self.history), 3)
        self.assertEqual(cp.state['tools'], self.before_wait['tools'])
        self.assertEqual(len(cp.state['tools']), 1)
        self.assertEqual(cp.state['tools'][0]['name'], 'read_file')
        self.assertEqual((cp.state['requests'], cp.state['attempts'], cp.state['admission_attempts']), (1, 1, 1))
        self.assertIsNone(cp.owner_epoch); self.assertIsNone(cp.operation)
        self.assertFalse(cp.requires_reconciliation)
        service_stop.flushed_tools(cp.state)
        self.assertEqual(len(self.dispatched), 1); self.assertEqual(self.result['provider_calls'], 1)
        self.assertEqual(self.closed, ['agent', 'provider'])
        self.assertTrue(all(db.close_calls == 1 for db in f.opened))
        self.assertNotIn('cleanup_errors', self.result)
        self.assertNotIn('paused_expiry', self.result)
        self.assertFalse((f.run/'work/report.json').exists())
        self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def test_deadline_preserves_work_and_returns_distinct_verified_expiry(self):
        self.assertEqual(self.exercise('expiry'), 6, self.result)
        self.common_preservation()
        self.assertEqual(self.fixture.now, 900.0)
        marker = execution_outcome(self.cp.state)
        self.assertEqual(marker['schema'], WAIT_EXPIRY_SCHEMA)
        self.assertEqual(marker['pending_request_sha256'], rec.digest(self.pending))
        self.assertEqual(self.result['control_state'], 'waiting_admission')
        self.assertEqual(self.result['control_reason'], 'admission_wait_budget_expired')
        self.assertFalse(self.result['passed']); self.assertFalse(self.result['completed'])
        self.assertNotIn('error_type', self.result)
        before = self.fixture.box.snapshot()
        self.assertEqual(self.verify_exit(6, request_before_verify=True), 'admission_wait_budget_expired')
        self.assertEqual(self.fixture.box.snapshot(), before)  # Late post-seal Stop cannot append/ACK.
        for code in (2, 4, 5):
            with self.subTest(code=code), self.assertRaises((rec.RecoveryStop, KeyError)): self.verify_exit(code)

    def test_host_receipt_mutations_refuse_and_original_can_still_verify(self):
        self.assertEqual(self.exercise('expiry'), 6, self.result)
        path = self.fixture.run/f'result-{os.getpid()}.json'
        original = path.read_bytes()
        for key, value in (('pid', True), ('revision', self.cp.revision + 1),
                ('pending_request_sha256', 'a'*64), ('request_count', 0), ('task_completed', True)):
            row = json.loads(original); row['admission_wait_expiry'][key] = value
            path.write_text(json.dumps(row))
            with self.subTest(key=key), self.assertRaises(rec.RecoveryStop): self.verify_exit(6)
        path.write_bytes(original)
        self.assertEqual(self.verify_exit(6), 'admission_wait_budget_expired')

    def test_receipt_clock_refuses_before_seal_and_nonfinite_observations(self):
        self.assertEqual(self.exercise('expiry'), 6, self.result)
        for now in (899.999, float('nan'), float('inf'), float('-inf')):
            self.fixture.now = now
            with self.subTest(now=now), self.assertRaises(rec.RecoveryStop):
                self.verify_exit(6)
        for now in (900.0, 901.0):
            self.fixture.now = now
            with self.subTest(now=now):
                self.assertEqual(self.verify_exit(6), 'admission_wait_budget_expired')

    def test_original_claim_exit_failure_cannot_publish_safe_wait(self):
        from adaptive_inference import task_store
        actual = task_store._FileLock.close
        initialize = task_store._FileLock.__init__
        target = str(self.fixture.store.path) + '.task-' + hashlib.sha256(b'orders-report').hexdigest() + '.lock'
        def init(lock, path):
            initialize(lock, path); lock.wait_expiry_target = str(path) == target
        def close(lock):
            actual(lock)
            if lock.wait_expiry_target and EXECUTION_OUTCOME in self.fixture.store.load('orders-report').state:
                raise OSError('injected released lock close failure')
        with mock.patch.object(task_store._FileLock, '__init__', init), mock.patch.object(task_store._FileLock, 'close', close):
            self.assertEqual(self.exercise('expiry'), 2)
        self.assertNotIn('admission_wait_expiry', self.result)
        self.assertEqual(self.result['error_type'], 'OSError')

    def test_receipt_publication_failure_cannot_return_safe_exit(self):
        save = rec.save
        def fail(path, value):
            if Path(path).name.startswith('result-'):
                raise OSError('injected wait receipt failure')
            return save(path, value)
        with mock.patch.object(rec,'save',side_effect=fail), self.assertRaisesRegex(OSError,'wait receipt failure'):
            self.exercise('expiry')
        cp = self.fixture.store.load('orders-report')
        self.assertIsNone(cp.owner_epoch);self.assertIn(EXECUTION_OUTCOME,cp.state)
        self.assertFalse((self.fixture.run/f'result-{os.getpid()}.json').exists())


class WaitSealTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.run = Path(temp.name).resolve(); self.work = self.run/'work'; self.work.mkdir()
        self.db = ClosingDB(self.run/'native.sqlite3'); self.addCleanup(self.db.connection.close)
        self.db.append({'role':'user', 'content':'Saved original objective'})
        self.store = TaskStore(self.run/'task.sqlite3')
        self.identity = DemandIdentity('registered', 'task', 'host', NOW)
        self.original = prepare_task(self.store, self.identity, 'Saved original objective', 'native',
            metadata={'deadline_clock':CLOCK_ID, 'model':'exact-model'})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.cap = object(); self.box = Mailbox(self.registry, 'registered', requester_capability=self.cap)
        self.claim = self.store.claim('task', expected_revision=self.original.revision)
        self.owned = self.claim.__enter__(); self.addCleanup(self.release)
        self.box.submit(self.cap, 'genuine-resume', 'resume'); self.box.consume(self.owned, updated_at_utc=NOW)
        state = deepcopy(self.owned.checkpoint.state)
        self.request = {'model':'exact-model', 'messages':[{'role':'user','content':'Saved original objective'}],
                        'stream':False}
        state.update(phase='waiting_admission', pending_request=self.request, deadline_monotonic=10.0,
                     native_history=rec.native_history(self.db, 'native'))
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.now = 10.0
        self.controls = Controls(self.box, deadline=10.0, utc_now=lambda:NOW, clock=lambda:self.now,
                                 deadline_clock=CLOCK_ID)
        self.controller = rec.Recovery(self.owned, self.db, self.work, self.run, controls=self.controls)
        self.agent = SimpleNamespace(close=mock.Mock()); self.provider = SimpleNamespace(close=mock.Mock())

    def release(self):
        if self.claim is not None:
            self.claim.__exit__(None, None, None); self.claim = None

    def finalize(self):
        return service_stop.finalize_admission_wait_expiry(self.controller, agent=self.agent,
            db=self.db, provider=self.provider, session_db_factory=ClosingDB, pid=123)

    def test_valid_state_seals_only_marker_and_all_closed_resources(self):
        before = deepcopy(self.owned.checkpoint.state)
        proof = self.finalize(); after = deepcopy(self.owned.checkpoint.state)
        marker = after.pop(EXECUTION_OUTCOME)
        self.assertEqual(after, before)
        self.assertEqual(marker['schema'], WAIT_EXPIRY_SCHEMA)
        self.assertEqual(proof['state_sha256'], rec.digest(self.owned.checkpoint.state))
        self.assertEqual(proof['pending_request_sha256'], rec.digest(self.request))
        self.agent.close.assert_called_once(); self.provider.close.assert_called_once()
        self.assertEqual(self.db.close_calls, 1)

    def test_initial_and_during_close_pause_suffix_remains_unacknowledged(self):
        self.box.submit(self.cap, 'late-stop-before-observation', 'pause')
        self.agent.close.side_effect = lambda:self.box.submit(self.cap, 'late-stop-during-close', 'pause')
        proof = self.finalize(); snap = self.box.snapshot()
        self.assertEqual((proof['request_count'], proof['ack_count']), (3, 1))
        self.assertEqual([r['command'] for r in snap.receipts], ['resume'])
        self.assertEqual([r['command'] for r in snap.requests], ['resume', 'pause', 'pause'])
        self.assertTrue(self.box.admission_wait_candidate(snap, allow_sealed=True))

    def test_pending_resume_refuses_before_close(self):
        self.box.submit(self.cap, 'late-resume', 'resume')
        with self.assertRaises(ControlBlocked): self.finalize()
        self.agent.close.assert_not_called()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_pending_cancel_alone_refuses_before_close(self):
        self.box.submit(self.cap, 'late-cancel', 'cancel')
        with self.assertRaises(ControlBlocked): self.finalize()
        self.agent.close.assert_not_called()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_cancel_appended_during_close_refuses_seal(self):
        self.agent.close.side_effect = lambda:self.box.submit(self.cap, 'late-cancel', 'cancel')
        with self.assertRaises(ControlBlocked): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)
        self.assertEqual(len(self.box.snapshot().receipts), 1)

    def test_resume_appended_during_close_refuses_seal(self):
        self.agent.close.side_effect = lambda:self.box.submit(self.cap, 'late-resume', 'resume')
        with self.assertRaises(ControlBlocked): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_applied_cancel_is_not_safe_wait_expiry(self):
        self.box.submit(self.cap, 'cancel', 'cancel'); self.box.consume(self.owned, updated_at_utc=NOW)
        with self.assertRaises(ControlBlocked): self.finalize()
        self.assertEqual(self.box.snapshot().demand['state'], 'cancelled')
        self.agent.close.assert_not_called()

    def test_early_or_changed_clock_refuses_before_resources_close(self):
        self.now = 9.0
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.now = 10.0; self.controls.deadline_clock = 'wrong'
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.agent.close.assert_not_called()

    def test_pending_request_or_accounting_change_invalidates_old_observation(self):
        observation = self.box.admission_wait_observation(self.owned)
        state = deepcopy(self.owned.checkpoint.state); state['pending_request']['messages'][0]['content']='changed'
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked):
            self.box.seal_admission_wait(self.owned, observed_wait=observation, deadline_monotonic=10.0,
                sealed_at_monotonic=10.0, deadline_clock=CLOCK_ID)
        state = deepcopy(self.owned.checkpoint.state); state['admission_attempts']=1
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_malformed_ack_and_foreign_owner_refuse(self):
        state = deepcopy(self.owned.checkpoint.state); state[ACKS]['receipts'][0]['command']='cancel'
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked): self.finalize()
        with self.assertRaises(OwnershipError): self.box.admission_wait_observation(object())
        self.agent.close.assert_not_called()

    def test_history_mutation_never_seals(self):
        self.agent.close.side_effect=lambda:self.db.append({'role':'assistant','content':'unexpected late write'})
        with self.assertRaises(ReconciliationRequired): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_false_queue_drain_never_seals(self):
        self.db.flush_result=False
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME, self.owned.checkpoint.state)

    def test_generating_phase_refuses(self):
        state=deepcopy(self.owned.checkpoint.state); state['phase']='generating'
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked): self.finalize()
        self.agent.close.assert_not_called()

    def test_unflushed_native_tool_intent_refuses(self):
        self.db.append({'role':'assistant','content':None,'tool_calls':[{'id':'unflushed', 'type':'function',
            'function':{'name':'read_file','arguments':json.dumps({'path':'orders.csv'})}}]})
        state=deepcopy(self.owned.checkpoint.state); state['native_history']=rec.native_history(self.db,'native')
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.agent.close.assert_not_called()

    def test_missing_pending_request_and_inflight_state_refuse(self):
        state=deepcopy(self.owned.checkpoint.state); state['pending_request']=None
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        state=deepcopy(self.owned.checkpoint.state);state['pending_request']=self.request
        self.owned.begin_operation('generation',details={'unknown':True},state=state,
                                  expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked): self.finalize()
        self.agent.close.assert_not_called()

    def test_new_outcome_never_reopens_original_execution(self):
        self.finalize(); before=self.box.snapshot()
        result=self.box.submit(self.cap, 'too-late-resume','resume')
        self.assertEqual(result.reason,'execution_budget_expired')
        self.assertEqual(self.box.snapshot(),before)
        with self.assertRaises(ReconciliationRequired): self.controls.poll(self.owned)

    def test_sealed_pending_request_mutation_is_rejected(self):
        self.finalize()
        state=deepcopy(self.owned.checkpoint.state)
        state['pending_request']['messages'][0]['content']='different goal'
        with self.assertRaises(ControlBlocked):execution_outcome(state)
        state=deepcopy(self.owned.checkpoint.state)
        state[EXECUTION_OUTCOME]['ack_count']=True
        with self.assertRaises(ControlBlocked):execution_outcome(state)

    def test_host_candidate_original_binding_and_ui_continue_are_strict(self):
        from adaptive_inference.desktop.composition import DesktopComposition
        from adaptive_inference.desktop.hermes.continuation import LINK
        from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
        c=object.__new__(DesktopComposition)
        c.original=self.original;c.deadline=10.0
        binding=object.__new__(service_stop.WorkerStopBinding)
        binding.mailbox=self.box;binding.original=self.original
        binding.deadline=10.0;binding.deadline_clock=CLOCK_ID
        c.stop_binding=binding
        c.runtime=SimpleNamespace(refresh=mock.AsyncMock(),_cache=SimpleNamespace(snapshot=self.box.snapshot()))
        self.assertTrue(asyncio.run(c._admission_wait_expiry_candidate()))
        c.runtime._cache.snapshot.target.metadata[LINK]={'selected':True}
        with self.assertRaises(rec.RecoveryStop):
            asyncio.run(c._admission_wait_expiry_candidate())
        self.finalize();self.release()
        snapshot=self.box.snapshot();c.runtime._cache.snapshot=snapshot
        self.assertTrue(asyncio.run(c._admission_wait_expiry_candidate()))
        ui=object.__new__(MailboxRuntime)
        ui._owner=lambda:None;ui._cache=SimpleNamespace(snapshot=snapshot)
        ui._check_observation=lambda value:value.snapshot
        ui._transitioning=ui._stopping=ui._task_retired=False;ui._faults=[]
        ui.mailbox=self.box
        ui.lifecycle=SimpleNamespace(status=lambda:{'host_phase':'parked','waiting_reason':'resources'})
        ui._continuation_phase='available';ui._continuation_request=None;ui._continuation=object()
        ui._selection={'execution_id':'task','execution_generation':0}
        status=ui.status()
        self.assertEqual(status['waiting_reason'],'budget_expired')
        self.assertEqual(status['continuation'],{'phase':'available','request_id':None})
        self.assertEqual(status['task_status'],'pending')

    def test_worker_stop_subclass_cannot_claim_original_only_outcome(self):
        proof=self.finalize();self.release(); cp=self.store.load('task')
        original_result={'model':'exact-model','quality':{},'owner_epoch':proof['owner_epoch'],
            'admission_wait_expiry':proof,'passed':False,'completed':False,'controlled':True,
            'control_state':'waiting_admission','control_reason':'admission_wait_budget_expired'}
        (self.run/'result-123.json').write_text(json.dumps(original_result))
        class SelectedShape(service_stop.WorkerStopBinding): pass
        binding=object.__new__(SelectedShape)
        binding.mailbox=self.box;binding.original=self.original;binding.deadline=10.0
        binding.deadline_clock=CLOCK_ID;binding.run=self.run;binding.diagnostics=self.run
        binding.worker=SimpleNamespace(pid=123);binding.model='exact-model';binding.quality={}
        with self.assertRaises(rec.RecoveryStop):binding._verify_exit(6)

    def test_host_append_competing_with_seal_cannot_commit_after_marker(self):
        actual=self.store._write;entered=threading.Event();rows=[];failures=[];threads=[]
        def submit():
            entered.set()
            try:rows.append(self.box.submit(self.cap,'append-racing-seal','pause'))
            except BaseException as exc:failures.append(exc)
        def write(db,cp,**kwargs):
            if EXECUTION_OUTCOME in kwargs['state']:
                thread=threading.Thread(target=submit);threads.append(thread);thread.start()
                self.assertTrue(entered.wait(3))
            return actual(db,cp,**kwargs)
        before=self.box.snapshot()
        try:
            with mock.patch.object(self.store,'_write',side_effect=write):self.finalize()
        finally:
            for thread in threads:thread.join(5)
        self.assertTrue(threads);self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(failures,[]);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].reason,'execution_budget_expired')
        after=self.box.snapshot()
        self.assertEqual(after.requests,before.requests);self.assertEqual(after.receipts,before.receipts)


class AdmissionStopTests(unittest.TestCase):
    def test_later_original_task_can_stop_without_authorizing_another_task(self):
        import test_task_admission as admission_fixture
        from adaptive_inference.task_spec import TaskSpec
        f=admission_fixture.AdmissionTests();f.setUp();self.addCleanup(f.doCleanups)
        with f.claim() as host_owner:
            grant=f.reserve(host_owner);payload=grant['payload']
            preparing=f.admission.begin(host_owner,grant,action='prepare')
            run=Path(payload['run']);run.mkdir();work=run/'work';work.mkdir()
            store=TaskStore(run/'task.sqlite3')
            identity=DemandIdentity(**{k:payload['demand_identity'][k] for k in
                ('registration_id','task_id','owner_id','arrived_at_utc')})
            spec=TaskSpec(payload['task_spec'])
            original=prepare_task(store,identity,spec.prompt,payload['session_id'],metadata={
                **spec.metadata(),'pre_effect_validator':spec.validator_identity(),
                'deadline_clock':CLOCK_ID,'model':'exact-model'})
            f.admission.prepared(host_owner,grant,operation_id=preparing)
            launching=f.admission.begin(host_owner,grant,action='launch')
            db=ClosingDB(run/'native.sqlite3');self.addCleanup(db.connection.close)
            db.append({'role':'user','content':spec.prompt})
            registry=DemandRegistry((Registration(store,identity),));cap=object()
            box=Mailbox(registry,identity.registration_id,requester_capability=cap)
            box.submit(cap,'genuine-task-b-resume','resume')
            with store.claim(original.task_id,expected_revision=original.revision) as owned:
                box.consume(owned,updated_at_utc=NOW)
                state=deepcopy(owned.checkpoint.state)
                state.update(phase='waiting_admission',deadline_monotonic=10.0,
                    native_history=rec.native_history(db,payload['session_id']),
                    pending_request={'model':'exact-model','messages':[{'role':'user','content':spec.prompt}],'stream':False})
                owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
                controls=Controls(box,deadline=10.0,utc_now=lambda:NOW,clock=lambda:10.0,deadline_clock=CLOCK_ID)
                recovery=rec.Recovery(owned,db,work,run,controls=controls,
                    pre_effect_validator=spec.validate_write,validator_identity=spec.validator_identity())
                proof=service_stop.finalize_admission_wait_expiry(recovery,agent=SimpleNamespace(close=lambda:None),
                    db=db,provider=SimpleNamespace(close=lambda:None),session_db_factory=ClosingDB,pid=123)
            result={'model':'exact-model','quality':{},'owner_epoch':proof['owner_epoch'],
                'admission_wait_expiry':proof,'passed':False,'completed':False,'controlled':True,
                'control_state':'waiting_admission','control_reason':'admission_wait_budget_expired'}
            (run/'result-123.json').write_text(json.dumps(result))
            binding=object.__new__(service_stop.WorkerStopBinding)
            binding.mailbox=box;binding.original=original;binding.deadline=10.0;binding.deadline_clock=CLOCK_ID
            binding.run=binding.diagnostics=run;binding.worker=SimpleNamespace(pid=123,poll=lambda:6)
            binding.model='exact-model';binding.quality={}
            cp=store.load(original.task_id);before=store.history(cp.task_id)
            with self.assertRaisesRegex(ReconciliationRequired,'complete or be cancelled'):
                f.admission.finish(host_owner,grant,execution_id=cp.task_id,task_revision=cp.revision,
                    operation_id=launching,cleanup_sha256=admission_fixture.PROOF)
            stopped=f.admission.stop(host_owner,grant,cleanup_sha256=admission_fixture.PROOF,
                                     operation_id=launching,binding=binding)
            self.assertEqual(stopped['outcome'],'admission_wait_budget_expired')
            self.assertEqual(store.history(cp.task_id),before)
            self.assertTrue(f.admission.status()['host_stopped'])
            self.assertIsNone(f.admission.status()['operation'])
            self.assertEqual(store.load(cp.task_id).state['status'],'pending')
            with self.assertRaises(ReconciliationRequired):f.reserve(host_owner,f.request('must-not-admit-c'))


class WaitCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_remains_responsive_until_exact_join_and_new_proof(self):
        import test_desktop_expiry_composition as existing
        base=existing.ExpiryCompositionTests('test_active_or_unknown_expiry_remains_failure')
        await base.asyncSetUp();self.addCleanup(base.doCleanups)
        c=base.case;c.stop_binding._verify_exit.return_value='admission_wait_budget_expired'
        with mock.patch.object(c,'_paused_expiry_candidate',new=mock.AsyncMock(return_value=False)), \
                mock.patch.object(c,'_admission_wait_expiry_candidate',new=mock.AsyncMock(return_value=True)) as candidate:
            task=asyncio.create_task(c.interact())
            try:
                await base.until(lambda:candidate.await_count>0)
                self.assertFalse(task.done());self.assertFalse(c.result['execution_expired'])
                c.worker.code=6
                await base.until(lambda:c.worker.waits==1)
                for _ in range(3):await c.runtime.refresh();await asyncio.sleep(0)
                self.assertFalse(task.done());c.stop_binding._verify_exit.assert_not_called()
                c.worker.done.set();await base.until(lambda:c.result['execution_expired'])
                self.assertFalse(c.result['task_completed']);self.assertFalse(task.done())
                self.assertEqual(c.result['worker_outcome'],'admission_wait_budget_expired')
            finally:await base.stop(task)
        c.stop_binding._verify_exit.assert_called_once_with(6)
        c.facade.cooperative_stop.assert_awaited_once()


if __name__ == '__main__': unittest.main()
