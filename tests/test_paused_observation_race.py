# SPDX-License-Identifier: Apache-2.0
"""Real SQLite control interleavings; no SDK, model, native engine or GUI.

Each observation is a new transaction, not a reservation of an earlier sample:
https://www.sqlite.org/isolation.html
"""
from copy import deepcopy
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import ACKS, EXECUTION_OUTCOME, ControlBlocked, execution_outcome
from adaptive_inference.demand import _record
from adaptive_inference.task_store import OwnershipError, RevisionConflict, TerminalTaskError
from adaptive_inference.desktop.hermes import recovery as rec
import test_desktop_paused_expiry as fixture


class PauseObservationRaceTests(unittest.TestCase):
    setUp = fixture.PausedExpiryTests.setUp
    advance = fixture.PausedExpiryTests.advance
    release = fixture.PausedExpiryTests.release

    def applied_pause(self):
        self.box.submit(self.cap, 'pause-one', 'pause')
        boundary = self.box.consume(self.owned, updated_at_utc=fixture.NOW)
        self.assertEqual(boundary['reason'], 'demand_paused')
        observed = self.box.paused_execution_observation(self.owned)
        self.controls.paused_expiry_observation = {'pause': observed, 'observed_at': self.now}
        return observed

    def interleave(self, command, *, at_deadline=False):
        actual = self.box.paused_execution_observation
        injected = []
        def observe(owned):
            if not injected:
                before = self.box.snapshot()
                self.assertTrue(before.status('pause-one')['owner_acknowledged'])
                self.assertEqual(_record(owned.checkpoint, self.identity)['state'], 'paused')
                injected.append(self.box.submit(self.cap, 'arrived-' + command, command))
                if at_deadline:
                    self.now = self.controls.deadline
            return actual(owned)
        return mock.patch.object(self.box, 'paused_execution_observation', side_effect=observe), injected

    def assert_no_seal(self):
        self.assertIsNone(execution_outcome(self.owned.checkpoint.state))
        self.assertIsNone(self.owned.checkpoint.operation)

    def test_resume_arrival_after_consumed_pause_is_applied_once(self):
        self.applied_pause()
        activity = []; sleeps = []
        self.controls.wait_activity = lambda owned, *observation: activity.append(observation)
        def sleep(seconds):
            sleeps.append(seconds); self.advance(seconds)
        self.controls.sleep = sleep
        patch, injected = self.interleave('resume')
        with patch:
            self.controller.control_safe_point()
        snap = self.box.snapshot()
        self.assertEqual(len(injected), 1)
        self.assertEqual([row['request_id'] for row in snap.receipts], ['pause-one', 'arrived-resume'])
        self.assertTrue(all(row['outcome'] == 'applied' for row in snap.receipts))
        self.assertTrue(snap.status('arrived-resume')['owner_acknowledged'])
        self.assertEqual(_record(snap.target, self.identity)['state'], 'waiting')
        self.assertEqual(activity, [(None,), ()])
        self.assertEqual(sleeps, [.25])
        self.assertIsNone(self.controls.paused_expiry_observation)
        self.assert_no_seal()

    def test_cancel_arrival_keeps_existing_terminal_outcome(self):
        self.applied_pause()
        patch, injected = self.interleave('cancel')
        with patch, self.assertRaises(rec.ControlStop) as raised:
            self.controller.control_safe_point()
        self.assertEqual(raised.exception.control_state, 'cancelled')
        self.assertEqual(raised.exception.reason, 'durable_control_acknowledged')
        self.assertEqual(len(injected), 1)
        self.assertTrue(self.box.status('arrived-cancel')['owner_acknowledged'])
        self.assertIsNone(self.controls.paused_expiry_observation)
        self.assert_no_seal()

    def test_new_pause_requires_its_own_predeadline_observation(self):
        previous = self.applied_pause()
        patch, _ = self.interleave('pause')
        with patch, self.assertRaises(rec.ControlStop):
            self.controller.control_safe_point()
        observation = self.controls.paused_expiry_observation
        self.assertEqual(observation['pause']['pause_request_id'], 'arrived-pause')
        self.assertNotEqual(observation['pause'], previous)
        self.assertEqual(observation['observed_at'], 9.25)
        self.assertEqual([row['request_id'] for row in self.box.snapshot().receipts], ['pause-one', 'arrived-pause'])
        self.assert_no_seal()

    def test_pending_at_deadline_clears_cache_runs_activity_and_never_seals(self):
        observed = self.applied_pause(); activity = []; sleeps = []
        self.controls.wait_activity = lambda owned, *observation: activity.append(observation)
        self.controls.sleep = sleeps.append
        patch, _ = self.interleave('resume', at_deadline=True)
        with patch, self.assertRaises(rec.ControlStop) as raised:
            self.controller.control_safe_point()
        self.assertEqual(raised.exception.reason, 'control_wait_deadline')
        self.assertEqual(activity, [(None,)])
        self.assertEqual(sleeps, [])
        self.assertIsNone(self.controls.paused_expiry_observation)
        self.assertFalse(self.box.status('arrived-resume')['owner_acknowledged'])
        with self.assertRaises(ControlBlocked):
            self.box.seal_paused_execution(self.owned, deadline_monotonic=10.,
                pause_observed_at_monotonic=9., observed_pause=observed, sealed_at_monotonic=10.)
        self.assert_no_seal()

    def test_pending_observation_is_read_only_but_strict_seal_refuses(self):
        observed = self.applied_pause()
        for command in ('resume', 'cancel', 'pause'):
            self.box.submit(self.cap, 'pending-' + command, command)
        before = self.box.snapshot(); history = self.store.history('task')
        self.assertIsNone(self.box.paused_execution_observation(self.owned))
        self.assertEqual(self.box.snapshot(), before)
        self.assertEqual(self.store.history('task'), history)
        with self.assertRaises(ControlBlocked):
            self.box.seal_paused_execution(self.owned, deadline_monotonic=10.,
                pause_observed_at_monotonic=9., observed_pause=observed, sealed_at_monotonic=10.)
        self.assertEqual(self.box.snapshot(), before)
        self.assert_no_seal()

    def test_malformed_ack_is_not_treated_as_expected_pending_progress(self):
        self.applied_pause(); self.box.submit(self.cap, 'pending', 'resume')
        state = deepcopy(self.owned.checkpoint.state)
        state[ACKS]['receipts'][0]['request_id'] = 'wrong'
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaisesRegex(ControlBlocked, 'ordered request prefix'):
            self.box.paused_execution_observation(self.owned)

    def test_malformed_request_with_pending_controls_still_refuses(self):
        self.applied_pause(); self.box.submit(self.cap, 'pending', 'resume')
        cp = self.store.load(self.box.task_id)
        with self.store.claim(self.box.task_id, expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state)
            from adaptive_inference.control_mailbox import REQUESTS
            state[REQUESTS][-1]['command'] = 'unknown'
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        with self.assertRaisesRegex(ControlBlocked, 'ordered control request'):
            self.box.paused_execution_observation(self.owned)

    def test_foreign_and_ended_owners_still_refuse(self):
        self.applied_pause(); self.box.submit(self.cap, 'pending', 'resume')
        cp = self.store.create('other', 'Different task')
        with self.store.claim('other', expected_revision=cp.revision) as foreign:
            with self.assertRaises(OwnershipError):
                self.box.paused_execution_observation(foreign)
        self.release()
        with self.assertRaises(OwnershipError):
            self.box.paused_execution_observation(self.owned)

    def test_stale_revision_is_not_treated_as_expected_pending_progress(self):
        self.applied_pause(); self.box.submit(self.cap, 'pending', 'resume')
        stale = self.owned.checkpoint
        self.owned.save_checkpoint(deepcopy(stale.state), expected_revision=stale.revision)
        current = self.owned.checkpoint; self.owned.checkpoint = stale
        try:
            with self.assertRaises(RevisionConflict):
                self.box.paused_execution_observation(self.owned)
        finally:
            self.owned.checkpoint = current

    def test_inflight_operation_cannot_be_optional_observation(self):
        self.applied_pause(); self.box.submit(self.cap, 'pending', 'resume')
        self.owned.begin_operation('effect', details={'fixture': True}, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked):
            self.box.paused_execution_observation(self.owned)

    def test_empty_applied_prefix_and_nonpause_last_ack_still_refuse(self):
        self.box.submit(self.cap, 'no-ack', 'pause')
        with self.assertRaises(ControlBlocked):
            self.box.paused_execution_observation(self.owned)
        self.box.consume(self.owned, updated_at_utc=fixture.NOW)
        self.box.submit(self.cap, 'resume', 'resume')
        self.box.consume(self.owned, updated_at_utc=fixture.NOW)
        self.box.submit(self.cap, 'pending-pause', 'pause')
        with self.assertRaises(ControlBlocked):
            self.box.paused_execution_observation(self.owned)

    def test_sealed_and_terminal_tasks_remain_immutable(self):
        observed = self.applied_pause()
        self.box.seal_paused_execution(self.owned, deadline_monotonic=10.,
            pause_observed_at_monotonic=9., observed_pause=observed, sealed_at_monotonic=10.)
        with self.assertRaises(ControlBlocked):
            self.box.paused_execution_observation(self.owned)
        state = deepcopy(self.owned.checkpoint.state)
        del state[EXECUTION_OUTCOME]
        state.update(status='accepted', output='fixture terminal checkpoint')
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        with self.assertRaises(TerminalTaskError):
            self.box.paused_execution_observation(self.owned)

    def test_poll_does_not_catch_structural_observation_failure(self):
        self.applied_pause()
        with mock.patch.object(self.box, 'paused_execution_observation', side_effect=ControlBlocked('malformed observation')):
            with self.assertRaisesRegex(ControlBlocked, 'malformed observation'):
                self.controller.control_safe_point()
        self.assertIsNone(self.controls.paused_expiry_observation)


if __name__ == '__main__':
    unittest.main()
