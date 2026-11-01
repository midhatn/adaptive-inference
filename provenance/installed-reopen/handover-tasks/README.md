# Later handover task reopening: source preservation

This additive record separates the later-task reopening change from previously
accepted source and physical evidence. Its predecessor is
`c6f20623579021d78cecdd6af8229bbdf2d6ef46`. The four files under `predecessor/`
are exact Git blob bytes from that revision: the two changed runtime modules
and the two changed lineage readers. They are parsed for comparison and never
executed. Local Git attributes preserve their exact bytes.

The change reuses the project's Apache-2.0 complete-file SHA-256 and
cross-version AST projection in `tests/continuation_timeout_lineage.py`.
[source-lineage.json](source-lineage.json) pins both the retained predecessors
and reviewed successors. Only exact successor bytes map to a predecessor;
unknown bytes pass through to the existing validators. AST projection also
requires the complete current source bytes to match. The outer runtime view
projects both `desktop/task_handover.py` and `desktop/saved_tasks.py` before the
older installed-reopen view removes the latter module. Other modules remain
visible to the existing complete-runtime checks.

The preparation, installed-reopen, integrated reader, fixture Stop,
timeout-diagnostic and task-file-alias manifests remain unchanged. The existing
integrated-reader test receives one outer projection before its original
assertions. Five new tests check exact retained files, unknown changes and
legacy roots, complete runtime coverage, byte-bound AST projection, and
tampering with predecessor identities or successor AST pins. Disposable-root
tests receive the new manifest and four predecessor files through the existing
input collector.

[The focused lineage record](lineage-validation-2026-11-01.json) retains the
75-check Python 3.11 result, unchanged source identities, and natural owned-child
exit. Component behavior and its preserved predecessor failure have a separate
[validation record](component-validation-2026-11-01.json). These source checks
do not qualify an installed later-task restart, model behavior, reboot recovery,
foreground coexistence or performance. Existing physical receipts retain their
original scope; the integrated suite and publication remain separate gates.
The changed runtime requires fresh installed qualification before an installed
later-task recovery claim.

The [complete integrated suite](integration-validation-2026-11-01.json) passed
1,359 tests in 413.619 seconds with unchanged source inputs and a normal retained
child exit. Distribution, hosted and installed later-task qualification remain
separate gates.
