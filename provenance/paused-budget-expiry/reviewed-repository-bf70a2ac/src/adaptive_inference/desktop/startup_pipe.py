# SPDX-License-Identifier: Apache-2.0
"""Bounded frame shape, not a claim that synchronous pipe I/O cannot block."""
from dataclasses import asdict
import json
import threading

from adaptive_inference.desktop.control_client import Bootstrap, BOOTSTRAP_LIMIT, decode

REPORT_LIMIT = 4096
ACK_LIMIT = 512


class StartupError(RuntimeError):
    pass


class PipeCleanupError(StartupError):
    def __init__(self, primary, cleanup):
        super().__init__('Startup pipe operation and cleanup both failed')
        self.primary_error, self.cleanup_error = primary, cleanup


def close_preserving(stream, primary):
    try:
        stream.close()
    except BaseException as cleanup:
        if primary is not None:
            raise PipeCleanupError(primary, cleanup) from primary
        raise


def frame(value, limit):
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
    if len(data) > limit:
        raise StartupError('Startup frame exceeds its bound')
    return data


def bootstrap_frame(bootstrap):
    if type(bootstrap) is not Bootstrap:
        raise TypeError('Verified bootstrap object required')
    return frame(asdict(bootstrap), BOOTSTRAP_LIMIT)


def read_frame(stream, limit):
    data = stream.readline(limit + 1)
    if type(data) is not bytes or not 0 < len(data) <= limit or not data.endswith(b'\n') or data.count(b'\n') != 1:
        raise StartupError('Invalid startup frame')
    return data


def read_report(stream):
    # Parent uses a retained off-loop task. A short frame without EOF is not
    # accepted, and a blocked EOF read is an unresolved owned obligation.
    primary = None
    try:
        data = read_frame(stream, REPORT_LIMIT)
        if stream.read(1) != b'':
            raise StartupError('Startup report has trailing bytes')
        return data
    except BaseException as error:
        primary = error
        raise
    finally:
        close_preserving(stream, primary)


def write_frame(stream, data, *, close=False):
    primary = None
    try:
        offset = 0
        while offset < len(data):
            written = stream.write(data[offset:])
            if type(written) is not int or not 0 < written <= len(data) - offset:
                raise StartupError('Startup write made no confirmed progress')
            offset += written
        stream.flush()
    except BaseException as error:
        primary = error
        raise
    finally:
        if close:
            close_preserving(stream, primary)


def candidate(bootstrap, hwnd):
    if type(hwnd) is not int or not 0 < hwnd < 2**64:
        raise StartupError('Invalid root candidate')
    return {'schema': 1, 'host_epoch': bootstrap.host_epoch, 'session_id': bootstrap.session_id,
            'task_id': bootstrap.task_id, 'root_hwnd': hwnd}


def parse_candidate(data, bootstrap):
    value = decode(data, REPORT_LIMIT, line=True)
    if (type(value) is not dict or set(value) != {'schema', 'host_epoch', 'session_id', 'task_id', 'root_hwnd'}
            or type(value['schema']) is not int or value != candidate(bootstrap, value['root_hwnd'])):
        raise StartupError('Startup report does not match this retained launch')
    return value['root_hwnd']


def ready_ack(bootstrap):
    return frame({'ready': True, 'session_id': bootstrap.session_id}, ACK_LIMIT)


class ChildHandshake:
    """One retained startup I/O thread. No Tk calls or network in that thread."""
    def __init__(self, bootstrap, hwnd, stdin, stdout):
        self.bootstrap, self.hwnd, self.stdin, self.stdout = bootstrap, hwnd, stdin, stdout
        self.done = threading.Event()
        self.accepted = False
        self.error = None
        self.primary_error = self.cleanup_error = None
        self.start_error = None
        self.cleanup_errors = {}
        self._start_attempted = self._never_started = False
        self._started = False
        self._thread = threading.Thread(target=self._run, name='adaptive-ui-startup', daemon=False)

    def start(self):
        if self._start_attempted:
            raise StartupError('Startup thread cannot be attempted again')
        self._start_attempted = True
        try:
            # Reuse NetworkWorker's successful-acquisition ordering. A failed
            # start is not a successful thread and cannot be joined as one.
            self._thread.start()
            self._started = True
        except BaseException as error:
            self.start_error = self.primary_error = error
            self.accepted = False
            self.error = 'startup_thread_start_unconfirmed'
            if self._thread.ident is not None:
                self._started = True
            elif isinstance(error, RuntimeError):
                # CPython3.11.9's native creation failure has no ident. An
                # interrupted/ambiguous BaseException remains retained below;
                # it must not close streams a late thread might still use.
                self._never_started = True
                for name, stream in (('stdout', self.stdout), ('stdin', self.stdin)):
                    try:
                        stream.close()
                    except BaseException as cleanup:
                        self.cleanup_errors[name] = cleanup
                        if self.cleanup_error is None:
                            self.cleanup_error = cleanup
                self.done.set()
            raise

    def _run(self):
        try:
            write_frame(self.stdout, frame(candidate(self.bootstrap, self.hwnd), REPORT_LIMIT), close=True)
            ack = decode(read_frame(self.stdin, ACK_LIMIT), ACK_LIMIT, line=True)
            if (type(ack) is not dict or set(ack) != {'ready', 'session_id'}
                    or ack['ready'] is not True or ack['session_id'] != self.bootstrap.session_id
                    or self.stdin.read(1) != b''):
                raise StartupError('Parent readiness acknowledgement is invalid')
            self.accepted = self.start_error is None
        except BaseException as error:
            self.primary_error = error
            self.error = 'startup_exchange_unconfirmed'
        finally:
            try:
                self.stdin.close()
            except BaseException as error:
                self.cleanup_error = error
                self.error = 'startup_input_close_unconfirmed'
                self.accepted = False
            self.done.set()

    def joined(self):
        if not self._start_attempted or self._never_started:
            return True
        # CPython publishes ident before its own started Event. Our existing
        # completion Event can only follow entry into run(), after that native
        # bootstrap boundary. Identity alone cannot authorize Thread.join().
        if not self.done.is_set():
            return False
        if not self._started:
            if self._thread.ident is None:
                return False
            self._started = True
        if self._thread.is_alive():
            return False
        self._thread.join(timeout=0)
        return True
