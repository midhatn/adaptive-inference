"""Read-only completion/reopen evidence; inert artifacts, no SDK/compiler/model."""
import unittest
from unittest import mock

from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.compiler_evidence import verify_compiler_evidence
from adaptive_inference.desktop.saved_tasks import readonly_checkpoint
from adaptive_inference.task_store import TaskStore, ReconciliationRequired
import test_compiler_recovery as recovery_fixture


class CompilerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recovery_fixture.CompilerRecoveryTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def build(self, status='passed', *, flush=True):
        f = self.fixture
        f.status = status
        call, args = f.intent()
        result = f.dispatch(call, args)
        self.assertIsNone(f.controller.fatal)
        if flush:
            f.flush(call, result)
        return call, result

    def released(self):
        f = self.fixture
        f.release()
        checkpoint = readonly_checkpoint(f.run, 'task')
        self.assertIsNone(checkpoint.owner_epoch)
        return checkpoint, rec.native_history(f.db, 'session')

    def snapshot(self, *, active_owner=False):
        return {str(path.relative_to(self.fixture.run)): path.read_bytes()
                for path in self.fixture.run.rglob('*') if path.is_file()
                and not (active_owner and path.name.endswith('.lock'))}

    def test_completed_failure_then_success_reads_without_owner_or_any_mutation(self):
        f = self.fixture
        self.build('failed'); self.build('passed')
        f.db.append({'role': 'assistant', 'content': 'Compiled and checked.'})
        f.controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                             'final_response': 'Compiled and checked.'})
        cp, native = self.released()
        self.assertEqual(cp.state['status'], 'accepted')
        before = self.snapshot()
        with mock.patch.object(TaskStore, '__init__', side_effect=AssertionError('constructor used')), \
                mock.patch.object(TaskStore, 'claim', side_effect=AssertionError('worker claimed')):
            receipts = verify_compiler_evidence(cp, f.run, native)
        self.assertEqual([row['status'] for row in receipts], ['failed', 'passed'])
        self.assertTrue(f.spec.compiler_completion(receipts)['qualified'])
        self.assertEqual(self.snapshot(), before)

    def test_stopped_failed_attempt_is_evidence_without_claiming_completion(self):
        self.build('failed')
        cp, native = self.released()
        before = self.snapshot()
        receipts = verify_compiler_evidence(cp, self.fixture.run, native)
        self.assertEqual([row['status'] for row in receipts], ['failed'])
        self.assertFalse(self.fixture.spec.compiler_completion(receipts)['qualified'])
        self.assertEqual(self.snapshot(), before)

    def test_default_requires_native_result_and_live_flush_is_explicit(self):
        f = self.fixture
        call, result = self.build(flush=False)
        cp, native = f.owned.checkpoint, rec.native_history(f.db, 'session')
        with self.assertRaisesRegex(ReconciliationRequired, 'native history'):
            verify_compiler_evidence(cp, f.run, native)
        self.assertEqual(len(verify_compiler_evidence(cp, f.run, native, require_native_results=False)), 1)
        # The SDK's future append is not invented by the receipt verifier.
        # Windows deliberately prevents reads of the active task's locked byte;
        # saved-task cases above/below compare every file after owner release.
        before = self.snapshot(active_owner=True)
        self.assertEqual(len(f.controller.compiler_receipts()), 1)
        self.assertEqual(self.snapshot(active_owner=True), before)
        with self.assertRaises(ReconciliationRequired):
            f.controller.control_safe_point()
        f.flush(call, result)
        self.assertEqual(len(verify_compiler_evidence(f.owned.checkpoint, f.run,
                                                     rec.native_history(f.db, 'session'))), 1)

    def test_changed_native_result_is_refused_before_it_can_be_acknowledged(self):
        f = self.fixture
        call, result = self.build(flush=False)
        f.db.append({'role': 'tool', 'tool_call_id': call, 'content': result + 'changed'})
        cp, native = self.released()
        before = self.snapshot()
        with self.assertRaisesRegex(ReconciliationRequired, 'native history'):
            verify_compiler_evidence(cp, f.run, native)
        self.assertEqual(self.snapshot(), before)

    def test_artifact_tamper_is_refused_by_same_ownerless_reader(self):
        self.build()
        cp, native = self.released()
        (self.fixture.recipes[0].build/'program.stdout').write_bytes(b'wrong result')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            verify_compiler_evidence(cp, self.fixture.run, native)
        self.assertEqual(self.snapshot(), before)

    def test_stale_checkpoint_cannot_supply_old_receipts(self):
        f = self.fixture
        old = f.owned.checkpoint
        self.build()
        _, native = self.released()
        before = self.snapshot()
        with self.assertRaisesRegex(ReconciliationRequired, 'checkpoint changed'):
            verify_compiler_evidence(old, f.run, native)
        self.assertEqual(self.snapshot(), before)

    def test_missing_origin_history_refuses_without_repair_or_rewrite(self):
        # A direct fixture-only corruption removes an actual origin transaction.
        # The read-only inspection must not guess it from the current result.
        import sqlite3
        self.build()
        cp, native = self.released()
        with sqlite3.connect(self.fixture.run/'task.sqlite3') as db:
            db.execute("DELETE FROM history WHERE task_id=? AND event=?", ('task', 'operation_started'))
        before = self.snapshot()
        with self.assertRaisesRegex(ReconciliationRequired, 'completed origin operation'):
            verify_compiler_evidence(cp, self.fixture.run, native)
        self.assertEqual(self.snapshot(), before)
