# Continue a task after its resource-wait budget expires

**Status: source and component development; installed IQ3_S qualification of
this extension remains pending.** Earlier paused-task and model results keep
their original build identities. The prior failed ordinary-task trial (case06)
remains failed.

Suppose an agent has read the input file, then waits because the computer's
resources are unavailable. Its execution budget ends before it can ask the model
for the next step. The saved read and conversation should survive, the controller
should remain available, and Stop should close the service cleanly. A subsequent
explicit **Continue saved task** should continue the original objective.

This extension connects that case to the existing task store, control mailbox,
cleanup checks and continuation mechanism. It does not complete an unfinished
task or silently renew its budget.

## What is preserved

Safe expiry requires a saved, undispatched request at the admission boundary,
with no unresolved generation or tool operation. The exact owner and checkpoint,
original deadline, pending request, conversation, completed tool results and
cumulative counters are checked. Resources must close, queued writes must drain,
and a read-only native-history check must agree before the execution is sealed.
The host then joins the retained worker and verifies its result.

The seal records the actual control-request and acknowledgement prefix in the
same existing SQLite transaction used to append controls. A late unapplied Pause
can remain visible without inventing an acknowledgement. Pending Resume or Cancel
conflicts refuse this proof; an already applied cancellation keeps its separate
outcome. An original second task opened in the same service can stop through the
same verified path. Incomplete work still cannot authorize a different task.

There are two closely spaced deadline checks before a provider operation starts.
Both now carry an explicit pre-dispatch expiry type into the existing recovery
boundary. The later transport check occurs after a durable operation begins and
remains a failure requiring reconciliation. HTTP errors, missing evidence and
arbitrary timeouts cannot become a successful expiry by matching their messages.

## How explicit Continue works

The expired execution and its complete pending request stay immutable. An
explicit continuation command creates a separate execution through the existing
authorization transaction, with a new finite deadline and a recorded link to its
predecessor. Duplicate delivery looks up that same authorization; it does not
create another budget or launch.

Hermes's supported saved-conversation entry appends a continuation turn and
builds a new provider request. Accordingly, the grant records that the old
undispatched request is superseded, identifies it by digest, and prepares only
the successor to rebuild from the saved conversation. It does not claim to replay
the old request byte for byte or inject a saved response into a different request.
The original objective, model/quality, inputs, completed effects and cumulative
request limits remain unchanged.

For the current desktop example, each explicit continuation grants another
900-second execution while the eight-request limit remains cumulative. These
are separate from the named media test's bounds. A continued execution can safely
expire again, but its selected-execution lifetime, cleanup and exact result must
all verify before another continuation. Stop retains priority during selection,
launch and readiness, including a committed successor known not to have started.

The UI's available button is a cached indication. The actual command rechecks
the predecessor, control prefix, authorization, released worker and parked native
owner before proceeding. Spent request capacity, an unreleased owner, a changed
prefix, Stop or a retired endpoint cannot grant another execution.

## Delayed acknowledgement observations

A successful database read can be too old to authorize the next step by the time
the controller receives it. Both the installed composition and its CPU-worker
fixture use the same one-second observation lifetime. Waiting for a database lock
or for the host event loop can exceed that interval. The Windows check on
`9308707` failed at this boundary; its log lacks the timestamps needed to identify
the exact failed freshness clause. A separate deterministic reproduction aged one
otherwise real worker/database observation and reproduced the permanent failure.

The selected-worker acknowledgement loop can discard only a structurally valid,
correctly bound, ordered observation that has expired. It reads again within the
same execution deadline and retained worker lifetime. It never installs the old
read, accepts its acknowledgement, renews its timestamp, sends another Resume or
launches another child. The previous validated cache and intent remain unchanged;
the new read cannot create authority. Stop and lost user intent still end the wait.

Malformed timestamps, wrong task identity, backward history and actual database
errors still fail. Ordinary refresh, observations after a control write, and the
final readiness check retain their strict behavior. The worker cannot dispatch
until fresh acknowledgement and the separate identity/capacity readiness checks
pass. A read that finishes after the execution deadline cannot authorize progress.

This uses the existing serialized, retained database task. Python's
[thread offload](https://docs.python.org/3.12/library/asyncio-task.html#asyncio.to_thread)
does not guarantee delivery latency, and
[shielding](https://docs.python.org/3.12/library/asyncio-task.html#shielding-from-cancellation)
keeps a cancelled caller from abandoning that retained task. SQLite's
[busy timeout](https://sqlite.org/c3ref/busy_timeout.html) documents bounded waiting
before a lock failure; it is not a guarantee that a successful read remains fresh.
These are API references, not copied implementations or a change to either timeout.

## Reproduction and evidence boundaries

After installing the checkout as described in the repository's reproduction
guide, the focused portable cases can be run with:

```text
python -B -m unittest discover -s tests -p "test_*wait*.py"
python -B -m unittest discover -s tests -p "test_prebegin_deadline_edges.py"
python -B -m unittest discover -s tests -p "test_sdk_rebuild_pins.py"
python -B -m unittest discover -s tests -p "test_continuation_observation.py"
```

These exercise real SQLite state and current worker/control code with explicitly
scripted external boundaries. They cover preserved progress, repeated execution
generations, late controls, result/cleanup failures, deadline crossings, bounded
accounting and continued task versus new-task authority. They do not establish
real model completion, native release, GUI behavior or survival across a reboot.

The separate [Hermes saved-history SDK check](../examples/validation/hermes_saved_history/README.md)
uses the actual pinned conversation prologue, request builder and public
middleware with a scripted terminal response. It also checks source and import
origins. The complete installed agent and real IQ3_S workflow need their own
fresh package, identities and acceptance run. See the [evidence ledger](evidence.md),
[explicit continuation contract](explicit-continuation.md) and [roadmap](../PLAN.md).

## Research and reuse

This reuses the existing TaskStore and mailbox
[SQLite transaction/isolation](https://www.sqlite.org/isolation.html) boundaries,
resource-close/readback routine and retained-child lifecycle. The distinction
between a logical task and a new execution follows the already cited
[Temporal Continue-As-New model](https://docs.temporal.io/develop/python/workflows/continue-as-new).
The SDK behavior is checked against Hermes's pinned
[turn facade](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_facade.py)
and [turn context](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/agent/turn_context.py).

Typed handling and preserved causes use ordinary
[Python exception dispatch/chaining](https://docs.python.org/3.14/builtins/exceptions.html#exception-context).
[HTTPX's timeout hierarchy](https://www.python-httpx.org/exceptions/) provides a
precedent for distinguishing phases, but an HTTP timeout is not evidence of
non-dispatch here. Only the local pre-operation boundary supplies that fact.
No new scheduler, provider executor or automatic renewal loop is introduced.
