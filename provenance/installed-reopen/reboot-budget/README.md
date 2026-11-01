# Versioned reboot-budget source preservation

This source increment adds the explicitly versioned budget contract described in
[the reboot plan](../../../docs/reboot-budget.md). Its predecessor is
`c7d6493c364b73d2124240992fe11e76fdc585c2`. Historical application-restart and
continuation records retain their original source identities and acceptance
limits; this source record does not requalify those runs.

[source-lineage.json](source-lineage.json) binds the exact predecessor and
successor bytes and portable AST fingerprints for seven runtime files and two
source-preservation readers. The predecessor copies were taken directly from
that Git revision. The new `desktop/execution_budget.py` module has its own
complete byte and AST pins. The record also binds the complete 62-module
predecessor runtime and the unchanged earlier manifests.

The implementation reuses the existing Apache-2.0 exact predecessor mechanism in
[`tests/continuation_timeout_lineage.py`](../../../tests/continuation_timeout_lineage.py).
Its new outer layer reverses only recognized complete successor files and removes
the new module only after verifying both pins. Earlier byte, AST and complete
runtime checks then receive their original inputs. Unknown bytes, extra or
missing modules, altered predecessor identities and changes outside the approved
AST are not hidden. Retained source is parsed, never executed. Existing expected
hashes and assertions remain unchanged.

The focused source-preservation batch passed **104 tests**, including five new
tests for the exact delta, legacy inputs, runtime closure and addition,
complete-byte AST checks, and identity tampering. The retained test child exited
normally; input hashes remained unchanged, and its emergency guard was not used.
The combined behavior and source results are recorded in
[validation-2026-11-01.json](validation-2026-11-01.json).

These checks establish source preservation and refusal boundaries. Behavior
fixtures, installed SDK checks and actual computer-reboot qualification remain
separate evidence. The changed runtime needs fresh installed qualification; no
physical reboot, model quality, foreground performance or speedup result is
claimed here.
