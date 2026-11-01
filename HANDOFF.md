# Continue Adaptive Inference

This is the shared continuation entry point for a new human or AI contributor.
Read [AGENTS.md](AGENTS.md) first. The repository, its retained evidence and current
Git state are authoritative; no previous conversation or particular AI provider
is required to understand the intended work.

**Snapshot date: 1 November 2026.** Recheck branch heads, PRs, task ownership and
the actual machine before acting. This file does not reserve hardware or assert
that a previously recorded process is still running.

## The outcome we are building

A person starts an agent and continues using their computer for browsing, games,
video and ordinary work. The agent yields CPU, RAM, GPU and VRAM when the person
needs them. It also makes room for its own compiler, media tools or another
supported engine, then continues the original task. Completed work and task
intent survive interruptions and eventually application and computer restarts.
The large model may unload while the lightweight controller and durable task
state remain available. Shared hardware still has finite capacity.

Build a functional reference system first, then improve speed and expand
supported engines and agents. Research existing implementations before inventing
a new mechanism. Preserve the user's original objective, IQ3_S quality baseline,
citations and unsuccessful evidence. The full milestone sequence is in
[PLAN.md](PLAN.md); acceptance standards are not reduced when an experiment fails.

## Read only what the next decision needs

| Question | Authoritative starting point |
| --- | --- |
| What is the goal and milestone order? | [Roadmap](PLAN.md), [always-on vision](docs/always-on-controller.md) |
| What implementation is actually available? | [README](README.md), current checkout and [architecture](docs/architecture.md) |
| What has been demonstrated, and at what scope? | [Evidence ledger](docs/evidence.md) and its source-bound receipts |
| What is portable versus native or application-specific? | [Integration contract](docs/integration-contract.md), [compatibility matrix](docs/integrations.md) |
| How can sources and tests be reproduced? | [Reproduction guide](docs/reproducing.md), [source preservation](docs/source-of-truth.md) |
| Which earlier ideas were inspected or reused? | [Research](docs/research.md), [bibliography](REFERENCES.bib), [NOTICE](NOTICE) |
| What belongs in a particular upstream PR? | [Delivery ledger](docs/upstream-delivery.md), [PR index](docs/upstream-prs.md) |
| How should multiple contributors share the work? | [Collaboration workflow](docs/multi-agent-collaboration.md), [task template](.github/ISSUE_TEMPLATE/agent_task.md) |

## Current continuation state

| Item | Dated state and verification boundary |
| --- | --- |
| Stable main starting point | Commit `c348398089e544bf54add2beaaf73550f8951efc`, including merged PRs #25, #26, #28, #29 and #30. Verify current `main`; this is a dated anchor, not a claim that it remains HEAD. |
| Released reference and active work | [v0.4.0a1](https://github.com/midhatn/adaptive-inference/releases/tag/v0.4.0a1) is published at tested source `57f673f8e934e275bc2bd51e85d434dc7025bc9a`; PR #28's merged tree matches it exactly. PR #29's measurement preparation merged after its exact-head checks. The first adaptive diagnostic and following control are closed; their scoped results and unmet comparison gates are recorded in the [evidence ledger](docs/evidence.md#first-adaptive-video-diagnostic). |
| Installed source used for the latest experiments | `7306a53085ddc31d53d2ba50e91975c80cfc0014`; unchanged IQ3_S and quality. Source, package, controlled-clock SDK and physical evidence are separate levels. |
| Current work | The [ordinary saved-task reopening source](docs/saved-task-reopening.md) passed 51 focused checks, 77 corrected source-history checks and the full 1,342-test local suite, with independent source review and an actual one-shot Windows boot probe. Package/hosted checks belong to the exact candidate publication; installed IQ3_S application restart remains unqualified. Correct M3 comparison timing first: the earlier write preceded playback/handback and its adaptive capture missed playback. Broader tool handoff, reboot and daily-use gates remain on the roadmap. |
| Latest accepted single-task result | The first adaptive video diagnostic passed all 19 terminal checks: original 23-unit answer, three provider calls, one physical write, one Resume/Stop and owned cleanup within unchanged budgets. Independent review verified 33 audit input hashes. This is bounded task correctness and cleanup, not full video/handoff acceptance. |
| Preserved M2 recovery result | Case17 passed both original audits: 99 primary recovery/handover checks plus the foreground/lineage supplement. Its correct inventory result survived safe expiry and one Continue; a separate welcome task completed before one normal Stop. Six calls produced two physical writes. Welcome has format-only acceptance. Full M2 is broader than that run. |
| Preserved limits and failures | Original quality, 900-second execution budgets, 2,700-second outer bound and task accounting remain unchanged. Cases14/15/16 keep their original failed outcomes. Case17 retains the rejected file-picker input and 30-second operating-target misses; neither repeated a task control nor violated the strict foreground gate. |
| Foreground evidence | Case17 retained 25 real document actions, 24 wholly preseal, maximum adjacent interval 54.680872 seconds and preseal tail 37.453106 seconds. The original supplement passed onset, continuous hold and saved-read lineage; the postseal action is excluded from coverage. This is not a desktop-performance or GPU-preemption measurement. |
| Next experiment | Follow the [revised M3 sequence](PLAN.md#m3--protect-actual-desktop-activity): verify actual geometry and reachable Start before Resume, keep first-inflight/capture/Start adjacent within the original capture lead, and require output after ordinary handback. The closed diagnostic dropped 26/10,799 frames; the planned following control dropped 21/10,799 at the same smaller viewport. Preserve both and the original failed 59/10,800 control. No controlled improvement or full M3 qualification follows. |
| Latest release validation | Corrected source `57f673f` passed all 14 original hosted jobs, final archive/runtime verification and merge-tree verification. All five uploaded assets and the tag were verified at publication. The 48-check watchdog and 21-check refusal corrections retain their own local scope; earlier failed runs remain failed. |
| M3 publication | [PR #29](https://github.com/midhatn/adaptive-inference/pull/29) merged at `f6c0da1` with the tested `3136e35` tree. Its original 14 head jobs and seven post-merge jobs passed, including portable archive checks. Earlier archive/fixture failures remain retained; these preparation checks do not requalify the installed runtime. |
| Diagnostic publication and test correction | [PR #30](https://github.com/midhatn/adaptive-inference/pull/30) merged at `c348398` with the exact tested `72ac717` tree. Its corrected head passed 14 original hosted jobs and all 12 distribution checks; the original post-merge run passed seven jobs and six distribution checks. The original `fd4d483` pair retains 13 passes and one Windows SQLite concurrency-fixture failure. The [bounded correction](docs/evidence.md#sqlite-concurrency-fixture-ownership) owns test threads in a retained child and joins before cleanup; 18 focused checks passed. This publication changed no runtime, models or physical records. |
| Process state at diagnostic closure | The actual task parent and capture parents joined with exit 0. The observer joined with exit 1 after three post-shutdown connection errors; both page servers were intentionally interrupted after terminal saves, retaining shell exit 1. The terminal audit and independent review checked owned worker/GUI/native/transport cleanup. Selected owned processes/listeners were absent. Recheck live state before launching anything; this dated result is not a hardware reservation. |
| Publication boundary | The [case17 replay](provenance/task-handover/acceptance/README.md) includes a public result and fixed 33-input selection; actual and relocated replay produced identical output. The [fresh-run workflow](examples/validation/task_handover/README.md) preserves the harness, predicates and explicit local templates. New physical trials still need actual installation/deployment records and model assets; a public clone does not include private replay inputs or an automatic installer. No complete M2, reboot, gaming/media or speedup claim is made. |

The [delivery evidence ledger](docs/evidence.md#reference-delivery-checks)
preserves the earlier continuation, snapshot, authority-entry and whole-job
timeout outcomes with their separate corrections. They are historical results,
not pending experiments to repeat. The corrected alpha passed all 14 original
hosted jobs, its final archive matched 1,191 source files and 61 runtime modules,
and all five uploaded release files matched their checked sizes and SHA-256
digests before publication. The public tag points to the tested source. This
does not silently upgrade the separately recorded physical installation.

Local PLAN.md and docs/evidence.md describe the selected checkout. For unmerged
M2 work, verify the active PR's development revision before reading that revision's
**Current M2 gate**. Earlier entries saying
"next" are historical when a newer source-bound result supersedes them; verify
the current work item before choosing or repeating an action.

**Preserved delivery history:** corrected source `6be2629` passed its original 14
jobs and PR #25 merged at `e0b46e5`. Alpha `d5837f9` passed its original seven
push jobs; [release PR #28](https://github.com/midhatn/adaptive-inference/pull/28)
then exposed a selected CPU-child watchdog failure. The prospective correction
changes only that test child's emergency allowance and its source-view comment;
48 affected checks passed with retained child joins. Original outcomes, exact
exit/cleanup assertions and product settings stayed intact. That original
candidate remains failed; the final released successor has its own complete
hosted and package evidence above.

The next alpha head `70dc1cd` exposed a separate macOS listener-test assumption:
the deliberately refused unread TCP connection reset instead of returning empty
EOF. The [bounded correction](docs/evidence.md#refused-tcp-connection-fixture-on-macos)
accepts that specific reset only for the refusal, while retaining all ownership,
subsequent-request, timeout and cleanup assertions. Its 21 existing listener
tests passed locally with completed fixture cleanup, followed by the final
successor's 14 hosted jobs. The original `70dc1cd` result remains failed.

PR #26 merged at `46ecac6` after all 14 fresh jobs passed for its reviewed head
`aaabfd8`. Its five documentation/data/manifest files are integrated into this
candidate without changing runtime or tests. The [NPU qualification guide](docs/npu-qualification.md)
supports optional M9 research; it enables no backend and establishes no agent
speedup. Continue real foreground coexistence,
useful tool handoff and restart recovery.

Cases12 and13 also remain failed, for their recorded checker/observation issues.
The corrected UTF-8 receipt checker passed its 47 focused tests and was used by
case14; this does not requalify earlier cases. Existing successful source and
installation suites should not be replayed just to manufacture a fresh status.

Task authoring no longer requires manual JSON/hash editing; its focused source
tests do not transfer physical acceptance to a changed installed package. The
setup helper also leaves the runtime wheel unchanged. The next delivery is
ordinary use of the released reference and real desktop coexistence. Its launcher creates a
new run; application/reboot recovery must not be inferred from a reusable launcher.
The `0.4.0a1` reference passed fresh isolated wheel identity and installed
task preparation, including all 61 module hashes and unchanged task budgets.
The package version is the only runtime-source change from its immediate
development predecessor. Its combined source/archive and exact-head CI checks
passed before publication; retain the original physical installation identities.
The later gates remain: real desktop coexistence; agent-driven tool/media handoff;
installed startup, sleep/wake and actual reboot recovery; daily-use fault/soak qualification; then
broader native adapters and measured optimization. The autonomous media test
requires the latest supported participating software stack, the same specified
models, individual engine optimization and a co-optimized nonadaptive autonomous
baseline before comparison. Read the [pinned media test specification](https://github.com/midhatn/adaptive-inference/blob/4d2f5a767d58b4fadaab539438f9bfe9211d6615/docs/adaptive-hermes-media-autonomous-test.md)
before scheduling it; this small M2 run does not satisfy that test.

## First actions for a fresh contributor

The next functional experiment is the corrected [M3 video comparison](PLAN.md#m3--protect-actual-desktop-activity).
Its local video page and separate adaptive parent/observer passed focused
component checks and independent review; see [preparation evidence](docs/evidence.md#video-coexistence-preparation).
The original single-task terminal projection passed six synthetic checks; its
corrected observation join then passed ten focused checks. These component
results do not establish foreground resource or task acceptance. The
[first real no-AI control](docs/evidence.md#first-no-ai-video-control) completed
but failed the fixed frame-drop target; independent display attribution remains
unknown. The [first adaptive diagnostic and following control](docs/evidence.md#first-adaptive-video-diagnostic)
are also closed: task correctness and owned cleanup passed, while capture timing,
original viewport matching and post-handback output timing did not. Preserve all
of those outcomes. Correct the measurement sequence before a fresh comparison,
with all thresholds and budgets unchanged. Root remains the physical experiment
owner for this work item; another contributor must check ownership and fresh
machine state before starting a run. No runtime change is inferred from these
measurement failures alone.

1. Inspect local changes and branch/revision identities. Read current open work
   before claiming a task; do not overwrite another contributor's files or
   treat an old issue assignment as a live process handle.
2. Resolve the intended lane: stable main, the active M2 branch, or a separate
   target-specific adapter. Check the current PR head and base before using it.
   Follow linked evidence to the exact source that produced a claim.
3. Choose one bounded contribution that advances the next acceptance gate.
   Reuse relevant prior research, refresh primary sources for the new problem,
   and record the proposed acceptance before implementation.
4. Record its coordinator, file scope, resources and reviewer using the
   [collaboration workflow](docs/multi-agent-collaboration.md). Parallel research
   and read-only reviews are useful; physical test ownership remains exclusive.
5. Validate the changed contract, preserve failures, request independent review
   at the appropriate scope, then leave a complete handoff and update this file
   if the next decision changed.

## If you only have a public clone

Start with portable source, fixture, documentation or integration work you can
actually reproduce. Private raw model traces, local installations, the user's
model assets and machine-specific ownership records are intentionally not in
Git. Their hashes identify retained evidence but do not make it available to a
new contributor. Missing private inputs are an explicit limitation, not an
invitation to invent them, use a different model or claim the same hardware run.

If a later change requires a fresh physical M2 case, an operator on the authorized
qualification host must recover the local continuation packet, verify its exact
source and unused output paths, observe live resource availability and retain actual process
ownership. Without those inputs, continue independent portable work or prepare
the public reproduction package; do not improvise a replacement hardware result.
Preserve the entire goal while reporting which evidence is still unavailable.

## Keep this handoff useful

The integration owner updates this snapshot after an accepted result, a material
failure, a plan change, a publication or an ownership transfer. Record the date,
exact source/evidence, next action and any live-work boundary. Put detailed
measurements in the evidence ledger and research rationale beside the mechanism;
link them here. Keep historical outcomes intact and make stale state explicit.
The collaboration guide contains the reusable work-item and return templates.
