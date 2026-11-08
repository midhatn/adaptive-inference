# Automatic tool recovery source preservation

The source-lineage record binds automatic desktop tool recovery to the exact
published pending-effect increment at `9242434991f2c2c21461061d61d898649299b847`.
Six complete predecessor Git blobs preserve the three changed runtime modules
(`composition.py`, `desktop_controls.py`, `task_handover.py`), one modified
desktop composition test module, and two source-lineage files. They remain data
under this repository's Apache-2.0 license; tests do not import or execute the
retained copies.

The test-only view reuses [pending tool recovery's source-preservation mechanism](../../tests/pending_tool_lineage.py)
and the [new layer](../../tests/automatic_tool_recovery_lineage.py). Complete-file
SHA-256 and a portable Python syntax-tree fingerprint must both identify a
declared successor before projection to its exact predecessor. Unknown complete
bytes, including an added comment, do not earn that projection.

The complete 77-module runtime is checked before the preceding pending-effect,
recipe, video and compiler views run. Existing projected views remain idempotent.
The 24 original pending-effect, recipe, video and compiler JSON records keep
their original bytes, source identities and qualification limits.

This preserves the meaning of historical evidence. It does not qualify the new
automatic recovery behavior: component checks, the complete local suite,
distribution, installed-agent recovery and physical IQ3_S tests remain separate
gates.
