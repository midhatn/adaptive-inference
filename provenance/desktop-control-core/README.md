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
