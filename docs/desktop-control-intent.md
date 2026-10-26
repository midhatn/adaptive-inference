# Reliable input during a desktop status check

The desktop client retains one user command when its background status check
is already running. A click on Pause, Resume, Cancel task, Stop engine, or
explicit Retry receives immediate local feedback. The client finishes the
status exchange, checks whether the command is still allowed, and sends it
before starting another background poll.

This is a client behavior change. It does not change engine commands, task
quality, the request protocol, resource policy, or the durable task checkpoint.

## What the user sees

For example, clicking Pause during a status check first shows that the request
is waiting locally and has not been sent. After dispatch, the existing message
says recording is not yet confirmed. The engine's recorded receipt and the
agent's acknowledgement remain separate later outcomes. A local click does not
prove the agent has paused or that the engine has stopped.

Only one local intent can wait. Further clicks cannot silently replace it or
create a backlog. A background status check alone leaves eligible controls
enabled, so an ordinary poll does not disable a button between mouse press and
release. A genuine state change can still make an action unavailable.

The client checks again before dispatch. If the task completed while Cancel
was waiting, for example, it displays that the request was not sent. A new
Resume still requires valid status. An explicit Retry of an earlier uncertain
request retains the same identity and the existing reconciliation rules; it is
not a newly admitted Resume. If status already confirms that earlier request,
the client does not send a redundant Retry.

Transport cleanup must be known before another request starts. A failed socket
close blocks dispatch and is shown as uncertain cleanup. A worker refusal is
shown as not sent; an exception that may have partially submitted a request is
shown as uncertain and fences further dispatch. Neither path silently retries.

Actual session teardown settles only the local unsent attempt and never
replays it into another window. Discarding an unsent Retry does not erase the
uncertain outcome of the earlier request. The installed window's **X still
minimizes to the taskbar**; minimizing does not tear down the session or discard
the local intent. **Stop engine** retains its existing recorded-Stop and owned
cleanup sequence.

## Continuing a safely expired execution

[Continue saved task](explicit-continuation.md) uses the same retained intent and
bounded pending-response mechanisms. One eligible click grants a finite successor
execution and requests its Resume through fresh owner acknowledgements. The
window and logical task remain stable; an execution ID and generation distinguish
the selected work. Adopting the grant invalidates old status/acknowledgement
freshness, and the client waits for a real successor snapshot before enabling
ordinary task controls. Delayed old replies cannot restore the previous selection.

Retry keeps the exact command identity and cannot create another grant or child.
Selection/startup status is distinct from task acceptance. Stop remains available
for the whole retained host during the transition, and lost-session or uncertain
outcomes do not create automatic new intent. These are successor semantics; the
historical retained-command acceptance below continues to describe its own build.

## Why this change exists

The first installed full-task trial completed its task and cleanup, but its
first Stop click was missed; a second click succeeded. Deterministic fixtures
then reproduced an ordering in which a poll made the controller busy while
the button remained rendered enabled. The callback returned without retaining
or sending the user's command. The same gap affected the other controls.

Tk also checks enabled state at mouse release. A poll that disables the widget
between press and release can prevent the callback entirely. This second path
is supported by the installed Tk source; the original live trial did not retain
the event trace needed to identify its exact first-click timing.

The fix reuses the existing controller and single-request worker. It does not
add a parallel transport, an unbounded queue, a retry service, or a blocking UI
callback. This follows Tk's [cooperative event model](https://docs.python.org/3.11/library/tkinter.html#threading-model)
and [scheduled callback semantics](https://www.tcl-lang.org/man/tcl8.6.14/TclCmd/after.htm).
The [Tk 8.6.14 button bindings](https://github.com/tcltk/tk/blob/core-8-6-14/library/ttk/button.tcl)
explain the press/release constraint. These references informed the adaptation;
no Tk implementation source is incorporated into the runtime change.

## Validation and limits

The focused fixtures exercise commands before, during, and after status;
duplicate and conflicting clicks; the last available command ID; changed task
state; invalid status; cleanup failures; worker refusal and ambiguous submission;
explicit Retry; older acknowledgements; and session teardown. A bounded real
NetworkWorker thread fixture proves that the status result must be consumed
before exactly one retained command is dispatched. Fake exchanges create no
socket, visible GUI, or model workload.

The existing GUI/client subset passes 165 tests on Python 3.11.9. The same
suite on Python 3.12.9 passes with one pre-existing ABI test skipped because
the installed Windows GUI profile requires the exact supported 3.11 runtime.
The [source-successor record](../provenance/desktop-control-intent/README.md)
retains the complete pre-change client and checks every definition outside the
declared intent methods, including the transport, Tk timers and owned shutdown
statements. Historical source fingerprints remain unchanged.

The subsequent [installed successor acceptance](../provenance/desktop-control-intent/acceptance/README.md)
adds a model-free cold trial with one Pause and one Stop click, and a full IQ3_S
report/restart trial with one click for each Resume and one Stop. Independent
terminal audits passed 38 and 50 checks respectively. Those real trials did not
observe the local waiting message or establish physical click/status overlap;
the deterministic fixtures supply that ordering evidence. No performance
improvement is claimed.

The prior [installed acceptance](../provenance/installed-desktop/acceptance/README.md)
still applies only to its original wheel and retains its missed-click limitation.
The local intent is deliberately not durable across a new session or a computer
restart; task survival remains the separate durable checkpoint contract.
