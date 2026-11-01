# User tasks and their saved contracts

The controller should keep running as a person changes from one useful task to
another. A task therefore carries its own original prompt, input files, allowed
outputs, validation requirements and budget. These are data supplied for that
task; there is no product menu of hardcoded report types.

`adaptive_inference.task_spec.TaskSpec` is the first bounded implementation of
this contract. It is independent of the inference engine and agent SDK. The
Windows reference adapter continues to select the existing IQ3_S model and
quality settings through its deployment profile. A task cannot replace those
settings, choose a new Python module, or install a validator.

This is development work with one bounded installed result:
[case17](evidence.md#case17-complete-foreground-continuation-and-two-task-handover)
passed foreground/resource-wait continuation and inventory-to-welcome handover
in the same controller using IQ3_S. CPU tests remain separate evidence. A usable
reference alpha and standalone reproduction are the next delivery; computer
restart recovery remains a later milestone.

## Try a different file task

The [welcome example](../examples/tasks/welcome/task.json) asks for a short text
artifact from a supplied brief. The [inventory example](../examples/tasks/inventory/task.json)
asks for pack-rounded replenishment quantities from different input data. Both
use the same contract and adapter. The examples are starting points for forks,
not the set of supported task names.

With the reference Windows deployment already installed, a build containing
this change accepts:

```powershell
adaptive-inference desktop --profile .\deployment.json --run .\runs\welcome-01 `
  --task-spec .\examples\tasks\welcome\task.json `
  --task-inputs .\examples\tasks\welcome\inputs
```

Use a fresh run directory under an existing parent. The host starts paused;
Resume supplies explicit user intent. The original prompt appears in the
control window. Omitting both task arguments keeps the retained orders example.
Supplying only one argument is an error. This command starts a host; it is not
an API command for adding a task to an already running host; use the existing
window's **New task** control for that.

The ordinary interaction uses these existing controls:

1. Start the installed desktop host with the task specification and input folder.
2. Read the objective in the window, then select **Resume**.
3. Use the computer while the controller observes foreground demand. It waits
   and restores its owned model as capacity permits. A request already running
   drains to a safe boundary; instantaneous preemption is not claimed.
4. If the finite execution budget ends with safely saved work, select
   **Continue saved task** to authorize another bounded execution.
5. After completion, select **New task**, choose the next specification and
   its input folder, then **Resume** in the new task window. The controller
   stays running and each task keeps separate records and outputs.
6. Select **Stop engine** when finished. Closing the window with X minimizes it;
   it does not stop the service or establish restart recovery.

These product controls do not require qualification receipts or audit-file
editing. The explicit local installation/profile remains a prerequisite; an
automatic setup experience is not yet delivered. Case17 exercised these
controls with the inventory and welcome examples. New tasks still need their
own appropriate result checks.

Each task receives its own work directory, Hermes session, native conversation,
task history and effect receipts. The specification and input bytes are checked
before work. Resume and explicit continuation must preserve the same prompt,
specification and completed effects. A new objective needs a new task identity.

## What the contract means

| Field | Meaning |
| --- | --- |
| `schema` | `adaptive.task-spec.v1` |
| `prompt` | The original user objective, stored unchanged; at most 16 KiB of UTF-8. |
| `inputs` | File names, byte counts and SHA-256 hashes. Only declared files are copied into the task workspace. |
| `outputs` | Create-only file names, whether each is required, `text` or `json`, and a text-length limit. |
| `budget` | The current reference adapter supports eight provider requests, eight attempts, 32 admission attempts and a 900-second execution allowance. |
| `validation` | Explicitly declares either no semantic oracle or the built-in `json-equals.v1` expected-value check. |

The first file capability accepts at most 16 input/output declarations combined,
256 KiB of input bytes combined, and 4,096 characters per output. Names are flat,
portable basenames; inputs and outputs cannot overlap. Existing outputs cannot
be overwritten without a matching durable receipt. These bounds describe this
adapter's current capability, not a limit on the project's long-term goal.
Tool arguments may name a declared file by its basename, a relative alias such
as `./answer.txt`, or an absolute path to that same task workspace file. The
adapter checks the workspace and filesystem identity before treating those
spellings as the same capability. Absolute paths must use the worker's resolved
workspace path; alternate directory aliases, including a Windows short-name
parent, are outside this bounded capability. It refuses parent traversal, paths outside
the workspace, links, and undeclared names. On Windows it also refuses ambiguous
drive-relative paths, network/device paths and alternate data streams.

The original tool arguments remain unchanged in native history and intent
verification. Each retry keeps its own call identity and raw arguments, while a
verified repeated write can reuse the original durable effect receipt. Completion
checks group accepted writes by the declared output and verify the artifact.
The changed validator identity requires a newly prepared task; it does not
silently migrate older task records. Source/component checks cover these rules;
case17 adds the bounded installed two-task IQ3_S result described above. A task may
declare no outputs and return a textual answer; that answer is still not
independently checked for correctness.

JSON outputs reject duplicate keys and nonfinite values. A format check can
establish that an output is readable JSON; it cannot establish that its content
answers the user correctly. Accordingly, an unvalidated text or JSON task
reports semantic validation as `not_checked`. The agent's completion report and
the artifact checks remain distinguishable.

`json-equals.v1` compares a declared output with the SHA-256 of its expected
canonical JSON value. Canonical bytes are produced by Python's
`json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')`.
This deliberately distinguishes integers from floating-point spellings. The
reference example computes its expected result independently; the prompt and
correction feedback do not include that answer. Matching an oracle establishes
only that declared check. It is not general semantic correctness.

When a proposed write fails its check, the existing feedback path returns a
correction message before performing the write. The same finite request budget
still applies. Accepted writes keep their receipts, and recovery verifies the
actual files against those receipts before deciding whether more work is safe.

## Existing mechanisms reused

File alias handling follows the pinned Hermes
[file tools](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/file_tools.py)
and [path anchoring](https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/tools/file_tools_paths.py),
with Python's existing [path and filesystem identity operations](https://docs.python.org/3.11/library/pathlib.html).
The adapter applies its narrower declared-file capability before dispatch. It
reuses the existing receipt and recovery implementation; no upstream tool
implementation was copied. The exact predecessor source and preservation checks
are retained in the [alias repair record](../provenance/task-handover/task-file-aliases/README.md).

The contract reuses this repository's TaskStore, capability boundary, durable
tool receipts, pre-effect feedback and explicit continuation. It does not add a
second task database implementation or an executor. Host admission uses the
same store for a durable selection record while retaining separate task
workspaces. Installed handover has its own bounded case17 validation.

The admission component keeps one selected task and up to 16 explicit admission
commands. A reservation is durable before preparation or launch can happen;
repeating a command looks up that same reservation. A different payload with
the same command ID is refused. Stop may abandon a known unstaged reservation,
but unknown preparation or launch outcomes are retained for reconciliation.
The caller must supply verified process-cleanup evidence: a stored digest alone
does not prove that a worker or engine exited.

The admission component accepts completed or explicitly cancelled executions,
including a **Continue saved task** successor when the host retains its exact
worker binding. It reuses the continuation authority's existing result and
lifetime verifier. The authority lock is taken before the execution lock, even
when a continuation authority has not yet been created. This prevents a first
Continue authorization from racing the handover. The host must separately join
the actual child and prove native resources have been released.

The command also binds the original specification path, its raw-byte digest and
the input directory. A retry cannot silently change any of those fields while
keeping the same prompt or command ID. Historical lookup does not require the
source files still to exist; new preparation checks their actual bytes.

Service **Stop** closes the host's admission lifetime without changing a pending
task into a cancelled task. The existing safe worker-exit verifier must confirm
a running task's saved state. A prepared task that was never launched keeps its
original pending state. A committed but unlaunched continuation uses its existing
no-launch verifier. An unknown launch or cleanup outcome remains unresolved.
No further task can be admitted through a stopped host authority; reopening work
after a process or computer restart still needs the separate recovery milestone.

## Retained-host handover

The source implementation connects the new-task UI and host composition around
these contracts. The interaction is **New task**, choose a specification and its input
directory, then Resume in the new task window. The new window starts paused and
has its own credentials. The controller, inference gateway and native resource
owner stay in the same host. The previous task's records remain separate and its
window retains Status and service Stop until the new window is ready.

Each task keeps an immutable control endpoint. A late close or failed status
request from an old window must not revoke the new task's permission to work.
The shared Stop path retains every task worker, window, preparation operation
and connection until cleanup is known. This uses the existing private GUI
bootstrap and retained process lifecycles rather than an additional executor.
The installed launch also pins the task chooser's TaskSpec and feedback modules.
The chooser checks their installed origins before opening a dialog or reading
task data; the existing startup checks still run before GUI resources are acquired.
This extends the existing check of Python's
[loaded-module registry](https://docs.python.org/3.11/library/sys.html#sys.modules),
and uses its standard [file and directory dialogs](https://docs.python.org/3.11/library/dialog.html#module-tkinter.filedialog).

Component tests, including actual SQLite stores and bounded CPU child processes,
exercise admission and continuation release. The assembled A-to-B-to-C handover
test exercises the real preparation, mailbox, runtime selection and cleanup
orchestration with explicit substitutes for windows, children and native
resources. Those component tests do not establish installed GUI/model behavior.
Case17 separately passed both real installed two-task and foreground audits;
its exact source, quality and limits are in the linked evidence. Complete M2
and a generally reproducible installed alpha remain work in progress.

The integration assessment checked Hermes'
[session guidance](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/sessions.md)
and [gateway session lifecycle](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/gateway-session-lifecycle.md)
on 26 October 2026. Those sources separate conversation identity from cached
agent resources and use explicit session selection. We apply that separation
to task admission. The adapter remains on the pinned Hermes source revision
`14e1e43a23761b369641208e204365cd6cb9399d`; this research does not upgrade it.
No upstream implementation was copied for TaskSpec. Existing Hermes MIT and
project Apache-2.0 notices remain in their source-preservation records.

The handover assessment also checked Python's
[retained-task and shielding guidance](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation)
and [stream shutdown contract](https://docs.python.org/3.11/library/asyncio-stream.html#asyncio.StreamWriter.wait_closed),
plus Microsoft's [process handle lifetime](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)
and [redirected child I/O](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output)
documentation. Those contracts support retaining each transition, child and pipe
until it is joined; a timeout or a process number alone is not a cleanup receipt.
The implementation reuses the project's existing lifecycle helpers. No additional
upstream code was copied from these documentation sources.

The response-timeout repair was checked against the exact CPython
[3.11.9](https://github.com/python/cpython/blob/v3.11.9/Lib/asyncio/tasks.py)
and [3.12.9](https://github.com/python/cpython/blob/v3.12.9/Lib/asyncio/tasks.py)
implementations. If a shielded operation has already failed when its caller's
timeout fires, its completed result must be inspected before returning a stored
grant. This reuses `Task.result()` and preserves the original bounded wait and
historical lookup behavior; it introduces no replacement timeout scheduler.
