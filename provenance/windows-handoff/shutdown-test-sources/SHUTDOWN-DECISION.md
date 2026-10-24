# Private successor v6: orderly shutdown and complete receipts

Date: 2026-10-24. This is a bounded correction for review before a fresh qualification run. Controlled-10 and its failed exporter receipts remain unchanged and are **not fully accepted**. CPU fixtures below do not establish M1 acceptance, resource performance, or installed-agent recovery.

## Research and reuse

Before implementation, reviewed the official [aiohttp graceful-shutdown documentation](https://docs.aiohttp.org/en/stable/web_advanced.html#graceful-shutdown), served as aiohttp 3.14.5 on this date. Its established sequence rejects new connections, lets running handlers finish, and then cleans up resources. Reuse the distinction between closing admission and waiting for existing ownership; keep the project's existing scheduler and native acknowledgment mechanism.

Also reviewed the official [CPython asyncio Queue.shutdown documentation](https://docs.python.org/3/library/asyncio-queue.html#asyncio.Queue.shutdown), served as Python 3.15.1. A normally shutting-down queue refuses new puts while allowing existing work to wind down. The documentation warns that immediate shutdown can invalidate unfinished-work accounting. This API was introduced in Python 3.13: this project uses Python 3.11, so no new API or dependency is introduced. This is design guidance only; no upstream implementation was copied.

Existing implementation inspected: canonical `src/adaptive_inference/scheduler.py`, `handoff.py`, and the frozen v5 `native/windows_host.py` plus `run_validation.py`. Canonical checkout HEAD at preparation was `ed261587234ec9938f680acc460bfdef26ceb419`; exact copied file hashes in `shutdown-predecessor-source-manifest.json` bind any local working-tree content independently of that commit. Canonical code is Apache-2.0; the unmodified license is retained in `runtime/LICENSE`.

## Evidence and bounded changes

Controlled-10 reached application outputs, but the full exporter refused `invalid_handoff_transition`: closing the scheduler while an awaited native stop finished caused `_gateway_open` to label clean shutdown as `gateway_completion_unreconciled`. The harness also captured its final controller history before awaiting `host.close`, omitting events appended during cleanup. These are real acceptance failures, not permission to relax the exporter.

1. Missing scheduler or uncertain completion still latches the existing fault. Known clean `scheduler.closing` returns closed admission without creating a fault. Stop still requires identical owner, all retained exits, cleanup acknowledgment, and free listener before a release event and parked state. Closing prevents restoration or a new grant. An already-running start retains its verified identity for host-owned cleanup, with admission closed.
2. The harness awaits controlled-host close and captures the full controller ledger afterward in `finally`, including when close fails. It rejects a controller fault before setting the provisional success value and after cleanup. Independent review found that an active request can finish uncertain after the controller drive loop exits; the helper therefore also checks the actual scheduler independently after close: closing, no active owner, no pending requests, and no uncertainty. A cleanup failure makes the receipt fail; if a primary operation already failed, that original exception remains the raised cause and the separate cleanup error remains in the receipt.
3. Native v4 ownership/host source and foreground helpers are copied byte-for-byte from v5. The model, quality controls, prompts, expected answers, and all prior harness functions except `main` are unchanged. `close_controlled_host` is the sole added harness function. Its normal package imports remain portable.

The separate `runtime/src/adaptive_inference` snapshot exists only to qualify the core correction privately. CPU tests select it through `PYTHONPATH`; the harness does not hard-code that location. Promotion of reviewed core files, publication, and any real run belong to the parent coordinator. No canonical, sealed native package, historical receipt, or exporter file was edited here.

## CPU validation

Using the existing Python 3.11 project environment with `PYTHONPATH` pointing at this successor's `runtime/src`:

```powershell
python -m unittest discover -s runtime -p test_handoff.py -v
python -m unittest test_shutdown_receipts test_arithmetic_feedback -v
python -m unittest discover -s native -p test_windows_host.py -v
```

From the successor-v6 directory: 34 handoff tests, 20 harness/feedback tests, and 14 existing host-composition tests pass. The handoff suite covers closure while stop acknowledgment is blocked, active-request ownership retained until release, rejection of queued/new work, uncertainty during closure, refusal of restoration after closure, and unchanged unsafe native proof failures. Harness tests cover post-close events, terminal-fault rejection, late scheduler uncertainty after the actual host fixture's drive loop exits, preserving primary and cleanup failures separately, and unchanged native/helper sources. The feedback tests retain the same rejected-answer evidence and unchanged IQ3_S quality/acceptance contract. These tests use fixtures and loopback fake components; no real inference model, UI, or native process qualification is launched.

## Next acceptance boundary

Independent review must confirm the frozen hashes and exact changes. Only then may the coordinator promote the core correction and run a fresh controlled qualification with a fresh installed-agent task. The full exporter must still reject fault transitions, incomplete ledgers, uncertain ownership, invalid foreground evidence, altered model/task acceptance, unsafe recovery, and missing cleanup. Earlier failed runs remain historical failures.
