import unittest
from activity import Deltas, idle_seconds
from metrics import compare, percentile, summarize


class Sampling(unittest.TestCase):
    def test_tick_wrap_and_nonmonotonic_input(self):
        self.assertEqual(idle_seconds(0x100000020, 0xFFFFFFF0), .048)
        self.assertIsNone(idle_seconds(1000, 1100))

    def test_process_identity_change_and_gap(self):
        d = Deltas()
        self.assertIsNone(d.foreground(0, (10, 100), 0))
        for i in range(1, 5):
            self.assertIsNone(d.foreground(i * .2, (10, 100), i * 1_000_000))
        self.assertAlmostEqual(d.foreground(1, (10, 100), 5_000_000), .5)
        self.assertEqual(d.foreground_window_s, 1)
        self.assertIsNone(d.foreground(1.2, (10, 200), 8_000_000))
        self.assertEqual(len(d.foreground_history), 1)
        self.assertIsNone(d.foreground(10, (10, 200), 10_000_000))
        self.assertIsNone(d.foreground(10.2, None, None))
        self.assertFalse(d.foreground_history)
        self.assertIsNone(d.foreground(10.4, (10, 200), 10_000_000))

    def test_cpu_window_uses_current_counter_and_resets_regression(self):
        d = Deltas()
        for i in range(6):
            d.foreground(i * .2, (10, 100), 0)
        self.assertEqual(d.foreground(1.2, (10, 100), 1_000_000),
                         1_000_000 / 10_000_000 / d.foreground_window_s)
        self.assertEqual(d.foreground_history[-1], (1.2, 1_000_000))
        self.assertIsNone(d.foreground(1.4, (10, 100), 0))
        self.assertEqual(len(d.foreground_history), 1)
        self.assertIsNone(d.foreground(1.4, (10, 100), 0))
        self.assertEqual(len(d.foreground_history), 1)

    def test_cpu_window_and_history_are_bounded(self):
        d = Deltas()
        for i in range(10_000):
            self.assertIsNone(d.foreground(i * .00001, (10, 100), i))
        self.assertEqual(len(d.foreground_history), d.CPU_MAX_SAMPLES)
        self.assertIsNone(d.foreground(3, (10, 100), 20_000))
        self.assertEqual(len(d.foreground_history), 1)
        # A cadence whose predecessor crosses the maximum span is unknown,
        # rather than an arbitrarily long average relabeled as current CPU.
        d = Deltas()
        published = 0
        for t in (0, .4, .8, 1.2, 1.6, 2.0):
            value = d.foreground(t, (10, 100), 0)
            if value is not None:
                published += 1
                self.assertEqual(value, 0)
                self.assertEqual(d.foreground_window_s, t - d.foreground_history[0][0])
                self.assertTrue(1 <= d.foreground_window_s <= 1.25)
                self.assertEqual(d.foreground_history[-1], (t, 0))
        self.assertEqual(published, 3)
        d = Deltas()
        for t in (0, .49, .98):
            self.assertIsNone(d.foreground(t, (10, 100), 0))
        self.assertIsNone(d.foreground(1.47, (10, 100), 0))
        self.assertIsNone(d.foreground_window_s)

    @staticmethod
    def policy_sample(now, cpu):
        return {"monotonic_s": now, "foreground": {"pid": 10,
                "creation_time_100ns": 100, "valid": True, "cpu_cores_used": cpu},
                "session_input_idle_s": 100, "host": {"ram_available_gib": 20,
                "commit_available_gib": 30}, "errors": []}

    def test_quantized_quiet_cpu_recovers_under_unchanged_policy(self):
        from adaptive_inference.handoff import ForegroundPolicy
        d, policy = Deltas(), ForegroundPolicy()
        total = 0
        # True committed work is three 15.625ms quanta per 2.04 seconds.
        # Short deltas reach 0.0766 and 0.1532 cores, despite the low average.
        increments = (0, 0, 156_250, 0, 0, 312_500, 0, 0, 0, 0)
        raw, averaged = [], []
        for i in range(45):
            step = increments[i % len(increments)] if i else 0
            total += step
            now = i * .204
            cpu = d.foreground(now, (10, 100), total)
            if i:
                raw.append(step / 10_000_000 / .204)
            if cpu is not None:
                averaged.append(cpu)
                self.assertLess(cpu, .05)
                self.assertTrue(1 <= d.foreground_window_s <= 1.25)
            policy.observe(self.policy_sample(now, cpu), now)
            if now < 1:
                self.assertIsNone(cpu)
                self.assertFalse(policy.allowed)
        self.assertGreater(max(raw), .15)
        self.assertTrue(policy.allowed)
        self.assertFalse(policy.yield_requested)
        self.assertLess(max(averaged), .05)

    def test_sustained_quantized_cpu_engages_and_recent_input_is_immediate(self):
        from adaptive_inference.handoff import ForegroundPolicy
        d, policy = Deltas(), ForegroundPolicy()
        for i in range(12):
            now = i * .204
            cpu_ticks = int(now * .3 * 10_000_000 // 156_250) * 156_250
            cpu = d.foreground(now, (10, 100), cpu_ticks)
            policy.observe(self.policy_sample(now, cpu), now)
            if cpu is not None:
                self.assertGreater(cpu, .15)
        self.assertTrue(policy.yield_requested)
        self.assertFalse(policy.allowed)
        warming = ForegroundPolicy()
        for now in (0, .204):
            sample = self.policy_sample(now, None)
            sample["session_input_idle_s"] = 0
            self.assertFalse(warming.observe(sample, now))
            self.assertEqual(warming.reason, "foreground_activity")
        self.assertTrue(warming.yield_requested)

    def test_cpu_kernel_includes_idle_and_reset(self):
        d = Deltas()
        self.assertIsNone(d.host((20, 30, 20)))
        self.assertEqual(d.host((40, 60, 40)), .6)
        self.assertIsNone(d.host(None))
        self.assertIsNone(d.host((40, 60, 40)))
        self.assertIsNone(d.host((5, 10, 10)))


class Metrics(unittest.TestCase):
    def fixture(self, fps=60, duration=45, foreground=True):
        frames = [{"elapsed_s": i / fps, "paint_s": i / fps, "post_to_paint_ms": 1}
                  for i in range(int(duration * fps) + 1)]
        observations = [{"elapsed_s": i / 10, "target_foreground": foreground,
                         "target_visible": True} for i in range(int(duration * 10) + 1)]
        return frames, observations

    def test_percentile_and_invalid(self):
        self.assertEqual(percentile(range(1, 101), .95), 95)
        self.assertIsNone(percentile([], .95))
        with self.assertRaises(ValueError):
            percentile([float("nan")], .95)

    def test_valid_baseline_and_no_fake_speedup(self):
        s = summarize(*self.fixture(), duration_s=45)
        self.assertTrue(s["valid_foreground_run"])
        self.assertTrue(compare(s, s, s)["controlled_responsiveness_passed"])
        self.assertFalse(compare(s, s, s)["improvement_observed"])

    def test_hidden_and_short_runs_refused(self):
        self.assertFalse(summarize(*self.fixture(foreground=False), duration_s=45)["valid_foreground_run"])
        self.assertFalse(summarize(*self.fixture(duration=30), duration_s=45)["valid_foreground_run"])
        self.assertFalse(summarize([], [], duration_s=45)["valid_foreground_run"])

    def test_real_degradation_distinction(self):
        baseline = summarize(*self.fixture(), duration_s=45)
        degraded = summarize(*self.fixture(fps=25), duration_s=45)
        decision = compare(baseline, degraded, baseline)
        self.assertTrue(decision["uncontrolled_degradation_detected"])
        self.assertTrue(decision["improvement_observed"])
        self.assertFalse(compare(baseline, degraded, degraded)["controlled_responsiveness_passed"])


if __name__ == "__main__":
    unittest.main()
