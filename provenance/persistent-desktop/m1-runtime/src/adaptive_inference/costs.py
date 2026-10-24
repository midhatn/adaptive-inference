"""Small, process-local latency model for the opt-in inference waiting queue.

Peak EWMA follows Finagle's latency-spike update (Apache-2.0, Twitter Inc.):
https://github.com/twitter/finagle/blob/9cc08d15216497bb03a1cafda96b7266cfbbcff1/
finagle-core/src/main/scala/com/twitter/finagle/loadbalancer/PeakEwma.scala
See third_party/finagle/NOTICE and LICENSE.

Unlike a network endpoint probe, an idle inference workload is not assumed to
become arbitrarily cheap: reads do not decay its estimate toward zero. A new
measurement permits recovery; stale measurements expire. The empirical p90 is
a tail guard, NOT a confidence interval or a guaranteed completion deadline.

The host supplies an opaque runtime/request-shape key and measures completed
execution, excluding queue and admission time. No prompt, response, user name,
or credential belongs in this model. Learning latency does not certify quality
or authorize another device, model, precision, context size or resource lease.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import math
import threading


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class _Group:
    rows: deque = field(default_factory=deque)
    peak: float = 0.0
    stamp: float = 0.0


class RequestCostModel:
    """Bounded empirical cost feedback. All methods are safe across request threads.

    Keys must change when the actual runtime, sampling, route, request shape or
    workload class changes. The server intentionally starts cold after restart.
    Unknown, sparse, expired or invalid observations provide no learned estimate.
    """

    def __init__(self, decay_s=60, ttl_s=900, min_samples=3, max_groups=128, max_samples=32):
        if (not _finite(decay_s) or not 0 < decay_s <= 86400
                or not _finite(ttl_s) or not 0 < ttl_s <= 86400
                or type(min_samples) is not int or not 3 <= min_samples <= 256
                or type(max_samples) is not int or not min_samples <= max_samples <= 256
                or type(max_groups) is not int or not 1 <= max_groups <= 1024):
            raise ValueError("invalid request cost model limits")
        self.decay_s, self.ttl_s = float(decay_s), float(ttl_s)
        self.min_samples, self.max_samples, self.max_groups = min_samples, max_samples, max_groups
        self._groups = OrderedDict()
        self._lock = threading.Lock()
        self._observations = self._rejected = self._evicted = 0

    @staticmethod
    def _valid_key(key):
        return isinstance(key, str) and 0 < len(key) <= 128

    def _recent(self, group, now):
        while group.rows and now - group.rows[0][0] > self.ttl_s:
            group.rows.popleft()
        return bool(group.rows)

    def observe(self, key, duration_s, *, now, success=True):
        """Record one complete execution; never reward fast errors or cancellation.

        A reported failure invalidates that group's estimate. Failed and partial
        execution times do not represent the time needed to finish the request.
        """
        with self._lock:
            if (not self._valid_key(key) or not _finite(now) or now < 0
                    or not _finite(duration_s) or not 0 < duration_s <= 86400
                    or type(success) is not bool):
                self._rejected += 1
                return False
            if not success:
                self._groups.pop(key, None)
                self._rejected += 1
                return False
            group = self._groups.get(key)
            if group is not None and now < group.stamp:
                self._rejected += 1
                return False
            if group is None or not self._recent(group, now):
                group = _Group(peak=float(duration_s), stamp=float(now))
                self._groups[key] = group
            else:
                # Finagle's uneven-time-series Peak EWMA: immediate rise, then
                # exponential recovery on subsequent successful observations.
                weight = math.exp(-(now - group.stamp) / self.decay_s)
                group.peak = (float(duration_s) if duration_s > group.peak else
                              group.peak * weight + float(duration_s) * (1 - weight))
                group.stamp = float(now)
            group.rows.append((float(now), float(duration_s)))
            while len(group.rows) > self.max_samples:
                group.rows.popleft()
            self._groups.move_to_end(key)
            while len(self._groups) > self.max_groups:
                self._groups.popitem(last=False)
                self._evicted += 1
            self._observations += 1
            return True

    def predict(self, key, *, now):
        """Return a recent empirical estimate, or an explicit cold fallback."""
        missing = {"estimate_s": None, "samples": 0, "reason": "cold",
                   "peak_s": None, "p90_s": None, "observed_range_s": None}
        with self._lock:
            if not self._valid_key(key) or not _finite(now) or now < 0:
                return {**missing, "reason": "invalid_context"}
            group = self._groups.get(key)
            if group is None:
                return missing
            if now < group.stamp:
                return {**missing, "reason": "clock_regressed"}
            if not self._recent(group, now):
                del self._groups[key]
                return {**missing, "reason": "expired"}
            values = sorted(value for _, value in group.rows)
            p90 = values[math.ceil(.9 * len(values)) - 1]
            ready = len(values) >= self.min_samples
            return {"estimate_s": max(group.peak, p90) if ready else None,
                    "samples": len(values), "reason": "measured" if ready else "sparse",
                    "peak_s": group.peak, "p90_s": p90,
                    "observed_range_s": [values[0], values[-1]]}

    def status(self):
        with self._lock:
            return {"kind": "peak_ewma_empirical_p90", "groups": len(self._groups),
                    "observations": self._observations, "rejected": self._rejected,
                    "evicted": self._evicted, "max_groups": self.max_groups,
                    "max_samples": self.max_samples, "minimum_samples": self.min_samples,
                    "expires_after_s": self.ttl_s, "recovery_decay_s": self.decay_s}
