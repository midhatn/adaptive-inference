# SPDX-License-Identifier: Apache-2.0
"""Original local Windows job wrapper; only process lifetime, no resource tuning.

API reference: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
The controller joins before it creates children; its non-inheritable job handle
is retained until process exit. Closing the controller also cleans its children.
"""
import ctypes as C
from ctypes import wintypes as W

_HANDLE = None


def contain_current_process():
    global _HANDLE
    if _HANDLE is not None:
        return
    class Basic(C.Structure):
        _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                    ('flags', W.DWORD), ('min_ws', C.c_size_t), ('max_ws', C.c_size_t),
                    ('active', W.DWORD), ('affinity', C.c_size_t),
                    ('priority', W.DWORD), ('scheduling', W.DWORD)]
    class Io(C.Structure):
        _fields_ = [(name, C.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                    'read_bytes', 'write_bytes', 'other_bytes')]
    class Limits(C.Structure):
        _fields_ = [('basic', Basic), ('io', Io), ('process_mem', C.c_size_t),
                    ('job_mem', C.c_size_t), ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]
    k = C.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
    k.CreateJobObjectW.restype = W.HANDLE
    k.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    k.SetInformationJobObject.restype = W.BOOL
    k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    k.AssignProcessToJobObject.restype = W.BOOL
    k.GetCurrentProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.CreateJobObjectW(None, None)
    if not handle:
        raise C.WinError(C.get_last_error())
    limits = Limits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway.
    if not k.SetInformationJobObject(handle, 9, C.byref(limits), C.sizeof(limits)):
        error = C.get_last_error(); k.CloseHandle(handle); raise C.WinError(error)
    if not k.AssignProcessToJobObject(handle, k.GetCurrentProcess()):
        error = C.get_last_error(); k.CloseHandle(handle); raise C.WinError(error)
    _HANDLE = handle


def active_process_ids():
    """Bounded member query for this helper's own job, never an arbitrary job.

    Microsoft JOBOBJECT_BASIC_PROCESS_ID_LIST / QueryInformationJobObject:
    https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list
    No external implementation was copied.
    """
    if _HANDLE is None:
        raise RuntimeError('The current process has not joined its owned job.')
    k = C.WinDLL('kernel32', use_last_error=True)
    k.QueryInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    k.QueryInformationJobObject.restype = W.BOOL
    capacity = 32
    while capacity <= 4096:
        buffer = C.create_string_buffer(8 + capacity * C.sizeof(C.c_size_t))
        returned = W.DWORD()
        ok = k.QueryInformationJobObject(_HANDLE, 3, buffer, len(buffer), C.byref(returned))
        if not ok:
            error = C.get_last_error()
            if error == 234:  # ERROR_MORE_DATA: retry with a bounded larger list.
                capacity *= 2
                continue
            raise C.WinError(error)
        assigned, count = (W.DWORD * 2).from_buffer(buffer)
        if count > capacity or assigned != count:
            capacity *= 2
            continue
        return {int(pid) for pid in (C.c_size_t * count).from_buffer(buffer, 8)}
    raise RuntimeError('Owned job member count exceeded the bounded query.')

