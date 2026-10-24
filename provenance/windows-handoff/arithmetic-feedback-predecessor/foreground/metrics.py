"""Deterministic foreground report and predeclared comparison rules."""
from __future__ import annotations
import math


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    if not 0 < q <= 1 or not all(math.isfinite(v) and v >= 0 for v in values):
        raise ValueError("finite nonnegative values and 0 < q <= 1 required")
    return values[max(0, math.ceil(len(values) * q) - 1)]


def summarize(frames, observations, *, duration_s, warmup_s=5):
    kept = [r for r in frames if warmup_s <= r["elapsed_s"] <= duration_s]
    intervals = [(b["paint_s"] - a["paint_s"]) * 1000 for a, b in zip(kept, kept[1:])]
    latencies = [r["post_to_paint_ms"] for r in kept]
    observed = [r for r in observations if warmup_s <= r["elapsed_s"] <= duration_s]
    covered = [r for r in observed if r["target_foreground"] and r["target_visible"]]
    result = {
        "measurement": "GDI paint submission and host-message scheduling; not physical display/input latency",
        "duration_s": duration_s, "warmup_s": warmup_s,
        "frames": len(kept), "samples": len(observed),
        "foreground_fraction": len(covered) / len(observed) if observed else 0,
        "paint_interval_p95_ms": percentile(intervals, .95),
        "paint_interval_p99_ms": percentile(intervals, .99),
        "paint_interval_max_ms": max(intervals, default=None),
        "post_to_paint_p95_ms": percentile(latencies, .95),
        "stalls_over_50ms_fraction": sum(x > 50 for x in intervals) / len(intervals) if intervals else 1,
    }
    # Sufficient samples + full observation duration prevents a frozen sampler or
    # early close being accepted from a handful of good frames.
    result["valid_foreground_run"] = (
        len(kept) >= (duration_s - warmup_s) * 15
        and len(observed) >= (duration_s - warmup_s) * 5
        and result["foreground_fraction"] >= .95
        and kept[-1]["elapsed_s"] >= duration_s - .3
        and observed[-1]["elapsed_s"] >= duration_s - .3)
    return result


def compare(baseline, uncontrolled, controlled):
    valid = all(x["valid_foreground_run"] for x in (baseline, uncontrolled, controlled))
    bp, up, cp = (x["paint_interval_p95_ms"] for x in (baseline, uncontrolled, controlled))
    baseline_valid = valid and bp is not None and bp <= 25
    limit = max(25, bp * 1.25) if bp is not None else None
    accepted = bool(baseline_valid and cp <= limit
                    and controlled["stalls_over_50ms_fraction"] <= .01)
    detectable = bool(baseline_valid and (up > max(25, bp * 1.25)
                      or uncontrolled["stalls_over_50ms_fraction"] > .01))
    improvement = bool(accepted and detectable and cp < up)
    return {"valid_comparison": bool(baseline_valid), "controlled_p95_limit_ms": limit,
            "controlled_responsiveness_passed": accepted,
            "uncontrolled_degradation_detected": detectable,
            "improvement_observed": improvement,
            "scope": "One foreground GDI workload; controller handoff/agent continuation require separate receipts"}
