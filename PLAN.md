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
| Native foreground and tool work | One complete source-bound Windows/IQ3_S workflow is accepted: real foreground interaction, verified release, checked GPU encode, restoration and clean shutdown. |
| Resource-aware agent waiting | Immediate admission and the pinned Hermes recovery adapter completed the same accepted workflow, with durable waiting following foreground interruption and one same-boot worker restart. |
| Desktop protection observation | A later qualification withheld model startup while a foreground game was active. That observation is not a gaming-performance benchmark or a completed qualification. |
| Full always-on experience | Persistent everyday operation, broad foreground coverage, physical reboot recovery and native qualification of other engines remain development work. |

The [evidence ledger](docs/evidence.md) and its source-bound receipts define
accepted results. Development work earns a released capability only after its
own acceptance gate. Existing successful tests will be reused; failed and
interrupted runs will remain identified as such.

## Milestones and dependency order

| ID | Deliverable | Depends on | Initial status |
| --- | --- | --- | --- |
| M1 | One complete corrected handoff and agent-restart workflow | Existing foundation | Accepted for the bounded Windows/Strata/Hermes IQ3_S composition |
| M2 | A practical persistent controller with durable waiting and clear user intent | M1 for live integration acceptance | Active: durable demand and bounded task controls implemented; persistent host and Hermes control integration under review |
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

**Accepted, 24 October 2026:** [controlled-11](provenance/windows-handoff/controlled-11/README.md)
passed the complete source-bound terminal audit after two arithmetic tasks,
two real foreground animation phases, a verified 90-frame GPU encode and a
same-boot installed-Hermes worker restart. Both arithmetic tasks passed on the
first attempt. The recorded durable wait spanned 81.375 seconds during release
and restoration following foreground demand; it began after the second visible
window ended. This does not demonstrate a wait longer than the former
180-second watchdog or waiting throughout a visible 81-second workload.

Failures changed implementation and procedure while the acceptance gate stayed
fixed. The [retained outcomes](provenance/windows-handoff/controlled-11/result.json)
and preserved predecessor sources record:

- A queued provider hit its private stale-provider watchdog during deliberate
  deferral. The adapter now uses public immediate admission and authentic
  non-dispatch receipts, keeping safe waiting outside provider execution.
- A Windows metadata query raced with process teardown. A bounded wait on the
  same retained handle can confirm exit; access denial alone cannot excuse a
  live process. Unknown startup outcomes still require reconciliation.
- Window activation without ordinary input did not establish user activity.
  Qualification now verifies the actual input-age observation.
- An arithmetic answer had correct item totals but a wrong grand total. The
  harness reuses bounded feedback with unchanged independent checks and saves
  every attempt; the unsuccessful run remains failed.
- A later run completed its tasks but failed final shutdown auditing. Intentional
  closure is now distinguished from uncertain completion, the harness captures
  the final transition ledger after close, and both scheduler and controller
  must be clean. The earlier recorded pass remains explicitly unaccepted.
- The wait collector starts before the visible window. The exporter validates
  all observations against their worker phase and reports the exact subset,
  revisions and duration instead of assuming every wait occurs on screen.

The accepted scope uses Windows, the explicitly owned Strata backend, installed
Hermes and the existing IQ3_S at the unchanged quality baseline. Its complete
source and sanitized evidence live here; private logs and model assets do not.
The following gate remains required for any new composition or changed run:

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
process below. An upstream PR receives it only when it supports a relevant,
mergeable change with validation for that target repository.

### M2 — Make the controller practical to leave running

**User result:** start it once, see what it is doing, and let it wait and resume
without manually managing model servers.

Build a persistent service mode from the tested contracts. Keep bounded test
mode available; a qualification's finite process lifetime must not accidentally
become the product's definition of always on.

The first component reuses the existing TaskStore transactions and
ownership for durable inference demand; it introduces no second database.
Demand must exist independently of queued HTTP tickets because immediate
admission deliberately leaves no ticket when deferred. KEDA activation/cooldown
and Temporal durable waiting are inspected design references; only mechanisms
actually adopted will be credited as implementation lineage. The
[durable demand component](docs/durable-demand.md) passes 15 component tests,
including replacement-worker persistence and repeated observation without
consuming history. Independent review found no blocking component defect;
host integration and live acceptance remain separate steps. Its observation
does not grant dispatch or unloading, and demand cancellation does not yet
cancel the existing runner. The [task-control component](docs/task-controls.md)
now records ordered Pause, Resume and Cancel requests without taking that
runner's long-held lock. It reuses a separate task record in the same store;
only the actual owner applies and acknowledges a request at a safe checkpoint.
The existing launchers and Hermes runner still need the explicit hooks below.

**Plan adjustment from integration review:** an intermittent store-verification
error prompted inspection of SQLite's actual contracts. Live immutable reads and
independent raw header reads were unsupported patterns, although the specific
Windows failure's cause remains unproved. The
[storage correction](docs/task-store-verification.md) reuses the existing stable
lock for short operations and SQLite's recovery implementation. Its Windows
component passed 75 supplied tests and four independent probes. Complete the
cross-platform checks, then compose one exact corrected store in the host and
every worker before rerunning pause/restart qualification. Stop and join older
readers before upgrading; never mix the old and new access protocols. Preserve
failed runs and the accepted M1 source identity. Model quality and acceptance
requirements remain unchanged.

**Next integration sequence:** compose the already reviewed demand and cold-start
components with the existing native host, then add trusted user controls and
qualify the persistent composition. Research the exact preserved startup cache
planner before adding load feasibility; its RAM/commit estimate does not prove
GPU fit or reserve resources. A missing measurement must remain unknown.

Component review also found an admission constraint: a prepared operation can
make demand ineligible while a queued request waits for an unloaded model. The
host must enforce immediate admission and resolve only a proven non-dispatch
before returning to durable waiting. Unknown provider outcomes cannot be
reclassified as safe waiting. Pause/cancel requests must be acknowledged by the
trusted task owner at a safe boundary, rather than editing a live task behind
its owner. Cold preparation must retain the existing startup barrier without
inventing a running owner or release receipt. These are integration requirements;
component tests alone do not qualify the persistent product.

Review feedback refined this sequence. The first control-status reader could
mistake concurrent valid acknowledgements for corruption; the corrected read
order and regression preserve the unsuccessful predecessor. Host composition
also exposed a soft setup deadline and a completed-timeout cleanup retry bug.
The successor retains setup work across timeout, fences late startup and joins
completed failures while preserving their original errors. These lifecycle
fixes are under component review, not live qualification. Next, connect controls
at Hermes' actual native-history safe points, then qualify the complete cold
start, demand, waiting, cancellation and cleanup path with unchanged IQ3_S.

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

- **Research before invention:** before solving each new problem, search current
  primary research, GitHub implementations/issues/PRs and official documentation
  for existing solutions. Reuse or adapt a suitable mechanism first. Record what
  was inspected, its revision/date, applicability and licensing; explain the gap
  before adding original work. Recheck relevant prior findings rather than
  repeating completed research or replacing a validated design for novelty.
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
   heads/states. Identify a specific change that belongs in each proposed target
   repository. The list of related PRs is an audit inventory, not a broadcast list.
6. Prepare the smallest mergeable adapter, host fix or scoped documentation
   change for that repository, and validate that actual PR revision with its
   applicable tests. Link only the canonical evidence relevant to that change;
   a canonical result alone does not qualify an unchanged upstream branch.
   Preserve maintainers' contribution requirements and merge control. Where an
   upstream contribution is unavailable, retain a supported canonical adapter
   when feasible; do not let that delay the core product.
7. Record resulting commits, tests, comment URLs and adoption status. Retire
   an overlay only after upstream replacement passes the same relevant contracts.

### Target-specific propagation gate

Propagate a result to an upstream PR only when all four conditions hold:

1. The behavior or fix is relevant to that repository and to the PR's scope.
2. The PR contains, or is updated with, a concrete change that can be reviewed
   and merged there. A link back to this repository is supporting context, not
   the implementation of a missing integration.
3. Validation covers that exact upstream base/head and the proposed integration.
   Keep fixture, real-model and native lifecycle results distinct; do not inherit
   unsupported claims from a different target or from the canonical composition.
4. The PR explains the target-specific problem, resulting behavior, relevant
   tests and remaining limitations, with a stable link to its canonical source
   and supporting evidence.

For example, a Hermes PR should receive a tested Hermes middleware, task-resume
or request-handling change and its Hermes validation. Strata-only memory results,
another engine's performance or a general Adaptive Inference milestone do not
belong in that PR merely because Hermes is listed in the integration matrix.
Likewise, a documentation-only PR must be validated and described as documentation;
it does not acquire a native-runtime claim from a linked example.

If there is no applicable mergeable change or its validation is incomplete,
keep the result in the canonical repository and hold that upstream update.
Do not send general progress announcements to every related PR. Do not reopen
closed historical PRs routinely or treat archived/policy-constrained targets as
promises of an eventual merge. Target-specific delivery remains traceable here.

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

The implementation loop is **observe the issue → search existing solutions →
adapt the smallest suitable approach → validate → update the plan from the
evidence → continue**. Review feedback participates in the same loop. A failed
approach changes the next experiment, not the original user objective or the
standard required to claim success.

These milestones are an order of work, not calendar commitments. Estimate the
next small delivery after its dependencies and environment are known; update
that estimate when evidence changes. Do not publish a completion date or
percentage for the whole research-and-engineering program without a defensible
basis.

## Next execution packet

Finish M1 publication with exact source/evidence preservation, fresh distribution
checks and CI for the submitted revision. Keep the accepted native composition
separate from any upstream target whose proposed change has not been tested.
The first publication CI exposed temporary-path spelling mismatches in three
evidence fixtures on macOS and hosted Windows. Resolve those fixture roots using the existing standard-library path
operation, retain their originals, and rerun cross-platform CI. The runtime,
exporter's exact-path checks and accepted hardware evidence stay unchanged.

The active technical packet is M2:

- Compose reviewed durable demand, cold parked ownership and the existing
  controller into one explicit persistent-host mode. Retain bounded M1 mode.
- Reuse the actual native startup cache planner and original observations.
  Distinguish low capacity, unknown data and unresolved startup; a cache proposal
  is neither full GPU feasibility nor a reservation.
- Add trusted pause/resume/cancel delivery with durable acknowledgement at safe
  owner checkpoints. Keep waiting outside active provider requests and retain
  the original task across interface or worker replacement.
- Start with one qualified profile and cooperating worker. Reuse the existing
  lifecycle/watchdog mechanisms, make service stop distinct from interface
  close, and bound storage without discarding unfinished work.
- Provide understandable status and explicit user AI-task intent, then test
  cold idle, demand arrival, repeated busy/quiet activity, pause/resume/cancel,
  active-request boundaries, interrupted startup and orderly shutdown.
- Independently review the composed host before a fresh IQ3_S qualification.
  Record failures, revise this packet from evidence and keep quality unchanged.

M3/M4 desktop and tool qualification follows the persistent composition; physical
restart recovery remains M5. The first release can be useful before every later
milestone is finished, with its established experience stated precisely.
