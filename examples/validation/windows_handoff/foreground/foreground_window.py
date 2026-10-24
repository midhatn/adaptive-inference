"""Explicitly launched, bounded real Windows GDI animation. No models or stress loop.

Original code under Apache-2.0; see RESEARCH.md for Windows API references.
"""
from __future__ import annotations
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

from activity import WindowsActivityReader
from metrics import summarize


def run(output: Path, seconds: float, fps: int):
    if os.name != "nt":
        raise OSError("Windows desktop required")
    if not 10 <= seconds <= 180 or fps not in (30, 60):
        raise ValueError("duration must be 10..180 s and fps 30 or 60")
    output.mkdir(parents=False, exist_ok=False)
    watchdog_done = threading.Event()
    def deadline_watchdog():
        if not watchdog_done.wait(seconds + 15):
            failure = {"schema": "adaptive.foreground-result.v1",
                       "valid_foreground_run": False, "error": "own_process_deadline",
                       "scope": "Own foreground workload only; no backend action"}
            try:
                (output / "timeout.json").write_text(json.dumps(failure), encoding="utf-8")
            finally:
                os._exit(124)  # only this explicitly launched workload
    threading.Thread(target=deadline_watchdog, name="own-process-deadline", daemon=True).start()
    u, g, k = (C.WinDLL(name, use_last_error=True) for name in ("user32", "gdi32", "kernel32"))
    LRESULT, WPARAM, LPARAM = C.c_ssize_t, C.c_size_t, C.c_ssize_t
    Callback = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)
    class WndClass(C.Structure):
        _fields_ = [("size", W.UINT), ("style", W.UINT), ("proc", Callback),
                    ("class_extra", C.c_int), ("window_extra", C.c_int),
                    ("instance", W.HANDLE), ("icon", W.HANDLE), ("cursor", W.HANDLE),
                    ("brush", W.HANDLE), ("menu", W.LPCWSTR), ("name", W.LPCWSTR),
                    ("small_icon", W.HANDLE)]
    class Paint(C.Structure):
        _fields_ = [("dc", W.HDC), ("erase", W.BOOL), ("rect", W.RECT),
                    ("restore", W.BOOL), ("update", W.BOOL), ("reserved", W.BYTE * 32)]
    u.DefWindowProcW.argtypes = [W.HWND, W.UINT, WPARAM, LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.RegisterClassExW.argtypes = [C.POINTER(WndClass)]
    u.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                 C.c_int, C.c_int, C.c_int, C.c_int,
                                 W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
    u.CreateWindowExW.restype = W.HWND
    u.PostMessageW.argtypes = [W.HWND, W.UINT, WPARAM, LPARAM]
    u.PostMessageW.restype = W.BOOL
    u.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
    u.GetMessageW.restype = C.c_int
    u.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    u.DispatchMessageW.restype = LRESULT
    u.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
    u.ShowWindow.argtypes = [W.HWND, C.c_int]
    u.SetForegroundWindow.argtypes = [W.HWND]
    u.IsWindowVisible.argtypes = [W.HWND]
    u.IsIconic.argtypes = [W.HWND]
    u.DestroyWindow.argtypes = [W.HWND]
    u.InvalidateRect.argtypes = [W.HWND, C.POINTER(W.RECT), W.BOOL]
    u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    u.BeginPaint.argtypes = [W.HWND, C.POINTER(Paint)]
    u.BeginPaint.restype = W.HDC
    u.EndPaint.argtypes = [W.HWND, C.POINTER(Paint)]
    u.FillRect.argtypes = [W.HDC, C.POINTER(W.RECT), W.HBRUSH]
    g.CreateSolidBrush.argtypes = [W.DWORD]
    g.CreateSolidBrush.restype = W.HBRUSH
    g.DeleteObject.argtypes = [W.HANDLE]
    g.SetBkMode.argtypes = [W.HDC, C.c_int]
    g.SetTextColor.argtypes = [W.HDC, W.DWORD]
    g.TextOutW.argtypes = [W.HDC, C.c_int, C.c_int, W.LPCWSTR, C.c_int]
    k.GetModuleHandleW.argtypes = [W.LPCWSTR]
    k.GetModuleHandleW.restype = W.HMODULE
    u.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
    WM_FRAME, WM_CLOSE, WM_DESTROY, WM_PAINT = 0x8001, 0x10, 2, 0xF
    done = threading.Event()
    mutex = threading.Lock()
    state = {"pending": None, "posted": 0, "coalesced": 0, "error": None,
             "requested_close": False, "observations": [], "frames": []}
    reader = WindowsActivityReader()
    brushes = [g.CreateSolidBrush(x) for x in (0x21170D, 0xF1C15B, 0xA7D05B, 0x785BE3, 0xE8E8E8)]
    if not all(brushes):
        raise C.WinError(C.get_last_error())
    start = time.perf_counter()

    @Callback
    def window_proc(hwnd, msg, wp, lp):
        try:
            if msg == WM_FRAME:
                u.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_PAINT:
                paint = Paint()
                dc = u.BeginPaint(hwnd, C.byref(paint))
                try:
                    rect = W.RECT()
                    u.GetClientRect(hwnd, C.byref(rect))
                    u.FillRect(dc, C.byref(rect), brushes[0])
                    elapsed = time.perf_counter() - start
                    width, height = max(1, rect.right), max(1, rect.bottom)
                    # Forty-eight moving cells create actual visible UI work.
                    # No busy waits, video decoder, GPU allocations or stressor.
                    for row in range(6):
                        for column in range(8):
                            x = int((column * 105 + elapsed * (35 + row * 5)) % (width + 50)) - 50
                            y = 90 + row * max(35, (height - 130) // 6)
                            cell = W.RECT(x, y, x + 65, y + 26)
                            u.FillRect(dc, C.byref(cell), brushes[1 + (column + row) % 3])
                    g.SetBkMode(dc, 1)
                    g.SetTextColor(dc, 0xF0F0F0)
                    title = "Adaptive foreground measurement | native animation | Esc closes"
                    g.TextOutW(dc, 20, 18, title, len(title))
                    subtitle = f"{elapsed:.1f} / {seconds:.0f} seconds   |   Target {fps} Hz   |   No model started here"
                    g.TextOutW(dc, 20, 45, subtitle, len(subtitle))
                finally:
                    u.EndPaint(hwnd, C.byref(paint))
                now = time.perf_counter()
                with mutex:
                    pending = state["pending"]
                    if pending is not None:
                        state["frames"].append({"elapsed_s": now - start, "paint_s": now,
                                                "post_to_paint_ms": (now - pending) * 1000})
                        state["pending"] = None
                return 0
            if msg == 0x100 and wp == 27:  # own window Escape only; never logged
                u.DestroyWindow(hwnd)
                return 0
            if msg == WM_CLOSE:
                u.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                done.set()
                u.PostQuitMessage(0)
                return 0
            if msg == 0x14:
                return 1  # erase handled by complete paint
        except BaseException as exc:
            state["error"] = type(exc).__name__ + ": " + str(exc)
            u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wp, lp)

    instance = k.GetModuleHandleW(None)
    class_name = "AdaptiveForegroundMeasure_" + str(os.getpid())
    wc = WndClass(C.sizeof(WndClass), 0, window_proc, 0, 0, instance,
                  None, None, None, None, class_name, None)
    if not u.RegisterClassExW(C.byref(wc)):
        raise C.WinError(C.get_last_error())
    hwnd = u.CreateWindowExW(0, class_name, "Adaptive foreground measurement", 0x00CF0000,
                             100, 100, 940, 640, None, None, instance, None)
    if not hwnd:
        raise C.WinError(C.get_last_error())
    # One normal activation attempt on explicit launch. No topmost/focus loop.
    u.ShowWindow(hwnd, 5)
    activation_requested = bool(u.SetForegroundWindow(hwnd))
    start = time.perf_counter()
    ready = {"schema": "adaptive.foreground-window.v1", "pid": os.getpid(),
             "hwnd": int(hwnd), "started_monotonic_s": time.monotonic(),
             "duration_s": seconds, "fps_target": fps,
             "activation_request_succeeded": activation_requested}
    (output / "ready.json").write_text(json.dumps(ready, indent=2) + "\n", encoding="utf-8")

    def producer():
        next_frame, next_sample = start, start
        while not done.is_set():
            now = time.perf_counter()
            if now - start >= seconds:
                state["requested_close"] = True
                u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return
            if now >= next_sample:
                sample = reader.sample()
                sample["elapsed_s"] = now - start
                sample["target_foreground"] = (sample["foreground"]["valid"]
                                                and sample["foreground"]["pid"] == os.getpid())
                sample["target_visible"] = bool(u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd))
                # Other PID identities remain in RAM only. Output contains own
                # identity or null; no user application inventory is retained.
                if not sample["target_foreground"]:
                    sample["foreground"] = {"valid": False, "pid": None,
                                            "creation_time_100ns": None, "cpu_cores_used": None}
                state["observations"].append(sample)
                next_sample = now + .1
            if now >= next_frame:
                with mutex:
                    if state["pending"] is None:
                        state["pending"] = now
                        if not u.PostMessageW(hwnd, WM_FRAME, 0, 0):
                            state["error"] = "PostMessageW failed"
                            done.set()
                            return
                        state["posted"] += 1
                    else:
                        state["coalesced"] += 1
                next_frame += 1 / fps
                if next_frame < now:
                    next_frame = now + 1 / fps
            # Python 3.11 uses a high-resolution Windows waitable timer here.
            # Event.wait rounded 16.7ms to ~32ms on this host, which would make
            # the workload itself miss its declared 60-Hz timing budget.
            time.sleep(max(.0005, min(next_frame, next_sample) - time.perf_counter()))

    def guarded_producer():
        try:
            producer()
        except BaseException as exc:
            state["error"] = "producer: " + type(exc).__name__ + ": " + str(exc)
            u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    thread = threading.Thread(target=guarded_producer, name="bounded-frame-producer", daemon=True)
    thread.start()
    msg = W.MSG()
    try:
        while True:
            status = u.GetMessageW(C.byref(msg), None, 0, 0)
            if status == 0:
                break
            if status == -1:
                raise C.WinError(C.get_last_error())
            u.TranslateMessage(C.byref(msg))
            u.DispatchMessageW(C.byref(msg))
    finally:
        done.set()
        thread.join(2)
        for brush in brushes:
            g.DeleteObject(brush)
        u.UnregisterClassW(class_name, instance)
    summary = summarize(state["frames"], state["observations"], duration_s=seconds)
    summary.update({"schema": "adaptive.foreground-result.v1", "pid": os.getpid(),
                    "completed_duration": state["requested_close"], "error": state["error"],
                    "producer_exited": not thread.is_alive(), "coalesced_frames": state["coalesced"],
                    "target_fps": fps,
                    "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in (Path(__file__), Path(__file__).with_name("activity.py"),
                                                Path(__file__).with_name("metrics.py"))}})
    summary["valid_foreground_run"] &= bool(summary["completed_duration"] and not summary["error"]
                                             and summary["producer_exited"])
    (output / "samples.json").write_text(json.dumps({"frames": state["frames"],
                                                     "observations": state["observations"]}), encoding="utf-8")
    (output / "result.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    watchdog_done.set()
    print(json.dumps(summary))
    return 0 if summary["valid_foreground_run"] else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seconds", type=float, default=45)
    p.add_argument("--fps", type=int, default=60)
    a = p.parse_args()
    raise SystemExit(run(a.output, a.seconds, a.fps))
