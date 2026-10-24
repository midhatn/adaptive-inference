# Private TaskStore verification successor

This private CPU prototype corrects two established SQLite contract violations: using immutable reads against a live mutable database, and reading its raw header through a separate file descriptor that can disturb another SQLite connection's POSIX locks. It does not establish the cause of the earlier isolated Windows qualification failure and does not turn that failure into a pass.

The original TaskStore source, its consumer modules, and existing tests are preserved byte-for-byte under `predecessor/`. Only `src/adaptive_inference/task_store.py` changes behavior. Ownership epochs, task locks, original prompts, attempt and history bounds, operation reconciliation, durable demand, mailbox ordering and feedback acceptance remain unchanged. The new source-preservation tests check these boundaries and the extracted original transaction body.

## Mechanisms reused

- The stable `.init.lock` sidecar now protects each complete short operation as well as initialization. Lock contention waits at most five seconds with a monotonic deadline; failure to open the sidecar is not retried. A claimed task does not monopolize this gate. All SQLite handles close before the gate is released.
- Verification uses normal SQLite `mode=ro`, connection-local `locking_mode=EXCLUSIVE` before its first read, an explicit read transaction, exact identity/schema checks, DELETE-mode confirmation and `quick_check`. There are no live immutable reads or raw main-database reads on the normal path.
- Only `SQLITE_READONLY_ROLLBACK` (776) authorizes a recovery inspection. The readonly connection closes first. Under the gate, the main database and its rollback journal are copied together into a private temporary subdirectory beside the original store. Copy files are created with mode 0600 on platforms that support it.
- SQLite recovers the copied pair. Only a recovered copy with the exact accepted schema and integrity permits SQLite to recover the original. Pre-recovery copy, validation or cleanup failure leaves the original pair untouched. No application code interprets pages or replays journal records.
- Any journal ending in SQLite's eight-byte journal magic is conservatively rejected before copied SQLite recovery. In the pinned upstream implementation this suffix is necessary for an external super-journal reference; rejecting all matches avoids parsing or following those references. A coincidental suffix can cause a safe refusal.
- Existing WAL/SHM sidecars are refused. A clean WAL database with no sidecars is also refused without creating them in the Windows SQLite 3.45.1 fixture: connection-local exclusive locking avoids WAL shared-memory operations. Its exact error code is platform-dependent and is never a recovery fallback.

The gate deliberately serializes cooperating reads and writes. This is a correctness tradeoff for the first functional implementation, not a throughput or fairness improvement. It uses the existing lock mechanism rather than introducing another ownership service. Database copy bounds are 64 MiB for the main file and 128 MiB for the journal; larger or ambiguous recovery cases are refused.

The contract is cooperating API users on a private local filesystem. It does not fence unrelated SQLite connections, raw file replacement, malicious writers, path aliases outside the resolved API identity, or arbitrary tools holding handles to the same file. Do not delete sidecar locks while runners may exist. A process dying during the private recovery-copy step may leave a private `.adaptive-task-recovery-*` directory for later inspection; it is not automatically adopted or used to bypass original SQLite recovery.

## Validation and limits

Run from an existing Python 3.11+ environment:

```powershell
python -I -B .\run_cpu_tests.py NEW_RESULT_FILE.json
```

The runner explicitly imports only this prototype's source. It runs the existing TaskStore, demand, persistent-feedback and published mailbox tests, plus new SQLite/OS-lock regressions and source-preservation checks. The final combined Windows/Python 3.11/SQLite 3.45.1 run passed **75 tests in 8.060 seconds**: 22 mailbox, 15 demand, 7 persistent feedback, 11 TaskStore, 17 new verification regressions, and 3 preservation checks. See `cpu-result.json`. Harmless owned child processes create actual interrupted SQLite transactions and demonstrate lock release after process exit. There is no model, native inference owner, GPU load, UI action, network service or runtime qualification.

New tests cover overlapping readers and writers, multiple readers during checkpoint writes, bounded contention, process-exit release, original hot-journal rollback, exact-error-code fallback, foreign same-header hot journals, an interrupted transaction that replaced a foreign schema, super-journal refusal, copy/validation/cleanup failures, private copy placement, size bounds, and both WAL layouts. On rejection, the original database and journal hashes remain unchanged in the corresponding fixtures.

The interrupted replacement-schema test does not claim SQLite physically spilled the uncommitted schema page into the main file. An earlier fixture attempted to assert that stronger premise and failed; its source and result are preserved under `pre-cpu-01/`. The correction retains the actual interrupted transaction and tests recovered committed-schema refusal without overstating that premise. The same first run also had a test-wrapper argument-name collision, corrected without weakening the implementation contract. First CPU result: 48 tests, two fixture errors. Second result before mailbox/preservation additions: 50 tests passed.

Windows tests alone do not establish POSIX behavior. Linux/macOS CI must run the same lock, WAL and hot-journal tests before portability is claimed. This successor must be independently reviewed before being rebased into the qualification runner. Existing frozen qualification packages, accepted M1 evidence and canonical source are unchanged.

## Research and attribution

Research-first review was performed on 2026-10-24. The accompanying `research-design.md` preserves the original design analysis; the exclusive-lock WAL correction described above is a subsequent evidence-backed refinement. SQLite itself performs all parsing, transactions, integrity checks and recovery.

- [SQLite URI parameters](https://www.sqlite.org/uri.html): immutable promise and warnings.
- [SQLite corruption guide](https://www.sqlite.org/howtocorrupt.html): consistent paired copying and POSIX raw-close hazard, especially §1.2, §1.4 and §2.2.
- [SQLite locking and hot-journal algorithm](https://www.sqlite.org/lockingv3.html).
- [READONLY_ROLLBACK result code](https://www.sqlite.org/rescode.html#readonly_rollback).
- [SQLite WAL documentation](https://www.sqlite.org/wal.html): readonly sidecar creation (§5), exclusive mode avoiding shared memory (§8).
- [SQLite 3.45.1 pager source](https://raw.githubusercontent.com/sqlite/sqlite/version-3.45.1/src/pager.c): `readSuperJournal`, `pager_playback`, `pager_delsuper`, and readonly recovery failure releasing the lock. SQLite source is public domain; the eight-byte refusal guard is derived from this existing format, not a recovery parser.
- [Python 3.11 sqlite3 exception metadata](https://docs.python.org/3.11/library/sqlite3.html#exceptions).
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html): rollback and super-journal semantics.

The original TaskStore transaction/revision pattern retains its existing attribution to medking82's Strata PR #1136, `serve/chat_archive.py` at commit `64d119cd602ddc439c311dedf61fda460f2785ef` (MIT). See the unchanged source header and `third_party/strata/LICENSE`. No new claim of upstream authorship is made for the operation gate or verification correction.
