"""Read-only host admission; backend-specific GPU actuators are separate adapters."""
import ctypes
import math
import os

import psutil


def available_gib():
    available = psutil.virtual_memory().available / 2**30
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in ("total", "available", "commit_total", "commit_available", "virtual_total", "virtual_available", "extended")]]
        value = Memory()
        value.length = ctypes.sizeof(value)
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Memory)]
        dll.GlobalMemoryStatusEx.restype = ctypes.c_int
        if not dll.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise OSError("Cannot observe Windows commit headroom")
        available = min(available, value.commit_available / 2**30)
    if not math.isfinite(available) or available < 0:
        raise OSError("Invalid memory observation")
    return available


class Capacity:
    def __init__(self, minimum):
        self.minimum, self.latest, self.error = minimum, None, None

    def __call__(self):
        if self.minimum == 0:
            return True
        try:
            self.latest = available_gib()
            self.error = None
            return self.latest >= self.minimum
        except (OSError, RuntimeError):
            self.error = "memory_observation_unavailable"
            return False

    def status(self):
        return {"enabled": self.minimum > 0, "minimum_available_gib": self.minimum,
                "last_observed_available_gib": self.latest, "error": self.error,
                "scope": "host RAM/Windows commit observation only; no GPU reservation or actuator"}
