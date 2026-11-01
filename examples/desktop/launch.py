# SPDX-License-Identifier: Apache-2.0
"""Choose a prepared task and run the existing installed desktop composition."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid


def select_task():
    import tkinter
    from adaptive_inference.desktop.run_gui import choose_task

    root = tkinter.Tk()
    try:
        root.withdraw()
        return choose_task(root)
    finally:
        root.destroy()


def launch(profile_path=None, runs=None, *, picker=None, executor=None):
    from adaptive_inference.desktop.profile import WindowsProfile

    directory = Path(__file__).resolve(strict=True).parent
    profile_path = Path(profile_path or directory / 'deployment.json').resolve(strict=True)
    profile = WindowsProfile.load(profile_path)
    from adaptive_inference.desktop.installation import package_identity, verify_interpreter
    verify_interpreter(profile.host_python, profile.host_python_sha256, current=True)
    package_identity()
    run_parent = Path(runs or directory / 'runs').resolve(strict=True)
    if not run_parent.is_dir():
        raise ValueError('The configured runs folder is unavailable')
    selected = (select_task if picker is None else picker)()
    if selected is None:
        return None
    if executor is None:
        from adaptive_inference.desktop.composition import execute
        executor = execute
    # execute owns the new directory, Windows job, children and normal cleanup.
    # The temporary picker is already destroyed; there is no second supervisor.
    run = run_parent / ('session-' + uuid.uuid4().hex)
    return executor(profile_path, run, task_spec=selected['task_spec_path'],
                    task_inputs=selected['task_inputs'])


def main():
    try:
        result = launch()
        if result is None:
            return 0
        print(json.dumps({key: result.get(key) for key in
                          ('clean_stop', 'task_completed', 'worker_outcome',
                           'semantic_validation', 'validated_artifacts')}))
        return 0 if result['clean_stop'] else 1
    except (OSError, ValueError, RuntimeError) as error:
        print('Adaptive Inference: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
