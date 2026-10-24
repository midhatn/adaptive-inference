# Research, reuse and attribution

Adaptive Inference combines a portable HTTP gateway, bounded pending-request scheduling and a small online execution-cost model. Research informs these choices; citing a system does not mean that its implementation or published performance has been reproduced here. Optional source overlays preserve the earlier Strata/Hermes integration. Its accepted Windows-owner/model results are historical evidence for that predecessor, whose owner is not shipped in these overlays. The gateway's own checks are recorded separately in the [evidence ledger](evidence.md). Comparative performance and richer task-level adaptation remain separate work.

Links and project identities below were checked against their primary repositories, official documentation or paper pages on 24 October 2026. Pinned revisions denote the source actually inspected. The machine-readable bibliography is [REFERENCES.bib](../REFERENCES.bib); component PRs and historical feedback are indexed in [upstream-prs.md](upstream-prs.md). The [preserved source index](../third_party/reference-sources/README.md) contains exact licensed originals for the mechanisms actually used here, with offline hash verification. The implementation and design explanations in this checkout remain usable when an external link is unavailable.

## Direct implementation lineage

| Source | Use here | Attribution and boundary |
| --- | --- | --- |
| [Strata](https://github.com/Niko1221/Strata), including [medking82's live-cache work #726](https://github.com/Niko1221/Strata/pull/726) | Native inference, memory acknowledgements, memory policy, FIFO/lifecycle and optional resource leases underlie the predecessor. Selected native/runtime changes are preserved as optional source overlays; the generic gateway does not acquire those controls by forwarding HTTP. | Strata and its contributors retain authorship and licenses. The downstream scheduling and historical standalone-controller composition is distinct from the upstream PR head. [#1093](https://github.com/Niko1221/Strata/pull/1093) informed honest unloaded/busy reporting. |
| [Twitter Finagle Peak EWMA](https://github.com/twitter/finagle/blob/9cc08d15216497bb03a1cafda96b7266cfbbcff1/finagle-core/src/main/scala/com/twitter/finagle/loadbalancer/PeakEwma.scala) | The spike-sensitive update equation is adapted into the execution-cost model: a new peak takes effect immediately, while lower observations recover gradually. | Copyright 2017 Twitter Inc.; Apache-2.0. Preserve the distributed Finagle NOTICE and LICENSE with any copy of the derived module. Pin: `9cc08d15216497bb03a1cafda96b7266cfbbcff1`; source blob `2179c6b1db996984020ca4347f292e5aecb1e372`. |
| [NVIDIA Dynamo queue source](https://github.com/ai-dynamo/dynamo/blob/868de572ad9e10e2effb16bb0cff57f3973ca1e8/lib/kv-router/src/scheduling/policy_queue.rs) | Informed independently implemented arrival-time offsets, a stable tie-break, and a rank frozen at enqueue. | Inspected Apache-2.0 source at `868de572ad9e10e2effb16bb0cff57f3973ca1e8`, blob `93ab24f7ca13a9667f9a332b98ade59e9d9f8e32`. This is not a port of Dynamo's router, DRR policy or backend preemption. |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | Optional host-origin request tagging and bounded parent/child integration use Hermes' existing provider and delegation paths. | Hermes and its contributors retain authorship and licenses. Public metadata allows background self-demotion; it does not authorize arbitrary priority escalation or tool access. |
| [medking82's Strata #726](https://github.com/Niko1221/Strata/pull/726) | Fresh, advancing observation and recovery rules adapted into the portable optional headroom gate. | MIT; `15a59d4785f492b4df3fb78862373a5383696450`. The new gate controls admission only; it does not port native cache resizing or process-name detection. |
| [medking82's Strata #3684](https://github.com/Niko1221/Strata/pull/3684) | Small-context safety margin adapted into an explicit context planner. | MIT; `f273ef65e8f4548125f3e72833cd61019b82080f`. Our feasibility/compaction decisions preserve the caller's output ceiling instead of importing the original clamp. |
| [medking82's Strata #1136](https://github.com/Niko1221/Strata/pull/1136) | Per-operation SQLite transactions and optimistic revision checks adapted into durable task checkpoints. | MIT; `64d119cd602ddc439c311dedf61fda460f2785ef`, `serve/chat_archive.py`. OS runner ownership, operation receipts and feedback continuation are new; saved conversation history alone is not execution recovery. |

The already-merged [learned-profile fix by medking82](https://github.com/midhatn/Strata/pull/1) is retained in the pinned Strata overlay. [Policy setup](portable-policies.md) explains the new opt-in behavior. Exact source pins and tests distinguish adapted mechanisms from code retained only in that overlay.

The Finagle adaptation adds bounded context groups, empirical p90, three-observation minimum, expiry, failure invalidation and cold fallback. Predictions are read without decaying long-running work toward zero merely because it is idle. Endpoint selection, network retries and Finagle's pending-request multiplier were not copied. RNG seed is excluded only from the copied latency-population identity; actual sampling and replay retain their exact seeds.

The pending queue freezes a bounded class/cost offset at arrival. Unknown cost receives the conservative maximum offset, so cold work does not receive a free short-job bonus. Ownership and feasibility remain authoritative. Reordering waiting work does not preempt an active generation.

## Primary research considered

| Reference | Useful idea | Decision and scope |
| --- | --- | --- |
| [MARS: Efficient, Adaptive Co-Scheduling for Heterogeneous Agentic Systems](https://arxiv.org/abs/2604.26963v2) | Joint GPU/KV and CPU/tool observations; separate admission and execution; hysteresis. | Architectural reference for inference/tool loops. The [preview](https://github.com/Afterglow231/MARS_preview/tree/7e649f33f40ceb5d977ea4b7c07538effdad88d7) uses modified vLLM and targets datacenter GPUs. It is not this Windows implementation. |
| [JITServe: SLO-aware LLM Serving with Imprecise Request Information](https://www.usenix.org/conference/nsdi26/presentation/zhang-wei), [paper v2](https://arxiv.org/html/2504.20068v2) | Streaming user latency, complete-response deadlines and compound-task goals differ; uncertain cost should be treated conservatively. | Preserve request/quality context before learning. Our peak/p90 heuristic is not JITServe's quantile-forest predictor or GMAX algorithm. Inspected [artifact pin](https://github.com/UIUC-MLSys/JITServe/tree/84584a119b892cf90c65e2b3f5bac67250d39d27); its trained assets and transport were not imported. |
| [Agentix](https://www.usenix.org/conference/nsdi26/presentation/luo) | Programs and attained service across multiple calls are better units than isolated requests. | Motivates later task-level state. Normal/background tags alone do not implement program scheduling. |
| [FastServe](https://www.usenix.org/conference/nsdi26/presentation/wu-bingyang), [implementation](https://github.com/LLMServe/FastServe) | Iteration-level preemption, feedback queues and proactive KV movement. | Requires native resumability and memory ownership. No FastServe code or token-preemption claim. |
| [PolicyCache](https://www.usenix.org/conference/nsdi26/presentation/tian), [paper](https://www.usenix.org/system/files/nsdi26-tian.pdf) | Local online learning and switching can reduce dependence on cross-environment generalization. | Supports expiring context-local observations. Its congestion-control tree and exploration policy are not copied. |
| [Deep Reinforcement Learning for HPC Job Scheduling: A Statistical Evaluation](https://arxiv.org/abs/2610.21008) | Compare learned policies with feasible masked-random controls and repeated seeds, not just weak heuristics. | Evaluation guidance; no DRL scheduler enabled. |
| [ATSInfer](https://arxiv.org/abs/2607.10183v2) | Measured tensor-granularity hybrid CPU/GPU placement and load-aware transfer. | Earlier routing research context. No claim that this pending-request scheduler implements its tensor allocator. |
| [ConServe](https://arxiv.org/abs/2410.01228v2) | Online/offline co-serving with fine-grained yielding and incremental KV management. | Background/foreground distinction is relevant; its preemption and KV mechanisms are not imported. |
| [Agentic CPU-GPU Scheduling for Heterogeneous AI Workloads](https://arxiv.org/abs/2607.22242) | A runtime monitor can expose measured contention and feasible device choices to a slower adviser. | Research lead for later advisory selection. The model must never grant ownership or override capacity. |

These papers' hardware, workloads, objective functions and reported speedups differ from this project's. Their results are not our benchmark results.

## Existing systems considered before adding mechanisms

- [Dynamo priority scheduling](https://docs.nvidia.com/dynamo/agents/priority-scheduling) separates router and backend priority. [Versioned DRR documentation](https://docs.dynamo.nvidia.com/dynamo/v1.3.0/components/router/deficit-round-robin-queue-scheduling) provides a future weighted-service comparison; the [development admission architecture](https://docs.dynamo.nvidia.com/dynamo/dev/knowledge-base/concepts/fault-tolerance/admission-control-architecture) separates capacity, queueing and routing. DRR is not silently substituted for the tested bounded-offset policy.
- [Envoy adaptive concurrency](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/adaptive_concurrency_filter) and [Netflix concurrency-limits](https://github.com/Netflix/concurrency-limits) inform fast backoff and slower recovery. Native single-owner capacity is still a hard constraint; network retry semantics are inappropriate for effects such as tool execution.
- [StarPU](https://starpu.gitlabpages.inria.fr/features.html) demonstrates measured heterogeneous task costs. [Apache TVM MetaSchedule](https://tvm.apache.org/docs/deep_dive/tensor_ir/tutorials/meta_schedule.html) separates bounded tuning search from reuse of measured records. Neither runtime is installed by this project.
- [MABWiser](https://github.com/fidelity/mabwiser), with its [LinUCB/LinTS API](https://fidelity.github.io/mabwiser/api.html), was considered for shadow/offline selection. It is not a dependency or enabled policy. Any future exploration must be restricted to already feasible, quality-preserving actions.

## Research-first response to startup failure

A fresh Windows qualification on 24 October 2026 failed before generation with
an access-denied error during native-owner startup. A later cleanup error hid
the operation that originally failed. A bounded diagnostic using the unchanged
process tracker and 15 short-lived helper processes did not reproduce it. This
is a diagnostic gap, not evidence that permissions should be relaxed or that
the failed process can be assumed to have exited.

The next correction uses established API and runtime behavior rather than a
new process-management mechanism. Microsoft's [GetLastError contract](https://learn.microsoft.com/en-us/windows/win32/api/errhandlingapi/nf-errhandlingapi-getlasterror)
requires capturing the error immediately. Python's [exception notes](https://docs.python.org/3.11/library/exceptions.html#BaseException.add_note)
allow operation and process context to accompany the original traceback.
Microsoft's [process-handle contract](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)
and Python's [Popen lifecycle](https://docs.python.org/3.11/library/subprocess.html#subprocess.Popen.poll)
support retaining the launched process object rather than rediscovering an
owner by PID alone. These are API/design references; no external implementation
is copied by the diagnostic change.

The process tracker also adapts psutil's [specific missing-process classification](https://github.com/giampaolo/psutil/blob/a1e3067965a075c40b79971cfda51501e80da685/psutil/arch/windows/proc_utils.c#L84-L108):
only an `OpenProcess` invalid-parameter error is a missing-PID candidate. The
local implementation additionally requires independent absence. Access denial
and failures of metadata or job-membership checks remain errors. The exact
BSD-3-Clause source and license are retained in the [source archive](../third_party/reference-sources/README.md).

The implementation must retain primary and cleanup errors separately, keep
unknown cleanup unsuccessful, and bind a failed launch to the attempt identity
created before readiness. Neither access denial nor an empty listener is a
normal release receipt. The diagnostic successor subsequently identified
`QueryFullProcessImageNameW` as the denied operation, after opening the handle
and reading creation time.

A bounded owned-child experiment then reproduced the exact error-5 window:
image metadata was unavailable while the retained process handle was still
nonsignaled, followed about 1.3-1.6 milliseconds later by error 31 and a signaled
handle. Microsoft's [process termination contract](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process)
and [wait outcomes](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject),
plus CPython's [retained-handle error confirmation](https://github.com/python/cpython/blob/v3.11.9/Lib/multiprocessing/popen_spawn_win32.py),
inform the correction. These are API/design references; their implementation is
not copied. The exact historical child's exit state was not recorded at the
failure, so the experiment establishes the mechanism rather than retrospective
proof of that child's lifecycle.

On failed image capture, preserve the original error and wait at most 50 ms on
that exact open handle. Only positive signaling permits skipping the already
exited capture. A timeout or failed wait retains the failure. Record capture
exit observations separately from verified job membership and owned-process
exit totals; they grant no release authority. The 50-ms bound matches the
existing lifecycle polling interval and is not a measured worst-case guarantee.
Four real child checks exercised the new handling, including two naturally
observed error-5 transitions; 64 lifecycle tests and independent review passed.
The full model/agent workflow still requires its own acceptance.

## Bounded correction after an independently rejected answer

A full handoff attempt produced correct item amounts with an incorrect grand
total. It remains failed. The successor qualification reuses this repository's
existing `run_with_feedback` implementation for at most three attempts on each
of two arithmetic tasks. It keeps the original prompt and rejected outputs,
gives actionable validator feedback without the expected answers, and retains
every request and response. Model quality and the exact acceptance result do
not change. Transport failures or unknown completion outcomes stop rather than
becoming blind retries.

[Self-Refine](https://arxiv.org/abs/2303.17651v2) provides the feedback/revision
design context; [intrinsic self-correction limitations](https://arxiv.org/abs/2310.01798v2)
support keeping acceptance outside model confidence. The more recent
[AMTFV](https://arxiv.org/abs/2607.29549v1) separates mathematical verification
from execution. Its tool-agent machinery is unnecessary for this fixed integer
task, whose exact expected result already exists. [LLM-as-a-Verifier](https://arxiv.org/abs/2607.05391v2)
was also inspected; probabilistic scoring is not adopted where an exact check
is available. These are design references, not copied implementations or
evidence of improvement on the local model. The reused executable loop is the
existing project module, now included in the qualification's runtime hashes.

Logical task duration includes rejected attempts and waiting. Individual HTTP
completion times must be retained separately when checking resource release;
a release can correctly follow a rejected request before a later correction.
CPU fixtures verify this correction contract, while a real run must separately
establish task completion. A run requiring no correction cannot demonstrate
successful real-model self-correction merely because the loop was available.

## Optional typed-decision advisers

[TypeSafe Jev](https://docs.typesafe.ai/introduction) is a hosted structured-decision service. Its [independent evaluation](https://arxiv.org/abs/2609.37647) is useful background on task-dependent calibration, not evidence for hardware-resource decisions. No Jev service call was used in this project's evaluation.

[Receptron's Laya runtime](https://github.com/receptron/laya/tree/60d5ee6ef8e731646e8ca9ac0139d25fcf4fa295) is a Node/TypeScript ONNX wrapper for Convai Innovations' decision model. The wrapper is MIT; model weights are separately Apache-2.0. The evaluated [English export](https://huggingface.co/receptron/laya-onnx/tree/d42786bdff8a7550316339c5fbf8f46caa83ea1b) is pinned to `d42786bdff8a7550316339c5fbf8f46caa83ea1b`. The [typed-decisions checkpoint](https://huggingface.co/convaiinnovations/laya-typed-decisions) is a distinct trained model, not the evaluated bundle.

A bounded two-thread CPU experiment produced 22/32 raw fixture-policy matches, with only 6/16 paired decisions agreeing across option order. The guard accepted six correct choices; deterministic fallback made the full guarded set 48/48, exactly matching the already-correct arithmetic baseline. Warm nearest-rank p50/p95 were about 1.256/1.363 seconds, with roughly 1.8 GiB additional peak process-tree resident memory. This did not establish benefit. The adviser remains disabled and is not required by the engine.

## Context-preservation research

Separate offline compaction work inspected [Hermes #136671](https://github.com/NousResearch/hermes-agent/pull/136671) at `6fc8f700ed9876d4009ec9141d52950cc1a35432`, [#117462](https://github.com/NousResearch/hermes-agent/pull/117462) at `cd3e50f0d67d22a99efead563070b819125365b2`, and [#137349](https://github.com/NousResearch/hermes-agent/pull/137349) at `1ca8ee5f1d29088d7d678871c78323f44f6b0a31`. Their MIT-licensed contributions informed selected tool-result lineage, tool-argument reference harvesting and carrying exact historical references across rewrites. Individual authors and original PRs are retained in the registry.

These were narrow mechanism adaptations in a separate offline prototype, not whole-PR merges or components shipped by the gateway's Hermes overlay. Restored evidence remains quoted data; it cannot authorize a tool, supersede current instructions or bypass secret redaction. Exact-budget overflow refuses rather than truncating references. Saved-response replay and synthetic carry checks do not establish durable natural multi-generation agent continuation, and are not requirements for the gateway's scheduling contract.
# Shutdown and evidence-accounting follow-up

The complete-workflow audit exposed two distinct implementation assumptions.
The foreground wait collector starts before its animation window; checking
every sample against the later window boundary rejects valid preliminary
observations. The revised audit retains and validates all observations but
counts only the post-window-start subset, within the exact worker phase and
before its verified safe checkpoint. Python 3.11's
[system-wide monotonic clock contract](https://docs.python.org/3.11/library/time.html#time.monotonic)
supports this same-boot chronology. It does not support reusing a monotonic
deadline after a computer reboot, or mixing it with wall-clock timestamps.

Separately, intentional gateway closing was misclassified as unknown completion
when a native stop finished during shutdown. The existing queue already closes
new admission and retains active ownership. The correction follows aiohttp's
[graceful shutdown ordering](https://docs.aiohttp.org/en/stable/web_advanced.html#graceful-shutdown):
stop admission, wait for retained work, then complete cleanup. A known closing
flag must not erase active ownership or imply uncertainty by itself; an actual
uncertain completion remains a fault. The harness must inspect the final
controller state and record events after close completes. These are design
references applied to existing repository mechanisms; no external source was
copied and no new shutdown framework was introduced.
