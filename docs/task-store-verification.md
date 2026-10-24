# Task-store verification and recovery

Task records can be read by the controller while a worker saves progress or a
user requests Pause. Verification must participate in the same locking rules as
those operations. This correction reuses SQLite transactions and the existing
stable store lock; it does not introduce another database or recovery engine.

## What changed

The existing `.init.lock` now covers each complete short store operation,
including verification, commit or rollback, and closing SQLite connections.
Waiting for this gate is bounded at five seconds. A task owner does not hold it
while waiting, generating text or running tools, so a pause request can still be
saved while that owner retains its separate task claim.

Normal verification uses SQLite's ordinary read-only connection and a read
transaction. It no longer promises that a changing database is immutable or
opens and closes the main file independently while another cooperating SQLite
connection might hold POSIX locks. Exact schema, application identity, DELETE
journal mode and integrity checks remain required.

Only SQLite's specific `SQLITE_READONLY_ROLLBACK` result allows recovery
inspection. With cooperating operations quiescent, bounded database and rollback
journal copies are placed in a private subdirectory beside the original. SQLite
recovers and verifies this pair first. Only after that verification and temporary
cleanup succeed may SQLite recover the original. No application code parses
pages, replays SQL or transplants recovered pages.

The copied journal must not end in SQLite's super-journal magic suffix. The
upstream format requires that suffix for an external super-journal reference;
conservatively refusing every match prevents copied recovery from following such
a reference. An accidental suffix match can therefore refuse an otherwise valid
journal. The main-file limit is 64 MiB and the recovery-journal limit 128 MiB.

WAL layouts are unsupported. Existing WAL/SHM files are refused, and
connection-local exclusive locking is requested before the first read to avoid
creating shared-memory files when inspecting a clean WAL database. Verification
also requires DELETE mode. Other SQLite errors never authorize recovery.

## Upgrading an existing installation

**Stop and join every older TaskStore worker and reader before using this
version on its stores.** The older implementation does not honor the short
operation gate. The host, controls and replacement workers must all use the
corrected module. Mixed-version access or recovery during an upgrade is unsupported.

There is no schema migration or reset. Keep the existing database, journal and
lock sidecars together. Preserve the original objective, ownership epochs,
revision history, attempt budgets and unresolved operation receipts. Never delete
lock files while a runner may exist. For a retained historical qualification, use
its [preserved runtime](../provenance/persistent-desktop/README.md) in isolation,
with no concurrent current-version process opening its stores.

The contract covers cooperating API users of one resolved path in a private
local directory. It does not fence unrelated SQLite writers, raw replacement,
malicious processes or uncoordinated hard-link aliases. The gate serializes reads
and writes; throughput and fairness improvements are not claimed. Its acquisition
deadline is not a hard bound on filesystem latency. An interrupted recovery-copy
operation can leave a private `.adaptive-task-recovery-*` directory for inspection;
that directory is never automatically adopted.

## Evidence and research

The reviewed Windows component passed 75 supplied tests and four independent
probes. The canonical suite adds 17 verification regressions and those four
independent cases, without duplicating inherited tests. They exercise actual
SQLite transactions and bounded child processes, including interrupted writes,
lock release, concurrent readers, exact-error recovery, foreign-schema refusal,
copy failure, WAL refusal and a mailbox request while a task remains claimed.
Foreign-file assertions concern the database and journal bytes and WAL/SHM files;
the stable API lock sidecar may legitimately be created.

One earlier composed fixture reported an unexplained verification error. Subsequent
diagnostics did not reproduce it. The correction addresses two independently
established unsupported access patterns; it does not establish that error's cause
or convert that run into a pass. Earlier failed producer fixtures are retained in
the [source archive](../provenance/task-store-verification/README.md).

Linux/macOS CI and a fresh installed-agent IQ3_S composition are separate gates.
This component result is not a real-model, reboot, power-loss or arbitrary-tool
recovery claim.

Research first inspected SQLite's [URI rules](https://www.sqlite.org/uri.html),
[locking and hot-journal recovery](https://www.sqlite.org/lockingv3.html),
[corruption guide](https://www.sqlite.org/howtocorrupt.html),
[READONLY_ROLLBACK](https://www.sqlite.org/rescode.html#readonly_rollback) and
[WAL rules](https://www.sqlite.org/wal.html). The exact public-domain
[SQLite 3.45.1 pager source](../third_party/reference-sources/sqlite/189e44dfecdc7868bb860dfb5d98eab371318c37/src/pager.c)
and its original notice are preserved locally. The existing transaction/revision
pattern retains its [Strata attribution](task-survival.md); this change adds no
claim of upstream authorship for the operation gate.
