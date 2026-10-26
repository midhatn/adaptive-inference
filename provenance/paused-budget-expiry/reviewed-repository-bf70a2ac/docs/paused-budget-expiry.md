# Safe expiry of a paused execution budget

An always-on agent needs to distinguish a finished task from an unfinished task
whose current execution budget has ended. This implementation preserves a safely
paused task when its original execution deadline arrives. The task stays pending,
the saved work stays intact, and the window remains available for **Stop engine**.
It does not grant more execution time or automatically resume the task.

For example, a report agent may have safely written its output and then received
Pause while you use another application. If it remains at that verified boundary
until the original 900-second execution deadline, the worker can close its owned
resources, seal that execution, and exit with a distinct verified outcome. The
host continues running. The existing paused-demand policy parks the model when
its own safe-release conditions are satisfied; expiry itself is not evidence
that memory or GPU resources have already been released.

This change has deterministic component coverage. Its first installed expiry
trial was rejected: the host and worker used different Windows clock domains,
and the host correctly refused a seal timestamp that appeared to be in its future.
The saved deadline itself matched. That failed trial and its exact build remain
preserved; it is not an accepted expiry result. A new installed qualification
must independently exercise the original 900-second deadline with the IQ3_S
model before an installed expiry acceptance claim is published. Earlier cold/full
acceptance records remain evidence for their exact predecessor builds.

## What must be proved

The owner must have observed the exact applied Pause **before** the saved
deadline, after a coherent read of its complete request/acknowledgement prefix.
That observation binds the owner epoch, target revision, Pause identifier and
sequence, and prefix digest. A slow read cannot backdate the observation.
A changed prefix, Resume, allowed work, uncertainty, or a new owner invalidates
it. A Pause that first becomes visible at or after the deadline cannot qualify.

At expiry the worker retains ownership while it:

1. Verifies the existing checkpoint, native conversation, effects, and validation
   feedback have reached a safe boundary, with no unresolved operation or request.
2. Retains the exact Hermes token-writer thread before agent cleanup can clear its
   reference, checks the existing bounded queue flush, and closes the writable
   native database. A live or replaced writer, busy queue, or unknown close fails.
3. Reopens the native history through the same pinned Hermes SDK in read-only
   mode, verifies the final projection and existing effect receipts, closes that
   reader and the provider, and commits the execution seal.
4. Releases the TaskStore owner and completes outer cleanup. Only then may it
   publish the successful expiry receipt and return the dedicated exit code 5.

The host still has to join the exact retained worker and verify its receipt
against the released durable checkpoint. A candidate Pause, a receipt file by
itself, a process identifier lookup, or a generic deadline exit is insufficient.
Any cleanup error forces ordinary failure, including an error after the seal was
committed. A failure after receipt replacement can leave honest evidence on disk;
the retained non-5 process exit prevents accepting it as a safe expiry.

## Atomic controls and the execution seal

The optional checkpoint field `adaptive_inference.execution_outcome.v1` records
the original deadline, the earlier Pause observation, the seal time, exact owner
and Pause identity, and the complete prefix digest. Its pre-seal state hash covers
the entire prior state; it does not hash itself. The external receipt binds the
complete sealed state. Existing task history, prompt, output, feedback, native
conversation, effects, and request budget remain in place.

Both appending a control and sealing execution use the existing TaskStore SQLite
write transaction. If the append commits first, the unacknowledged suffix prevents
sealing. If the seal commits first, the new command is known **not recorded**.
This is a typed result, not a fabricated owner acknowledgement or an uncertain
transport exception. Looking up an already recorded identifier still returns its
real prior result. Tasks with no seal retain their earlier mailbox semantics.

The UI distinguishes this refusal from an unsent local click and from an unknown
dispatch. Once it observes `budget_expired`, Pause, Resume, Cancel and their retries
are unavailable; Stop remains available. A stale asynchronous Resume-authority
read cannot reactivate intent at or after the original deadline, even before the
host has refreshed the seal. Startup, replacement and recovery also refuse that
sealed execution. No code path resets its deadline to create another 900 seconds.

## Reused mechanisms and limits

The distinction between timeout and cooperative cancellation follows the useful
separation described by [Temporal's activity-failure documentation](https://docs.temporal.io/encyclopedia/detecting-activity-failures).
Durable pause state is informed by [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).
Neither system is a runtime dependency, and this implementation does not adopt
their retry or replay behavior. The atomic append/seal boundary uses SQLite's
existing [transaction](https://www.sqlite.org/lang_transaction.html) and
[isolation](https://www.sqlite.org/isolation.html) guarantees.

The nested cleanup order follows Python's
[with-statement semantics](https://docs.python.org/3.11/reference/compound_stmts.html#the-with-statement)
and [context manager rules](https://docs.python.org/3.11/library/contextlib.html#contextlib.contextmanager):
the inner expiry finalizer runs while the outer TaskStore owner is still held,
and its result stays provisional through the outer owner's exit. The host reuses
its retained [shielded asynchronous tasks](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation)
and existing thread offloads; no second process supervisor or database is added.

Hermes integration uses Nous Research's MIT-licensed
[Hermes Agent at commit 14e1e43a23761b369641208e204365cd6cb9399d](https://github.com/NousResearch/hermes-agent/tree/14e1e43a23761b369641208e204365cd6cb9399d),
specifically the supplied SessionDB ownership and cleanup behavior in
[run_agent.py](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/run_agent.py),
[hermes_state.py](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_state.py),
[hermes_state_usage.py](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_state_usage.py),
and the existing native-message projection. The selected source hashes and
attribution are retained in [the local provenance record](../provenance/paused-budget-expiry/README.md).

Queue-idle and thread-exit checks do not prove billing or usage-counter persistence;
that SDK path can handle its own write failures separately. This change makes no
billing guarantee. It also does not establish reboot recovery, automatic budget
renewal, safe active-work expiry, general checkpoint replay, or complete M2
qualification. Active, ambiguous, incomplete, or late-Pause expiry remains a
failure with preserved evidence.

## Shared execution time and deliberate Pause activity

The installed host uses CPython 3.11.9 and the installed Hermes worker uses
CPython 3.14.7. Their default Windows monotonic clocks differ. The successor uses
the standard `time.perf_counter()` for every operand of the shared execution
deadline, backed by Windows QueryPerformanceCounter in both supported runtimes.
Fresh plan, metadata, state, bootstrap and version 2 expiry proofs bind the explicit
`windows-qpc-seconds-v1` domain. The installed path rejects an untagged or different
domain before claiming the saved task; it never converts an older deadline or
grants a replacement budget. Historical version 1 seals keep their original reader
and blocking semantics. Local elapsed timers and asyncio scheduling keep their
own clocks. This remains a same-machine, same-boot contract, not reboot recovery.

This follows the standard [Python3.11 performance-counter contract](https://docs.python.org/3.11/library/time.html#time.perf_counter),
the [Python3.14 clock documentation](https://docs.python.org/3.14/library/time.html#time.monotonic),
and [Microsoft's QPC guidance](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps).
No clock tolerance, wall-clock deadline, global clock replacement or interpreter
upgrade is used to make a proof pass.

The first trial also exposed a separate integration issue: Hermes' existing
600-second watchdog treated a deliberate long Pause as a stalled turn. The repair
reuses its pinned activity method only after the current owner has successfully
verified a complete safe Pause and its still-live SDK session lease. At most once
every 15 seconds, before the original execution deadline, that serialized owner
reports that it is waiting at an acknowledged Pause. It does not report model or
tool progress, renew the SDK lease, start a heartbeat thread, disable the watchdog,
or change its timeout. A blocked or failed read cannot emit activity.

An admitted interruption, changed or expired lease, or unknown authority is
latched as a failure. The finalizer checks both that latch and the pinned SDK's
retained interruption evidence before cleanup, because SDK unwinding can clear
temporary interrupt flags. A verified normal SDK return explicitly enters a
post-turn state so the existing final task-acceptance check still works after
the SDK has released its lease.

The adopted behavior comes from the MIT-licensed pinned Hermes
[activity tracking](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/activity_tracking.py),
[turn watchdog](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_liveness.py),
[lease lifecycle](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_facade_lease.py),
and [interrupt control](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/interrupt_control.py).
Exact source pins and the failed predecessor are retained in the
[clock-successor provenance](../provenance/paused-budget-expiry/clock-successor/README.md).

## Tool-thread handoff and timeout cleanup

The next installed trial exposed a different integration boundary: Hermes runs
even sequential tools on a worker thread. The corrected guard follows the
existing Recovery lock and exact logical task claim, with a short-lived scope
around each synchronous control operation. It does not require the thread that
constructed the adapter. An unrelated caller, released claim, changed epoch or
revoked callback cannot report activity or authorize another effect.

The pinned [Hermes tool executor](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/tool_executor.py)
can return a timeout while its callback is still running. The repair therefore
also checks the SDK's existing [worker interruption signal](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/interrupt.py).
It preserves an observed failure even after the SDK clears a transient signal.
Cleanup revokes late callbacks and must acquire the same lock immediately;
otherwise it reports unconfirmed cleanup. The final authority check, SDK close,
native readback and seal all remain inside that lock. This follows Python's
[RLock ownership](https://docs.python.org/3.11/library/threading.html#rlock-objects)
and [Future cancellation semantics](https://docs.python.org/3.14/library/concurrent.futures.html),
without changing Hermes's executor or timeouts.

The [thread-successor record](../provenance/paused-budget-expiry/thread-successor/README.md)
preserves the failed source and exact changes. The dispatch fixture uses the
actual pinned SDK runner, worker pool, context propagation and interruption
registry, with real task ownership and a reduced native-history database.
Successful reads/writes and rejected abandoned callbacks are component evidence;
the complete installed expiry workflow remains a separate acceptance gate.
