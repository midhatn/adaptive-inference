# Evidence and limits

This ledger separates portable software tests, source reconstruction, actual SDK/host fixtures, real model tasks and historical predecessor results. A pass in one does not establish a pass in another. The older prototype checks below did not execute the new gateway; the new gateway has its own evidence here.

## Reference delivery checks

**1 November 2026:** setup predecessor `a9eff31bf4e2257723e34d8b30188dbf8b8efb81`
passed all 14 original jobs across its push and PR workflows. The next launcher
head `5ccf7391dd07723ab8c3ce5d6553ab9cd624dec4` encountered a separate ordinary
Windows 3.12 continuation-fixture timeout before any successor worker launched.
Its [original job and diagnostic interpretation](../provenance/task-handover/continuation-timeout-diagnostics/README.md#whole-fixture-orchestration-guard-1-november-2026)
remain recorded. The precise delay cause is unknown. A prospective 30-second
test orchestration guard does not qualify the original five-second attempt or
change any product task budget. The deliberately injected timeout keeps its
five-second guard. Corrected-source checks and release packaging must be assessed
at their own revision; the installed results below remain separately scoped.

The correction passed 50 affected source/readiness checks on Python 3.11.9 and
34 continuation-host/diagnostic checks on Python 3.12.9. The latter used local
`aiohttp` 3.11.13 and `psutil` 7.0.0; it is not the hosted locked-dependency
environment. Both runs explicitly loaded this checkout and recorded actual
module origins. They are local CPU-fixture/source validation, separate from the
corrected head's hosted checks and all installed IQ3_S evidence.

A later original [Windows 3.11 job at `fbc78b9`](https://github.com/midhatn/adaptive-inference/actions/runs/41267272612/job/124732589702)
passed the continuation and injected-timeout checks, then failed a snapshot
test's final thread-liveness assertion after four-second joins. The log does
not identify which thread or operation was slow. The [prospective completion-guard change](../provenance/control-mailbox/README.md#snapshot-fixture-completion-guard-1-november-2026)
retains the original read barrier, 50-millisecond non-commit check, snapshot
content assertions and product SQLite settings. Its five existing tests passed
once in 0.554 seconds on Python 3.11.9, with explicit current-source imports,
both retained threads joined and parent exit 0. Independent source/evidence
review accepted this narrow correction; the original hosted attempt stays failed.

The `fbc78b9` workflows finished with 13 passes and the one snapshot failure.
The separate alpha head `1efe6cd4e9957fbb9627a43e5614a18062b7acb0` finished
with six successful jobs and one [Windows 3.11 cancellation](https://github.com/midhatn/adaptive-inference/actions/runs/41267498706/job/124733245107).
GitHub's check annotation confirms the cumulative 15-minute job limit. All
1,306 core tests passed in 813.388 seconds, and subsequent provenance/validation
steps passed through the demo. Cancellation interrupted the profiles command;
build and distribution checking never ran in that job. It remains canceled,
not a complete pass. No workflow was canceled or rerun by the coordinator.

Following the documented [GitHub job timeout control](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes),
the prospective Windows portable-job allowance becomes 30 minutes. The other
platforms and offline-source job retain 15 minutes. The same locked dependencies,
test commands, assertions, individual fixture guards and artifact checks remain
required. This is an outer CI scheduling allowance, not a product deadline or
proof of the slowdown's cause. The new head still needs its own complete hosted
result before merge or release.

## Supported desktop setup helper

**1 November 2026:** the [setup and launch helpers](../examples/desktop/README.md)
generate the existing deployment profile and a reusable Windows command from
already installed components. They reuse the task picker and controller without
changing the runtime wheel, task budgets, model assets or quality settings.

Five focused checks passed on Windows/Python 3.11.9. They cover generated profile
contents, existing-contract rejection before output, cancellation and forwarding,
picker cleanup, and the actual generated command executing an inert Python
stub. The first attempt's older global import and incorrectly quoted outer test
command remain recorded; the successful attempt explicitly imported the current
checkout and corrected that test invocation.

The setup command also ran successfully with the retained case17 installation.
It verified the existing host wheel, pinned Hermes interfaces and native owner's
files/dependencies/model metadata. Readback confirmed the selected components,
hashes, gateway settings and foreground policy matched that installation; only
the operator's backend revision label changed to the helper's generic label.
The copied launch script matched exactly and its run folder was empty. That
setup-only check launched no worker, model or GUI.

The first actual launcher attempt then stalled inside `tk_getOpenFile`, with
no targetable window and no run/task created. A read-only
[py-spy stack](https://github.com/benfred/py-spy#dump) identified the blocked call;
it did not establish its underlying cause. The exact owned test process was
terminated and its parent joined nonzero. That attempt remains failed.

The correction shows a small startup window and invokes the existing picker
from its **Choose task** button after entering Tk's event loop. A fresh installed
check displayed that window, selected the existing inventory specification and
inputs, and displayed the original objective with **Task paused**. One genuine
**Stop engine** click closed the controller. The actual parent joined with exit
0; terminal records confirmed zero provider calls, no native backend launch,
joined retained obligations, and closed GUI, listener and transport resources.
There was no Resume and the inventory task was not executed. UI automation's
unavailable nested element and closed-window refreshes were retained; observation
was refreshed rather than repeating a task control.

Five focused checks passed again for the changed visible-entry flow. This is a
bounded installed launcher/startup/Stop result on the existing deployment, not
new inference acceptance, measured desktop coexistence or reboot recovery.

The checked setup source has SHA-256
`e99f3ae9c235145b150e6136c485a002efa6229d763ba54ac826dc19508134c5`;
the launch source has SHA-256
`e23eebc34323c7fb45cd6a34e741f8ef75b365be76aaf8c47e488345d40bb8fd`.
Both are preserved in the repository and complete source archive. The
component tests are [directly reproducible](../tests/test_desktop_setup.py);
actual installation paths and model assets remain local prerequisites.

## Case17: complete foreground continuation and two-task handover

**1 November 2026: both original terminal audits passed for the same installed
IQ3_S run.** The primary recovery/handover audit passed all 99 checks. The
separate first-admitted-cycle foreground and saved-read lineage audit also
passed. Each audit ran once after both retained supervision processes joined;
earlier failed cases were neither replayed nor combined into this result.
Bounded independent terminal review accepted the combined scenario with no
blocking finding, checking the closed evidence and its source identities.

The service yielded during genuine document work, preserved the saved input
read and original task through its 900-second resource-wait expiry, and
continued after one explicit **Continue saved task**. The inventory output
matched the independent 23-unit oracle. **New task** selected a distinct welcome
task and session in the same retained controller; it completed with format-only
acceptance. One **Stop engine** produced normal shutdown and verified release
of the owned workers, windows, native services and connections. Six cumulative
provider calls produced two physical output writes. The original prompt,
history and inventory output remained preserved across the task handover.

Actual controls were one Resume for each task, one Continue, one New task and
one Stop, with no Pause or Retry. A file-picker value-setting attempt was
rejected by the UI automation helper and recovered through the visible filename
field. That unsuccessful input is retained; it did not repeat a task control.

The foreground record contains 25 genuine document actions, 24 wholly before
the expiry seal. The later action is preserved but excluded from preseal
coverage. The maximum adjacent start-to-next-end interval was 54.680872 seconds;
the final preseal tail was 37.453106 seconds. Fourteen intervals missed the
30-second operating target, but none violated the unchanged strict 60-second
coverage gate. The audit verified onset during the same first admitted cycle,
continuous foreground hold and causal saved-read lineage. This is not proof of
GPU preemption or a measurement of desktop responsiveness.

The actual parent joined with exit 0. The GET-only observer joined with exit 1
after three connection errors following shutdown, with the terminal result
already present: 1,618 valid responses in 1,621 samples. Cleanup is established
by the independent retained-process/resource checks, not by those connection
errors. No emergency termination or extra execution budget was used.

The installed runtime source remained
`7306a53085ddc31d53d2ba50e91975c80cfc0014`, with the same IQ3_S assets, 65,536
context, 10,923 output allowance, high reasoning and 8,192 reasoning-token budget.
The three executions retained 900 seconds each, the 2,700-second outer bound,
eight cumulative requests per logical task and the existing admission limits.
The reviewed checker correction used the producer's exact authorization-time
plus 900 calculation; it changed no runtime or acceptance budget. Its
[source and citations](../provenance/explicit-continuation/deadline-arithmetic/README.md)
remain separate from historical acceptance records.

| Retained record | SHA-256 |
| --- | --- |
| Terminal result | `122af7d5ebdf939d5c7ec5c178c09b2d56b5690106a5324ec2b2458d6c5be6dc` |
| Original primary audit | `6a0e6f14360a4aed403ab1efdbb946daf6c0f151162aad24bf4e3141aa81b4d0` |
| Original foreground/lineage audit | `8fa5059cb817e5ebd8228ead738bc36e8e388b2abba53d0f3dc75ba7b7431cc5` |
| Actual UI observations | `8be65e46288848c8f078a8ebe5e82f893958192b494a24239a34d72cbfc220e9` |
| Actual supervision joins | `9f57602d8c5342409de4233fb3b0724d23fdb8cef0b74ff7003d152397c06b26` |
| Corrected harness manifest | `75809e201f9b8b6595ea429f605f19b92ded944fb8b16527be4a9ba9ca5fc4f3` |
| Independent terminal review | `4c4d44b689a4fb01bc55c1450b457f54cfd05d1f1f27b8fdec462490c5847cd6` |

These hashes identify retained private evidence. The subsequent
[public acceptance package](../provenance/task-handover/acceptance/README.md)
preserves the sanitized result, fixed selectors, tested build/runtime map and
file-only replay. Actual replay and replay with all 33 inputs relocated produced
identical public result/manifest bytes. The relocated replay attempted no
database, process, network or shell calls and imported no runtime module.
The [fresh-run workflow](../examples/validation/task_handover/README.md)
preserves the exact harness/predicates and five narrowly reversible helper-path
adaptations. Seven focused source/fixture checks passed on Python 3.11.9 and
3.12.9; eight exporter checks passed on Python 3.11.9. Those checks are not
another model trial. Two exporter authoring refusals were retained: selecting a
binding digest from the wrong receipt field, and substituting a resolved path
for the model's original raw read argument. Both were corrected without changing
the original predicates; neither refused attempt created output.

The public source workflow still requires actual installation/deployment
records and external IQ3_S assets. It does not provide an automatic fresh-machine
installer or the private inputs for replay. The next practical delivery is a
usable installed reference using the existing host and task controls. Full M2,
computer restart, games/video coexistence, autonomous media quality and speedup
remain separate requirements. Cases14/15/16 below keep their recorded failures.

The checker/reporting head `f049342060b3ae8d04f237bf5632d2b9f459869d` passed all
14 hosted jobs on their original attempts: [PR run](https://github.com/midhatn/adaptive-inference/actions/runs/41257834524)
and [push run](https://github.com/midhatn/adaptive-inference/actions/runs/41257830828).
Those are source/CI results for that exact commit, separate from the installed
runtime identity and from later documentation commits.

The subsequent reporting-only head
`bd0abd7cee7a4589b13d89f6bee08e0a5f914b95` also passed all 14 original attempt-1
jobs: [PR run](https://github.com/midhatn/adaptive-inference/actions/runs/41260983340)
and [push run](https://github.com/midhatn/adaptive-inference/actions/runs/41260978937).
This is separate from validation of the later public workflow/exporter code.

## Safe resource-wait expiry and continuation development

The [resource-wait recovery extension](admission-wait-recovery.md) handles a
saved, undispatched request whose execution budget expires. Source and component
checks cover its exact checkpoint and control prefix, verified cleanup, explicit
continuation, repeated execution generations and preserved cumulative limits.
The predecessor keeps the complete old request; the continuation grant records
its digest, and the successor rebuilds through the supported saved-conversation
entry. A later error after
an operation starts still requires reconciliation.

The public [saved-history SDK check](../examples/validation/hermes_saved_history/README.md)
exercises the actual pinned Hermes conversation prologue, request builder and
middleware with a scripted terminal response and checked import origins. It is
not a full agent or model trial. The [source lineage](../provenance/task-handover/safe-admission-wait/README.md)
preserves the narrow predecessor inputs needed to reproduce earlier acceptance.

Hosted Linux/macOS checks on `0cacf969` exposed four fixture errors: a synthetic
900-second expiry was checked against the host performance counter. Python
documents that counter's [undefined reference point](https://docs.python.org/3.11/library/time.html#time.perf_counter).
The same four errors were reproduced locally with a simulated host clock of
100 seconds. The corrected fixture uses its existing synthetic clock for the
receipt check too. All 34 affected tests then passed on Python 3.11/3.12; an
additional long-host-clock run passed on 3.11. The added regression still rejects
pre-seal and nonfinite observations. Runtime code and expiry guards are unchanged;
the earlier hosted failures remain part of the history.

The following Windows Python 3.12 check on `24713ab3` failed while opening a
CPU-fixture readiness marker in setup. The bounded
[readiness correction](../provenance/task-handover/fixture-readiness/README.md)
retains the original child and time limits. Its deterministic denial reproduction
and actual Windows sharing-handle regression pass; all 50 focused Python 3.12
source/CPU-child checks passed without skips. The exact earlier fixture and
historical manifests remain preserved. This is a test-only change.
The first readiness publication, `c3d99c1`, then failed an older test-reader
identity check omitted from the focused selection. The follow-up preserves the
three dependent test sources and their exact assertions; all 69 lineage and
readiness cases pass on Python 3.12. The earlier focused review was insufficient
for that dependency, and its failure remains recorded in the readiness packet.

The completed checks at `9308707` were **13 successes and one failure**. The
[Windows Python 3.12 job](https://github.com/midhatn/adaptive-inference/actions/runs/40384008747/job/121787353059)
failed during the selected worker's initial Pause acknowledgement, before the
test's intentional result corruption. Its log lacks observation timestamps, so
the exact failed freshness clause remains unmeasured. A separate real CPU-worker
and SQLite reproduction aged one valid observation by two seconds; it produced
the same permanent continuation/database fault with unchanged source. The
[acknowledgement-read correction](admission-wait-recovery.md#delayed-acknowledgement-observations)
is runtime development, separate from the preceding fixture-only fixes. Its
regressions cover expired reads followed by fresh ones, unchanged intent and
cache on discard, deadlines, Stop, child exit, malformed state, actual SQL errors
and strict post-write behavior. The deterministic age injection is not a
measurement of the hosted delay or an installed model result.
The same reproduction passes against the two-module candidate: the selected
worker completes with no runtime faults, both children join without forced
termination, and the source stays unchanged. The focused group passes **48/48**
on each of Python 3.11 and 3.12: 17 new cases, 28 existing mailbox cases and three
existing host cases. Full assembled-source, package and installed gates remain
separate from those focused results.

The new wheel `e8dd65996661c470e0f4be8ad8d5eccea1e0674a3126c1e3d295e1f3ec2d89c7`
has now passed its actual isolated host/worker installation sequence: both
offline installs, both import audits, three installed SDK dispatcher cases,
three shared-clock comparisons, and native-input/resource checks. All seven
steps joined successfully. Independent review confirmed the exact installed
60-module map in both environments, unchanged SDK identities, signed driver
621.01 and preserved prior installations. Private gate SHA-256:
`a07b2b1ece6fb98f86e68a485eff9ca0668effa4190e839f23e3cf2ffc24a888`.
These installation checks do not execute the model task. The new recovery
harness separately passed 41 independently replayed component cases; that is
preparation evidence rather than an observed installed recovery outcome.
That wheel predates the acknowledgement-read correction. Its installation
receipts remain valid for that package and must not be reused for a changed one.

Installed IQ3_S qualification of this extension remains pending. These checks
do not establish native resource release, GUI behavior, physical reboot recovery,
performance, autonomous media completion or a pass for the failed trial below.

The acknowledgement-read successor uses wheel SHA-256
`18469c0cf967f391cbb23433e6496e48756645d8dfb880352936a336413857a4`.
All seven isolated installation steps and independent review passed for that
exact wheel. All fourteen hosted checks passed on source head
`5fd3d7a66590effa3b85d6bcf0d02c6b8f9b0c8c`, including the retry of a Windows job
that had exceeded its whole-job time limit. The original timeout remains a
separate unsuccessful attempt. These are preparation results for case07 below.

## Ordinary-task handover development

The installed two-task IQ3_S scenario remains unqualified. On 26 October 2026,
the candidate built from source head `841989abfcc442f9615a0d1390670a4de8e5c0bd`
used wheel SHA-256
`d2a10deb4a1eb6b911988357b2f8838dd62afe805402ace2367b3ed84b0b5e61`.
Its source tests, provenance checks, fourteen hosted checks and isolated
installation gates passed. The following real run, retained as case06, failed
the original 900-second task budget before completing inventory or selecting
the welcome task. Those earlier passes do not establish end-to-end completion.

One real model request and one inventory read completed, with no output write.
Of 895 valid external observations, 784 showed the engine parked and 720 reported
foreground activity; no controller fault was reported. These are sample counts,
not exact durations or desktop-responsiveness measurements. The original task,
session, three native-history messages, completed read and pending next request
survived, and both terminal databases passed integrity checks.

The worker returned `active / control_wait_deadline` through its generic failure
path. It did not produce a safe-expiry or service-stop receipt, and the shutdown
Pause remained unacknowledged. The product therefore correctly refused to claim
cooperative cleanup. Separate native evidence confirmed all nine retained native
process exits and listener release; the GUI and gateway listener also recorded
closure. The retained parent exited with code 1 after about 912 seconds without
an outer timeout or emergency termination. Both parent and observer were joined.
Observer connection loss alone is not cleanup evidence.

The unchanged acceptance auditor rejected `normal_parent`. An independent
fourteen-check diagnostic review confirmed this failure classification; it did
not pass the task. Two distinct Resume acknowledgements exist, while the root
record shows one successful automated Resume and an earlier rejected input.
The source of the second acknowledgement is unknown; no total physical-click
count is inferred. There is no second task, manual Stop, FP16 result or performance
claim. The installed pause-observation race did not appear in the recorded
exception chain, but this is not proof of absence of all races.

Private terminal result SHA-256:
`881a62f79e60ebe93d7a822a05886f44aee41bb0ea271a46aa83396cf37a7187`.
Independent failure-review SHA-256:
`c1e77836463bd623710f85077754e97a945365113ed4410aeb3bfc5db5823202`.
These identify retained evidence rather than a public reproducible acceptance
receipt. The [roadmap](../PLAN.md) records the safe-wait expiry lifecycle gap and
the separate foreground-coexistence work that this outcome prioritizes.

The next installed run, **case07**, also failed. Its first real IQ3_S request
completed, and foreground activity triggered admission closure and native drain.
The native owner then reported `TerminateProcess` error 5, six retained processes
and only five confirmed exits, although its visible active list was empty.
Server exit zero and an empty list did not satisfy complete release; the adapter
correctly refused it. The worker preserved its pending request and returned its
cooperative service-stop outcome, exit 4. It did not reach verified expiry exit 6,
explicit continuation, task acceptance or a second task.

The host's terminal retention-failure loop cannot retry cleanup or produce a
successful result. Root explicitly terminated that exact runner after checking
its creation identity, executable, command and parent, then confirmed exit using
the same retained handle. Its original supervisor observed runner exit 125. The separate
root receipt records external emergency termination; the supervisor's own
`emergency_termination_attempted=false` describes only its unused timeout handler.
It is not a clean Stop. Both test listeners and observed test processes were
absent afterward, which establishes containment rather than product release.
The external observer recorded 473 valid responses and three connection errors;
connection loss does not establish successful shutdown.

The exact kernel timing was not captured. The receipt is consistent with a
documented Windows exit race, and the [roadmap](../PLAN.md) now prioritizes a
bounded same-handle termination check. Neither error 5 nor PID absence may be
accepted as exit without that signal and complete retained-process accounting.
The original failed case and native source remain preserved; a changed owner
requires its own deployment identity and fresh installed qualification.

The [native-owner correction](../examples/validation/windows_handoff/native/README.md#termination-denial-during-exit)
passes 30 focused source checks on each of Python 3.11 and 3.12. Two independent
checks cover the shared cleanup deadline across handles and unchanged complete
release requirements. An additional Windows CPU-child probe uses actual retained
handles, job membership and waits, with only termination denial and release
coordination injected. The predecessor retains its error; the candidate signals
and collects every owned process. Both children exit normally and are joined.
The reviewer's first collector incorrectly assumed one owned process; Windows
also created a console host. That failed review attempt remains preserved, and
the fresh replay checks complete owned-descendant accounting. These results
qualify the narrow source behavior, not a fresh native-model release or full
task handover. Independent review SHA-256:
`9e3d3ecd621b3e9b74b0ea0c3d79a31df9c3dcd0bcf43e788f60534d0f32b1b1`.

Hosted CI at `fc84187c124b9fbed9e115cc88a713c941eabd21` subsequently caught an
omitted historical source selection in the older arithmetic/shutdown checks:
those checks still compared the newer native helper with an exact predecessor.
The [correction](../provenance/windows-handoff/termination-race-predecessor/README.md)
preserves both original readers and every original assertion, verifies current
and predecessor hashes for exactly two declared helpers, and keeps other inputs
current. The affected 11 arithmetic and nine shutdown tests, three new source
selection tests and 81 provenance checks pass on Python 3.11 and 3.12 (104 per
interpreter). Independent source review passed 15 checks. These local results
belong to `d07f1012f6ae736ab90d2c8e8ceeb09055c72396`; hosted checks on the
corrected commit remain a separate gate. The original failed CI is retained.

On 30 October, all 14 hosted checks passed for research-integration commit
`920c0a577321d20a2f3f77174a68df3627a97f3c`. Its source archive verified all 1,072
expected source files and its wheel verified all 60 runtime modules plus the
required notices. This new archive was not installed over the qualification
wheel. The preceding `d07f101` push run passed all seven jobs; its duplicate PR
run finished with six successful jobs and one cancelled Windows job. Those
outcomes are retained separately.

### V6 inventory completion and the missed recovery boundary

The fresh case08 used the repaired v6 owner and unchanged IQ3_S runtime. Its
inventory worker completed three actual provider requests, executed native
`read_file` and one physical `write_file`, and produced the independently checked
23-unit result. The original prompt and native history were preserved. The
worker returned zero and its retained process was joined.

The task completed before the intended foreground resource-wait boundary.
The operator performed one Resume and one Stop; no safe expiry, Continue or
second task occurred. The parent therefore returned one, the original auditor
refused `normal_parent`, and the whole result retains both
`qualification_case_passed=false` and `clean_stop=false`. Missing operator
observations were left missing. This is a failed recovery qualification, not a
replacement for the required two-task acceptance.

The component cleanup evidence is narrower and positive: normal native release
confirmed all five retained descendants and the separate owner handle exited,
with server exit zero. GUI, pipe, listener, transport and asynchronous obligations
were closed or joined; no emergency termination was required. A recorded error 5
belongs to `QueryFullProcessImageNameW` during identity capture, so it does not
prove that the new termination-denial branch executed.

Independent review passed 48 evidence-integrity checks across 383 source and
evidence identities, using the existing terminal task/native/artifact validators.
Review SHA-256:
`7e2616824e96ab28a4ab42444a28f184020da3618498c2c8773d6f676ff95592`.
The live status exposed neither successful native `read_file` nor the saved
undispatched request. Gateway completion was not treated as proof of either.
The [roadmap](../PLAN.md) revises the next experiment around an observable
in-flight boundary and immutable evidence afterward, without changing this
failed result or weakening task-progress, ownership and budget requirements.

### Foreground release and restoration with an unsuccessful timing test

Case09 retained the same installed wheel, IQ3_S quality and v6 native owner.
The original inventory task completed after native release and restoration:
three real provider requests, one native read, one native write and one physical
output write. The independent oracle accepted 23 units. Artifact SHA-256:
`f279173777ec0ddcbe467a5370337b8a4d4fa3c09c4c211e1740e8f1232a8e3e`.

The declared scenario required foreground activity during the first admitted
request, with open admission observed before the action and that same request
still active afterward. The trace contained 46 first-active observations, but
the action began about 9.11 seconds after the last of them. The latest complete
pre-action sample already showed the second request active and admission closed.
The post-action sample showed foreground-driven draining during that later
request. These observations do not satisfy either required onset condition.

The operator record also rounded a 64-bit Windows process-creation value while
transferring it through JavaScript. The immutable pre-Resume capture retained
the exact value and matched the actual retained GUI identity; the consumed UI
record remains inconsistent. This is a test-recording limitation, not evidence
of a changed runtime identity. Future binding transfers must preserve integers
through the existing [Python JSON reader/writer](https://docs.python.org/3.11/library/json.html).
[RFC8259](https://www.rfc-editor.org/rfc/rfc8259#section-6) explains the common
binary64 integer-interoperability limit that this Windows identity exceeds.

Both native owners released normally, confirming 7/7 and 8/8 lifetime descendant
exits. The final release separately retained six stop-time handles: its owner
and five then-active descendants. The first complete stop-time handle list was
not persisted, so that detail cannot be reconstructed. Worker, GUI, pipes,
listener, transport and asynchronous cleanup records support closure; there was
no emergency termination. No termination-denial branch coverage is established.

Independent review passed 60 integrity/component checks across 401 pinned files,
SHA-256 `720dfca7e4a962016097a0312e0e6b1ab6fc6936d0bf6c9e0d3e4b2256ddfb61`.
The separate native review is
`47b650e26c5aadb7d9de522d77b41711255b17e8f9bbd3426a05c7a3097c7977`.
No safe expiry, Continue or second task occurred. The original parent returned
one, the original auditor failed `normal_parent`, and both
`qualification_case_passed=false` and whole-trial `clean_stop=false` remain
unchanged. The supplemental auditor was not used as an alternative. These
component results do not qualify the full recovery workflow.

The next correction is limited to the operator procedure: promptly observe the
existing append-only GET trace, bound all UI text output, perform a fresh genuine
action, and copy complete identity records without integer rounding. Runtime,
quality, task acceptance, timing predicates and execution limits remain fixed.

For documentation/ledger head `e85b68147613f476bd89da834ec0939aa6391e51`, the
[push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41035632823)
passed all seven jobs. The [PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41035639711)
passed six; its Windows/Python 3.11 job exceeded the cumulative 15-minute job
limit during core test discovery, and later steps were skipped. The checkouts
have identical tree `1a52efe071dc59d1638c3924b36b03ad4e7d7a6a`. The successful
Windows job completed 1,258 core tests in 447.901 seconds and its remaining steps.
This is 13 successful jobs and one cancelled job, not 14 passes; the differing
duration is not diagnosed as an infrastructure-only failure.

### First-request foreground transition with an unsuccessful continuous hold

Case10 kept the same installed wheel, IQ3_S quality, native owner and execution
limits. Its bounded cue used only the existing append-only GET observer; the
operator then inspected a fresh screenshot and performed actual document input.
The trace records the same first request active with admission open before the
input, then active with admission closed for foreground activity and draining
afterward. It subsequently records that request complete and the engine parked.
This establishes the onset component, not the complete recovery scenario.

The interval from the second action's start through the third action's end took
**66.1093105 seconds**, exceeding
the unchanged strict `<60` condition. Trace samples also changed to foreground
recovery margin/dwell. Admission remained closed and no second request dispatched
during that gap, but continuous foreground hold was not established. The operator
returned to quiet recovery and allowed the original task to finish within its
existing budget, then used normal Stop once. There was no extra Resume, safe
expiry, Continue or second task.

The inventory oracle accepted **23 units**, three real requests, one native read,
one native write and one physical output write. Artifact SHA-256:
`48de85ae982b910b3f88139528b182c45fdce62c0e005428e0aea2d49c7d1af9`.
The Python recorder preserved the complete A binding exactly, including its
64-bit integer creation identity, while leaving all nonbinding action fields
unchanged. Its three recorded input hashes and output/backup hashes were checked.
B and expired-window transfer were not exercised by this failed attempt.

Both native owners released normally, confirming 10/10 and 7/7 lifetime
descendant exits. The final stop set separately retained the owner plus five
then-active descendants; two lifetime descendants had exited earlier. The first
complete stop-time handle list was not persisted. Worker, GUI and associated
cleanup records support closure without emergency termination; monitor joins
remain inferred from successful pinned close paths rather than separate raw
thread-join flags. No termination-denial branch coverage is established.

Independent review retained 60 component/integrity checks across 439 input
hashes, receipt SHA-256
`0664d15d8ef4e1128a475684e0a410159bb9a5e60fc2bebcbf268d6e09911516`.
The separate native review is
`1b268a113b8e02af7fbffb3b2860b3b25b34974022d6c8a7a8cdeeb5b49e0c95`.
The original parent returned one and its auditor failed `normal_parent`;
`qualification_case_passed=false` and whole-trial `clean_stop=false` remain
unchanged. The supplemental auditor was not run. Component evidence does not
convert the consumed case into a qualification pass.

The review also preserved a checker assumption and its narrow correction. The
native read used the exact absolute path of the bound 70-byte, four-line input.
An initial component assertion expected a literal relative path; its failed
receipt remains preserved. The successor review checked the exact bound path,
input hash, full returned content and native intent/result. It did not change
the original supplemental lineage rule, whose literal-relative-path predicate
remains unestablished. A future equivalence rule needs separate source review
before another case; matching content or basename alone is insufficient.

The preparation's 22 new synthetic helper tests and two additional independent
failure cases cover bounded observation and lossless recording. They are not
runtime qualification. The next operator correction uses existing QPC feedback
and a 30-second action target, deferring nonessential work outside the hold while
retaining the strict 60-second condition and genuine observed input. See the
[roadmap](../PLAN.md) for the remaining gates and citations.

### Resource waiting interrupted by the agent's inactivity watchdog

Case11 retained the same installed wheel, IQ3_S assets, quality settings and
execution limits. The first actual document action occurred while the first
request was active and admission was open. The next retained observation showed
that same request active with admission closed and the controller draining for
foreground activity. The request completed and the native engine parked.

There were 27 actual document actions. Their maximum adjacent start-to-next-end
interval was **38.4695074 seconds**, below the unchanged strict 60-second limit.
Some actions occurred after the worker failed but before the operator observed
the failure, and remain in the truthful record. No expiry seal exists, so this
does not establish the complete continuous hold through safe expiry.

Hermes's turn watchdog reported **611.1 seconds without activity**, last labelled
as starting the second API call. Its committed interruption caused the existing
guard to refuse further authority. The saved state and ledger contain one
request, one attempt, one admission and no deferrals; the admission-attempt limit
was not reached. The original task, exact 70-byte/four-line input read, three
native history rows and prepared second request remain saved. There was no
output write, task acceptance, Continue or second task. A one-shot readiness
check correctly refused the already-terminal case instead of creating an
expiry receipt.

One native lifetime released normally: **8/8 retained descendant exits**, plus
the separate retained owner. The final stop set had the owner and five then-live
descendants; three other descendants had exited earlier. GUI, pipe and listener
closure are supported by failure-containment receipts. The transport still
records `stop_failed`, and cooperative product Stop remains unconfirmed.
The parent and observer returned one; no timeout or emergency termination was
used. The original auditor ran once and failed `normal_parent`. The supplemental
audit was not run. **Qualification and whole-trial clean Stop remain false.**

Independent terminal review retained 762 component/integrity checks across 367
input hashes, receipt SHA-256
`623def7fcb5ac22ce179ab7f13c20937516a0edf44612638c3fbe527b5662099`.
Its separate native review retained 108 checks and 32 input hashes, SHA-256
`08a070a5b1b29314ecae11389581f0fda08250e6f3f0431c46b939dd50386e48`.
The A-only Python recording preserved the complete integer identity and all
nonbinding action fields. No expired-window or B observation was invented.

Source inspection explains the integration gap: the case11 guard reports an
acknowledged user Pause, while admission waiting performs health checks without
an activity stamp. The subsequent source correction reuses the existing coherent owned
wait observation and serialized activity guard before the original deadline.
It does not disable Hermes's watchdog or renew task authority. The inspected
[merged Hermes activity fix](https://github.com/NousResearch/hermes-agent/pull/131916)
supports reporting a previously invisible legitimate activity; it concerns MoA
streaming, not this adaptive wait. The [roadmap](../PLAN.md) records the required
focused, installation and fresh physical qualification gates. Case11 remains
consumed and failed regardless of any later correction.

### Admission-wait activity correction: source and SDK components

The correction changes only `desktop/hermes/pause_activity.py` in the runtime.
It derives a fresh coherent wait only for actual waiting/active demand and a
saved, undispatched request. It checks the exact checkpoint, request, native
history, owner and original deadline, then reads the SDK lease and current time
after potentially slow reads. Changed identity, interruption or cleanup
revocation prevents another activity stamp. The existing 15-second cadence and
900-second execution bound remain; no timer, automatic Resume or lease renewal
is added. Pause with newly arriving Resume/Cancel retains its normal control path.

Nineteen focused tests pass against the final source. A controlled-clock worker
case waits beyond 600 seconds and reaches the original 900-second safe expiry
with its request and completed read preserved, without another provider dispatch
or tool effect. Ten affected selected-worker tests also pass after their scripted
agent gained the existing SDK activity hook. The first regression run retained
124 successes and seven failures caused by that fixture omission; its original
candidate and failed output remain distinct from final-source results.

The optional [actual Hermes component check](../examples/validation/hermes_admission_activity/README.md)
passed all three cases on the pinned worker interpreter. Its healthy wait uses
the actual activity writer and watchdog for 60 activity stamps through execution
second 885, with no stamp at 900 or 901. An otherwise silent turn is actually
interrupted at 600 and its lease component deactivated; the guard cannot revive
it. A bounded contender exercises a reserved abort claim that verified owner
activity invalidates, then joins without publishing an interruption. Receipt
SHA-256: `5f3d1ec8468d8609f6fad269ec802f648f40ddc4ba69cdb41e65f51727221106`.
These are controlled-clock components with reduced SQLite and a scripted lease
row, not a complete agent, durable SDK heartbeat, physical-time benchmark or
installed IQ3_S recovery. The existing SDK dispatcher and saved-history checks
separately pass three and two cases against the changed source.

The existing source-preservation mechanism retains the complete previous module
and two original source-test readers; all 59 other runtime modules stay unchanged.
Fifty-four affected source/AST checks passed separately on Python 3.11.9 and
3.12.9. Independent review confirmed exact prior bytes and rejection of an unknown
input. Historical source assertions and manifests remain intact.

The complete source suite passed **1,282 tests with no failures or skips** on
Windows/Python 3.11.9 with all 15 locked dependency versions, in 329.279 seconds.
All **81 source-preservation tests** passed separately. The source receipt is
`114d361588e26c16e2c16ccaf3b1bb7b3a98b661c0c671e316e2d3ab9c44ff0e`;
the preservation receipt is
`6b234af37ce54751cf0694f67183a74a55b27efddbefcf804c92fceda780bf15`.
These test durations are validation timings, not inference performance results.

The preceding full run remains failed: 28 child-readiness identity failures and
one resulting cleanup-control failure. Its virtual-environment executable was a
Windows redirector that started a second process, whereas the fixtures require
the actual child to retain the launched PID. A bounded local probe and independent
review confirmed the mismatch. The corrected run used the full interpreter and
the same pinned libraries; all 1,084 source hashes, 1,282 test identities and
assertions were unchanged. No identity check was relaxed. This follows the
version-matched [CPython launcher behavior](https://github.com/python/cpython/blob/v3.11.9/PC/launcher.c#L755)
and its [multiprocessing treatment of the redirector](https://github.com/python/cpython/blob/v3.11.9/Lib/multiprocessing/popen_spawn_win32.py).

Fresh archive checks verify 1,084 source paths, all 60 runtime modules, wheel
RECORD hashes and license files. Publication then adds a narrow Git attribute
rule to preserve the tested SDK reference file exactly; an actual checkout with
`core.autocrlf=true` preserves its bytes. The roadmap and this evidence account
are updated after validation. These three metadata/documentation changes are
recorded separately from the unchanged tested program and are checked in the
final archive; behavioral suites are not repeated for them. Existing failed
runs and the first archive remain preserved. The fresh isolated installation
has since passed all eight steps and independent review. It checks both installed
environments, dispatcher and admission-activity SDK components, shared clocks,
native inputs and predecessor preservation. The physical results below do not
requalify case11 or establish general foreground performance.

### Current installed head and physical recovery checks

Exact source `7306a53085ddc31d53d2ba50e91975c80cfc0014` passed all **14 hosted
jobs**, seven each in the [PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41062578967)
and [push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41062565459),
on their original attempts. The twelve portable jobs reported 1,282 core tests
and 81 preservation tests, with explicit platform skips: 36 on Linux/macOS, one
on Windows/Python 3.12 and none on Windows/Python 3.11. The two source trees were
identical. Earlier failures and cancellations remain separate outcomes.

Wheel `50919bc2dd7c4cabdc661f57cab387d2df0eb999e3ca467a03852ed6ea15e33f`
passed the eight-step isolated installation. Independent gate
`c32e20a02463bb414497e9c6d697c220eaaa105a13c2f9a71c1a5f4844e22a1c`
binds the installed 60-module payload in both interpreters, dispatcher checks,
three actual SDK admission-activity cases, clocks, native inputs and predecessor
preservation. This establishes installed-component readiness, not a resource
reservation, physical task acceptance or a performance gain.

| Physical evidence | Observed result | Limit |
| --- | --- | --- |
| Case12 original task | Safe expiry, one Continue and the independently checked 23-unit inventory output; three cumulative model requests, one input read and one physical output write. | The old private checker required a completion-only prompt hash from the expired worker and raised `KeyError`, before recovery-acceptance publication, task B or user Stop. Whole qualification failed. |
| Corrected prompt-hash checker | Both workers retain model, quality, context, SDK and fixture checks; the successful worker retains the mandatory prompt digest. Independent original/selected prompt and metadata comparisons remain. All 44 focused tests passed with no skips, followed by independent source review. | Private harness correction only. Its initial fixture expectation error remains preserved; no runtime change, deadline extension or retroactive case12 pass. |
| Case13 task A | Actual controlled expiry and one Continue led to published safe-wait and inventory acceptance. The 23-unit output, original prompt, saved read and history remained exact after task B. Three cumulative requests and one physical output write. | This is the original-task recovery component, not a complete foreground/two-task qualification. |
| Case13 task B | A distinct task and session read the bound brief and wrote one 382-byte text output. Its worker and durable task record reported completion after three requests. | Format-only validation; no semantic-quality claim. The checker failed before publishing B acceptance or observing user Stop. |
| Case13 foreground and cleanup | Twenty real document actions were retained. Five native lifetimes recorded complete descendant release; both GUI endpoints, pipes, listeners and transports closed. | The 202.0352201-second action gap fails the strict 60-second rule. Both invocations joined with exit 1. Cleanup after failure is not normal user Stop; `qualification_case_passed` and `clean_stop` remain false. |

The case12 checker correction follows the published producer: its
[successful result](https://github.com/midhatn/adaptive-inference/blob/7306a53085ddc31d53d2ba50e91975c80cfc0014/src/adaptive_inference/desktop/hermes/run_recovery.py#L569)
contains the prompt digest, while its
[expiry result](https://github.com/midhatn/adaptive-inference/blob/7306a53085ddc31d53d2ba50e91975c80cfc0014/src/adaptive_inference/desktop/hermes/run_recovery.py#L633)
represents incomplete work. The initial added fixture expected a later refusal
than the existing durable-store validator actually produced. That failed test
attempt is preserved; the corrected regression checks the earlier refusal and
comparison with the independently retained prompt. The acceptance predicate
was unchanged between those test runs.

The case13 discrepancy was in the receipt reader. The
[producer](https://github.com/midhatn/adaptive-inference/blob/7306a53085ddc31d53d2ba50e91975c80cfc0014/src/adaptive_inference/desktop/hermes/recovery.py#L454)
writes UTF-8 JSON lines with unescaped Unicode. The checker omitted an encoding.
Python 3.11's [text-file default is locale-dependent](https://docs.python.org/3.11/library/functions.html#open),
and [PEP 597](https://peps.python.org/pep-0597/) describes this Windows portability
error. Independent decoding of the unchanged receipt as UTF-8 equals the durable
write exactly. Decoding those same bytes as `cp1252` reproduces the discrepancy
solely in two em dashes in the original text. IDs, path, fingerprint, result and
artifact hash match; this does not establish a duplicate or lost write. The
separate post-run host observation reports `cp1252`, but is not presented as a
historical in-process encoding measurement.

The fresh private checker changes only that reader to explicit UTF-8, retaining
strict decode failures and every content, identity and duplicate-write check.
All **47 focused tests passed on their first invocation**, with no failures,
errors or skips and unchanged tested source. The 44 existing tests remain; three
new tests exercise the actual reader on real UTF-8 receipt files under a
deterministic legacy-encoding default, reject malformed UTF-8, and retain
refusal of changed content, call/operation identities and duplicate receipts.
The fixture reuses the existing real SQLite recovery producer with its reduced
native-history fixture; this is not a full SDK or model test.

A separate read-only projection of the closed case13 B files reproduces the old
reader's refusal and confirms that the corrected reader recovers the actual
three requests, six native-history rows and one 382-byte write. The downstream
check reaches missing GUI-resume records after its preceding task, quality,
prompt, wire and artifact checks. Complete B transport and job-identity fields
were not persisted, so none were invented. This partial retrospective diagnosis
cannot publish the missing case13 acceptance or supply user Stop. Focused-test
receipt SHA-256:
`6a4da3af5d417e5301243e9516c1a24ce3dcde053128263b705bde33cfa60a3a`.

The original primary audit failed at `normal_parent`; the official foreground
supplement was not run. Independent evaluation of the unchanged onset predicate
rejects the retained activity gap. Neither issue is removed from case13.

The independent case13 review passed 471 evidence-integrity checks across 391
pinned files, SHA-256
`7760b9b325ab0258a6fd902d0a77f13eddf1e7c5044c7ee4e47664aae761b3cd`.
These identify retained private evidence, not a public reproducible acceptance
receipt. Case12's corresponding review is
`48578b0df4a4d712cf33c627fc329ba0ea0c0e8dc32468af7b5a52a44edcc4e2`.
The [roadmap](../PLAN.md) keeps a fresh complete qualification as the next live
gate. No physical reboot, general media-quality, arbitrary-engine or performance
claim follows from these results.

#### Case14: primary recovery/handover passed; foreground supplement failed

The fresh run used the same installed `7306a53` payload, V6 native owner, IQ3_S
assets and quality, with the reviewed UTF-8 checker. Its original 900-second
execution budget expired during a verified safe resource wait. An actual expired
screen was observed before one Continue. The inventory task then produced the
independently checked 23-unit result and published safe-wait and task-acceptance
records. A native task/file chooser admitted the separate welcome specification
and input directory; its new window was captured before one Resume. That task
published its own format-only acceptance. One user Stop completed normal cleanup.

The unchanged primary audit passed **99 checks**. Six cumulative provider calls
produced two physical writes, one per task. The original inventory prompt, read,
history, output and counters remained intact across continuation and task B;
the second task had separate task/session authority. The parent joined with exit
0 after 1,457.406 seconds, with no timeout or emergency termination. Three native
lifetimes accounted for 7/7, 6/6 and 6/6 descendants, and both GUI endpoints,
listeners, transports and all five retained preparation/worker processes closed.
The external observer joined with exit 1 after its expected three connection
errors following service closure; its 1,439 valid observations are not themselves
proof of cleanup. Retained owner evidence supplies that proof.

The additional first-inflight foreground audit nevertheless returned
`hold_not_preserved`. All audited hold rows kept admission closed, with no second
dispatch or reported backend uncertainty. Twelve early rows had a different
reason: eleven `foreground_recovery_margin` and one `foreground_recovery_dwell`,
instead of the predicate's required `foreground_activity`. The later parked
observations and normal task recovery do not erase this refusal. The lineage
stage after that failed predicate was not reached. Thus the product's recorded
`qualification_case_passed=true` belongs to the original primary audit;
**the combined foreground/recovery scenario is failed**.

The operator retained 55 actual document actions. Their maximum adjacent
start-to-next-end interval was 29.4707506 seconds; the last completed pre-seal
action began 7.6725251 seconds before sealing. Those pass the unchanged temporal
coverage requirement. The first record was standalone window activation, however,
and the first navigation key followed about 17 seconds later. All twelve reason
violations occurred before that key. A `foreground_activity` sample also returned
before the key's bracket, so the key is not presented as the proven sole cause of
the transition. Compact action notes and clocks were retained during the hold;
the structured captions were transcribed afterward from the displayed UI
observations, with that provenance declared and the original compact log kept.

Microsoft distinguishes [last session input](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)
from [foreground activation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow).
The latter documents focus and input routing, not a guarantee that activation
refreshes the input-event timestamp. [Keyboard/mouse input](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
is a separate operation. These contracts and the retained action sequence support
a prospective procedure correction, not an independently measured historical
input age: the observer does not save raw input-age/CPU samples. The existing
policy keeps admission closed in both recovery states. No runtime or acceptance
rule is changed to turn this run into a pass.

The next first action will retain the full useful transition when activation is
needed: QPC before activation, activation and refresh, inspection of the actual
document, an immediate state-derived navigation input and refresh, then QPC after.
Both UI substeps and their latency remain explicit. Each input uses a separate
observed UI call; there is no automatic key loop. If latency misses the original
inflight request, the unchanged overlap check must still fail. The original
case14 records will not be regrouped, retried or reclassified.

Primary audit SHA-256:
`1e218b3f2c56c74d1fd5d1ee049ab46f6091babcb1f68ef7bad7f58f7ae3d569`.
Failed supplement SHA-256:
`640feeab44a1e700daf769bf1c0df18901473aaaa2d3408c86575253bd41fdf1`.
Independent terminal review passed 3,059 evidence-integrity and identity checks
across 2,866 pinned files, preserving the failed combined outcome. Its SHA-256 is
`330933877ab119086cf98a43621f5a9cb63bb4bbfa9912a40041bc126d3987b7`.
The review verifies the preserved compact action records and declared caption
provenance; it does not independently reconstruct unsaved screenshot contents.
These identify retained private evidence, not a public reproducible acceptance
release. The full foreground gate and sanitized reconstruction package remain
required before advancing the combined milestone.

For the preceding documentation-only head `ac5d5b9`, the
[PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41081619157)
passed all seven jobs, while the
[push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41081611814)
passed six and cancelled Windows/Python 3.12 at its cumulative 15-minute limit.
The cancelled job had passed its core and preservation suites and built packages;
the timeout interrupted archive reading. Its equivalent PR job passed on the same
source tree. This remains **13 successes and one cancellation**, without a retry;
it does not replace the separate 14 successful jobs for the installed source.

#### Case15: primary recovery passed; foreground coverage failed

On 1 November 2026, a fresh case used the same installed `7306a53` runtime,
V6 owner, IQ3_S assets, quality and original budgets. The unchanged primary audit
passed **99 checks**: safe admission-wait expiry, an observed saved-work screen,
one Continue, the original inventory acceptance, a separate welcome task and one
Stop. Six cumulative provider calls produced two physical writes. Inventory has
the independent 23-unit oracle; welcome remains format-only. The primary result
is bounded private evidence, not a complete foreground or public reproduction pass.

The actual parent joined with exit 0 after 1,458.437 seconds, without timeout or
emergency termination. The observer joined with exit 1 after three connection
errors following closure; it retained 1,442 valid status responses. The primary
owner audit verifies cleanup separately. A subsequent read-only process/listener
observation found no remaining owned runtime processes or qualification listeners.

The foreground supplement failed at **`real_activity_hold_gap`**. All 32 recorded
document actions finished before the wait was sealed, but action24's start to
action25's end spanned **63.3778490 seconds**, violating the unchanged strict
less-than-60-second requirement. Their individual brackets lasted 0.5465117 and
0.5281718 seconds, with 62.3031655 seconds between them. Across 31 adjacent
intervals, the median was 22.0501411 seconds; four missed the 30-second operating
target and one failed the actual 60-second gate. The final pre-seal action began
18.5124573 seconds before sealing.

The first action now truthfully included activation, an inspected document
refresh, a meaningful navigation key and its refresh, spanning 7.6786183 seconds.
This does not prove that the onset correction qualified: the supplement stopped
at coverage before evaluating the later onset, continuous-hold and lineage
predicates. The original primary `qualification_case_passed` field does not
override the failed combined result. Case14's different failure remains unchanged.

The action record does not attribute the missed interval to reasoning, tools,
service scheduling or the runtime. Microsoft recommends [QPC for same-machine
elapsed intervals](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps),
and Python's [performance-counter contract](https://docs.python.org/3.11/library/time.html#time.perf_counter)
includes time elapsed during sleep. Neither guarantees an operator response deadline.
Keep the actual elapsed interval; do not subtract time or infer a product defect.

The next procedure review will reduce work between genuine observed actions:
retain short factual notes, defer polished analysis, and place required progress
messages after a completed action and before the next fresh observation. Assess
that operator path with bounded genuine work before another model trial. This
is a prospective feasibility step, not a measured fix. All predicates, models,
quality, time/request budgets and failed records remain intact; no automatic
input or synthetic activity is introduced.

Primary audit SHA-256:
`d5fc3f8cb51539cfc1b354f6276a5b79d6bf3b1e29714ed0b1d5bd7a881d8391`.
Failed supplement SHA-256:
`57e7593e3b8e33450809338b3fcd8e2cb7e310bf529fd0bb2f9236e21b0572b6`.
Foreground action record SHA-256:
`8b984335689292b9f92f04523a3f560854ee134f9d44c65bfe66dcdce03851c2`.
Independent terminal review passed 355 integrity/identity checks across 111
exact input pins, confirming the original inventory oracle, source identity and
retained cleanup while preserving the failed combined result. Review SHA-256:
`f542262d749bf5b54f26748cc6fc11ed22e8f8540e7ef9c86aee55bfac191829`.
These hashes identify retained private evidence. They do not make that private
run publicly reproducible or establish physical reboot, media quality, general
desktop responsiveness or a performance improvement.

Separately, development revision `33ae7f01c3deba44e6f11d2a546fdff26029b7ea`
passed all **14 original-attempt hosted jobs** in its
[PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41249549616)
and [push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41249544792).
All four Windows jobs reported 1,290 core tests and 81 provenance tests; Python
3.11 had no core skips and Python 3.12 had one. Both new timeout-diagnostic
regressions and the original successful-continuation test passed in all four.
Their archive checks verified 1,097 source files and 60 runtime modules. The PR
checkout and published package share tree `5140531a0a9187fe08de3c21a5617e91365e6d8d`.
This leaves installed `7306a53` unchanged and does not explain or erase the prior
`4d2f5a7` result of 13 successes and one actual timeout failure. Later reporting
commits require their own applicable checks; these CI results are exact-revision evidence.

#### Case16: original task completed; exact-duration checker failed

The next fresh run retained installed source `7306a53`, the V6 owner, IQ3_S
assets, quality and all original limits. It reached verified safe resource-wait
expiry, displayed the saved-work screen and received one Continue. The continued
inventory worker completed with the independently checked 23-unit result. The
private qualification checker then rejected `one_exact_wait_grant` before
publishing recovery acceptance or selecting the second task. There was no New
Task, Task B or user Stop. The original primary audit ran once and failed
`normal_parent`; the additive foreground audit was not run. **The whole case
remains failed**, including its `clean_stop` claim.

Closed-data diagnosis evaluated all fourteen conjuncts of the rejected grant
check. Thirteen passed. The sole failure was the assertion that subtracting the
stored authorization time from the stored deadline must equal exactly 900.
The runtime constructed its deadline by adding 900 to the authorization time;
that producer-form equality holds exactly in the saved grant. Binary floating
point subtraction instead yielded `900.0000000000018`, about 1.82 picoseconds
above 900. This is a checker arithmetic defect, not evidence of an added runtime
allowance. The stored predecessor, history, single grant and successor deadline
remained exact in the separate diagnosis.

Python documents that each floating-point operation can introduce rounding and
that reversing an operation need not recover the original value exactly.
The prospective correction checks the producer's addition identity, with finite
numeric timestamps and a deadline strictly after authorization. It keeps the
exact 900-second budget and all other identity, history, quality and request
checks. It adds no tolerance, clock conversion or budget extension. The
[deadline-arithmetic source record](../provenance/explicit-continuation/deadline-arithmetic/README.md)
preserves the original public checker and cites the existing producer and
[Python arithmetic contract](https://docs.python.org/3.11/tutorial/floatingpoint.html).
It cannot retroactively supply the missing second task, Stop or acceptance.

The corrected public example passed its existing aggregate wrapper on Python
3.11.9 and 3.12.9: 52 checks on each, comprising 45 existing checks and seven
focused regression/source-preservation checks. The prospective private
safe-wait checker passed 24 checks on each interpreter, comprising its 19
existing predicate cases and five deadline regressions. These use complete
synthetic fixtures; no model or installed runtime was changed or rerun. The
private successor is not an activated qualification harness. Independent review
cleared the correction and reporting; source preparation and the next functional
model run remain pending.

The closed foreground record contains 27 actual document actions. Its maximum
adjacent start-to-next-end interval was **48.813776 seconds**, with nine misses
of the 30-second operating target and no interval reaching the strict 60-second
boundary. The last completed preseal action began **8.759196 seconds** before
sealing. The first complete activation/inspection/navigation bracket lasted
**8.3366181 seconds**. A separate descriptive trace review found the same first
request active with open admission before that full bracket and foreground
draining afterward. All 749 subsequent preseal hold rows had closed admission,
`foreground_activity` and no pending request: 25 draining, seven releasing and
717 parked. These descriptive checks do not substitute for the unexecuted
additive audit or qualify the combined scenario.

The actual parent joined with exit 1 after **1,143.609 seconds**, without timeout
or emergency termination. The observer joined with exit 2 after 1,116 valid
responses and three connection errors; its terminal-path observation was still
false at its own endpoint. Independent cleanup review confirmed the retained
worker, GUI, listener, transport and two native-release records, including
5 + 9 descendant exits. A separate later availability observation found no
remaining test processes or listeners. Failure cleanup is not a normal user
Stop. The failed path did not retain the success-only final job enumeration or
all worker birth-identity rows; the review preserves those limits.

Independent terminal review confirmed the inventory oracle, three cumulative
provider calls (one before continuation and two afterward), one physical write,
the exact grant diagnosis and the failed overall outcome. It passed 322
evidence-consistency checks across 110 input pins; these are review checks, not
additional model trials. Receipt SHA-256:
`50d8839ae7c219ab350236146146162df9c5008521c4fd4ff57bbe9c7797667f`.
The separate cleanup-review receipt is
`e7098f6b85bb19b084deef13a50d709e040f2335e61ae16d02bb0d19cd2046a9`.
These hashes identify retained private evidence, not a public reproduction pass.

### CI diagnostics and isolated HTTP fixture validation

At documentation head `938a9a123c2b9ad3991a8863856650e601798cf4`, the
[PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41040556106)
passed all seven jobs; the [push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41040549390)
passed six and cancelled Windows/Python 3.11 at its cumulative 15-minute limit.
Both checkouts have tree `104a22c0dc9859172530e269d4aa586749935239`. The successful
Windows counterpart passed 1,258 core tests in 508.419 seconds and all remaining
checks. Cancellation interrupted AST copying during lineage verification, which
identifies the interruption location, not the cause of the accumulated delay.
Together with the preceding timeout at a different test, this warrants a bounded
duration investigation. It remains 13 successful checks and one cancellation,
with no runtime regression or infrastructure-only cause established by these
documentation changes.

At documentation head `d3bc4032753cf52db78a6ead6c5c0fa8d25e5e87`, the
[PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41046301890)
and [push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41046296284)
finished with **12 successful jobs and two cancellations**, both at the cumulative
15-minute limit. The push Windows/Python 3.11 job passed 1,258 core tests in
809.063 seconds before a later cancellation. The PR Windows/Python 3.12 job
logged `ERROR` for `test_clock_crosses_after_admitted_before_begin`; no final
traceback was retained in its log or inspected diagnostic artifact. That error
remains unexplained. The opposite-event counterparts passed, including 1,258
core tests in 426.573 seconds on Windows/Python 3.12. Both checkouts have tree
`0a86b0f12a487b04f5800ae48248203f4e684263`.

One focused local Python 3.12 control of that exact test passed in 0.354 seconds:
safe expiry preserved pending work with no second begin or transport call. It
uses a scripted SDK and actual worker/recovery control flow, not a model run.
This pass does not diagnose the hosted error or establish that all CI passed.

The subsequent workflow change adds only standard unittest `--failfast` to core
discovery. Passing runs retain the same collection and assertions. Failed runs
stop after the first failure/error; tests not reached must be recorded as not
executed. The matrix's `fail-fast: false`, timeout and always-run diagnostic upload remain
unchanged. CPython reports stored tracebacks after the current test and cleanup
return, so blocked cleanup or job termination can still prevent a report.
This is a diagnostic change, not a runtime correction or duration improvement.
See [Python 3.11](https://docs.python.org/3.11/library/unittest.html#command-line-options),
[Python 3.12](https://docs.python.org/3.12/library/unittest.html#command-line-options)
and the pinned [CPython runner](https://github.com/python/cpython/blob/v3.12.10/Lib/unittest/runner.py#L235).

At diagnostic-change head `39d2d90b291603113c3dd6b017681ca8367a8872`, the
[push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41050044491)
and [PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41050053294)
finished with **13 successful checks, one failure and no cancellations**. All
four Windows jobs passed. Both checkouts have tree
`3a5cb999528892c84a910c332cf093a6bf7e9e60`. The failed
[push macOS/Python 3.11 job](https://github.com/midhatn/adaptive-inference/actions/runs/41050044491/job/124043555978)
reported `AssertionError: unexpectedly None` in the disconnect/EOF test: its
owner snapshot was already None before the client response was closed. Fail-fast
preserved the traceback and exit 1 after 907 tests in 80.571 seconds, including
35 skips; remaining core tests were not executed and later steps were skipped.
The [matching PR job](https://github.com/midhatn/adaptive-inference/actions/runs/41050053294/job/124043585767)
passed that test; its core suite reported 1,258 tests in 146.390 seconds with
36 skips. This observed
diagnostic result does not explain the earlier `d3bc403` error or resolve
cumulative CI duration variability.

The subsequent [fixture-only correction](../tests/test_immediate_admission.py)
gives this deliberately event-held stream a separate bounded five-second read
timeout, asserts a non-None owner before closing, and releases its finish event
in `finally`. Ownership and post-EOF checks remain. Every other fixture test
keeps 50 milliseconds; the dedicated timeout method is unchanged. The
[Python Event contract](https://docs.python.org/3.11/library/asyncio-sync.html#asyncio.Event),
[aiohttp read-timeout contract](https://github.com/aio-libs/aiohttp/blob/v3.14.5/docs/client_reference.rst#L2235)
and [timer implementation](https://github.com/aio-libs/aiohttp/blob/v3.14.5/aiohttp/client_proto.py#L287)
support separating these scenarios. A competing 50-millisecond timeout remains
a hypothesis about the failed hosted execution; its gateway history was not
retained.

The two affected tests passed once each on local Python 3.11.9 with pinned
aiohttp 3.14.5 (0.684 seconds), and Python 3.12.9 with installed aiohttp 3.11.13
(0.655 seconds). The latter is an older-dependency compatibility control, not
dependency-equivalent CI validation. Test-file blob
`6235532acc1ac06209c75f733dbb7dc7d2f99e87` binds this correction. Actual session
timeouts were five seconds and 50 milliseconds respectively; timeout cases
still returned 502 with uncertain completion, no retry proof and one backend
call. Lifecycle checks observed the same owner before and after client close,
then one completion after explicit EOF without uncertainty. Their histories
recorded `client_disconnected=false`:
closing the client and yielding once does not prove that the server observed a
TCP disconnect. No runtime code, installed dependency or model was changed.
Fresh exact-head hosted CI remains a separate gate for this fixture correction.

At fixture-correction head `aec8d9070f1509268e7d9b3e9944c14c3f374e75`, the
[PR workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41054525936)
passed all seven jobs. The [push workflow](https://github.com/midhatn/adaptive-inference/actions/runs/41054518769)
passed five and cancelled both Windows jobs at the cumulative 15-minute limit:
**12 successes and two cancellations**. Both tested trees are
`9b1e2c51645f7b54dbe629f9e876e93f28e4fd8a`. Both affected HTTP tests logged `ok`
in all 12 portable jobs. The push Windows/Python 3.12 job completed 1,258 core
tests in 752.991 seconds with one supported-interpreter skip and individually
completed its later validation/build steps; its overall result nevertheless
remains cancelled. Push Windows/Python 3.11 has no completed core summary: it
was interrupted during a SQLite commit in task creation. That location does
not identify the cause of cumulative delay. The passing PR Windows counterparts
completed 1,258 tests in 674.558 and 680.898 seconds respectively. This validates
the fixture correction within those bounds; it does not qualify the separately
developed activity bridge or explain earlier unresolved failures.

## Explicit continuation after safe expiry

The [source-bound continuation record](../provenance/explicit-continuation/acceptance/README.md)
and [public result](../provenance/explicit-continuation/acceptance/result.json)
cover one installed Windows/Hermes/Strata IQ3_S task on 26 October 2026. One real
Resume and Pause led to safe expiry of the first 900-second execution. One
Continue in the same window granted another 900 seconds and requested Resume
through fresh acknowledgements. The original objective completed before the
successor budget ended; one Stop produced normal owned cleanup. No Retry was
used.

The three cumulative model requests are two before Continue and one after it.
The sealed predecessor and its history stayed immutable. The report remained
four rows, 17 units and 4,350 cents, with one physical file write. Model, context,
quality and the shared eight-request ceiling remained unchanged. The independent
terminal audit passed **70 checks**, binding **214 private inputs**, including
actual task/native history, request/effect files, UI observations, both retained
worker exits and native/window/control cleanup.

The qualified wheel SHA-256 is
`02010db139127855e4ec5a5542e1bda3c5f7dde12ea650fe9235181cef83ce66`,
with 57 runtime modules from source freeze
`73fbec145f95a7f97b60ba51dd8cbe737b3124b37c442417ac4acc69effe8906`.
The acceptance record binds source, package and actual installation gates.
Later documentation and evidence additions form a separate publication overlay;
they do not change the identity of that qualification wheel.

The external observer retained 1,147 valid status responses in 1,150 samples and
exited with code 1 after three connection errors following Stop. Its samples
establish observed service availability before and after Continue. They do not
establish cleanup or task completion; those follow from retained process/resource
proofs. UI times are operation brackets, not exact click timestamps or latency
measurements.

The final host component separately passed 295 supplied checks plus one
independent receipt-integrity case, and its qualification harness passed 37
synthetic/source-equivalence checks. Public export tests and custodian replay
are described in the acceptance record; they remain distinct from the actual
model trial. Earlier failed development and expiry evidence remains preserved.
This result does not complete M2, establish physical reboot recovery, qualify
arbitrary tasks/engines or broader foreground activity, or claim a performance
or precision improvement.

## Safe expiry of a paused task

The [paused-expiry acceptance record](../provenance/paused-budget-expiry/acceptance/README.md)
binds the corrected installed Windows/Strata/Hermes composition to one complete
IQ3_S trial. Two model requests produced one correct report write with no
validation rejections. One genuine Resume and one genuine Pause preceded the
original 900-second deadline. The verified Pause was observed 654.325 seconds
before that deadline; the execution seal followed the deadline by 0.174 seconds.
The saved report and native history remained unchanged, and the task stayed
pending and paused rather than being marked complete.

The same window displayed the saved-progress expiry message and kept Stop
available. There were 55 complete status-request intervals after verified expiry
and before the Stop timing bracket. One genuine Stop was followed by normal
runner, worker, GUI, listener and owned-native cleanup. The independent terminal
audit passed 46 checks. These observations establish availability in that interval,
not UI or network latency performance. The observer's three connection errors
after service closure remain inconclusive for cleanup; retained process and
resource evidence establishes cleanup separately.

The correction passed 104 focused checks on Python 3.11 and 3.12. Independent
review passed those 104 plus one worker-cleanup regression. The public
[Hermes dispatcher example](../examples/validation/hermes_pause_dispatch/README.md)
passed three cases through the pinned SDK, including the installed wheel on the
actual Python 3.14 worker. Those dispatcher checks use a reduced native-history
fixture and are separate from the live model trial. The failed clock-domain and
constructor-thread trials remain failed and preserved in the acceptance record.

This result does not qualify active or uncertain-work expiry, automatic budget
renewal, another task in the same host, broad foreground workloads, physical
reboot recovery or the complete M2 milestone.

## Installed Windows desktop composition

The [installed cold01/full01 receipt](../provenance/installed-desktop/acceptance/README.md)
binds one regular installed wheel and explicit Windows deployment to two
independently accepted cases. Cold Pause/Stop produced no model calls, native
launches or file effects and retained the unfinished paused task. The full case
made three actual IQ3_S requests, wrote the correct 4-row/17-unit/4,350-cent report
once, preserved its context across a safe retained-worker replacement, then
joined its worker, GUI, control connections and native owners normally. The
independent terminal audits passed 35 and 47 checks respectively.

The tested source passed 985 required software checks; its focused 348 product,
GUI and qualification cases are included in that total. An independent regular
wheel installation repeated those 348 cases outside the checkout. Twenty later
evidence-selection tests verify the new public receipt's refusal/privacy rules;
they are not additional live-model validation.

The full GUI's first Stop click did not register; the second produced normal
shutdown. This limitation remains explicit. Cold minimize/restore reused the
same window, without testing destroyed-window reopening or a physical reboot.
Both full readiness observations had GUI CPU below 0.05 cores, so this installed
case does not itself demonstrate the new policy's distinction above the old
threshold. The report had zero validator rejections and supplies no real-model
correction evidence. That historical build does not qualify pending-task expiry;
the later paused-expiry result above has its own source and evidence.
Pressure/foreign-foreground trials, arbitrary tasks and daily-use always-on
completion remain separate work.

## Persistent-controller portable components

The optional demand-aware handoff and runtime timing components, combined with
the corrected task store, passed **263 core software tests** on Windows/Python
3.11 in 28.733 seconds. The new coverage includes 23 demand-controller tests and
19 timing fixtures plus four independent timing probes. Native acknowledgements
and model replies are simulated in these cases; the timing tests exercise the
actual gateway, scheduler and local HTTP code.

The [controller contract](persistent-controller.md) separates restoration,
dispatch and idle release. The [timing contract](runtime-timing.md) retains the
existing learner per verified runtime and captures it at dispatch. Both are
opt-in; neither result is a latency improvement, a new model qualification or
completion of M2. Exact reviewed inputs and the accepted historical runtime are
[preserved locally](../provenance/persistent-desktop/README.md).

## Task-store verification correction

The [verification correction](task-store-verification.md) passed **217 core
software tests** on Windows/Python 3.11 in 23.991 seconds. This includes 17 new
SQLite/OS-lock regressions and four independent probes, each discovered once.
Independent review of the frozen component repeated its 75-test suite and all
four additional probes; runtime promotion is byte-exact. The
[source record](../provenance/task-store-verification/README.md) preserves its
earlier fixture failures and exact predecessors. The original unexplained
composed Windows failure is not attributed to this correction without proof.

These results cover storage behavior and existing portable contracts. They do
not qualify the new store inside a live persistent Hermes/controller workflow.
Linux/macOS validation is separately recorded by exact-head CI. Older readers
must be stopped and joined before upgrade; mixed-version access is unsupported.

## Complete foreground handoff and Hermes worker restart

The [controlled-11 receipt and reproduction guide](../provenance/windows-handoff/controlled-11/README.md) record one complete accepted workflow on Windows with the existing IQ3_S model, pinned Strata owner and installed Hermes SDK. Both arithmetic tasks passed independent integer checks on their first attempts. Real foreground interaction caused admission closure and verified backend release, a declared NVENC tool produced and decoded 90 frames, and the same model configuration was restored. Hermes preserved its accepted report and native history across a safe worker restart, then finished the original task without repeating the report write.

The two 45-second animation phases had full observed foreground coverage and p95 paint intervals of **17.4944 ms** and **18.6084 ms**, within the predeclared 25-ms budget. This measures GDI paint submission and host-message scheduling, not physical display or input latency. The earlier baseline and uncontrolled runs are historical numerical references with different native/runtime revisions. No causal performance improvement is established.

The final independent export validates the complete ordered transition history, no controller fault, closed admission, no active or pending request, no uncertain completion and confirmed owned-process cleanup. It retains the preceding run's recorded pass as **unaccepted** because that run ended with a controller fault and an incomplete pre-close ledger. Failed startup, missing interaction, wrong arithmetic and queued-provider watchdog outcomes remain identified separately; none contributes missing acceptance evidence to the successful run.

The agent's 780 durable wait observations span **81.375 seconds** during release and restoration following foreground demand. They begin 1.828 seconds after the second animation window ends; none overlaps that visible window. The first handoff independently confirms native release inside the first animation window, 7.375 seconds after its active response completes. The recorded sequence establishes safe waiting and continuation, not 81 seconds of simultaneous visible foreground work.

This establishes one bounded native composition and one same-boot installed-agent restart. It does not qualify a persistent service, physical reboot or power loss, arbitrary tools, games, video playback, other native engines, or real-model correction after a rejected answer. The receipt records actual wait durations; passing this run does not demonstrate waiting longer than the old 180-second watchdog. Model assets are metadata-bound, not fully content-hashed. The [source-bound receipt](../provenance/windows-handoff/controlled-11/result.json) is authoritative for exact fields and limits.

## Real Hermes file task on IQ3_S

The [sanitized receipt and three task artifacts](../provenance/hermes-iq3-s/README.md) record one accepted Windows task using the existing IQ3_S model, exact Hermes commit `14e1e43a23761b369641208e204365cd6cb9399d`, the canonical optional routing plugin and the released v0.2.0 gateway wheel. The parent read a four-row synthetic CSV and wrote a report. A host-created production child independently read the CSV and report, checked the arithmetic and wrote a verification. Independent acceptance recomputed **4 rows, 17 units and 4,350 cents**, including every per-item total.

All **six actual model requests** (three normal, three background) and **five native file operations** completed successfully. Public hooks supplied child classification; the prompt and harness did not inject a class. Both agents retained context 65,536, output allowance/reserve 10,923, high reasoning with 8,192 reasoning tokens, disabled speed projection and the declared PCIe fraction 0.37. Actual serialized requests and gateway history matched. Both phases stopped naturally. The task took 208.627 seconds; this is one observed duration, not a comparative performance result.

The task's owned child-process job was empty. The gateway ended with six completed requests, no active/pending work and no uncertain completion, then closed cleanly. The separate backend owner confirmed all seven retained process identities exited, with server exit code zero; both listening ports were absent afterward. Sampled minimum physical RAM was 10.870 GiB, commit headroom 32.602 GiB and VRAM 1,103.285 MiB. Sampling does not establish a continuous guarantee. Native source and model metadata were checked; the model weights were not fully content-hashed.

The [parameterized Windows reproduction runner](../examples/validation/hermes_tool_task/README.md) is a subsequent refactor. Its separate receipt covers twelve CPU boundary tests and six synthetic responses through the actual pinned Hermes SDK, including five native file operations. It has not been rerun against a model after parameterization. The original real receipt remains bound to the original runner hashes. No alternative inference model was used. Logs, assistant reasoning and private host records are excluded from the public export.

This proves a bounded serial file-tool workflow for this composition. The host chose the child, so it is not autonomous-delegation evidence. It does not establish foreground/game responsiveness, resource-lease handoff, idle-model reload, operating-system reboot recovery or every matrix target's native behavior.

## Generalized client and host integrations

The generalized-integration revision passed **110 core software tests**, **17 preservation checks** and **12 task-boundary checks** locally. The current handoff revision separately passes **174 core**, **64 native-owner/host**, **20 harness**, **11 foreground**, **17 preservation** and **12 task-boundary** tests locally. The source-bound SDK receipts below exercise real installed libraries or pinned original host code with simulated responses; none invokes an inference model.

| Check | Evidence and scope |
| --- | --- |
| LangGraph, CrewAI and retained AutoGen | [15 successful HTTP requests plus 6 refused overrides](../provenance/python-clients/README.md): normal/background text, streaming and strict tool-schema transport; selected model and separate gateway credentials preserved |
| Hermes public-hook plugin | [Pinned SDK tests](../integrations/hermes-plugin-tests/README.md): 41 current-SDK tests; 40 older-SDK passes and one explicitly unavailable cron-hook skip; separate admission checks |
| OpenClaw configuration | [Composer and exact host schema](../examples/agents/openclaw-config.md): supplied model, credential and fallback settings retained; schema evidence is not a full application run |
| Aider, Continue and Cline | [Preserved client transports](../provenance/client-config-transports/README.md): 2 Aider and 4 current plus 4 published JavaScript transport cases; Cline's missing reasoning-budget forwarding remains an explicit limitation |
| OpenHands | [26 configuration/transport cases](../integrations/openhands/README.md), including two actual released-gateway compositions with a fake backend; use the documented `litellm_proxy/` selector to preserve the declared request options |
| SGLang and Ollama | [6 client/gateway fixture cases](../integrations/openai-admission/README.md): executable shared admission guides, request/stream preservation and clear native-server limits |
| LM Studio | [SDK constructor regression](../provenance/lmstudio-baseurl/README.md): `baseUrl` fails type checking and leaves the default remote URL; `baseURL` selects the intended local endpoint, with no socket connections |

Independent review reproduced a real defect in the three Python factories: nested `extra_body.model` and authorization headers could override the selected identity. The shared option validator now refuses those before constructing/sending a client request, while preserving ordinary generation options, tool schemas and tracing. The six negative SDK checks attempted zero dispatches; all fifteen normal SDK cases still passed. Source hashes identify the corrected factories and validator.

The [upstream delivery ledger](upstream-delivery.md) records published proposal heads and outstanding contribution requirements. A submitted PR is not an accepted integration. Fixture coverage is not native qualification of SGLang, vLLM, Ollama, Apple hardware or any other unexecuted backend.

## Portable gateway release acceptance

At commit `e1d14978328d61267dcbda6fbaa55cdc882f3394`, all **45 gateway/profile/CLI tests plus 4 reconstruction-admission tests** passed in each of six GitHub CI jobs: Windows, Linux and macOS, with Python 3.11 and 3.12. Every job also ran the local HTTP demo, listed the eight engine profiles and built wheel/source distributions. [CI run and artifacts](https://github.com/midhatn/adaptive-inference/actions/runs/40038431587).

A separate fresh, non-editable wheel installation outside the checkout passed the installed `profiles`, `demo` and `doctor` commands on Windows. Its eleven Python module files matched the source, required license notices were included, and the source distribution included the reconstruction helpers. The demo's backend is simulated; the HTTP transport, queue and feedback paths are real. The demo proves equal-cost normal/background ordering and one rejected result followed by a caller-validated correction.

The same gateway source then completed **eight real Strata model requests**: four normal and four background. Full returned text was checked against the exact integer answer (`437` or `493`), all requests stopped naturally, and each class's fourth request used three earlier execution observations. The gateway ended with zero active/pending requests and no uncertain-completion state. The separately operated backend owner confirmed all six retained processes exited with server exit code zero. Exact source/model/settings, per-request timing, answers and counters are in the [sanitized receipt](../provenance/gateway-strata-2026-10-24.json); the [runnable check](../examples/validation/README.md) is included.

This is serial arithmetic and feedback engagement on one Windows/Strata composition. It does not establish comparative speed, prediction accuracy, installed-agent tasks, native priority or tool leases. Gateway scheduling metadata is consumed at the gateway; both classes share its queue. The backend owner remains separately operated predecessor software.

### Retained failure: idle backend reload

The first gateway attempt timed out before any model answer. Strata had unloaded after 60 seconds of idle time. A subsequent status observation reported `reload_footprint_unavailable`: the recorded requirement was 55,901,364,224 bytes free physical RAM, versus 50,850,979,840 available. The nonstreaming reload-admission path can wait without sending HTTP bytes until the gateway's 120-second read timeout. Direct no-model HTTP probes and request framing checks succeeded. This diagnosis combines observed backend state and code inspection; the original waiting thread's stack was not captured.

The accepted run started immediately after a fresh owned backend startup. It qualifies the ready-backend path, **not idle unload/reload recovery**. The gateway and old backend sources were unchanged between attempts. No generation was automatically retried; the operator restarted after inspecting the backend. Native lifecycle/admission coordination remains a tracked development stage in [PLAN.md](../PLAN.md).

## Portable resource/context additions

The post-v0.1.0 source adds the optional sustained-headroom admission policy and explicit context-budget planner. On Windows/Python 3.11, **75 software tests and 4 reconstruction-admission tests passed**, and wheel/source distributions built successfully. The [source-bound acceptance receipt](../provenance/portable-policies-acceptance.json) identifies the tested runtime and test files. This run includes the earlier 45 software tests; the 75 is a total, not 75 additional tests.

New checks exercise fresh/replayed/stale/invalid observations, pressure and recovery, idle sampling, unchanged HTTP request fields, active-owner preservation, cleanup, exact moving-margin compaction targets and CLI exit codes. A fault-injection review found that an already-failed sampler could prevent HTTP-client cleanup; the connection pool now closes in a `finally` block and the regression passes. The software checks use simulated headroom and loopback HTTP fixtures, not new GPU/model or foreground-interference measurements.

Source review also ran the pinned upstream policy and context-budget fixtures for the reused mechanisms. Source extraction setup failures were resolved by restoring exact dependency bytes. These checks do not qualify installed Strata companions, a real compiler/video handoff or the complete [always-on goal](always-on-controller.md).

## Durable task continuation

At `734fbe7`, the durable task store and resumable feedback runner passed **95 software tests in total**, plus the existing four reconstruction checks, across Windows, Linux and macOS on Python 3.11 and 3.12. [CI run](https://github.com/midhatn/adaptive-inference/actions/runs/40043584632). Every job also ran the demo and built wheel/source distributions. Twenty of the software tests cover task-store ownership, checkpoint transitions, the persistent feedback runner and its process-restart demonstration. An independent focused review reran the 18 store/runner tests successfully and found no blocking defect within the documented local-store contract.

The [sanitized restart receipt](../provenance/restart-survival-2026-10-24.json) binds the tested source hashes to a real process-termination exercise. A new worker retained the original task and rejected feedback, produced the accepted inventory total of 42 on the second attempt, and reopening the completed task invoked no callbacks. A competing live owner was refused. A separate worker died after one external delivery but before its acknowledgment; two fresh resumes stopped for reconciliation and did not repeat the delivery. All seven workers exited. Separate tests recovered an uncommitted SQLite rollback journal without accepting its interrupted changes.

The generation and tool callbacks are deterministic fixtures. This is process/disk-state evidence, not an installed-agent, operating-system reboot, physical power-loss or distributed exactly-once guarantee. The [host integration contract](task-survival.md) explains the remaining startup, identity and reconciliation work.

## Fresh source reconstruction

### Standalone source preservation in v0.2.0

The [offline reconstruction receipt](../provenance/offline-source-2026-10-24.json) records restoration from the bundled sources on Windows/Python 3.11.9. The gate disabled Git transports and Python socket access; its positive control confirmed that an HTTPS Git request was refused before networking. Restoration issued no fetch/clone commands and attempted no Python sockets.

The verifier checked every resulting tracked file and complete final tree: **4,785 Strata files, 3,608 llama.cpp files and 16,784 Hermes files**, totaling **25,177**. The preserved original baseline commits, source inventories, overlay hashes and expected final trees matched. Fifteen preservation/restore/guard tests passed, including corrupted or incomplete input refusal, raw bytes and file modes, original commit identity, existing-output preservation and repeatable bundle creation.

The [reference verifier](../third_party/reference-sources/verify.py) independently checks 13 original source/license/notice files in five groups. The [distribution check](../provenance/check_distribution.py) verifies that complete source archives include the current source, local bundles, manifests and notices, while runtime wheels contain the matching modules/licenses. CI runs these gates alongside the portable tests. No preserved upstream code, model or compiler is executed by the source restoration test.

Testing the built source archive in a deeper Windows directory exposed Git's default path-length limit during index refresh, despite intact source bytes. Restoration and independent verification now explicitly enable Git's long-path support. A real-Git regression restores a path longer than 260 characters and confirms the failure with that option disabled on Windows. The preservation suite now contains 16 checks; the earlier short-path receipt above remains unchanged.

Current development adds a seventeenth preservation check for exact receipt-bound fixture bytes, and a separate [current Hermes snapshot](../integrations/hermes/current-source/README.md). That snapshot restores all **20,897 tracked files** at the plugin/task SDK revision from the preserved baseline plus a checked 47,850,166-byte delta. Windows restoration passed with exact commit/tree identity and a clean checkout, while network-denial positive controls, existing-output refusal and missing-baseline refusal passed. It is separate from the original 25,177-file restoration and does not replace that baseline. CI also runs this additional restoration with network access denied.

### Earlier network-assisted reconstruction

On 24 October 2026, the included setup scripts fetched the pinned public GitHub commits into new empty locations and applied their checked overlays. All 88 expected Strata changed files and all 7 Hermes changed files matched SHA-256 hashes of the intended canonical Git content. Expected reconstructed trees and patch hashes are in [provenance/reconstruction.json](../provenance/reconstruction.json).

The reconstructed Strata source passed 54 CPU tests covering queue ordering, bounded cost estimation, real service/HTTP integration with fake engines, route delivery, preparation reservations and parking/seed feedback. The reconstructed Hermes source passed its 2 request-intent test methods, which exercise the canonical request-builder matrix. Four reconstruction admission tests passed: existing destination preservation, corrupt-patch refusal, fixed remote identity and path traversal refusal. These checks used Windows/Python 3.11.9 for Strata/setup and Python 3.14.7 for Hermes. They ran no model or new native build.

Reproduce these checks with the commands in each [integration README](../integrations). Test fixture throughput is not an inference benchmark. The hash-locked sources and scripts are public; dependencies and hardware remain separate prerequisites.

## Historical local prototype results

These are operator-observed, bounded results retained from the earlier workstation prototype. Raw runs include private machine state and are not redistributed. Public sanitized source and summaries permit code review and new reproduction, but the following numbers are not independently certified by the existence of this repository.

| Check | Observed result | Boundary |
| --- | --- | --- |
| Native Windows CUDA build at a69684f1 | 183 build steps; thirteen utility/protocol programs passed; all 1,638 retained process identities exited | CUDA 13.4 / MSVC 14.44, architecture 89; live-memory test used protocol-only mode, no model; not HIP/SYCL/Metal qualification |
| Mixed pending-request model check at 9eff | Active owner completed, then normal, then background; canceled pending request produced no generation; all 6 retained handles exited | Three short full-quality arithmetic requests; no throughput or task-quality improvement claim |
| Actual Hermes parent/production-child check | Two real production request-builder paths completed at declared quality; normal/background host intent reached the native service; all 14 retained handles exited | Sequential requests, explicit constructor budget; no leased-tool execution |
| Standalone core at c6b + exact Windows process-rights overlay | 8/8 arithmetic responses correct and naturally completed; eight timing observations; each class's fourth request used three earlier observations; all 8 retained handles exited, server exit0 | Persistent legacy Windows owner; not the new generic gateway; no comparative speed or prediction-accuracy claim |

The standalone check used the native binary SHA-256 `744205e4e024b5cbba19e4b560678ffe21e6899e59050929f7af51557f3c6198`, manifest `19a85d390981380b3ceeb021a885b25f415110174cedfb3dcdc0552cd0ab052b`, and a 23.9375 GiB startup cache selected from 41.956 GiB free effective RAM/commit. Minimum sampled headroom was 11.116 GiB physical RAM, 31.656 GiB commit and 1147.285 MiB VRAM. Sampling is not a continuous residency guarantee. The model/pack contents were metadata-bound, not fully content-hashed.

The quality baseline was IQ3_S/context 65,536, 10,923 total output cap, 8,192 reasoning tokens/high, CPU vision enabled, MTP/projection off. The arithmetic calls did not exercise vision. These figures establish functional execution and feedback engagement for that workload, not general reasoning quality, automatic hardware tuning or optimal scheduling.

## Failures retained and corrected

- Initial persistent startup omitted the server's required owner attestation and failed before model dispatch. The owner was corrected to bind a fresh private key to exact configuration and arguments; an actual mock-server parser/drain regression was added.
- The first timing-feedback attempt remained cold on its second equivalent request: parking injected a new seed between prediction and observation. c6b removes seed only from the copied latency identity, preserving native seeds/replay and all quality/runtime/route distinctions. The unchanged eight-request fixture subsequently passed.
- A fixed 42 GiB owner threshold refused startup at 41.594 GiB free RAM. The owner was corrected to reuse the existing cache policy before eager loading, preserving startup allowance and headroom. It then started with a smaller cache; the emergency guards were unchanged.

The c6b correction collected 225 CPU tests: 224 passed and one POSIX-only test was skipped on Windows; the final legacy owner's 17 CPU tests passed. These historical counts are distinct from the freshly reconstructed 54 + 2 + 4 checks above. Prior unsuccessful receipts were retained locally, not relabeled as successful runs.

## What is not established

No comparative latency/throughput win, broad task-quality improvement, arbitrary-tool recovery, visual browser interaction, GPU kernel preemption or general autonomous operation is claimed. The bounded native handoff above qualifies only its declared GPU tool and agent task. Exact reconstruction does not make a fresh native binary bit-identical across toolchains. The upstream branches and this standalone gateway are separate deliverables; review the tested revision and composition for each claim.
