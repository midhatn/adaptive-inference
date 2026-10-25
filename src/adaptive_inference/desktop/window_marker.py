# SPDX-License-Identifier: Apache-2.0
"""One owned Tk root's native property lifetime; DLL calls are lazy/injected."""
import ctypes as C
from ctypes import wintypes as W
import os
import threading

WM_NCDESTROY = 0x0082
GA_ROOT = 2
POINTER_LIMIT = 1 << (C.sizeof(C.c_void_p) * 8)


class MarkerError(RuntimeError):
    pass


class WindowAPI:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows window adapter required')
        self.u = C.WinDLL('user32', use_last_error=True)
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.c = C.WinDLL('comctl32', use_last_error=True)
        self.callback_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT,
                                         C.c_size_t, C.c_ssize_t, C.c_size_t, C.c_size_t)
        declarations = (
            (self.u, 'GetAncestor', [W.HWND, W.UINT], W.HWND),
            (self.u, 'GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            (self.k, 'GetCurrentProcessId', [], W.DWORD),
            (self.k, 'GetCurrentThreadId', [], W.DWORD),
            (self.u, 'GetPropW', [W.HWND, W.LPCWSTR], W.HANDLE),
            (self.u, 'SetPropW', [W.HWND, W.LPCWSTR, W.HANDLE], W.BOOL),
            (self.u, 'RemovePropW', [W.HWND, W.LPCWSTR], W.HANDLE),
            (self.c, 'SetWindowSubclass', [W.HWND, self.callback_type, C.c_size_t, C.c_size_t], W.BOOL),
            (self.c, 'RemoveWindowSubclass', [W.HWND, self.callback_type, C.c_size_t], W.BOOL),
            (self.c, 'DefSubclassProc', [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t], C.c_ssize_t),
        )
        for dll, name, args, result in declarations:
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result

    @staticmethod
    def error(operation):
        error = C.WinError(C.get_last_error())
        error.operation = operation
        return error

    def root(self, hwnd):
        return self.u.GetAncestor(hwnd, GA_ROOT) or 0

    def current_identity(self):
        return self.k.GetCurrentThreadId(), self.k.GetCurrentProcessId()

    def window_identity(self, hwnd):
        pid = W.DWORD()
        tid = self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return tid, pid.value

    def marker(self, hwnd, name):
        return self.u.GetPropW(hwnd, name) or 0

    def set_marker(self, hwnd, name, value):
        if not self.u.SetPropW(hwnd, name, value):
            raise self.error('SetPropW')

    def remove_marker(self, hwnd, name):
        return self.u.RemovePropW(hwnd, name) or 0

    def callback(self, function):
        return self.callback_type(function)

    def subclass(self, hwnd, callback, identity):
        if not self.c.SetWindowSubclass(hwnd, callback, identity, 0):
            raise self.error('SetWindowSubclass')

    def unsubclass(self, hwnd, callback, identity):
        if not self.c.RemoveWindowSubclass(hwnd, callback, identity):
            raise self.error('RemoveWindowSubclass')

    def forward(self, hwnd, message, wparam, lparam):
        return self.c.DefSubclassProc(hwnd, message, wparam, lparam)


class RootMarker:
    def __init__(self, root, name, value, *, api):
        if (type(name) is not str or not 16 <= len(name) <= 128
                or any(not 33 <= ord(char) <= 126 for char in name)
                or type(value) is not int or not 0 < value < POINTER_LIMIT):
            raise ValueError('Fresh bounded property identity required')
        self.root, self.name, self.value, self.api = root, name, value, api
        self._thread = threading.current_thread()
        self.hwnd = None
        self.installed = self.removed = self.destroyed = self.subclass_installed = False
        self._attempted = False
        self._callback = None
        self.faults = set()

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise MarkerError('Window marker belongs to its creator thread')

    def install(self):
        self._owner()
        if self.installed:
            if self.destroyed or self.removed or self.api.marker(self.hwnd, self.name) != self.value:
                raise MarkerError('Window marker can never be recreated')
            return True
        if self._attempted:
            raise MarkerError('An attempted marker cannot be installed again')
        self._attempted = True
        self.root.update_idletasks()
        hwnd = self.api.root(self.root.winfo_id())
        if (type(hwnd) is not int or not 0 < hwnd < POINTER_LIMIT
                or self.api.root(hwnd) != hwnd
                or self.api.window_identity(hwnd) != self.api.current_identity()):
            raise MarkerError('Tk root is not owned by this process and thread')
        if self.api.marker(hwnd, self.name) != 0:
            raise MarkerError('Fresh property already exists; no adoption')
        self.hwnd = hwnd
        self._callback = self.api.callback(self._dispatch)
        self.api.subclass(hwnd, self._callback, self.value)
        self.subclass_installed = True
        try:
            self.api.set_marker(hwnd, self.name, self.value)
            # Set succeeded: retain the removal obligation even if readback fails.
            self.installed = True
            if self.api.marker(hwnd, self.name) != self.value:
                raise MarkerError('Installed marker readback changed')
        except BaseException:
            self.faults.add('marker_install_failed')
            # Retain subclass/callback to cover destruction; no lost cleanup
            # obligation and no attempt to delete a replacement property's value.
            raise
        return True

    def remove(self):
        self._owner()
        if self.removed:
            return True
        if not self.installed:
            return not self._attempted or not self.subclass_installed
        if self.api.marker(self.hwnd, self.name) != self.value:
            self.faults.add('marker_missing_or_replaced')
            return False
        if (self.api.remove_marker(self.hwnd, self.name) != self.value
                or self.api.marker(self.hwnd, self.name) != 0):
            self.faults.add('marker_removal_unconfirmed')
            return False
        self.removed = True
        return True

    def _dispatch(self, hwnd, message, wparam, lparam, identity, reference):
        # Exceptions must never unwind through a ctypes native callback.
        if message == WM_NCDESTROY and hwnd == self.hwnd:
            try:
                self._owner()
                if not self.remove():
                    self.faults.add('native_marker_cleanup_unconfirmed')
            except BaseException:
                self.faults.add('native_marker_cleanup_failed')
            try:
                self._owner()
                if self.subclass_installed:
                    self.api.unsubclass(hwnd, self._callback, self.value)
                    self.subclass_installed = False
            except BaseException:
                self.faults.add('native_subclass_cleanup_failed')
            self.destroyed = True
        try:
            return self.api.forward(hwnd, message, wparam, lparam)
        except BaseException:
            self.faults.add('native_forward_failed')
            return 0

    def diagnostics(self):
        self._owner()
        return {'marker_installed': self.installed, 'marker_removed': self.removed,
                'native_destroyed': self.destroyed, 'subclass_installed': self.subclass_installed,
                'faults': sorted(self.faults)}
