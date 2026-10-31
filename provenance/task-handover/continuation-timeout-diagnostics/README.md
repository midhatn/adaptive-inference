# CPU continuation timeout observations

This test-only change follows the original Windows 3.12 push failure at
`4d2f5a767d58b4fadaab539438f9bfe9211d6615`:
[run 41092525579, job 124189817789](https://github.com/midhatn/adaptive-inference/actions/runs/41092525579/job/124189817789).
Its five-second continuation wait raised `TimeoutError`; the same source tree
passed the corresponding PR job. The aggregate remains 13 successful jobs and
one failed job. New diagnostics do not explain or erase that original failure.

The fixture retains its exact wait, success assertions, Stop fencing, process
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
