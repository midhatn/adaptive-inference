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
child exit. The same source's package and original hosted checks subsequently
passed. The [first installed attempt](first-installed-attempt-2026-11-01.json)
retains the unqualified first-app result and independent diagnosis of a private
audit digest mismatch. Its original failed gate remains preserved; later-task
restart qualification is still pending. Corrected separate checker copies
subsequently passed five focused checks and a clock-independent closed
diagnostic. The [second attempt](second-installed-attempt-2026-11-01.json)
failed before Stop because the SDK advertised an unsupported search tool and
the worker masked that refusal with a missing-output error. Its unresolved
host admission state is retained. A prospective runtime correction and its own
source/SDK/package/installed validation are required; neither failed attempt is
reclassified or reopened.

The later correction and its own qualification are now complete at `b35b631`.
See the [supported-tool source and SDK evidence](../tool-capabilities/README.md)
and the [accepted installed later-task restart](installed-restart-2026-11-01.json).
The fresh third trial completed A, created B in the same controller, stopped B
after one confirmed read and reopened that same task paused. Two resumed calls
completed the correct 23-unit output with one physical write overall, preserving
the original deadline and counters. Completed viewing changed no checked A/B
or admission bytes. Independent review accepted only this same-boot application
scope. The two historical failures above retain their original outcomes.
