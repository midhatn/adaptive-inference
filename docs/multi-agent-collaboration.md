# Collaborative development and durable handoff

Adaptive Inference can be continued by different people and AI coding tools from
the same repository. [AGENTS.md](../AGENTS.md) is the stable instruction entry;
[HANDOFF.md](../HANDOFF.md) is the short, dated continuation state;
[PLAN.md](../PLAN.md) holds the goal and gates; the [evidence ledger](evidence.md)
holds results. Keep those roles distinct rather than maintaining competing
copies of the plan inside separate agent memory files.

This uses the existing [AGENTS.md convention](https://agents.md/), ordinary
[Git worktrees](https://git-scm.com/docs/git-worktree), and
[GitHub issue/PR ownership](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/assigning-issues-and-pull-requests-to-other-github-users).
It adds no agent runtime, model dependency or automatic job launcher. Tools that
do not automatically read AGENTS.md can receive the short entry instruction at
the end of this page. Documentation cannot transfer private credentials, a live
process handle, machine access or an AI's unavailable capabilities.

The use of incremental tasks, explicit acceptance and durable progress records
also draws on [research on long-running agent harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents).
This is a coordination practice, not evidence that adding more agents guarantees
success. Sources and the scope of reuse are retained in [REFERENCES.bib](../REFERENCES.bib).

## Divide work by a concrete contract

One work item has a coordinator/integration owner, bounded implementation or
research workers, and an independent reviewer when its acceptance needs one.
A single contributor may coordinate small tasks; do not create workers merely
to satisfy a fixed headcount. Delegate independent work when it improves speed
or review quality. Typical parallel lanes are source research, implementation,
portable validation and independent evidence review.

Each contributor's first update identifies the files actually read, exact
checkout revision, chosen task, ownership and missing tools/evidence. Include
required source paths in each delegated assignment; context inheritance and
automatic instruction loading vary by client and worker setup.

Use an existing issue or PR when it already owns the work. Otherwise use the
[task issue template](../.github/ISSUE_TEMPLATE/agent_task.md), or the same text in
a local Markdown work item when offline. An AI need not have a GitHub account:
record the responsible contributor and a local worker name separately. Posting,
assignment and external communication still require the authority supplied by
the user/session and the target repository's rules.

Before a worker starts, the coordinator confirms its scope and ownership in the
shared work item or existing session coordination channel. Claims are coordination
records, not an atomic distributed lock. A timestamp or abandoned assignment does
not prove an experiment stopped. Resolve conflicting claims before mutations;
use read-only research while ownership is uncertain.

| Responsibility | Required boundary |
| --- | --- |
| Coordinator/integration owner | Owns the work item, dependencies, acceptance decision, integration, publication and continuation-state update. |
| Research/implementation worker | Receives an exact objective, base revision, allowed files, reusable sources and deliverable. Reports evidence and uncertainties; does not broaden scope silently. |
| Validation worker | Runs the agreed checks on an identified revision/environment. Retains command, actual exit/result, coverage and failures. Does not label unexecuted tests as passing. |
| Independent reviewer | Checks source and evidence against the original contract. Separates source clearance from hardware qualification; cannot infer missing physical observations. |
| Physical experiment owner | Sole actor for that host's model/GPU/native-service/UI experiment. Retains actual handles, observes readiness, preserves original deadlines and performs owned cleanup. |

## Avoid conflicts and duplicate experiments

Prefer separate branches/worktrees for concurrent code changes. A shared checkout
is acceptable only with explicit disjoint file ownership and coordination before
integration. Do not revert another worker's edits, reset a dirty tree, or write a
shared status file from several workers. The integration owner reconciles worker
results and updates HANDOFF.md/PLAN.md after review.

Separate worktrees do not isolate GPU memory, ports, models, installed services,
shared output directories or databases. Only the physical owner may run the
agreed heavy trial on that host. Other workers can inspect frozen source and
closed evidence; they must not poll live databases, change active services,
launch competing model workloads or operate the UI behind the owner.

Before resuming work, identify any actual live process/session/job handle. An
observation timeout is not terminal; re-observe that same handle or authoritative
state. Never restart a trial solely because a watcher timed out. A saved PID is
not sufficient process identity. When an actual run finishes, retain its joins,
exit results and cleanup evidence before another owner starts.

Completed and failed cases are immutable. A new experiment gets a fresh identity
and unused output paths after the reason for repeating it is recorded. Do not
re-run completed suites without changed behavior, a relevant failure or an
unresolved question. Preserve original attempts, model quality, acceptance
criteria and time/request budgets.

## Research, implementation, validation and integration

1. Read the current evidence and inspect the relevant code. Before designing a
   new solution, search current primary documentation/research and existing
   implementations or issues. Record version/date, applicability, license and
   why an existing mechanism can or cannot be reused.
2. State the concrete user-visible result and acceptance gate. Use the shared
   queue, task store, resource ownership, feedback and adapter contracts.
3. Implement the bounded change. Favor a functional end-to-end reference over
   unrelated optimization or speculative ports. Corrective model iterations may
   be normal; unknown external effects still require reconciliation.
4. Validate the changed behavior using the relevant existing tests and exact
   source. A documentation-only change needs link/content/package-inclusion
   checks where applicable; it does not require a new inference experiment.
   Runtime changes must satisfy the applicable roadmap, reproduction and CI
   gates. Keep fixture, installed SDK, real model, native lifecycle, desktop
   measurement and physical reboot results separate.
5. Return an inspectable patch/commit and evidence. The reviewer checks the
   original requirement and all material limits, not just a green summary.
6. The integration owner records the decision, updates the evidence/plan/handoff
   as needed and publishes the canonical result. An upstream PR receives only
   a relevant mergeable change validated for its exact target, not a generic
   progress announcement.

An unsuccessful experiment is useful evidence when it changes the next action.
Do not turn it into a pass by narrowing the goal after the fact, discarding an
inconvenient observation, replacing the model or relaxing a threshold.

## Work-item record

Use this compact structure in the shared issue, PR or local work item. Keep
private commands, prompts, paths, host identifiers and credentials in the
authorized local record, with a sanitized public summary where appropriate.

```text
Objective and milestone:
User-visible result / acceptance gate:
Base repository, branch and exact commit:
Required reading / files actually read / unavailable evidence:
Coordinator / worker / reviewer:
Status: proposed | claimed | running | waiting | ready-for-review | accepted | failed | blocked | superseded
Allowed files and interfaces:
Dependencies and existing related work:
Physical resources / sole owner, or "none":
Research inspected: source URL, revision/date, applicability, license:
Validation plan and unchanged limits:
Current live handle / last authoritative observation (private if needed):
Result, actual validation and retained failures:
Evidence locations and source identities:
Next action / unresolved uncertainty / ownership transfer:
```

These work-item statuses describe that item only; they do not silently mark a
roadmap milestone complete or alter a user's active goal. Use `waiting` only
with a specific dependency or an actually live handle, and `blocked` with the
concrete missing input. `accepted` requires evidence for the declared gate.

## Worker return and session handoff

```text
What changed and why:
Exact commit or patch / changed paths:
Research or existing implementation reused, with citation/license:
Checks actually run, environment, exits and evidence:
What the result proves / what it does not prove:
Failures and unexecuted checks:
Live work: actual retained handle, owner and next observation; otherwise confirmed joins:
Remaining work and exact next safe action:
Suggested updates to HANDOFF.md, PLAN.md and evidence (integration owner applies):
```

Before a restart, context limit or session transfer, write this state while the
facts are available. Preserve already running work under its current owner;
do not launch a replacement merely to obtain a new handle. If the next AI lacks
the original private inputs or process handle, it must report that boundary and
verify available authoritative state before dependent work. It can still make
progress in independent portable lanes.

## Entry instruction for any AI tool

> Continue work on Adaptive Inference from this repository. Read AGENTS.md,
> HANDOFF.md and the current PLAN.md, then inspect the checkout and current task
> ownership. Report the files you actually read, revision, intended task and any
> access/evidence limits. Preserve the always-on-agent goal, research existing solutions
> before new design, use the recorded model and acceptance constraints, and
> choose the next bounded contribution supported by current evidence. Coordinate
> with active contributors and leave a source-bound handoff when you finish.

This entry instruction is not an instruction to bypass the user's scope or the
tool's higher-priority rules. Any contributor can use the same files manually;
automatic discovery depends on the chosen AI application.
