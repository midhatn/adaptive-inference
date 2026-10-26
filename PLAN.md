# Adaptive Inference roadmap

**Updated: 26 October 2026. Status: living plan, with evidence-based completion gates.**

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
| M2 | A practical persistent controller with durable waiting and clear user intent | M1 for live integration acceptance | Active: bounded installed composition, retained commands, safe paused expiry and explicit same-window continuation qualified; ordinary task use remains |
| M3 | Measured coexistence with real desktop applications | M2 for broad qualification; a bounded control-window policy now feeds M2 | Early policy work active; broad desktop qualification planned |
| M4 | Agent-driven compiler and GPU-tool handoffs | M1 and M2; foreground acceptance from M3 | Planned |
| M5 | Recovery across application restart, sleep/wake and computer reboot | M2 and supported M4 effect contracts | Planned |
| M6 | A reproducible daily-use release with fault and soak qualification | M3, M4 and M5 for its advertised scope | Planned |
| M7 | Broader engine and agent adapters using the same contracts | M2 contract stability; native acceptance follows M3–M6 | Staged expansion |
| M8 | Better policy and efficiency from measured evidence | Stable M3/M4 workloads and M6 baseline | Optional optimization |
| M9 | Additional hardware and distributed resource ownership | Relevant M7 adapters and measured demand | Conditional research |

The core order is **M1 → M2 → M3/M4 → M5 → M6**. Portable conformance work for
M7 can proceed alongside this path. Broad porting and optional research must
not displace a reproducible working reference system.

The dependency order can change when integration evidence identifies a
prerequisite. The 25 October adjustment brings a small part of M3 forward:
distinguish progress in the controller's own interface from actual contention.
This does not advance the broad desktop or reboot milestones.

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
component passed 75 supplied tests and four independent probes. The focused
canonical correction subsequently passed all 14 CI checks across Windows, Linux
and macOS with Python 3.11/3.12 and offline source reconstruction. Compose one
exact corrected store in the host and every worker. Stop and join older
readers before upgrading; never mix the old and new access protocols. Preserve
failed runs and the accepted M1 source identity. Model quality and acceptance
requirements remain unchanged.

**Next integration sequence:** compose the already reviewed demand and cold-start
components with the existing native host, then add trusted user controls and
qualify the persistent composition. Research the exact preserved startup cache
planner before adding load feasibility; its RAM/commit estimate does not prove
GPU fit or reserve resources. A missing measurement must remain unknown.

The optional [controller component](docs/persistent-controller.md) now supplies
cold parked initialization, demand-driven restoration and idle release. Its
compatibility tests preserve the default bounded host path. The complete M1
runtime is archived inside the repository before changing the current runtime;
passing compatibility tests does not change the older result's source identity.

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
fixes passed component review; the installed-agent controls are connected at
Hermes' actual native-history safe points in the development composition. Its
complete cold-start, demand, waiting and cleanup path still needs successful
live qualification with unchanged IQ3_S.

The installed-agent bridge review exposed two further requirements. Saved
completion candidates need exact fields and types before resumed acceptance;
truthy malformed data must not become a successful task. Bootstrap must consume
already-recorded controls before creating waiting demand, otherwise a cancelled
task can briefly request a native load. Both original failures are retained in
development evidence. A controlled safe checkpoint will qualify pause, worker
replacement and resume without stopping an uncertain operation.

The first two live cases were deliberately separate from the full UI gate.
The pre-cancelled development case completed across two worker owners without
provider calls, tool effects or a native launch. A separate complete-task attempt
remained parked while the actual foreground ChatGPT process used sustained CPU,
then failed its existing 240-second readiness bound with clean shutdown and no
model launch. That is useful protection evidence but not a completed task.

**Priority established by that result:** finish and qualify the trusted own-window
control interface before another complete-task attempt. It must authenticate its
task/session, retain process/window ownership and distinguish the user's request
from unrelated foreground activity. Do not whitelist ChatGPT, force focus to
manufacture idle conditions, raise thresholds or extend the failed run's timers
to obtain a pass. Treat a new coexistence policy as separate M3 development,
with its own predeclared acceptance. Keep the
failed attempt and use a new source-bound case for any changed composition.
Every case retains its original deadline, prompt, arrival and attempt accounting;
worker exits precede host cleanup. These bounded cases do not establish indefinite
service lifetime, arbitrary tools or a reboot.

**25 October development feedback and next priority:** the owned GUI now passes
an actual cold Pause/Stop run with an installed worker, preserved task state and
clean shutdown. The complete GUI/inference/replacement workflow remains
unaccepted. Four full attempts failed before task inference. One was interrupted
by a Windows status-file replacement error; a scratch experiment rejected a
reader-only sharing fix. Subsequent observation reuses the existing gateway
status API instead of opening its live status file.

The fourth full attempt restored the native model, then yielded and released
it before admission; its original 240-second readiness gate failed. The saved API
trace contained no successful admission. A separate paused-task GUI profile,
spanning startup, waiting, Pause and Stop, found most measured GUI-thread CPU
time inside the native Tk event loop, with little
time in application callbacks. That diagnostic does not identify a native bug
or establish unprofiled performance. Further speculative rendering changes and
repeated identical retries are not the next step.

The conservative foreground policy currently requires sampled foreground CPU
at or below 0.05 cores through a five-second recovery dwell. It does not use the
already sampled host CPU busy fraction. Process activity alone therefore acts as an
admission veto, although it does not measure contention or responsiveness.
Bring the relevant M3 work forward as an explicitly versioned, opt-in policy:

1. Reuse the existing authenticated, serialized GUI status exchange to observe
   main-thread control-path progress. Require the exact retained window/session
   identity and genuine current user intent; a server response alone is not
   proof that the GUI processed it.
2. Combine fresh progress observations with host CPU headroom and existing
   RAM/commit, demand, ownership and resource-release checks. Preserve the
   conservative fallback for unqualified foreground applications.
3. Declare freshness, recovery and control-response budgets before testing.
   Validate missing/stalled progress, resource pressure and foreground switching
   as well as successful IQ3_S task completion and worker replacement.
4. Publish only the demonstrated scope. Control-path progress does not establish
   frame time, video playback, gaming performance or arbitrary application
   responsiveness. Those remain separate M3 workloads.

The first candidate's trial bounds are fixed before implementation and tests:

| Signal | Candidate requirement |
| --- | --- |
| Control exchange | Two consecutive successful authenticated status exchanges in one session and intent generation; host timestamps only |
| Exchange completion | Each authenticated arrival to joined, successfully closed connection at most 0.5 seconds |
| GUI progress | Previous successful closure to the next serialized status arrival at most 2.5 seconds; latest successful closure no older than 2.5 seconds |
| Host CPU | Clear at or below 80% busy; busy at or above 95%; intermediate values block new admission and recovery |
| Existing guards | Activity age at most 1 second; RAM and commit each at least 4 GiB; five-second recovery dwell; two busy samples to yield |
| Qualification limits | Original 900-second task, 240-second readiness and 1,800-second outer limits |

Selecting the cooperative profile does not permit fallback to the old
low-process-CPU rule when its health or host measurements fail. Invalidate old
evidence on intent/session changes, failed exchange completion, Stop, revocation
or clock regression. Normal per-request connection closure remains expected.
These are experimental control-progress bounds, not universal responsiveness
constants. Preserve raw CPU observations rather than rewriting them as idle.

This adapts the feedback-control principle studied in
[Heracles](https://research.google/pubs/improving-resource-efficiency-at-scale-with-heracles/)
and [Caladan](https://www.usenix.org/conference/osdi20/presentation/fried): use
signals relevant to interference and the protected workload. Their datacenter
results are not transferred to this Windows composition. Reuse the project's
existing control transport and feedback contracts first. Windows background QoS
remains a possible later actuator, not evidence of GPU or memory isolation.
The existing [research review](docs/research.md) covers Envoy and Netflix's
completed-request feedback and MARS's separate admission/execution layers.
[Python's stream contract](https://docs.python.org/3.11/library/asyncio-stream.html#asyncio.StreamWriter.wait_closed)
defines connection closure; it does not establish GUI consumption, hence the
following serialized main-thread request requirement. Recent
[DLFP results](https://arxiv.org/abs/2609.38386v1) reinforce this measurement
boundary: a scheduler interval need not measure completed GPU work. No scheduler
algorithm or published speedup from these references is claimed here.
Keep every failed case failed and retain its original deadline and quality.
The new policy must earn a new acceptance result; it cannot revise the old one.

**Later 25 October feedback:** the first live cooperative-policy attempt passed
initial admission and ran two real IQ3_S requests with its owned control window
in the foreground. Its readiness observation recorded healthy control progress,
fresh resource headroom and foreground process CPU above the old 0.05-core
recovery limit. This supports the narrow distinction the candidate was designed
to test; it does not establish arbitrary application responsiveness.

That fifth full attempt still **failed**: the model wrote correct per-item
amounts but incorrect unit and grand totals. The unchanged report check caught
the error before worker replacement, and normal shutdown released the owned
model and preserved the failed task. Initial admission is therefore supported;
complete-task and replacement acceptance were still outstanding at that point.

**Next adjustment:** make correctable tool proposals part of the existing
feedback path. The bounded recovery adapter deliberately refuses to overwrite
a completed file effect. Validate a proposed report before dispatching its
write, return diagnostic feedback through Hermes' existing native tool-result
loop, and retain rejected proposals separately from completed effects. Reuse
the shared `Verdict` contract and the existing eight-request budget and whole-task
deadline. Preserve the original prompt, IQ3_S quality, independent final oracle,
and exactly one dispatched report write. Do not wrap the agent in a second
conversation or retry loop, or silently repair its file outside the agent.

This follows established
[tool argument validation and bounded correction](https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/#tool-retries)
and the project's existing feedback design. Pydantic AI is a design reference,
not a new dependency; implementation uses the pinned Hermes public middleware.
Bind the validator identity to the durable task, preserve rejection feedback
across restart, and keep interrupted or uncertain effects blocked. Test a wrong
proposal followed by correction before the next source-bound full trial. The
fifth failure remains failed even if its successor succeeds.

**Sixth development trial: bounded recovery passed.** The successor completed
the real control-window/IQ3_S/installed-Hermes sequence with validation enabled:
two actual Resume commands, a verified report checkpoint, replacement of that
worker, completion from the preserved conversation and normal final Stop.
Independent terminal review passed 42 checks. Three real model requests produced
one correct report write; the replacement preserved its bytes and the completed
tool results. Both native model lifetimes and all retained controls and children
closed cleanly. The original prompt, deadline and quality settings were retained.

Both readiness observations belonged to their current intent generations and
passed the cooperative progress/resource checks. The first also admitted above
the old foreground-CPU recovery floor. This qualifies that bounded development
composition, not the complete M2 milestone or unrelated foreground applications.
The real model proposed a correct report on its first try, so this run does not
prove real-model correction. A separate installed-Hermes synthetic-provider
fixture exercised rejection, native feedback, correction and one actual write.

**Next priority: promote and qualify the installed composition.** Move the
reviewed control components into one maintained package with qualified imports,
preserved sources, citations and existing tests. Keep a library-only slice
clearly separate from a runnable desktop host. Then parameterize the existing
host/backend composition, preserve retained startup pipes and process ownership,
and qualify the installed wheel outside its source checkout. Packaging changes
cannot inherit a previous runtime's live qualification without checking the
changed launch/import path. Avoid a second miniature task runner or another copy
of the private experiment layout. Interface close/reopen, meaningful terminal
status text, cancellation, busy/quiet bursts and longer service use remain M2
work; computer reboot and broad desktop workloads retain their separate gates.

**Installation feedback:** use one complete installed composition, with the
existing host and GUI sharing the same full Python environment. Inspection of
the pinned CPython Windows launcher and a bounded process probe confirmed that
an ordinary virtual-environment launcher adds a process between the retained
launcher and the executing GUI. Keep the exact process/window ownership checks;
do not replace them with process discovery. Verify the child's installed import
closure, including package initializers, before acquiring its GUI resources.
The first installed task profile remains the qualified IQ3_S orders-report
workflow; packaging it does not establish arbitrary agent tasks.
For the first installed interface, the window's X minimizes the same owned
window to the taskbar, where it can be restored; Stop remains explicit shutdown.
Qualify that behavior without presenting it as window destruction/reopening or
process-restart recovery. Those broader interface-survival gates remain open.

The actual installation also exposed a packaging constraint: the selected
worker Python was externally managed, so ordinary package installation was
refused. Preserve that failure and the existing managed installation. Reuse
Astral's documented standalone archive deployment in a dedicated directory,
then verify the exact distribution, executable, installed wheel and actual
process identity before the live trials. Do not weaken ownership checks or add
another package bootstrap to work around the refusal. Archive variants must
be checked explicitly: the first archive had a different executable hash and
was withheld from execution. This is a deployment adjustment, not a model,
quality, task-budget or acceptance change. Sources and the supported procedure
belong in the [deployment guide](docs/installed-desktop.md).

**Installed reference qualification, 25 October:** the regular package passed
separate cold and full Windows trials. Independent terminal review passed 35
cold checks and 47 full checks. The cold case acknowledged Pause, minimized and
restored the same window, then stopped without model calls or file effects.
The full case made three real IQ3_S requests, wrote one independently checked
report, replaced the worker at a verified checkpoint and completed from the
saved task without repeating that write. The original quality, eight-request
allowance and 900-second deadline were preserved. Both native model instances,
workers, GUI and connections completed normal owned cleanup. The
[installed acceptance record](provenance/installed-desktop/acceptance/README.md)
binds this result to its exact package and deployment; it is not full M2,
computer-reboot, gaming-performance or general-task acceptance.

**Publication feedback:** fresh CI found test assumptions that the local run did
not expose: temporary-directory aliases on Windows/macOS and Python 3.12's
additional AST fields. The repaired fixtures use canonical temporary paths and
an explicitly bounded AST comparison, preserving the original expected hashes,
runtime checks and historical live receipt. The publication gate passed in
[PR #18](https://github.com/midhatn/adaptive-inference/pull/18):
all 14 checks passed on `de735ddedaad02703c6c379fca91287219644316`, and
the successor source archive verified 681 files against Git and all 52 runtime
modules against the accepted wheel. The merged tree is the unchanged reference
for the following interface work. These fixture repairs do not establish a new
model or desktop result.

The trial also exposed a usability issue: the first Stop click after task
completion did not register, while a second click completed normal Stop. Both
observations remain in that version's record. The follow-up reproduced the
interaction with background status polling and reused the existing serialized
channel to retain one local user command. Recording and owner acknowledgement
remain distinct; there are no parallel requests or automatic mutation retries.

**Retained-command successor accepted, 25 October:** the new installed cold and
full cases passed 38 and 50 independent terminal checks. Cold used one Pause and
one Stop click with no model launch. Full used one click for each of two Resumes
and one Stop after completion, with three real IQ3_S requests, one correct report
write, preserved worker-restart progress and normal cleanup. The
[successor record](provenance/desktop-control-intent/acceptance/README.md) binds the
actual package and complete result. The original quality and budgets are intact;
only the client changed among 52 runtime modules. The deliberate status-ordering
tests and the real GUI trials supply separate evidence: the live clicks were not
proven to overlap a poll. These results do not establish universal input
reliability, broader foreground performance or full M2. Safe task expiry was the
next gate and is recorded separately below.

**Publication test feedback:** one Windows CI job failed an existing intent test
while the other 13 jobs passed. A controlled delayed-authority reproduction
exposed its invalid assumption: a bounded `pending` response can arrive before
the retained Resume operation finishes and activates intent. The exact original
CI timing was not captured. Tests of completed activation must await that exact
retained operation; tests of pending replies must keep the distinction visible.
Keep the production response timeout and freshness limits unchanged, preserve
the failed CI run, and require fresh exact-head CI after the fixture repair.

The repair then passed 48 relevant checks on Python 3.11 and 3.12, and an
independent 48-check replay against the installed runtime. Restoring the old
premature helper made the new regression fail as intended. All 14 CI checks
passed on `26cc60dc4bc0f3b314cecc7aa05bf4913808a299` in
[PR #19](https://github.com/midhatn/adaptive-inference/pull/19), which merged with
the exact tested tree. The final source archive verified 694 files; the live
wheel and all 52 runtime modules were unchanged by this fixture repair.

Keep the ordinary host's lifetime independent of that task's deadline and the
qualification supervisor's emergency bound. After verified task completion it
can remain parked until an actual Stop. Preserve bounded task/qualification
checks and truthful unresolved-cleanup reporting. Each changed deployment must
earn its own relevant acceptance; the installed reference result does not
transfer automatically to different imports, launch paths or control behavior.
The first report still has its original 900-second task budget. The predecessor
recovery contract treated pending expiry as failure. The later
[paused-expiry qualification](provenance/paused-budget-expiry/acceptance/README.md)
accepts only an already verified safe Pause: the original budget is sealed, saved
work remains pending, and the controller stays available until Stop. Active or
uncertain expiry still fails. Explicit continuation and ordinary task use require
their own gates before the complete always-on M2 experience can be claimed.

Independent composition tests completed both simulated cases, then exposed a
watchdog defect: a failed diagnostic write could prevent the emergency exit.
The corrected runner now makes termination independent of reporting, stays armed
through final teardown and refuses a truncated event ledger. Both the corrected
runner and its successor composition passed independent CPU review. These are
qualification-harness fixes; passing simulated cases cannot replace the separate
native/IQ3_S acceptance gate.

Control-interface review also reproduced two defects before integration: a
historical Resume request could revive intent after a later Pause, and cancellation
before a connection handler's first instruction could abandon its stream. Reuse
the existing durable mailbox as command authority and retain accepted connection
cleanup independently of handler execution. Preserve both failures and qualify
the actual mailbox adapter before trusting fake-runtime component results.

For the original conservative UI path, use the existing local launch/control
and standard window facilities. Bind explicit intent to the project's exact owned window and one
authenticated runner/task. Remove only its own recent-input block; keep CPU,
memory, observation and native-ownership checks. Do not exempt a whole browser.
Fresh window/session verification is separate from task-lifetime intent, so a
long valid request does not silently lose priority to an unrelated short timer.
Closing the interface preserves the task and host. The implementation and live
window-switch/reopen checks remain required before claiming this experience.

Timing review also found that a static backend revision can retain speed
estimates across a replacement owner's different cache configuration. Reuse
the existing learner with a runtime context established before admission.
Capture the actual execution's learner after admission; an old completion must
not train the replacement. Preserve existing queued arrival/rank accounting
and distinguish its arrival prediction from the eventual execution context.
This is runtime bookkeeping, not a new statistical scheduling algorithm.

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

The named end-to-end media gate is the
[Adaptive-Hermes-Media-Autonomous Test](docs/adaptive-hermes-media-autonomous-test.md).
It preserves the autonomous Hermes supervisor/worker, IQ3_S, Turbo Q8_0 reference,
H3 Ref2VA Q8 video, verified cleanup and independent output-review requirements
from the retained media experiment. Its two-image/two-video/four-worker and
four-hour bounds are separate from the smaller M2 examples. This canonical
integration is planned, not passed. Preserve bounded self-correction, but do not
manually steer the agent through a running attempt to produce a success.

At that milestone's preflight, apply the newest stable supported version
requirement to the **entire participating software stack**: Adaptive Inference,
every engine and agent, orchestration/delegation plugins, custom nodes, tool
servers, runtimes and resolved dependencies, benchmark/quality tools, and the
supported host/driver environment. Strata 0.2.6 is only a minimum; any alternative
engine or agent actually used follows the same test-time rule. Record official
sources, check dates, chosen and available versions, exact identities and any
compatibility exceptions. An older component cannot silently count as an
all-latest result. Freeze the resolved versions for comparable tuning and the
attempt while keeping the same IQ3_S, Turbo Q8_0 and H3 model assets. Recheck before
the final attempt and requalify affected checks if a newer release is adopted;
historical pinned replays remain explicitly labeled reproductions.
Compare ancestry first: retain and explicitly identify a verified newer upstream
revision when needed for required adapter capabilities, rather than silently
downgrading it to an older release tag.
Qualify each engine first, then co-optimize the **complete autonomous workflow
without Adaptive Inference** before freezing and qualifying its unattended
baseline. Introduce and tune the adaptive variant only afterward, with separate
development runs. Compare frozen variants under matched conditions and unchanged
quality, including a restored baseline control and independently reviewed results.
Neither Codex nor the user may coach, repair or manually hand resources between
engines during a measured attempt; intervention disqualifies an autonomous pass.
An absent or failed autonomous reference cannot support a comparative improvement
claim. Include separate checks of visual/audio realism and sound/video
synchronization. The named test documents the baseline, comparison, measurement
and rollback requirements. Assess Hermes's official
advanced-delegation provider for reusable profile routing instead of adding a
new router; every test route must retain the same local IQ3_S contract and the
existing resource, lifecycle and sequential-worker requirements.

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
Include the named autonomous media test, then separately declared foreground
activity and restart variants of that workflow. A quiet successful render alone
does not demonstrate the combined always-on requirement.
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

The [cache-state assessment](docs/cache-state-research.md) adds a concrete
efficiency path from the user-supplied Gandalf and cross-model KV papers:

- First qualify same-model session save/restore through the existing native
  Strata API after the current Continue saved task flow. Reuse the retained
  implementation; do not build another file format or recovery store.
- Keep optional native cache separate from durable task/effect authority.
  Bind complete hybrid state to one prefix and exact runtime/model identity;
  a missing or refused cache falls back to a clean re-prefill without replaying
  tools or resetting budgets. Saved bytes do not promise identical future tokens.
- Measure total resume cost, foreground delay and actual host/device writes
  before comparing RAM retention, whole-session files and type-aware admission.
  Gandalf informs placement criteria; no SSD-endurance multiplier is claimed here.
- Treat cross-model mapping as an unenabled research lane. Dense-model results
  do not validate the hybrid IQ3_S baseline. Reuse existing implementations only
  after a compatible, separately authorized model-pair evaluation; do not change
  the current model merely to demonstrate a speedup.
- Evaluate [AKV's agent-directed cache operations](docs/cache-state-research.md#akv-agent-directed-cache-operations)
  only through an explicitly capable backend. Preserve cache-operation history
  as well as conversation history, measure actual released memory and task
  quality, and retain the full-workflow baseline. Its current model support does
  not qualify our hybrid IQ3_S stack; no cache operation is enabled by this plan.

These are adopted requirements and acceptance steps, not enabled runtime
capabilities. They do not block M2 or weaken its recovery and cleanup gates.

The [precision assessment](docs/precision-research.md) identifies mixed precision
already present in the retained engine and the existing optional
`STRATA_PF_WMMA=1` expert-prompt path. After continuation qualification, evaluate
it on the same IQ3_S assets using control, candidate and restored-control runs,
verified native-child configuration and actual kernel dispatch. Keep task
validators and reasoning/output allowances intact; measure complete task time,
foreground response and resource cost. The reported GPU unlock changes the
performance environment, so record that identity separately and do not infer
an application gain from dense matrix rates or compare old/new timings as a
scheduler-only change. No precision setting is enabled by this plan.

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

Preserve the published M1 source and evidence while developing its successor.
Require fresh distribution checks and CI for each changed submitted revision.
Keep the accepted native composition separate from any upstream target whose
proposed change has not been tested.

The active technical packet is M2:

**Current gate, 26 October:** **Continue saved task** passed the complete installed
Windows/Hermes/Strata IQ3_S trial and its independent 70-check terminal audit.
The original 900-second allowance expired naturally after a genuine Pause. One
Continue click in the same window selected a fresh execution and resumed the
original objective without a second Resume. The task completed with three
cumulative model requests and one physical report write; the sealed predecessor,
report and existing history stayed unchanged. One normal Stop joined the retained
workers, native engine and window and closed the service controls. See the
[continuation evidence](provenance/explicit-continuation/acceptance/README.md).
Preserve the earlier 46-check paused-expiry acceptance and both failed expiry
predecessors as separate historical results.

Publication feedback: Python 3.12 represents unchanged function syntax with an
additional empty field. Reuse the existing narrow source-preservation comparison
in standalone workflows, retain historical hashes, and check both supported
Python versions before publication; this repair does not change runtime behavior.
One hosted Windows fixture also exceeded its combined startup/work wait. Give
fixture imports their own bounded readiness handshake and register retained
cleanup before setup can fail; keep the existing work guard and product budgets.

**Next functional M2 gate:** accept a different user task in the same retained
host, with explicit task identity, isolated task/effect records and clear completed,
waiting and stopped states. The session research is now recorded in the
[task contract](docs/task-spec.md). Reuse TaskStore and the pinned Hermes adapter.
The first implementation slice removes the fixed orders objective: an explicit
TaskSpec supplies the prompt, pinned inputs, create-only outputs, checks and
supported budget. The ordinary desktop entry accepts this specification while
retaining the original example for compatibility. Contract and CPU fixture
checks do not qualify a new installed task or complete this milestone.

Next, wire durable new-task admission into the retained host, keeping each
task's records and completed effects separate. Reuse the existing private GUI
bootstrap for a fresh task view; do not weaken session identity to claim the
same window. Qualify two distinct useful tasks without restarting the host or
confusing old controls with the new objective. The examples must remain
qualification cases for the generic contract, not a hardcoded task menu.
Reboot recovery remains M5.

**Retained-host implementation feedback:** preserve a separate control binding
for each task and overlap the old and new windows until the new one is ready.
Retiring a task view must not invoke whole-service Stop or let a late old-window
callback revoke the new task's intent. Reuse the existing private bootstrap and
one shared cleanup owner for all retained task lifetimes. Keep preparation and
readiness waits outside the control-command serial section so Status and Stop
remain available. A Stop closes the host lifetime while leaving a known pending
task saved; it must not manufacture task cancellation.

The first admission review found a race when the continuation authority did not
yet exist: locking only an existing row allowed a first Continue authorization
to appear during handover. Lock the authority's deterministic identity before
checking for the row, followed by the selected execution lock. The original
failure and unchanged regression are retained; the corrected component passes
the review. A separate Windows Python 3.12 failure showed that a response timeout
can coincide with a completed operation failure. Recheck the retained operation
before returning a pending grant, without cancelling it or enlarging the timeout.
Neither repair changes the installed-evidence boundary. Next qualify ordinary
A-to-B tasks, continued-A-to-B, a late old-window close and Stop during preparation
with the same host/gateway identity, followed by the real IQ3_S two-task gate.

Independent review also found that exceptional cleanup could keep retrying an
old window's uncertain handle closure before requesting Stop for a later task.
Retain the failure case. Start each retained task's independent cleanup before
waiting for any one uncertain sibling, using the existing owned asynchronous
operations. Each task must progress through its own worker, window and endpoint
cleanup; an unresolved old handle must remain unresolved without preventing
other tasks from stopping. Require the unchanged reproducer to pass before the
candidate advances, and rerun the complete source checks after that repair.

Installation review found two additional imports used by the new task chooser.
Extend the existing child-source pins and import-origin checks to those modules
before the installed trial. A complete host package inventory does not replace
the GUI child's own launch checks. Preserve the accepted installation and test
the candidate in separate full interpreter copies with the same native profile.

**Installed preparation and first trial, 26 October:** both isolated installations
match the reviewed 60-module wheel. The installed SDK's three dispatch checks and
three shared-clock comparisons pass with the unchanged IQ3_S profile. The first
real GUI trial remained paused behind a Windows Security permission dialog.
No Resume or model request occurred. Its original 900-second worker allowance
expired with the task saved; the dialog also intercepted the attempted Stop input.
The runner and observer were then forcibly stopped, and the retained processes
were joined. This is an interrupted, unaccepted trial, not normal GUI shutdown
or two-task handover evidence. An independent interruption audit found no task
effects and verified that the accepted and isolated installation files remained
unchanged.

Before another trial, resolve the first-run OS dialog for the same isolated test
installation and confirm that its controls are usable. Reuse that installation
only after its existing identity checks, then start a fresh case with the original
budgets. Do not renew an expired execution, rewrite the interrupted result, or
infer public-network permission from successful local status requests. Microsoft's
[firewall rule guidance](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)
describes the first-use prompt and the different consequences of allowing or
cancelling it. Handling the dialog is an installation prerequisite; it does not
change the model, task contract or acceptance gate.

**Verifier feedback from the fresh trial:** after the operator handled the OS
dialog, the same installed runtime completed the inventory worker's three model
requests and produced the expected 23-unit result. The qualification nevertheless
stopped before the second task because its prompt fingerprint comparison used
raw UTF-8 bytes, while the existing worker records the hash of a JSON-encoded
string. The worker's recorded value matches its existing serialization contract.
Python's [JSON documentation](https://docs.python.org/3/library/json.html) explains
the string encoding; the installed worker and retained source are authoritative
for the exact representation used here.

Correct the verifier to use that existing representation, retaining strict
prompt, metadata, session and quality comparisons. Add a regression against the
actual worker's formatter and reject the former raw-text fingerprint and changed
prompts. Preserve the original verifier and failed trial. A corrected replay can
explain this failure, but cannot turn it into a two-task success: the next case
must still perform both real tasks and normal GUI Stop. The runtime, model,
installation and time allowances do not need to change for this verifier repair.

The following fresh trial passed the inventory check and opened the second task,
but stopped before its Resume on another verifier assumption. The native Windows
folder picker returned the intended input directory with forward slashes; the
verifier expected backslashes. Independent inspection confirmed the same resolved
directory and filesystem identity, unchanged task file/hash and input contents,
and preserved task A. Task B made no model requests before failure cleanup.

Use the existing [pathlib path and filesystem identity semantics](https://docs.python.org/3.11/library/pathlib.html)
for this folder comparison. Preserve the exact selected source payload used by
the command, and retain exact task-file/hash checks. Exercise the actual picker
representation and reject a different directory, altered specification or changed
source fields. Share the source check between live qualification and terminal
replay. Preserve this failed attempt and require another complete real two-task
run; neither the correction nor successful preparation of B proves its completion.

The next actual IQ3_S attempt exposed the documented file-alias limitation. Its
first model response requested the correct inventory input using its absolute
Windows path. The adapter required the exact relative basename, refused the
read, and recorded no tool receipt or output. The task therefore failed its
completion check, and the unresolved native tool continuation prevented a clean
product Stop claim. Preserve this failed attempt; repeating it until the model
chooses a different spelling would not resolve the adapter mismatch.

Before the next installed trial, reuse the pinned
[Hermes file-tool path contract](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/file_tools.py)
and Python's existing path resolution to recognize an allowed file consistently
across dispatch, validation, completion and recovery. Keep the exact original
tool arguments in native history and intent verification. A basename, relative
alias or absolute path may denote the same declared workspace file; a matching
basename outside that workspace must not authorize access. Test original-intent
preservation, write deduplication, completion and refusal boundaries through the
existing adapter before rebuilding and qualifying the changed installation.
The Stop and task-acceptance checks remain unchanged.

The documentation-only PR refresh also exposed an independent Windows CI
cleanup defect: three jobs printed a continuation-test error, then stalled in
asynchronous teardown before their original error tracebacks could be reported.
Eleven checks passed; the cancelled jobs remain incomplete evidence. A bounded
CPU-child reproduction shows that a test-side restore callback can wait forever
after an error before Resume when teardown does not fence admission. Fix the
fixture cleanup so the callback exits and retained resources are joined while
the original test error is still reported. Keep the existing CI time limit and
product Stop requirements. The original hosted error remains unknown until a
fresh run can report it; successful cleanup alone does not resolve that error.

The file-alias repair is now integrated at the source level. Independent checks
on Python 3.11 and 3.12 passed all 65 task-contract/recovery cases, including
real SQLite receipts, exact original intent, equivalent paths, deduplicated
writes and refusal of paths outside the declared workspace. The seven independent
regressions are included in the ordinary public test suite. The fixture cleanup
repair separately passed 30 relevant tests on each interpreter and independent
error-preservation checks: retained CPU children exit, logs close, and the
original injected error remains visible. These component results do not establish
installed task completion or resolve the unknown primary error in cancelled CI.
The integrated Windows Python 3.11.9 run passed all 1,110 source tests and 81
provenance tests with unchanged source hashes and no skips. Rebuild and check
the distribution, and obtain fresh exact-head CI. Then install and verify the changed package,
prepare fresh task identities, and repeat the complete two-task IQ3_S workflow
using the reviewed logical-write/physical-effect verifier. Preserve the original
failed trials and their source identities; normal Stop remains a required gate.

Fresh CI at `232519048fe81371c383840b7933482cae681931` completed with ten
successes and four Windows failures. All Windows jobs exposed an assumption in
the added native-path comparison: the runner's temporary directory used a short
Windows name while the adapter resolved the full name. Inspection confirmed that
the actual worker resolves its run directory before supplying the agent's working
directory; the test now uses that exact resolved working directory. An actual
Windows short-name reproduction produced the original six failures and four
errors on Python 3.11.9 and 3.12.9, then all seven corrected tests passed on each.
The product source and access rules remain unchanged. One Python 3.12 job also
reported failure to observe a continuation Resume
acknowledgement. That exception can mean a worker exit or an elapsed deadline;
the log alone cannot distinguish them. The cleanup correction let the original
traceback appear and the job finish, but does not resolve that underlying cause.
Retain the existing CPU fixture's child receipts in CI so the next occurrence
reports actual exit, join and forced-cleanup information. Reuse GitHub's pinned
[artifact upload action](https://github.com/actions/upload-artifact/blob/ea165f8d65b6e75b540449e92b4886f43607fa02/action.yml)
and documented [post-failure step condition](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#always),
without extending any product deadline, child watchdog or job time limit.
Three bounded local replays of the exact continuation test passed on Python
3.12.9, with six retained CPU children joined normally and no forced cleanup.
That does not explain the hosted error. Keep it open for diagnostic evidence
instead of changing the runtime or increasing waits without a reproduced cause.

The corrected-path head `c1044ed42158182382576597892dae6da3d9d8f9` then passed
13 hosted checks; the remaining Windows Python 3.12 job reproduced the same
continuation error. The new artifact records the original child exiting with
code 5 and the selected child with code 1, both joined without forced cleanup.
The selected child ran for roughly half a second, ruling out its 15-second
emergency watchdog in that occurrence. The merged child output was still removed
with the temporary fixture directory. The existing optional receipt hook now
retains up to 64 KiB of that output after the child is joined and its stream is
closed. Six diagnostic regressions and the unchanged affected child test passed
on Python 3.11 and 3.12; 13 source-preservation checks also passed on both.
Independent review confirmed the bounded capture and unchanged runtime. All
assertions and time limits remain in place. Keep the installed model trial on
hold until the remaining failure is understood.

A deterministic SQLite probe also found a separate actionable control race:
Resume can be recorded between the worker consuming Pause and reading its expiry
observation. The observation then raises `ControlBlocked`, leaving a legitimate
Resume pending. The diagnostic head `144a980d223d49bc5389a47d8ecec497d4ddeebd`
finished with 13 successes and one Windows Python 3.11 failure. Its complete
1,886-byte child traceback now shows that same `Controls.poll` →
`paused_execution_observation` → `_paused_execution` failure. Both children
joined normally, with exits 5 and 1; no watchdog or forced cleanup caused it.
The earlier c104 run still lacks its original exception text.
The repair now uses the existing control loop to recheck a validated pending
command, while keeping malformed state, ownership checks and atomic expiry
sealing strict. The design follows SQLite's
[snapshot isolation](https://www.sqlite.org/isolation.html) and the existing
wait-loop pattern described in Python's
[condition-variable guidance](https://docs.python.org/3.12/library/threading.html#condition-objects).
The 83 targeted tests pass on both Python 3.11 and 3.12. Independent review
repeated those tests and added two real-SQLite checks of the actual activity
callback: no false activity stamp and no progress with interrupted authority.
Both interpreters passed all 85 checks, with no skips. The two runtime modules
and three changed methods are isolated; strict sealing is unchanged. All 60
source-preservation checks also passed, with independent review. All 1,143
combined source tests and all 81 provenance tests then passed on Windows Python
3.11.9, with unchanged source bytes during both runs. Build and install a new
wheel before the fresh IQ3_S trial. The prior installed wheel does not contain
this repair.

The first public reproduction prerequisite is now implemented in the existing
distribution checker: `--output` writes a wheel-derived installed identity after
complete module/RECORD/name/version and existing source/license checks. Eight
archive/CLI regressions passed on Python 3.11 and 3.12, including the metadata
version mismatch found in independent review. The existing release wheel also
produced exactly the previously reviewed 60-module installation identity. This
closes identity generation for the public installed SDK command; it does not
complete the other deployment receipts or retroactively establish build-time
source stability. See [reproduction instructions](docs/reproducing.md#expected-identity-for-installed-checks).

**26 October ordinary-task trial feedback:** the repaired wheel passed isolated
installation checks, but the next real IQ3_S trial exhausted the original
900-second inventory budget before a second task could be selected. One model
request and one input read completed; no output was written. Foreground activity
kept the engine parked for most sampled observations. The worker then reported
an active control-wait deadline, which had no verified safe-expiry receipt in that
installed lifecycle. The host correctly refused to call that a cooperative product
stop, although the native owner independently confirmed release of all nine
retained processes. Preserve this failed run and its missing acknowledgement;
neither a clean OS process list nor intact saved state replaces the required
worker receipt. See the [bounded failure evidence](docs/evidence.md#ordinary-task-handover-development).

The [safe-wait repair](docs/admission-wait-recovery.md) is now implemented and
independently checked at the source/component boundary. It reuses the checkpoint,
resource-close and execution-seal mechanisms for a distinct expiry outcome. Two
deadline crossings before dispatch carry an explicit expiry type; failures after
an operation begins retain their reconciliation requirement. Explicit Continue
preserves the old pending request and records its supersession before the pinned
SDK rebuilds from saved conversation. Request and effect limits remain cumulative.

The assembled Windows source, provenance and package gates passed. Hosted
Linux/macOS checks then exposed a test-clock mismatch: the simulated expiry used
900 seconds while receipt verification read the host's unrelated performance
counter. The fixture now carries its simulated clock through verification;
the runtime still rejects future seals and nonfinite observations. The affected
34 tests pass on Python 3.11/3.12, including explicit invalid-clock cases.
The next hosted Windows run exposed an unreadable CPU-fixture readiness marker
in setup. The [bounded observation correction](provenance/task-handover/fixture-readiness/README.md)
handles transient missing/denied reads without changing the same-child identity,
startup deadline or work guard. Fifty focused Python 3.12 source/actual-child
checks passed. A subsequent hosted run caught an omitted historical test-reader
dependency; the explicit three-file support projection now preserves those
assertions too, and all 69 lineage/readiness checks pass. Exact-head hosted CI
remains a separate gate. Neither fixture
correction changes runtime modules, installed deadlines or previous results.

At `9308707`, 13 hosted jobs passed and one Windows Python 3.12 source check
failed while awaiting the selected worker's initial acknowledgement. Unlike the
earlier fixture corrections, this path uses the product's actual observation
lifetime. A successful read can arrive too late to be usable. A deterministic
CPU-worker/SQLite reproduction aged one valid read and reproduced the permanent
fault; the hosted log itself does not establish which timestamp check failed.
The [narrow acknowledgement-read correction](docs/admission-wait-recovery.md#delayed-acknowledgement-observations)
discards only expired valid reads within the same worker lifetime and execution
deadline. It preserves prior cache/intent without renewing either, and keeps
malformed records, changed identity, database failures, ordinary refresh and
post-write checks strict. This runtime change requires fresh source/package and
installation validation before the IQ3_S trial; the prior installed wheel cannot
serve as evidence for the correction.

The fresh isolated package installation has now passed both import audits,
the installed SDK dispatcher, shared-clock checks and resource-input audit;
all seven installation steps joined successfully and passed independent review.
The recovery harness also passed independent component review: 38 supplied and
three additional actual-SQLite cases. Keep these preparation results separate
from real IQ3_S task acceptance. Confirm the corrected hosted checks before the
fresh task trial, retaining the same model and quality.
**Next installed trial, 26 October:** all 14 hosted checks passed on
`5fd3d7a66590effa3b85d6bcf0d02c6b8f9b0c8c`; retain the earlier whole-job timeout
and its successful retry separately. The fresh IQ3_S trial completed its first
model request, then failed native release after real foreground activity closed
admission. Windows denied a termination call on a retained process handle. The
owner recorded six retained processes but only five confirmed exits, so the
adapter correctly refused release even though its final active-process list was
empty. The worker saved its pending request and acknowledged service Stop; it did
not produce the distinct safe-expiry outcome or complete the task. The host
remained in its terminal retention-failure loop. An explicit external emergency
termination ended that exact runner, and its original supervisor observed runner
exit 125.
This is emergency containment of a failed run, not normal Stop or installed
acceptance. Preserve
the failed case, its unchanged package/native sources and the separate external
termination receipt.

The next repair belongs in the existing native retained-handle termination path.
[Microsoft documents](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)
asynchronous termination and access denied for an already terminated process;
[CPython checks that same retained handle](https://github.com/python/cpython/blob/v3.11.9/Lib/multiprocessing/popen_spawn_win32.py)
before treating a denial as completed exit. Reuse the owner's existing bounded
exit wait, capped by its remaining cleanup deadline, only for this documented
denial. Require a positive exit signal and the normal collection pass to account
for every retained process. Preserve the original error on a live process,
timeout or failed wait; do not reopen a PID, broaden access rights, or weaken the
adapter's release/parking predicates. The failed receipt supports this race as
a diagnosis to test; it does not establish the exact kernel timing. Require a
deterministic predecessor-fails/successor-passes regression, negative cases and
independent review before a separately identified deployment and fresh trial.

The narrow source repair has now passed that component gate: 30 checks on each
of Python 3.11 and 3.12, two additional independent deadline/release-proof checks,
and an owned Windows CPU-child probe using actual retained handles and waits.
Only termination denial and release coordination were injected in that probe;
it does not reproduce a spontaneous kernel race. The original source fails the
same deterministic regression. The corrected source preserves six-of-six exit
accounting, while a live denial remains failed. The next step is a fresh sealed
native-owner package and relevant input/clock verification, retaining the
unchanged installed wheel and quality, followed by the complete IQ3_S scenario.
The failed case07 and the earlier qualified packages remain immutable.

Exercise ordinary-task waiting, truthful expiry, explicit continuation and Stop,
with separate original-task acceptance before a second task can be admitted.
Do not extend a budget silently, accept uncertain effects or reuse old installed
receipts for the new package. Preserve the failed run, earlier paused-expiry
acceptance and all source identities. Separately, M3 must qualify useful progress
during light foreground work; merely parking correctly does not establish
everyday coexistence.

**Next bounded efficiency experiment:** after publishing this accepted baseline,
evaluate the existing FP16 expert-prompt path using the
[precision comparison](docs/precision-research.md#reversible-qualification).
Use unchanged control, candidate and restored control on the same IQ3_S assets,
verify actual dispatch and compare correct completed tasks and resource use.
The reported GPU unlock is a changed environment, not a measured application
speedup. Keep one owner of heavy model experiments and retain an ineffective or
slower result. No precision setting has been enabled by the continuation trial.
The first instrumented startup failed before native launch; an OS permission
prompt also obstructed the later unprofiled control. The original worker expired
while paused and the unchanged outer diagnostic limit eventually terminated the
host. Both unsuccessful runs remain failures. No FP16 dispatch, quality or speed
claim follows from them. Resolve the capture environment and use a narrower
trace only after validating its existing stdin/cleanup contract; this optional
experiment does not displace functional M2 work.

The continuation implementation reuses the existing TaskStore, installed adapter
and retained lifecycle; it does not reopen the sealed execution or reset the
cumulative request allowance. The researched identity and transition references are
[Temporal Continue-As-New](https://docs.temporal.io/develop/python/workflows/continue-as-new)
and [LangGraph durable interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).
The implementation feedback below records why those existing transaction and
effect-identity mechanisms needed the final inherited-state and lifecycle checks.

**Continuation implementation feedback:** the current ownership lock protects a
single stored execution ID. Different executions of the same task would otherwise
have different locks while sharing one Hermes session and report destination.
Reuse a separate logical-task authority claim, then the selected execution claim,
with one documented lock order. Create and select the successor in one existing
SQLite write transaction. Read the sealed predecessor without claiming it:
claiming a pending task itself appends history. Preserve its complete state and
history, and return the original grant on a matching retry even while the new
worker owns the authority. Carry forward cumulative requests, attempts, admission
accounting and the verified prefix of the shared request ledger. A storage-only
prototype is an implementation step, not a usable continuation result.

The first private storage prototype passed its supplied tests, but independent
second-extension checks found that a new valid expiry seal could hide a changed
inherited request entry or a changed earlier deadline. Hold that prototype and
preserve the failing cases. Reuse one inherited-grant validator at both worker
claim and every later authorization: validate the original selected deadline,
creation record, preserved history/counters and request-ledger prefix. A valid
new seal does not replace these earlier obligations. Require the original cases
to fail against the predecessor and pass against the repair before integration.
The narrow repair passed the same two independent failure cases and supplied
storage tests, including legitimate second extensions and later request-ledger
growth. That component result preceded the worker, host and UI gates; the complete
installed qualification above now covers the first explicit continuation.

Keep the task, window and authenticated UI session stable, with a separate selected
execution ID and increasing execution generation. Delayed commands and status from
an earlier generation must not affect or replace the current one. Stop remains
available across that transition. One explicit **Continue saved task** click should
grant the new finite execution budget and request its Resume through the existing
fresh Pause/acknowledgement bootstrap; it should not require a second click in the
successful path. Retain the launch immediately, honor Stop or lost user intent at
every transition, and distinguish a selected grant from readiness or task
completion. The complete installed IQ3_S workflow above qualifies this one
continuation; keep the earlier expiry acceptance independently reproducible.

**Final integration feedback:** a late successful status read from the retired
execution must not replace the newly selected execution. Genuine read failures
still surface. Retain process waits by the actual child object, not a reusable
process number. The assembled source passed 954 tests; exact installed origins,
the actual SDK dispatcher and both interpreters' shared clock were checked before
the real run. The external status observer ended with three connection errors
after shutdown (1,147 valid observations of 1,150); direct task, retained-process
and resource evidence established completion and cleanup. Do not reinterpret
connection loss as successful shutdown or add overlapping test counts together.

**25 October live expiry feedback:** the first installed expiry trial failed after
the worker returned its distinct expiry outcome. The host correctly rejected a
seal timestamp that appeared to be in its future. Independent inspection found
the same saved deadline throughout, but the installed Python 3.11 host used
`GetTickCount64` for `monotonic()` while the Python 3.14 worker used
`QueryPerformanceCounter`; their readings differed by about eight seconds.
The report and native conversation survived, but there was no accepted expiry
display or manual Stop. Preserve that failed run and its original package identity.
Before another trial, use one explicit, documented same-machine clock for every
shared execution deadline and seal comparison, and check compatibility in the
actual installed interpreters. Python documents the system-wide
[performance counter](https://docs.python.org/3.11/library/time.html#time.perf_counter)
and its [newer implementation](https://docs.python.org/3.14/library/time.html#time.perf_counter).
Do not compensate with a tolerance, reinterpret an old checkpoint silently, or
weaken the future-timestamp check. The same run also exposed the pinned agent's
600-second inactivity watchdog during an intentional Pause; address that distinct
wait-versus-stall interaction using the existing SDK mechanism before accepting
the longer paused experience. Neither observation changes the original quality,
request budget or complete installed acceptance gate.

**Follow-up installed feedback:** the shared-clock source and installed interpreter
checks passed, but the next real-model trial stopped before writing its report.
The new wait guard incorrectly equated task ownership with the thread that
constructed the guard. The [pinned Hermes sequential tool path](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/tool_executor.py)
dispatches through its existing worker pool, so a legitimate tool safe point arrived on another
thread. Preserve this second failed trial. Before repeating the full scenario,
exercise the actual pinned SDK dispatch path with the adapter's existing owned
task and serialized safe-point contract. Correct the ownership check without
adding an executor, allowing concurrent checkpoint mutation, or weakening lease
and interruption checks. A component fixture that calls the middleware only on
the constructor thread does not cover this integration boundary. Reuse the
adapter's existing `Recovery` lock and the SDK's context-preserving executor;
[Python futures](https://docs.python.org/3.14/library/concurrent.futures.html)
already provide the required result and exception handoff.

The actual pinned sequential dispatcher now reproduces the rejected-thread
failure with a real task-store claim before any tool effect. That regression
becomes the repair's positive gate: the same path must perform the allowed read
and write exactly once under the original logical owner. Research also found
that a tool timeout can return while its daemon callback is still running;
`Future.cancel()` is not a callback join. Honor Hermes's existing
[worker interruption signal](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/interrupt.py)
even when the agent's own interruption flags remain false. Serialize safe-point
checks and final cleanup with the same existing lock, revoke late callbacks,
and refuse a successful seal while callback completion is unresolved. Require
an event-controlled timeout test and a concurrent-finalization test through the
real SDK dispatcher before another installed trial. These are component gates;
they do not replace the original full IQ3_S acceptance workflow.

The five-module correction has now passed focused source checks on Python 3.11
and 3.12, independent cleanup review, and the actual pinned SDK dispatcher checks
on the deployed Python 3.14 interpreter. The same
[reproducible dispatcher example](examples/validation/hermes_pause_dispatch/README.md)
is included here with explicit source and installed modes. The subsequent ordinary
package passed that dispatcher check with verified installed origins, then the
complete expiry trial passed the independent terminal audit recorded above. Fresh
clock observations and resource checks were taken after the computer restart;
previous absolute timer readings were not reused. This same-boot qualification
does not establish continuation across a reboot.

- Preserve the now-qualified installed host/GUI/backend composition and its
  unchanged IQ3_S quality as the reference. Continue in that implementation;
  do not create another runner or repeat completed source-promotion work. Its
  cross-platform fixture repairs and exact-head CI passed in PR #18; keep the
  historical runtime/evidence identities separate from each successor.
- Preserve the accepted [retained-command change](docs/desktop-control-intent.md):
  one locally waiting intent, serialized dispatch, stable request identities,
  fresh eligibility and truthful queued/recorded/unknown states. Its cold/full
  trials and deterministic status-ordering tests have passed separately. Keep
  those boundaries when adding new task outcomes; do not repeat completed input
  work or transfer its evidence to a changed implementation without validation.
- Preserve the accepted safe budget-expiry outcome at an already verified paused checkpoint.
  Preserve the pending task, effects, history and original deadline. Verify the
  applied Pause observed before the deadline and its complete request/acknowledgement
  prefix, seal that execution,
  release ownership and join the retained worker. Verify final native history
  after cleanup and queued writes; a normal cleanup return alone is insufficient.
  Keep ownership through that cleanup and verify the final conversation through
  the same pinned agent SDK after its original database closes. Reject unknown
  drain or a still-running writer; do not claim billing persistence from this
  task-history check. Serialize the execution seal and new control append using
  the existing [SQLite write transaction](https://www.sqlite.org/lang_transaction.html):
  check the full request/acknowledgement prefix in the seal transaction and
  recheck the seal in the append transaction. A host-only lock or earlier
  snapshot cannot fence another process. A command already committed remains
  visible; a new command refused before append receives a distinct known
  non-recorded outcome. Preserve truthful same-ID lookup and reject a sealed
  execution before worker claim or replacement launch.
  Reuse paused demand and ordinary idle release to park resources while keeping
  the service available; the whole-service Stop fence is unsuitable here.
  Unknown effects or exits remain failures. Reuse the distinction between
  [overall execution and attempt timeouts](https://docs.temporal.io/encyclopedia/detecting-activity-failures)
  and [durable interruption with protected effects](https://docs.langchain.com/oss/python/langgraph/interrupts).
  Expiry must not be mislabeled completion or attempt exhaustion. Qualify the
  installed IQ3_S report at a safe Pause through its original 900-second deadline,
  with no renewed budget or repeated write, then a genuine Stop. Fake-clock
  fixtures remain component evidence. Post-expiry new budgets and task mutations
  require their own explicit continuation contract.
- Design explicit continuation after expiry and acceptance of another task in
  the same host using the existing task store and identity contracts. Do not
  renew a spent execution budget silently. Preserve user intent and completed
  work, and keep resource waiting outside active provider requests.
- Qualify cold idle, demand arrival, cancellation, active-request boundaries,
  interrupted startup, longer service use and bounded storage. Broader pressure
  and foreign-application switching remain separate outstanding gates; the
  owned-window result does not establish those workloads. Reuse the native
  cache planner while distinguishing unknown data, insufficient capacity and
  unresolved ownership; a cache proposal is not a reservation.
- Independently review changes, run the relevant actual IQ3_S qualification,
  preserve failures and revise this packet from the observations. Publish only
  accepted scope, with exact-head CI and reproducible source/distribution checks.

Broader M3/M4 desktop and tool qualification follows the persistent composition; physical
restart recovery remains M5. The first release can be useful before every later
milestone is finished, with its established experience stated precisely.
