# Desktop control-core source lineage

This directory retains the exact five component modules, five fixture source
files and one test-only foreground-policy consumer selected for promotion.
`source-lineage.json` binds every retained file and identifies the original
component manifest. The complete private packet is not a runtime dependency.

The production modules differ only by qualified imports into
`adaptive_inference.desktop`. The package initializer performs no setup. No
CLI, GUI launch, native adapter, model, task owner or foreground policy is
promoted by this change.

Canonical tests use normal imports rather than private path loaders. The
mailbox runtime retains its 27 runtime cases; its five snapshot cases already
exist in the canonical mailbox suite. The progress selection omits the actual
GUI-client serialization test and three desktop/full-runner methods whose
components are not being promoted. It retains the canonical handoff-controller
safe-drain case. Transport-progress setup substitutes the exact original client
objective string for `bootstrap().objective`, avoiding an unpublished GUI
dependency without changing the tested protocol data.

The only added test support is `tests/desktop_support/policy.py`, a copy of the
retained policy with qualified control-core imports. The canonical strict
`adaptive_inference.handoff.ForegroundPolicy` and `number` helper are
AST-identical to the original policy predecessor, so the regression imports
that canonical module instead of preserving another duplicate. The policy
consumer is source/test material and is not shipped in the runtime wheel.

Run current tests from `tests/`; archived test files describe their historical
layout and are not installed entry points. Source preservation alone does not
establish a pass. Component tests and complete GUI/native/model qualification
are separate evidence.

All retained code is original Apache-2.0 project code. Existing TaskStore and
policy reuse attribution, including the MIT Strata/medking82 source references,
remains in the repository's NOTICE and third-party archive. No CPython,
Microsoft, NVIDIA or Hermes implementation was copied into this component.
See the [library contract](../../docs/desktop-control-core.md) for its API,
authority limits and primary research references.

## Pending-reply fixture authority entry, 1 November 2026

The original alpha `ebe0f1a3d165de783fe123aaf5428f0fa2f6dd5c`
[Windows 3.11 job](https://github.com/midhatn/adaptive-inference/actions/runs/41268742104/job/124736929014)
failed `test_pending_reply_precedes_retained_resume_authority_completion` at
the shared two-second snapshot-entry wait. It stopped after 551 tests in
315.436 seconds. The log does not establish which operation was delayed or
whether authority had entered; the original attempt remains failed.

The current fixture reuses the authority-entry pattern already present in its
rotation test: an [`asyncio.Event`](https://docs.python.org/3.11/library/asyncio-sync.html#asyncio.Event)
signals entry to the authority coroutine, and a bounded
[`wait_for`](https://docs.python.org/3.11/library/asyncio-task.html#asyncio.wait_for)
wait establishes that phase before the existing short snapshot-entry check.
The 30-second setup guard follows
[CPython 3.12.10's short test timeout](https://github.com/python/cpython/blob/v3.12.10/Lib/test/support/__init__.py).
No external implementation is copied or dependency added.

The two-second snapshot-entry and response waits, three-second held read and
retained-operation completion waits, pending-response ordering, intent and
single-request assertions remain unchanged. This change is limited to one
test's setup ordering; runtime settings, product budgets and all historical
source bytes and hashes remain unchanged. Current local checks and subsequent
exact-revision CI have their own scope; this is not an installed-model or
desktop-performance result.
