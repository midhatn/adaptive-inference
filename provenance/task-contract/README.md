# Source preservation for generic task contracts

This source-only layer preserves the exact changed predecessor modules from
repository commit `5d2264dfeafe6483dd9d839097811f687fab654c`. It contains seven
changed predecessors; fifty runtime modules remain unchanged and two are new.
The manifest pins complete source bytes and the repository's cross-version
canonical AST for all fifty-nine current runtime modules.

`tests/task_contract_lineage.py` reuses the complete-file projection pattern in
`tests/thread_pause_lineage.py`. It verifies the complete current source closure
before constructing the historical fifty-seven-file view used by the original
continuation assertions. The original continuation, paused-expiry and earlier
manifests and their expected hashes remain unchanged. Both outside-function and
inside-function mutations are refused; preserved source is parsed, not executed.

These files are Apache-2.0 project source; their original citations and notices
are retained. See the repository [license](../../LICENSE),
[TaskSpec contract and research](../../docs/task-spec.md), and
[existing continuation lineage](../explicit-continuation/source-lineage.json).
The task-contract code reuses existing TaskStore ownership, checkpoint and
operation contracts; it does not replace their source attribution.

Preserving earlier source assertions is not live qualification of new code.
Current behavioral tests are separate from historical evidence. The accepted
installed continuation result still refers to its exact earlier package and
fifty-seven-module source. This layer does not change that package, its receipts,
the IQ3_S baseline, or any accepted result. Generic TaskSpec/admission source has
no new installed model or resource-handoff claim merely because this projection
passes.
