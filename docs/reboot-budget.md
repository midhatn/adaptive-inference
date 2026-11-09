# Preserve a task's time allowance across a normal reboot

Status: source, package, hosted, isolated installation and scripted SDK gates
passed. The next gate is an actual clean Stop/Windows Restart/resume trial.
The accepted same-boot application restart does not establish computer-reboot
recovery; no physical reboot result is claimed here.

The first source component is the pure
[`execution_budget` helper](../src/adaptive_inference/desktop/execution_budget.py).
Its six [controlled-clock tests](../tests/test_execution_budget.py) passed on
Python 3.11.9. The working host/worker/clean-Stop integration also passed a
controlled changed-boot case through the real TaskStore, native-history recovery
and paused composition: a saved read reached the first resumed request, three
requests total completed the task and one output write occurred. Desktop edges
and provider transport were inert. All 123 combined behavior checks and 104
source-preservation checks passed, including actual worker startup through inert
SDK edges. The complete suite also passed **1,394 tests in 517.802 seconds**
with unchanged inputs. The [source-bound record](../provenance/installed-reopen/reboot-budget/validation-2026-11-01.json)
retains these results and the earlier fixture failures. Corrected source
`260187a` passed package verification of 1,280 source files/63 runtime modules,
all 14 original hosted jobs and 12 distribution checks. Fresh isolated
installation and the [actual pinned SDK fixture](../provenance/installed-reopen/reboot-budget/installed-sdk-validation-2026-11-01.json)
passed independent review. Scripted responses exercised rejection feedback and
one correct write; the initial budget included startup time and remained
unchanged across 33 history rows. Physical IQ3_S reboot qualification remains
pending. The actual installed wheel has the same 74 member contents as the
corrected package; their source archives and container hashes differ.

The user should be able to stop a task safely, restart Windows, open that same
task and continue its unfinished work. Completed reads and writes, the original
objective, native conversation and consumed attempts must survive. Restarting
the computer must not award another full execution allowance.

## Reuse the existing durable state

Temporal persists timers across worker/service downtime and retains an absolute
execution expiration across retry. We reuse that policy with the existing
TaskStore, rather than adding Temporal as a dependency. The repository already
commits checkpoint state and its history in an owned SQLite transaction.

Eligible new tasks will receive a versioned budget record when their first
deadline is granted. It binds a fixed UTC expiry to the allowance already
granted, the original boot observation and the current boot's QPC deadline.
Clock observations are bracketed conservatively so preparation or observation
delay cannot create extra time. At a clean Stop, save a remaining-time cap with
the same checkpoint before constructing the existing Stop receipt.

Opening the task during the same current boot keeps its exact QPC deadline.
After a changed boot, the available time is the smaller of the saved cap and
the time until the fixed expiry. Under the existing host lock and TaskStore
claim, commit an explicit budget/boot transition before taking the reopened
paused snapshot. The worker still requires its supplied deadline to match the
committed deadline; the existing anti-reset check is not removed.

The reopened task starts paused and needs a fresh Resume. Selection and startup
delay continue to consume its allowance. Its original creation context, task
identity, counters, saved requests, conversation and effects remain intact.
Completed-result viewing remains read-only and requires no new budget.

## Boundaries for the first implementation

- Existing tasks without this budget record retain their current same-boot
  behavior. Do not invent missing expiry metadata for them.
- Explicit Continue authorizes a separate execution. Preserve the old allowance
  in its sealed predecessor and clear that execution-specific record from the
  successor. These successors retain their existing behavior and are not part
  of the first reboot qualification.
- Start with the already supported clean Stop checkpoint. Crash, power loss,
  uncertain effects, sleep and hibernation remain separate qualification cases.
- An expired allowance refuses execution. An inconsistent boot/budget record or
  detectable clock rollback also refuses automatic continuation.
- UTC is adjustable. This first path assumes a valid system clock; a saved cap
  prevents refunding recorded consumption but cannot prove powered-off duration
  under arbitrary offline clock changes. No external time service is introduced.

## Validation sequence

First exercise controlled boot and clock observations with the existing task
store: downtime consumes allowance; reopening on the same boot retains the
exact deadline; another reboot cannot renew it; expiry refuses dispatch; and
the owned transition preserves task history, counters and effects. Check the
ordinary initial-task and later-task composition, not only arithmetic helpers.
Preserve the existing acceptance fences and use the current transaction rollback
behavior if a budget transition cannot commit.

Then qualify a fresh installed IQ3_S task with the unchanged model and quality.
Stop after a confirmed read and before the output write, retain actual cleanup,
perform a separately scheduled normal reboot, and reopen the same task paused.
Require the saved read in the first resumed request, remaining original
allowance, correct output, one physical write and normal cleanup. A reboot that
consumes the allowance is an expiration, not permission to restart the timer.

## Sources and applicability

- [Temporal persisted timers](https://docs.temporal.io/workflow-execution/timers-delays)
  provide the durable waiting pattern. Temporal's
  [expiration creation](https://github.com/temporalio/temporal/blob/e0233ff6658fcab7b4e7ecc1c16af40baf629b78/common/util.go#L588)
  and [retry inheritance](https://github.com/temporalio/temporal/blob/e0233ff6658fcab7b4e7ecc1c16af40baf629b78/service/history/workflow/retry.go#L306)
  preserve an absolute execution expiry. Temporal is MIT licensed; this project
  reuses the policy, copies no server implementation and adds no service.
- [Microsoft QPC guidance](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
  distinguishes interval measurements from UTC. Its
  [system-time documentation](https://learn.microsoft.com/en-us/windows/win32/sysinfo/system-time)
  explains that UTC can move forward or backward. These are documentation
  references, not copied Windows code.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html) supports
  committing budget and checkpoint state together through the existing
  TaskStore. It does not make external tool effects exactly once or establish
  clock accuracy. SQLite is public domain; its existing project attribution
  remains in place.

Primary sources were refreshed on 1 November 2026. The inference from these
sources is the proposed local budget policy above, not a claim that an upstream
framework already implements this exact Windows/Hermes adapter.
