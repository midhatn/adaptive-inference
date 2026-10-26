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

This is development work. CPU tests of the contract and adapter do not establish
installed IQ3_S execution, multiple tasks in one running host, or reboot recovery.
The existing installed orders qualification remains a separate, preserved result.

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
yet a command for adding a task to an already running host.

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
The current tool boundary also requires those exact relative names in tool
arguments: `answer.txt`, rather than `./answer.txt` or an absolute alias. Hermes'
general file-tool schema is broader. An alias can therefore stop this bounded
adapter even if it would name the same file. Normalizing aliases consistently
across intent, validation, receipts and recovery is a follow-up, not an implied
capability of this version. A task may declare no outputs and return a textual
answer; that answer is still not independently checked for correctness.

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

The contract reuses this repository's TaskStore, capability boundary, durable
tool receipts, pre-effect feedback and explicit continuation. It does not add a
second task database implementation or an executor. The next host-admission
step uses the same store for a durable selection record while retaining separate
task workspaces. Installed handover requires its own validation.

The admission component keeps one selected task and up to 16 explicit admission
commands. A reservation is durable before preparation or launch can happen;
repeating a command looks up that same reservation. A different payload with
the same command ID is refused. Stop may abandon a known unstaged reservation,
but unknown preparation or launch outcomes are retained for reconciliation.
The caller must supply verified process-cleanup evidence: a stored digest alone
does not prove that a worker or engine exited.

The first admission component accepts completed or explicitly cancelled original
task executions. Handover after a **Continue saved task** successor still needs
integration with the existing continuation authority's release verifier. The
component refuses that unsupported case. Host authentication, submission into
the running service, demand rebinding and fresh task-window launch are also
outstanding. Sequential SQLite tests do not establish any of those installed
behaviors.

The integration assessment checked Hermes'
[session guidance](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/sessions.md)
and [gateway session lifecycle](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/gateway-session-lifecycle.md)
on 26 October 2026. Those sources separate conversation identity from cached
agent resources and use explicit session selection. We apply that separation
to task admission. The adapter remains on the pinned Hermes source revision
`14e1e43a23761b369641208e204365cd6cb9399d`; this research does not upgrade it.
No upstream implementation was copied for TaskSpec. Existing Hermes MIT and
project Apache-2.0 notices remain in their source-preservation records.
