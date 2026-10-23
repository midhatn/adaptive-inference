"""Read-only host admission; backend-specific GPU actuators are separate adapters."""
import ctypes
import asyncio
import math
import os
import time

import psutil

from .resource_policy import HeadroomPolicy


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
    def __init__(self, minimum, *, adaptive=False, recovery_margin_gib=1,
                 recovery_seconds=30, max_sample_age_s=5):
        self.minimum, self.latest, self.error = minimum, None, None
        self.policy = (HeadroomPolicy(minimum, recovery_margin_gib=recovery_margin_gib,
                       recovery_seconds=recovery_seconds, max_sample_age_s=max_sample_age_s)
                       if adaptive else None)
        self.sample_interval_s = min(1.0, max_sample_age_s / 2)

    async def monitor(self):
        """Keep genuine samples advancing during idle time and active work."""
        while True:
            self()
            await asyncio.sleep(self.sample_interval_s)

    def __call__(self):
        if self.minimum == 0:
            return True
        try:
            self.latest = available_gib()
            self.error = None
            if self.policy is not None:
                now = time.monotonic()
                return self.policy.observe({"sampled_at": now, "available_gib": self.latest,
                                            "complete": True}, now)
            return self.latest >= self.minimum
        except (OSError, RuntimeError):
            self.error = "memory_observation_unavailable"
            if self.policy is not None:
                self.policy.observe(None, time.monotonic())
            return False

    def status(self):
        return {"enabled": self.minimum > 0, "minimum_available_gib": self.minimum,
                "last_observed_available_gib": self.latest, "error": self.error,
                "adaptive_headroom": self.policy.status() if self.policy is not None else None,
                "scope": "host RAM/Windows commit observation only; no GPU reservation or actuator"}
