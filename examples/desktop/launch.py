# SPDX-License-Identifier: Apache-2.0
"""Choose a prepared task and run the existing installed desktop composition."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid


def choose_saved_task(parent, runs):
    import tkinter
    from tkinter import messagebox
    from adaptive_inference.desktop.saved_tasks import discover

    rows = discover(runs)
    if not rows:
        messagebox.showinfo('Saved tasks', 'No tasks created with saved-task support are available.', parent=parent)
        return None
    window = tkinter.Toplevel(parent)
    window.title('Open a saved task')
    selected = None
    listing = tkinter.Listbox(window, width=90, height=min(12, len(rows)), exportselection=False)
    for row in rows:
        listing.insert('end', row['label'])
    listing.pack(padx=12, pady=12)
    listing.selection_set(0)

    def open_selected():
        nonlocal selected
        index = listing.curselection()
        if index:
            selected = {'saved_task': rows[index[0]]['saved_task']}
            window.destroy()

    tkinter.Button(window, text='Open saved task', command=open_selected).pack(fill='x', padx=12, pady=5)
    tkinter.Button(window, text='Cancel', command=window.destroy).pack(fill='x', padx=12, pady=5)
    parent.wait_window(window)
    return selected


def show_saved_result(result):
    import tkinter
    root = tkinter.Tk()
    try:
        root.title('Adaptive Inference — saved result')
        text = tkinter.Text(root, width=90, height=24, wrap='word')
        text.pack(padx=12, pady=12)
        text.insert('end', result['objective'] + '\n\n' + result['output'])
        if result['artifacts']:
            text.insert('end', '\n\nSaved files:\n' + '\n'.join(result['artifacts']))
        text.configure(state='disabled')
        tkinter.Button(root, text='Close', command=root.quit).pack(pady=8)
        root.mainloop()
    finally:
        root.destroy()


def select_task(runs=None):
    import tkinter
    from adaptive_inference.desktop.run_gui import choose_task

    root = tkinter.Tk()
    selected = None
    failures = []

    def choose(saved=False):
        nonlocal selected
        try:
            selected = choose_saved_task(root, runs) if saved else choose_task(root)
        except Exception as error:
            failures.append(error)
            root.quit()
        else:
            if selected is not None:
                root.quit()

    try:
        root.title('Adaptive Inference — choose a task')
        root.resizable(False, False)
        tkinter.Label(root, text='Start a new task or open saved work.\n'
                      'The engine will remain paused until you select Resume.',
                      padx=18, pady=14).pack()
        tkinter.Button(root, text='New task', command=choose).pack(
            fill='x', padx=18, pady=5)
        if runs is not None:
            tkinter.Button(root, text='Open saved task', command=lambda: choose(True)).pack(
                fill='x', padx=18, pady=5)
        tkinter.Button(root, text='Cancel', command=root.quit).pack(
            fill='x', padx=18, pady=(5, 14))
        root.protocol('WM_DELETE_WINDOW', root.quit)
        # Reuse the working New task interaction: a native picker opened by a
        # button callback on a visible parent with its Tk event loop running.
        root.mainloop()
        if failures:
            raise failures[0]
        return selected
    finally:
        root.destroy()


def launch(profile_path=None, runs=None, *, picker=None, executor=None, result_viewer=None):
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
    selected = select_task(run_parent) if picker is None else picker()
    if selected is None:
        return None
    if executor is None:
        from adaptive_inference.desktop.composition import execute
        executor = execute
    # execute owns the new directory, Windows job, children and normal cleanup.
    # The temporary picker is already destroyed; there is no second supervisor.
    run = run_parent / ('session-' + uuid.uuid4().hex)
    if 'saved_task' in selected:
        result = executor(profile_path, run, saved_task=selected['saved_task'], enable_reopen=True)
    else:
        result = executor(profile_path, run, task_spec=selected['task_spec_path'],
                          task_inputs=selected['task_inputs'], enable_reopen=True)
    if 'saved_result' in result:
        (show_saved_result if result_viewer is None else result_viewer)(result['saved_result'])
    return result


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
