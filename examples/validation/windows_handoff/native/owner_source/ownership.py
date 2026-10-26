"""Retained Windows handles; derived from the qualified local lifecycle controller.

Only handles verified to belong to the controller's kill-on-close job can be
terminated. Completed handles are signalled before being closed and counted.
The bounded tail is a diagnostic history, not a complete process-event trace.
"""
import ctypes as C
from ctypes import wintypes as W
from collections import deque
import os
import threading
import time
import psutil


def win_error(operation, pid, access_mask, code=None):
    """Add diagnostic context without changing native error type or access rights.

    https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess
    An access denial is not proof of exit; callers retain existing verification.
    """
    error = C.WinError(C.get_last_error() if code is None else code)
    error.operation, error.pid, error.access_mask = operation, pid, access_mask
    error.add_note(f'Windows operation={operation}, pid={pid}, access_mask={access_mask:#x}')
    return error


class ProcessHandle:
    def __init__(self, pid, expected=None):
        self.pid, self.access_mask = pid, 0x100000|0x1000|1
        self.k = C.WinDLL('kernel32', use_last_error=True)
        for name, args, result in [
            ('OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
            ('GetProcessTimes',[W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)],W.BOOL),
            ('QueryFullProcessImageNameW',[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)],W.BOOL),
            ('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD),
            ('TerminateProcess',[W.HANDLE,W.UINT],W.BOOL),
            ('IsProcessInJob',[W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)],W.BOOL),
            ('CloseHandle',[W.HANDLE],W.BOOL),
        ]:
            fn=getattr(self.k,name); fn.argtypes=args; fn.restype=result
        self.handle=self.k.OpenProcess(self.access_mask,False,pid)
        if not self.handle: raise win_error('OpenProcess',pid,self.access_mask)
        try:
            times=[W.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(self.handle,*[C.byref(x) for x in times]):
                raise win_error('GetProcessTimes',pid,self.access_mask)
            size=W.DWORD(32768); text=C.create_unicode_buffer(size.value)
            if not self.k.QueryFullProcessImageNameW(self.handle,0,text,C.byref(size)):
                error=win_error('QueryFullProcessImageNameW',pid,self.access_mask)
                # Image metadata can disappear before a terminating process is
                # signalled. Preserve the original error, then wait at most one
                # existing lifecycle polling interval on this exact open handle.
                # Only a positive signal proves exit; denial/PID absence do not.
                # https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process
                # https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
                try:
                    error.capture_exit_confirmed=self.exited(wait_ms=50)
                    error.capture_exit_wait_ms=50
                except BaseException as wait_error:
                    error.add_note(f'Same-handle exit check failed: {type(wait_error).__name__}: {wait_error}')
                raise error
            self.record={'pid':pid,'created_filetime':(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime,
                         'exe':text.value}
            if expected and (self.record['created_filetime']!=expected['created_filetime'] or
                             self.record['exe'].casefold()!=expected['exe'].casefold()):
                raise RuntimeError('Process identity changed; no signal sent')
        except BaseException:
            self.close(); raise

    def in_job(self, job):
        belongs=W.BOOL()
        if not self.k.IsProcessInJob(self.handle,job._HANDLE,C.byref(belongs)):
            raise win_error('IsProcessInJob',self.pid,self.access_mask)
        return bool(belongs.value)

    def exited(self, wait_ms=0):
        value=self.k.WaitForSingleObject(self.handle,wait_ms)
        if value == 0xffffffff:
            raise win_error('WaitForSingleObject',self.pid,self.access_mask)
        if value not in (0,258):
            raise RuntimeError(f'Unexpected process wait result {value}, pid={self.pid}, access_mask={self.access_mask:#x}')
        return value==0

    def terminate(self, *, deadline=None):
        if not self.exited() and not self.k.TerminateProcess(self.handle,125):
            # Termination is asynchronous; ERROR_ACCESS_DENIED can race exit.
            # Preserve the API error, then use only this retained handle and
            # at most one existing 50ms polling interval inside cleanup's budget.
            # https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess
            # https://github.com/python/cpython/blob/v3.11.9/Lib/multiprocessing/popen_spawn_win32.py
            error = win_error('TerminateProcess',self.pid,self.access_mask)
            if error.winerror != 5:
                raise error
            wait_ms = (min(50, max(0, int((deadline-time.monotonic())*1000)))
                       if deadline is not None else 0)
            try:
                confirmed = self.exited(wait_ms=wait_ms)
            except BaseException as wait_error:
                error.add_note(f'Same-handle exit check failed: {type(wait_error).__name__}: {wait_error}')
                raise error
            if not confirmed:
                raise error

    def close(self):
        if self.handle: self.k.CloseHandle(self.handle); self.handle=None


class Identities:
    def __init__(self,job):
        self.job=job; self.active={}; self.completed=deque(maxlen=256)
        self.retained=self.confirmed_exits=0
        self.capture_exits=0; self.capture_exit_tail=deque(maxlen=256)
        self.lock=threading.RLock()

    def collect(self):
        with self.lock:
            for key,handle in list(self.active.items()):
                if handle.exited():
                    self.completed.append({**handle.record,'exited':True}); self.confirmed_exits+=1
                    handle.close(); del self.active[key]
            try:
                members = self.job.active_process_ids()
            except OSError as exc:
                exc.operation = 'QueryInformationJobObject'
                exc.add_note('While collecting the owned job process list; requires JOB_OBJECT_QUERY; no process PID selected yet')
                raise
            for pid in members-{os.getpid()}:
                if any(h.record['pid']==pid and not h.exited() for h in self.active.values()): continue
                handle=None
                try:
                    handle=ProcessHandle(pid)
                    if not handle.in_job(self.job): raise RuntimeError('Process outside owned job')
                    key=(pid,handle.record['created_filetime'])
                    self.active[key]=handle; self.retained+=1; handle=None
                except OSError as exc:
                    if (getattr(exc,'operation',None)=='QueryFullProcessImageNameW'
                            and getattr(exc,'capture_exit_confirmed',None) is True):
                        # This handle was signalled before it was closed, but
                        # identity/job capture never completed. Keep it separate
                        # from retained ownership and confirmed owned exits.
                        self.capture_exits+=1
                        self.capture_exit_tail.append({'pid':pid,'operation':exc.operation,
                            'winerror':exc.winerror,'same_handle_exit_confirmed':True,
                            'wait_bound_ms':exc.capture_exit_wait_ms,
                            'ownership_verified':False})
                        continue
                    # Only OpenProcess's known missing-PID error can be a
                    # vanished member; denial or later metadata failures remain
                    # failures without a positive same-handle exit signal,
                    # even if a subsequent PID query reports absence.
                    # Adapted semantics, not copied implementation:
                    # https://github.com/giampaolo/psutil/blob/a1e3067965a075c40b79971cfda51501e80da685/psutil/arch/windows/proc_utils.c#L84-L108
                    if (getattr(exc,'operation',None)!='OpenProcess'
                            or getattr(exc,'winerror',None)!=87 or pid<=0):
                        raise
                    try: still_present=psutil.pid_exists(pid)
                    except BaseException as absence_error:
                        exc.add_note(f'Independent PID absence check failed: {type(absence_error).__name__}: {absence_error}')
                        raise exc
                    if still_present: raise
                finally:
                    if handle: handle.close()
            if len(self.active)>4096: raise RuntimeError('Owned active process bound exceeded')

    def snapshot(self):
        with self.lock:
            return {'retained_total':self.retained,'confirmed_exits':self.confirmed_exits,
                    'active':[dict(h.record) for h in self.active.values() if not h.exited()],
                    'completed_tail':list(self.completed),
                    'exited_during_identity_capture':self.capture_exits,
                    'capture_exit_tail':list(self.capture_exit_tail)}

    def cleanup(self,seconds=12):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            failure=None
            try: self.collect()
            except BaseException as exc: failure=exc
            with self.lock:
                try:
                    empty=self.job.active_process_ids()=={os.getpid()} and not self.active
                except BaseException as exc:
                    if failure is None: failure=exc
                    else: failure.add_note(f'Owned job query also failed: {type(exc).__name__}: {exc}')
                    empty=False
                if empty and failure is None: return True
                # Collection failure must not prevent safe attempts on handles
                # whose identity and job membership were already verified.
                for handle in self.active.values():
                    try: handle.terminate(deadline=deadline)
                    except BaseException as exc:
                        if failure is None: failure=exc
                        else: failure.add_note(f'Retained handle termination also failed: {type(exc).__name__}: {exc}')
            if failure is not None: raise failure
            time.sleep(.05)
        self.collect(); return False

    def close(self):
        with self.lock:
            failure=None
            for key,handle in list(self.active.items()):
                try:
                    handle.close(); del self.active[key]
                except BaseException as exc:
                    if failure is None: failure=exc
                    else: failure.add_note(f'Another retained handle close failed: {type(exc).__name__}: {exc}')
            if failure is not None: raise failure
