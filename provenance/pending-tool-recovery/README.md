# Pending tool recovery source preservation

The source-lineage record binds pending-effect recovery to the exact published
recipe-feedback increment at `93eba3ce4eee9609283f360fb7ca51b6c136e8bb`.
Eight complete predecessor Git blobs preserve the four changed runtime modules,
two previously tested fixture modules and two source-lineage files. They remain
data under this repository's Apache-2.0 license; tests do not import or execute
the retained copies.

The test-only view reuses [recipe reconciliation's source-preservation mechanism](../../tests/recipe_reconciliation_lineage.py)
and the [new layer](../../tests/pending_tool_lineage.py). Complete-file SHA-256
and a portable Python syntax-tree fingerprint must both identify a declared
successor before projection to its exact predecessor. Unknown complete bytes,
including an added comment, do not earn that projection.

The complete 77-module runtime is checked before the preceding recipe, video
and compiler views run. Existing projected views remain idempotent. The 21
original recipe, video and compiler JSON records keep their original bytes,
source identities and qualification limits.

This preserves the meaning of historical evidence. It does not qualify the
new recovery behavior: component checks, the complete local suite, distribution,
installed-agent recovery and physical tests remain separate gates. This layer
does not claim a worker restart, computer restart, performance improvement or
successful recovery of an unknown effect.
