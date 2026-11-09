"""Closed completed-effect repair: real TaskStore/native SQLite, inert recipes.

Reuse compiler/video dispatch fixtures and the public SessionDB lease surface.
No SDK, compiler, encoder, model, process interruption or hardware qualification.
"""
from copy import deepcopy
import json
from unittest import TestCase, mock

from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.run_recovery import reconcile_saved_result
from adaptive_inference.task_store import ReconciliationRequired
import test_compiler_recovery as compiler_fixture
import test_video_dispatch as video_fixture


class RecipeReconciliationTests(TestCase):
    def fixture(self, kind):
        if kind == 'video':
            wrapper = video_fixture.VideoRecoveryTests()
            self.addCleanup(wrapper.doCleanups)
            wrapper.setUp()
            f = wrapper.fixture
            f.recipe_intent, f.recipe_dispatch = wrapper.intent, wrapper.dispatch
        else:
            f = compiler_fixture.CompilerRecoveryTests()
            self.addCleanup(f.doCleanups)
            f.setUp()
            f.recipe_intent, f.recipe_dispatch = f.intent, f.dispatch
        # Exercise real saved counters, rather than only an empty initial state.
        state = deepcopy(f.owned.checkpoint.state)
        state.update(requests=1, attempts=2, admission_attempts=3)
        f.owned.save_checkpoint(state, expected_revision=f.owned.checkpoint.revision)
        f.native_lease = None
        f.appended_by_reconcile = []

        def acquire(session, holder, wait_seconds):
            self.assertEqual(session, 'session')
            self.assertEqual(wait_seconds, 0)
            if f.native_lease is not None:
                return False
            f.native_lease = holder
            return True

        def release(session, holder):
            self.assertEqual((session, holder), ('session', f.native_lease))
            f.native_lease = None

        def append(session, role, **kwargs):
            self.assertEqual(session, 'session')
            self.assertEqual(kwargs['turn_lease_holder'], f.native_lease)
            row = {'role': role, 'content': kwargs['content'],
                   'tool_call_id': kwargs['tool_call_id'], 'tool_name': kwargs['tool_name']}
            f.db.append(row)
            f.appended_by_reconcile.append(deepcopy(row))

        f.db.acquire_session_turn_lease = acquire
        f.db.release_session_turn_lease = release
        f.db.append_message = append
        return f

    def completed_without_flush(self, kind):
        f = self.fixture(kind)
        call, args = f.recipe_intent()
        result = f.recipe_dispatch(call, args)
        self.assertIsNone(f.controller.fatal)
        self.assertEqual(f.owned.checkpoint.state['phase'], 'awaiting_native_flush')
        self.assertIsNone(f.owned.checkpoint.operation)
        receipt = deepcopy(f.owned.checkpoint.state['tools'][-1])
        self.assertEqual(receipt['result'], result)
        old_owner = f.owned.checkpoint.owner_epoch
        self.reclaim(f)
        self.assertNotEqual(f.owned.checkpoint.owner_epoch, old_owner)
        return f, call, result, receipt

    def reclaim(self, f):
        f.release()
        cp = f.store.load('task')
        f.context = f.store.claim('task', expected_revision=cp.revision)
        f.owned = f.context.__enter__()

    def repair(self, f, receipt, **kwargs):
        return reconcile_saved_result(f.owned, f.db, f.work, receipt,
            expected_operation_id=kwargs.get('operation_id', receipt['operation_id']))

    def test_lost_worker_after_durable_completion_repairs_both_recipe_families(self):
        for kind in ('compiler', 'video'):
            with self.subTest(kind=kind):
                f, call, result, receipt = self.completed_without_flush(kind)
                before = deepcopy(f.owned.checkpoint)
                effects = (f.run/'effect-receipts.jsonl').read_bytes()
                with self.assertRaises(ReconciliationRequired):
                    rec.resumable(f.owned, f.db, f.work)
                cp = self.repair(f, receipt)
                self.assertEqual(cp.revision, before.revision + 1)
                self.assertEqual(cp.state['phase'], 'ready')
                expected = deepcopy(before.state)
                expected.update(phase='ready', native_history=rec.native_history(f.db, 'session'))
                self.assertEqual(cp.state, expected)
                self.assertEqual(cp.metadata, before.metadata)
                self.assertEqual((cp.task_id, cp.prompt, cp.max_attempts),
                                 (before.task_id, before.prompt, before.max_attempts))
                self.assertEqual(cp.state['deadline_monotonic'], 900.)
                self.assertEqual((f.run/'effect-receipts.jsonl').read_bytes(), effects)
                self.assertEqual(len(f.calls), 1)
                self.assertEqual(len(f.appended_by_reconcile), 1)
                rows = rec.resumable(f.owned, f.db, f.work)
                self.assertEqual([row['content'] for row in rows if row.get('tool_call_id') == call], [result])
                self.assertIsNone(f.native_lease)
                # Explicit retry verifies the already-ready checkpoint without mutation.
                self.assertEqual(self.repair(f, receipt), cp)
                self.assertEqual(len(f.appended_by_reconcile), 1)
                self.assertEqual(len(f.calls), 1)
                self.assertEqual(sum(e['event'] == 'operation_completed'
                                     for e in f.store.history('task')), 1)

    def test_native_result_already_flushed_only_saves_checkpoint(self):
        for kind in ('compiler', 'video'):
            with self.subTest(kind=kind):
                f, call, result, receipt = self.completed_without_flush(kind)
                f.db.append({'role': 'tool', 'tool_call_id': call, 'content': result})
                native = rec.native_history(f.db, 'session')
                self.repair(f, receipt)
                self.assertEqual(rec.resumable(f.owned, f.db, f.work), native)
                self.assertEqual(f.appended_by_reconcile, [])
                self.assertEqual(len(f.calls), 1)

    def test_loss_after_native_append_before_checkpoint_retries_without_duplicate(self):
        for kind in ('compiler', 'video'):
            with self.subTest(kind=kind):
                f, call, result, receipt = self.completed_without_flush(kind)
                with mock.patch.object(f.owned, 'save_checkpoint', side_effect=RuntimeError('lost before checkpoint')):
                    with self.assertRaisesRegex(RuntimeError, 'lost before checkpoint'):
                        self.repair(f, receipt)
                self.assertIsNone(f.native_lease)
                self.assertEqual(f.owned.checkpoint.state['phase'], 'awaiting_native_flush')
                self.reclaim(f)
                self.repair(f, receipt)
                self.assertEqual(len(f.appended_by_reconcile), 1)
                self.assertEqual(len(f.calls), 1)
                rows = rec.resumable(f.owned, f.db, f.work)
                self.assertEqual([row['content'] for row in rows if row.get('tool_call_id') == call], [result])

    def test_conflicting_or_duplicate_native_result_cannot_be_repaired(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                f, call, result, receipt = self.completed_without_flush('video')
                f.db.append({'role': 'tool', 'tool_call_id': call, 'content': result if duplicate else 'changed'})
                if duplicate:
                    f.db.append({'role': 'tool', 'tool_call_id': call, 'content': result})
                before = deepcopy(f.owned.checkpoint)
                with self.assertRaises(ReconciliationRequired): self.repair(f, receipt)
                self.assertEqual(f.owned.checkpoint, before)
                self.assertEqual(f.appended_by_reconcile, [])
                self.assertIsNone(f.native_lease)

    def test_changed_artifact_and_wrong_receipt_are_refused_before_append(self):
        for kind in ('compiler', 'video'):
            for change in ('artifact', 'receipt', 'operation'):
                with self.subTest(kind=kind, change=change):
                    f, _, _, receipt = self.completed_without_flush(kind)
                    before = deepcopy(f.owned.checkpoint)
                    if change == 'artifact':
                        path = (f.recipes[0].build/'program.exe' if kind == 'compiler'
                                else f.recipes[0].run/f.recipes[0].artifact)
                        path.write_bytes(b'changed artifact')
                    elif change == 'receipt':
                        value = json.loads(receipt['result']); value['task_deadline'] = 1800.
                        receipt['result'] = json.dumps(value)
                    with self.assertRaises((ReconciliationRequired, ValueError)):
                        self.repair(f, receipt, operation_id='wrong-operation' if change == 'operation' else receipt['operation_id'])
                    self.assertEqual(f.owned.checkpoint, before)
                    self.assertEqual(f.appended_by_reconcile, [])
                    self.assertIsNone(f.native_lease)

    def test_live_native_turn_blocks_reconciliation_without_mutation(self):
        f, _, _, receipt = self.completed_without_flush('compiler')
        before = deepcopy(f.owned.checkpoint)
        f.native_lease = 'another-worker'
        with self.assertRaisesRegex(ReconciliationRequired, 'still owned'): self.repair(f, receipt)
        self.assertEqual(f.owned.checkpoint, before)
        self.assertEqual(f.appended_by_reconcile, [])
        self.assertEqual(f.native_lease, 'another-worker')

    def test_unresolved_effect_stays_fenced(self):
        f = self.fixture('compiler')
        f.status = 'outcome_unknown'
        call, args = f.recipe_intent()
        f.recipe_dispatch(call, args)
        operation = deepcopy(f.owned.checkpoint.operation)
        self.assertIsNotNone(operation)
        self.reclaim(f)
        before = deepcopy(f.owned.checkpoint)
        receipt = {'name': 'build_and_test', 'operation_id': operation['id']}
        with self.assertRaises(ReconciliationRequired): self.repair(f, receipt)
        self.assertEqual(f.owned.checkpoint, before)
        self.assertTrue(f.owned.checkpoint.requires_reconciliation)
        self.assertEqual(f.appended_by_reconcile, [])
        self.assertIsNone(f.native_lease)

    def test_unexpected_native_progress_after_missing_result_stays_fenced(self):
        f, _, _, receipt = self.completed_without_flush('video')
        f.db.append({'role': 'assistant', 'content': 'unexplained next turn'})
        before = deepcopy(f.owned.checkpoint)
        with self.assertRaises(ReconciliationRequired): self.repair(f, receipt)
        self.assertEqual(f.owned.checkpoint, before)
        self.assertEqual(f.appended_by_reconcile, [])

    def test_explicit_file_route_still_uses_existing_reconciler(self):
        f = self.fixture('compiler')
        receipt = {'name': 'write_file', 'operation_id': 'original-file-operation'}
        with mock.patch.object(rec, 'reconcile_write', return_value='existing-file-result') as existing:
            self.assertEqual(self.repair(f, receipt), 'existing-file-result')
        existing.assert_called_once_with(f.owned, f.db, f.work, receipt,
                                        expected_operation_id='original-file-operation')

    def test_unexpected_native_progress_during_append_is_not_checkpointed(self):
        f, _, _, receipt = self.completed_without_flush('video')
        before = deepcopy(f.owned.checkpoint)
        append = f.db.append_message
        def concurrent_append(*args, **kwargs):
            append(*args, **kwargs)
            f.db.append({'role': 'user', 'content': 'new unowned input'})
        f.db.append_message = concurrent_append
        with self.assertRaisesRegex(ReconciliationRequired, 'advanced during'):
            self.repair(f, receipt)
        self.assertEqual(f.owned.checkpoint, before)
        self.assertEqual(len(f.appended_by_reconcile), 1)
        self.assertIsNone(f.native_lease)
