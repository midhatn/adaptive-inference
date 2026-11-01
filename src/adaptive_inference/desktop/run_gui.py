# SPDX-License-Identifier: Apache-2.0
"""Explicit Windows GUI entrypoint. Importing this file performs no UI/API work."""
from contextlib import contextmanager
import io
import hashlib
from pathlib import Path
import sys


@contextmanager
def owned_startup_streams():
    """Own only the child standard pipe descriptors, before their first read.

    CPython 3.11.9 creates these wrappers with closefd=False. FileIO supplies
    standard-library descriptor ownership; the existing handshake closes it.
    Original wrappers are retired while the descriptors are still valid, so
    interpreter shutdown cannot flush a stale standard output wrapper.
    """
    originals = (sys.stdin, sys.stdout)
    for stream, buffer_type, descriptor in zip(
            originals, (io.BufferedReader, io.BufferedWriter), (0, 1)):
        if (type(stream) is not io.TextIOWrapper or stream.closed
                or type(stream.buffer) is not buffer_type
                or type(stream.buffer.raw) is not io.FileIO
                or stream.buffer.raw.closefd is not False
                or stream.fileno() != descriptor):
            raise RuntimeError('Expected untouched CPython standard pipe wrappers')

    owned = []
    retired = False
    primary = None

    def close_all(streams):
        errors = []
        for stream in streams:
            try:
                stream.close()
            except BaseException as error:
                errors.append(error)
        return errors

    try:
        # Retain each successful acquisition before doing anything with it.
        # No os.close fallback can accidentally close a descriptor twice.
        owned.append(io.FileIO(0, 'rb', closefd=True))
        owned.append(io.FileIO(1, 'wb', closefd=True))
        retired = True
        errors = close_all(reversed(originals))
        if errors:
            raise BaseExceptionGroup('Standard wrapper retirement failed', errors)
        yield owned[0], owned[1]
    except BaseException as error:
        primary = error
    finally:
        # On partial acquisition, retire non-owning wrappers before closing any
        # acquired owner. Unacquired standard descriptors remain process-owned;
        # this entrypoint exits nonzero and its parent retains that child exit.
        errors = [] if retired else close_all(reversed(originals))
        errors.extend(close_all(reversed(owned)))
        if errors:
            raise BaseExceptionGroup('Startup stream cleanup failed',
                                     ([primary] if primary is not None else []) + errors)
        if primary is not None:
            raise primary


def _verify_installed_imports(*, chooser=False):
    """Reject another package copy before acquiring pipes or GUI resources."""
    root = Path(__file__).resolve(strict=True).parent.parent
    expected = {'adaptive_inference': '__init__.py',
                'adaptive_inference.desktop': 'desktop/__init__.py'}
    if chooser:
        expected.update({'adaptive_inference.task_spec': 'task_spec.py',
                         'adaptive_inference.feedback': 'feedback.py'})
    else:
        expected.update({'adaptive_inference.desktop.' + name: 'desktop/' + name + '.py'
                         for name in ('control_client', 'startup_pipe', 'window_marker', 'gui_session')})
    if root.name != 'adaptive_inference':
        raise RuntimeError('The GUI requires its ordinary installed package')
    for name, relative in expected.items():
        origin = getattr(sys.modules.get(name), '__file__', None)
        if not origin or Path(origin).resolve(strict=True) != root / relative:
            raise RuntimeError('GUI package import identity changed')


def choose_task(root, *, dialogs=None):
    """Use standard native dialogs; cancellation never submits a command.

    Only the bounded local TaskSpec is read here. The host rechecks its exact raw
    hash and stages declared inputs; no prompt, credential or file body crosses
    the control protocol. Python 3.11 tkinter.filedialog is the reused mechanism:
    https://docs.python.org/3.11/library/dialog.html#module-tkinter.filedialog
    """
    from adaptive_inference.task_spec import TaskSpec, MAX_SPEC_BYTES, _file
    _verify_installed_imports(chooser=True)
    if dialogs is None:
        from tkinter import filedialog as dialogs
    selected = dialogs.askopenfilename(parent=root, title='Choose a task specification',
        filetypes=(('Task specification', '*.json'), ('All files', '*')))
    if not selected:return None
    path = Path(selected)
    raw = _file(path, MAX_SPEC_BYTES)
    spec = TaskSpec.from_bytes(raw)
    inputs = str(path.parent)
    if spec.data['inputs']:
        inputs = dialogs.askdirectory(parent=root, title='Choose the task input folder', mustexist=True)
        if not inputs:return None
    return {'task_spec_path': str(path), 'task_spec_sha256': hashlib.sha256(raw).hexdigest(),
            'task_inputs': str(inputs)}


def main():
    # -I uses the ordinary installed package, never a source-checkout path.
    from adaptive_inference.desktop.control_client import Bootstrap, BOOTSTRAP_LIMIT, TkView, WireExchange
    from adaptive_inference.desktop.startup_pipe import read_frame
    from adaptive_inference.desktop.window_marker import WindowAPI, RootMarker
    from adaptive_inference.desktop.gui_session import GUISession
    _verify_installed_imports()
    import socket
    import tkinter

    with owned_startup_streams() as (startup_input, startup_output):
        bootstrap = Bootstrap.from_private_reader(lambda limit: read_frame(startup_input, BOOTSTRAP_LIMIT))
        root = tkinter.Tk()
        root.title('Adaptive inference')
        view = TkView(root, minimize_on_close=True, task_chooser=lambda: choose_task(root))
        marker = RootMarker(root, bootstrap.marker_name, bootstrap.marker_value, api=WindowAPI())
        exchange = WireExchange(bootstrap, lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        session = GUISession(root, view, bootstrap, marker, startup_input, startup_output, exchange)
        try:
            session.start()
            root.mainloop()
        finally:
            clean = session.after_mainloop()
    return 0 if clean else 1


if __name__ == '__main__':
    try:
        result = main()
    except BaseException:
        # Never print bootstrap data, exceptions or credential-bearing bytes.
        result = 2
    raise SystemExit(result)
