# Foreground measurement and minimal Windows signals

Reviewed 2026-10-24. This document describes preparation and CPU/read-only sampler evidence. Actual foreground, background model, handoff and comparison results are recorded separately in the canonical evidence ledger. All actual model work belongs to the supervisor's IQ3_S lane.

## Signals implemented

`activity.py` uses public Windows APIs, with original project code under Apache-2.0. It reads no titles, executable paths, accessibility text, clipboard, key identities or mouse coordinates; it installs no input hooks and changes no process priority.

| Signal | API and interpretation | Limitation |
| --- | --- | --- |
| Foreground identity | [GetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow) and [GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid) | Activation can temporarily return no window. A window can switch between samples; this is sampled identity, not a continuous assertion. |
| Process work | [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes), opened with query-only access | PID plus creation FILETIME fences PID reuse. Counter differences use current real endpoints over 1.0–1.25s, with no interpolation. Warm-up, switches, read failures or >0.5s gaps produce unknown CPU usage. CPU use is cores used, not percentage of the whole laptop. |
| Session input recency | [GetLastInputInfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo) | Applies to the calling session, not all sessions. Its timestamp is not guaranteed monotonic. The 32-bit tick wrap is handled; implausibly old/future deltas are unknown. Synthetic input can update it; recency does not prove a human was typing. |
| Host CPU | [GetSystemTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes) | Kernel time already includes idle time. First sample is unknown. On systems above 64 processors the API's processor-group limitation applies. |
| RAM/commit headroom | [GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex) | Available memory is a sampled observation and can change immediately. Available page-file/commit allowance is not a resource reservation. |

`WindowsActivityReader().sample()` returns `adaptive.foreground-sample.v1`, monotonic sample time, `{pid, creation_time_100ns, valid, cpu_cores_used, cpu_window_s}`, session idle seconds, host CPU fraction/RAM/commit GiB, and short API error identifiers. The sampler opens and immediately closes a query handle; it has no process-control handle. The raw ephemeral sample contains a PID only. The workload's saved observation masks other applications' identities.

## GPU measurements and existing tools

The native adapter's existing driver headroom reader should remain the GPU source. Do not use [DXGI QueryVideoMemoryInfo](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_4/nf-dxgi1_4-idxgiadapter3-queryvideomemoryinfo) from the controller as if it described the foreground process: it reports the calling process's budget and usage. Windows can page/freeze workloads that overrun their assigned video-memory budget.

[Intel PresentMon](https://github.com/GameTechDev/PresentMon) is an existing MIT-licensed ETW-based presentation measurement tool worth using for a later real game/video workload. It is not required, installed, invoked or copied here. It can distinguish presentation/display behavior that our own GDI submission timestamps cannot. [DWM timing APIs](https://learn.microsoft.com/en-us/windows/win32/dwm/frametiming-ovw) expose compositor timing, but desktop-wide timing is not automatically the displayed-frame timing of our particular window. Neither tool should be replaced with a claimed physical input-to-photon measurement based on ordinary timer callbacks.

The already implemented Peak-EWMA cost feedback and headroom admission in the canonical project remain useful. The new foreground gate needs a separate fast-engage/slow-release hysteresis, without changing generation quality or declaring GPU preemption.

The producer uses [Python 3.11 time.sleep](https://docs.python.org/3/library/time.html#time.sleep), which uses a high-resolution waitable timer on modern Windows. A bounded CPU-only timing check on this host observed 30 waits each: `Event.wait(1/60)` p95 32.04ms versus `time.sleep(1/60)` p95 17.18ms. The former would cause the workload itself to miss its baseline budget. These are timer observations, not foreground or inference evidence; no system-wide timer-resolution setting is changed.

## Suggested controller policy, for supervisor implementation

- Sample every 100–250ms. Treat any valid foreground application as eligible; do not special-case this measurement process in production policy.
- Activity can be recent session input (for example <=60s) or meaningful matched-identity foreground CPU work. GPU activity/video playback may require the independent native/presentation signal; an idle CPU alone cannot classify video as idle.
- Combine active foreground with contention/headroom pressure. Engage after two consecutive qualifying samples and recheck before acting. Recent input is available immediately; CPU-only qualification additionally uses the rolling 1.0–1.25s observed-counter window. A lower recovery threshold and 5–10s continuous quiet avoid oscillation.
- Unknown, failed or stale readings must never mean "free capacity". Hold protective state and stop admitting new background work until known-safe observations resume; bounded timeout/failure recovery belongs to the owner.
- Apply only supported, owned actuators. Preserve existing active-request and resource-lease ownership; stopping or unloading a model must not replay accepted tool effects. Record actual stop, resource release, resume and final task correctness separately.

These are initial engineering thresholds, not a statistical optimality claim. The foreground fixture tests their measurement inputs; it does not certify the shared controller.

## Installed facilities inspected without activation

Python 3.11.9 (Tk 8.6), Chrome 155.0.8059.85, Edge 156.0.4314.42, FFmpeg 8.1.1, .NET SDKs 9.0.319 and 10.0.402 were found. No browser profile or user application was changed. The native workload needs only Python's standard library and Windows user32/gdi32/kernel32.
