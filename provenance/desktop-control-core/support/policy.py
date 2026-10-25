# SPDX-License-Identifier: Apache-2.0
"""Private policy successor; only trusted own-window recent input is suppressible."""
from copy import deepcopy
import math
from ui_intent import UIIntentGate


def number(value, *, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


class ForegroundPolicy:
    """Explicit conservative desktop policy using observations, never prompts.

    Recent input protects an actual foreground process even when it uses little
    CPU. Sustained foreground CPU protects work without input. Separate engage
    and recovery thresholds prevent repeated load/unload transitions. The dwell
    principle reuses this project's HeadroomPolicy contract and its attributed
    Strata/medking82 lineage; this foreground policy is original implementation.
    """
    def __init__(self, *, input_hold_s=60, cpu_engage_cores=.15,
                 cpu_release_cores=.05, min_available_gib=4,
                 recovery_s=5, max_age_s=1, engage_samples=2,
                 ignored_identities=(), ui_intent=None, cooperative_progress=None):
        for value in (input_hold_s, cpu_engage_cores, cpu_release_cores,
                      min_available_gib, recovery_s, max_age_s):
            if not number(value) or value > 3600:
                raise ValueError("Invalid foreground policy bound")
        if (max_age_s == 0 or cpu_release_cores > cpu_engage_cores
                or type(engage_samples) is not int or not 1 <= engage_samples <= 100):
            raise ValueError("Invalid foreground policy thresholds")
        self.input_hold_s, self.cpu_engage_cores = input_hold_s, cpu_engage_cores
        self.cpu_release_cores, self.min_available_gib = cpu_release_cores, min_available_gib
        self.recovery_s, self.max_age_s, self.engage_samples = recovery_s, max_age_s, engage_samples
        self.ignored = frozenset(tuple(identity) for identity in ignored_identities)
        if any(len(identity) != 2 or any(type(v) is not int or v <= 0 for v in identity)
               for identity in self.ignored):
            raise ValueError("Ignored foreground identities need PID and creation time")
        if ui_intent is not None and type(ui_intent) is not UIIntentGate:
            raise TypeError("Intent must be the exact trusted UIIntentGate")
        self.ui_intent = ui_intent
        if cooperative_progress is not None:
            from ui_progress import CooperativeProgress
            if (type(cooperative_progress) is not CooperativeProgress
                    or cooperative_progress.gate is not ui_intent or self.ignored or ui_intent.max_age_s != 1
                    or (input_hold_s,cpu_engage_cores,cpu_release_cores,
                        min_available_gib,recovery_s,max_age_s,engage_samples)
                       != (60,.15,.05,4,5,1,2)):
                raise TypeError('Cooperative policy requires the exact gate and no ignored identities')
        self.cooperative_progress = cooperative_progress
        self._cooperative_path = False
        self._progress_revision = None
        self._last_input_suppressed = False
        self.allowed = False
        self.yield_requested = False
        self.reason = "awaiting_activity_sample"
        self.last = None
        self.last_now = None
        self.clear_since = None
        self.busy_samples = 0

    def _invalid(self, reason):
        self.allowed = False
        self.clear_since = None
        self.busy_samples = 0
        self.reason = reason
        return False

    def observe(self, sample, now):
        if not number(now) or self.last_now is not None and now < self.last_now:
            return self._invalid("activity_clock_regressed")
        self.last_now = now
        if not isinstance(sample, dict) or sample.get("errors"):
            return self._invalid("activity_unavailable")
        stamp = sample.get("monotonic_s")
        if not number(stamp) or not 0 <= now - stamp <= self.max_age_s:
            return self._invalid("activity_stale")
        if self.last is not None:
            previous = self.last["monotonic_s"]
            if stamp < previous:
                return self._invalid("activity_regressed")
            if stamp == previous:
                if sample != self.last:
                    return self._invalid("activity_conflict")
                if self._cooperative_path and not self._progress_fresh(sample, now):
                    return False
                if (self._last_input_suppressed and
                        not self.ui_intent.matches(sample, now)):
                    return self._invalid("ui_intent_unavailable")
                return self.allowed
            if stamp - previous > self.max_age_s:
                self._invalid("activity_gap")
        foreground, host = sample.get("foreground", {}), sample.get("host", {})
        if not isinstance(foreground, dict) or not isinstance(host, dict):
            return self._invalid("activity_unavailable")
        identity = foreground.get("pid"), foreground.get("creation_time_100ns")
        idle = sample.get("session_input_idle_s")
        cpu = foreground.get("cpu_cores_used")
        ram, commit = host.get("ram_available_gib"), host.get("commit_available_gib")
        if (foreground.get("valid") is not True
                or any(type(v) is not int or v <= 0 for v in identity)
                or not all(number(v) for v in (idle, ram, commit))):
            return self._invalid("activity_unavailable")
        ignored = identity in self.ignored
        own_intent = (not ignored and self.ui_intent is not None
                      and (self.cooperative_progress is not None or idle <= self.input_hold_s)
                      and self.ui_intent.matches(sample, now))
        cooperative = self.cooperative_progress is not None and own_intent
        if (self.cooperative_progress is not None and not own_intent
                and (self.cooperative_progress.pending is not None
                     or self.cooperative_progress.completed is not None)):
            self.cooperative_progress.invalidate('progress_foreground_changed')
        suppressed = (not ignored and idle <= self.input_hold_s
                      and own_intent)
        recent = not ignored and idle <= self.input_hold_s and not suppressed
        if cpu is not None and not number(cpu):
            return self._invalid("activity_unavailable")
        if cpu is None and not recent and not ignored and not cooperative:
            return self._invalid("activity_cpu_warming")
        self.last = deepcopy(sample)
        self._last_input_suppressed = bool(suppressed)
        if cooperative != self._cooperative_path:
            self.clear_since = None
            self.busy_samples = 0
        self._cooperative_path = cooperative
        pressure = min(ram, commit) < self.min_available_gib
        busy = recent or not ignored and cpu is not None and cpu >= self.cpu_engage_cores
        clear = ignored or not recent and cpu is not None and cpu <= self.cpu_release_cores
        if cooperative:
            host_cpu = host.get('cpu_busy_fraction')
            # Owned intent selects this profile: failed health/pressure never
            # falls through to a low foreground-CPU allowance in the old policy.
            if pressure:
                self.yield_requested = True
                return self._invalid('host_memory_pressure')
            if not number(host_cpu) or host_cpu > 1:
                return self._invalid('cooperative_host_cpu_unavailable')
            if not self._progress_fresh(sample, now):
                return False
            busy, clear = host_cpu >= .95, host_cpu <= .80
        if pressure or busy:
            self.allowed = False
            self.clear_since = None
            self.busy_samples += 1
            self.reason = ("host_memory_pressure" if pressure else
                           "host_cpu_pressure" if cooperative else "foreground_activity")
            if pressure or self.busy_samples >= self.engage_samples:
                self.yield_requested = True
            return False
        self.busy_samples = 0
        if not clear:
            self.allowed = False
            self.clear_since = None
            self.reason = "cooperative_recovery_margin" if cooperative else "foreground_recovery_margin"
            return False
        if self.clear_since is None:
            self.clear_since = stamp
        self.allowed = stamp - self.clear_since >= self.recovery_s
        self.reason = (("cooperative_clear" if self.allowed else "cooperative_recovery_dwell") if cooperative
                       else "foreground_clear" if self.allowed else "foreground_recovery_dwell")
        if self.allowed:
            self.yield_requested = False
        return self.allowed

    def fresh(self, now):
        if self._cooperative_path and not self._progress_fresh(self.last, now):
            return False
        if (self._last_input_suppressed and
                not self.ui_intent.matches(self.last, now)):
            return self._invalid("ui_intent_unavailable")
        return (self.last is not None and number(now)
                and 0 <= now - self.last["monotonic_s"] <= self.max_age_s)

    def _progress_fresh(self, sample, now):
        progress = self.cooperative_progress
        healthy = progress.healthy(sample, now)
        if self._progress_revision != progress.revision:
            self._progress_revision = progress.revision
            self.clear_since = None
            self.busy_samples = 0
            self.allowed = False
        if not healthy:
            # Reuse the controller's retained safe-boundary drain. Never cancel
            # active inference or forget its owner when control progress stalls.
            self.yield_requested = True
            return self._invalid('cooperative_' + progress.reason)
        return True
