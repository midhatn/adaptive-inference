# SPDX-License-Identifier: Apache-2.0
"""Trusted host callback for one retained UI process and one root-window lifetime.

No launch/adoption/authentication or UI input is implemented. Windows calls are
deferred until explicit WindowsAPI construction; tests supply fake API tables.
The unchanged UIIntentGate remains responsible for intent and freshness.
"""
import ctypes as C
from ctypes import wintypes as W
import math
import os
import threading
import time

from adaptive_inference.desktop.ui_intent import UIBinding, VerifiedUIObservation

QUERY_AND_SYNCHRONIZE = 0x1000 | 0x100000
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED = 0, 258, 0xffffffff
GA_ROOT = 2
POINTER_LIMIT = 1 << (C.sizeof(C.c_void_p) * 8)


def positive(value, limit):
    return type(value) is int and 0 < value < limit


def timestamp(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class AcquisitionError(RuntimeError):
    """Acquisition failed and closing its duplicate also failed.

    The unavailable verifier preserves an explicit unresolved cleanup obligation.
    Do not retry a numeric CloseHandle blindly; the original launcher handle and
    process lifecycle remain the trusted host's responsibility.
    """
    def __init__(self, primary_error, cleanup_error, verifier):
        super().__init__('UI verifier acquisition and duplicate cleanup both failed')
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        self.verifier = verifier


class WindowsAPI:
    """Minimal WinAPI surface; no OpenProcess, termination, enumeration or input.

    Adapted retained-handle pattern from provenance/ownership.py. API declarations
    follow Microsoft contracts linked in README.md, not copied implementation.
    """
    def __init__(self):
        if os.name != 'nt':
            raise OSError('WindowsAPI requires Windows; CPU tests inject a fake API')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.u = C.WinDLL('user32', use_last_error=True)
        declarations = (
            (self.k, 'GetCurrentProcess', [], W.HANDLE),
            (self.k, 'DuplicateHandle', [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL),
            (self.k, 'GetProcessId', [W.HANDLE], W.DWORD),
            (self.k, 'GetProcessTimes', [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            (self.k, 'WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD),
            (self.k, 'CloseHandle', [W.HANDLE], W.BOOL),
            (self.u, 'GetForegroundWindow', [], W.HWND),
            (self.u, 'GetAncestor', [W.HWND, W.UINT], W.HWND),
            (self.u, 'GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            (self.u, 'GetPropW', [W.HWND, W.LPCWSTR], W.HANDLE),
        )
        for dll, name, args, result in declarations:
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result

    @staticmethod
    def error(operation):
        error = C.WinError(C.get_last_error())
        error.operation = operation
        error.add_note('Retained UI verification: ' + operation)
        return error

    def duplicate(self, source, *, access, inherit, options):
        target = W.HANDLE()
        current = self.k.GetCurrentProcess()
        if not self.k.DuplicateHandle(current, source, current, C.byref(target), access, inherit, options):
            raise self.error('DuplicateHandle')
        return target.value

    def process_identity(self, handle):
        pid = self.k.GetProcessId(handle)
        if not pid:
            raise self.error('GetProcessId')
        times = [W.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *[C.byref(value) for value in times]):
            raise self.error('GetProcessTimes')
        return pid, (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def wait(self, handle, timeout_ms):
        result = self.k.WaitForSingleObject(handle, timeout_ms)
        if result == WAIT_FAILED:
            raise self.error('WaitForSingleObject')
        return result

    def foreground(self):
        return self.u.GetForegroundWindow() or 0

    def root(self, hwnd):
        return self.u.GetAncestor(hwnd, GA_ROOT) or 0

    def window_identity(self, hwnd):
        pid = W.DWORD()
        tid = self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return tid, pid.value

    def marker(self, hwnd, name):
        return self.u.GetPropW(hwnd, name) or 0

    def close(self, handle):
        if not self.k.CloseHandle(handle):
            raise self.error('CloseHandle')


class RetainedUIVerifier:
    """One owner-thread record; intent, launch and authentication live elsewhere.

    `from_launch` accepts only the trusted host's retained launch handle value,
    never an untrusted claimed PID. The API/clock are trusted dependencies.
    Missing/replaced window identity retires this record permanently; ordinary
    foreground changes do not. Errors never prove exit or grant classification.
    """
    @classmethod
    def from_launch(cls, binding, process_handle, marker_name, marker_value, *, api=None, clock=time.monotonic):
        if type(binding) is not UIBinding:
            raise TypeError('Exact existing UIBinding required')
        if not positive(process_handle, POINTER_LIMIT) or not positive(binding.hwnd, POINTER_LIMIT):
            raise ValueError('Actual retained launch handle and native-sized HWND required')
        if (type(marker_name) is not str or not 16 <= len(marker_name) <= 128
                or any(ord(char) < 33 or ord(char) > 126 for char in marker_name)):
            raise ValueError('Fresh bounded unique ASCII session property name required')
        if not positive(marker_value, POINTER_LIMIT) or not callable(clock):
            raise ValueError('Nonzero native-sized marker and trusted clock required')
        self = cls()
        self.binding, self._marker_name, self._marker_value = binding, marker_name, marker_value
        self._api, self._clock = api if api is not None else WindowsAPI(), clock
        self._thread = threading.current_thread()
        self._handle, self._creator_thread = None, None
        self._reading = self._closed = self._retired = self._close_attempted = False
        self._last_clock = self._close_error = self.last_error = None
        self.reason = None
        try:
            handle = self._api.duplicate(process_handle, access=QUERY_AND_SYNCHRONIZE, inherit=False, options=0)
            if not positive(handle, POINTER_LIMIT):
                raise RuntimeError('DuplicateHandle did not return a usable owned handle')
            self._handle = handle
            if not self._process_matches():
                raise RuntimeError('Retained launch process identity unavailable')
            first = self._window_matches()
            if not first or not self._window_matches() or not self._process_matches():
                raise RuntimeError('Initial root window/session identity unavailable')
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                raise AcquisitionError(primary, cleanup, self) from primary
            raise
        return self

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PermissionError('Only the retaining host thread may operate this verifier')

    def revoke(self, reason='authenticated_session_closed'):
        self._owner()
        self._retired = True
        self.reason = reason

    def _process_matches(self):
        value = self._api.wait(self._handle, 0)
        if type(value) is not int or value not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise RuntimeError('Unknown retained process wait result')
        if value == WAIT_OBJECT_0:
            self.revoke('retained_process_exit')
            return False
        identity = self._api.process_identity(self._handle)
        if (type(identity) is not tuple or len(identity) != 2
                or not positive(identity[0], 2**32) or not positive(identity[1], 2**64)):
            raise RuntimeError('Incomplete retained process identity')
        if identity != (self.binding.pid, self.binding.creation_time_100ns):
            self.revoke('retained_process_identity_changed')
            return False
        return True

    def _window_matches(self):
        root = self._api.root(self.binding.hwnd)
        identity = self._api.window_identity(self.binding.hwnd)
        marker = self._api.marker(self.binding.hwnd, self._marker_name)
        if (type(root) is not int or root != self.binding.hwnd
                or type(identity) is not tuple or len(identity) != 2
                or not positive(identity[0], 2**32) or type(identity[1]) is not int
                or identity[1] != self.binding.pid or type(marker) is not int
                or marker != self._marker_value):
            self.revoke('root_window_or_session_identity_lost')
            return False
        if self._creator_thread is None:
            self._creator_thread = identity[0]
        if identity[0] != self._creator_thread:
            self.revoke('window_creator_thread_changed')
            return False
        return True

    def _now(self):
        value = self._clock()
        if not timestamp(value) or self._last_clock is not None and value < self._last_clock:
            self.revoke('host_clock_invalid_or_regressed')
            return None
        self._last_clock = value
        return value

    def verify_current(self, binding):
        if threading.current_thread() is not self._thread:
            return None
        if (type(binding) is not UIBinding or binding != self.binding
                or self._closed or self._retired or self._reading):
            return None
        self._reading = True
        try:
            stamp = self._now()
            if stamp is None or not self._process_matches():
                return None
            first = self._api.foreground()
            if type(first) is not int or first != binding.hwnd:
                self.reason = 'other_or_no_foreground_window'
                return None
            if not self._window_matches():
                return None
            second = self._api.foreground()
            if type(second) is not int or second != binding.hwnd:
                self.reason = 'foreground_changed_during_observation'
                return None
            if not self._window_matches() or not self._process_matches():
                return None
            after = self._now()
            if after is None or self._closed or self._retired:
                return None
            self.reason, self.last_error = None, None
            return VerifiedUIObservation(binding, stamp, True, True)
        except Exception as error:
            self.reason, self.last_error = 'observation_error', error
            return None
        finally:
            self._reading = False

    def is_live(self, binding, *, max_age_s=1):
        """Same retained session checks without requiring foreground activity.

        This is for window readiness/lifecycle, not authentication or input classification. The
        original verify_current and UIIntentGate remain foreground authorities.
        """
        if (threading.current_thread() is not self._thread
                or type(binding) is not UIBinding or binding != self.binding
                or self._closed or self._retired or self._reading
                or not timestamp(max_age_s) or not 0 < max_age_s <= 60):
            return False
        self._reading = True
        try:
            stamp = self._now()
            if (stamp is None or not self._process_matches() or not self._window_matches()
                    or not self._window_matches() or not self._process_matches()):
                return False
            after = self._now()
            if (after is None or after - stamp > max_age_s or self._closed or self._retired):
                return False
            self.reason, self.last_error = None, None
            return True
        except Exception as error:
            self.reason, self.last_error = 'observation_error', error
            return False
        finally:
            self._reading = False

    def close(self):
        """Host must revoke its gate first. A failed close is never hidden/retried.

        No destructor closes on an arbitrary thread. The host owns this explicit
        obligation and must stop/join any observer before calling close.
        """
        self._owner()
        if self._reading:
            raise RuntimeError('Cannot close a retained handle during observation')
        self._closed = True
        if self._close_error is not None:
            raise self._close_error
        if self._handle is None or self._close_attempted:
            return
        self._close_attempted = True
        try:
            self._api.close(self._handle)
        except BaseException as error:
            self._close_error = error
            raise
        self._handle = None

    def status(self):
        self._owner()
        return {'closed': self._closed, 'retired': self._retired, 'reason': self.reason,
                'duplicate_retained': self._handle is not None,
                'duplicate_close_confirmed': self._closed and self._handle is None,
                'close_error': type(self._close_error).__name__ if self._close_error else None}
