"""Bounded independent driver-memory guard; import performs no native calls.

Locally authored from NVIDIA's documented NVML query ABI, also checked against
Strata serve/telemetry.py. No driver settings or CUDA context initialization.
https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html
NVML's Windows accounting is a distinct observation, not a promise against OOM.
"""
import ctypes as c
import ctypes
import math
import hashlib
import json
import os
from pathlib import Path
import threading
import time

MIB = 2**20


class GuardError(RuntimeError):
    pass


def checked_sample(row):
    if (set(row) != {"total_bytes", "free_bytes", "used_bytes"}
            or any(type(v) is not int for v in row.values())
            or not 7 * 2**30 <= row["total_bytes"] <= 9 * 2**30
            or not 0 <= row["free_bytes"] <= row["total_bytes"]
            or not 0 <= row["used_bytes"] <= row["total_bytes"]):
        raise GuardError("NVML memory result is unavailable or inconsistent")
    return row


class NativeReader:
    class Memory(c.Structure):
        _fields_ = [("total", c.c_ulonglong), ("free", c.c_ulonglong), ("used", c.c_ulonglong)]

    def __init__(self, dll_path, dll_sha256):
        if os.name != "nt":
            raise GuardError("The reviewed NVML reader is Windows-only")
        path = Path(dll_path).resolve(strict=True)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.GetSystemDirectoryW.argtypes = [c.c_wchar_p, c.c_uint]
        kernel.GetSystemDirectoryW.restype = c.c_uint
        buffer = c.create_unicode_buffer(32768)
        size = kernel.GetSystemDirectoryW(buffer, len(buffer))
        if not 0 < size < len(buffer) or path != (Path(buffer.value) / "nvml.dll").resolve():
            raise GuardError("Use the pinned Windows System32 NVML library")
        if path.stat().st_size > 32 * MIB or hashlib.sha256(path.read_bytes()).hexdigest() != dll_sha256:
            raise GuardError("NVML library identity changed")
        self.lib = c.CDLL(str(path))
        self.ready = False
        for name, args in {
            "nvmlInit_v2": [], "nvmlShutdown": [],
            "nvmlDeviceGetCount_v2": [c.POINTER(c.c_uint)],
            "nvmlDeviceGetHandleByIndex_v2": [c.c_uint, c.POINTER(c.c_void_p)],
            "nvmlDeviceGetName": [c.c_void_p, c.c_char_p, c.c_uint],
            "nvmlDeviceGetMemoryInfo": [c.c_void_p, c.POINTER(self.Memory)],
        }.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, c.c_int
        self._call("nvmlInit_v2")
        self.ready = True
        try:
            count = c.c_uint()
            self._call("nvmlDeviceGetCount_v2", c.byref(count))
            if count.value != 1:
                raise GuardError("The qualified single-NVIDIA-device mapping changed")
            self.handle = c.c_void_p()
            self._call("nvmlDeviceGetHandleByIndex_v2", 0, c.byref(self.handle))
            name = c.create_string_buffer(96)
            self._call("nvmlDeviceGetName", self.handle, name, len(name))
            self.name = name.value.decode("ascii", errors="strict")
            if self.name != "NVIDIA GeForce RTX 4070 Laptop GPU":
                raise GuardError("NVML selected a different device")
            self.read()
        except BaseException:
            self.close()
            raise

    def _call(self, name, *args):
        result = getattr(self.lib, name)(*args)
        if result != 0:
            raise GuardError(f"NVML query failed: {name} code={result}")

    def read(self):
        value = self.Memory()
        self._call("nvmlDeviceGetMemoryInfo", self.handle, c.byref(value))
        return checked_sample({"total_bytes": value.total, "free_bytes": value.free, "used_bytes": value.used})

    def close(self):
        if self.ready:
            self._call("nvmlShutdown")
            self.ready = False


def host_memory():
    class Global(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                    *[(name, ctypes.c_ulonglong) for name in ('total_phys', 'avail_phys',
                      'total_commit', 'avail_commit', 'total_virtual', 'avail_virtual', 'extended')]]
    value = Global()
    value.length = ctypes.sizeof(value)
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Global)]
    if not dll.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'sampled_at': time.time(), 'total_ram_gib': value.total_phys / 2**30,
            'available_ram_gib': value.avail_phys / 2**30,
            'available_commit_gib': value.avail_commit / 2**30}


def checked_host_sample(row):
    required = {'sampled_at', 'total_ram_gib', 'available_ram_gib', 'available_commit_gib'}
    if (type(row) is not dict or set(row) != required
            or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in required)
            or any(row[k] < 0 for k in ('available_ram_gib', 'available_commit_gib'))
            or not 0 < row['total_ram_gib'] or row['available_ram_gib'] > row['total_ram_gib']
            or not 0 <= time.time() - row['sampled_at'] <= 2):
        raise GuardError('Independent Windows physical/commit capacity is unknown or stale')
    return row

