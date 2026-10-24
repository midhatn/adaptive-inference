# Bounded native foreground responsiveness workload

This folder provides a **real visible Windows application** for measuring automatic resource handoff. Preparation and CPU tests do not count as a foreground run. The supervising operator owns activation, background conditions, model ownership and the final comparison. See the canonical evidence ledger for separately recorded actual runs.

The 940x640 native GDI window animates 48 moving cells at a requested 60 Hz. A bounded producer posts at most one outstanding frame message. It measures host-posted-message-to-paint-submission latency and actual paint-submission intervals. It samples actual Windows foreground ownership/visibility every 100ms. It never starts models, requests an API, fills GPU memory or busy-spins. These are UI-thread/paint metrics, **not displayed FPS or physical input-to-photon latency**.

## Run contract

After the supervisor releases the test lane, run from this folder with a new output directory whose parent exists:

```powershell
python foreground_window.py --output baseline-01 --seconds 45 --fps 60
```

The workload makes one ordinary activation request when explicitly launched. It does not use topmost mode, attach input threads, send synthetic keystrokes, or repeatedly steal focus. If Windows does not activate it, the supervisor can explicitly activate that window through the normal UI. Keep it visible and foreground for the measurement. Escape or its close button ends it; that early result will not qualify the full-duration test. A supervisor may read `ready.json` to identify only this process/window. The window closes after the selected duration, with an own-process hard deadline 15s later if its message loop cannot drain. Model/backend teardown remains the separate owner’s responsibility.

Outputs: `ready.json`, `samples.json`, `result.json`; a deadline failure additionally writes `timeout.json` and exits 124. Exit 0 means a complete, sufficiently observed foreground run, **not a passing responsiveness or handoff comparison**. An invalid/early/not-foreground run exits 2. A UI setup failure has a nonzero exception exit. Source hashes bind the exact workload and measurement rules.

## Declared comparison, before measurement

Use identical duration, target rate and exact source in three independent fresh runs:

1. Baseline: the supervised IQ3_S background generation is absent. Record other system activity and owner state externally.
2. Uncontrolled: the exact declared IQ3_S agent task/background condition runs without the new foreground policy. Preserve the same quality limits and model. Root owns stopping and cleanup.
3. Controlled: the same task/quality/backend composition with foreground handoff enabled. Record detection, safe-boundary yielding/release, quiet-state recovery, final answer/tool correctness and no-replay evidence in separate controller receipts.

Discard the first five seconds. A run requires >=95% foreground-and-visible samples, at least 15 measured paints/second, at least five observations/second, and observations/paints reaching within 300ms of the full duration. Do not infer adequate sampling from a handful of good frames after a long freeze.

The baseline is valid for this first 60 Hz gate if p95 paint-submission interval <=25ms. Controlled acceptance requires p95 <=max(25ms, 1.25x baseline p95) and intervals over 50ms <=1%. The uncontrolled condition must actually exceed a declared bound before claiming degradation; controlled improvement additionally requires lower p95. If it does not, report functional handoff/non-regression only. One triplet is a bounded observation, not a performance generalization. A repeat baseline is recommended before any comparative speed claim to detect thermal/background drift.

```powershell
python compare_runs.py --baseline baseline-01/result.json --uncontrolled uncontrolled-01/result.json --controlled controlled-01/result.json --output comparison-01.json
```

The comparator validates workload hashes/settings and refuses output overwrite. It cannot attest which model/background condition was running; supervisor evidence must establish that.

## Foreground CPU observation window

Windows process CPU accounting was observed to arrive in roughly 15.6ms increments. Dividing one increment by a 100–200ms poll can make a mostly quiet process look intermittently busy. The sampler therefore divides the difference of two real process counters by their actual elapsed time over a rolling 1.0–1.25s window. The newest endpoint is always the current observation; the older endpoint is the latest observed counter at or before one second ago. There is no interpolation, stale-result relabeling, or invented idle value. The sample reports `foreground.cpu_window_s` alongside `cpu_cores_used`; one core fully occupied is 1.0, regardless of total logical processor count.

The history is bounded to 128 samples. A foreground PID or creation-time change, a failed read, a counter or clock regression, or a sampling gap over 0.5s resets it. Before one full second is observed, or when no observed pair fits the 1.25s limit, CPU is unknown. Recent session input still closes foreground admission immediately while this window warms. CPU-only detection has roughly one second of averaging delay plus the polling interval, with an accepted window span capped at 1.25s; it does not promise sub-second detection. The controller's 0.15-core engage threshold, 0.05-core recovery threshold, input hold and recovery dwell are unchanged.

The regression tests feed the actual policy both a quiet quantized-counter pattern whose short intervals cross 0.15 cores and sustained work above that threshold. They establish recovery for the quiet averaged pattern and protection for sustained work; these are deterministic fixture results, not live responsiveness measurements. Changing the sampler hash requires a fresh matching baseline/uncontrolled/controlled comparison. Earlier run receipts are retained with their original source identities.
## Preparation checks and privacy

```powershell
python -m unittest -v test_foreground
python -m py_compile foreground_window.py activity.py metrics.py compare_runs.py
```

Tests cover wraparound/nonmonotonic input timestamps, PID reuse, bounded rolling CPU observations and quantized-counter recovery, kernel/idle accounting, sample sufficiency, early close/background refusal and no invented improvement. A read-only native sampler smoke is permitted independently; it does not launch a window. Raw OS signals disclose no window title, path, screen content, key or mouse coordinates. Other foreground process identities are masked in workload output. See [RESEARCH.md](RESEARCH.md) for public API sources, definitions and limitations.
