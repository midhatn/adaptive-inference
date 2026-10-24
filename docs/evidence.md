# Evidence and limits

Three different things are tracked here: the new generic gateway, reconstruction of optional upstream integrations, and historical local model runs. A pass in one does not establish a pass in another. The older prototype checks below did not execute the new gateway; the new gateway has its own evidence here.

## Portable gateway release acceptance

At commit `e1d14978328d61267dcbda6fbaa55cdc882f3394`, all **45 gateway/profile/CLI tests plus 4 reconstruction-admission tests** passed in each of six GitHub CI jobs: Windows, Linux and macOS, with Python 3.11 and 3.12. Every job also ran the local HTTP demo, listed the eight engine profiles and built wheel/source distributions. [CI run and artifacts](https://github.com/midhatn/adaptive-inference/actions/runs/40038431587).

A separate fresh, non-editable wheel installation outside the checkout passed the installed `profiles`, `demo` and `doctor` commands on Windows. Its eleven Python module files matched the source, required license notices were included, and the source distribution included the reconstruction helpers. The demo's backend is simulated; the HTTP transport, queue and feedback paths are real. The demo proves equal-cost normal/background ordering and one rejected result followed by a caller-validated correction.

The same gateway source then completed **eight real Strata model requests**: four normal and four background. Full returned text was checked against the exact integer answer (`437` or `493`), all requests stopped naturally, and each class's fourth request used three earlier execution observations. The gateway ended with zero active/pending requests and no uncertain-completion state. The separately operated backend owner confirmed all six retained processes exited with server exit code zero. Exact source/model/settings, per-request timing, answers and counters are in the [sanitized receipt](../provenance/gateway-strata-2026-10-24.json); the [runnable check](../examples/validation/README.md) is included.

This is serial arithmetic and feedback engagement on one Windows/Strata composition. It does not establish comparative speed, prediction accuracy, installed-agent tasks, native priority or tool leases. Gateway scheduling metadata is consumed at the gateway; both classes share its queue. The backend owner remains separately operated predecessor software.

### Retained failure: idle backend reload

The first gateway attempt timed out before any model answer. Strata had unloaded after 60 seconds of idle time. A subsequent status observation reported `reload_footprint_unavailable`: the recorded requirement was 55,901,364,224 bytes free physical RAM, versus 50,850,979,840 available. The nonstreaming reload-admission path can wait without sending HTTP bytes until the gateway's 120-second read timeout. Direct no-model HTTP probes and request framing checks succeeded. This diagnosis combines observed backend state and code inspection; the original waiting thread's stack was not captured.

The accepted run started immediately after a fresh owned backend startup. It qualifies the ready-backend path, **not idle unload/reload recovery**. The gateway and old backend sources were unchanged between attempts. No generation was automatically retried; the operator restarted after inspecting the backend. Native lifecycle/admission coordination remains a tracked development stage in [PLAN.md](../PLAN.md).

## Portable resource/context additions

The post-v0.1.0 source adds the optional sustained-headroom admission policy and explicit context-budget planner. On Windows/Python 3.11, **75 software tests and 4 reconstruction-admission tests passed**, and wheel/source distributions built successfully. The [source-bound acceptance receipt](../provenance/portable-policies-acceptance.json) identifies the tested runtime and test files. This run includes the earlier 45 software tests; the 75 is a total, not 75 additional tests.

New checks exercise fresh/replayed/stale/invalid observations, pressure and recovery, idle sampling, unchanged HTTP request fields, active-owner preservation, cleanup, exact moving-margin compaction targets and CLI exit codes. A fault-injection review found that an already-failed sampler could prevent HTTP-client cleanup; the connection pool now closes in a `finally` block and the regression passes. The software checks use simulated headroom and loopback HTTP fixtures, not new GPU/model or foreground-interference measurements.

Source review also ran the pinned upstream policy and context-budget fixtures for the reused mechanisms. Source extraction setup failures were resolved by restoring exact dependency bytes. These checks do not qualify installed Strata companions, a real compiler/video handoff or the complete [always-on goal](always-on-controller.md).

## Durable task continuation

The durable task store and resumable feedback runner passed **95 software tests in total**, plus the existing four reconstruction checks, on Windows/Python 3.11.9. Wheel and source distributions built successfully. Twenty of the software tests cover task-store ownership, checkpoint transitions, the persistent feedback runner and its process-restart demonstration.

The [sanitized restart receipt](../provenance/restart-survival-2026-10-24.json) binds the tested source hashes to a real process-termination exercise. A new worker retained the original task and rejected feedback, produced the accepted inventory total of 42 on the second attempt, and reopening the completed task invoked no callbacks. A competing live owner was refused. A separate worker died after one external delivery but before its acknowledgment; two fresh resumes stopped for reconciliation and did not repeat the delivery. All seven workers exited. Separate tests recovered an uncommitted SQLite rollback journal without accepting its interrupted changes.

The generation and tool callbacks are deterministic fixtures. This is process/disk-state evidence, not an installed-agent, operating-system reboot, physical power-loss or distributed exactly-once guarantee. The [host integration contract](task-survival.md) explains the remaining startup, identity and reconciliation work.

## Fresh source reconstruction

On 24 October 2026, the included setup scripts fetched the pinned public GitHub commits into new empty locations and applied their checked overlays. All 88 expected Strata changed files and all 7 Hermes changed files matched SHA-256 hashes of the intended canonical Git content. Expected reconstructed trees and patch hashes are in [provenance/reconstruction.json](../provenance/reconstruction.json).

The reconstructed Strata source passed 54 CPU tests covering queue ordering, bounded cost estimation, real service/HTTP integration with fake engines, route delivery, preparation reservations and parking/seed feedback. The reconstructed Hermes source passed its 2 request-intent test methods, which exercise the canonical request-builder matrix. Four reconstruction admission tests passed: existing destination preservation, corrupt-patch refusal, fixed remote identity and path traversal refusal. These checks used Windows/Python 3.11.9 for Strata/setup and Python 3.14.7 for Hermes. They ran no model or new native build.

Reproduce these checks with the commands in each [integration README](../integrations). Test fixture throughput is not an inference benchmark. The hash-locked sources and scripts are public; dependencies and hardware remain separate prerequisites.

## Historical local prototype results

These are operator-observed, bounded results retained from the earlier workstation prototype. Raw runs include private machine state and are not redistributed. Public sanitized source and summaries permit code review and new reproduction, but the following numbers are not independently certified by the existence of this repository.

| Check | Observed result | Boundary |
| --- | --- | --- |
| Native Windows CUDA build at a69684f1 | 183 build steps; thirteen utility/protocol programs passed; all 1,638 retained process identities exited | CUDA 13.4 / MSVC 14.44, architecture 89; live-memory test used protocol-only mode, no model; not HIP/SYCL/Metal qualification |
| Mixed pending-request model check at 9eff | Active owner completed, then normal, then background; canceled pending request produced no generation; all 6 retained handles exited | Three short full-quality arithmetic requests; no throughput or task-quality improvement claim |
| Actual Hermes parent/production-child check | Two real production request-builder paths completed at declared quality; normal/background host intent reached the native service; all 14 retained handles exited | Sequential requests, explicit constructor budget; no leased-tool execution |
| Standalone core at c6b + exact Windows process-rights overlay | 8/8 arithmetic responses correct and naturally completed; eight timing observations; each class's fourth request used three earlier observations; all 8 retained handles exited, server exit0 | Persistent legacy Windows owner; not the new generic gateway; no comparative speed or prediction-accuracy claim |

The standalone check used the native binary SHA-256 `744205e4e024b5cbba19e4b560678ffe21e6899e59050929f7af51557f3c6198`, manifest `19a85d390981380b3ceeb021a885b25f415110174cedfb3dcdc0552cd0ab052b`, and a 23.9375 GiB startup cache selected from 41.956 GiB free effective RAM/commit. Minimum sampled headroom was 11.116 GiB physical RAM, 31.656 GiB commit and 1147.285 MiB VRAM. Sampling is not a continuous residency guarantee. The model/pack contents were metadata-bound, not fully content-hashed.

The quality baseline was IQ3_S/context 65,536, 10,923 total output cap, 8,192 reasoning tokens/high, CPU vision enabled, MTP/projection off. The arithmetic calls did not exercise vision. These figures establish functional execution and feedback engagement for that workload, not general reasoning quality, automatic hardware tuning or optimal scheduling.

## Failures retained and corrected

- Initial persistent startup omitted the server's required owner attestation and failed before model dispatch. The owner was corrected to bind a fresh private key to exact configuration and arguments; an actual mock-server parser/drain regression was added.
- The first timing-feedback attempt remained cold on its second equivalent request: parking injected a new seed between prediction and observation. c6b removes seed only from the copied latency identity, preserving native seeds/replay and all quality/runtime/route distinctions. The unchanged eight-request fixture subsequently passed.
- A fixed 42 GiB owner threshold refused startup at 41.594 GiB free RAM. The owner was corrected to reuse the existing cache policy before eager loading, preserving startup allowance and headroom. It then started with a smaller cache; the emergency guards were unchanged.

The c6b correction collected 225 CPU tests: 224 passed and one POSIX-only test was skipped on Windows; the final legacy owner's 17 CPU tests passed. These historical counts are distinct from the freshly reconstructed 54 + 2 + 4 checks above. Prior unsuccessful receipts were retained locally, not relabeled as successful runs.

## What is not established

No comparative latency/throughput win, broad task-quality improvement, full tool-lease workflow, visual browser interaction, GPU kernel preemption or general autonomous operation is claimed. Exact reconstruction does not make a fresh native binary bit-identical across toolchains. The upstream branches and this standalone gateway are separate deliverables; review the tested revision and composition for each claim.
