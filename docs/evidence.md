# Evidence and limits

Three different things are tracked here: the new generic gateway, reconstruction of optional upstream integrations, and historical local model runs. A pass in one does not establish a pass in another. The gateway's own runnable tests and examples are documented by this repository's main README; the older model checks below did not execute that new gateway.

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
