# Installed Windows desktop composition

The `desktop` command connects the existing adaptive host, retained control
window, native owner and Hermes report worker from one installed package. It
starts paused. Resume is an actual authenticated user command; model loading
still requires fresh foreground/capacity observations and the existing recovery
dwell. Pause waits for a safe task boundary. Stop joins the retained worker,
window, pipes and native resources before reporting a clean shutdown.

The retained default profile runs the **orders-report task** with the existing
**IQ3_S** model. The current development source also accepts bounded
[user file tasks and same-host New task](task-spec.md), with a separate
[case17 installed result](evidence.md#case17-complete-foreground-continuation-and-two-task-handover).
It preserves context 65,536, output allowance 10,923, high reasoning with
an 8,192-token budget, the original report oracle and at most eight cumulative
model requests. Each execution has a 900-second budget. After verified safe
expiry, [Continue saved task](explicit-continuation.md) can explicitly authorize
a successor in the same window; it does not reset the request allowance. Rejected report proposals
use the existing feedback mechanism before a file effect. The file-task adapter
supports its declared read/write capabilities; it is not a general Hermes
service installer or computer-reboot recovery service. The ordinary task and
New task steps are in the task guide. The
[setup helper](../examples/desktop/README.md) generates the explicit profile and
Start launcher from already installed components. A fresh-machine installer
and broader daily-use qualification remain later deliveries.

The product code reuses the previously qualified composition. A source promotion
or fixture pass does not transfer real-process acceptance to a new installation.
Run the installed cold/full qualification before claiming that deployment works.
The exact source and permitted promotion changes are retained in
[provenance/installed-desktop](../provenance/installed-desktop/README.md).

One such installation has now passed its separate cold and full qualification:
actual GUI Pause/Stop without model loading, followed by three real IQ3_S
requests, one correct report write and a retained Hermes worker replacement.
The [source-bound acceptance record](../provenance/installed-desktop/acceptance/README.md)
contains 35 cold and 47 full independent checks and the exact wheel/profile.
That version's full trial recorded a missed first Stop click; a second click
produced normal shutdown. The [retained-command successor](desktop-control-intent.md)
resolves the reproduced status-polling gap and has its own
[installed acceptance](../provenance/desktop-control-intent/acceptance/README.md):
38 cold and 50 full independent checks, including one click for each Resume and
one Stop after task completion. Deterministic tests establish the deliberate
poll-overlap ordering; the live clicks establish their observed GUI outcomes.
This bounded result does not qualify reboot recovery, pending-task expiry or
every agent/engine. New installations must run their own qualification.

## Required installation

The first supported host/GUI layout is a **full Windows CPython 3.11.9
installation with Tcl/Tk**. Install the regular wheel into that interpreter;
do not use an editable checkout for this command. The host and GUI use the same
configured interpreter. The Hermes worker also uses its explicit full/base
interpreter with the same regular wheel installed, plus the separately specified
Hermes SDK and dependency directory. No system service or package installation
occurs merely from reading the profile or importing the library.

Windows venv `Scripts/python.exe` can start a different base-Python process and
wait for it. Its retained launcher PID is then not the GUI window's PID. The
existing process/window ownership checks intentionally reject that mismatch.
This follows the pinned [CPython 3.11.9 launcher implementation](https://github.com/python/cpython/blob/v3.11.9/PC/launcher.c)
and [venv launcher build](https://github.com/python/cpython/blob/v3.11.9/PCbuild/venvlauncher.vcxproj).
Do not replace the child command with `pythonw` or a Windows `gui_scripts`
entry point: the private startup handshake owns binary stdin/stdout pipes.
See [PyPA's entry-point specification](https://packaging.python.org/en/latest/specifications/entry-points/).
The embeddable Python distribution omits Tcl/Tk and is not this profile.

Build the wheel with the existing repository build workflow. Install its same
bytes in both selected full interpreters using normal `pip install`, not `-e`.
Use `requirements.lock` for the host's dependency versions. Hermes dependencies
remain its explicit existing installation; only canonical Adaptive Inference
code must come from the regular wheel. The worker verifies package contents
before loading that dependency directory and verifies origins again afterward.

When replacing a development wheel that still has the same version number,
pip may keep the older installed package. After installing the locked
dependencies, explicitly reinstall the selected wheel into each chosen target
interpreter with `python -m pip install --force-reinstall --no-deps <wheel>`.
Use that interpreter's full path and verify the imported package origin and
contents. This uses pip's documented
[reinstallation option](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-force-reinstall);
the task-preparation package check reproduced the same-version skip before
confirming installation of the selected wheel. A version string alone is not
proof that the new source was installed.

The exact Hermes revision is
`14e1e43a23761b369641208e204365cd6cb9399d`; the existing
[offline source supplement](../integrations/hermes/current-source/README.md)
preserves it independently of upstream availability.

An externally managed Python installation can refuse this direct installation
under [the externally managed environment specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/).
For this full-interpreter layout, use a separately owned distribution instead
of removing its management marker. Astral documents direct extraction of its
[standalone Python distributions](https://gregoryszorc.com/docs/python-build-standalone/main/running.html),
which include pip for normal package installation. Select an official versioned
release, verify its published archive digest, retain its licenses, and extract
into a new directory. Pin the resulting executable and use that explicit path.
The `install_only` and `install_only_stripped` archives are distinct artifacts;
the same version string does not establish identical executable bytes. Verify
direct process identity and full interpreter prefixes, then install and verify
the same canonical wheel before qualifying the new deployment. This procedure
reuses the vendor's packaging; it introduces no alternate package loader.

The reference worker deployment selects
`cpython-3.14.7+20260901-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`
from the [official PBS 20260901 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901),
archive SHA-256 `ca3c33ca924dfcab3b74205a7a58a88b0255135c53f95497b26b5e60700fd66d`.
Its executable SHA-256 is
`716fbcb56cb6753dd9ea9f7acb3f988e9c4ba65ab492cb32b9bcd0ab81938737`.
The same artifact is recorded in
[uv 0.12.16's download metadata](https://github.com/astral-sh/uv/blob/0.12.16/crates/uv-python/download-metadata.json).
The [versioned PBS instructions](https://github.com/astral-sh/python-build-standalone/blob/20260901/docs/running.rst)
describe extraction and included packaging tools;
[uv's managed-installation implementation](https://github.com/astral-sh/uv/blob/0.12.16/crates/uv-python/src/managed.rs)
explains the marker added when uv manages that installation. These references
establish the supported deployment method, not completion of its live task.

The native owner is an explicit sealed local package, with external IQ3_S assets.
Use the existing [handoff-owner preparation helper](../examples/validation/windows_handoff/native/prepare_handoff_owner.py)
and its source/manifest/provenance verification. Model assets are not copied into
the Python wheel. This first profile retains owned Strata at
`http://127.0.0.1:18098/v1`; it does not discover/adopt a running server, substitute
a model, weaken driver pins or claim native support for other HTTP engines.

## Explicit profile

Use the [setup helper](../examples/desktop/README.md) to select the installed
components and calculate their hashes. It writes the same profile shown below
and a reusable launcher. The helper and launch script travel in the repository
and full source distribution; the runtime wheel is unchanged.

For manual configuration, create a local JSON file with these exact fields,
replacing the example paths and SHA-256 placeholders with the actual selected
artifacts. There is one host interpreter field; it is also the GUI interpreter.

```json
{
  "schema": "adaptive.desktop.windows-orders.v1",
  "host_python": {"path": "C:/Python311/python.exe", "sha256": "<64 lowercase hex characters>"},
  "worker_python": {"path": "C:/Python314/python.exe", "sha256": "<64 lowercase hex characters>"},
  "hermes": {
    "source": "D:/Agents/hermes-pinned-source",
    "site_packages": "D:/Agents/hermes-environment/Lib/site-packages"
  },
  "native_owner": {
    "package": "D:/Models/owned-strata-profile",
    "manifest_sha256": "<64 lowercase hex characters>",
    "provenance_sha256": "<64 lowercase hex characters>"
  },
  "gateway": {
    "listen": {"host": "127.0.0.1", "port": 18100},
    "backend": {"kind": "strata", "base_url": "http://127.0.0.1:18098/v1", "revision": "explicit-local-IQ3_S"},
    "scheduler": {"queue_timeout_s": 600},
    "limits": {"upstream_timeout_s": 600, "upstream_read_timeout_s": 600},
    "default_class": "normal"
  },
  "foreground_policy": "cooperative-owned-foreground.v1"
}
```

The existing `Config` parser validates the gateway. Unknown profile fields,
relative paths, changed interpreter/package bytes, mixed imported module
identities and changed SDK interfaces are refused. Package verification uses
Python's [installed distribution file metadata](https://docs.python.org/3.11/library/importlib.metadata.html#distribution-files)
and recorded file hashes. It is a reproducibility/identity check, not an integrity
boundary against someone who can modify the interpreter and installation.

Select `strict-foreground.v3` for the previous strict foreground policy. The
explicit cooperative profile permits the exact owned GUI only while the host
observes authenticated serialized control progress and sufficient headroom.
It retains pressure/freshness gates, conservative yield and safe-boundary drain.
It does not exempt another foreground application or fabricate low CPU samples.
Its declared thresholds and limitations are in the [plan](../PLAN.md).

Launch from a directory outside the checkout and use a **fresh** state directory:

```powershell
& 'C:/Python311/python.exe' -I -B -m adaptive_inference desktop --profile 'D:/Profiles/windows-orders.json' --run 'D:/Runs/orders-001'
```

The command runs as a dedicated process containing its own children in a
Windows job. It does not signal unrelated PIDs. Run state and private diagnostics
stay in the selected local directory. Do not tail mutable host status files
while it is running; on Windows an open destination can interfere with the
writer's atomic replacement. Use the existing authenticated control UI/API and
read terminal evidence after shutdown.

The window's X button minimizes the same controls to the taskbar. Restore it
from the taskbar; **Stop engine** remains the explicit session shutdown action.
This uses the existing Tk window and binding. It is not window-close/reopen or
restart recovery, which remains a separate qualification item. The implementation
reuses Tcl/Tk's [window-manager iconify operation](https://www.tcl-lang.org/man/tcl8.6.14/TkCmd/wm.htm).

The task deadline and request allowance remain bounded. After a verified
completed or cancelled task the ordinary host remains parked/open until Stop; a qualification
watchdog does not limit that host's lifetime. If cleanup cannot prove that its
retained process/pipe/native obligations are finished, it retains those
obligations and reports uncertainty instead of claiming a clean Stop. Explicit
qualification callers retain the original 1,800-second emergency guard; an
emergency exit is a failed test, never normal cleanup.

A safely paused execution can end with the separately verified
[paused-expiry outcome](paused-budget-expiry.md), preserving its pending task and
keeping the host/window open. Active or uncertain work does not acquire that
outcome merely because its deadline passed. Unexpected worker exit is never
reinterpreted as safe completion or clean Stop.

The later [explicit Continue action](explicit-continuation.md) preserves the
same logical task/window and creates a distinct execution only after verified
release and authorization. One click includes the derived Resume; ordinary
foreground/capacity gates still apply. Its [separate installed acceptance](../provenance/explicit-continuation/acceptance/README.md)
passed 70 independent terminal checks with three cumulative IQ3_S requests, one
report write and normal shutdown. Its qualification envelope is 2,700 seconds for two 900-second
budgets plus setup/cleanup; the original 1,800-second expiry qualification is
unchanged. New tasks, physical reboot recovery and daily-use always-on operation
remain separate M2 gates.

## Component and deployment checks

The portable component suite includes actual SQLite controls, retained wait and
closure races, worker import boundaries, exact cold-start ordering, unchanged
quality/report validation, foreground policy behavior and GUI protocol/rendering
fixtures. It starts no native model and cannot establish desktop performance.

```text
python -m unittest discover -s tests -p "test_desktop_*.py" -v
```

Regular-wheel checks must run from an external working directory in isolated
mode so checkout imports cannot hide missing files. This reuses
[PyPA's src-layout guidance](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).
The retained lifecycle follows the existing host's `max_runtime_seconds=None`,
Python's [shielded-task retention](https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation)
and actual process/stream joins. The [installed qualification scripts](../examples/validation/installed_desktop/README.md) exercise
that same composition, with separate cold Pause/Stop and full report/restart
cases; they must not replace the oracle, original deadlines or exact-owner gates.
