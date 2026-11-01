# Set up the supported desktop launcher

These helpers accompany the `0.4.0a1` reference alpha. Use its matching complete
source archive and runtime wheel; the small wheel does not contain these example
scripts or the external model/runtime prerequisites.

This helper creates a local deployment profile and **Start Adaptive Inference**
launcher from an existing supported installation. It removes manual hash editing
and run-directory naming. It does not install Python, packages, Hermes, drivers,
the native owner or models. Follow the [installed desktop guide](../../docs/installed-desktop.md)
for those prerequisites, retaining the existing IQ3_S assets and quality.

Download this repository or its source archive. Run `setup.py` with the explicit
full Windows CPython 3.11.9 interpreter containing the regular Adaptive Inference
wheel. Keep the same wheel installed in the selected full worker interpreter.
Run from outside the checkout so the package comes from that installation.

```powershell
& 'C:/Python311/python.exe' -I -B 'D:/adaptive-inference/examples/desktop/setup.py' `
  --destination 'D:/Adaptive Desktop' `
  --worker-python 'D:/Python314/python.exe' `
  --hermes-source 'D:/Agents/hermes-pinned-source' `
  --hermes-site-packages 'D:/Agents/hermes-environment/Lib/site-packages' `
  --native-owner 'D:/Models/owned-strata-profile'
```

Replace these example paths with your existing components. The destination must
be new and its parent must exist. The helper verifies the running host and its
wheel, pinned Hermes interfaces, and the existing native owner's own file,
dependency, model-metadata and quality checks. It calculates the profile's hashes
from the selected files. It does not run the worker or model; the existing
composition verifies the worker's installed package and imports during startup.
Successful setup is not a live inference qualification.

The default uses the existing cooperative foreground policy and gateway port
18100. `--foreground-policy strict-foreground.v3` selects the existing strict
policy; `--gateway-port` selects another allowed local gateway port. The owned
backend stays on port 18098 with the same quality and execution allowances.

Open **Start Adaptive Inference.cmd**, select **New task** in its startup
window, choose a prepared task specification and its input folder, then use
**Resume** in the existing control window. Cancelling a native picker returns to
the startup window; **Cancel** closes it without starting a task. Each launch
uses a new folder below `runs`; the
controller owns its creation and cleanup. Stop the current controller before
starting another against the same backend. **New task**, **Continue saved task**
and **Stop engine** retain their existing behavior. See the
[ordinary workflow](../../docs/reference-workflow.md) and
[task preparation command](../../docs/task-spec.md#prepare-your-own-task).

The generated folder contains `deployment.json`, a byte-for-byte copy of
`launch.py`, the Start command and `runs`. The launcher calls the existing
`choose_task` and `composition.execute` in one dedicated full-Python process.
It uses no extra service or task executor. The picker is destroyed before the
controller acquires its children.

The candidate launcher also offers **Open saved task** for tasks created by this
launcher with saved-task support. A safe stopped unfinished task reopens paused
with its original prompt, history, receipts and remaining execution budget;
select **Resume** to continue. Time while the application is closed still counts
against that budget. Reopening requires the same observed Windows boot, profile
and package; an exhausted or uncertain execution is refused. Completed tasks
open a read-only result view without the worker or model, including after a boot
or package change. Discovery does not repair databases or adopt old validation
archives. This first path lists tasks started from the startup window; it is not
computer-restart recovery or a migration tool. See [saved-task reopening](../../docs/saved-task-reopening.md)
for its source-validation and pending installed-qualification boundaries.

## Reused mechanisms and validation scope

The helper uses the project's Apache-2.0 profile, installation, native-owner,
task-picker and controller code. No external implementation is copied.
Official sources checked on 1 November 2026:

- [Python native file dialogs](https://docs.python.org/3.11/library/dialog.html#module-tkinter.filedialog)
  provide the existing task selection and cancellation behavior.
- [Python's Tk event-loop example](https://docs.python.org/3.11/library/tkinter.html#a-hello-world-program)
  supplies the normal visible-window/button-callback pattern. The first installed
  launcher check reached the native file-dialog call without a visible picker or
  a task starting. The revised entry follows the existing controller's **New task**
  interaction: a visible parent running its event loop before the user opens the
  picker. A fresh [installed startup/Stop check](../../docs/evidence.md#supported-desktop-setup-helper)
  then displayed the picker and paused controller and closed after one Stop,
  with zero provider calls and no native backend launch. The precise cause of
  the first invisible dialog remains unknown; both attempts retain their
  original installation identities.
- [Python command-line options](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I)
  document isolated `-I` execution; `-B` avoids bytecode writes. The launcher
  uses an explicit interpreter and ordinary installed imports.
- [Installed distribution file metadata](https://docs.python.org/3.11/library/importlib.metadata.html#distribution-files)
  supplies the file/hash information already checked by `package_identity`.
- [Microsoft's command processor reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)
  documents quoting and expansion. Literal interpreter percent signs are escaped,
  delayed expansion is disabled, and paths are quoted.
- [PyPA entry points](https://packaging.python.org/en/latest/specifications/entry-points/)
  distinguish Windows console and GUI wrappers. The existing pipe-based GUI
  startup continues using full `python.exe`, without a `pythonw` substitution.

`tests/test_desktop_setup.py` checks profile generation, exact launcher copying,
cancel/launch forwarding and the generated Windows command with an inert Python
stub. These are setup/component checks, not model, foreground-performance or
reboot acceptance. The helpers ship in the source archive; they do not alter the
runtime wheel or replace the separate installed deployment qualification.
