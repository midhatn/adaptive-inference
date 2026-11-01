"""Admission-wait activity: real SQLite and scripted SDK edges, no live model.

The long-wait case advances a deterministic clock through the original budget;
it does not claim elapsed hardware time or an installed Hermes watchdog run.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import ControlBlocked, execution_outcome, WAIT_EXPIRY_SCHEMA
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.pause_activity import PauseActivity
import test_admission_wait_expiry as expiry_fixture
import test_desktop_pause_activity as pause_fixture


class AdmissionActivityTests(unittest.TestCase):
    release = expiry_fixture.WaitSealTests.release
    guard = pause_fixture.PauseActivityTests.guard

    def setUp(self):
        expiry_fixture.WaitSealTests.setUp(self)
        self.now = 0.0
        self.controls.deadline = 900.0
        self.save(deadline_monotonic=900.0)

    def save(self, **changes):
        state = deepcopy(self.owned.checkpoint.state)
        state.update(changes)
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)

    def test_verified_wait_stamps_at_fifteen_seconds_without_changing_saved_work(self):
        guard = self.guard()
        checkpoint = self.owned.checkpoint
        before = deepcopy(checkpoint.state)
        mailbox = self.box.snapshot()
        with mock.patch.object(self.box, 'admission_wait_observation',
                               wraps=self.box.admission_wait_observation) as observe:
            for instant in (0.0, 14.999, 15.0, 29.999, 30.0):
                self.now = instant
                guard(self.owned)
            self.assertEqual(observe.call_count, 3)
        self.assertEqual(self.agent._touch_activity.call_args_list,
                         [mock.call('waiting for adaptive admission')] * 3)
        self.assertEqual((guard.stamps, guard.last_stamp), (3, 30.0))
        self.assertIs(self.owned.checkpoint, checkpoint)
        self.assertEqual(checkpoint.state, before)
        self.assertEqual(self.box.snapshot(), mailbox)
        self.assertEqual(rec.native_history(self.db, 'native'), before['native_history'])

    def test_original_deadline_is_not_extended_and_due_poll_at_deadline_cannot_stamp(self):
        guard = self.guard()
        self.now = 884.0
        guard(self.owned)
        with mock.patch.object(self.box, 'admission_wait_observation',
                               wraps=self.box.admission_wait_observation) as observe:
            for instant in (900.0, 901.0):
                self.now = instant
                guard(self.owned)
            observe.assert_not_called()
        self.assertEqual(self.agent._touch_activity.call_count, 1)
        self.assertEqual(self.controls.deadline, 900.0)
        self.assertEqual(self.owned.checkpoint.state['deadline_monotonic'], 900.0)

    def test_ready_and_generating_polls_are_not_wait_activity(self):
        for phase in ('ready', 'generating'):
            with self.subTest(phase=phase):
                self.save(phase=phase)
                guard = self.guard()
                with mock.patch.object(self.box, 'admission_wait_observation',
                                       side_effect=AssertionError('ordinary work is not a wait')):
                    guard(self.owned)
                self.agent._touch_activity.assert_not_called()

    def test_observation_must_match_exact_owner_revision_and_saved_request_and_history(self):
        for key in ('owner_epoch', 'target_revision', 'state_sha256',
                    'pending_request_sha256', 'native_history_sha256'):
            with self.subTest(key=key):
                guard = self.guard()
                observation = self.box.admission_wait_observation(self.owned)
                observation[key] = observation[key] + 1 if key == 'target_revision' else 'different'
                with mock.patch.object(self.box, 'admission_wait_observation', return_value=observation):
                    with self.assertRaises(rec.RecoveryStop):
                        guard(self.owned)
                self.agent._touch_activity.assert_not_called()
                self.assertIsNotNone(guard.fault)

    def test_checkpoint_replaced_during_observation_cannot_stamp_old_request(self):
        guard = self.guard()
        observe = self.box.admission_wait_observation
        def changed(owned):
            result = observe(owned)
            request = deepcopy(self.request)
            request['messages'][0]['content'] = 'different pending request'
            self.save(pending_request=request)
            return result
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=changed):
            with self.assertRaises(rec.RecoveryStop):
                guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_in_place_checkpoint_change_during_observation_cannot_stamp(self):
        guard = self.guard()
        observe = self.box.admission_wait_observation
        def changed(owned):
            result = observe(owned)
            owned.checkpoint.state['pending_request']['model'] = 'different-model'
            return result
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=changed):
            with self.assertRaises(rec.RecoveryStop):
                guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_actual_native_history_change_after_observation_refuses_activity(self):
        guard = self.guard()
        observe = self.box.admission_wait_observation
        def changed(owned):
            result = observe(owned)
            self.db.append({'role': 'assistant', 'content': 'unsaved native history'})
            return result
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=changed):
            with self.assertRaises(rec.RecoveryStop):
                guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_unconsumed_pause_suppresses_stamp_without_consuming_or_acknowledging_it(self):
        guard = self.guard()
        self.box.submit(self.cap, 'unconsumed-pause', 'pause')
        before = self.box.snapshot()
        guard(self.owned)
        self.agent._touch_activity.assert_not_called()
        self.assertEqual(self.box.snapshot(), before)
        self.assertIsNone(guard.fault)
        self.assertEqual(len(before.requests), len(before.receipts) + 1)

    def test_unconsumed_cancel_refuses_activity(self):
        guard = self.guard()
        self.box.submit(self.cap, 'unconsumed-cancel', 'cancel')
        before = self.box.snapshot()
        with self.assertRaises(ControlBlocked):
            guard(self.owned)
        self.agent._touch_activity.assert_not_called()
        self.assertEqual(self.box.snapshot(), before)

    def test_unconsumed_resume_refuses_activity(self):
        guard = self.guard()
        self.box.submit(self.cap, 'unconsumed-resume', 'resume')
        before = self.box.snapshot()
        with self.assertRaises(ControlBlocked):
            guard(self.owned)
        self.agent._touch_activity.assert_not_called()
        self.assertEqual(self.box.snapshot(), before)

    def paused_control_race(self, command):
        guard = self.guard()
        self.controller._control_thread = None
        self.box.submit(self.cap, 'pause-during-admission', 'pause')
        read = self.box.paused_execution_observation
        def append_after_pause(owned):
            self.box.submit(self.cap, 'control-during-pause-observation', command)
            observation = read(owned)
            self.assertIsNone(observation)
            return observation
        def advance(seconds):
            self.now += seconds
        self.controls.sleep = advance
        with mock.patch.object(self.box, 'paused_execution_observation',
                               side_effect=append_after_pause) as pause_read, \
                mock.patch.object(self.box, 'admission_wait_observation',
                                  wraps=self.box.admission_wait_observation) as wait_read:
            if command == 'cancel':
                with self.assertRaises(rec.ControlStop) as raised:
                    self.controller.control_safe_point()
                self.assertEqual(raised.exception.control_state, 'cancelled')
                self.assertEqual(raised.exception.reason, 'durable_control_acknowledged')
                wait_read.assert_not_called()
                self.agent._touch_activity.assert_not_called()
            else:
                self.controller.control_safe_point()
                wait_read.assert_called_once_with(self.owned)
                self.agent._touch_activity.assert_called_once_with('waiting for adaptive admission')
            pause_read.assert_called_once_with(self.owned)
        snapshot = self.box.snapshot()
        self.assertEqual([row['command'] for row in snapshot.requests], ['resume', 'pause', command])
        self.assertEqual([row['command'] for row in snapshot.receipts], ['resume', 'pause', command])
        self.assertEqual(self.owned.checkpoint.state['phase'], 'waiting_admission')
        self.assertEqual(self.owned.checkpoint.state['pending_request'], self.request)
        self.assertEqual(self.now, 0.25)
        self.assertEqual(self.controls.deadline, 900.0)
        self.assertIsNone(self.controller._control_thread)
        self.assertIsNone(guard.fault)

    def test_resume_arriving_during_paused_observation_returns_to_healthy_admission(self):
        self.paused_control_race('resume')

    def test_cancel_arriving_during_paused_observation_returns_normal_control_stop(self):
        self.paused_control_race('cancel')

    def test_slow_wait_read_requires_a_fresh_unexpired_sdk_lease(self):
        guard = self.guard()
        observe = self.box.admission_wait_observation
        wall = [1000.0]
        order = []
        guard.wall_clock = lambda: wall[0]
        def delayed(owned):
            order.append('observation')
            result = observe(owned)
            wall[0] = 2000.0
            return result
        def lease(*_):
            order.append('lease')
            return 1500.0
        self.db.session_turn_lease_expires_at.side_effect = lease
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=delayed):
            with self.assertRaisesRegex(rec.RecoveryStop, 'lease is missing or expired'):
                guard(self.owned)
        self.assertEqual(order, ['observation', 'lease'])
        self.agent._touch_activity.assert_not_called()

    def test_wait_read_that_crosses_original_deadline_cannot_stamp(self):
        guard = self.guard()
        observe = self.box.admission_wait_observation
        def delayed(owned):
            result = observe(owned)
            self.now = 900.0
            return result
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=delayed):
            guard(self.owned)
        self.agent._touch_activity.assert_not_called()
        self.assertEqual(self.controls.deadline, 900.0)

    def test_failed_observation_is_latched_before_any_lease_or_activity_read(self):
        guard = self.guard()
        with mock.patch.object(self.box, 'admission_wait_observation', side_effect=OSError('read failed')):
            with self.assertRaises(OSError):
                guard(self.owned)
        self.db.session_turn_lease_expires_at.assert_not_called()
        with self.assertRaises(rec.RecoveryStop):
            guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_interruption_or_cleanup_revocation_during_wait_read_cannot_stamp(self):
        observe = self.box.admission_wait_observation
        for change in ('interrupt', 'revoke'):
            with self.subTest(change=change):
                guard = self.guard()
                def changed(owned):
                    result = observe(owned)
                    if change == 'interrupt':
                        self.agent._hard_interrupt_requested.set()
                    else:
                        guard.revoke()
                    return result
                with mock.patch.object(self.box, 'admission_wait_observation', side_effect=changed):
                    with self.assertRaises(rec.RecoveryStop):
                        guard(self.owned)
                self.agent._touch_activity.assert_not_called()

    def test_changed_sdk_and_control_identities_during_lease_read_cannot_stamp(self):
        for change in ('holder', 'session', 'database', 'recovery_database', 'mailbox',
                       'controls', 'deadline', 'checkpoint', 'thread'):
            with self.subTest(change=change):
                guard = self.guard()
                original_controls, original_mailbox = self.controls, self.controls.mailbox
                original_database = self.controller.db
                original_thread = self.controller._control_thread
                def changed(*_):
                    if change == 'holder': self.agent._active_session_turn_lease_holder = 'replacement'
                    elif change == 'session': self.agent.session_id = 'replacement'
                    elif change == 'database': self.agent._session_db = object()
                    elif change == 'recovery_database': self.controller.db = object()
                    elif change == 'mailbox': self.controls.mailbox = object()
                    elif change == 'controls': self.controller.controls = SimpleNamespace()
                    elif change == 'deadline': self.controls.deadline = 1000.0
                    elif change == 'checkpoint': self.save()
                    elif change == 'thread': self.controller._control_thread = None
                    return 2000.0
                self.db.session_turn_lease_expires_at.side_effect = changed
                try:
                    with self.assertRaises(rec.RecoveryStop):
                        guard(self.owned)
                    self.agent._touch_activity.assert_not_called()
                finally:
                    self.controller.controls = original_controls
                    self.controller.db = original_database
                    self.controller._control_thread = original_thread
                    self.controls.mailbox = original_mailbox
                    self.controls.deadline = 900.0

    def test_interruption_or_revocation_during_touch_is_not_recorded_as_success(self):
        for change in ('interrupt', 'revoke'):
            with self.subTest(change=change):
                guard = self.guard()
                def changed(*_):
                    if change == 'interrupt': self.agent._interrupt_requested = True
                    else: guard.revoke()
                self.agent._touch_activity.side_effect = changed
                with self.assertRaises(rec.RecoveryStop):
                    guard(self.owned)
                self.assertEqual(self.agent._touch_activity.call_count, 1)
                self.assertEqual(guard.stamps, 0)
                self.assertIsNone(guard.last_stamp)
                self.agent._interrupt_requested = False
                with self.assertRaises(rec.RecoveryStop):
                    guard.check_final(self.agent)


class LongAdmissionActivityTests(unittest.TestCase):
    setUp = expiry_fixture.WorkerWaitTests.setUp
    exercise = expiry_fixture.WorkerWaitTests.exercise
    preserve = expiry_fixture.WorkerWaitTests.preserve
    common_preservation = expiry_fixture.WorkerWaitTests.common_preservation
    verify_exit = expiry_fixture.WorkerWaitTests.verify_exit

    def test_wait_exceeds_sdk_six_hundred_second_limit_then_safely_expires_at_nine_hundred(self):
        f = self.fixture
        invoke, check = f.invoke, PauseActivity.__call__
        touched = []
        attached = set()
        watchdog = {'last_activity': 0.0, 'interrupted': False}
        def from_start(**kwargs):
            # Override only the existing fixture's start-at-899 shortcut, before
            # the worker starts. The original deadline and execution path remain.
            f.now = 0.0
            return invoke(**kwargs)
        def sdk_boundary(guard, owned, pause_observation=None):
            agent = guard.recovery.agent
            if agent is not None:
                if id(agent) not in attached:
                    original_touch = getattr(agent, '_touch_activity', lambda reason: None)
                    def touch(reason):
                        original_touch(reason)
                        touched.append((f.now, reason))
                        watchdog['last_activity'] = f.now
                    agent._touch_activity = touch
                    attached.add(id(agent))
                # Script the pinned SDK's inactivity edge, not a real watchdog
                # thread. Only the production guard can invoke the touch hook.
                if f.now - watchdog['last_activity'] >= 600.0:
                    watchdog['interrupted'] = True
                    agent._interrupt_requested = True
                    agent._tool_interrupt_reason = 'turn liveness watchdog'
            return check(guard, owned, pause_observation)
        with mock.patch.object(f, 'invoke', side_effect=from_start), \
                mock.patch.object(PauseActivity, '__call__', sdk_boundary):
            self.assertEqual(self.exercise('expiry'), 6, self.result)
        self.common_preservation()
        self.assertFalse(watchdog['interrupted'])
        self.assertTrue(touched)
        self.assertEqual(touched[0][0], 0.0)
        self.assertGreater(touched[-1][0], 600.0)
        self.assertLess(touched[-1][0], 900.0)
        self.assertTrue(all(reason == 'waiting for adaptive admission' for _, reason in touched))
        self.assertTrue(all(15.0 <= later[0] - earlier[0] <= 15.25
                            for earlier, later in zip(touched, touched[1:])))
        self.assertEqual(f.now, 900.0)
        self.assertEqual(execution_outcome(self.cp.state)['schema'], WAIT_EXPIRY_SCHEMA)
        self.assertEqual(self.result['control_reason'], 'admission_wait_budget_expired')
        self.assertFalse(self.result['completed'])
        self.assertFalse(self.result['passed'])
        self.assertEqual(self.verify_exit(6), 'admission_wait_budget_expired')
