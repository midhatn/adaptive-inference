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


class ProcessHandle:
    def __init__(self, pid, expected=None):
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
        self.handle=self.k.OpenProcess(0x100000|0x1000|1,False,pid)
        if not self.handle: raise C.WinError(C.get_last_error())
        try:
            times=[W.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(self.handle,*[C.byref(x) for x in times]):
                raise C.WinError(C.get_last_error())
            size=W.DWORD(32768); text=C.create_unicode_buffer(size.value)
            if not self.k.QueryFullProcessImageNameW(self.handle,0,text,C.byref(size)):
                raise C.WinError(C.get_last_error())
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
            raise C.WinError(C.get_last_error())
        return bool(belongs.value)

    def exited(self):
        value=self.k.WaitForSingleObject(self.handle,0)
        if value not in (0,258): raise RuntimeError('Original process handle wait failed')
        return value==0

    def terminate(self):
        if not self.exited() and not self.k.TerminateProcess(self.handle,125):
            if not self.exited(): raise C.WinError(C.get_last_error())

    def close(self):
        if self.handle: self.k.CloseHandle(self.handle); self.handle=None


class Identities:
    def __init__(self,job):
        self.job=job; self.active={}; self.completed=deque(maxlen=256)
        self.retained=self.confirmed_exits=0
        self.lock=threading.RLock()

    def collect(self):
        with self.lock:
            for key,handle in list(self.active.items()):
                if handle.exited():
                    self.completed.append({**handle.record,'exited':True}); self.confirmed_exits+=1
                    handle.close(); del self.active[key]
            for pid in self.job.active_process_ids()-{os.getpid()}:
                if any(h.record['pid']==pid and not h.exited() for h in self.active.values()): continue
                handle=None
                try:
                    handle=ProcessHandle(pid)
                    if not handle.in_job(self.job): raise RuntimeError('Process outside owned job')
                    key=(pid,handle.record['created_filetime'])
                    self.active[key]=handle; self.retained+=1; handle=None
                except OSError:
                    # The member can exit between the job query and OpenProcess.
                    if psutil.pid_exists(pid): raise
                finally:
                    if handle: handle.close()
            if len(self.active)>4096: raise RuntimeError('Owned active process bound exceeded')

    def snapshot(self):
        with self.lock:
            return {'retained_total':self.retained,'confirmed_exits':self.confirmed_exits,
                    'active':[dict(h.record) for h in self.active.values() if not h.exited()],
                    'completed_tail':list(self.completed)}

    def cleanup(self,seconds=12):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            self.collect()
            with self.lock:
                if self.job.active_process_ids()=={os.getpid()} and not self.active: return True
                for handle in self.active.values(): handle.terminate()
            time.sleep(.05)
        self.collect(); return False

    def close(self):
        with self.lock:
            for handle in self.active.values(): handle.close()
            self.active.clear()
