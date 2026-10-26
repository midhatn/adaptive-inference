# SPDX-License-Identifier: Apache-2.0
"""Bounded cooperative host intent; no UI, authentication transport or OS probe.

The host must supply a synchronous, bounded, read-only verifier using its own
retained process/window identity. A receipt is that trusted callback's input,
not independently implemented proof here. See README.md before integration.
"""
from dataclasses import dataclass
import inspect
import math
import threading
import time


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _label(value):
    if (type(value) is not str or not 1 <= len(value) <= 128
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise ValueError('Bounded non-whitespace ASCII identity required')
    return value


@dataclass(frozen=True)
class UIBinding:
    host_epoch: str
    session_id: str
    task_id: str
    hwnd: int
    pid: int
    creation_time_100ns: int

    def __post_init__(self):
        for value in (self.host_epoch, self.session_id, self.task_id):
            _label(value)
        for value, limit in ((self.hwnd, 2**64), (self.pid, 2**32),
                             (self.creation_time_100ns, 2**64)):
            if type(value) is not int or not 0 < value < limit:
                raise ValueError('Exact positive bounded Windows identity required')


@dataclass(frozen=True)
class VerifiedUIObservation:
    """Only a trusted host verifier may produce this complete observation.

    `window_matches` must mean the exact root HWND currently belongs to the
    retained live process and is foreground. It is not IsWindow alone. This
    type is not a capability and cannot be supplied through a public request.
    """
    binding: UIBinding
    observed_at_monotonic: float
    process_alive: bool
    window_matches: bool


class UIIntentGate:
    """One current window; finite remembered sessions/tasks; owner-thread only.

    Gate state is ephemeral for one host epoch. No timestamps are serialized.
    Matching never renews intent, writes TaskStore, acquires resource ownership
    or changes the sensor sample. Invalid verification simply grants nothing.
    """
    def __init__(self, *, host_epoch, capability, verify_current,
                 clock=time.monotonic, max_age_s=1,
                 max_sessions=32, max_tasks=32):
        self.host_epoch = _label(host_epoch)
        if type(capability) is not object:
            raise TypeError('Exact private host capability required')
        if (not callable(verify_current) or inspect.iscoroutinefunction(verify_current)
                or not callable(clock)):
            raise TypeError('Synchronous trusted verifier and clock required')
        if not _number(max_age_s) or not 0 < max_age_s <= 60:
            raise ValueError('Finite observation freshness bound required')
        if any(type(v) is not int or not 1 <= v <= 1000 for v in (max_sessions, max_tasks)):
            raise ValueError('Finite identity limits from 1 to 1000 required')
        self._capability, self._verify, self._clock = capability, verify_current, clock
        # Python documents that numeric thread IDs may be recycled. Retain the
        # creator Thread object instead of authorizing a later reused ID.
        self._thread = threading.current_thread()
        self.max_age_s = max_age_s
        self.max_sessions, self.max_tasks = max_sessions, max_tasks
        self._sessions, self._tasks, self._retired, self._terminal = {}, set(), set(), set()
        self._binding = self._active = None
        self._verified_stamp = None
        self._last_clock = None
        self._clock_fault = False
        self._revision = 0
        self._progress = None  # Optional private cooperative observer; never a wire input.

    def _advance(self):
        self._revision += 1
        if self._progress is not None:
            self._progress.invalidate('intent_generation_changed')

    def _authorize(self, capability):
        if capability is not self._capability or threading.current_thread() is not self._thread:
            raise PermissionError('Only the bound host thread may change UI intent')

    def _now(self):
        if self._clock_fault:
            return None
        try:
            now = self._clock()
        except Exception:
            now = None
        if (not _number(now) or self._last_clock is not None and now < self._last_clock):
            self._clock_fault = True
            self._active = None
            self._advance()
            return None
        self._last_clock = now
        return now

    def bind(self, capability, binding):
        """Register a launcher-verified window; replacing it retires its session."""
        self._authorize(capability)
        if type(binding) is not UIBinding or binding.host_epoch != self.host_epoch:
            raise ValueError('Exact binding for this host epoch required')
        if binding.task_id in self._terminal or binding.session_id in self._retired:
            raise ValueError('Terminal task or retired UI session cannot reopen')
        known = self._sessions.get(binding.session_id)
        if known is not None:
            if known != binding or self._binding != binding:
                raise ValueError('A session cannot change or regain its identity')
            return binding
        if len(self._sessions) >= self.max_sessions:
            raise ValueError('UI session history exhausted; no identity is forgotten')
        if binding.task_id not in self._tasks and len(self._tasks) >= self.max_tasks:
            raise ValueError('UI task identity history exhausted')
        if self._binding is not None:
            self._retired.add(self._binding.session_id)
        self._sessions[binding.session_id] = binding
        self._tasks.add(binding.task_id)
        self._binding, self._active = binding, None
        self._verified_stamp = None
        self._advance()
        return binding

    def activate(self, capability, *, session_id, task_id):
        """Explicit intent lasts for the task/session, not a model-load timer.

        Permission still requires a new or still-fresh verified observation on
        every check. This method never changes durable task state/accounting.
        """
        self._authorize(capability)
        _label(session_id); _label(task_id)
        binding = self._binding
        if (binding is None or binding.session_id != session_id or binding.task_id != task_id
                or session_id in self._retired or task_id in self._terminal):
            raise ValueError('Current live session/task binding required')
        now = self._now()
        if now is None:
            raise ValueError('Host clock cannot authorize activation')
        self._active = (binding, now)
        self._verified_stamp = None
        self._advance()
        return {'session_id': session_id, 'task_id': task_id, 'active': True}

    def deactivate(self, capability):
        """Pause/stop removes intent; a later genuine Resume may reactivate."""
        self._authorize(capability)
        self._active = None
        self._advance()

    def revoke(self, capability, session_id):
        self._authorize(capability)
        if _label(session_id) not in self._sessions:
            raise ValueError('Unknown UI session')
        self._retired.add(session_id)
        if self._binding is not None and self._binding.session_id == session_id:
            self._binding = self._active = None
        self._advance()

    def terminal(self, capability, task_id):
        """Host reports cancelled/fulfilled/terminal task; never writes its outcome."""
        self._authorize(capability)
        if _label(task_id) not in self._tasks:
            raise ValueError('Unknown task identity')
        self._terminal.add(task_id)
        if self._binding is not None and self._binding.task_id == task_id:
            self._retired.add(self._binding.session_id)
            self._binding = self._active = None
        self._advance()

    def _receipt_valid(self, receipt, binding, activated, after):
        return (type(receipt) is VerifiedUIObservation
                and type(receipt.binding) is UIBinding and receipt.binding == binding
                and receipt.process_alive is True and receipt.window_matches is True
                and _number(receipt.observed_at_monotonic)
                and activated <= receipt.observed_at_monotonic <= after
                and after - receipt.observed_at_monotonic <= self.max_age_s
                and (self._verified_stamp is None
                     or receipt.observed_at_monotonic >= self._verified_stamp))

    def matches(self, sample, policy_now):
        """Advisory classification only; raw sample and resource gates unchanged."""
        if threading.current_thread() is not self._thread:
            return False
        now = self._now()
        active, revision = self._active, self._revision
        if now is None or active is None or not _number(policy_now):
            return False
        binding, activated = active
        if (binding != self._binding or binding.session_id in self._retired
                or binding.task_id in self._terminal
                or not 0 <= now - policy_now <= self.max_age_s):
            return False
        if type(sample) is not dict or sample.get('errors'):
            return False
        stamp, foreground = sample.get('monotonic_s'), sample.get('foreground')
        if (not _number(stamp) or not activated <= stamp <= now
                or now - stamp > self.max_age_s or type(foreground) is not dict
                or foreground.get('valid') is not True):
            return False
        for name, expected in (('hwnd', binding.hwnd), ('pid', binding.pid),
                               ('creation_time_100ns', binding.creation_time_100ns)):
            if type(foreground.get(name)) is not int or foreground[name] != expected:
                return False
        try:
            receipt = self._verify(binding)
        except Exception:
            return False
        after = self._now()
        if (after is None or revision != self._revision or self._active != active
                or after - stamp > self.max_age_s
                or after - policy_now > self.max_age_s
                or not self._receipt_valid(receipt, binding, activated, after)):
            return False
        self._verified_stamp = receipt.observed_at_monotonic
        return True
