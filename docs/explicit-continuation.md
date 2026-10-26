# Continue a saved task in the same window

**Continue saved task** gives an unfinished, safely paused task another finite
execution budget after its previous budget expires. The original objective,
conversation, saved report and effect records stay with the task. The same
window remains open.

**Accepted for one installed Windows/Hermes/Strata IQ3_S task, 26 October 2026:**
one Continue in the same window resumed the original report task after genuine
safe expiry. Three cumulative model requests produced one physical report write,
and one Stop completed normal shutdown. The independent terminal audit passed
70 checks. The [source-bound acceptance record](../provenance/explicit-continuation/acceptance/README.md)
and [public result](../provenance/explicit-continuation/acceptance/result.json)
identify this bounded trial. A recorded grant or ready worker alone is not task
acceptance; the original objective still has to pass its checks.

## An example

Suppose the agent has written a report and you click **Pause**. It reaches a safe
checkpoint, acknowledges the pause and preserves the report. If the current
execution budget expires while it stays paused, the worker closes its owned
resources and seals that execution. The task is still unfinished.

When the controller has verified that the old worker exited and its native
owner is parked, **Continue saved task** becomes eligible. One click authorizes
another execution and requests its Resume. The new worker first acknowledges a
fresh Pause through the existing control path; the controller then records the
derived Resume and waits for ordinary readiness. You do not need a second
Resume click in the successful path.

The agent continues the remaining report task. Restarting a worker must not
cause it to write the report again. The saved file, effect receipt and native
conversation are checked before the task can be accepted. **Task completed.**
is a separate result from the controller selecting or starting the execution.
Use **Stop engine** to finish the session and join its owned resources.

## When Continue is available

This implementation supports the bounded Windows orders-report composition in
the **same live host and computer boot**. The predecessor must have a verified
expiry seal at the supported safe, ready checkpoint. Its worker must have exited,
and its native resource owner must be parked with confirmed release. Pending
controls and operations must be settled, and an uncertain external effect cannot
be bypassed by granting another budget.

Continue does not reopen accepted, cancelled or exhausted tasks. It does not
renew active work automatically, infer new authorization from an expired clock,
or resume an arbitrary unmodified Hermes session. Closing the host or restarting
the computer requires the separate [task-survival integration](task-survival.md)
and reboot qualification. Saved task state does not make an old same-boot
execution deadline valid after a reboot.

The reference profile keeps the existing IQ3_S model, context length **65,536**,
output allowance **10,923**, high reasoning effort and **8,192-token** reasoning
budget. Each explicit execution has a **900-second** budget. The original task's
**eight-request ceiling is cumulative**: Continue does not replenish requests,
reset attempts, erase rejection feedback, change quality or replace the user's
objective. The selected worker's readiness wait is bounded by the earlier of
**240 seconds from readiness entry** and its new execution deadline.

## One task, distinct executions

The **expired execution** keeps its immutable checkpoint, control history and
expiry seal. The existing TaskStore transaction records a separate successor
and its authorization while retaining the shared logical task identity. The
successor receives its own execution ID, increasing execution generation, demand
identity and diagnostic directory. Its work directory, native conversation and
effect and request accounting belong to the original task.

One stable command ID identifies one grant. A retry with the same ID and payload
looks up that grant; it cannot allocate a second budget, child or derived Resume.
Conflicting reuse of the ID is refused. This builds on the existing SQLite
transactions and cooperating-owner locks, without adding another database or
task supervisor.

The controller drains accepted operations before replacing the selected
execution and publishes the related runtime, mailbox and demand bindings
together. Task-changing commands carry the execution ID and generation. Old
queued commands, delayed replies and stale status observations cannot authorize
work for the new execution or restore an older selection. Adopting a grant clears
the old status and acknowledgement freshness; controls wait for an actual
snapshot of the successor. The GUI's logical task and session remain stable.

## Waiting, failure and Stop

Status distinguishes selection, preparation, readiness and running from task
acceptance. A long startup retains its operation while the control interface
can return a bounded pending response. It does not hold the command-serialization
lock through native readiness.

**Stop engine** acts on the whole retained host, including an execution that is
still being selected or started. Stop latches before cleanup waits. Subsequent
startup steps recheck Stop and the original intent; any child already being
launched remains retained and must be joined. Cleanup joins transitions,
children, controls, window and native resources.
A committed grant without a child still has a lifecycle obligation.

If authorization commits but its return is lost inside the host, exact read-only
lookup may establish that the grant exists. That recovery does not launch a
worker or clear the original error. An unresolved lookup or uncertain cleanup
remains a failure. A lost UI session does not silently create a fresh intent.
Worker exit is established through its retained process object; a reused process
number cannot borrow a different child's completed wait.

These rules preserve explicit ownership. They do not provide a general
exactly-once guarantee for arbitrary external tools or distributed services.

## Reproduction and evidence

The [public qualification workflow](../examples/validation/explicit_continuation/README.md)
includes the execution scripts, source lineage, input templates, genuine window
sequence and terminal auditor for a fresh local trial. Its public helper-path
adaptation passed 43 portable checks; it was not rerun with a model. The accepted
installed run and fixed-evidence replay retain their original source identities.

The [installed desktop guide](installed-desktop.md) describes the full host and
worker interpreters, regular wheel installation, pinned Hermes SDK, explicit
profile and native-owner prerequisites. Both interpreters must contain the same
reviewed wheel; an editable source import is not an installed qualification.
The separately acquired model remains IQ3_S with the quality settings above.

The existing software checks remain:

```text
python -m unittest discover -s tests -v
python -m unittest discover -s provenance -p "test_*.py" -v
```

The [actual Hermes dispatcher fixture](../examples/validation/hermes_pause_dispatch/README.md)
has a distinct installed-mode check. It verifies the pinned SDK's dispatch and
cleanup behavior against the installed package, without claiming a full model
conversation. The installed execution clock must also be checked in both actual
interpreters on the current boot.

The complete continuation qualification requires a fresh task and the genuine
window sequence: Resume, report saved, Pause, natural expiry of the first
900-second budget, one Continue, acceptance of the original task and normal
Stop. Its separate **2,700-second test envelope** covers setup, two sequential
budgets and cleanup. It does not extend either execution budget, and the run can
finish before the second budget expires. The existing 1,800-second expiry
qualification remains unchanged.

The [accepted trial](../provenance/explicit-continuation/acceptance/README.md)
used wheel SHA-256
`02010db139127855e4ec5a5542e1bda3c5f7dde12ea650fe9235181cef83ce66`,
with 57 runtime modules from reviewed source freeze
`73fbec145f95a7f97b60ba51dd8cbe737b3124b37c442417ac4acc69effe8906`.
The independent terminal audit passed 70 checks and bound 214 private inputs.
The original sealed checkpoint/history and correct report remained unchanged:
four rows, 17 units and 4,350 cents, with one physical write. Two IQ3_S requests
preceded Continue and one followed it. Both execution authorizations were
900 seconds; the successor completed the objective before its budget ended.

The real window recorded one Resume, one Pause, one Continue and one Stop, with
no Retry. It displayed saved progress after expiry, then **Task completed.**
Both workers were joined through retained process identities, followed by
verified native, window and control cleanup. The external status observer
recorded availability before and after Continue and exited with code 1 after
three connection errors following Stop. That observation is retained; connection
refusal is neither cleanup proof nor task acceptance. Cleanup comes from the
separate retained-process and resource evidence. UI action times are observed
brackets, not precise click timestamps or latency measurements.

The acceptance record gives the public projection and custodian replay command.
Replaying it requires the retained private terminal inputs; the public synthetic
suite does not rerun the model or GUI. Historical expiry evidence remains scoped
to its earlier trial. A later release archive may contain new documentation and
evidence files; it is not byte-identical to this tested qualification wheel.

The final reviewed host component passed 295 supplied checks plus one independent
receipt-integrity case. The qualification harness passed 37 synthetic and
source-equivalence checks. These results do not establish installed model
acceptance or demonstrate every interruption in a live run. Component tests,
installed SDK checks and complete model qualification remain distinct.

This feature advances explicit continuation after safe expiry. Broader foreground
applications, arbitrary tasks, automatic renewal, physical reboot recovery and
other native engine/agent integrations retain separate roadmap gates. Model-cache
save and restore is an optional later optimization; durable task progress does
not depend on assuming that a model cache survived.

## Research and reuse

[Temporal's Continue-As-New guidance](https://docs.temporal.io/develop/python/workflows/continue-as-new)
informed the separation between stable logical identity and a new execution, and
settling handlers before transition. This project adapts those concepts to its
existing task store; it does not import Temporal's successful workflow-closure
semantics or add a Temporal dependency. The inspected documentation revision is
`013b6f8b13f0613056250b17a5034960b3a440ae` (MIT).

[LangGraph's interrupt guidance](https://docs.langchain.com/oss/python/langgraph/interrupts)
informed explicit resumption of saved state and the need to account for effects
that may be encountered again. The inspected documentation revision is
`4506df5fb4105a39b84c2b7390d21bed89e28668` (MIT). No LangGraph dependency or
implementation is copied.

The implementation reuses [SQLite transactions](https://www.sqlite.org/lang_transaction.html),
the existing [retained asynchronous operations](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation)
and [process waits](https://docs.python.org/3.11/library/subprocess.html#subprocess.Popen.wait).
The pinned Hermes SDK remains at
`14e1e43a23761b369641208e204365cd6cb9399d`; its licensed source and native-history
interfaces are already preserved in the [source supplement](../integrations/hermes/current-source/README.md).
The [research ledger](research.md#explicit-continuation-of-a-safely-expired-execution)
and [bibliography](../REFERENCES.bib) retain the adopted references and their limits.
