"""Pending effect recovery with real TaskStore/native SQLite and inert recipes.

Reuse the completed-feedback fixtures. No SDK, tool executable or worker crash
is run here; injected exceptions model the cross-store persistence boundaries.
"""
from copy import deepcopy
import json
import sqlite3
from unittest import TestCase, mock

from adaptive_inference.desktop.execution_budget import BUDGET, create_budget
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.compiler_evidence import verify_recipe_evidence
from adaptive_inference.desktop.hermes.compiler_recovery import make_recipe_receipt
from adaptive_inference.task_store import ReconciliationRequired
import test_recipe_reconciliation as completed_fixture


class PendingRecipeReconciliationTests(TestCase):
    def pending(self, kind, *, status='passed', prior_attempt=False):
        helper = completed_fixture.RecipeReconciliationTests()
        self.addCleanup(helper.doCleanups)
        f = helper.fixture(kind)
        if prior_attempt:
            self.assertEqual(kind, 'compiler')
            f.status = 'failed'
            call, args = f.recipe_intent()
            result = f.recipe_dispatch(call, args)
            f.flush(call, result)
        journal = f.run/'effect-receipts.jsonl'
        prior_journal = journal.read_bytes() if journal.exists() else None
        state = deepcopy(f.owned.checkpoint.state)
        state[BUDGET] = create_budget(boot_id='a'*64, deadline=900.,
            observation={'qpc_before':10., 'qpc_after':10., 'utc_ns':1_000_000_000_000})
        f.owned.save_checkpoint(state, expected_revision=f.owned.checkpoint.revision)
        f.status = status
        retained = {}
        original = f.controller.compiler_client

        def lost(request):
            retained['result'] = original(request)
            raise rec.RecoveryStop('fixture worker lost before effect bookkeeping')

        f.controller.compiler_client = lost
        call, args = f.recipe_intent()
        with self.assertRaises(rec.RecoveryStop):
            f.recipe_dispatch(call, args)
        operation = deepcopy(f.owned.checkpoint.operation)
        self.assertIsNotNone(operation)
        self.assertEqual(journal.read_bytes() if journal.exists() else None, prior_journal)
        helper.reclaim(f)
        self.assertTrue(f.owned.checkpoint.requires_reconciliation)
        receipt = make_recipe_receipt(task_root=f.run, task_spec=f.spec,
            details=operation['details'], operation_id=operation['id'],
            result=retained['result'], expected_deadline=900.)
        f.repair = lambda value=receipt: helper.repair(f, value)
        f.reclaim = lambda: helper.reclaim(f)
        return f, receipt

    def journal(self, f):
        return [json.loads(row) for row in (f.run/'effect-receipts.jsonl').read_text().splitlines()]

    def verify(self, f):
        return verify_recipe_evidence(f.owned.checkpoint, f.run, rec.native_history(f.db, 'session'),
                                      store_path=f.store.path)

    def test_pending_terminal_receipt_repairs_both_kinds_and_preserves_original_state(self):
        for kind in ('compiler', 'video'):
            with self.subTest(kind=kind):
                f, receipt = self.pending(kind)
                before, calls = deepcopy(f.owned.checkpoint), deepcopy(f.calls)
                result = f.repair()
                self.assertIsNone(result.operation)
                self.assertFalse(result.requires_reconciliation)
                self.assertEqual(result.state['phase'], 'ready')
                self.assertEqual(result.state['status'], 'pending')
                self.assertEqual(result.state['tools'], before.state['tools'] + [receipt])
                self.assertEqual(result.metadata, before.metadata)
                rec.resumable(f.owned, f.db, f.work)
                for key in before.state.keys() - {'phase', 'tools', 'native_history'}:
                    self.assertEqual(result.state[key], before.state[key], key)
                self.assertEqual(f.calls, calls)
                self.assertEqual(self.journal(f), [receipt])
                self.assertEqual(len(f.appended_by_reconcile), 1)
                self.assertEqual(self.verify(f)[0]['status'], 'passed')
                ends = [row for row in f.store.history('task') if row['event'] == 'operation_reconciled']
                self.assertEqual(len(ends), 1)
                self.assertEqual(ends[0]['payload']['event_data'], {
                    'operation': before.operation, 'resolution':'completed', 'result':receipt})
                history, native = f.store.history('task'), rec.native_history(f.db, 'session')
                self.assertEqual(f.repair(), result)
                self.assertEqual(f.store.history('task'), history)
                self.assertEqual(rec.native_history(f.db, 'session'), native)
                self.assertEqual(self.journal(f), [receipt])

    def test_existing_exact_effect_journal_is_recognized_without_another_entry(self):
        for kind in ('compiler', 'video'):
            with self.subTest(kind=kind):
                f, receipt = self.pending(kind)
                path = f.run/'effect-receipts.jsonl'
                path.write_text(json.dumps(receipt)+'\n', encoding='utf-8')
                original = path.read_bytes()
                f.repair()
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(len(f.appended_by_reconcile), 1)
                self.verify(f)

    def test_prior_failed_attempt_is_preserved_when_later_success_is_reconciled(self):
        f, receipt = self.pending('compiler', prior_attempt=True)
        before = deepcopy(f.owned.checkpoint.state)
        prior = self.journal(f)
        self.assertEqual(len(prior), 1)
        f.repair()
        self.assertEqual(self.journal(f), prior + [receipt])
        self.assertEqual(f.owned.checkpoint.state['tools'], before['tools'] + [receipt])
        self.assertEqual([row['status'] for row in self.verify(f)], ['failed', 'passed'])
        self.assertEqual(len(f.calls), 2)
        rec.resumable(f.owned, f.db, f.work)

    def test_loss_after_journal_and_after_native_append_can_be_explicitly_retried(self):
        for boundary in ('journal', 'native'):
            with self.subTest(boundary=boundary):
                f, receipt = self.pending('video')
                target = f.db if boundary == 'journal' else f.owned
                method = 'append_message' if boundary == 'journal' else 'reconcile_operation'
                before = deepcopy(f.owned.checkpoint)
                with mock.patch.object(target, method, side_effect=RuntimeError('fixture recovery lost')):
                    with self.assertRaisesRegex(RuntimeError, 'recovery lost'):
                        f.repair()
                self.assertEqual(f.owned.checkpoint, before)
                self.assertEqual(self.journal(f), [receipt])
                self.assertEqual(len(f.appended_by_reconcile), 0 if boundary == 'journal' else 1)
                f.reclaim()
                f.repair()
                self.assertEqual(self.journal(f), [receipt])
                self.assertEqual(len(f.appended_by_reconcile), 1)
                self.assertEqual(self.verify(f)[0]['status'], 'passed')

    def test_conflicting_journal_and_native_result_stay_pending_without_new_writes(self):
        for conflict in ('journal', 'native'):
            with self.subTest(conflict=conflict):
                f, receipt = self.pending('compiler')
                if conflict == 'journal':
                    (f.run/'effect-receipts.jsonl').write_text(json.dumps({**receipt,'result':'different'})+'\n')
                else:
                    f.db.append({'role':'tool','tool_call_id':receipt['tool_call_id'],'content':'different'})
                before = deepcopy(f.owned.checkpoint)
                with self.assertRaises(ReconciliationRequired):
                    f.repair()
                self.assertEqual(f.owned.checkpoint, before)
                self.assertEqual(f.appended_by_reconcile, [])
                if conflict == 'native':
                    self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def test_changed_artifact_or_origin_identity_is_refused_before_journal_or_append(self):
        for change in ('artifact', 'owner', 'deadline', 'unknown'):
            with self.subTest(change=change):
                f, receipt = self.pending('compiler')
                changed = deepcopy(receipt)
                if change == 'artifact':
                    (f.recipes[0].build/'program.exe').write_bytes(b'changed artifact')
                elif change == 'owner':
                    changed['owner_epoch'] = f.owned.checkpoint.owner_epoch
                else:
                    result = json.loads(changed['result'])
                    if change == 'deadline': result['task_deadline'] += 1
                    else: result.update(status='outcome_unknown', passed=False, owned_processes_exited=False)
                    changed['result'] = json.dumps(result)
                before = deepcopy(f.owned.checkpoint)
                with self.assertRaises(ReconciliationRequired):
                    f.repair(changed)
                self.assertEqual(f.owned.checkpoint, before)
                self.assertEqual(f.appended_by_reconcile, [])
                self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def test_live_native_lease_keeps_pending_effect_and_journal_untouched(self):
        f, _ = self.pending('video')
        before = deepcopy(f.owned.checkpoint)
        f.native_lease = 'live other owner'
        with self.assertRaisesRegex(ReconciliationRequired, 'still owned'): f.repair()
        self.assertEqual(f.owned.checkpoint, before)
        self.assertEqual(f.appended_by_reconcile, [])
        self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def test_unexpected_native_row_during_repair_does_not_reconcile_pending_effect(self):
        f, _ = self.pending('video')
        original = f.db.append_message

        def extra(*args, **kwargs):
            original(*args, **kwargs)
            f.db.append({'role':'user','content':'unexpected next turn'})

        before = deepcopy(f.owned.checkpoint)
        with mock.patch.object(f.db, 'append_message', side_effect=extra):
            with self.assertRaisesRegex(ReconciliationRequired, 'advanced during'):
                f.repair()
        self.assertEqual(f.owned.checkpoint, before)
        self.assertTrue(f.owned.checkpoint.requires_reconciliation)

    def test_known_failed_terminal_attempt_is_feedback_not_task_acceptance(self):
        f, receipt = self.pending('compiler', status='failed')
        f.repair()
        self.assertEqual(f.owned.checkpoint.state['status'], 'pending')
        self.assertEqual(self.verify(f)[0]['status'], 'failed')
        self.assertEqual(self.journal(f), [receipt])
        self.assertEqual(len(f.calls), 1)

    def test_origin_reader_rejects_not_performed_and_changed_reconciled_result(self):
        for change in ('resolution', 'result'):
            with self.subTest(change=change):
                f, _ = self.pending('compiler')
                f.repair()
                self.verify(f)
                with sqlite3.connect(f.store.path) as db:
                    revision, raw = db.execute(
                        "SELECT revision,payload FROM history WHERE task_id='task' AND event='operation_reconciled'").fetchone()
                    payload = json.loads(raw)
                    if change == 'resolution': payload['event_data']['resolution'] = 'not_performed'
                    else: payload['event_data']['result']['owner_epoch'] = 'changed'
                    db.execute("UPDATE history SET payload=? WHERE task_id='task' AND revision=?",
                               (json.dumps(payload), revision))
                with self.assertRaisesRegex(ReconciliationRequired, 'exact completed origin'):
                    self.verify(f)
