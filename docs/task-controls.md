# Durable task controls

`adaptive_inference.control_mailbox` lets a trusted host record Pause, Resume
and Cancel while an agent is busy or waiting. The agent's actual task owner
applies the request at a safe checkpoint. A saved request and an applied request
are different states, and callers can inspect both.

This is a portable component. The current launchers and Hermes adapter do not
yet consume these requests. It does not complete the persistent-controller
milestone, interrupt a native process or establish computer-reboot recovery.
The [desktop control library](desktop-control-core.md) supplies the reusable
transport and mailbox adapter for a trusted host; full host/GUI wiring remains
a separate integration.

## Why this uses the existing task store

The reviewed Hermes recovery adapter holds a thread lock throughout provider
admission waiting. A button handler that tried to take that same lock could
wait behind the work it wanted to pause. Instead, this component records a
control request in a separate task record in the **same TaskStore database**.
It uses the existing per-task lock and short SQLite transactions. The requester
does not take the target task's owner lock or the agent's long-held thread lock.

There is no second database, schema or lock implementation. Normal SQLite
contention and the existing connection timeout still apply; recording is not
guaranteed to finish immediately. Busy writers receive an explicit error and
may retry the same request ID.

## Trusted host contract

Create the target's immutable [demand identity](durable-demand.md) first. Then
construct `Mailbox(registry, registration_id, requester_capability=object())`
from trusted host settings. The exact registry binds the store, target task,
logical owner and original arrival. The constructor provisions a deterministic
control-record task alongside that target.

Keep the capability object in the host. A model output, arbitrary task ID,
claimed PID or HTTP header cannot supply it. This object identity check is an
in-process cooperative boundary, not authentication against arbitrary Python
code or same-user database changes. A separate process or network interface
needs its own trusted binding and authentication; none is introduced here.

| Operation | Result |
| --- | --- |
| `submit(capability, request_id, command)` | Persist an ordered `pause`, `resume` or `cancel` request and return its current status. |
| `status(request_id)` | Observe `pending`, `applied` or `rejected`, including whether the owner acknowledged it. No write or ownership claim. |
| `snapshot()` | Read the bound task, mailbox revision, ordered requests, acknowledged prefix and demand together in one existing TaskStore transaction. |
| `consume(owned_task, updated_at_utc=...)` | Apply pending controls in order on the actual owner thread at an application-safe checkpoint. |
| `begin_operation(owned_task, kind, ...)` | Consume controls, refuse blocked work, then use the existing TaskStore operation ledger. |

The requester must retain one stable ID for retries. Repeating the same ID and
command returns the existing result without another write. Reusing an ID for a
different command is refused. Hosts reconstruct the original binding and a new
local capability after restart; they do not recreate the target or reset its
history.

Pause changes demand to `paused`. Resume changes it to `waiting`; that does not
mean the model is ready. Cancel changes it to `cancelled`, which cannot reopen.
Completed inference demand (`fulfilled`) also cannot reopen. Later incompatible
commands receive a recorded rejection. These demand states do not manufacture
TaskStore `accepted` or `exhausted` outcomes.

## What happens around an interruption

The owner first commits the demand transition, then commits its acknowledgement.
These are **two transactions**, not an atomic operation. If it stops between
them, the command remains pending. A replacement owner must consume controls
before doing more work: repeating the same demand transition is an idempotent
no-op, after which the acknowledgement can be saved. Later commands cannot
overtake that unfinished acknowledgement. A failed transition or acknowledgement
must stop the cooperating caller before a new operation begins.

Do not perform another direct demand transition during this gap. Do not clear
an in-flight operation to make cancellation appear successful. Generation,
validation and effects with unresolved outcomes remain subject to the existing
reconciliation contract. A pending cancellation is not proof that they stopped.

The last control read and operation preparation are separate calls. A request
arriving just after that read can remain pending while the selected operation
finishes. Once cancellation is acknowledged, the cooperating operation-entry
path refuses new work. This is cooperative cancellation at a safe boundary;
it is not instantaneous interruption or atomic ordering against every dispatch.

If a task reaches its genuine terminal state before a pending command is
consumed, status reports a rejection derived from that terminal record, with
`owner_acknowledged=False`. Immutable terminal tasks are not rewritten.

## Required agent integration

An empty TaskStore operation field is necessary but may not be sufficient for
an application-safe checkpoint. Hermes, for example, can still be flushing its
native conversation after a provider response completes. Before acknowledging
a control, the host must preserve that history and any verified tool receipt.

The pending integration must:

- Consume old controls before establishing new demand or waiting for a model.
- Poll on the owner thread inside admission waiting and immediately before new
  work, without making a requester wait for the owner's thread lock.
- Check the next tool, duplicate-effect receipt and final-acceptance paths too.
- Consume controls before copying checkpoint state, or reload it afterward.
  Saving an old copy with a new revision can otherwise erase demand and receipts.
- Keep prepared operations, authentic non-dispatch receipts, unknown outcomes
  and scheduler/native ownership rules unchanged.
- Show saved, applied, rejected, cancelled and accepted outcomes accurately.

These controls do not grant resources, authorize tools, reserve GPU capacity or
permit unloading an active model.

## Reading a coherent snapshot

A host that needs the task checkpoint, demand and several control results at
once can use `snapshot = mailbox.snapshot()`, then `snapshot.status(request_id)`.
Both task records are read through the same existing TaskStore connection and
explicit read transaction. The store gate covers that complete read; no nested
`load()` call opens a second connection, and the target's owner lock is not
claimed. Registration identity and the entire acknowledgement prefix are
validated before a snapshot is returned.

The result is detached read evidence. Its fields cannot be reassigned, but
nested task state, request, receipt and demand records are private mutable
copies. Changing them does not write to the database. Keep raw checkpoint
content inside the trusted host and project only the fields a user interface
needs. This is not a reservation: a command can arrive after the read, and the
owner must still consume controls at its next safe boundary.

`status(request_id)` keeps its existing read order and result semantics,
including `KeyError` for an unknown request before acknowledgement validation.
`snapshot()` validates all stored requests and acknowledgements even when the
caller has not selected a request. It does not make the separate demand and
acknowledgement commits atomic.

## Finite bounds

Each mailbox keeps at most **32 lifetime commands**. Full capacity is explicit;
acknowledged requests are not silently removed or rotated. The mailbox uses one
of TaskStore's 1,000 task records and its existing 64-MiB database, 1-MiB record
and 256-revision-per-task limits. Ordinary agent work also consumes revisions.
The host must handle exhaustion without discarding earlier work. Unlimited
history, compaction and automatic archival require a separate contract.

## Validation and research

The portable suite contains 18 producer fixtures and four independently authored
boundary fixtures. They use real TaskStore transactions and ownership with
temporary databases. They cover concurrent recording, duplicate IDs, ordered
controls, both transaction-interruption gaps, replacement owners, active and
unknown operations, control/dispatch races, exhausted bounds and terminal tasks.
Run `python -m unittest discover -s tests -p test_control_mailbox.py -v` after
installing this checkout. There are no model, hardware or installed-agent calls.

Five additional snapshot fixtures use real SQLite and the existing store gate.
They cover one connection without a target ownership claim, detached returned
data, a writer attempting to commit between the two reads, identity and
acknowledgement validation, and terminal rejection semantics. Run them with
`python -m unittest discover -s tests -p test_control_mailbox_snapshot.py -v`.

Independent review found a valid concurrent status read being mistaken for
corruption. Reading the target acknowledgements first and the append-only
requests second preserves a valid prefix. The regression and original sources
are retained in [source lineage](../provenance/control-mailbox/README.md).

Before implementation and review, we inspected Temporal's
[message-passing contract](https://docs.temporal.io/develop/python/workflows/message-passing),
SQLite's [transaction](https://www.sqlite.org/lang_transaction.html) and
[atomic-commit](https://www.sqlite.org/atomiccommit.html) documentation, and the
actual TaskStore and Hermes recovery sources. The recorded-versus-completed
distinction adapts those design references without adding Temporal or copying
its implementation. Existing TaskStore transaction/revision reuse credits
[medking82's Strata implementation](../third_party/reference-sources/README.md)
and retains its MIT source and license. The new coordination code is Apache-2.0.

The snapshot addition reuses TaskStore's explicit `BEGIN` read transaction.
SQLite's [transaction contract](https://www.sqlite.org/lang_transaction.html),
Python 3.11's [transaction control](https://docs.python.org/3.11/library/sqlite3.html#transaction-control)
and the [CPython 3.11.9 connection implementation](https://github.com/python/cpython/blob/v3.11.9/Modules/_sqlite/connection.c)
were checked before promotion. A connection context manager alone does not
start a read transaction; the existing TaskStore implementation already does.
No SQLite or CPython implementation was copied, and no new database, lock or
dependency is introduced. Exact reused sources and selected fixtures remain
available in the [snapshot lineage](../provenance/control-mailbox/snapshot-lineage.json).
