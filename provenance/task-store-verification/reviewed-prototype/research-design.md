# TaskStore verification and hot-journal recovery design review

Research and source review: 2026-10-24. This is a private design recommendation, not an implementation or runtime acceptance report. No canonical or frozen source was changed and no model, native owner, or UI was run for this review.

## Evidence and scope

The reviewed canonical `task_store.py` is the existing 64 MiB bounded, DELETE-journal, FULL-synchronous store. It reuses SQLite transactions and an existing `.init.lock` sidecar. Exact source SHA-256 at review: `39f4efaa0983fea5202ac1027f12c7638787e7da874e26b678a9a3812b1afacc`.

An actual qualification fixture produced `InvalidStoreError` during concurrent mailbox/bootstrap work, but its original exception cause was not retained. A subsequent bounded concurrency reproduction using the same source passed. The following two defects are established from the code and upstream contracts; neither is established as the cause of that particular Windows failure:

1. `immutable=1` is used against the live mutable database. It disables locking and change detection under a promise this file cannot change.
2. The database header is read using a separate raw file open/close on every verification. On POSIX, such a close can release SQLite locks held by other threads in the same process.

The current exact-schema and foreign-file refusal requirements remain. Existing real hot-journal rollback and foreign/corrupt/same-header-schema byte-preservation tests must remain. This review does not weaken operation reconciliation, per-task runner ownership, revisions, quality, or acceptance.

## Recommended smallest functional correction

Reuse the existing per-store `.init.lock` as a short operation gate. Hold it across constructor create/verify and each complete `_connection` context, including verification, SQLite transaction, commit/rollback, and connection close. Bound acquisition using the existing `_FileLock` mechanism. Do not hold this gate for an agent lifetime, model request, native lifecycle operation, or external effect. Do not substitute it for the existing long-lived per-task owner lock.

The lock order stays task-owner lock then short store gate where needed. Constructor and store verification never acquire a task-owner lock. Avoid nested gate acquisition by making the already-coordinated verification helper explicit. All cooperating store instances and processes must use the same resolved database path and stable sidecar. Never unlink a lock file while runners may exist.

Normal verification uses normal `mode=ro`, an explicit read transaction, exact `application_id`/`user_version`/schema verification, and `quick_check`. Use SQLite PRAGMAs to read database identity. Remove the raw main-database header read and all live `immutable=1` access. SQLite still owns database page locking and all transaction and recovery work.

Only an actual `sqlite3.Error` with extended `sqlite_errorcode == SQLITE_READONLY_ROLLBACK` (776) may enter the recovery path. BUSY, permission errors, corruption, missing files, and other READONLY variants are not recovery authorization. Preserve code, name, operation, and cause in diagnostics without publishing private paths.

For that rare case, while holding the store gate:

1. Close every SQLite connection opened by the operation. The failed readonly connection is not a retained snapshot lock.
2. Require the supported bounded single-database DELETE-journal layout. Refuse WAL/SHM sidecars rather than accidentally treating them as a complete DELETE snapshot. Check file bounds and reject unsupported file types/layouts. These checks are refusal boundaries, not replacement SQLite validation.
3. Copy the database and matching rollback journal together to an exclusive private temporary directory while all cooperating accesses remain excluded. Bound both file sizes. The recovery copy must include the journal; the unrecovered main database alone can contain uncommitted schema or payload pages.
4. Before opening the copy with SQLite, conservatively reject any journal whose final eight bytes equal SQLite journal magic `d9 d5 05 f9 20 a1 63 d7`. This rejects possible external super-journal references without interpreting or replaying journal records. See the source rationale below. An accidental matching suffix is a safe refusal, not permission to relax the check.
5. Let ordinary SQLite recover the copied pair. Validate the recovered exact schema and `quick_check` in a read transaction. A foreign/corrupt/unsupported recovered copy must leave the original database and original journal untouched.
6. Only after this validation may ordinary SQLite open the original read/write and perform its own recovery. Revalidate its exact schema and integrity under the same operation gate before the requested operation proceeds. Never transplant recovered pages manually.

This deliberately serializes cooperating reads as well as writes. It may reduce throughput and has no fairness guarantee. That is a bounded correctness tradeoff for the functional milestone, not a performance improvement. Direct external SQLite writers, raw file replacement, symlink/hard-link aliasing, and noncooperating tools are outside the existing private-store coordination contract. The gate does not make a raw copy safe in their presence. Document this explicitly.

For the normal path, consider refusing existing WAL/SHM sidecars before opening SQLite: even a readonly SQLite connection can interact with WAL shared-memory state. This store only creates DELETE-mode databases, so no WAL recovery claim is necessary.

## Why a readonly check or a copy alone is insufficient

SQLite 3.45.1 `sqlite3PagerSharedLock()` returns 776 when a readonly connection discovers a hot journal. Its failure path calls `pager_unlock()` and returns the pager to OPEN. Keeping that connection open after the error therefore does not hold a stable shared snapshot for raw copying.

SQLite backup/serialization require a readable source and do not bypass necessary hot-journal recovery. `query_only` is not equivalent to a genuinely readonly connection. Using immutable against just the current main database misses rollback state; a foreign committed database might temporarily contain an uncommitted schema resembling ours.

Recovering a copied pair also needs an external-reference boundary. In pinned SQLite 3.45.1, `readSuperJournal()` only returns a nonempty super-journal name if the final eight bytes match the journal magic. `pager_playback()` can subsequently call `pager_delsuper()`, which opens referenced files and can delete the super-journal. A temporary directory alone does not confine those absolute references. Rejecting every possible magic suffix is a deliberately broader condition than SQLite uses and never parses or rewrites the referenced name. TaskStore itself never uses ATTACH and does not need multi-database recovery.

If even that eight-byte conservative format guard is considered outside the allowed scope, stdlib SQLite does not provide an equivalent public authorizer hook for internal journal filesystem operations. Do not claim arbitrary foreign-journal isolation in that case. Keep ambiguous recovery refused instead of adding an unreviewed VFS, journal parser, OS sandbox, or deserialize workaround.

## Required implementation qualification

- All existing TaskStore, demand, mailbox, recovery, and ownership tests remain meaningful and pass.
- Real interrupted single-database transaction recovers the previous checkpoint and complete history through SQLite; no application-level replay occurs.
- Foreign/corrupt/unsupported databases, including our header values with another schema, remain byte-identical on rejection.
- A foreign database with an actual hot journal is rejected without changes to either original file. Include a committed foreign schema whose uncommitted pages resemble the accepted schema, where feasible with SQLite-driven fixtures.
- A possible super-journal suffix is refused before the copied database is opened by SQLite. Use a harmless private sentinel/external-journal fixture to prove no referenced file is touched. Do not exercise paths belonging to unrelated files.
- Only exact error 776 takes the copy/recovery branch; errors retain useful cause/code/name. Permission/BUSY/corruption do not silently retry as recovery.
- Normal reads perform no raw main-database file open and no immutable connection. Explicit read transactions contain identity/integrity checks.
- Actual bounded concurrent cooperating threads and processes can read/write/load history without the previous live-immutable path; gate timeout and process-exit release are tested. Preserve every failure receipt.
- No nested lock deadlock; task owner can perform normal operations while holding its task lock; constructor does not take task locks; a long-lived claimed task does not monopolize the short store gate.
- Snapshot copying occurs only after SQLite connections close under the gate. Oversized/unsupported pairs are refused; original byte preservation is checked on every pre-recovery failure.
- Cross-platform CI must cover POSIX lock behavior, not infer it from a Windows-only test pass. Normal SQL operation semantics and acceptance/reconciliation boundaries remain unchanged.

## Primary sources inspected

Accessed 2026-10-24. SQLite source is public domain and is reused as a documented mechanism, not copied as a new recovery engine. Existing medking82/Strata attribution in TaskStore remains applicable and unchanged.

- SQLite URI parameters, immutable promise and warnings: <https://www.sqlite.org/uri.html>
- SQLite corruption guide, live copy consistency and raw close/POSIX lock hazard (§1.2, §1.4, §2.2): <https://www.sqlite.org/howtocorrupt.html>
- Locking and hot-journal algorithm (§4.1): <https://www.sqlite.org/lockingv3.html>
- Exact READONLY_ROLLBACK extended result code: <https://www.sqlite.org/rescode.html#readonly_rollback>
- PRAGMA query_only limitation: <https://www.sqlite.org/pragma.html#pragma_query_only>
- Online backup API and consistent snapshots: <https://www.sqlite.org/backup.html>
- Atomic commit, multi-file super-journal semantics (§5): <https://www.sqlite.org/atomiccommit.html>
- Pinned engine source, SQLite `version-3.45.1`, `src/pager.c`: <https://raw.githubusercontent.com/sqlite/sqlite/version-3.45.1/src/pager.c> — `readSuperJournal()` around 1245–1281; `pager_delsuper()` 2404–2494; `pager_playback()` 2657–2840; readonly hot-journal rejection 4991–4994; unlock on failed acquisition 5145–5149.
- SQLite database/journal file-format reference: <https://www.sqlite.org/fileformat2.html>
- Python 3.11 SQLite exceptions and extended error metadata: <https://docs.python.org/3.11/library/sqlite3.html#exceptions>
- SQLite deserialize API warning, reviewed and not selected: <https://www.sqlite.org/c3ref/deserialize.html>

No observed live qualification failure has been reclassified as passing by this design. A correction needs its own preserved source, independent review, CPU evidence, and fresh qualification.
