"""CPU fake process/stdio/DLL/window fixtures only; never launch a child or GUI."""
import asyncio
import ctypes as C
from ctypes import wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from adaptive_inference.desktop import control_client as cc
from adaptive_inference.desktop import gui_launch as launch
from adaptive_inference.desktop.gui_session import GUISession
from adaptive_inference.desktop.startup_pipe import (ChildHandshake, StartupError, PipeCleanupError, bootstrap_frame,
    frame, candidate, parse_candidate, read_frame, read_report, ready_ack, write_frame, REPORT_LIMIT)
from adaptive_inference.desktop.window_marker import RootMarker, WindowAPI, MarkerError, WM_NCDESTROY
from test_desktop_control_client import bootstrap, FakeWorker, Binding, View, life, status
from test_desktop_retained_ui import FakeAPI as VerifierFakeAPI
from adaptive_inference.desktop.retained_ui import AcquisitionError, RetainedUIVerifier
from adaptive_inference.desktop.ui_intent import UIBinding


class Output:
    def __init__(self, *, entered=None, release=None, on_close=None):
        self.data = bytearray()
        self.closed = False
        self.entered, self.release, self.on_close = entered, release, on_close
        self.close_calls = 0
    def write(self, data):
        if self.entered is not None:
            self.entered.set()
        if self.release is not None and not self.release.wait(3):
            raise AssertionError('Bounded fake write was not released')
        self.data.extend(data)
        return len(data)
    def flush(self):
        pass
    def close(self):
        self.close_calls += 1
        self.closed = True
        if self.on_close:
            self.on_close()


class PipeTests(unittest.TestCase):
    def test_frames_are_strict_and_candidate_has_no_credentials(self):
        b = bootstrap()
        data = frame(candidate(b, 2**40 + 55), REPORT_LIMIT)
        self.assertEqual(parse_candidate(data, b), 2**40 + 55)
        self.assertNotIn(b.token.encode(), data)
        for bad in (data + b'x', data + data, data[:-1], b'{}\n', data.replace(b'"schema":1', b'"schema":true')):
            with self.assertRaises(Exception):
                parse_candidate(bad, b)
        for bad in (b'', b'x' * 4097, b'{}'):
            with self.assertRaises(StartupError):
                read_frame(io.BytesIO(bad), 4096)

    def test_report_requires_eof_and_closes_owned_stream(self):
        b = bootstrap()
        good = frame(candidate(b, 100), REPORT_LIMIT)
        stream = io.BytesIO(good)
        self.assertEqual(read_report(stream), good)
        self.assertTrue(stream.closed)
        stream = io.BytesIO(good + b'trailing')
        with self.assertRaises(StartupError):
            read_report(stream)
        self.assertTrue(stream.closed)

    def test_pipe_primary_and_cleanup_failures_both_survive(self):
        class Broken:
            def readline(self, count):
                raise OSError('primary')
            def close(self):
                raise RuntimeError('cleanup')
        with self.assertRaises(PipeCleanupError) as caught:
            read_report(Broken())
        self.assertIsInstance(caught.exception.primary_error, OSError)
        self.assertIsInstance(caught.exception.cleanup_error, RuntimeError)

    def test_partial_writes_are_completed_and_zero_progress_refused(self):
        class Partial(Output):
            def write(self, data):
                self.data.extend(data[:3])
                return min(3, len(data))
        stream = Partial()
        write_frame(stream, b'0123456789\n', close=True)
        self.assertEqual(stream.data, b'0123456789\n')
        self.assertTrue(stream.closed)
        with self.assertRaises(StartupError):
            write_frame(type('Zero', (), {'write': lambda *a: 0})(), b'x')

    def test_child_requires_exact_ack_and_eof_before_acceptance(self):
        b = bootstrap()
        for data, accepted in ((ready_ack(b), True), (ready_ack(b) + b'junk', False),
                               (b'{"ready":true,"session_id":"other"}\n', False), (b'', False)):
            with self.subTest(accepted=accepted, data=data):
                out = Output()
                handshake = ChildHandshake(b, 100, io.BytesIO(data), out)
                handshake.start()
                self.assertTrue(handshake.done.wait(2))
                self.assertTrue(handshake.joined())
                self.assertEqual(handshake.accepted, accepted)
                self.assertTrue(out.closed)
                self.assertEqual(parse_candidate(bytes(out.data), b), 100)

    def test_child_blocked_ack_is_a_retained_join_obligation(self):
        entered, release = threading.Event(), threading.Event()
        b = bootstrap()
        class Blocked(io.BytesIO):
            def readline(self, limit):
                entered.set()
                if not release.wait(2):
                    raise AssertionError('Bounded ACK fixture timed out')
                return super().readline(limit)
        handshake = ChildHandshake(b, 100, Blocked(ready_ack(b)), Output())
        handshake.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertFalse(handshake.joined())
            self.assertFalse(handshake.accepted)
            self.assertFalse(handshake._thread.daemon)
        finally:
            release.set()
            self.assertTrue(handshake.done.wait(2))
            self.assertTrue(handshake.joined())


class FakeRoot:
    def __init__(self):
        self.calls = []
        self.callbacks = []
        self.id = 100
    def update_idletasks(self):
        self.calls.append('idle')
    def winfo_id(self):
        return self.id
    def protocol(self, name, callback):
        self.calls.append(('protocol', name))
    def after(self, delay, callback):
        self.callbacks.append(callback)


class MarkerAPI:
    def __init__(self):
        self.value = 0
        self.calls = []
        self.identity = (11, 7)
        self.root_value = 200
        self.remove_error = self.unsubclass_error = None
    def root(self, hwnd): return self.root_value
    def current_identity(self): return (11, 7)
    def window_identity(self, hwnd): return self.identity
    def marker(self, hwnd, name): return self.value
    def callback(self, function): return function
    def subclass(self, hwnd, callback, identity): self.calls.append('subclass')
    def set_marker(self, hwnd, name, value): self.calls.append('set'); self.value = value
    def remove_marker(self, hwnd, name):
        self.calls.append('remove')
        if self.remove_error: raise self.remove_error
        before, self.value = self.value, 0
        return before
    def unsubclass(self, hwnd, callback, identity):
        self.calls.append('unsubclass')
        if self.unsubclass_error: raise self.unsubclass_error
    def forward(self, *args): self.calls.append(('forward', args)); return 17


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.root, self.api = FakeRoot(), MarkerAPI()
        self.marker = RootMarker(self.root, 'Adaptive.UI.session-1234', 1234, api=self.api)

    def test_install_is_owned_root_and_subclass_precedes_property(self):
        self.assertTrue(self.marker.install())
        self.assertEqual(self.marker.hwnd, 200)
        self.assertEqual(self.api.calls[:2], ['subclass', 'set'])
        self.assertTrue(self.marker.install())
        self.assertEqual(self.api.calls.count('set'), 1)

    def test_wrong_creator_or_preexisting_property_is_not_adopted(self):
        self.api.identity = (12, 7)
        with self.assertRaises(MarkerError): self.marker.install()
        self.assertEqual(self.api.calls, [])
        self.marker = RootMarker(self.root, 'Adaptive.UI.session-1234', 1234, api=self.api)
        self.api.identity, self.api.value = (11, 7), 1234
        with self.assertRaises(MarkerError): self.marker.install()
        self.assertEqual(self.api.calls, [])

    def test_replacement_property_is_never_removed_and_no_recreation(self):
        self.marker.install()
        self.api.value = 999
        self.assertFalse(self.marker.remove())
        self.assertNotIn('remove', self.api.calls)
        with self.assertRaises(MarkerError): self.marker.install()

    def test_native_destruction_cleans_before_forward_and_keeps_callback(self):
        self.marker.install()
        callback = self.marker._callback
        self.assertEqual(callback(200, WM_NCDESTROY, 0, 0, 1234, 0), 17)
        self.assertTrue(self.marker.removed and self.marker.destroyed)
        self.assertFalse(self.marker.subclass_installed)
        self.assertLess(self.api.calls.index('remove'), self.api.calls.index('unsubclass'))
        self.assertEqual(self.api.calls[-1][0], 'forward')
        self.assertIs(self.marker._callback, callback)

    def test_native_cleanup_exceptions_never_skip_forward_or_escape(self):
        self.marker.install()
        self.api.remove_error = OSError('remove denied')
        self.api.unsubclass_error = OSError('subclass denied')
        self.assertEqual(self.marker._callback(200, WM_NCDESTROY, 0, 0, 1234, 0), 17)
        self.assertIn('native_marker_cleanup_failed', self.marker.faults)
        self.assertIn('native_subclass_cleanup_failed', self.marker.faults)
        self.assertEqual(self.api.calls[-1][0], 'forward')

    def test_normal_close_removes_once_then_native_destroy_only_unsubclasses(self):
        self.marker.install()
        self.assertTrue(self.marker.remove())
        self.marker._callback(200, WM_NCDESTROY, 0, 0, 1234, 0)
        self.assertEqual(self.api.calls.count('remove'), 1)

    def test_wrong_thread_mutation_refuses_without_native_calls(self):
        errors = []
        def run():
            try: self.marker.install()
            except Exception as error: errors.append(error)
        worker = threading.Thread(target=run)
        worker.start(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors[0], MarkerError)
        self.assertEqual(self.api.calls, [])

    def test_wrong_thread_native_callback_never_mutates_property_and_still_forwards(self):
        self.marker.install()
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.marker._callback(200,WM_NCDESTROY,0,0,1234,0)))
        worker.start();worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results,[17])
        self.assertNotIn('remove',self.api.calls)
        self.assertNotIn('unsubclass',self.api.calls)
        self.assertIn('native_marker_cleanup_failed',self.marker.faults)

    @unittest.skipUnless(os.name == 'nt', 'Windows ctypes ABI declarations; fake DLL only')
    def test_real_adapter_declarations_and_callback_keep_64bit_values(self):
        calls, table, value = [], {}, {'property': 0}
        hwnd, marker_value = 2**40 + 7, 2**48 + 9
        class Function:
            def __init__(self, name, function): self.name, self.function = name, function
            def __call__(self, *args): calls.append((self.name, args)); return self.function(*args)
        class DLL: pass
        u, k, c = DLL(), DLL(), DLL()
        def add(dll, name, fn): setattr(dll, name, Function(name, fn))
        add(k, 'GetCurrentThreadId', lambda: 11)
        add(k, 'GetCurrentProcessId', lambda: 7)
        add(u, 'GetAncestor', lambda *a: hwnd)
        def creator(h, ptr): C.cast(ptr, C.POINTER(W.DWORD))[0] = 7; return 11
        add(u, 'GetWindowThreadProcessId', creator)
        add(u, 'GetPropW', lambda *a: value['property'])
        def setprop(h, n, v): value['property'] = v; return 1
        def remove(h, n): before=value['property'];value['property']=0;return before
        add(u, 'SetPropW', setprop);add(u, 'RemovePropW', remove)
        add(c, 'SetWindowSubclass', lambda *a: 1);add(c, 'RemoveWindowSubclass', lambda *a: 1)
        add(c, 'DefSubclassProc', lambda *a: 2**40 + 15)
        with mock.patch('adaptive_inference.desktop.window_marker.C.WinDLL', side_effect=lambda name, **k: {'user32':u,'kernel32':k_dll,'comctl32':c}[name]):
            k_dll = k
            api = WindowAPI()
        marker = RootMarker(self.root, 'Adaptive.UI.session-64bit', marker_value, api=api)
        self.assertTrue(marker.install())
        self.assertEqual(marker._callback(hwnd, WM_NCDESTROY, 2**45, -123, marker_value, 0), 2**40 + 15)
        self.assertEqual(calls[-1][1], (hwnd, WM_NCDESTROY, 2**45, -123))
        self.assertEqual(C.sizeof(c.SetWindowSubclass.argtypes[2]), C.sizeof(C.c_void_p))


class VerifierLiveTests(unittest.TestCase):
    def setUp(self):
        self.api = VerifierFakeAPI()
        self.binding = UIBinding('host', 'session', 'task', 100, 7, 80)
        self.verifier = RetainedUIVerifier.from_launch(self.binding, 500, 'Adaptive.UI.session-1234', 1, api=self.api)
        self.addCleanup(self.verifier.close)

    def test_background_window_liveness_uses_no_foreground_call(self):
        self.api.values['foreground'] = 999
        self.api.calls.clear()
        self.assertTrue(self.verifier.is_live(self.binding))
        self.assertNotIn('foreground', [row[0] for row in self.api.calls])
        self.assertIsNone(self.verifier.verify_current(self.binding))

    def test_marker_loss_or_reentrant_revocation_refuses(self):
        self.api.values['marker'] = 0
        self.assertFalse(self.verifier.is_live(self.binding))
        self.assertTrue(self.verifier.status()['retired'])

    def test_reentrant_revoke_before_return_cannot_grant_liveness(self):
        self.api.hooks['marker'] = lambda *a: (self.verifier.revoke('fixture'), 1)[1]
        self.assertFalse(self.verifier.is_live(self.binding))

    def test_denial_is_not_positive_exit_and_slow_observation_refuses(self):
        self.api.hooks['wait'] = lambda *a: (_ for _ in ()).throw(OSError('denied'))
        self.assertFalse(self.verifier.is_live(self.binding))
        self.assertFalse(self.verifier.status()['retired'])
        self.api.hooks.clear()
        stamps = iter([10, 12])
        self.verifier._last_clock = None
        self.verifier._clock = lambda: next(stamps)
        self.assertFalse(self.verifier.is_live(self.binding, max_age_s=1))


class FakeProcess:
    def __init__(self, data):
        self.pid, self.exitcode = 7, None
        self.stdin = Output()
        self.stdout = io.BytesIO(data)
    def poll(self): return self.exitcode


class LaunchAPI:
    def __init__(self):
        self.parent_member = self.child_member = True
        self.identity_value = (7,80)
        self.calls = []
        self.close_error = None
    def current_in_job(self, job): self.calls.append(('parent-job',job));return self.parent_member
    def handle(self, process): self.calls.append(('handle',process));return 500
    def in_job(self, handle, job): self.calls.append(('child-job',handle,job));return self.child_member
    def identity(self, handle): return self.identity_value
    def close_process_handle(self, process):
        self.calls.append(('close-process',process))
        if self.close_error: raise self.close_error


class LaunchVerifier:
    def __init__(self): self.closed=False;self.live=True;self.revoked=False
    def is_live(self, binding): return self.live and not self.revoked
    def revoke(self, reason): self.revoked=True
    def close(self): self.closed=True
    def status(self): return {'duplicate_close_confirmed':self.closed}


class LaunchMappingTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt' and launch.sys.implementation.name == 'cpython'
        and launch.sys.version_info[:3] == (3, 11, 9)
        and hashlib.sha256(Path(launch.subprocess.__file__).read_bytes()).hexdigest() == launch.SUBPROCESS_SHA256,
        'Exact supported CPython Windows bridge; fake function table only')
    def test_real_launch_bridge_retains_original_handle_and_exact_job_membership(self):
        calls=[]
        retained,job=2**45+9,2**44+17
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def member(process,containing,answer):
            calls.append(('job',process,containing))
            C.cast(answer,C.POINTER(W.BOOL))[0]=1
            return 1
        class Kernel:
            IsProcessInJob=Function(member)
            GetCurrentProcess=Function(lambda:-1)
        class Identity:
            k=Kernel()
            def process_identity(self,handle):calls.append(('identity',handle));return (7,2**40+31)
        class Handle:
            closed=False
            def __int__(self):return retained
            def Close(self):self.closed=True;calls.append(('close',retained))
        # Construct a Python object, not a process. Popen.__init__/WinDLL are
        # never called; the original handle seam is exercised exactly.
        process=object.__new__(launch.subprocess.Popen)
        process._child_created=False
        process._handle=Handle()
        with mock.patch('adaptive_inference.desktop.gui_launch.VerifierAPI',return_value=Identity()):
            api=launch.WindowsLaunchAPI()
        self.assertEqual(api.handle(process),retained)
        self.assertTrue(api.current_in_job(job))
        self.assertTrue(api.in_job(retained,job))
        self.assertEqual(api.identity(retained),(7,2**40+31))
        with self.assertRaises(StartupError):api.in_job(retained,True)
        with self.assertRaises(StartupError):api.handle(object())
        api.close_process_handle(process)
        self.assertTrue(process._handle.closed)
        self.assertIn(('job',retained,job),calls)
        self.assertEqual(Kernel.IsProcessInJob.argtypes[:2],[W.HANDLE,W.HANDLE])


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gui-launch-fixture-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()/'adaptive_inference'
        (root/'desktop').mkdir(parents=True)
        interpreter, entry = root/'python-fixture.exe', root/'desktop/run_gui.py'
        interpreter.write_bytes(b'fake interpreter never executed')
        for name in launch.CHILD_SOURCES:(root/name).write_bytes(b'# fixture source never executed\n')
        self.spec = launch.LaunchSpec(interpreter, hashlib.sha256(interpreter.read_bytes()).hexdigest(), entry,
                                      tuple((name,hashlib.sha256((root/name).read_bytes()).hexdigest()) for name in launch.CHILD_SOURCES))
        self.bootstrap = bootstrap()
        self.proc = FakeProcess(frame(candidate(self.bootstrap,100), REPORT_LIMIT))
        self.api, self.verifier = LaunchAPI(), LaunchVerifier()
        self.events, self.releases, self.records = [], [], []
        self.spawn_calls = []
        def spawn(*args, **kwargs): self.spawn_calls.append((args,kwargs));return self.proc
        def verifier(*args):
            self.events.append('verify')
            self.assertNotIn(b'"ready":true', self.proc.stdin.data)
            return self.verifier
        self.record = launch.OwnedUILaunch(api=self.api, spawn=spawn, verifier_factory=verifier)
        self.records.append(self.record)

    def bind(self, binding, verifier, bootstrap):
        self.events.append('bind')
        self.assertNotIn(b'"ready":true', self.proc.stdin.data)
        return True

    async def start(self, **kwargs):
        return await self.record.start(self.spec,self.bootstrap,containing_job=99,launch_ready=lambda:True,
            bind_session=self.bind,revoke_session=lambda sid:self.events.append('revoke'),**kwargs)

    async def asyncTearDown(self):
        for release in self.releases: release.set()
        self.proc.exitcode=0
        for record in self.records:
            await record.join(timeout_s=3)

    async def test_launch_contains_no_secret_and_ack_follows_verified_binding(self):
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY':'do-not-inherit','UI_TOKEN':self.bootstrap.token}):
            self.assertIs(await self.start(), self.record)
        args,kwargs=self.spawn_calls[0]
        self.assertNotIn(self.bootstrap.token,str(args))
        self.assertNotIn(self.bootstrap.token,str(kwargs))
        self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
        self.assertTrue(kwargs['close_fds'])
        self.assertEqual(kwargs['creationflags'],0x08000000)
        self.assertEqual(self.events,['verify','bind'])
        self.assertTrue(self.proc.stdin.closed and self.proc.stdout.closed)
        self.assertEqual(bytes(self.proc.stdin.data),bootstrap_frame(self.bootstrap)+ready_ack(self.bootstrap))
        self.assertTrue(self.record.session_live('session'))
        self.assertFalse(self.record.session_live('other'))

    async def test_no_spawn_if_cold_host_or_parent_job_not_confirmed(self):
        self.api.parent_member=False
        with self.assertRaises(StartupError): await self.start()
        self.assertEqual(self.spawn_calls,[])
        self.assertTrue((await self.record.join())['closed'])

    async def test_no_bootstrap_if_retained_child_job_is_wrong(self):
        self.api.child_member=False
        with self.assertRaises(StartupError): await self.start()
        self.assertEqual(self.proc.stdin.data,b'')

    async def test_changed_local_child_import_is_refused_before_process_creation(self):
        (self.spec.entrypoint.parent/'control_client.py').write_bytes(b'changed')
        with self.assertRaises(StartupError):await self.start()
        self.assertEqual(self.spawn_calls,[])

    async def test_bad_report_never_binds_or_acknowledges(self):
        self.proc.stdout=io.BytesIO(b'{"schema":1}\n')
        with self.assertRaises(Exception): await self.start()
        self.assertEqual(self.events,[])
        self.assertNotIn(b'"ready":true',self.proc.stdin.data)

    async def test_retained_identity_mismatch_never_accepts_report_pid(self):
        self.api.identity_value=(8,80)
        with self.assertRaises(StartupError): await self.start()
        self.assertEqual(self.events,[])

    async def test_large_blocked_bootstrap_writer_and_reader_are_retained_concurrently(self):
        self.bootstrap=bootstrap(objective='x'*16000)
        self.proc.stdout=io.BytesIO(frame(candidate(self.bootstrap,100),REPORT_LIMIT))
        entered,release=threading.Event(),threading.Event();self.releases.append(release)
        self.proc.stdin=Output(entered=entered,release=release)
        waiter=asyncio.create_task(self.start(timeout_s=.05))
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        with self.assertRaises(asyncio.TimeoutError): await waiter
        self.assertTrue(self.proc.stdout.closed)
        self.assertFalse(self.proc.stdin.closed)
        self.assertGreater(self.record.diagnostics()['pending_pipe_operations'],0)
        self.assertFalse((await self.record.join(timeout_s=.02))['closed'])
        release.set();self.proc.exitcode=0
        result=await self.record.join(timeout_s=2)
        self.assertTrue(result['closed'])
        self.assertTrue(result['faults'])
        self.assertNotIn(b'"ready":true',self.proc.stdin.data)

    async def test_cancelled_start_preserves_late_popen_and_pipe_cleanup(self):
        entered,release=threading.Event(),threading.Event();self.releases.append(release)
        def slow_spawn(*args,**kwargs):
            entered.set()
            if not release.wait(2):raise AssertionError('Spawn fixture timed out')
            return self.proc
        self.record.spawn=slow_spawn
        waiter=asyncio.create_task(self.start())
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
        self.assertIsNone(self.record.process)
        self.assertFalse((await self.record.join(timeout_s=.02))['closed'])
        release.set();self.proc.exitcode=0
        result=await self.record.join(timeout_s=2)
        self.assertTrue(result['closed'])
        self.assertIs(self.record.process,self.proc)

    async def test_marker_loss_does_not_block_cleanup_auth_but_session_revocation_does(self):
        await self.start()
        self.verifier.live=False
        self.assertTrue(self.record.session_live('session'))
        self.assertFalse(self.record.window_live('session'))
        self.record.revoke_session('session')
        self.verifier.live=True
        self.assertFalse(self.record.session_live('session'))

    async def test_late_child_exit_is_required_before_handle_and_session_cleanup(self):
        await self.start()
        early=await self.record.join(timeout_s=.02)
        self.assertFalse(early['child_exit_observed'] or early['closed'])
        self.assertNotIn('revoke',self.events)
        self.proc.exitcode=0
        final=await self.record.join(timeout_s=1)
        self.assertTrue(final['closed'] and final['child_exit_observed'])
        self.assertTrue(final['pipe_threads_joined'] and final['pipe_handles_closed'])
        self.assertTrue(final['verifier_handle_closed'] and final['process_handle_closed'])
        self.assertEqual(self.events[-1],'revoke')

    async def test_process_close_failure_is_visible_and_not_retried(self):
        await self.start();self.proc.exitcode=0
        self.api.close_error=OSError('fixture close failure')
        first=await self.record.join(timeout_s=1)
        second=await self.record.join(timeout_s=1)
        self.assertFalse(first['closed'] or second['closed'])
        self.assertEqual(sum(row[0]=='close-process' for row in self.api.calls),1)

    async def test_failed_verifier_acquisition_keeps_its_duplicate_cleanup_obligation(self):
        cleanup=OSError('fixture duplicate cleanup failed')
        self.verifier.close=lambda:(_ for _ in ()).throw(cleanup)
        def fail(*args):raise AcquisitionError(ValueError('fixture acquire failed'),cleanup,self.verifier)
        self.record.verifier_factory=fail
        with self.assertRaises(AcquisitionError):await self.start()
        self.assertIs(self.record.verifier,self.verifier)
        self.proc.exitcode=0
        result=await self.record.join(timeout_s=1)
        self.assertTrue(result['child_exit_observed'] and result['pipe_threads_joined'])
        self.assertFalse(result['closed'] or result['verifier_handle_closed'])
        self.assertIn('verifier_close_unconfirmed',result['faults'])

    async def test_report_reader_timeout_remains_owned_until_actual_eof(self):
        entered,release=threading.Event(),threading.Event();self.releases.append(release)
        data=frame(candidate(self.bootstrap,100),REPORT_LIMIT)
        class Blocked(io.BytesIO):
            def read(self,count=-1):
                entered.set()
                if not release.wait(2):raise AssertionError('Fixture EOF was not released')
                return super().read(count)
        self.proc.stdout=Blocked(data)
        waiter=asyncio.create_task(self.start(timeout_s=.05))
        self.assertTrue(await asyncio.to_thread(entered.wait,1))
        with self.assertRaises(asyncio.TimeoutError):await waiter
        self.assertFalse(self.proc.stdout.closed)
        self.assertFalse((await self.record.join(timeout_s=.02))['pipe_threads_joined'])
        release.set();self.proc.exitcode=0
        result=await self.record.join(timeout_s=2)
        self.assertTrue(result['closed'])
        self.assertEqual(self.events,[])

    async def test_partial_session_bind_failure_requires_revocation_before_handle_close(self):
        def failed_bind(*args):self.events.append('partial-bind');raise RuntimeError('fixture binding failed')
        with self.assertRaises(RuntimeError):
            await self.record.start(self.spec,self.bootstrap,containing_job=99,launch_ready=lambda:True,
                bind_session=failed_bind,revoke_session=lambda sid:self.events.append('revoke'))
        self.proc.exitcode=0
        result=await self.record.join(timeout_s=1)
        self.assertTrue(result['closed'])
        self.assertEqual(self.events,['verify','partial-bind','revoke'])


class GUISessionTests(unittest.TestCase):
    def fixture(self):
        root,view=FakeRoot(),View()
        view.attach=lambda controller:None
        marker=RootMarker(root,'Adaptive.UI.session-1234',1234,api=MarkerAPI())
        class Handshake:
            accepted=False;error=None;ready=False
            def __init__(self,*args):pass
            def start(self):pass
            def joined(self):return self.ready
        workers=[]
        def worker(exchange):
            made=FakeWorker();workers.append(made);return made
        session=GUISession(root,view,bootstrap(),marker,io.BytesIO(),Output(),lambda r:None,
            handshake_factory=Handshake,worker_factory=worker)
        session.start()
        return session,root,view,workers

    def test_no_network_worker_or_readiness_before_parent_ack_join(self):
        session,root,view,workers=self.fixture()
        session.tick();self.assertEqual(workers,[])
        self.assertTrue(root.callbacks)
        session.handshake.accepted=True;session.handshake.ready=True
        session.tick()
        self.assertEqual(len(workers),1)
        self.assertEqual([r.method for r in workers[0].sent],['window_ready'])

    def test_early_close_retires_marker_and_waits_for_handshake_thread(self):
        session,root,view,workers=self.fixture()
        session.close();session.tick()
        self.assertTrue(session.marker.removed)
        self.assertFalse(view.destroyed)
        session.handshake.ready=True;session.tick()
        self.assertTrue(view.destroyed)
        self.assertEqual(workers,[])

    def test_failed_or_late_ack_never_activates_network(self):
        session,root,view,workers=self.fixture()
        session.handshake.ready=True;session.handshake.error='unconfirmed'
        session.tick()
        self.assertEqual(workers,[])
        self.assertTrue(session.closed)

    def test_post_ack_worker_initialization_failure_closes_with_visible_fault(self):
        session,root,view,workers=self.fixture()
        session.handshake.ready=session.handshake.accepted=True
        session.worker_factory=lambda exchange:(_ for _ in ()).throw(RuntimeError('fixture worker init failed'))
        session.tick()
        self.assertTrue(session.closed and session.marker.removed)
        self.assertIn('client_activation_failed',session.faults)
        self.assertEqual(workers,[])

    def test_partial_view_attach_failure_retains_worker_until_join(self):
        session,root,view,workers=self.fixture()
        session.handshake.ready=session.handshake.accepted=True
        view.attach=lambda controller:(_ for _ in ()).throw(RuntimeError('fixture attach failed'))
        session.tick()
        self.assertIn('client_activation_failed',session.faults)
        self.assertTrue(session.closing and workers[0].closing and session.marker.removed)
        self.assertFalse(session.closed or view.destroyed)
        self.assertEqual(workers[0].sent,[])
        workers[0].is_joined=True
        session.tick()
        self.assertTrue(session.closed and view.destroyed)

    def test_validated_stop_requested_closes_presentation_without_waiting_host_final(self):
        worker,binding,view=FakeWorker(),Binding(),View()
        client=cc.ClientController(bootstrap(),worker,binding,view,close_on_stop_recorded=True)
        client.start();worker.respond({'ok':True,'state':'window_ready'});client.tick()
        client.poll_status();worker.respond(status());client.tick()
        client.action('stop');worker.respond({'ok':True,'state':'stop_requested',**life(stop_requested=True)});client.tick()
        self.assertTrue(client.closing and worker.closing and client.stop_recorded)
        self.assertFalse(client.closed)
        self.assertIn('unconfirmed',client.connection)
        self.assertNotIn('Engine stopped safely',client.action_text)
        worker.is_joined=True;client.tick()
        self.assertTrue(client.closed and view.destroyed)

    def test_lost_stop_response_does_not_manufacture_ack_or_close(self):
        worker,binding,view=FakeWorker(),Binding(),View()
        client=cc.ClientController(bootstrap(),worker,binding,view,close_on_stop_recorded=True)
        client.start();worker.respond({'ok':True,'state':'window_ready'});client.tick()
        client.poll_status();worker.respond(status());client.tick()
        client.action('stop');worker.respond(error='outcome_unconfirmed');client.tick()
        self.assertFalse(client.stop_recorded or client.closing)
        self.assertTrue(client.retry())


if __name__ == '__main__':
    unittest.main(verbosity=2)
