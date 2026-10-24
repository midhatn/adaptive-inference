"""Privacy-minimal Windows activity sampling. No UI changes, hooks or process control.

Original code, Apache-2.0. API references and limitations are in RESEARCH.md.
"""
from __future__ import annotations
from collections import deque
import ctypes as C
from ctypes import wintypes as W
import math
import os
import time


def idle_seconds(now_tick: int, input_tick: int) -> float | None:
    # LASTINPUTINFO is a 32-bit tick count, even on 64-bit Windows. A future or
    # non-incremental timestamp must not become a false forty-nine-day idle.
    elapsed = ((now_tick & 0xFFFFFFFF) - input_tick) & 0xFFFFFFFF
    return elapsed / 1000 if elapsed <= 7 * 24 * 3600 * 1000 else None


class Deltas:
    # Windows process CPU time may arrive in ~15.6ms accounting quanta. Keep
    # actual endpoints across one second, rather than magnifying each quantum
    # over a 100-200ms polling interval. No counter interpolation is performed.
    CPU_WINDOW_S = 1.0
    CPU_MAX_SPAN_S = 1.25
    CPU_MAX_GAP_S = .5
    CPU_MAX_SAMPLES = 128

    def __init__(self):
        self.previous_host = None
        self.previous_foreground = None
        self.foreground_history = deque(maxlen=self.CPU_MAX_SAMPLES)
        self.foreground_window_s = None

    def host(self, counters):
        old, self.previous_host = self.previous_host, counters
        if old is None or counters is None:
            return None
        idle, kernel, user = (n - p for n, p in zip(counters, old))
        total = kernel + user  # kernel includes idle
        if min(idle, kernel, user) < 0 or total <= 0 or idle > total:
            return None
        return (total - idle) / total

    def foreground(self, now, identity, cpu_100ns):
        self.foreground_window_s = None
        if (not identity or type(now) not in (int, float) or not math.isfinite(now)
                or type(cpu_100ns) is not int or cpu_100ns < 0):
            self.previous_foreground = None
            self.foreground_history.clear()
            return None
        old = self.previous_foreground
        if (old is None or old[1] != identity or not 0 < now - old[0] <= self.CPU_MAX_GAP_S
                or cpu_100ns < old[2]):
            self.foreground_history.clear()
        self.previous_foreground = (now, identity, cpu_100ns)
        self.foreground_history.append((now, cpu_100ns))
        cutoff = now - self.CPU_WINDOW_S
        # Keep the latest real observation at/before the cutoff. A bounded
        # sample-interval overshoot is honest; interpolating a past counter is not.
        while len(self.foreground_history) >= 2 and self.foreground_history[1][0] <= cutoff:
            self.foreground_history.popleft()
        first_time, first_cpu = self.foreground_history[0]
        elapsed = now - first_time
        if not self.CPU_WINDOW_S <= elapsed <= self.CPU_MAX_SPAN_S:
            return None
        self.foreground_window_s = elapsed
        return (cpu_100ns - first_cpu) / 10_000_000 / elapsed


class WindowsActivityReader:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows desktop session required")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.u.GetForegroundWindow.restype = W.HWND
        self.u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.u.GetWindowThreadProcessId.restype = W.DWORD
        self.k.GetTickCount64.restype = C.c_ulonglong
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
        self.k.GetProcessTimes.restype = W.BOOL
        self.k.GetSystemTimes.argtypes = [C.POINTER(W.FILETIME)] * 3
        self.k.GetSystemTimes.restype = W.BOOL
        self.deltas = Deltas()

    @staticmethod
    def _ticks(value):
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def sample(self):
        now = time.monotonic()
        errors = []
        pid = W.DWORD()
        hwnd = self.u.GetForegroundWindow()
        valid = bool(hwnd and self.u.GetWindowThreadProcessId(hwnd, C.byref(pid)))
        identity, cpu = None, None
        if valid:
            handle = self.k.OpenProcess(0x1000, False, pid.value)  # query only
            if handle:
                try:
                    created, ended, kernel, user = (W.FILETIME() for _ in range(4))
                    if self.k.GetProcessTimes(handle, C.byref(created), C.byref(ended),
                                              C.byref(kernel), C.byref(user)):
                        identity = (pid.value, self._ticks(created))
                        cpu = self._ticks(kernel) + self._ticks(user)
                    else:
                        errors.append("GetProcessTimes")
                finally:
                    self.k.CloseHandle(handle)
            else:
                errors.append("OpenProcess")
        else:
            errors.append("ForegroundUnavailable")
        class LastInput(C.Structure):
            _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]
        inp = LastInput(C.sizeof(LastInput), 0)
        idle = None
        if self.u.GetLastInputInfo(C.byref(inp)):
            idle = idle_seconds(self.k.GetTickCount64(), inp.dwTime)
        else:
            errors.append("GetLastInputInfo")
        counters = None
        values = [W.FILETIME() for _ in range(3)]
        if self.k.GetSystemTimes(*(C.byref(x) for x in values)):
            counters = tuple(self._ticks(x) for x in values)
        else:
            errors.append("GetSystemTimes")
        class Memory(C.Structure):
            _fields_ = [("length", W.DWORD), ("load", W.DWORD)] + [
                (name, C.c_ulonglong) for name in
                ("total_phys", "avail_phys", "total_page", "avail_page",
                 "total_virtual", "avail_virtual", "avail_extended")]
        memory = Memory()
        memory.length = C.sizeof(memory)
        ram, commit = None, None
        if self.k.GlobalMemoryStatusEx(C.byref(memory)):
            ram, commit = memory.avail_phys / 2**30, memory.avail_page / 2**30
        else:
            errors.append("GlobalMemoryStatusEx")
        # Do not blend a CPU observation across a foreground switch during the
        # read. A valid PID without process identity remains visible but unknown.
        final_pid = W.DWORD()
        final_hwnd = self.u.GetForegroundWindow()
        if (not final_hwnd or not self.u.GetWindowThreadProcessId(final_hwnd, C.byref(final_pid))
                or final_pid.value != pid.value):
            valid, identity, cpu = False, None, None
            errors.append("ForegroundChangedDuringSample")
        foreground_cpu = self.deltas.foreground(now, identity, cpu)
        return {
            "schema": "adaptive.foreground-sample.v1", "monotonic_s": now,
            "foreground": {"pid": pid.value if valid else None,
                           "creation_time_100ns": identity[1] if identity else None,
                           "valid": valid,
                           "cpu_cores_used": foreground_cpu,
                           "cpu_window_s": self.deltas.foreground_window_s},
            "session_input_idle_s": idle,
            "host": {"cpu_busy_fraction": self.deltas.host(counters),
                     "ram_available_gib": ram, "commit_available_gib": commit},
            "errors": errors,
        }
