"""Real SQLite seal/append ordering; no worker, GUI, model or sleep."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import (
    Mailbox, ControlBlocked, ControlNotRecorded, EXECUTION_OUTCOME, execution_outcome,
)
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore

NOW = '2026-10-25T12:00:00Z'


class PausedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name).resolve()/'task.sqlite3')
        self.identity = DemandIdentity('registered', 'task', 'host', NOW)
        self.store.create('task', 'Original objective', metadata={NAMESPACE:self.identity.metadata()})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.cap = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.cap)
        self.box.submit(self.cap, 'pause', 'pause')
        self.claim = self.store.claim('task', expected_revision=self.store.load('task').revision)
        self.owned = self.claim.__enter__()
        self.addCleanup(self.claim.__exit__, None, None, None)
        state = deepcopy(self.owned.checkpoint.state)
        state['deadline_monotonic'] = 10.0
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.box.consume(self.owned, updated_at_utc=NOW)
        self.observation = self.box.paused_execution_observation(self.owned)

    def seal(self, **changes):
        values = dict(deadline_monotonic=10.0, pause_observed_at_monotonic=9.0,
                      observed_pause=self.observation, sealed_at_monotonic=10.0)
        values.update(changes)
        return self.box.seal_paused_execution(self.owned, **values)

    def test_seal_adds_only_marker_and_preserves_full_original_state(self):
        before = self.owned.checkpoint
        marker = self.seal()
        after = self.owned.checkpoint
        state = deepcopy(after.state)
        self.assertEqual(state.pop(EXECUTION_OUTCOME), marker)
        self.assertEqual(state, before.state)
        self.assertEqual(after.revision, before.revision + 1)
        self.assertEqual(after.owner_epoch, before.owner_epoch)
        self.assertEqual(execution_outcome(after.state), marker)

    def test_seal_before_new_append_refuses_without_new_claim_or_ack(self):
        self.seal()
        before = self.store.history(self.box.task_id)
        value = self.box.submit(self.cap, 'new-resume', 'resume')
        self.assertEqual(value, ControlNotRecorded('new-resume', 'resume'))
        self.assertEqual(self.store.history(self.box.task_id), before)
        self.assertEqual(len(self.box.snapshot().requests), 1)

    def test_seal_between_submit_preread_and_append_refuses_atomically(self):
        actual = self.store.claim
        @contextmanager
        def interleaved(task_id, **kwargs):
            with actual(task_id, **kwargs) as owner:
                if task_id == self.box.task_id:
                    self.seal()
                yield owner
        with mock.patch.object(self.store, 'claim', side_effect=interleaved):
            value = self.box.submit(self.cap, 'new-resume', 'resume')
        self.assertEqual(value, ControlNotRecorded('new-resume', 'resume'))
        snapshot = self.box.snapshot()
        self.assertEqual(len(snapshot.requests), 1)
        self.assertIsNone(self.store.load(self.box.task_id).owner_epoch)
        self.assertEqual(self.store.history(self.box.task_id)[-1]['event'], 'claimed')
        self.assertIsNotNone(execution_outcome(snapshot.target.state))

    def test_append_before_seal_keeps_pending_suffix_and_refuses(self):
        self.box.submit(self.cap, 'later-pause', 'pause')
        with self.assertRaises(ControlBlocked):
            self.seal()
        self.assertNotIn(EXECUTION_OUTCOME, self.store.load('task').state)
        self.assertEqual(self.box.status('later-pause')['outcome'], 'pending')

    def test_absent_marker_preserves_recorded_terminal_race(self):
        actual = self.store.claim
        @contextmanager
        def interleaved(task_id, **kwargs):
            with actual(task_id, **kwargs) as owner:
                if task_id == self.box.task_id:
                    state = deepcopy(self.owned.checkpoint.state)
                    state.update(status='accepted', output='Original task accepted')
                    self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
                yield owner
        with mock.patch.object(self.store, 'claim', side_effect=interleaved):
            value = self.box.submit(self.cap, 'new-resume', 'resume')
        self.assertEqual(value['outcome'], 'rejected')
        self.assertIs(value['owner_acknowledged'], False)
        self.assertEqual(value['reason'], 'target_task_terminal')
        self.assertEqual(len(self.box.snapshot().requests), 2)

    def test_changed_applied_prefix_does_not_reuse_old_pause_observation(self):
        self.box.submit(self.cap, 'later-pause', 'pause')
        self.box.consume(self.owned, updated_at_utc=NOW)
        with self.assertRaises(ControlBlocked):
            self.seal()
        self.assertNotIn(EXECUTION_OUTCOME, self.store.load('task').state)

    def test_existing_id_after_seal_returns_actual_ack_not_nonrecorded(self):
        self.seal()
        value = self.box.submit(self.cap, 'pause', 'pause')
        self.assertEqual(value['outcome'], 'applied')
        self.assertIs(value['owner_acknowledged'], True)
        with self.assertRaises(ValueError):
            self.box.submit(self.cap, 'pause', 'resume')

    def test_bad_time_types_and_late_pause_cannot_seal(self):
        for changes in ({'pause_observed_at_monotonic':10.0}, {'sealed_at_monotonic':9.9},
                        {'deadline_monotonic':True}, {'sealed_at_monotonic':float('nan')},
                        {'deadline_monotonic':11.0}, {'sealed_at_monotonic':10**1000}):
            with self.subTest(changes=changes), self.assertRaises(ControlBlocked):
                self.seal(**changes)
        self.assertNotIn(EXECUTION_OUTCOME, self.store.load('task').state)

    def test_present_malformed_marker_never_means_absence(self):
        for value in (None, {}, True, {'schema':'other'}):
            state = deepcopy(self.owned.checkpoint.state)
            state[EXECUTION_OUTCOME] = value
            with self.subTest(value=value), self.assertRaises(ControlBlocked):
                execution_outcome(state)

    def test_postseal_state_mutation_cannot_validate(self):
        self.seal()
        state = deepcopy(self.owned.checkpoint.state)
        state['feedback'].append('unrelated later mutation')
        with self.assertRaises(ControlBlocked):
            execution_outcome(state)

    def test_boolean_original_deadline_does_not_equal_numeric_marker(self):
        state = deepcopy(self.owned.checkpoint.state)
        state['deadline_monotonic'] = True
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.observation = self.box.paused_execution_observation(self.owned)
        with self.assertRaises(ControlBlocked):
            self.seal(deadline_monotonic=1.0, pause_observed_at_monotonic=.5, sealed_at_monotonic=1.0)

    def test_failed_commit_does_not_install_in_memory_seal(self):
        before = self.owned.checkpoint
        with mock.patch.object(self.store, '_write', side_effect=OSError('fixture write failed')):
            with self.assertRaises(OSError):
                self.seal()
        self.assertIs(self.owned.checkpoint, before)
        self.assertNotIn(EXECUTION_OUTCOME, self.store.load('task').state)


if __name__ == '__main__':
    unittest.main()
