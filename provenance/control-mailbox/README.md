# Task-control source lineage

This directory preserves the exact implementation and fixture sources used in
the component's review. It is not a live M2 qualification receipt.

- `predecessor/` retains the original helper and tests before the concurrent
  status-read correction. A status reader could read old requests followed by
  newer acknowledgements and falsely report corruption.
- `reviewed/` retains the corrected helper and its 18 fixtures. The corrected
  read order captures acknowledgements before the append-only request list.
  Every acknowledgement follows its request commit; a newer request list can
  therefore contain additional requests without invalidating the older prefix.
- `independent/` retains four separately authored boundary tests: ended owners,
  active validation, failed acknowledgement writes and new requests arriving
  during an earlier acknowledgement.
- `source-lineage.json` binds these exact files and records the TaskStore and
  demand revisions inspected. Private manifests with local paths are omitted.
- `snapshot-reviewed/` retains the coherent snapshot implementation and the
  exact `DataFixture` and five-test `SnapshotTests` class excerpt used in the
  later promotion. The excerpt is historical source, not a standalone test
  entry point. `snapshot-lineage.json` binds these bytes, records the complete
  original fixture file's hash and identifies the selected classes.

The initial production module differed from `reviewed/` only in its documentation
link. The snapshot promotion adds a single-transaction read API and shares the
existing status-result calculation without changing control writes or ownership.
Its production implementation is byte-identical to `snapshot-reviewed/` at
promotion. The original portable test module combines all 22 fixture methods unchanged, uses
the canonical package import and removes private path/dependency-hash setup.
At promotion, `tests/test_control_mailbox_snapshot.py` retained the selected
fixture classes unchanged and supplied only their portable imports and constants.
Run the current tests under `tests/`; the archived test entry points retain
their historical layout and are evidence, not installed commands. The existing
CI test discovery runs the portable tests on Windows, Linux and macOS with
Python 3.11 and 3.12. Test results and CI acceptance must be read at their actual
revision; storing these sources alone does not establish a pass.

All preserved component and fixture code is Apache-2.0. The runtime reuses
TaskStore's already-attributed MIT transaction/revision patterns; the original
Strata source and license remain under `third_party/`. No new external code or
service dependency is introduced. See [the component contract](../../docs/task-controls.md)
for research references, authority limits, finite storage and integration work.

## Snapshot fixture completion guard, 1 November 2026

At `fbc78b934df13f205eb5a1a2da2bff23e6843752`, the original
[Windows 3.11 push job](https://github.com/midhatn/adaptive-inference/actions/runs/41267272612/job/124732589702)
failed the snapshot fixture's final thread-completion assertion after its
four-second joins. The read-entry, writer-start and 50-millisecond non-commit
checks had passed. The log does not identify the remaining thread or the exact
slow operation; the original attempt remains failed.

The prospective fixture gives each retained thread join a named 30-second
completion guard and reports reader/writer liveness and caught failures if the
guard expires. This follows [CPython 3.12.10's short test timeout](https://github.com/python/cpython/blob/v3.12.10/Lib/test/support/__init__.py),
without copying or importing its implementation. The old four-second join was
shorter than TaskStore's existing five-second individual SQLite wait, and was
not a product latency contract. This comparison does not establish the cause
of the original failure. The read barrier, 50-millisecond non-commit check,
before/after snapshot assertions, runtime SQLite timeouts and all archived
source bytes and hashes remain unchanged. Current fixture checks and subsequent
hosted CI retain their own validation scope.
