# Serialized task ownership across Hermes tool threads

The second installed paused-expiry trial remains a failure. Its package was
`9ab7743de1f1f9696c19152bdde82c0d7b4da9d0880a42ac91d93348716f5eb6`.
It made one IQ3_S request, then refused a legitimate Hermes tool callback before
the report could be written. The first Pause guard required the thread that had
constructed it, although the pinned SDK dispatches sequential tools through its
existing daemon worker pool. No expiry, task completion or clean Stop is claimed
for that trial.

This successor reuses the adapter's existing Recovery RLock, exact task claim and
SDK interruption API. A safe point belongs to the current serialized operation,
including a legitimate SDK worker, rather than to a constructor thread. The guard
retains its task, process, epoch, session, lease and Pause-prefix checks. Cleanup
revokes further activity and must acquire that same lock without waiting on an
unresolved callback. The lock covers the final check, SDK cleanup, native history
readback and execution seal. No executor, database, timer or budget is added.

Hermes can time out a tool while its callback is still running. Cancelling that
Future is not a join. The guard observes the existing per-worker interruption
signal even when agent-level flags remain false. An observed authority failure
is retained, and cleanup cannot certify an unresolved callback as finished.

`source-lineage.json` pins five changed modules and 49 unchanged runtime files.
The five complete failed predecessor files are preserved under `sources/`. The
test helper accepts only the exact declared successor bytes or AST, restores
those files, then applies the unchanged clock and earlier expiry comparisons.
Historical manifests and hashes remain intact. Mutation checks cover the scope,
interruption and cleanup boundaries. The SDK origin map gains only
`tools/interrupt.py`, taking 19 existing entries to 20.

The adopted dispatch, context and interruption behavior comes from Nous Research's
MIT-licensed [Hermes Agent revision 14e1e43](https://github.com/NousResearch/hermes-agent/tree/14e1e43a23761b369641208e204365cd6cb9399d):
[tool executor](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/tool_executor.py),
[daemon pool](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/daemon_pool.py),
[context propagation](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/thread_context.py)
and [worker interruption](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/interrupt.py).
Exact references are recorded in `sdk-references.json`. No SDK implementation is
copied into production code. All project predecessor/successor files are Apache-2.0.

The actual-dispatch fixture reuses the upstream timeout tests' bounded submit
barrier, so the deadline starts after the callback reaches the intended blocked
safe point. It retains and joins its actual futures and worker threads. It uses
real TaskStore ownership and a reduced SQLite native-history fixture; it does not
construct a full agent or run a model, GUI or backend. Its results remain separate
from the required full installed IQ3_S expiry qualification.
