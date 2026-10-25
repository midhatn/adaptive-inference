# Desktop control library

`adaptive_inference.desktop` contains the reusable control components for one
prepared task: an authenticated loopback transport, a serialized listener, a
durable mailbox adapter, explicit window intent and control-progress evidence.
Importing these modules starts no listener, GUI, worker, engine or model.

These remain reusable **library components**. The subsequent
[installed Windows composition](installed-desktop.md) connects them to the
existing retained GUI, agent and backend lifecycles through explicit
configuration. Its `desktop` command has the bounded orders-report scope; it
does not introduce another task owner, scheduler or demonstration host.

## Components and trusted inputs

| Component | What it owns | What the host must supply |
| --- | --- | --- |
| `control_transport.PreparedTask` | The unchanged task and host identity used by the control protocol | Original objective, task ID and fresh host epoch |
| `control_transport.ControlTransport` | Bounded authenticated requests and retained mutations | Exact runtime, private host capability and a distinct inference credential |
| `serial_listener.SerialListener` | One serialized loopback connection lifecycle | The exact transport, on its owning event loop |
| `mailbox_runtime.MailboxRuntime` | Coherent mailbox observations and bounded database work | Actual `Mailbox`, its requester capability, intent gate and retained lifecycle callbacks |
| `ui_intent.UIIntentGate` | Explicit intent bound to one exact window/session identity | Private capability and a verifier backed by the host's retained window/process ownership |
| `ui_progress.CooperativeProgress` | Bounded host-observed control-progress receipts | The exact gate and capability; optional transport/listener wiring |

The object capabilities are an in-process cooperative boundary, not protection
against arbitrary Python code in the same process. Remote requests cannot supply
these objects or choose a task, process or window to adopt. The host creates a
fresh UI credential, binds the session and delivers its bootstrap through its
owned startup channel; it keeps that credential distinct from inference access.

Use one canonical import identity throughout the host. These components check
the actual types of `PreparedTask`, `UIBinding`, `UIIntentGate`, `Mailbox`,
`MailboxSnapshot` and `ControlTransport`. Do not load second copies under flat
module names or inject a checkout directory into `sys.path`.

## Wiring into an existing host

The following integration excerpt runs on the trusted host's event loop. Its
inputs already belong to the prepared task and retained lifecycle; it does not
discover or create a worker, GUI or backend:

```python
from adaptive_inference.desktop.control_transport import PreparedTask, ControlTransport
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.serial_listener import SerialListener
from adaptive_inference.desktop.ui_intent import UIIntentGate

prepared = PreparedTask(host_epoch, mailbox.identity.task_id, original_objective)
gate = UIIntentGate(
    host_epoch=host_epoch,
    capability=intent_capability,
    verify_current=retained_window_verifier,
)
runtime = MailboxRuntime(
    prepared, mailbox,
    requester_capability=mailbox_requester_capability,
    gate=gate,
    intent_capability=intent_capability,
    lifecycle=retained_lifecycle,
)
transport = ControlTransport(
    prepared, runtime,
    capability=transport_capability,
    runner_credential=inference_credential,
)
listener = SerialListener(transport)
await runtime.refresh()
```

The host starts the listener explicitly, binds the exact retained GUI session,
and performs the existing authenticated `window_ready` exchange. The listener
binds `127.0.0.1` on an ephemeral port. Constructing the objects is not readiness
or admission evidence.

The supplied lifecycle implements `session_is_live`, `window_ready`,
`window_closed`, `status`, `fence_admission` and `cooperative_stop`. Window
readiness returns the exact `UIBinding`; status exposes only the bounded host
phase and waiting reason. Stop must return the actual `worker_joined`,
`host_closed`, `uncertain` and `fault` result after the retained obligations are
resolved. A callback returning a fabricated success does not establish process
cleanup. The installed composition supplies the existing native host and GUI
implementations of these obligations.

## Progress and shutdown boundaries

Pause, Resume and Cancel are saved through the existing
[durable mailbox](task-controls.md). Only the actual owner acknowledges them at
a safe boundary. Status is detached observation, not a resource reservation.
The runtime refuses stale observations, changed task identity and malformed
acknowledgements; it does not take over the task owner lock.

An optional `CooperativeProgress(gate, intent_capability)` can be passed as
`cooperative_progress` to the transport. The listener publishes a successful
exchange only after the handler has joined, stream closure is confirmed and
the accepted socket is closed. Receipts are bound to the current host/session
and intent generation. Slow or stale exchanges, generation changes, retained
faults and shutdown invalidate them. Two consecutive exchanges are required;
the fixed qualification bounds are 0.5 seconds per exchange and 2.5 seconds for
the next arrival and last-completion age. These receipts are inputs for a
separate admission policy. They do not themselves authorize inference, suppress
resource pressure or claim that an arbitrary application is responsive.

Client disconnect or waiter cancellation does not cancel an accepted database
mutation or cooperative Stop. Keep the owning loop and retained objects alive
until their pending work and cleanup are resolved. Listener close alone does
not request task Stop. The host must order its worker, GUI and backend shutdown,
then close the transport/listener and inspect their final receipts. A timeout
or unresolved cleanup remains a failure, not an invented exit.

## Reproduction and source reuse

After installing this checkout, run
`python -m unittest discover -s tests -p "test_desktop_*.py" -v`.
The selected existing tests use real temporary SQLite stores and bounded
loopback sockets, plus explicit simulated lifecycle/window boundaries. They
cover durable control races, cancellation retention, session/identity changes,
closure-before-progress publication, stale data and safe-boundary handoff.

The original `tests/desktop_support/policy.py` is retained as historical source
support. The intent/progress regressions now target that same policy promoted as
`adaptive_inference.desktop.foreground_policy`. GUI-client, lifecycle and native
component tests accompany the installed composition. There are no model,
installed-agent, real window or native-resource acceptance claims from these
software fixtures.

The [retained source lineage](../provenance/desktop-control-core/README.md)
records exact inputs, qualified-import changes, test selection and licensing.
The implementation reuses the existing TaskStore, mailbox, serialized control
transport and retained asyncio lifecycle. Primary references include Python's
[stream closure](https://docs.python.org/3.11/library/asyncio-stream.html#asyncio.StreamWriter.wait_closed)
and [shielded task retention](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation).
No new upstream implementation or service dependency was added.

Package promotion follows PyPA's
[source-layout guidance](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/):
validate a regular installed wheel outside the checkout so local imports cannot
hide missing files. The installed GUI launch preserves its owned standard
pipes; a Windows `gui_scripts` wrapper is not interchangeable with that launch.
See the [entry-point specification](https://packaging.python.org/en/latest/specifications/entry-points/)
and Python's [isolated mode](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I).
