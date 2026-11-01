# SPDX-License-Identifier: Apache-2.0
"""Retained one-attempt Windows launch. No process/window discovery or killing."""
import asyncio
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import ctypes as C
from ctypes import wintypes as W

from adaptive_inference.desktop.control_client import Bootstrap
from adaptive_inference.desktop.retained_ui import AcquisitionError, RetainedUIVerifier, WindowsAPI as VerifierAPI
from adaptive_inference.desktop.ui_intent import UIBinding
from adaptive_inference.desktop.startup_pipe import bootstrap_frame, parse_candidate, read_report, ready_ack, write_frame, StartupError

SUBPROCESS_SHA256 = '4f08d583a95b415762d888fff499c19103040d4b7027e25a73d46c7e3d777d04'
# Qualified child imports also execute both package initializers. Pins are
# relative to the installed adaptive_inference package, not the checkout.
CHILD_SOURCES = frozenset(('__init__.py', 'desktop/__init__.py',
    'desktop/run_gui.py', 'desktop/gui_session.py', 'desktop/startup_pipe.py',
    'desktop/window_marker.py', 'desktop/control_client.py', 'task_spec.py', 'feedback.py'))


@dataclass(frozen=True)
class LaunchSpec:
    interpreter: Path
    interpreter_sha256: str
    entrypoint: Path
    source_pins: tuple

    def verify(self):
        if (not self.interpreter.is_absolute() or not self.entrypoint.is_absolute()
                or not self.source_pins or len(self.source_pins) > 64):
            raise StartupError('Explicit bounded pinned launch paths required')
        if hashlib.sha256(self.interpreter.read_bytes()).hexdigest() != self.interpreter_sha256:
            raise StartupError('GUI interpreter changed')
        root = self.entrypoint.parent.parent.resolve(strict=True)
        if (root.name != 'adaptive_inference'
                or self.entrypoint != root / 'desktop' / 'run_gui.py'
                or self.entrypoint.resolve(strict=True) != self.entrypoint):
            raise StartupError('The GUI must be the installed package entrypoint')
        seen = set()
        for relative, expected in self.source_pins:
            if type(relative) is not str or relative not in CHILD_SOURCES or relative in seen:
                raise StartupError('Source pin must name one unique installed child source')
            path = (root / relative).resolve(strict=True)
            if path != root / relative or not path.is_relative_to(root) or not path.is_file():
                raise StartupError('Installed child source cannot escape its package')
            seen.add(relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise StartupError('GUI source changed')
        if seen != CHILD_SOURCES:
            raise StartupError('Every installed child import and package initializer must be pinned')


class WindowsLaunchAPI:
    """Pinned CPython handle seam plus documented retained identity/job APIs."""
    def __init__(self):
        if (os.name != 'nt' or sys.implementation.name != 'cpython'
                or sys.version_info[:3] != (3, 11, 9)
                or hashlib.sha256(Path(subprocess.__file__).read_bytes()).hexdigest() != SUBPROCESS_SHA256):
            raise StartupError('Unsupported retained Popen handle implementation')
        self.identity_api = VerifierAPI()
        self.k = self.identity_api.k
        self.k.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
        self.k.IsProcessInJob.restype = W.BOOL

    def in_job(self, process_handle, job_handle):
        if type(job_handle) is not int or job_handle <= 0:
            raise StartupError('Actual containing job handle required')
        answer = W.BOOL()
        if not self.k.IsProcessInJob(process_handle, job_handle, C.byref(answer)):
            raise self.identity_api.error('IsProcessInJob')
        return bool(answer.value)

    def current_in_job(self, job_handle):
        return self.in_job(self.k.GetCurrentProcess(), job_handle)

    @staticmethod
    def handle(process):
        if type(process) is not subprocess.Popen:
            raise StartupError('Original retained Popen required')
        return int(process._handle)

    def identity(self, handle):
        return self.identity_api.process_identity(handle)

    def close_process_handle(self, process):
        # Preserve Popen's Handle.closed bookkeeping and avoid a second close.
        # Caller has already positively joined this exact retained child.
        process._handle.Close()


def child_environment(interpreter):
    allowed = {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LOCALAPPDATA'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env['PATH'] = str(interpreter.parent) + os.pathsep + str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
    return env


class OwnedUILaunch:
    def __init__(self, *, api, spawn=subprocess.Popen, verifier_factory=RetainedUIVerifier.from_launch,
                 clock=time.monotonic):
        self.api, self.spawn, self.verifier_factory, self.clock = api, spawn, verifier_factory, clock
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self.process = self.binding = self.verifier = None
        self._start_task = self._writer = self._reader = self._input_close = self._output_close = None
        self._io = []
        self._aborted = self._bound = self._revoked = self._process_closed = False
        self._bind_attempted = self._revoke_attempted = False
        self._auth_revoked = self._process_close_confirmed = self._verifier_close_confirmed = False
        self._revoke = None
        self._faults = set()
        self.primary_error = self.cleanup_error = None
        self.returncode = None

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise StartupError('Launch belongs to its original host loop/thread')

    def _retain_io(self, function, *args, **kwargs):
        if len(self._io) >= 4:
            raise StartupError('Fixed startup I/O obligation bound exceeded')
        task = self._loop.create_task(asyncio.to_thread(function, *args, **kwargs))
        self._io.append(task)
        def finished(done):
            if done.cancelled() or done.exception() is not None:
                self._faults.add('startup_io_unconfirmed')
        task.add_done_callback(finished)
        return task

    def _close_input_after_writer(self):
        if (self.process is not None and self._input_close is None
                and (self._writer is None or self._writer.done())):
            self._input_close = self._retain_io(self.process.stdin.close)

    def abort_startup(self):
        self._owner()
        self._aborted = True
        self._close_input_after_writer()

    async def start(self, spec, bootstrap, *, containing_job, launch_ready, bind_session, revoke_session, timeout_s=10):
        self._owner()
        if (self._start_task is not None or type(spec) is not LaunchSpec or type(bootstrap) is not Bootstrap
                or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 30):
            raise StartupError('One bounded launch attempt required')
        if not all(callable(value) for value in (launch_ready, bind_session, revoke_session)):
            raise TypeError('Explicit trusted lifecycle hooks required')
        self._revoke = revoke_session
        self._start_task = self._loop.create_task(self._start(spec, bootstrap, containing_job, launch_ready, bind_session))
        try:
            return await asyncio.wait_for(asyncio.shield(self._start_task), timeout_s)
        except BaseException:
            self.abort_startup()
            raise

    async def _start(self, spec, bootstrap, job, launch_ready, bind_session):
        try:
            # This may hash an executable; it is not host-loop work.
            await asyncio.to_thread(spec.verify)
            if self._aborted or launch_ready() is not True or self.api.current_in_job(job) is not True:
                raise StartupError('Cold host/containing-job launch prerequisite failed')
            command = [str(spec.interpreter), '-I', '-B', str(spec.entrypoint)]
            self.process = await asyncio.to_thread(self.spawn, command,
                cwd=spec.entrypoint.parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0, close_fds=True,
                creationflags=0x08000000, env=child_environment(spec.interpreter))
            if self._aborted:
                self._close_input_after_writer()
                raise StartupError('Launch completed after startup was fenced')
            handle = self.api.handle(self.process)
            if self.api.in_job(handle, job) is not True or self.process.poll() is not None:
                raise StartupError('Retained child is not live in the exact containing job')
            self._writer = self._retain_io(write_frame, self.process.stdin, bootstrap_frame(bootstrap))
            reader = self._reader = self._retain_io(read_report, self.process.stdout)
            await asyncio.gather(asyncio.shield(self._writer), asyncio.shield(reader))
            if self._aborted:
                raise StartupError('Startup was fenced before readiness')
            hwnd = parse_candidate(reader.result(), bootstrap)
            pid, created = self.api.identity(handle)
            if pid != self.process.pid or self.process.poll() is not None:
                raise StartupError('Retained launch identity or liveness changed')
            self.binding = UIBinding(bootstrap.host_epoch, bootstrap.session_id, bootstrap.task_id, hwnd, pid, created)
            try:
                self.verifier = self.verifier_factory(self.binding, handle, bootstrap.marker_name, bootstrap.marker_value)
            except AcquisitionError as error:
                # The failed duplicate CloseHandle remains owned even though
                # construction never returned a usable verifier.
                self.verifier = error.verifier
                raise
            # Owner-loop binding is complete before the child gets ready ACK.
            if self._aborted:
                raise StartupError('Startup was fenced before session binding')
            self._bind_attempted = True
            if bind_session(self.binding, self.verifier, bootstrap) is not True:
                raise StartupError('Trusted session binding was not confirmed')
            self._bound = True
            if self._aborted or self._input_close is not None:
                raise StartupError('Startup was fenced during session binding')
            self._input_close = self._retain_io(write_frame, self.process.stdin, ready_ack(bootstrap), close=True)
            await asyncio.shield(self._input_close)
            if self._aborted:
                raise StartupError('Readiness completed after startup was fenced')
            return self
        except BaseException as error:
            self.primary_error = error
            self._faults.add('startup_failed')
            self._aborted = True
            self._close_input_after_writer()
            raise

    async def join(self, *, timeout_s=2):
        """Wait only this retained attempt; no kill or arbitrary process adoption."""
        self._owner()
        if type(timeout_s) not in (int, float) or not 0 < timeout_s <= 30:
            raise ValueError('Bounded join wait required')
        deadline = self.clock() + timeout_s
        while True:
            if self._aborted:
                self._close_input_after_writer()
            start_done = self._start_task is None or self._start_task.done()
            if self._start_task is not None and self._start_task.done():
                if not self._start_task.cancelled():
                    self._start_task.exception()  # Retrieve retained failure.
            if self.process is not None and self.returncode is None:
                self.returncode = self.process.poll()
            process_done = self.process is None and start_done or self.returncode is not None
            if (process_done and self.process is not None and self._reader is None
                    and self._output_close is None):
                self._output_close = self._retain_io(self.process.stdout.close)
            if process_done and start_done and all(task.done() for task in self._io):
                self._retire()
                break
            if self.clock() >= deadline:
                break
            await asyncio.sleep(min(.02, max(0, deadline - self.clock())))
        return self.diagnostics()

    def _retire(self):
        if self._bind_attempted and not self._revoked:
            if self._revoke_attempted:
                return
            self._revoke_attempted = True
            try:
                self._revoke(self.binding.session_id)
                self._revoked = True
            except BaseException as error:
                self.cleanup_error = error
                self._faults.add('session_revocation_failed')
                return
        if self.verifier is not None:
            try:
                self.verifier.close()
                self._verifier_close_confirmed = self.verifier.status()['duplicate_close_confirmed'] is True
                if not self._verifier_close_confirmed:
                    raise StartupError('Verifier duplicate close is unconfirmed')
            except BaseException as error:
                self.cleanup_error = error
                self._faults.add('verifier_close_unconfirmed')
                return
        if self.process is not None and not self._process_closed:
            # One attempted close. Do not blindly retry a numeric handle after
            # an exceptional CloseHandle outcome.
            self._process_closed = True
            try:
                self.api.close_process_handle(self.process)
                self._process_close_confirmed = True
            except BaseException as error:
                self.cleanup_error = error
                self._faults.add('launch_handle_close_unconfirmed')

    def session_live(self, session_id):
        self._owner()
        if (not self._bound or self._aborted or self._revoked or self._auth_revoked or self._process_closed
                or self.binding is None or session_id != self.binding.session_id):
            return False
        try:
            if self.process.poll() is not None:
                return False
            return self.api.identity(self.api.handle(self.process)) == (self.binding.pid, self.binding.creation_time_100ns)
        except Exception:
            self._faults.add('retained_process_observation_failed')
            return False

    def window_live(self, session_id):
        return self.session_live(session_id) and self.verifier.is_live(self.binding) is True

    def revoke_session(self, session_id):
        self._owner()
        if self.binding is None or session_id != self.binding.session_id:
            raise StartupError('Cannot revoke a different launch session')
        self._auth_revoked = True
        if self.verifier is not None:
            self.verifier.revoke('authenticated_session_closed')

    def diagnostics(self):
        self._owner()
        pending = sum(not task.done() for task in self._io)
        start_done = self._start_task is None or self._start_task.done()
        exited = self.returncode is not None
        pipes_closed = (self.process is None or
                        self.process.stdin.closed is True and self.process.stdout.closed is True)
        duplicate_closed = self.verifier is None or self._verifier_close_confirmed
        process_closed = self.process is None or exited and self._process_close_confirmed
        clean = (start_done and pending == 0 and pipes_closed and duplicate_closed and process_closed
                 and (not self._bind_attempted or self._revoked))
        return {'startup_complete': start_done, 'startup_aborted': self._aborted,
                'child_retained': self.process is not None, 'child_exit_observed': exited,
                'child_exit_code': self.returncode, 'pending_pipe_operations': pending,
                'session_bound': self._bound, 'session_revoked': self._revoked,
                'authentication_revoked': self._auth_revoked,
                'pipe_threads_joined': pending == 0, 'pipe_handles_closed': pipes_closed,
                'verifier_handle_closed': duplicate_closed, 'process_handle_closed': process_closed,
                'launch_handle_close_attempted': self._process_closed, 'faults': sorted(self._faults),
                'closed': clean}
