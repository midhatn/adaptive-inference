"""Regressions for independently reproduced startup failures; no real GUI/process."""
import asyncio
import io
import threading
import time
import unittest
from unittest import mock

import test_desktop_owned_launch as fixtures
from adaptive_inference.desktop.gui_session import GUISession
from adaptive_inference.desktop.startup_pipe import ChildHandshake, StartupError, ready_ack
from adaptive_inference.desktop.window_marker import RootMarker


class HandshakeAcquisitionTests(unittest.TestCase):
    def test_never_started_thread_preserves_failure_closes_pipes_and_destroys_view(self):
        root, view = fixtures.FakeRoot(), fixtures.View()
        marker = RootMarker(root, 'Adaptive.UI.session-1234', 1234, api=fixtures.MarkerAPI())
        failure = RuntimeError('fixture cannot start new thread')
        stdin, stdout = io.BytesIO(), fixtures.Output()
        def failing_handshake(*args):
            handshake = ChildHandshake(*args)
            handshake._thread.start = mock.Mock(side_effect=failure)
            return handshake
        session = GUISession(root, view, fixtures.bootstrap(), marker, stdin, stdout,
            lambda request: self.fail('No network is allowed'), handshake_factory=failing_handshake)
        with self.assertRaises(RuntimeError) as caught:
            session.start()
        self.assertIs(caught.exception, failure)
        self.assertIs(session.handshake.start_error, failure)
        self.assertTrue(session.marker.removed and stdin.closed and stdout.closed)
        self.assertFalse(session.handshake._thread.is_alive() or session.handshake.accepted)
        self.assertTrue(session.handshake.joined())
        self.assertFalse(session.after_mainloop())
        self.assertTrue(view.destroyed)
        with self.assertRaises(StartupError):session.handshake.start()

    def test_never_started_failure_attempts_both_pipe_closes_and_retains_each_error(self):
        failures={'stdin':OSError('input close'), 'stdout':OSError('output close')}
        attempts=[]
        class Broken:
            def __init__(self,name):self.name=name
            def close(self):attempts.append(self.name);raise failures[self.name]
        handshake=ChildHandshake(fixtures.bootstrap(),100,Broken('stdin'),Broken('stdout'))
        failure=RuntimeError('fixture thread creation failed')
        with mock.patch.object(handshake._thread,'start',side_effect=failure):
            with self.assertRaises(RuntimeError) as caught:handshake.start()
        self.assertIs(caught.exception,failure)
        self.assertIs(handshake.primary_error,failure)
        self.assertEqual(attempts,['stdout','stdin'])
        self.assertEqual(handshake.cleanup_errors,failures)
        self.assertTrue(handshake.joined())
        self.assertFalse(handshake.accepted)
        self.assertEqual(handshake.error,'startup_thread_start_unconfirmed')
        with self.assertRaises(StartupError):handshake.start()
        self.assertEqual(attempts,['stdout','stdin'])

    def test_start_then_raise_preserves_running_thread_and_does_not_close_its_input(self):
        entered,release=threading.Event(),threading.Event()
        b=fixtures.bootstrap()
        class Blocked(io.BytesIO):
            def readline(self,*args):
                entered.set()
                if not release.wait(2):raise AssertionError('Bounded input fixture not released')
                return super().readline(*args)
        stdin=Blocked(ready_ack(b));stdout=fixtures.Output()
        handshake=ChildHandshake(b,100,stdin,stdout)
        actual_start=handshake._thread.start
        failure=RuntimeError('fixture exception after successful acquisition')
        def start_then_fail():actual_start();raise failure
        try:
            with mock.patch.object(handshake._thread,'start',side_effect=start_then_fail):
                with self.assertRaises(RuntimeError):handshake.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(handshake.joined() or stdin.closed or handshake._never_started)
            self.assertIs(handshake.start_error,failure)
        finally:
            release.set()
            handshake._thread.join(timeout=2)
        self.assertTrue(handshake.joined() and stdin.closed)
        self.assertFalse(handshake.accepted)

    def test_ambiguous_start_keeps_obligation_until_late_thread_is_observed_and_joined(self):
        b=fixtures.bootstrap();stdin=io.BytesIO(ready_ack(b));stdout=fixtures.Output()
        handshake=ChildHandshake(b,100,stdin,stdout)
        actual_start=handshake._thread.start
        failure=KeyboardInterrupt('fixture interrupted acquisition')
        with mock.patch.object(handshake._thread,'start',side_effect=failure):
            with self.assertRaises(KeyboardInterrupt):handshake.start()
        self.assertFalse(handshake.joined() or stdin.closed or stdout.closed)
        self.assertIs(handshake.start_error,failure)
        # Simulate late completion of the interrupted acquisition, not a new
        # handshake start. The public one-attempt API continues to refuse reuse.
        with self.assertRaises(StartupError):handshake.start()
        actual_start()
        handshake._thread.join(timeout=2)
        self.assertTrue(handshake.joined() and stdin.closed and stdout.closed)
        self.assertFalse(handshake.accepted)


class LaunchFenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.LaunchTests.asyncSetUp
    asyncTearDown=fixtures.LaunchTests.asyncTearDown
    bind=fixtures.LaunchTests.bind
    start=fixtures.LaunchTests.start

    async def test_reentrant_abort_during_bind_never_sends_ack_or_overwrites_close(self):
        retained=[]
        def bind(binding,verifier,bootstrap):
            self.record.abort_startup()
            retained.append(self.record._input_close)
            return True
        with self.assertRaises(StartupError):
            await self.record.start(self.spec,self.bootstrap,containing_job=99,
                launch_ready=lambda:True,bind_session=bind,
                revoke_session=lambda session:self.events.append('revoke'))
        self.assertNotIn(b'"ready":true',self.proc.stdin.data)
        self.assertIs(self.record._input_close,retained[0])
        self.assertFalse(self.record.session_live(self.bootstrap.session_id))
        self.proc.exitcode=0
        receipt=await self.record.join(timeout_s=1)
        self.assertTrue(receipt['closed'] and receipt['session_revoked'])
        self.assertIn('startup_failed',receipt['faults'])
        self.assertEqual(self.proc.stdin.close_calls,1)

    async def test_cancelled_waiter_during_ack_keeps_io_until_actual_completion(self):
        entered,release=threading.Event(),threading.Event()
        self.releases.append(release)
        class AckOutput(fixtures.Output):
            def write(stream,data):
                if b'"ready":true' in data:
                    entered.set()
                    if not release.wait(2):raise AssertionError('Bounded ACK fixture not released')
                return super().write(data)
        self.proc.stdin=AckOutput()
        pending=asyncio.create_task(self.start())
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,1))
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):await pending
            receipt=await self.record.join(timeout_s=.03)
            self.assertFalse(receipt['closed'] or receipt['child_exit_observed'])
            self.assertGreater(receipt['pending_pipe_operations'],0)
        finally:
            release.set()
        self.proc.exitcode=0
        receipt=await self.record.join(timeout_s=1)
        self.assertTrue(receipt['closed'] and receipt['startup_aborted'] and receipt['child_exit_observed'])
        self.assertIn('startup_failed',receipt['faults'])


if __name__=='__main__':unittest.main(verbosity=2)
