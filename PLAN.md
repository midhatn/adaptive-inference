# Adaptive Inference roadmap

**Updated: 24 October 2026. Status: living plan, with evidence-based completion gates.**

## Destination

Make an always-on agent practical on an everyday computer. A person can browse,
play a game, watch video or work while the agent gives foreground activity
priority. The agent can also make room for a compiler, video tool or another
supported workload, then continue the original task. Closing an application or
restarting the computer should preserve the objective and completed work.

Always on means that the lightweight controller, task records and recovery
mechanisms remain available. The largest model may be unloaded. When resources
are insufficient, honest waiting is a correct outcome. Shared hardware cannot
promise unlimited background progress with literally zero contention.

The first objective is a functional, understandable system on one supported
composition. Better speed, broader hardware support and more sophisticated
prediction follow demonstrated needs. Corrective model iterations are normal;
a claimed completion still needs an independent acceptance check.

This repository is the canonical source for policy, contracts, adapters, tests,
evidence and citations. See the [always-on vision](docs/always-on-controller.md),
[integration contract](docs/integration-contract.md) and
[source-preservation contract](docs/source-of-truth.md).

## Starting point

This snapshot distinguishes released work, development work and future goals.
A roadmap entry is not a qualification receipt.

| Area | Position at this revision |
| --- | --- |
| Released foundation | Version 0.3.0 includes the portable gateway, normal/background queue, measured execution-cost feedback, durable task foundation, source preservation and scoped integration recipes. |
| Real task evidence | A recorded IQ3_S Hermes parent/child file workflow completed with independently checked artifacts. It does not establish foreground handoff or reboot recovery. |
| Native foreground and tool work | Development has a Windows controller and owned backend adapter. A bounded run demonstrated resource release, a checked GPU video encode and restoration, but its overall agent-recovery phase failed. |
| Resource-aware agent waiting | The failure exposed a private stale-provider watchdog during intentional waiting. The corrected immediate-admission and Hermes recovery integration passes software and installed-SDK fixtures; the complete corrected real-model workflow is not yet accepted. |
| Desktop protection observation | A later qualification withheld model startup while a foreground game was active. That observation is not a gaming-performance benchmark or a completed qualification. |
| Full always-on experience | Persistent everyday operation, broad foreground coverage, physical reboot recovery and native qualification of other engines remain development work. |

The [evidence ledger](docs/evidence.md) and its source-bound receipts define
accepted results. Development work earns a released capability only after its
own acceptance gate. Existing successful tests will be reused; failed and
interrupted runs will remain identified as such.

## Milestones and dependency order

| ID | Deliverable | Depends on | Initial status |
| --- | --- | --- | --- |
| M1 | One complete corrected handoff and agent-restart workflow | Existing foundation | In progress; live acceptance pending |
| M2 | A practical persistent controller with durable waiting and clear user intent | M1 | Planned |
| M3 | Measured coexistence with real desktop applications | M2; observation work can start earlier | Planned |
| M4 | Agent-driven compiler and GPU-tool handoffs | M1 and M2; foreground acceptance from M3 | Planned |
| M5 | Recovery across application restart, sleep/wake and computer reboot | M2 and supported M4 effect contracts | Planned |
| M6 | A reproducible daily-use release with fault and soak qualification | M3, M4 and M5 for its advertised scope | Planned |
| M7 | Broader engine and agent adapters using the same contracts | M2 contract stability; native acceptance follows M3–M6 | Staged expansion |
| M8 | Better policy and efficiency from measured evidence | Stable M3/M4 workloads and M6 baseline | Optional optimization |
| M9 | Additional hardware and distributed resource ownership | Relevant M7 adapters and measured demand | Conditional research |

The core order is **M1 → M2 → M3/M4 → M5 → M6**. Portable conformance work for
M7 can proceed alongside this path. Broad porting and optional research must
not displace a reproducible working reference system.

### M1 — Finish the corrected complete workflow

**User result:** an agent finishes a useful task after foreground interruption,
resource handoff and a worker restart, without losing completed work.

Use the current reference composition: Windows, the explicitly owned Strata
backend, Hermes and the existing IQ3_S model at the unchanged quality baseline.
Run the corrected implementation in a new output directory during an appropriate
desktop test interval. Do not force test windows over active user work.

The acceptance workflow must:

1. Complete actual model requests with independently checked answers.
2. Detect real foreground activity, close new admission, finish or explicitly
   resolve current ownership, verify release and later restore the same quality.
3. Admit the declared GPU tool only after fresh capacity and confirmed release;
   verify its output, exit and return to inference.
4. Interrupt the installed agent with foreground activity and observe its
   durable resource-wait state outside provider execution.
5. Reach a verified safe report checkpoint, terminate that exact worker, start a
   new worker and finish the original objective using the saved native history.
6. Verify one report write, unchanged completed artifact, valid task result,
   no unresolved operation and complete owned-process/listener cleanup.

**Done means:** one source-bound terminal acceptance for the entire corrected
composition, independently reviewed. Component successes cannot fill gaps in a
failed whole run. Record the actual wait duration; a synthetic or shorter wait
does not prove a real wait longer than the previous watchdog.

Retain the earlier failed queued-provider path and its explanation. The existing
foreground animation's frame budget remains a bounded UI test, not a game or
physical input-latency benchmark. Publish the accepted scope through the release
process below before announcing this milestone in related PRs.

### M2 — Make the controller practical to leave running

**User result:** start it once, see what it is doing, and let it wait and resume
without manually managing model servers.

Build a persistent service mode from the tested contracts. Keep bounded test
mode available; a qualification's finite process lifetime must not accidentally
become the product's definition of always on.

Required work:

- Maintain a trusted host demand record: direct user AI request, autonomous
  background task, delegated child, auxiliary request or protected tool.
- Distinguish typing a request into the AI interface from unrelated foreground
  work. The present conservative gate can block its own interactive request;
  fix that with explicit host intent, not a blanket process-name exemption or
  model-generated priority claim.
- Persist task lineage, class and resource profile across host/plugin restarts.
  Classification must not expand tool permissions.
- Store explicit user preferences and per-agent work profiles separately from
  learned timings. Start with foreground priority and a clear control for
  prioritizing the user's current AI task. Optional personalization stays local,
  inspectable and resettable; preferences cannot bypass feasibility or ownership.
- Keep deliberate waiting outside provider execution. Separate active-compute
  limits, admitted attempts, storage limits and any optional elapsed task budget.
  Long foreground activity must not lose a safely waiting task or reset its
  accounting.
- Restore a model only when actual demand exists. Add measured cooldown/minimum
  residency rules so brief quiet intervals do not cause repeated reloads.
- Invalidate or partition timing history when a native owner change alters the
  effective runtime or cache configuration. Fresh restoration must not inherit
  incompatible timing assumptions; richer calibration belongs to M8.
- Retain wait age/service accounting across immediate deferrals. Fairness applies
  when capacity is available; it cannot force work during unsafe contention.
- Expose Start, Status, Pause, Resume, Cancel and Stop through one understandable
  interface. Explain the current state and the next condition needed to proceed.
- Reconcile ownership on startup, isolate the supported profile, bound logs and
  task storage, and provide configuration/state migration and rollback.

Suggested user-facing states are **Working**, **Waiting while you use the
computer**, **Running a tool**, **Restoring the model**, **Needs verification**,
**Finished** and **Stopped**. Cancellation and failed outcomes must also remain
visible. An interface closing and the background service stopping are distinct,
explicit operations.

**Done means:** normal use requires no private receipt-file editing or manual
backend juggling. Closing/reopening the interface preserves the task; repeated
busy/quiet bursts do not reload an unused model; direct user AI requests do not
block themselves; cancellation reaches the intended task; shutdown releases only
owned resources. Missing model metadata cannot silently select a different
context or quality configuration.

### M3 — Protect actual desktop activity

**User result:** browsing, video playback, gaming and ordinary work coexist with
background progress within declared responsiveness budgets.

Extend observation beyond the foreground PID's CPU counter and recent input.
Account for relevant renderer/helper processes, GPU utilization and contention,
memory pressure and, where useful, CPU load, disk I/O, battery and thermal state.
Free VRAM alone does not establish that the GPU has spare execution capacity.

Use stable process identities and supported platform signals. Shared or detached
helpers require conservative attribution. Observe activity and resource counters;
do not collect keystroke contents, browsing history or screenshots as background
telemetry.

Evaluate separate workloads: interactive browsing, GPU-heavy graphics, video
playback, CPU-heavy work, memory pressure and rapid switching between them.
Measure each with suitable latency, frame-time, dropped-frame or task-progress
metrics. Compare no-background-AI, uncontrolled-AI and controlled conditions
where appropriate, retaining identical model quality.

**Done means:** declared per-workload budgets pass, background work progresses
when sustained safe capacity returns, and release/recovery delays are reported.
The existing animation's 25-ms p95 budget is not automatically a gaming or
video-playback budget. Set applicable targets before each comparison, retain
failed results and revise targets explicitly rather than changing them to label
an existing run successful.

If finishing a full generation takes too long to meet a practical foreground
budget, acknowledged native cancellation or a safe suspension point becomes
functional work for the reference backend. A canceled HTTP connection does not
prove native cancellation. Preserve task/output ownership and do not repeat
emitted output or tool effects. Lowering model quality is not the remedy.

### M4 — Let the agent hand resources to useful tools

**User result:** an agent can compile code or run a supported GPU step, then
continue its original task automatically.

Connect actual agent tool dispatch to the existing ownership and handoff
contract. The current supervisor-chosen video test is a starting point; the
agent-host integration must declare and request the tool's needs.

Begin with a small set of useful resource recipes:

| Recipe | Required acceptance |
| --- | --- |
| Compiler and tests | Bound CPU parallelism and RAM/commit demand; build a real artifact and verify its execution or test results. |
| Video encode/probe/decode | Bound GPU/VRAM demand; retain exact job/process identities and independently check the requested output. |
| Persistent application job | Track an exact job identifier, supported cancellation and completion through its documented API; do not treat an application process existing as job success. |
| Model-bearing media or secondary engine | Establish actual format, quality, lifecycle and device support before admitting a real model test. Until then retain a fixture/configuration-only label. |

Recipes declare requirements, preflight checks, interruption behavior, maximum
scope, effect type, artifact validation and recovery evidence. Add CPU/thread,
disk-space/I/O and device constraints when the workload needs them.

**Done means:** success, tool failure, cancellation, renewed foreground activity
and worker death produce truthful outcomes. All admitted descendants/jobs are
tracked, and inference does not resume over an unconfirmed tool owner. A tool
cannot hold the model's resource grant while waiting on that same model. Stale
telemetry or expired ownership does not authorize a new action.

Initial use can serialize heavy work. General parallel allocation is optional
until it has an explicit resource model and convincing benefit. The gateway
does not become an arbitrary shell-execution endpoint.

### M5 — Survive application and computer lifecycle changes

**User result:** reopening the application or restarting the supported computer
recovers the same objective and completed work.

First integrate ordinary installed-agent startup and task discovery, then test
controller/agent crash, sleep/wake, hibernation and an actual OS reboot as separate
cases. A same-boot worker test is not a reboot test.

Persist boot/session identity, trusted task lineage, profile/schema version and
budget policy. A saved monotonic timestamp cannot be reused across a reboot;
reconstruct permitted deadlines from durable policy without silently resetting
consumed attempts or extending a user's limit. Recheck executable, model,
configuration and resource ownership before resuming.

Recovery decisions are explicit:

| Recorded situation | Recovery action |
| --- | --- |
| Safe wait or completed checkpoint | Continue the original task after readiness and identity checks. |
| Uncertain generation | Require reconciliation by default. A host may explicitly enable retry only for a pure-generation callback, retaining consumed attempts and original intent. |
| Uncertain validation or tool effect | Inspect matching outcome evidence, such as its receipt, artifact or external job identifier; otherwise require reconciliation without automatic replay. |
| Changed artifact, foreign owner or incompatible state | Refuse unsafe continuation and present a specific recovery path. |

Support each tool's own reconciliation or idempotency mechanism. A database does
not make arbitrary external actions exactly once. Preserve completed results
through context compaction, and retain references needed to inspect the original
evidence. Corrections must still serve the original user objective.

**Done means:** actual app restart and actual supported OS reboot resume safe
tasks at the correct stage, do not repeat completed effects and expose ambiguous
ones clearly. Startup, stop, uninstall and rollback behavior are documented.
Physical power-loss, storage corruption and backup restoration remain separately
named tests; a normal reboot does not establish them.

### M6 — Qualify a reproducible daily-use release

**User result:** a supported installation can remain available through a normal
working day, with understandable limits and a reliable recovery path.

Combine the accepted M2–M5 capabilities into one product acceptance suite.
Exercise backend/controller/agent death, stale sensors, lost admission proof,
port or process-identity changes, allocation failure, interrupted tool execution,
disk-full writes, changed artifacts and failed startup.

Use increasing observation windows: a short mixed development run, a proposed
four-hour run, a full-day run and then a proposed 72-hour soak. These durations
are planning targets, not results. Advance only when the previous stage is
stable; an issue may justify a different workload or longer observation.

**Done means:**

- Useful artifacts complete across repeated activity and resource changes.
- Every task is completed, explicitly failed/canceled, safely waiting or awaiting
  verification; no task silently disappears.
- Queues, memory, logs, database growth and owned process counts remain bounded.
- Declared responsiveness and feasible-work fairness budgets pass.
- Shutdown, next startup, state migration and rollback are checked.
- A fresh installation/fork can reproduce the documented supported workflow.
- The release names exact platform, engine, agent, model, configuration, receipts
  and remaining limits.

A useful narrower alpha may be released before M6, with its tested scope visible.
The label **daily-use always-on** requires this gate for the advertised platform.

### M7 — Generalize through capability-tested adapters

**User result:** other agents and engines can adopt the same controller without
duplicating its policy or relying on old PR conversations.

Keep five qualification levels separate: configuration recipe, actual SDK
transport, installed application, real accepted task, and native lifecycle/restart
qualification. A submitted or merged PR is a separate delivery state.

| Lane | Default progression and conditions |
| --- | --- |
| Reference composition | Keep Strata + Hermes as the first complete contract and regression anchor. |
| Next native engine | Evaluate llama.cpp and Ollama first according to exact IQ3_S/model-format, platform and lifecycle support. Prove one second native adapter before expanding several at once. |
| Desktop server | Add LM Studio lifecycle support only through its verified interfaces and exact versions. |
| Higher-throughput servers | Evaluate SGLang and vLLM after deployment/model compatibility is established. The current single-active-request gateway may need capability-aware integration with native batching; do not assume its desktop policy is an efficient datacenter policy. |
| Apple-native execution | MLX-LM requires the actual supported Apple platform and compatible model representation; retain the current evidence level until available. |
| Next agent | Prefer OpenClaw or another host with suitable public durable-session/tool interfaces; qualify one complete continuation port before multiplying recipes. |
| Additional agents | Progress Aider, OpenHands, Continue, Cline, LangGraph and CrewAI by user value and exposed capabilities. Resolve concrete field-loss or tool/recovery gaps before claiming parity. |
| Legacy targets | Retain TGI, Roo Code and AutoGen recipes at their documented compatibility level; recheck upstream maintenance/submission status before new work. |

Every engine adapter advertises capabilities separately: status, drain,
acknowledged cancel, suspension, resource release, fresh capacity, restore,
cache controls and batching. Unsupported actions remain unavailable. Every
agent adapter proves task identity, classification, tool results and continuation.

**Done means for each port:** its applicable shared conformance checks plus its
own real task and native receipts at the claimed level, with preserved quality,
tools, credentials and context behavior. A quality field dropped by a client,
such as a declared reasoning budget, is a parity blocker rather than a cosmetic
difference.

Contract design, fixtures and a thin second adapter can start after M2 stabilizes.
Do not wait for every upstream merge to make the canonical implementation useful.
Do not promise native parity on all hardware or call all matrix targets tested.

### M8 — Improve policy and efficiency after measuring the bottleneck

**User result:** less waiting, fewer expensive reloads and better useful task
completion without sacrificing foreground responsiveness or model quality.

Keep a fast deterministic control loop for current feasibility and ownership.
A slower estimator or optional adviser may rank already-allowed actions. It
cannot grant permissions, waive memory requirements or override an uncertain
operation.

Compare changes incrementally:

1. Calibrate timing and uncertainty by relevant model/runtime/cache conditions;
   expire or partition observations after meaningful owner/configuration changes.
2. Account for total task cost: queueing, generation, tool work, waiting,
   unload/reload, retries and successful completion.
3. Compare demand-aware hysteresis, switching costs, weighted fairness and
   workload-change detection against the existing policy.
4. Where natively supported, evaluate lower-disruption actions such as reducing
   execution concurrency, thread shaping, partial cache relief or safe suspension
   before a full unload. Do not invent an unsupported backend control.
5. Evaluate statistical or contextual selection offline, then in shadow mode
   where proposed actions are logged but do not control resources.
6. Enable a policy only after repeated matched-quality comparisons demonstrate a
   useful benefit including overhead, failures and recovery cost. Keep rollback
   and the deterministic fallback.

The [research notes](docs/research.md), [bibliography](REFERENCES.bib) and
[preserved reference sources](third_party/reference-sources/README.md) already
cover queueing, Peak EWMA, adaptive concurrency, heterogeneous scheduling and
task-level work. Refresh primary sources before choosing a new mechanism.
Published speedups on another workload are not our results.

Jev and Laya are optional research, not prerequisites or enabled dependencies.
The previous Laya experiment established no advantage over the guarded
deterministic baseline. New evaluations using another decision model or hosted
model service are outside the current IQ3_S-only test constraint.

### M9 — Expand hardware only where it helps

**User result:** the same ownership and recovery principles can use additional
supported resources when there is a measured reason.

Investigate AVX-512 and other CPU capabilities through actual supported runtime
builds, then NPU support, additional GPUs, memory/storage tiers or multiple hosts
as separate opportunities. Hardware presence is not proof that a model or its
operators are supported.

For NPU or another accelerator, first establish runtime availability, model and
operator compatibility, precision/quality preservation, measurable overhead and
a fallback. For several hosts or devices, add explicit ownership/fencing,
network-partition handling and recovery; the present local lock is not a
distributed lease.

**Done means for an enabled feature:** an exact supported configuration, useful
measured improvement and intact resource/task guarantees. This lane does not
block a functional single-machine release, and it cannot change the model
baseline silently.

## Rules that apply to every milestone

- **Current model constraint:** all new actual inference qualification uses the
  user's existing IQ3_S model at the established quality baseline. Do not replace
  it with another model or quantization to make a port pass. A backend or
  model-bearing ComfyUI/H3 workflow that cannot meet that constraint stays at
  fixture/configuration evidence until the test scope is explicitly changed.
  Non-model compiler and encode/decode tests remain available.
- **User and task intent:** foreground protection, explicit user requests,
  background progress and tool needs are distinct facts. Do not infer privileges
  from prompt text, a public queue class or an untrusted adviser.
- **Continuity before certainty claims:** keep the original objective and
  acceptance feedback. Correctable output is expected; unknown external effects
  require evidence rather than an optimistic retry.
- **One shared design:** reuse the existing queue, TaskStore, handoff and
  capability contracts. Native/application-specific code is a thin adapter
  where possible.
- **Independent acceptance:** review the actual output and ownership receipts.
  Software tests, fixtures, model runs, foreground measurements and reboot
  tests remain distinct evidence levels.
- **Canonical attribution:** preserve authorship, exact revisions, relevant
  licensed source, notices and local explanations when work is actually used.
  Maintain the standalone reconstruction path; no contributor-review document
  is needed for unused work.
- **Operational boundaries:** do not disturb unrelated applications or silently
  take over an existing model server. Keep credentials and raw private histories
  out of published artifacts. CoS is not part of the execution plan.

## Measurements and stop conditions

Each acceptance plan records the workload and budget before execution.

| Question | Measurements or invariants |
| --- | --- |
| Is the person protected? | Application-appropriate p95/p99/worst-case latency, stalls/dropped frames and observed foreground coverage. |
| Does the task still finish? | Independent artifact acceptance, original objective, completed effects, correction count and end-to-end elapsed time. |
| Did resources actually move? | Exact owner exit/acknowledgement, fresh RAM/commit/VRAM and other relevant capacity, tool identity and resource-return evidence. |
| Is recovery reliable? | Same task/history, correct budget, no duplicate confirmed effect, explicit ambiguity and restart/reboot-specific evidence. |
| Is the policy useful? | Feasible-work wait age, release/resume delay, reload frequency, prediction error and controller overhead. |
| Can it remain installed? | Bounded memory/storage/process growth, clean lifecycle, reproducible install, migrations and rollback. |

Stop or hold an operation when identity, capacity freshness, cancellation outcome,
tool completion or durable state is unknown. If the user's activity consumes the
available budget, remain visibly waiting. If a capability or model format is
unsupported, hold that port without blocking the reference implementation.

A non-regression result is useful. Claim an improvement only against a suitable
comparison that actually exhibited the problem. Do not reduce quality, weaken
checks or hide unsuccessful trials to obtain a milestone pass.

## Release and upstream propagation

Every accepted milestone is independently releasable at its actual scope:

1. Finish the applicable acceptance and independent review. Recheck the final
   source after any fix that can affect the evidence.
2. Save sanitized, allowlisted receipts, failures, limitations and reproduction
   instructions in this repository. Keep private logs and model assets separate.
3. Update contracts, compatibility/evidence tables, changelog, citations and
   version. Verify fresh installation, applicable CI, complete source
   distribution and offline source reconstruction.
4. Publish the canonical commit/release before referring downstream users to it.
5. Refresh the [upstream delivery ledger](docs/upstream-delivery.md) and exact PR
   heads/states. Update every relevant open PR when there is applicable solid
   evidence; distinguish new canonical work from unchanged upstream code.
6. Extract the smallest useful adapter or host fix for each project. Preserve
   maintainers' contribution requirements and merge control. Where an upstream
   contribution is unavailable, retain a supported canonical adapter when
   feasible; do not let that delay the core product.
7. Record resulting commits, tests, comment URLs and adoption status. Retire
   an overlay only after upstream replacement passes the same relevant contracts.

Do not use a roadmap update as a successful runtime announcement. Do not reopen
closed historical PRs routinely or treat archived/policy-constrained targets as
promises of an eventual merge. Existing related PRs are maintained as delivery
channels, while this repository remains the source of truth.

## How the roadmap changes

The destination and evidence standards remain stable. Implementations, order and
scope can change when a real failure, new upstream capability or user priority
makes another route better.

Maintain a compact milestone record with: **ID, status, user outcome, dependency,
responsible owner, exact source, acceptance test, evidence, known limit and next
decision**. Use distinct states: planned, implementing, awaiting qualification,
qualified, released, or held with a concrete reason. Do not collapse local
implementation, release and upstream adoption into one checkmark.

Review the plan after every accepted milestone, significant failed run or
relevant upstream change. Record what changed, the observation that justified
it and the next experiment. Keep failed evidence; issue a successor attempt
rather than rewriting an earlier result. Reprioritize a functional blocker
ahead of optimization, and defer an optional feature that adds complexity
without measurable value.

These milestones are an order of work, not calendar commitments. Estimate the
next small delivery after its dependencies and environment are known; update
that estimate when evidence changes. Do not publish a completion date or
percentage for the whole research-and-engineering program without a defensible
basis.

## Next execution packet

The next technical packet remains M1:

- Recheck the frozen corrected source, model/quality settings and prepared task.
- Choose a fresh qualification directory and a suitable desktop interval.
- Run the complete foreground, tool, waiting and worker-restart sequence.
- Inspect artifact, history, source, capacity and cleanup evidence independently.
- If it passes, publish the scoped canonical result and propagate validation.
- If it fails, preserve the failure, fix the smallest demonstrated cause and
  revise this plan's next step without claiming the milestone complete.

M2 demand/intent, persistence and user-interface design can proceed alongside
that qualification. The first release is useful before every later milestone
is finished; each release must say clearly which experience it has established.
