"""Pure host-headroom admission with immediate pressure and earned recovery.

Fresh-sample dwell/reset mechanics are adapted from medking82's Strata PR #726,
serve/resource_presets.py and serve/memory_policy.py at
15a59d4785f492b4df3fb78862373a5383696450 (MIT; see third_party/strata/LICENSE).
https://github.com/medking82/Strata/tree/15a59d4785f492b4df3fb78862373a5383696450
Copyright (c) 2026 Niko1221 and the Strata contributors.

This adaptation gates new HTTP dispatch only. It does not resize a cache,
reserve memory, interrupt an active owner, or infer user intent from processes.
The caller supplies complete observations and `now` in the same monotonic clock.
"""
from __future__ import annotations

import math


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class HeadroomPolicy:
    """Keep a closed gate until fresh headroom continuously earns reopening.

    The first valid observation may admit immediately, preserving startup floor
    behavior. After pressure or unavailable telemetry, the recovery threshold is
    minimum + margin for the full recovery duration. No proposal is reported as
    an applied engine allocation. Construct only when the host guard is enabled.
    """

    def __init__(self, minimum_gib, *, recovery_margin_gib=1.0,
                 recovery_seconds=30.0, max_sample_age_s=5.0):
        bounds = ((minimum_gib, "minimum_gib", 0, 16384, False),
                  (recovery_margin_gib, "recovery_margin_gib", 0, 16384, True),
                  (recovery_seconds, "recovery_seconds", 0, 3600, True),
                  (max_sample_age_s, "max_sample_age_s", 0, 60, False))
        for value, name, lower, upper, inclusive in bounds:
            if (not _number(value) or value > upper
                    or (value < lower if inclusive else value <= lower)):
                raise ValueError(f"Invalid headroom policy {name}")
        self.minimum_gib = float(minimum_gib)
        self.recovery_margin_gib = float(recovery_margin_gib)
        self.recovery_seconds = float(recovery_seconds)
        self.max_sample_age_s = float(max_sample_age_s)
        self.allowed = False
        self.reason = "awaiting_telemetry"
        self.latest_available_gib = None
        self.last_sample = self.last_now = self.recovery_since = None
        self.recovery_progress_s = 0.0
        self._recovery_required = False

    def _block(self, reason):
        self.allowed = False
        self.reason = reason
        self._recovery_required = True
        self.recovery_since = None
        self.recovery_progress_s = 0.0
        return False

    def observe(self, snapshot, now):
        """Return admission advice from one bounded, caller-owned observation."""
        if not _number(now) or now < 0:
            return self._block("telemetry_unavailable")
        if self.last_now is not None and now < self.last_now:
            return self._block("clock_regressed")
        self.last_now = now
        if not isinstance(snapshot, dict) or snapshot.get("complete") is not True:
            return self._block("telemetry_unavailable")
        stamp, available = snapshot.get("sampled_at"), snapshot.get("available_gib")
        if (not _number(stamp) or stamp < 0 or not 0 <= now - stamp <= self.max_sample_age_s
                or not _number(available) or available < 0):
            return self._block("telemetry_unavailable")
        if self.last_sample is not None and stamp < self.last_sample:
            return self._block("telemetry_regressed")
        if self.last_sample == stamp:
            # A timestamp identifies an immutable observation. A changed value
            # under that identity is invalid; replay cannot earn recovery time.
            if self.latest_available_gib != available:
                return self._block("telemetry_conflict")
            return self.allowed
        gap = self.last_sample is not None and stamp - self.last_sample > self.max_sample_age_s
        self.last_sample = stamp
        self.latest_available_gib = float(available)
        if gap:
            self._block("telemetry_gap")
        if available < self.minimum_gib:
            return self._block("headroom_below_minimum")
        if not self._recovery_required:
            self.allowed, self.reason = True, "headroom_available"
            return True
        if available < self.minimum_gib + self.recovery_margin_gib:
            return self._block("recovery_margin")
        if self.recovery_since is None:
            self.recovery_since = stamp
        self.recovery_progress_s = stamp - self.recovery_since
        if self.recovery_progress_s < self.recovery_seconds:
            self.allowed, self.reason = False, "recovery_dwell"
            return False
        self.allowed, self.reason = True, "headroom_recovered"
        self._recovery_required = False
        self.recovery_since = None
        return True

    def status(self):
        return {"admission_allowed": self.allowed, "reason": self.reason,
                "minimum_available_gib": self.minimum_gib,
                "recovery_margin_gib": self.recovery_margin_gib,
                "recovery_seconds": self.recovery_seconds,
                "max_sample_age_s": self.max_sample_age_s,
                "last_observed_available_gib": self.latest_available_gib,
                "last_sampled_at": self.last_sample,
                "recovery_progress_s": self.recovery_progress_s,
                "scope": "new_dispatch_admission_only",
                "resource_reservation": False, "native_actuator": False}
