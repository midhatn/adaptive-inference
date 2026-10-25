"""Paused-expiry ownership and native SQLite projection; no SDK/model/UI launch."""
import asyncio
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME, ControlBlocked, execution_outcome
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.task_store import TaskStore, ReconciliationRequired
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.control_bridge import prepare_task, Controls
from adaptive_inference.desktop.hermes.service_stop import finalize_paused_expiry, WorkerStopBinding, PAUSED_EXPIRY_EXIT
from test_desktop_report_feedback import NativeDB

NOW = '2026-10-25T12:00:00Z'


class ClosingDB(NativeDB):
    """Existing SQLite native projection plus explicit SDK-lifecycle fixture fields."""
    def __init__(self, path, read_only=False):
        self.db_path, self.read_only = Path(path).resolve(), read_only
        if read_only:
            self.connection = sqlite3.connect(self.db_path.as_uri()+'?mode=ro', uri=True)
        else:
            super().__init__(self.db_path)
        self._token_writer_thread = None
        self._token_queue_cond = threading.Condition()
        self._token_queue = deque()
        self._token_writer_busy = False
        self._token_writer_stop = False
        self.flush_result = True
        self.before_close = None
        self.close_calls = 0
    def flush_token_counts(self, timeout=5.0):
        self.flush_timeout = timeout
        return self.flush_result
    def close(self):
        self.close_calls += 1
        if self.before_close is not None:
            self.before_close(self)
        self._token_writer_stop = True
        super().close()


class PausedExpiryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name).resolve()
        self.work = self.run/'work'; self.work.mkdir()
        self.db = ClosingDB(self.run/'native.sqlite3')
        self.addCleanup(self.db.connection.close)
        self.db.append({'role':'user','content':'Original objective'})
        self.store = TaskStore(self.run/'task.sqlite3')
        self.identity = DemandIdentity('registered','task','host',NOW)
        self.original = prepare_task(self.store,self.identity,'Original objective','native',metadata={})
        self.registry = DemandRegistry((Registration(self.store,self.identity),))
        self.cap = object()
        self.box = Mailbox(self.registry,'registered',requester_capability=self.cap)
        self.claim = self.store.claim('task',expected_revision=self.original.revision)
        self.owned = self.claim.__enter__()
        self.addCleanup(self.release)
        state = deepcopy(self.owned.checkpoint.state)
        state.update(deadline_monotonic=10.0,native_history=rec.native_history(self.db,'native'))
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        self.now = 9.0
        self.controls = Controls(self.box,deadline=10.0,utc_now=lambda:NOW,
            clock=lambda:self.now,sleep=self.advance)
        self.controller = rec.Recovery(self.owned,self.db,self.work,self.run,controls=self.controls)
        self.agent = SimpleNamespace(close=mock.Mock())
        self.provider = SimpleNamespace(close=mock.Mock())

    def advance(self, seconds):
        self.now += seconds

    def release(self):
        if self.claim is not None:
            self.claim.__exit__(None,None,None); self.claim = None

    def pause(self):
        self.box.submit(self.cap,'genuine-pause','pause')
        with self.assertRaises(rec.ControlStop) as raised:
            self.controller.control_safe_point()
        self.assertEqual(raised.exception.reason,'control_wait_deadline')
        return raised.exception

    def finalize(self, **changes):
        options = dict(agent=self.agent,db=self.db,provider=self.provider,
                       session_db_factory=ClosingDB,clock=lambda:self.now,pid=123)
        options.update(changes)
        return finalize_paused_expiry(self.controller,**options)

    def test_valid_pause_finalizes_under_owner_then_seals_only_new_marker(self):
        self.pause()
        before = self.owned.checkpoint
        self.agent.close.side_effect = lambda:self.assertEqual(self.store.load('task').owner_epoch,before.owner_epoch)
        proof = self.finalize()
        after = self.owned.checkpoint
        state = deepcopy(after.state)
        marker = state.pop(EXECUTION_OUTCOME)
        self.assertEqual(state,before.state)
        self.assertEqual(marker['pause_observed_at_monotonic'],9.0)
        self.assertEqual(proof['state_sha256'],rec.digest(after.state))
        self.assertEqual(self.db.flush_timeout,5.0)
        self.assertEqual(self.db.close_calls,1)
        self.agent.close.assert_called_once(); self.provider.close.assert_called_once()
        self.assertEqual(after.owner_epoch,before.owner_epoch)
        self.release()
        self.assertIsNone(self.store.load('task').owner_epoch)

    def test_late_pause_gets_no_predeadline_observation_or_seal(self):
        self.now = 10.0
        self.pause()
        self.assertIsNone(self.controls.paused_expiry_observation)
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)
        self.agent.close.assert_not_called()

    def test_timestamp_follows_slow_coherent_pause_read(self):
        actual = self.box.paused_execution_observation
        def slow(owned):
            value = actual(owned); self.now = 10.0; return value
        with mock.patch.object(self.box,'paused_execution_observation',side_effect=slow):
            self.pause()
        self.assertIsNone(self.controls.paused_expiry_observation)

    def test_allowed_resume_at_deadline_cannot_start_work(self):
        self.box.submit(self.cap,'resume','resume')
        self.now = 10.0
        with self.assertRaises(rec.ControlStop) as raised:
            self.controls.poll(self.owned)
        self.assertEqual(raised.exception.control_state,'active')
        self.assertIsNone(self.controls.paused_expiry_observation)

    def test_real_cancellation_at_deadline_retains_its_distinct_outcome(self):
        self.box.submit(self.cap,'cancel','cancel'); self.now = 10.0
        with self.assertRaises(rec.ControlStop) as raised:
            self.controls.poll(self.owned)
        self.assertEqual(raised.exception.control_state,'cancelled')
        self.assertIsNone(self.controls.paused_expiry_observation)

    def test_prefix_change_clears_predeadline_pause_observation(self):
        self.box.submit(self.cap,'pause-one','pause')
        def changed(seconds):
            self.box.submit(self.cap,'pause-two','pause'); self.now = 10.0
        self.controls.sleep = changed
        with self.assertRaises(rec.ControlStop): self.controller.control_safe_point()
        self.assertIsNone(self.controls.paused_expiry_observation)

    def test_resumed_work_clears_old_pause_observation(self):
        self.box.submit(self.cap,'pause-one','pause')
        def resumed(seconds):
            self.box.submit(self.cap,'resume','resume'); self.now = 9.5
        self.controls.sleep = resumed
        self.controller.control_safe_point()
        self.assertIsNone(self.controls.paused_expiry_observation)

    def test_agent_close_history_mutation_is_rejected(self):
        self.pause()
        self.agent.close.side_effect = lambda:self.db.append({'role':'assistant','content':'late mutation'})
        with self.assertRaises(ReconciliationRequired): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_database_close_history_mutation_is_rejected(self):
        self.pause()
        self.db.before_close = lambda db:db.append({'role':'assistant','content':'late close mutation'})
        with self.assertRaises(ReconciliationRequired): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_false_or_exceptional_flush_never_seals(self):
        self.pause(); self.db.flush_result = False
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        with mock.patch.object(self.db,'flush_token_counts',side_effect=OSError('flush failed')):
            with self.assertRaises(OSError): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_still_live_exact_writer_is_rejected_after_close(self):
        self.pause()
        release = threading.Event()
        writer = threading.Thread(target=lambda:release.wait(3))
        writer.start(); self.db._token_writer_thread = writer
        try:
            with self.assertRaises(rec.RecoveryStop): self.finalize()
        finally:
            release.set(); writer.join(3)
        self.assertFalse(writer.is_alive())
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_replaced_writer_or_unknown_drain_is_rejected(self):
        self.pause()
        self.db._token_writer_thread = threading.Thread(target=lambda:None)
        self.agent.close.side_effect = lambda:setattr(self.db,'_token_writer_thread',threading.Thread(target=lambda:None))
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.agent.close.side_effect = None; self.db._token_writer_thread = None
        self.db._token_writer_busy = True
        with self.assertRaises(rec.RecoveryStop): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_read_only_reopen_and_provider_close_failure_never_seal(self):
        self.pause()
        with self.assertRaises(OSError):
            self.finalize(session_db_factory=mock.Mock(side_effect=OSError('read reopen failed')))
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_provider_close_failure_after_final_projection_never_seals(self):
        self.pause(); self.provider.close.side_effect = OSError('provider close failed')
        with self.assertRaises(OSError): self.finalize()
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_late_command_during_cleanup_cannot_be_erased_by_seal(self):
        self.pause()
        self.agent.close.side_effect = lambda:self.box.submit(self.cap,'late-resume','resume')
        with self.assertRaises(ControlBlocked): self.finalize()
        self.assertEqual(self.box.status('late-resume')['outcome'],'pending')
        self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)

    def test_sealed_execution_refuses_bootstrap_and_recovery(self):
        self.pause(); self.finalize()
        with self.assertRaises(ReconciliationRequired): self.controls.bootstrap(self.owned)
        with self.assertRaises(ReconciliationRequired): self.controller.control_safe_point()
        with self.assertRaises(ReconciliationRequired): rec.resumable(self.owned,self.db,self.work)

    def test_exit5_receipt_binds_actual_released_checkpoint_and_rejects_errors(self):
        self.pause(); proof = self.finalize(); self.release()
        result = dict(passed=False,completed=False,controlled=True,control_state='paused',
            control_reason='paused_budget_expired',paused_expiry=proof,owner_epoch=proof['owner_epoch'],
            model='fixture',quality={})
        path = self.run/'result-123.json'
        async def verify():
            child = SimpleNamespace(pid=123,poll=lambda:5,wait=lambda:5)
            binding = WorkerStopBinding(child,self.run,self.box,requester_capability=self.cap,
                capability=object(),stop_request_id='stop',original=self.original,
                deadline_monotonic=10.0,model='fixture',quality={},fence=lambda:None)
            rec.save(path,result)
            self.assertEqual(binding._verify_exit(PAUSED_EXPIRY_EXIT),'paused_budget_expired')
            for key in ('error','cleanup_error','cleanup_errors','traceback_private'):
                rec.save(path,{**result,key:'failed after seal'})
                with self.subTest(key=key),self.assertRaises(rec.RecoveryStop):binding._verify_exit(5)
            rec.save(path,result)
            with self.assertRaises(rec.RecoveryStop):binding._verify_exit(2)
            for key, value in (('pid',124),('revision',True),('pause_sequence',True),('state_sha256','0'*64)):
                rec.save(path,{**result,'paused_expiry':{**proof,key:value}})
                with self.subTest(key=key),self.assertRaises(rec.RecoveryStop):binding._verify_exit(5)
        asyncio.run(verify())

    def test_sealed_replacement_is_refused_before_launch_callback(self):
        self.pause();self.finalize();self.release()
        async def replace():
            from adaptive_inference.desktop.desktop_controls import DesktopControlLifecycle
            from adaptive_inference.desktop.control_transport import PreparedTask
            import test_desktop_lifecycle as fixture
            child=SimpleNamespace(pid=123,poll=lambda:5,wait=lambda timeout=0:5)
            cap=object()
            binding=WorkerStopBinding(child,self.run,self.box,requester_capability=self.cap,
                capability=cap,stop_request_id='stop',original=self.original,
                deadline_monotonic=10.0,model='fixture',quality={},fence=lambda:None)
            facade=DesktopControlLifecycle(SimpleNamespace(closing=False,closed=False),
                PreparedTask('host','task','Original objective'),worker_stop=binding,
                worker_capability=cap,gui=fixture.GUI())
            launch=mock.Mock(side_effect=AssertionError('must not launch'))
            with self.assertRaisesRegex(RuntimeError,'known paused task'):
                facade.replace_worker(binding,launch)
            launch.assert_not_called();self.assertEqual(facade.worker_replacements,[])
        asyncio.run(replace())


if __name__ == '__main__':
    unittest.main()
