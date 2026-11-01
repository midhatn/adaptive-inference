# CPU continuation timeout observations

This test-only change follows the original Windows 3.12 push failure at
`4d2f5a767d58b4fadaab539438f9bfe9211d6615`:
[run 41092525579, job 124189817789](https://github.com/midhatn/adaptive-inference/actions/runs/41092525579/job/124189817789).
Its five-second continuation wait raised `TimeoutError`; the same source tree
passed the corresponding PR job. The aggregate remains 13 successful jobs and
one failed job. New diagnostics do not explain or erase that original failure.

At that revision, the fixture retained its exact wait, success assertions, Stop fencing, process
identity checks, child watchdog and product execution deadlines. With the
existing `CONTINUATION_TEST_RECEIPTS` opt-in, a timeout records the current phase,
task state, one suspended source location and retained child PID/creation/poll
values before teardown. It does not cancel the shielded task. After exact joins
and closed streams, it summarizes only bounded, allowlisted fields from the
existing fixture event, bootstrap and result files. Missing/invalid diagnostic
files and capture failures retain only error types; the original timeout remains
an error. No frame locals, source text, arbitrary JSON content, exception messages
or task representations are added. No new database snapshot or ACK-history read
is performed; these observations do not provide a full transition timeline.

The implementation adapts the existing opt-in child receipt and injected-error
cleanup fixtures. Python's documented [`wait_for` and `shield`](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.wait_for)
semantics explain why the underlying task can remain live after this timeout.
[`Task.get_stack`](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.Task.get_stack)
provides a bounded suspended source location; it is not an awaited-coroutine
trace or a cause diagnosis. The [CPython 3.12.10 implementation](https://github.com/python/cpython/blob/v3.12.10/Lib/asyncio/tasks.py)
was checked against the failed job's interpreter. These are API/documentation
references; no external implementation was copied. Existing repository code and
its license are reused.

`source-lineage.json` preserves the four preceding files and every existing
runtime module and historical manifest. `replacements.json` reverses the entire
change to each previous file, including all historical assertions. The new outer
input view accepts only pinned complete successor bytes; unknown input reaches
the unchanged inner validator and fails there. Legacy disposable roots may lack
this new archive, so that outer view passes their bytes through without claiming
that they are accepted. Retained predecessor files are parsed, never executed.

Focused tests cover a real deliberately held CPU continuation, its unchanged
timeout, normal exact-child cleanup, capture failures, sensitive-field omission,
bounded file reads, and the affected historical source consumers. This is fixture
diagnostic validation, not a hosted CI retry, runtime fix, native-resource test,
installed-agent test, model result, or qualification of the physical scenario.

## Fixture startup ordering correction, 1 November 2026

At `75ad10893ac2a3aa5d286ff7fb971f530739429e`, the original hosted runs
finished with 12 successful jobs and two Windows 3.12 failures. The
[PR job](https://github.com/midhatn/adaptive-inference/actions/runs/41264358030/job/124723949288)
timed out before the diagnostic fixture entered its deliberately held transition.
Its ordinary continuation test had passed earlier in the same job. The exact
pre-hold delay remains unknown. The nested receipt was unavailable because its
export followed the failing assertion.

The diagnostic fixture now signals entry with the existing
[`asyncio.Event`](https://docs.python.org/3.12/library/asyncio-sync.html#asyncio.Event)
pattern and awaits that setup precondition before starting the inherited,
unchanged five-second timeout. It preserves the nested receipt before asserting
the outcome. A startup failure cannot count as the deliberately injected timeout.
The product, ordinary continuation test, execution deadlines and exact-child
cleanup requirements are unchanged.

The separate [push job](https://github.com/midhatn/adaptive-inference/actions/runs/41264353438/job/124723935004)
failed waiting for an injected authority-read signal. Its targeted test now
awaits entry to the held authority read before the existing signal check, then
awaits the retained control operation before checking that session rotation
prevented late activation. The public handler may already have returned a pending
reply; that reply is not the operation's completion. This uses the existing
shielded-task join pattern and changes no shared runtime or freshness limit.
The cause of the original precondition delay is still unknown. Both original
failed runs remain failed; local fixture checks and later CI have their own scope.

## Whole-fixture orchestration guard, 1 November 2026

The later original [Windows 3.12 PR job](https://github.com/midhatn/adaptive-inference/actions/runs/41266470933/job/124730206654)
at `5ccf7391dd07723ab8c3ce5d6553ab9cd624dec4` failed the ordinary continuation
test's five-second wait. This time its diagnostic receipt was preserved. At the
timeout, the transition was `preparing`, the task was pending and not cancelled,
and only the original, already-exited worker was present. There was no successor
child before or after cleanup. The subsequent cleanup observation was 0.312
seconds later, with the original child joined and not forcibly stopped.

That phase includes grant-file staging and the derived Pause submission before
successor launch. The retained outer stack does not identify which awaited
operation caused the delay. It is not evidence of a slow successor import,
model execution, or a proven product defect. The original CI attempt remains
failed; no result is retrospectively accepted.

The ordinary test now names its whole-fixture orchestration guard and gives it
30 seconds. Its purpose is to bound filesystem, SQLite, scheduling and child
work while checking continuation semantics, not to assert a five-second product
latency. This follows the distinction in [CPython 3.12.10's test support](https://github.com/python/cpython/blob/v3.12.10/Lib/test/support/__init__.py)
between test timeouts and hang detection, and reuses its 30-second short timeout
as a reference. No CPython implementation is copied or imported.

The deliberately held diagnostic subclass explicitly retains five seconds,
along with its entry barrier and actual timeout/cleanup assertions. Product
deadlines, the 15-second CPU-child watchdog, readiness limits, exact ownership
and every continuation success assertion remain unchanged. The existing
[outer source view](../../task-preparation/source-lineage.json) reverses only
the declared guard and reader changes before historical checks; historical
manifests, predecessor bytes and unknown-source refusal remain intact.

## Selected CPU-child emergency guard, 1 November 2026

The original alpha `d5837f9f44dbcf7af3c28149dad0945bc6002f50`
[Windows 3.11 PR job](https://github.com/midhatn/adaptive-inference/actions/runs/41270791467/job/124742964115)
failed the held-transition diagnostic after 244 tests in 263.561 seconds.
Its expected child exits were `[5, 4]`; the actual exits were `[5, 124]`.
The selected CPU fixture had an emergency timer that exits with code 124.
Its retained launch and post-join observations were 674.781 and 689.968 seconds;
the deliberately injected timeout was observed at 680.453 seconds. Both exact
children joined without a parent cleanup kill. The original attempt remains
failed.

The selected result already recorded cooperative Stop and resource-cleanup
fields, but that file is written before `selected.finish(code)` and before the
owned-claim context exits. It does not prove those remaining steps or normal
process exit completed. The exact delayed operation is unknown.

The selected continuation fixture now has a 60-second emergency guard, covering
the already permitted 30-second entry phase, five-second deliberate hold and
20-second cleanup phase with modest headroom. The original-expiry fixture and
its readiness record retain 15 seconds. The distinction between test-completion
limits and hang detection follows
[CPython 3.12.10 test support](https://github.com/python/cpython/blob/v3.12.10/Lib/test/support/__init__.py);
60 seconds is this fixture's phase allowance, not a CPython-prescribed value.
No CPython implementation is copied or imported.

The injected five-second timeout, 20-second diagnostic cleanup bound, retained
child waits, expected exits `[5, 4]`, exact ownership and no-cleanup-kill
assertions remain unchanged. There is no timer lifecycle change, production
runtime change or model-budget change. The existing
[outer source view](../../task-preparation/source-lineage.json) reverses the
host fixture's updated explanatory comment; all earlier source pins and
historical outcomes remain unchanged. This is prospective CPU-fixture work,
not installed-agent, native-resource or model qualification.
