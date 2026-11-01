# Supported Hermes file capabilities

This increment makes the advertised Hermes tools match the bounded recovery
consumer: `read_file` and `write_file`. It also checks the native turn outcome
before looking for its output artifacts, so a stopped native turn retains its
original failure category. The prompt, model, quality settings, request budget,
effect receipts and unknown-outcome fences remain unchanged.

The implementation consumes Hermes's public `create_custom_toolset` API at the
installed revision
[`14e1e43a`](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/toolsets.py).
The same API is present in the separately inspected current revision
[`d1a82fff`](https://github.com/NousResearch/hermes-agent/blob/d1a82ffff37a62de6fbdfabb496d1d2d0bc22822/toolsets.py).
Hermes is [MIT licensed](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/LICENSE);
this change calls its existing API and copies no upstream implementation.

This is not a claim of arbitrary invalid-tool recovery. In the pinned SDK, an
all-invalid tool-name retry appends feedback in memory and returns before the
ordinary tool-round native-history flush. The existing durable-history fence
therefore remains necessary. See the pinned
[validation](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_tool_validation.py#L143)
and [dispatch ordering](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_tool_round.py#L80).

## Preserve the earlier source evidence

The [source record](source-lineage.json) binds the complete predecessor and
successor bytes and portable AST fingerprints for the one runtime module, the
two source readers, and the three existing portable SDK fixtures adjusted to
represent the explicit toolset contract. Their exact predecessors come from
`50232cfaccd4bbe34cded6a368a0bb2eab22d204` and remain under `predecessor/`.

The existing Apache-2.0 source-projection mechanism in
[`tests/continuation_timeout_lineage.py`](../../../tests/continuation_timeout_lineage.py)
applies this outer mapping before the earlier handover, reopening and preparation
views. Earlier manifests and assertions retain their original identities.
Unknown bytes pass through to the original checks, unknown runtime modules are
not removed, and a matching AST alone cannot authorize different source bytes.
Retained predecessor source is parsed for comparison, never executed as a test
replacement.

Source-preservation tests, portable behavior tests, a pinned-SDK scripted fixture
and physical IQ3_S qualification are separate evidence classes. This record
does not convert either unsuccessful installed later-task attempt into a pass,
renew a consumed task deadline, or qualify a new installed runtime.

The [focused validation](focused-validation-2026-11-01.json) records two meaningful
predecessor failures, 35 passing corrected behavior checks and 80 passing source
checks. Both positive runs ended normally with unchanged inputs; independent
source review found no material blocker. The [complete suite](integration-validation-2026-11-01.json)
passed 1,369 tests after a test-only complete-call mutation correction. The first
suite's syntax error and its two-check correction remain recorded. Package,
hosted, actual-SDK and installed-model gates remain separate.
