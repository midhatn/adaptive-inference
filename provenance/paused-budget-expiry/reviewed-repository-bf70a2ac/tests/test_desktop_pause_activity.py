"""Serialized Pause activity; deterministic no-provider/no-background fixtures."""
from types import SimpleNamespace
import threading
import unittest
from unittest import mock

from adaptive_inference.desktop.hermes.pause_activity import PauseActivity
from adaptive_inference.desktop.hermes import recovery as rec
import test_desktop_paused_expiry as fixture
NOW = fixture.NOW


class PauseActivityTests(unittest.TestCase):
    setUp=fixture.PausedExpiryTests.setUp
    advance=fixture.PausedExpiryTests.advance
    release=fixture.PausedExpiryTests.release
    pause=fixture.PausedExpiryTests.pause
    finalize=fixture.PausedExpiryTests.finalize

    def guard(self):
        agent=SimpleNamespace(_active_session_turn_lease_holder='exact-holder',session_id='native',
            _session_db=self.db,_interrupt_requested=False,_turn_user_intervened=False,
            _tool_interrupt_reason=None,_hard_interrupt_requested=threading.Event(),
            _touch_activity=mock.Mock(),close=mock.Mock())
        self.agent=self.controller.agent=agent
        self.db.session_turn_lease_expires_at=mock.Mock(return_value=2000)
        self.guardian=PauseActivity(self.controller,wall_clock=lambda:1000,thread_interrupted=lambda:False)
        self.controls.wait_activity=self.guardian
        # Direct guard unit tests represent the synchronous control callback;
        # actual handoff tests enter through Recovery.control_safe_point/tool.
        self.controller._control_thread=threading.current_thread()
        return self.guardian

    def observed(self):
        self.box.submit(self.cap,'pause','pause');self.box.consume(self.owned,updated_at_utc=NOW)
        value={'pause':self.box.paused_execution_observation(self.owned),'observed_at':self.now}
        self.controls.paused_expiry_observation=value
        return value

    def test_only_successful_safe_pause_stamps_at_bounded_cadence_before_original_deadline(self):
        guard=self.guard();self.controls.deadline=100;value=self.observed()
        guard(self.owned,value);self.now+=14;guard(self.owned,value)
        self.assertEqual(self.agent._touch_activity.call_count,1)
        self.now+=1;guard(self.owned,value)
        self.assertEqual(self.agent._touch_activity.call_count,2)
        self.now=100;guard(self.owned,value)
        self.assertEqual(self.agent._touch_activity.call_count,2)
        self.agent._touch_activity.assert_called_with('waiting at acknowledged adaptive Pause')

    def test_allowed_work_health_check_is_not_pause_or_provider_progress(self):
        guard=self.guard();guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_same_owner_outside_active_serialized_control_scope_is_refused(self):
        guard=self.guard();self.controller._control_thread=None
        with self.assertRaisesRegex(rec.RecoveryStop,'serialized control boundary'):guard(self.owned)
        self.controller._control_thread=threading.current_thread()
        with self.assertRaises(rec.RecoveryStop):guard(self.owned)
        self.agent._touch_activity.assert_not_called()

    def test_wrong_claim_or_released_claim_cannot_report_activity(self):
        guard=self.guard()
        with self.assertRaisesRegex(rec.RecoveryStop,'serialized control boundary'):guard(object())
        self.agent._touch_activity.assert_not_called()
        self.release()
        with self.assertRaisesRegex(rec.RecoveryStop,'logical task ownership'):guard.check_final(self.agent)

    def test_replaced_lock_and_changed_epoch_are_not_adopted(self):
        for change in ('lock','epoch'):
            guard=self.guard()
            if change=='lock':self.controller.lock=threading.RLock()
            else:self.owned._epoch+='-other'
            try:
                with self.subTest(change=change),self.assertRaisesRegex(rec.RecoveryStop,'logical task ownership'):
                    guard.check_final(self.agent)
            finally:
                self.controller.lock=guard.lock;self.owned._epoch=guard.epoch
        self.agent._touch_activity.assert_not_called()

    def test_direct_health_failure_is_sticky_after_worker_interrupt_clears(self):
        guard=self.guard();guard.thread_interrupted=lambda:True
        with self.assertRaisesRegex(rec.RecoveryStop,'worker was interrupted'):guard.check_final(self.agent)
        guard.thread_interrupted=lambda:False
        with self.assertRaisesRegex(rec.RecoveryStop,'authority check failed'):guard.check_final(self.agent)
        self.agent._touch_activity.assert_not_called()

    def test_revoked_owner_cannot_resume_or_stamp_after_cleanup(self):
        guard=self.guard();value=self.observed()
        with guard.cleanup_scope(self.agent,verify=True):pass
        with self.assertRaisesRegex(rec.RecoveryStop,'revoked'):guard(self.owned,value)
        self.agent._touch_activity.assert_not_called()

    def test_control_scope_is_restored_when_real_gate_raises(self):
        self.guard();self.controller._control_thread=None
        self.box.submit(self.cap,'resume','resume')
        with mock.patch.object(self.controls,'poll',side_effect=OSError('control read failed')):
            with self.assertRaises(OSError):self.controller.control_safe_point()
        self.assertIsNone(self.controller._control_thread)

    def test_missing_expired_or_failed_lease_read_cannot_heartbeat_or_seal(self):
        guard=self.guard();value=self.observed()
        for expiry in (None,True,1000,999,float('inf')):
            self.db.session_turn_lease_expires_at.return_value=expiry
            with self.subTest(expiry=expiry),self.assertRaises(rec.RecoveryStop):guard(self.owned,value)
        self.agent._touch_activity.assert_not_called()
        self.db.session_turn_lease_expires_at.return_value=2000
        with self.assertRaises(rec.RecoveryStop):guard.check_final(self.agent)

    def test_slow_read_checks_current_time_after_completion(self):
        guard=self.guard();value=self.observed();wall=[1000]
        guard.wall_clock=lambda:wall[0]
        def delayed(*_):wall[0]=2000;return 1500
        self.db.session_turn_lease_expires_at.side_effect=delayed
        with self.assertRaises(rec.RecoveryStop):guard(self.owned,value)
        self.agent._touch_activity.assert_not_called()

    def test_changed_holder_is_not_adopted(self):
        guard=self.guard();value=self.observed();guard(self.owned,value)
        self.agent._active_session_turn_lease_holder='replacement'
        with self.assertRaises(rec.RecoveryStop):guard(self.owned,value)
        self.assertEqual(self.agent._touch_activity.call_count,1)

    def test_committed_interrupt_before_or_during_touch_is_latched(self):
        guard=self.guard();value=self.observed()
        self.agent._touch_activity.side_effect=lambda *_:setattr(self.agent,'_turn_user_intervened',True)
        with self.assertRaises(rec.RecoveryStop):guard(self.owned,value)
        self.agent._turn_user_intervened=False  # Even an external clear cannot erase our fault.
        with self.assertRaises(rec.RecoveryStop):guard.check_final(self.agent)

    def test_sdk_unwind_cleared_flags_cannot_launder_committed_abort_or_lease_fallback(self):
        guard=self.guard();self.pause()
        for field,value in (('_turn_user_intervened',True),('_tool_interrupt_reason','session turn lease lost')):
            setattr(self.agent,field,value)
            with self.subTest(field=field),self.assertRaises(rec.RecoveryStop):self.finalize()
            setattr(self.agent,field,False if field=='_turn_user_intervened' else None)
        self.agent.close.assert_not_called()

    def test_failed_coherent_pause_read_never_reaches_activity_callback(self):
        guard=self.guard();self.box.submit(self.cap,'pause','pause')
        with mock.patch.object(self.box,'paused_execution_observation',side_effect=OSError('read blocked/failed')):
            with self.assertRaises(OSError):self.controller.control_safe_point()
        self.agent._touch_activity.assert_not_called()
        self.db.session_turn_lease_expires_at.assert_not_called()

    def test_production_finish_after_verified_sdk_return_and_released_lease_is_preserved(self):
        guard=self.guard()
        self.box.submit(self.cap,'resume','resume');self.box.consume(self.owned,updated_at_utc=NOW)
        guard(self.owned)  # Real owned turn before the facade returns.
        self.agent._active_session_turn_lease_holder=None
        outcome={'completed':True,'failed':False,'interrupted':False,'final_response':'finished'}
        guard.finish_turn(outcome)
        self.controller.finish(outcome)
        self.assertEqual(self.owned.checkpoint.state['status'],'accepted')
        self.agent._touch_activity.assert_not_called()

    def test_missing_live_holder_or_aborted_completion_never_enables_post_turn_bypass(self):
        guard=self.guard();self.agent._active_session_turn_lease_holder=None
        with self.assertRaises(rec.RecoveryStop):guard(self.owned)
        with self.assertRaises(rec.RecoveryStop):guard.finish_turn({'completed':True})
        self.assertFalse(guard.finished)

    def test_blocked_lease_read_has_no_independent_heartbeat(self):
        guard=self.guard();value=self.observed()
        entered=threading.Event();release=threading.Event();observations=[]
        def read(*_):
            entered.set()
            if not release.wait(3):raise TimeoutError('fixture release missing')
            raise OSError('lease read failed after blocking')
        def inspect():
            if entered.wait(3):observations.append(self.agent._touch_activity.call_count)
            release.set()
        self.db.session_turn_lease_expires_at.side_effect=read
        observer=threading.Thread(target=inspect);observer.start()
        try:
            with self.assertRaises(OSError):guard(self.owned,value)
        finally:release.set();observer.join(3)
        self.assertFalse(observer.is_alive());self.assertEqual(observations,[0])
        self.agent._touch_activity.assert_not_called()
