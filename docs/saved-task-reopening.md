# Open saved work after closing the desktop app

The development launcher offers **New task** and **Open saved task**. This is the
first application-restart path toward an always-on agent: unfinished work keeps
its original objective, conversation, confirmed file operations and remaining
execution allowance. The released `0.4.0a1` package and earlier physical
installation do not acquire this feature merely because this document exists.
Use a matching source checkout and runtime package when qualifying it.

## Ordinary use

1. Start a new task with the supported desktop launcher. It records the original
   task and the current Windows boot, deployment profile and package identity.
2. Use **Stop** to close the app at a safe checkpoint. Stop pauses the task and
   joins its owned work; cancelling the task has different, terminal semantics.
3. Start the launcher again and choose **Open saved task**. Select the original
   task from the configured runs folder. The application creates a fresh host
   session around the same task database and Hermes conversation.
4. The reopened task starts paused. Choose **Resume** to permit further work.
   The saved deadline and request/attempt counters remain unchanged. Time spent
   with the app closed still consumes this first version's execution allowance.
5. Opening an accepted task displays its saved answer and file references. It
   does not start a worker or model, repeat validation, or write the output again.

The selector reads existing plans. It does not scan other folders, repair a
database, or attach new recovery metadata to historical validation archives.
The selected checkpoint and artifacts are verified before use. The existing
task store and worker claim remain authoritative; no second recovery database
or agent framework is introduced.

This first selector lists initial tasks created from the startup window with
saved-task support. Tasks subsequently created through the running controller's
handover flow are not yet included. Their discovery remains follow-up work;
this increment is not a complete task browser.

## Current scope

Execution reopening requires the original supported Windows boot, profile,
package, model configuration and safe checkpoint. A changed or unavailable boot
observation, exhausted deadline, live owner, changed input or unresolved effect
refuses continuation. An old Resume receipt does not start a new host. New GUI,
process and resource bindings are established before a fresh Resume.

A safely stopped task may still have a request waiting for resources. The
reader accepts that request only when the existing admission-state validator
confirms its bounded accounting, the task is paused, its model matches, there
is no owner or unresolved operation, and native tool calls are fully flushed.
Selection keeps the saved request, history and deadline unchanged. After a new
Resume, the ordinary worker rebuilds its conversation from the saved native
history. An uncertain dispatched request remains refused.

The initial reader rejected this ordinary wait state even after a clean Stop.
The [correction evidence](../provenance/installed-reopen/admission-wait-validation-2026-11-01.json)
preserves the failing regression and subsequent component checks. Those checks
use real task storage, admission and Stop callbacks with inert transport and
desktop edges; they do not qualify installed IQ3_S restart.

Read-only accepted results are independent of execution authorization. Their
original stored identity, checkpoint and artifacts must remain valid, but viewing
them does not renew a deadline or require the old boot to remain current.

The [installed IQ3_S application-restart trial](../provenance/installed-reopen/application-restart-2026-11-01.json)
passed at source `6ac601546daf32d96e38b6689a5818e4cc8dafa8`: one saved read
survived ordinary Stop and reopening, the original task completed with one
physical output write, and the completed-result view made no additional model
call or canonical file change. This qualifies that installed same-boot path.
OS reboot needs a durable budget policy that does not reuse a prior boot's
monotonic timestamp. Crash recovery, sleep/wake, hibernation and Fast Startup
remain separately qualified cases.
See [M5 in the roadmap](../PLAN.md#m5--survive-application-and-computer-lifecycle-changes)
and the [evidence ledger](evidence.md) for the current validation boundary.

## Reproduce the bounded application-restart check

Use the [documented installation/setup](installed-desktop.md), a matching
candidate package and full host/worker interpreters, and the unchanged IQ3_S
model and quality recorded in the evidence. Keep existing validation folders
intact; create a separate setup with an empty runs folder. This sequence uses
the ordinary application, with no injected picker, control request or deadline.

1. Start the generated launcher. Choose **New task**, the repository's
   [inventory task](../examples/tasks/inventory/task.json), and its `inputs`
   folder. Confirm the task starts paused, then select **Resume** once.
2. Allow the first model step to read the input. Ordinary foreground activity
   can hold the next step at resource admission. Select **Stop engine** only at
   the safe waiting boundary, and wait for normal application/owned cleanup.
3. Inspect the closed evidence: require a confirmed read, no physical write,
   no unresolved owner/operation/effect and time left on the original deadline.
   A task already completed before Stop does not test unfinished-task recovery.
4. Start the launcher again, choose **Open saved task**, and select the original
   task. Confirm paused startup, then select **Resume** once. Require the same
   saved read in the first resumed provider request, the original deadline and
   counters, the correct 23-unit artifact and one physical write overall.
5. Stop normally and retain the application/worker/native cleanup records.
   Hash the closed canonical task/native databases, plan/configuration,
   request/effect records and input/output files. Open the completed task again,
   inspect the saved answer, and close it. Verify those hashes remain unchanged
   and no additional provider call or worker was created.

Use the existing task, native-history, request-hash and effect/oracle checks;
file appearance alone is not task acceptance. Keep actual process joins and
source/package identity with the result. This repository retains the code and
sanitized findings; private machine records/model assets are not a public
replay bundle. A different installation earns its own result. Preserve a failed
or expired attempt rather than using Continue to renew its budget for this test.

## Mechanisms and sources

This path reuses this repository's [task store and attribution](task-survival.md),
durable Pause/Resume mailbox, Hermes native-history verification, safe Stop and
owned-process cleanup. It adapts their composition, rather than adding another
scheduler or copying a separate gateway into the application.

The one-shot local boot observation uses Microsoft's documented
[Win32_OperatingSystem.LastBootUpTime](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem)
through [local Get-CimInstance](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-5.1).
Its bounded hidden child uses Python's documented
[subprocess.run timeout cleanup](https://docs.python.org/3.11/library/subprocess.html#subprocess.run).
The boot time is an observation, not a unique boot GUID. Microsoft's
[QPC documentation](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
and [power-state documentation](https://learn.microsoft.com/en-us/windows/win32/power/system-power-states)
explain why matching it does not independently qualify suspend or Fast Startup.

Research also checked Hermes' pinned
[local recovery contract](https://github.com/NousResearch/hermes-agent/blob/a4994d4ead8f9c915b485cec5689909b349a49df/gateway/session_local_recovery.py)
and [unknown-operation handling](https://github.com/NousResearch/hermes-agent/blob/a4994d4ead8f9c915b485cec5689909b349a49df/gateway/session_unattended_unknown.py).
Those gateway mechanisms already exist at the installed SDK revision; this
adapter uses direct AIAgent/SessionDB ownership, so gateway recovery is not a
drop-in replacement. No additional upstream code is copied by this feature.
