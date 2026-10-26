# Installed explicit Continue qualification

This is the reusable source workflow for one Windows, same-window, IQ3_S
orders-report qualification. The [accepted evidence record](../../../provenance/explicit-continuation/acceptance/README.md)
belongs to the original independently audited private run. This public path
adaptation has source-equivalence and CPU-fixture validation; it has not been
rerun with a model. A fresh run produces new evidence and must be evaluated on
its own results.

For ordinary use, follow the [installed desktop guide](../../../docs/installed-desktop.md)
and use the real window's Continue control after a verified paused-budget
expiry. This qualification adds bounded observation and an audit. It is not
required to use the feature.

## Source and installation prerequisites

Use a complete repository checkout. `run_continue.py`, `qualify_continue.py`,
`observe_continue.py`, `audit_continue.py` and `checks.py` are byte-for-byte the
accepted workflow sources. Only `bindings.baseline` changes helper resolution:
it uses the existing seven-file public qualification predecessor and two exact
pure QPC predicates extracted from the earlier auditor. `source-lineage.json`
records original source hashes, the narrow fixture-path change and helper AST
identities. No accepted manifest is overwritten. Original bindings are retained
as a source-equivalence reference, not executed.

Install and verify the desktop package, full host Python/Tk, worker Python,
pinned Hermes SDK, owned native runtime and the exact IQ3_S model described in
the installed desktop guide. The interpreter must resolve `adaptive_inference`
from the installation under `-I`; this harness never adds `src` to its path.
Preserve the model and quality contract in `checks.py`. This workflow uses the
declared loopback gateway at port 18100 and does not discover or stop unrelated
services. Use a fresh output directory and an otherwise available declared
environment.

Copy `bindings.template.private.json` outside the source directory. Replace
each null descriptor with an explicit absolute `path` and its SHA-256; the
`harness_manifest` descriptor points to this directory's `source-manifest.json`.
Set `case` to a fresh absolute directory whose parent exists and which is
outside this source directory. Set `enabled` to true only after checking the
inputs. The unchanged `private.*` schema names indicate local evidence formats;
they do not refer to the original author's folders.

| Input role | Required evidence |
| --- | --- |
| `profile` | Validated local Windows orders profile with exact host/worker interpreter descriptors. |
| `wheel` | The actual installed wheel whose hash the deployment gate verifies. |
| `source_freeze`, `source_review`, `package_review` | Retained source inventory and review results for this local build. These are supplied evidence, never invented successful values. |
| `deployment_gate` | Actual successful local deployment review, same wheel hash, and an `input_sha256` map of exact reviewed files. |
| `host_install`, `worker_install` | Actual installation audit results with `passed: true`, the identical `package_identity` and actual `package_root`. |
| `installed_identity` | Exact `{version, files}` package identity used by both interpreters. |
| `installed_sdk` | Passing installed-mode dispatcher receipt for that same package identity. |
| `clock_probe` | Passing installed shared-QPC receipt with the same profile hash. |

These local installation/review records are prerequisites. The harness does
not fabricate them or replace deployment validation. Keep all paths named in a
deployment gate available through the final audit. The published fixed-evidence
exporter deliberately accepts only its original 19 role hashes; it cannot label
a new run as that historical accepted trial.

## Run and retain both processes

Run these in separate terminals using the exact full host interpreter from the
profile; start the observer just before or alongside the retained parent:

```powershell
& $HostPython -I -B ./examples/validation/explicit_continuation/observe_continue.py --bindings $BindingsFile
& $HostPython -I -B ./examples/validation/explicit_continuation/run_continue.py --bindings $BindingsFile
```

Retain and wait for both exact processes. The parent retains its qualifier
child and records its actual exit. The parent/qualifier have a 2,700-second
emergency bound, covering two 900-second execution budgets and cleanup; the
observer has a bounded observation loop. Emergency termination fails the run.
The successor retains the original eight-request cumulative limit and exact
IQ3_S quality. Completion may occur before the second budget expires.

The qualifier appends `qualification_phase` records to the case's
`events.private.jsonl`. A local supervisor may read complete records from this
append-only log with short-lived read handles; ignore a partial final line and
close the handle promptly. Its observation files are not control interfaces.
Do not tail mutable status/checkpoint files while the host is writing them;
use the genuine window for controls and record actual phase/clock observations.

1. Identify the retained Adaptive inference window and capture its actual
   window identity. After the paused bootstrap, click **Resume** once.
2. After `report_saved_ready_for_genuine_gui_pause`, click **Pause** once.
   Let the original 900-second deadline expire naturally.
3. After `expired_progress_saved_ready_for_continue`, observe the same window
   displaying its saved-work/budget-ended state with **Stop engine** available.
   Click **Continue saved task** once. Do not click Resume again.
4. Wait for `continued_task_accepted_ready_for_manual_stop` and verify that the
   same window displays **Task completed.**, with Stop still available.
5. Click **Stop engine** once and wait for both retained processes. Record any
   retry, early stop, timeout or failure honestly; do not edit it into the
   planned success sequence.

## Record real UI observations and audit after shutdown

Copy `ui-observations.template.json` to the case as
`ui-observations.private.json`. Fill it only from actual observations. Before
and after each click and saved/completed-state observation, sample the
installed shared clock and UTC using the profile's host interpreter:

```powershell
& $HostPython -I -B -c 'import json; from datetime import datetime,timezone; from adaptive_inference.execution_clock import execution_now,CLOCK_ID; print(json.dumps({"deadline_clock":CLOCK_ID,"qpc":execution_now(),"utc":datetime.now(timezone.utc).isoformat()}))'
```

Use the actual same-window handle and observed text, states and click counts.
These before/after readings are brackets, not exact click timestamps or latency
measurements. Do not substitute another interpreter's monotonic clock or derive
missing observations from the desired outcome. The template's null values
cannot pass the audit. A human or local UI supervisor must capture these
observations; this harness does not automate clicks or infer screen content.

After shutdown and actual completed waits for both retained processes, run:

```powershell
& $HostPython -I -B ./examples/validation/explicit_continuation/audit_continue.py --bindings $BindingsFile --output $FreshAuditDirectory --parent-joined --observer-joined
```

The flags attest completed supervision; they are not permission to skip it.
The auditor checks actual SQLite/native history, cumulative requests, the one
physical effect, source and installation bindings, UI chronology, retained
worker joins, authority/result identities and cleanup. It writes a new private
receipt. Connection errors in the GET-only observer establish no cleanup fact.
Keep the raw local inputs and failed outcomes; publish only an allowlisted
projection after independent review.

## Portable validation and limits

From the repository root:

```console
python -m unittest discover -s examples/validation/explicit_continuation -p "test_*.py" -v
python -m unittest discover -s provenance -p test_explicit_continuation_harness.py -v
```

The second command is the normal-discovery wrapper for the same tests, not an
additional independent test set. Source checks compare exact preserved bytes,
the one changed loader function, the one fixture path and the two unchanged
QPC function ASTs. The fixtures test audit predicates and refusal paths without
loading the model, SDK, native engine or GUI.

One successful run qualifies only this declared report task, build, model and
environment. It does not prove physical reboot recovery, automatic renewal,
arbitrary tasks, general exactly-once external effects, all Stop races, gaming
performance or the complete always-on-agent goal.

This adaptation reuses this repository's Apache-2.0 mechanisms and existing
source manifests. Its loading and test-discovery patterns follow the official
[Python 3.11 importlib example](https://docs.python.org/3.11/library/importlib.html#importing-a-source-file-directly)
and [unittest discovery contract](https://docs.python.org/3.11/library/unittest.html#test-discovery).
