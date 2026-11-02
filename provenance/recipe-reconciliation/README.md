# Recipe reconciliation source preservation

The source-lineage record binds the recipe-feedback recovery increment to the
exact video candidate at `66deb339fcea1e227891c0fc30c41075c79548fc`.
The predecessor files are complete original Git blobs, retained as data under
the repository's Apache-2.0 license. Tests do not import or execute them.

The test-only source view reuses [the video source-preservation mechanism](../../tests/video_lineage.py):
both complete-file SHA-256 and a portable Python syntax-tree fingerprint must
match a declared successor before it can be projected to its predecessor.
Unknown bytes, including an added comment with unchanged syntax, are not
authorized. The full 77-module runtime closure is checked before the earlier
video and compiler source views run. The earlier source-lineage records and
physical evidence retain their original bytes and scope.

This permits historical evidence to continue checking its original source. It
does not make old tests evidence for the new recovery behavior. Component,
installed-agent and physical qualification of the new behavior are separate
gates; a source-preservation pass is not a crash, reboot or performance result.
