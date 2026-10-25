"""Bounded real Python-thread bootstrap race; no GUI/native/process/socket."""
from pathlib import Path
import io
import sys
import threading
import unittest
from unittest import mock

PACKET = Path(__file__).resolve().parent
from adaptive_inference.desktop.startup_pipe import ChildHandshake, ready_ack
from test_desktop_owned_launch import Output, bootstrap


class AmbiguousStartTests(unittest.TestCase):
    def test_ident_before_thread_started_event_is_still_unresolved(self):
        b = bootstrap()
        stdin, stdout = io.BytesIO(ready_ack(b)), Output()
        handshake = ChildHandshake(b, 100, stdin, stdout)
        original_start = handshake._thread.start
        with mock.patch.object(handshake._thread, 'start', side_effect=KeyboardInterrupt('fixture interrupted start')):
            with self.assertRaises(KeyboardInterrupt):
                handshake.start()
        entered, release = threading.Event(), threading.Event()
        original_state_lock = handshake._thread._set_tstate_lock
        def pause_bootstrap():
            original_state_lock()
            entered.set()
            if not release.wait(2):
                raise AssertionError('Bounded bootstrap gate was not released')
        # CPython sets ident, then its state lock, then _started. Pause the actual
        # fixture thread between these documented-in-pinned-source operations.
        with mock.patch.object(handshake._thread, '_set_tstate_lock', side_effect=pause_bootstrap):
            launcher = threading.Thread(target=original_start, daemon=False)
            launcher.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertIsNotNone(handshake._thread.ident)
                self.assertFalse(handshake._thread.is_alive())
                self.assertFalse(handshake.joined())
                self.assertFalse(stdin.closed or stdout.closed)
            finally:
                release.set()
                launcher.join(2)
                handshake._thread.join(2)
                self.assertFalse(launcher.is_alive() or handshake._thread.is_alive())
        self.assertTrue(handshake.joined())
        self.assertFalse(handshake.accepted)


if __name__ == '__main__':
    unittest.main(verbosity=2)
