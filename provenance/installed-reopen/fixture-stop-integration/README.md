# Reopening and fixture Stop source integration

This additive record composes the two previously reviewed test-reader changes
when the saved-task reopening branch incorporates the fixture Stop cleanup fix.
It retains the exact helper and test bytes from each branch. The original
installed-reopen and fixture-stop-verification records and their historical
source pins remain unchanged.

Only the complete declared combined helper or test can be projected to its
retained `reopen` or `fixture_stop` view. That view then passes through the
existing branch validator and its original byte and AST assertions. Unknown
bytes remain unchanged so the original checks can reject them. Retained source
is parsed, never executed.

The changed files are test readers only. Runtime code, deadlines, process
identity checks and installed results are not requalified by this mapping.
The existing task-preparation lineage tests check both branch views, preserved
record hashes, unknown-byte refusal and retained-source identity. This reuses
the repository's existing SHA-256 and AST source-preservation mechanism; it adds
no recovery or execution framework.

The [combined validation record](validation-2026-11-01.json) records 83 passing
focused checks and the complete 1,352-test local suite, with actual retained
joins and unchanged checked sources. All 62 runtime modules still match the
installed application-restart source. Package/hosted checks apply to the final
published combined head; this source integration repeats no physical trial.
