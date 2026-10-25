"""Qualification release using actual TaskStore/controls, never an agent/model."""
import ast
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'hermes'), str(HERE/'src')]
from adaptive_inference.control_mailbox import ACKS, ControlBlocked, Mailbox
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.task_store import OwnershipError, TaskStore
from control_bridge import prepare_task
from run_recovery import MODEL, PROMPT, QUALITY, qualification_report_resumed

NOW = '2026-10-25T10:00:00Z'


class ReportHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name)/'task.sqlite3')
        self.identity = DemandIdentity('report-hold', 'orders-report', 'fixture-owner', NOW)
        cp = prepare_task(self.store, self.identity, PROMPT, 'saved-native-session',
                          metadata={'model': MODEL, 'quality': deepcopy(QUALITY)}, max_attempts=8)
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.capability = object()
        self.mailbox = Mailbox(self.registry, self.identity.registration_id,
                               requester_capability=self.capability)
        self.context = self.store.claim(cp.task_id, expected_revision=cp.revision)
        self.owned = self.context.__enter__()
        self.addCleanup(self.release)
        state = deepcopy(self.owned.checkpoint.state)
        state.update(deadline_monotonic=123456.75, requests=2, attempts=2,
                     admission_attempts=2, native_history=[{'role': 'user', 'content': PROMPT}])
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.registry.transition(self.identity.registration_id, self.owned, 'waiting',
            expected_revision=self.owned.checkpoint.revision, updated_at_utc=NOW,
            reason='qualification fixture safe report checkpoint')

    def release(self):
        if self.context is not None:
            self.context.__exit__(None, None, None)
            self.context = None

    def submit(self, request_id, command, *, consume=True):
        self.mailbox.submit(self.capability, request_id, command)
        if consume: self.mailbox.consume(self.owned, updated_at_utc=NOW)

    def resumed(self):
        return qualification_report_resumed(self.mailbox, self.owned)

    def ready(self):
        self.submit('pause-after-safe', 'pause')
        self.submit('gui-resume-a1b2c3', 'resume')

    def test_arbitrary_gui_resume_after_exact_applied_pause_releases(self):
        self.ready()
        self.assertTrue(self.resumed())
        self.assertNotIn('resume-after-safe', [r['request_id'] for r in self.mailbox.snapshot().requests])

    def test_historical_qualification_resume_still_releases_after_exact_pause(self):
        self.submit('pause-after-safe', 'pause')
        self.submit('resume-after-safe', 'resume')
        self.assertTrue(self.resumed())

    def test_earlier_resume_never_substitutes_for_later_pause(self):
        self.submit('resume-before-report', 'resume')
        self.assertFalse(self.resumed())
        self.submit('pause-after-safe', 'pause')
        self.assertFalse(self.resumed())

    def test_other_pause_id_is_not_the_exact_report_anchor(self):
        self.submit('gui-pause', 'pause')
        self.submit('gui-resume', 'resume')
        self.assertFalse(self.resumed())

    def test_anchor_id_with_wrong_command_refuses(self):
        self.submit('pause-after-safe', 'resume')
        self.submit('gui-resume', 'resume')
        self.assertFalse(self.resumed())

    def test_recorded_pause_and_resume_without_owner_ack_refuse(self):
        self.submit('pause-after-safe', 'pause', consume=False)
        self.submit('gui-resume', 'resume', consume=False)
        self.assertEqual(self.mailbox.snapshot().demand['state'], 'waiting')
        self.assertFalse(self.resumed())
        self.mailbox.consume(self.owned, updated_at_utc=NOW)
        self.assertTrue(self.resumed())

    def test_waiting_transition_without_resume_ack_cannot_release(self):
        self.submit('pause-after-safe', 'pause')
        self.submit('gui-resume', 'resume', consume=False)
        self.registry.transition(self.identity.registration_id, self.owned, 'waiting',
            expected_revision=self.owned.checkpoint.revision, updated_at_utc=NOW,
            reason='simulate existing transition-to-ACK two-commit gap')
        self.assertEqual(self.mailbox.status('gui-resume')['outcome'], 'pending')
        self.assertFalse(self.resumed())
        self.mailbox.consume(self.owned, updated_at_utc=NOW)
        self.assertTrue(self.resumed())

    def later(self, command, *, consume):
        self.ready()
        self.assertTrue(self.resumed())
        self.submit('later-'+command, command, consume=consume)
        self.assertFalse(self.resumed())

    def test_later_pending_pause_refuses_even_with_waiting_demand(self):
        self.later('pause', consume=False)
        self.assertEqual(self.mailbox.snapshot().demand['state'], 'waiting')

    def test_later_pending_cancel_refuses_even_with_waiting_demand(self):
        self.later('cancel', consume=False)
        self.assertEqual(self.mailbox.snapshot().demand['state'], 'waiting')

    def test_later_applied_pause_refuses(self): self.later('pause', consume=True)

    def test_later_applied_cancel_refuses(self): self.later('cancel', consume=True)

    def test_later_pending_resume_cannot_borrow_earlier_applied_resume(self):
        self.ready()
        self.submit('later-resume', 'resume', consume=False)
        self.assertFalse(self.resumed())
        self.mailbox.consume(self.owned, updated_at_utc=NOW)
        self.assertTrue(self.resumed())

    def test_rejected_resume_with_owner_ack_refuses(self):
        self.submit('pause-after-safe', 'pause')
        self.submit('cancel-report', 'cancel')
        self.submit('gui-resume', 'resume')
        status = self.mailbox.status('gui-resume')
        self.assertTrue(status['owner_acknowledged'])
        self.assertEqual(status['outcome'], 'rejected')
        self.assertFalse(self.resumed())

    def test_active_demand_is_not_waiting_report_resume(self):
        self.ready()
        self.registry.transition(self.identity.registration_id, self.owned, 'active',
            expected_revision=self.owned.checkpoint.revision, updated_at_utc=NOW,
            reason='fixture must not authorize another active operation')
        self.assertFalse(self.resumed())

    def test_inflight_operation_refuses(self):
        self.ready()
        self.owned.begin_operation('effect', details={'fixture': True},
                                  expected_revision=self.owned.checkpoint.revision)
        self.assertFalse(self.resumed())

    def test_reclaimed_unresolved_operation_requires_reconciliation_and_refuses(self):
        self.ready()
        self.owned.begin_operation('effect', details={'fixture': True},
                                  expected_revision=self.owned.checkpoint.revision)
        self.release()
        checkpoint = self.store.load(self.identity.task_id)
        self.context = self.store.claim(checkpoint.task_id, expected_revision=checkpoint.revision)
        self.owned = self.context.__enter__()
        self.assertTrue(self.owned.checkpoint.requires_reconciliation)
        self.assertFalse(self.resumed())

    def test_unsafe_phase_or_pending_request_refuses(self):
        self.ready()
        for change in ({'phase': 'awaiting_native_flush'}, {'phase': 'waiting_admission'},
                       {'phase': 'ready', 'pending_request': {'fixture': True}}):
            with self.subTest(change=change):
                state = deepcopy(self.owned.checkpoint.state)
                state.update(change)
                self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
                self.assertFalse(self.resumed())

    def test_released_owner_is_not_authority(self):
        self.ready()
        self.release()
        with self.assertRaises(OwnershipError): self.resumed()

    def test_stale_local_checkpoint_is_not_authority(self):
        self.ready()
        self.owned.checkpoint = replace(self.owned.checkpoint, revision=self.owned.checkpoint.revision-1)
        from adaptive_inference.task_store import RevisionConflict
        with self.assertRaises(RevisionConflict): self.resumed()

    def test_local_state_difference_with_same_revision_is_rejected(self):
        self.ready()
        state = deepcopy(self.owned.checkpoint.state)
        state['requests'] += 1
        self.owned.checkpoint = replace(self.owned.checkpoint, state=state)
        with self.assertRaises(ControlBlocked): self.resumed()

    def test_malformed_ack_prefix_is_a_hard_error(self):
        self.ready()
        state = deepcopy(self.owned.checkpoint.state)
        state[ACKS]['receipts'][0]['sequence'] = 2
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked): self.resumed()

    def test_repeated_reads_preserve_prompt_deadline_quality_accounting_and_history(self):
        self.ready()
        before = deepcopy(self.owned.checkpoint)
        snapshot = self.mailbox.snapshot()
        with closing(sqlite3.connect(self.store.path)) as db:
            durable_before = list(db.iterdump())
        for _ in range(5): self.assertTrue(self.resumed())
        self.assertEqual(self.owned.checkpoint, before)
        self.assertEqual(self.mailbox.snapshot(), snapshot)
        self.assertEqual(before.prompt, PROMPT)
        self.assertEqual(before.metadata['quality'], QUALITY)
        self.assertEqual(before.state['deadline_monotonic'], 123456.75)
        self.assertEqual((before.state['requests'], before.state['attempts'], before.state['admission_attempts']), (2, 2, 2))
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(list(db.iterdump()), durable_before)


class OptInPreservationTests(unittest.TestCase):
    def test_worker_diff_is_only_opt_in_predicate_branch(self):
        old = ast.parse((HERE/'provenance/report-hold-predecessor/run_recovery.py').read_text())
        # Preserve the historical whole-worker proof against its frozen source.
        # The current successor adds independently tested validation wiring.
        new = ast.parse((HERE/'provenance/before-report-feedback/hermes/run_recovery.py').read_text())
        before = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        after = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        resumed = next(n for n in ast.walk(after) if isinstance(n, ast.FunctionDef) and n.name == 'resumed')
        branch = resumed.body.pop(0)
        self.assertIsInstance(branch, ast.If)
        self.assertEqual(ast.unparse(branch.test), 'args.qualification_hold_after_report')
        self.assertEqual(ast.unparse(branch.body[0]), 'return qualification_report_resumed(mailbox, owned)')
        self.assertEqual(ast.dump(before, include_attributes=False), ast.dump(after, include_attributes=False))

    def test_current_report_hold_body_is_byte_semantically_unchanged(self):
        old=ast.parse((HERE/'provenance/before-report-feedback/hermes/run_recovery.py').read_text())
        new=ast.parse((HERE/'hermes/run_recovery.py').read_text())
        for name in ('qualification_report_resumed','controlled_safe_hold'):
            before=next(n for n in ast.walk(old) if isinstance(n,ast.FunctionDef) and n.name==name)
            after=next(n for n in ast.walk(new) if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(before,include_attributes=False),ast.dump(after,include_attributes=False))


if __name__ == '__main__': unittest.main(verbosity=2)
