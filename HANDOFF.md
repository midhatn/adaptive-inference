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
| Stable main starting point | Commit `fb438a3fa0d4a63c395944897aabbd7d711a6936`, including the merged collaboration guide. Verify current `main`; this is a dated anchor, not a claim that it remains HEAD. |
| Active implementation | Branch `feat/same-host-task-admission`, [PR #25](https://github.com/midhatn/adaptive-inference/pull/25), still a draft at this snapshot. Do not merge its unqualified runtime merely to obtain these collaboration documents. |
| Installed source used for the latest experiments | `7306a53085ddc31d53d2ba50e91975c80cfc0014`; unchanged IQ3_S and quality. Source, package, controlled-clock SDK and physical evidence are separate levels. |
| Current milestone | M2: practical persistent controller, safe resource waiting, explicit continuation and isolated tasks in one retained host. M1's accepted reference remains independently preserved. |
| Latest physical result | Case15 completed safe expiry, one Continue, the original 23-unit inventory task, a distinct format-only welcome task and one Stop. The primary audit passed 99 checks. The separate foreground audit failed; the combined scenario and full M2 remain unqualified. |
| Remaining foreground issue | One of 31 adjacent intervals across 32 genuine document actions was 63.377849 seconds, violating the strict less-than-60-second coverage rule. The supplement stopped at `real_activity_hold_gap`; later onset/hold/lineage predicates were not reached. The delay's cause is unknown. Case14's distinct early recovery-reason failure remains preserved. |
| Next experiment decision | Review the operator critical path and assess its feasibility with genuine bounded work before another costly model trial. Keep short timely notes, defer polished analysis and place commentary before the next fresh observation. Preserve every predicate, original budget, source and model quality. No successor case is prepared by this result; never regroup or replay consumed cases14/15. |
| CI follow-up | Exact development head `33ae7f01c3deba44e6f11d2a546fdff26029b7ea` passed all 14 hosted jobs on their original attempts. The [test-only diagnostics](provenance/task-handover/continuation-timeout-diagnostics/README.md) leave runtime modules unchanged. All four Windows jobs passed 1,290 core tests, 81 provenance tests and 1,097-file/60-module archive checks; Python 3.12 had one core skip. This does not explain or erase `4d2f5a7`'s 13-success, one-timeout result. Check later reporting revisions separately. |
| Process state at the end of case15 | The actual retained parent and observer joined, owned cleanup passed the primary audit, and the subsequent read-only process/listener check found none. The observer's exit 1 followed service closure; it is not itself cleanup proof. This is a dated result, not current hardware reservation. |
| Publication boundary | The [case15 evidence](docs/evidence.md#case15-primary-recovery-passed-foreground-coverage-failed) and [current M2 roadmap](PLAN.md#milestones-and-dependency-order) distinguish tested runtime `7306a53`, primary recovery success, failed foreground qualification and exact-revision CI. The private run is not a public reproducible acceptance package. |

Local PLAN.md and docs/evidence.md describe the selected checkout. For unmerged
M2 work, verify the active PR's development revision before reading that revision's
**Current M2 gate**. Earlier entries saying
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
