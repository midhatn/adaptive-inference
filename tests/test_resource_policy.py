"""Synthetic advancing telemetry; no hardware, processes or backend controls."""
import copy
import math
import unittest

from adaptive_inference.resource_policy import HeadroomPolicy


def reading(stamp, available=8):
    return {"sampled_at": stamp, "available_gib": available, "complete": True}


class HeadroomPolicyTests(unittest.TestCase):
    def policy(self, **kwargs):
        return HeadroomPolicy(4, recovery_seconds=3, max_sample_age_s=2, **kwargs)

    def test_healthy_initial_reading_preserves_floor_and_input(self):
        policy = self.policy()
        snapshot = reading(10, 4)
        original = copy.deepcopy(snapshot)
        self.assertTrue(policy.observe(snapshot, 10))
        self.assertEqual(snapshot, original)
        self.assertFalse(policy.status()['resource_reservation'])
        self.assertFalse(policy.status()['native_actuator'])

    def test_pressure_closes_immediately_recovery_requires_margin_and_duration(self):
        policy = self.policy()
        self.assertTrue(policy.observe(reading(10), 10))
        self.assertFalse(policy.observe(reading(11, 3.99), 11))
        self.assertFalse(policy.observe(reading(12, 4.99), 12))
        for stamp in (13, 14, 15):
            self.assertFalse(policy.observe(reading(stamp, 5), stamp))
        self.assertTrue(policy.observe(reading(16, 5), 16))
        self.assertEqual(policy.reason, 'headroom_recovered')

    def test_replay_does_not_earn_dwell_and_staleness_blocks(self):
        policy = self.policy()
        policy.observe(reading(10, 1), 10)
        policy.observe(reading(11), 11)
        self.assertFalse(policy.observe(reading(11), 12))
        self.assertEqual(policy.status()['recovery_progress_s'], 0)
        self.assertFalse(policy.observe(reading(11), 13.1))
        self.assertEqual(policy.reason, 'telemetry_unavailable')
        for stamp in (14, 15, 16):
            self.assertFalse(policy.observe(reading(stamp), stamp))
        self.assertTrue(policy.observe(reading(17), 17))

    def test_gap_resets_recovery_even_when_new_sample_is_fresh(self):
        policy = self.policy()
        policy.observe(reading(1, 1), 1)
        policy.observe(reading(2), 2)
        policy.observe(reading(3), 3)
        self.assertFalse(policy.observe(reading(10), 10))
        self.assertEqual(policy.status()['recovery_progress_s'], 0)
        for stamp in (11, 12):
            self.assertFalse(policy.observe(reading(stamp), stamp))
        self.assertTrue(policy.observe(reading(13), 13))

    def test_gap_closes_previously_open_gate_until_recovery(self):
        policy = self.policy()
        self.assertTrue(policy.observe(reading(1), 1))
        self.assertFalse(policy.observe(reading(10), 10))
        self.assertEqual(policy.reason, 'recovery_dwell')

    def test_pressure_interrupts_recovery_without_preserving_old_credit(self):
        policy = self.policy()
        policy.observe(reading(1, 1), 1)
        for stamp in (2, 3, 4): policy.observe(reading(stamp), stamp)
        self.assertFalse(policy.observe(reading(5, 3), 5))
        for stamp in (6, 7, 8): self.assertFalse(policy.observe(reading(stamp), stamp))
        self.assertTrue(policy.observe(reading(9), 9))

    def test_invalid_and_future_data_fail_closed(self):
        snapshots = [None, {}, reading(10, -1), reading(10, math.nan), reading(10, math.inf),
                     reading(10, 10**1000), reading(10**1000),
                     reading(10, True), reading(True), reading(11),
                     {**reading(10), 'complete': 1}]
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                policy = self.policy()
                self.assertTrue(policy.observe(reading(9), 9))
                self.assertFalse(policy.observe(snapshot, 10))

    def test_conflicting_timestamp_is_not_a_second_observation(self):
        policy = self.policy()
        self.assertTrue(policy.observe(reading(10), 10))
        self.assertFalse(policy.observe(reading(10, 9), 10))
        self.assertEqual(policy.reason, 'telemetry_conflict')

    def test_regressions_preserve_high_watermark_and_reset_recovery(self):
        policy = self.policy()
        policy.observe(reading(10), 10)
        self.assertFalse(policy.observe(reading(9), 10))
        self.assertEqual(policy.last_sample, 10)
        self.assertFalse(policy.observe(reading(11), 9))
        self.assertEqual(policy.reason, 'clock_regressed')
        self.assertEqual(policy.last_now, 10)
        for stamp in (11, 12, 13): self.assertFalse(policy.observe(reading(stamp), stamp))
        self.assertTrue(policy.observe(reading(14), 14))

    def test_configuration_rejects_nonfinite_boolean_and_invalid_bounds(self):
        for value in (0, -1, True, math.nan, math.inf, 10**1000):
            with self.subTest(minimum=value), self.assertRaises(ValueError):
                HeadroomPolicy(value)
        for kwargs in ({'recovery_seconds': -1}, {'recovery_margin_gib': True},
                       {'max_sample_age_s': 0}, {'max_sample_age_s': 61}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                HeadroomPolicy(4, **kwargs)

    def test_explicit_zero_dwell_retains_recovery_margin(self):
        policy = HeadroomPolicy(4, recovery_seconds=0)
        self.assertFalse(policy.observe(reading(1, 2), 1))
        self.assertFalse(policy.observe(reading(2, 4.5), 2))
        self.assertTrue(policy.observe(reading(3, 5), 3))


if __name__ == '__main__': unittest.main()
