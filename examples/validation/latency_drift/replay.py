"""Offline, advisory-only latency-change replay using the released River detector.

No request dispatch, resource actions, model changes, or live telemetry collection.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
DEFAULT_PARAMETERS = {
    "min_instances": 30, "delta": 0.005, "threshold": 50.0,
    "alpha": 0.9999, "mode": "both",
}
BASELINE_PARAMETERS = {
    "decay_s": 60, "ttl_s": 900, "min_samples": 3,
    "max_groups": 1, "max_samples": 32,
}
MAX_RECORDS = 100_000
MAX_COHORTS = 128
MAX_BYTES = 32 * 1024 * 1024
LABEL = re.compile(r"[0-9a-f]{64}\Z")
TRACE_KEYS = {"schema", "units", "duration_scope", "records"}
ROW_KEYS = {"runtime_id", "request_cohort", "observed_at_s", "outcome", "execution_s"}


def finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError("nonfinite JSON constant")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("input exceeds offline replay limit")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def sha_lf(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_dependencies(repository):
    """Verify release sources, then use River and the existing cost-model code."""
    lock = read_json(HERE / "source-lock.json")
    distribution = importlib.metadata.distribution("river")
    if distribution.version != lock["river_version"]:
        raise ValueError("River version differs from inspected release")
    if any(importlib.metadata.version(name) != version
           for name, version in lock["tested_dependencies"].items()):
        raise ValueError("dependency version differs from the recorded replay environment")
    for name, pin in lock["runtime_sources"].items():
        if sha_lf(distribution.locate_file(name)) != pin["sha256_lf"]:
            raise ValueError("River source differs from inspected release")
    from river import drift, stats
    from river.base import drift_detector
    for module, name in (
        (sys.modules[drift.PageHinkley.__module__], "river/drift/page_hinkley.py"),
        (sys.modules[stats.Mean.__module__], "river/stats/mean.py"),
        (drift_detector, "river/base/drift_detector.py"),
    ):
        if Path(module.__file__).resolve() != Path(distribution.locate_file(name)).resolve():
            raise ValueError("River import origin differs from verified distribution")
    cost_path = Path(repository).resolve() / lock["baseline"]["path"]
    if sha_lf(cost_path) != lock["baseline"]["sha256_lf"]:
        raise ValueError("baseline changed: review and repin before replay")
    spec = importlib.util.spec_from_file_location("_offline_latency_costs", cost_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return drift.PageHinkley, module.RequestCostModel, lock


def parameters(value):
    result = dict(DEFAULT_PARAMETERS if value is None else value)
    if set(result) != set(DEFAULT_PARAMETERS):
        raise ValueError("exact detector parameters required")
    if type(result["min_instances"]) is not int or not 30 <= result["min_instances"] <= MAX_RECORDS:
        raise ValueError("minimum sample count must be an integer >= 30")
    if not finite(result["delta"]) or not 0 <= result["delta"] <= 86400:
        raise ValueError("delta must be finite in [0, 86400] seconds")
    if not finite(result["threshold"]) or not 0 < result["threshold"] <= MAX_RECORDS * 86400:
        raise ValueError("threshold must be finite and within the bounded trace scale")
    if not finite(result["alpha"]) or not 0 < result["alpha"] <= 1:
        raise ValueError("alpha must be finite in (0, 1]")
    if result["mode"] not in ("up", "down", "both"):
        raise ValueError("unknown detector mode")
    return result


def replay(trace, *, repository, detector_parameters=None):
    """Replay complete executions, preserving a separate unchanged baseline.

    Cohort labels are caller-supplied opaque digests. They must change with runtime,
    sampling, route, request shape or workload class. This is not automatic grouping.
    """
    config = parameters(detector_parameters)
    if (not isinstance(trace, dict) or set(trace) != TRACE_KEYS
            or trace["schema"] != "adaptive.latency-drift.trace.v1"
            or trace["units"] != "seconds"
            or trace["duration_scope"] != "completed_execution_excluding_queue_and_admission"
            or not isinstance(trace["records"], list) or len(trace["records"]) > MAX_RECORDS):
        raise ValueError("invalid bounded execution-only trace")
    detector_type, cost_type, lock = load_dependencies(repository)
    groups, events = {}, []
    accepted = excluded = alarms = 0
    for index, row in enumerate(trace["records"]):
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("exact aggregate measurement fields required")
        labels = (row["runtime_id"], row["request_cohort"])
        if any(not isinstance(label, str) or LABEL.fullmatch(label) is None for label in labels):
            raise ValueError("cohort labels must be opaque lowercase SHA-256 digests")
        now = row["observed_at_s"]
        if not finite(now) or now < 0:
            raise ValueError("invalid observation clock")
        if row["outcome"] not in ("success", "error", "missing"):
            raise ValueError("unknown outcome")
        group = groups.get(labels)
        if group is None:
            if len(groups) >= MAX_COHORTS:
                raise ValueError("too many explicit cohorts")
            group = groups[labels] = {
                "clock": now, "last_success": None, "count": 0,
                "detector": detector_type(**config), "baseline": cost_type(**BASELINE_PARAMETERS),
            }
        elif now < group["clock"]:
            raise ValueError("per-cohort clock regression")
        group["clock"] = now
        baseline = group["baseline"]
        before = baseline.predict("cohort", now=now)
        reset = None
        duration = row["execution_s"]
        valid = row["outcome"] == "success" and finite(duration) and 0 < duration <= 86400
        if not valid:
            # Invalid success is rejected without changing the baseline's retained
            # estimate. Missing/error events invalidate it without manufacturing
            # a duration just to call observe(success=False). PH resets in both cases.
            reset = row["outcome"] if row["outcome"] != "success" else "invalid_measurement"
            group.update(detector=detector_type(**config), last_success=None, count=0)
            if row["outcome"] != "success":
                group["baseline"] = cost_type(**BASELINE_PARAMETERS)
            excluded += 1
            detected = False
        else:
            if group["last_success"] is not None and now - group["last_success"] > BASELINE_PARAMETERS["ttl_s"]:
                group.update(detector=detector_type(**config), count=0)
                reset = "expired"
            if group["detector"].drift_detected:
                group["count"] = 0  # River itself resets on its next update.
            group["detector"].update(float(duration))
            group["count"] += 1
            group["last_success"] = now
            if not baseline.observe("cohort", float(duration), now=now):
                raise ValueError("existing baseline refused admitted measurement")
            detected = bool(group["detector"].drift_detected)
            accepted += 1
            alarms += int(detected)
        events.append({
            "index": index, "runtime_id": labels[0], "request_cohort": labels[1],
            "included": valid, "reset": reset, "segment_samples": group["count"],
            "evidence": ("insufficient_samples" if group["count"] < config["min_instances"]
                         else "drift_observed" if detected else "no_alarm_observed"),
            "drift_observed": detected,
            "baseline_before": before,
            "baseline_after": group["baseline"].predict("cohort", now=now),
        })
    return {
        "schema": "adaptive.latency-drift.replay.v1", "advisory_only": True,
        "source_lock_sha256_lf": sha_lf(HERE / "source-lock.json"),
        "dependency_versions": lock["tested_dependencies"],
        "detector_source_sha256_lf": {name: pin["sha256_lf"]
                                      for name, pin in lock["runtime_sources"].items()},
        "units": "seconds", "duration_scope": trace["duration_scope"],
        "detector": {"name": "river.drift.PageHinkley", "parameters": config,
                     "release_commit": lock["release_commit"], "version": lock["river_version"]},
        "baseline": {"source_sha256_lf": lock["baseline"]["sha256_lf"],
                     "parameters_per_cohort": BASELINE_PARAMETERS},
        "counts": {"records": len(events), "included": accepted, "excluded": excluded,
                   "cohorts": len(groups), "drift_observations": alarms},
        "events": events,
        "limitations": [
            "An alarm is not a causal diagnosis, confidence guarantee, or permission to adapt.",
            "No alarm does not prove stationarity; sparse histories are explicitly insufficient.",
            "Queue/admission exclusion and cohort correctness depend on the trace producer.",
            "Baseline estimates never consume the detector output; no live policy is changed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=HERE.parents[2])
    parser.add_argument("--parameters", type=Path, help="Optional exact detector-parameter JSON")
    args = parser.parse_args()
    result = replay(read_json(args.trace), repository=args.repository,
                    detector_parameters=None if args.parameters is None else read_json(args.parameters))
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()

