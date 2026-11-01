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

Read-only accepted results are independent of execution authorization. Their
original stored identity, checkpoint and artifacts must remain valid, but viewing
them does not renew a deadline or require the old boot to remain current.

Actual application restart with the installed IQ3_S model is a separate
acceptance step after source/component checks. OS reboot needs a durable budget
policy that does not reuse a prior boot's monotonic timestamp. Crash recovery,
sleep/wake, hibernation and Fast Startup remain separately qualified cases.
See [M5 in the roadmap](../PLAN.md#m5--survive-application-and-computer-lifecycle-changes)
and the [evidence ledger](evidence.md) for the current validation boundary.

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
