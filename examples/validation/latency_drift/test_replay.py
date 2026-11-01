"""CPU-only offline checks; synthetic data does not qualify a live controller."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import replay
import upstream_page_hinkley

HERE = Path(__file__).resolve().parent
REPOSITORY = Path(os.environ.get("ADAPTIVE_INFERENCE_REPOSITORY", HERE.parents[2]))
RUNTIME = hashlib.sha256(b"synthetic-runtime-A").hexdigest()
COHORT = hashlib.sha256(b"synthetic-request-A").hexdigest()
OTHER = hashlib.sha256(b"synthetic-request-B").hexdigest()


def row(value, index, *, runtime=RUNTIME, cohort=COHORT, outcome="success"):
    return {"runtime_id": runtime, "request_cohort": cohort, "observed_at_s": index * 10,
            "outcome": outcome, "execution_s": value}


def trace(rows):
    return {"schema": "adaptive.latency-drift.trace.v1", "units": "seconds",
            "duration_scope": "completed_execution_excluding_queue_and_admission",
            "records": rows}


def run(rows, **kwargs):
    return replay.replay(trace(rows), repository=REPOSITORY, **kwargs)


class OfflineReplayTests(unittest.TestCase):
    def test_exact_upstream_page_hinkley_regression(self):
        lock = replay.read_json(HERE / "source-lock.json")
        self.assertEqual(hashlib.sha256((HERE / "upstream_page_hinkley.py").read_bytes()).hexdigest(),
                         lock["upstream_test_excerpt_sha256"])
        upstream_page_hinkley.test_page_hinkley()  # Three exact released upstream mode expectations.

    def test_release_source_and_license_identity(self):
        detector, _, lock = replay.load_dependencies(REPOSITORY)
        self.assertEqual(detector()._max_decrease, -1)
        self.assertEqual(replay.sha_lf(HERE / "LICENSE.river"), lock["license_sha256_lf"])
        self.assertTrue(lock["main_is_not_release"])

    def test_stable_heldout_trace_has_no_alarm(self):
        rng = random.Random(91273)
        result = run([row(1 + rng.uniform(-.02, .02), i) for i in range(600)])
        self.assertEqual(result["counts"]["drift_observations"], 0)
        self.assertEqual(result["counts"]["included"], 600)
        self.assertEqual(result["events"][-1]["evidence"], "no_alarm_observed")

    def test_step_and_recovery_produce_advisory_observations(self):
        rng = random.Random(80399)
        values = [level + rng.uniform(-.02, .02) for level in ([1] * 120 + [6] * 120 + [1] * 120)]
        result = run([row(v, i) for i, v in enumerate(values)])
        alarms = [e["index"] for e in result["events"] if e["drift_observed"]]
        self.assertTrue(any(120 <= i < 240 for i in alarms), alarms)
        self.assertTrue(any(240 <= i < 360 for i in alarms), alarms)
        self.assertTrue(result["advisory_only"])
        self.assertNotIn("actions", result)
        self.assertNotIn("policy", result)

    def test_sparse_is_not_stability_proof(self):
        result = run([row(3, i) for i in range(29)])
        self.assertTrue(all(e["evidence"] == "insufficient_samples" for e in result["events"]))
        self.assertEqual(result["counts"]["drift_observations"], 0)

    def test_separate_cohorts_do_not_create_spurious_shift(self):
        rows = [row(1 if i % 2 == 0 else 20, i, cohort=COHORT if i % 2 == 0 else OTHER)
                for i in range(240)]
        result = run(rows)
        self.assertEqual(result["counts"]["cohorts"], 2)
        self.assertEqual(result["counts"]["drift_observations"], 0)
        self.assertEqual([e["segment_samples"] for e in result["events"][-2:]], [120, 120])

    def test_runtime_changes_are_separate_even_same_request(self):
        result = run([row(1, i) for i in range(35)] +
                     [row(20, i, runtime=OTHER) for i in range(35, 70)])
        self.assertEqual(result["counts"]["cohorts"], 2)
        self.assertEqual(result["events"][35]["segment_samples"], 1)
        self.assertEqual(result["events"][35]["baseline_before"]["reason"], "cold")

    def test_failure_and_missing_invalidate_without_a_reward(self):
        for outcome in ("error", "missing"):
            with self.subTest(outcome=outcome):
                result = run([row(5, i) for i in range(35)] +
                             [row(.0001, 35, outcome=outcome), row(5, 36)])
                self.assertEqual(result["counts"]["included"], 36)
                event = result["events"][35]
                self.assertFalse(event["included"])
                self.assertEqual(event["segment_samples"], 0)
                self.assertEqual(event["baseline_after"]["reason"], "cold")
                self.assertEqual(result["events"][36]["segment_samples"], 1)

    def test_invalid_success_measurements_are_never_trained(self):
        for bad in (0, -1, True, None, "1", float("nan"), float("inf"), float("-inf"), 86401, 10**1000):
            with self.subTest(value_type=type(bad).__name__):
                result = run([row(4, i) for i in range(35)] + [row(bad, 35)])
                self.assertEqual(result["counts"]["included"], 35)
                self.assertEqual(result["counts"]["excluded"], 1)
                self.assertEqual(result["events"][-1]["reset"], "invalid_measurement")
                self.assertEqual(result["events"][-1]["baseline_after"],
                                 result["events"][-1]["baseline_before"])

    def test_clock_regression_is_refused(self):
        with self.assertRaisesRegex(ValueError, "clock regression"):
            run([row(1, 2), row(1, 1)])

    def test_invalid_clock_is_refused(self):
        for value in (True, -1, float("nan"), float("inf"), 10**1000):
            item = row(1, 0)
            item["observed_at_s"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                run([item])

    def test_ttl_expiry_resets_detector_and_existing_baseline(self):
        rows = [row(1, i) for i in range(35)] + [row(6, 200)]
        result = run(rows)
        last = result["events"][-1]
        self.assertEqual(last["reset"], "expired")
        self.assertEqual(last["segment_samples"], 1)
        self.assertEqual(last["baseline_before"]["reason"], "expired")
        self.assertEqual(last["baseline_after"]["samples"], 1)

    def test_ttl_boundary_remains_current(self):
        rows = [row(1, i) for i in range(35)]
        last = row(1, 124)  # 1240 - 340 = 900, existing model expires only at >900.
        result = run(rows + [last])
        self.assertIsNone(result["events"][-1]["reset"])
        self.assertEqual(result["events"][-1]["segment_samples"], 36)

    def test_same_trace_baseline_is_unmodified_even_when_ph_alarms(self):
        _, cost_type, _ = replay.load_dependencies(REPOSITORY)
        original = cost_type(**replay.BASELINE_PARAMETERS)
        rows = [row(level, i) for i, level in enumerate([1] * 100 + [9] * 100 + [1] * 100)]
        actual = run(rows)
        for item, event in zip(rows, actual["events"]):
            self.assertEqual(event["baseline_before"], original.predict("cohort", now=item["observed_at_s"]))
            self.assertTrue(original.observe("cohort", item["execution_s"], now=item["observed_at_s"]))
            self.assertEqual(event["baseline_after"], original.predict("cohort", now=item["observed_at_s"]))
        self.assertGreater(actual["counts"]["drift_observations"], 0)

    def test_queue_duration_and_personal_fields_refused(self):
        for key in ("queue_s", "admission_s", "prompt", "path", "user"):
            item = row(1, 0)
            item[key] = "not-public"
            with self.subTest(key=key), self.assertRaises(ValueError):
                run([item])
        value = trace([])
        value["duration_scope"] = "end_to_end"
        with self.assertRaises(ValueError):
            replay.replay(value, repository=REPOSITORY)

    def test_opaque_labels_only(self):
        for value in ("task", "C:/private", "A"*64, "f"*63, None):
            item = row(1, 0)
            item["request_cohort"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                run([item])

    def test_strict_json_and_fresh_output_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(data, encoding="utf-8")
                with self.subTest(data=data), self.assertRaises(ValueError):
                    replay.read_json(path)
            path.write_text(json.dumps(trace([row(1, 0)])), encoding="utf-8")
            output = Path(tmp) / "result.json"
            args = ["replay", "--repository", str(REPOSITORY), "--trace", str(path), "--output", str(output)]
            with patch("sys.argv", args):
                replay.main()
            before = output.read_bytes()
            with patch("sys.argv", args), self.assertRaises(FileExistsError):
                replay.main()
            self.assertEqual(output.read_bytes(), before)

    def test_parameter_guards(self):
        mutations = {
            "min_instances": (True, 2, 29, 30.0, 100001),
            "delta": (-1, float("nan"), float("inf"), True, 86401, 1e308),
            "threshold": (0, -1, float("inf"), True, 10**1000, 1e308),
            "alpha": (0, -1, 1.1, float("nan"), True),
            "mode": ("warning", None),
        }
        for key, values in mutations.items():
            for value in values:
                config = {**replay.DEFAULT_PARAMETERS, key: value}
                with self.subTest(parameter=key, value_type=type(value).__name__), self.assertRaises(ValueError):
                    run([], detector_parameters=config)

    def test_baseline_source_change_refuses(self):
        lock = replay.read_json(HERE / "source-lock.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / lock["baseline"]["path"]
            path.parent.mkdir(parents=True)
            path.write_text("# changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "baseline changed"):
                replay.replay(trace([]), repository=tmp)

    def test_river_source_change_refuses(self):
        original = replay.sha_lf
        with patch.object(replay, "sha_lf", side_effect=lambda p: "wrong" if str(p).endswith("page_hinkley.py") else original(p)):
            with self.assertRaisesRegex(ValueError, "River source differs"):
                run([])

    def test_input_is_not_mutated(self):
        value = trace([row(2, i) for i in range(35)])
        before = copy.deepcopy(value)
        replay.replay(value, repository=REPOSITORY)
        self.assertEqual(value, before)

    def test_empty_trace_is_honest(self):
        result = run([])
        self.assertEqual(result["counts"], {"records": 0, "included": 0, "excluded": 0,
                                           "cohorts": 0, "drift_observations": 0})


if __name__ == "__main__":
    unittest.main()

