# Use the Windows reference workflow

The current reference lets one controller stay open while you complete a file
task, continue saved work after a resource wait, and choose another task. It
uses the existing IQ3_S model, an explicitly owned Strata backend and the pinned
Hermes adapter. The [case17 result](evidence.md#case17-complete-foreground-continuation-and-two-task-handover)
checks this bounded workflow with real foreground document work.

This page describes ordinary use. The separate qualification workflow records
measurements and audits a test; you do not edit its evidence files to use the
product.

## Set up once

Follow the [installed desktop guide](installed-desktop.md) to prepare the host
and worker interpreters, install the same regular Adaptive Inference package in
both, and configure the pinned Hermes source/dependencies and owned native
backend. Keep the existing IQ3_S model and quality settings. The explicit local
deployment profile selects these components. The
[desktop setup helper](../examples/desktop/README.md) creates that profile from
the selected installed components and writes a **Start Adaptive Inference**
launcher. It calculates the required hashes; no manual JSON editing is needed.
It does not install Python, Hermes, models or the native backend for you.

Use the current development source containing the file-task and handover
features. The version number alone does not identify those changes: the tested
runtime and the newer publication source are identified separately in the
evidence. An older 0.3.0 wheel does not acquire new behavior by sharing its name.

For a first task, use the supplied [inventory specification](../examples/tasks/inventory/task.json)
and [input folder](../examples/tasks/inventory/inputs). The specification describes
the objective, permitted files, execution allowance and independent output
check. The [welcome example](../examples/tasks/welcome/task.json) is a different
task for the next selection; its output receives format-only checking.

## Start and work

After setup, open **Start Adaptive Inference.cmd** and choose your task
specification and input folder. Cancelling the picker starts no task. Each
launch selects a fresh state directory and calls the existing desktop host.
The window still starts paused and requires **Resume**.

For a direct command, use your actual full host interpreter, deployment
profile, a new state directory and the chosen task files:

```powershell
& $HostPython -I -B -m adaptive_inference desktop `
  --profile $Profile --run $NewRunDirectory `
  --task-spec $TaskSpecification --task-inputs $InputDirectory
```

These variables stand for the explicit local paths from your installation.
The state directory must be new, with an existing parent. Do not start a second
controller against the same owned backend while the first is running.

1. **Read the objective, then select Resume.** The window starts paused. The
   controller loads its model only when its foreground and capacity checks
   permit work.
2. **Watch the current state.** When foreground activity needs priority, the
   controller stops admitting more model work and drains the current operation
   to a safe boundary before releasing its backend. When the activity clears
   and capacity returns, work can continue. This does not promise instantaneous
   preemption or unlimited simultaneous workloads.
3. **Continue saved work if its budget ends.** A safely expired execution leaves
   its objective and completed work saved. Select **Continue saved task** to
   authorize the next bounded execution. This preserves the task's cumulative
   request allowance; it does not silently grant unlimited work.
4. **Choose another task after completion.** Select **New task**, choose its
   specification and input folder, and select **Resume** in the new window.
   The controller stays running. Each task keeps a separate workspace, session,
   output record and result check.
5. **Stop through the window when finished.** **Stop engine** closes the service
   and releases its owned resources. X minimizes the controls to the taskbar;
   it does not stop the service.

Pause waits for a safe boundary. Cancel applies to the selected task. If status
is unavailable or an outcome needs verification, inspect that state before
assuming the task completed or starting another controller.

## Use your own task

With a build containing `prepare-task`, give the objective and selected files:

```powershell
adaptive-inference prepare-task --destination .\summary-task `
  --prompt "Summarize notes.txt into answer.txt." --input .\notes.txt
```

The command copies the selected inputs and calculates their hashes for you.
Select `summary-task\task.json` and `summary-task\inputs` in **New task**, or
pass those paths to the desktop launch command for the first task. Preparing a
task does not submit it or start the model. For a longer objective, use
`--prompt-file .\objective.txt` instead of `--prompt`.

The [task contract guide](task-spec.md#prepare-your-own-task) describes optional
output names and formats. The current adapter supports bounded reads and
create-only writes of declared files. General compiler/media tools remain a
later step.

A task reporting completion and an answer being correct are different facts.
The inventory example has an exact independent oracle. Free-form text tasks
report `not_checked` for semantic correctness, so review their output.

Closing the controller or rebooting the computer is outside this workflow's
accepted recovery scope. The [roadmap](../PLAN.md) retains application/reboot
survival, measured gaming/video coexistence and autonomous media handoff as
later work. The supported path above is the current reference toward that goal.
