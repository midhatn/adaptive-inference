# Qualify foreground waiting, Continue and a second task

This is the reusable source workflow for the accepted Windows/IQ3_S inventory
and welcome scenario. It uses the ordinary installed desktop controller and its
real controls. The first task reads its input, yields to genuine foreground
work, safely expires, and continues the original objective. A separate task then
completes in the retained service before one normal Stop.

The [accepted evidence package](../../../provenance/task-handover/acceptance/README.md)
replays one historical result. This directory runs a **fresh qualification**
with new evidence and real observations. Its public path adaptation has focused
source/fixture checks, not an additional model trial. Ordinary users should use
the [installed reference workflow](../../../docs/reference-workflow.md); these
qualification receipts are not a normal chat workflow.

## Prerequisites and local inputs

Use a complete repository checkout and an already qualified Windows installation
with the exact 60-module runtime, full host/worker interpreters, pinned Hermes
SDK, owned native engine, IQ3_S assets and model/quality/context contract in
`checks.py`. `-I` imports the package from the installation, not this checkout.
The profile uses the declared loopback service at port 18100. Do not share that
owned service/model with another experiment.

The existing [installation guide](../../../docs/installed-desktop.md) and
[package verification instructions](../../../docs/reproducing.md) explain the
profile and package identity. They do not by themselves generate all current
deployment receipts listed below. This example therefore requires those actual
retained prerequisites; it is not yet a turnkey fresh-machine installer. Missing
receipts cannot be replaced with manually invented successful values.

Copy `bindings.template.private.json` to an external local directory as
`bindings.disabled.private.json`. Fill its `case` with a fresh absolute output
directory outside the source tree. Fill every descriptor with the real absolute
file path and SHA-256. `harness_manifest` must name this directory's
`source-manifest.json`. Keep `enabled` false in this declaration.

| Roles | Required actual inputs |
| --- | --- |
| `profile`, `wheel` | Reviewed local profile and the exact installed wheel; the profile identifies both full interpreters and native ownership. |
| `source_freeze`, `source_review`, `package_review` | Retained source inventory and successful source/build review for that wheel. Later publication documents are not part of the earlier tested build. |
| `deployment_gate` | Successful actual deployment gate for the same wheel, with its reviewed input hashes. |
| `host_install`, `worker_install`, `installed_identity` | Successful installation records and the matching 60-module package identity. |
| `clock_probe`, `installed_sdk` | Successful same-boot shared-QPC and installed-mode SDK receipts for this profile/package. |
| `inventory_spec`, `inventory_input` | Exact `examples/tasks/inventory/task.json` and `inputs/inventory.csv`. |
| `welcome_spec`, `welcome_input` | Exact `examples/tasks/welcome/task.json` and `inputs/brief.txt`. |

Verify the declared input bytes, source manifest, local ownership and current
resources before running. A prior successful gate does not reserve hardware.
The case, its sidecars and the two audit directories must be unused. The source
manifest's `enabled: false` identifies a fixed source declaration; it is not the
local run-activation flag.

After local preparation, create `bindings.enabled.private.json` **beside** the
disabled declaration, changing only `enabled` to true. Keep both files unchanged
through the audits. The helpers use this explicit declaration pair to identify
the new case; they do not discover another trial or infer missing inputs.

```powershell
$Workflow = (Resolve-Path ./examples/validation/task_handover).Path
$HostPython = 'C:\your-full-host-python\python.exe'
$Local = 'D:\your-local-qualification'
$Disabled = "$Local\bindings.disabled.private.json"
$Bindings = "$Local\bindings.enabled.private.json"
$Case = 'D:\your-local-qualification\fresh-case-01' # Same absolute path as the declaration.

# Exclusive creation; refuses an existing enabled file.
& $HostPython -I -B -c 'import json,sys; from pathlib import Path; value=json.loads(Path(sys.argv[1]).read_bytes()); assert value["enabled"] is False; value["enabled"]=True; Path(sys.argv[2]).open("x",encoding="utf-8").write(json.dumps(value,indent=2)+"\n")' $Disabled $Bindings
```

## Start and retain both processes

Run these in separate retained invocations, starting the observer just before
or alongside the parent. Keep their actual process handles and wait results:

```powershell
& $HostPython -I -B "$Workflow\observe_handover.py" --bindings $Bindings
& $HostPython -I -B "$Workflow\run_handover.py" --bindings $Bindings
```

The parent retains its qualifier and enforces the original 2,700-second outer
bound. Each execution has 900 seconds, including startup; selected readiness
has at most 240 seconds within that budget. Requests/attempts remain cumulative
at eight and admissions at 32. Do not extend deadlines, change model quality,
add Resume/Continue clicks, or retry into a consumed directory. Emergency
termination or another incomplete execution is a failed run.

The observer is GET-only and records an append-only sidecar. Read only complete
sidecar records with short-lived handles. Do not poll live SQLite or mutable
status files, introduce another HTTP poller, or infer cleanup from connection
errors. Retained terminal checks establish actual release.

## Genuine foreground and UI observations

Prepare genuinely useful reading or other document work, with enough unfinished
work for the qualification. Use the empty `foreground.template.private.json` to
record the real document's title/path, PID/window identity, preparation and each
observed action. Do not use dummy activity or repeated blind navigation. Stop
naturally if useful work is exhausted and retain the resulting qualification
limit. A document may be any actual suitable document; the original private
review corpus is not a prerequisite.

Sample the installed shared clock before and after actual actions and their
refreshed observations. Never mix interpreter-specific monotonic clock origins:

```powershell
& $HostPython -I -B -c 'import json; from datetime import datetime,timezone; from adaptive_inference.execution_clock import execution_now,CLOCK_ID; print(json.dumps({"deadline_clock":CLOCK_ID,"qpc":execution_now(),"utc":datetime.now(timezone.utc).isoformat()}))'
```

1. At `inventory_paused_ready_for_resume`, independently observe/correlate the
   real A window and its process. Save `pre-resume-ui.private.json` in `$Case`
   using `pre-resume-observation.template.private.json`. Then capture its raw
   host binding and startup context before Resume:

   ```powershell
   & $HostPython -I -B "$Workflow\capture_binding.py" --bindings $Bindings --observation "$Case\pre-resume-ui.private.json" | Out-Null
   # Continue only when the preceding command exited zero.
   & $HostPython -I -B "$Workflow\expiry_ready.py" context --bindings $Bindings
   ```

   Retain the actual returned context hash as `$ContextSha256`. Full bindings
   and 64-bit process creation values stay in Python JSON; never round-trip them
   through JavaScript numbers.

2. **Resume A once**, recording actual `$ResumeBefore`/`$ResumeAfter` QPC values
   and UTC brackets. Obtain the actual same-instance gateway ID from the observer
   as `$Instance`. Use the existing bounded cue:

   ```powershell
   & $HostPython -I -B "$Workflow\cue_status.py" --bindings $Bindings --instance $Instance --seconds 20
   ```

   A cue is not an acceptance result. Each read is bounded to 20 seconds; retain
   timeout/refusal honestly. Before the first useful foreground action, freshly
   observe the actual document. If activation is necessary, the **full** bracket
   starts before activation and ends after inspection, meaningful navigation and
   refresh. If already visible, bracket the meaningful action and refresh. Do
   not shorten the bracket after admission has closed.

3. Continue genuine work with contemporaneous before/action/after notes. The
   operating target is 30 seconds from the previous action's start. The strict
   gate is next action **end** minus previous action **start** less than 60
   seconds, including the seal-to-last-wholly-preseal-start tail. Postseal or
   straddling actions cannot cover gaps. Keep all delays and rejected actions.
   Do not intentionally wait for a target or automate synthetic input.

4. Near the original deadline, remain in the useful document while making the
   one-shot immutable expiry check:

   ```powershell
   & $HostPython -I -B "$Workflow\expiry_ready.py" check --bindings $Bindings --context-sha256 $ContextSha256 --resume-before $ResumeBefore --resume-after $ResumeAfter
   ```

   Exit 0/status ready exclusively records readiness. Exit 2 is not ready;
   exit 1 is refusal. Do not rerun after readiness is saved. Only after ready,
   switch to A, freshly observe the actual expired screen and save
   `expired-ui.private.json` before **Continue saved task once**. Never Resume A
   again. Existing Continue supplies its own Pause acknowledgement and derived
   Resume; the original task, read, history, quality and cumulative limits stay
   bound.

5. After the original inventory task is accepted, choose **New task once** with
   the bound welcome TaskSpec and input. Independently observe/correlate B and
   save `welcome-pre-resume-ui.private.json` before Resume B:

   ```powershell
   & $HostPython -I -B "$Workflow\record_ui.py" capture-b --bindings $Bindings
   ```

   After successful capture, **Resume B once**. After its existing format-only
   acceptance, use **Stop engine once** and wait for both retained invocations.
   Inventory has an exact 23-unit oracle; welcome is not a semantic-quality test.

## Record once and audit after joined shutdown

Save actual action counts/brackets as `ui-actions.private.json` from
`actions-only.template.private.json`. Keep `window_a`, `window_b`,
`expired_window` and `selected_source` null; the existing Python recorder copies
already observed immutable identities. Save the complete actual foreground
record as `foreground-observations.private.json`. Then:

```powershell
& $HostPython -I -B "$Workflow\record_ui.py" record --bindings $Bindings --with-b --with-expired --parent-joined --observer-joined
& $HostPython -I -B "$Workflow\audit_handover.py" --bindings $Bindings --output "$Case-audit-01" --parent-joined --observer-joined
# Only when the primary audit passed:
& $HostPython -I -B "$Workflow\audit_first_inflight.py" --bindings $Bindings --output "$Case-first-inflight-audit-01" --parent-joined --observer-joined
```

The join flags attest actual completed supervision. For an A-only failure omit
the recorder's `--with-b`; omit `--with-expired` too if no expired observation/
Continue occurred. Preserve absent/zero fields and the real failure. Never fill
observations retrospectively or overwrite partial outputs. Primary and additive
audit directories are exactly the case path plus the suffixes shown above.

Both audits must pass on the same run. One pass covers this declared cooperative
request-boundary workflow, build, model and environment. It does not establish
token preemption, reboot recovery, arbitrary tasks, gaming/media performance,
general exactly-once external effects or the whole always-on-agent goal.

## Source checks and reuse

```console
python -B -m unittest discover -s provenance -p test_task_handover_reproduction.py -v
```

These are source and synthetic local-binding checks. The
[source-preservation record](../../../provenance/task-handover/reproduction/README.md)
pins unchanged predicates and exactly reversible path adaptations. Existing
project source remains Apache-2.0; `LICENSE-Hermes.txt` retains the used Hermes
MIT attribution. The profile, private evidence and inference model are excluded.
The commands follow Python's [isolated execution contract](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I).
The complete source archive and runtime wheel are distinct artifacts under
PyPA's [source distribution](https://packaging.python.org/en/latest/specifications/source-distribution-format/)
and [wheel](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
specifications; their different validation scopes must remain explicit.
