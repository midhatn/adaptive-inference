# Continue Adaptive Inference

This is the shared continuation entry point for a new human or AI contributor.
Read [AGENTS.md](AGENTS.md) first. The repository, its retained evidence and current
Git state are authoritative; no previous conversation or particular AI provider
is required to understand the intended work.

**Snapshot date: 30 October 2026.** Recheck branch heads, PRs, task ownership and
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
| Stable main starting point | Commit `5d2264dfeafe6483dd9d839097811f687fab654c`, merging explicit task continuation. Verify current `main`; this is a historical anchor, not a claim that it remains HEAD. |
| Active implementation | Branch `feat/same-host-task-admission`, [PR #25](https://github.com/midhatn/adaptive-inference/pull/25), still a draft at this snapshot. Do not merge its unqualified runtime merely to obtain these collaboration documents. |
| Installed source used for the latest experiments | `7306a53085ddc31d53d2ba50e91975c80cfc0014`; unchanged IQ3_S and quality. Source, package, controlled-clock SDK and physical evidence are separate levels. |
| Current milestone | M2: practical persistent controller, safe resource waiting, explicit continuation and isolated tasks in one retained host. M1's accepted reference remains independently preserved. |
| Latest physical result | Case14 completed safe expiry, one Continue, the original 23-unit inventory task, a distinct welcome task and one Stop. The primary audit passed 99 checks. The welcome task is format-only. The separate foreground audit failed; the combined scenario and full M2 remain unqualified. |
| Remaining foreground issue | Twelve early status rows had recovery-margin/dwell reasons rather than the exact required foreground-activity reason. Admission stayed closed. The first operator action was standalone window activation. Raw input-age/CPU samples were not retained, so an exact OS-level cause is not established. |
| Next experiment decision | Clarify the first useful document transition prospectively, including activation, actual observation and meaningful navigation in its full time bracket; preserve every predicate, model and budget. A fresh independently reviewed packet is required. Never regroup or rerun consumed case14. |
| Process state at the end of case14 | The retained parent and observer joined, all owned runtime lifetimes closed, and the later read-only process/listener check found none. This is a dated result; a new operator must inspect current state before any physical work. |
| Publication boundary | Detailed case14 evidence and the revised procedure are published at documentation commit [`4d2f5a767d58b4fadaab539438f9bfe9211d6615`](https://github.com/midhatn/adaptive-inference/commit/4d2f5a767d58b4fadaab539438f9bfe9211d6615), separate from tested runtime `7306a53`. Read its [case14 evidence](https://github.com/midhatn/adaptive-inference/blob/4d2f5a767d58b4fadaab539438f9bfe9211d6615/docs/evidence.md#case14-primary-recoveryhandover-passed-foreground-supplement-failed) and [current M2 roadmap](https://github.com/midhatn/adaptive-inference/blob/4d2f5a767d58b4fadaab539438f9bfe9211d6615/PLAN.md#milestones-and-dependency-order). The private run is not a public reproducible acceptance package. |

In this main-based snapshot, local PLAN.md and docs/evidence.md describe the
stable checkout. For active M2 development, start with the pinned development
roadmap's **Current M2 gate** and evidence linked above. Earlier entries saying
"next" are historical when a newer source-bound result supersedes them; verify
the current work item before choosing or repeating an action.

Cases12 and13 also remain failed, for their recorded checker/observation issues.
The corrected UTF-8 receipt checker passed its 47 focused tests and was used by
case14; this does not requalify earlier cases. Existing successful source and
installation suites should not be replayed just to manufacture a fresh status.

The later gates remain: complete foreground qualification and public reproduction;
real desktop coexistence; agent-driven tool/media handoff; installed startup,
sleep/wake and actual reboot recovery; daily-use fault/soak qualification; then
broader native adapters and measured optimization. The autonomous media test
requires the latest supported participating software stack, the same specified
models, individual engine optimization and a co-optimized nonadaptive autonomous
baseline before comparison. Read the [pinned media test specification](https://github.com/midhatn/adaptive-inference/blob/4d2f5a767d58b4fadaab539438f9bfe9211d6615/docs/adaptive-hermes-media-autonomous-test.md)
before scheduling it; this small M2 run does not satisfy that test.

## First actions for a fresh contributor

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

For the next physical M2 case, an operator on the authorized qualification host
must recover the local continuation packet, verify its exact source and unused
output paths, observe live resource availability and retain actual process
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
