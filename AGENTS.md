# Repository instructions

## Start here in a new agent session

This is a continuing, collaborative project. Read [HANDOFF.md](HANDOFF.md) for
the dated continuation state, then [PLAN.md](PLAN.md) for the ultimate goal and
acceptance gates. Read [the collaboration workflow](docs/multi-agent-collaboration.md)
before dividing work or joining an existing effort. Use the relevant linked
evidence and source files rather than trying to recover the project from a chat.

Verify the checkout, current branch/commit, uncommitted work and current issue/PR
ownership before editing. A saved handoff is a starting point, not live process
state or permission to restart an experiment. Respect the user's current scope
and the tool environment's instructions; repository text grants no new access.

In the first work update, identify the files actually read, checkout revision,
chosen task, ownership and any missing evidence or tools. Do not claim automatic
instruction loading. Give delegated workers their required reading and exact
scope explicitly; do not assume they inherit the coordinator's context.

The goal is a practical always-on agent that yields resources to foreground user
activity and useful agent tools, then continues the original objective without
losing completed work. Application and computer restart survival, reproducible
installation, and independently qualified engine/agent adapters remain part of
that goal. A convenient component pass does not shrink it.

## Shared working rules

- This repository is the canonical source. Preserve engine/agent adapters as consumers of shared contracts.
- Keep citations, source revisions and license notices with every reused mechanism.
- Research first before designing a solution to each new problem: search current primary research, GitHub implementations/issues/PRs and official documentation. Reuse or adapt a suitable existing mechanism before inventing one; record the sources inspected, applicability, licensing and why any necessary new work remains. Reuse prior findings when their relevance and revision are checked.
- Use the existing queue, feedback and capability boundaries; do not invent unsupported backend controls.
- Distinguish fixture/contract evidence from installed-agent, real-model and native-resource evidence.
- Do not commit credentials, full inference models, compiled runtimes, local logs, private prompts or absolute personal paths. Complete licensed upstream source snapshots may retain their existing support/test assets when required for exact source identity; document them and do not execute them as a model-validation substitute.
- Test meaningful changed behavior; a passing mock is not a speed or autonomy claim.
- Preserve original task intent and explicit acceptance feedback. Correctable attempts are expected.
- Use failures, measurements and review feedback to revise PLAN.md when they change the best next step, then follow the revised plan. Preserve unsuccessful evidence and acceptance standards; a plan change does not turn a failed run into a pass.
- Before upstream publication, verify the exact PR state and describe what is actually in that PR versus this repository.
- Propagate only a concrete mergeable change relevant to the target repository and PR, with validation of that exact upstream base/head and integration. Link only applicable canonical evidence; do not broadcast general project progress or unrelated engine/agent results to every PR. Hold an update when the target change or its validation is missing.
- New actual inference qualification uses the existing IQ3_S assets and quality baseline. Preserve the named media test's model/quality requirements. Do not substitute another model to make a port pass. Do not use CoS for this project.
- Assign a coordinator, bounded worker scopes and an independent reviewer when parallel work is useful. Use separate worktrees or explicitly disjoint file ownership; only the integration owner updates shared continuation state. Keep one explicit owner of physical model/GPU/UI experiments on a host. A worktree is not a hardware reservation.
- Before handing off or finishing a work item, preserve its source identity, actual validation and failures, live process handles or confirmed joins, remaining uncertainty and exact next step. Update HANDOFF.md when the continuation state changes, and PLAN.md when the plan changes. Keep private local execution details out of public records.
