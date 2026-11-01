"""Actual owner definitions with deterministic Win32 boundaries; no OS children."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import test_owner_failure as old

if os.environ.get('NATIVE_OWNER_SOURCE'):
    old.HERE = Path(os.environ['NATIVE_OWNER_SOURCE'])


class Clock:
    def __init__(self):
        self.now = 100.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class TerminationRaceTests(unittest.TestCase):
    def setUp(self):
        self.ns = old.ownership_namespace()
        self.clock = Clock()
        self.ns['time'] = self.clock
        self.patches = [
            mock.patch.object(ctypes, 'get_last_error', return_value=5, create=True),
            mock.patch.object(ctypes, 'WinError', side_effect=old.denied, create=True),
        ]
        self.last_error, self.win_error = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def handle(self, *, pid=42, signalled=False, delay_ms=10, code=5,
               wait_failure=None, terminate_success=False):
        h = self.ns['ProcessHandle'].__new__(self.ns['ProcessHandle'])
        h.pid, h.handle, h.access_mask = pid, 9000+pid, 0x101001
        h.record = {'pid': pid, 'created_filetime': 123+pid, 'exe': 'fixture.exe'}
        state = types.SimpleNamespace(signalled=signalled, waits=[], closed=[], attempts=[])
        def wait(handle, ms):
            self.assertEqual(handle, 9000+pid)
            state.waits.append(ms)
            if state.signalled:
                return 0
            if ms and wait_failure is not None:
                self.last_error.return_value = 6
                return wait_failure
            if ms and delay_ms is not None and ms >= delay_ms:
                self.clock.now += delay_ms/1000
                state.signalled = True
                return 0
            self.clock.now += ms/1000
            return 258
        def terminate(handle, exit_code):
            state.attempts.append((handle, exit_code))
            self.last_error.return_value = code
            return int(terminate_success)
        def close(handle):
            state.closed.append(handle)
            return 1
        h.k = types.SimpleNamespace(WaitForSingleObject=wait,
            TerminateProcess=terminate, CloseHandle=close)
        return h, state

    def test_already_signalled_needs_no_termination(self):
        h, s = self.handle(signalled=True)
        h.terminate(deadline=112)
        self.assertEqual(s.waits, [0])
        self.assertEqual(s.attempts, [])

    def test_denied_late_exit_uses_exact_handle_bounded_wait(self):
        h, s = self.handle()
        h.terminate(deadline=112)
        self.assertEqual(s.waits, [0, 50])
        self.assertEqual(s.attempts, [(9042, 125)])
        self.assertAlmostEqual(self.clock.now, 100.01)
        self.assertEqual(s.closed, [])
        self.ns['psutil'].pid_exists.assert_not_called()

    def test_live_denial_preserves_api_error_and_retained_handle(self):
        h, s = self.handle(delay_ms=None)
        with self.assertRaises(PermissionError) as caught:
            h.terminate(deadline=112)
        self.assertEqual((caught.exception.operation, caught.exception.winerror,
            caught.exception.pid, caught.exception.access_mask),
            ('TerminateProcess', 5, 42, 0x101001))
        self.assertEqual(s.waits, [0, 50])
        self.assertEqual(h.handle, 9042)
        self.assertEqual(s.closed, [])

    def test_failed_and_unexpected_wait_keep_original_termination_error(self):
        for result in (0xffffffff, 128):
            with self.subTest(result=result):
                h, s = self.handle(wait_failure=result)
                with self.assertRaises(PermissionError) as caught:
                    h.terminate(deadline=112)
                self.assertEqual((caught.exception.operation, caught.exception.winerror),
                    ('TerminateProcess', 5))
                self.assertIn('Same-handle exit check failed', caught.exception.__notes__[-1])
                self.assertEqual(s.closed, [])

    def test_non_access_error_is_not_swallowed(self):
        h, s = self.handle(code=6)
        with self.assertRaises(PermissionError) as caught:
            h.terminate(deadline=112)
        self.assertEqual(caught.exception.winerror, 6)
        self.assertEqual(s.waits, [0])

    def test_wait_cannot_exceed_remaining_cleanup_budget(self):
        h, s = self.handle(delay_ms=None)
        with self.assertRaises(PermissionError):
            h.terminate(deadline=100.03125)
        self.assertEqual(s.waits, [0, 31])
        self.assertLessEqual(self.clock.now, 100.03125)

    def test_expired_budget_and_ordinary_call_never_add_wait(self):
        for args in ({'deadline': 99.0}, {}):
            with self.subTest(args=args):
                h, s = self.handle()
                with self.assertRaises(PermissionError):
                    h.terminate(**args)
                self.assertEqual(s.waits, [0, 0])
                self.assertEqual(self.clock.now, 100.0)

    def test_successful_terminate_still_needs_later_collection(self):
        h, s = self.handle(terminate_success=True)
        h.terminate(deadline=112)
        self.assertEqual(s.waits, [0])
        self.assertFalse(s.signalled)

    def six_owned(self, live=False):
        pairs = [self.handle(pid=42+i, signalled=i<5,
                             delay_ms=None if live else 10) for i in range(6)]
        job = types.SimpleNamespace(active_process_ids=lambda: {os.getpid()} |
            {h.pid for h, s in pairs if not s.signalled})
        ids = self.ns['Identities'](job)
        ids.active = {(h.pid, h.record['created_filetime']): h for h, _ in pairs}
        ids.retained = 6
        return ids, pairs

    def test_cleanup_collects_full_six_exits_after_denied_late_exit(self):
        ids, pairs = self.six_owned()
        self.assertTrue(ids.cleanup())
        result = ids.snapshot()
        self.assertEqual((result['retained_total'], result['confirmed_exits']), (6, 6))
        self.assertEqual(result['active'], [])
        self.assertEqual(len(result['completed_tail']), 6)
        self.assertEqual([len(s.closed) for _, s in pairs], [1]*6)
        self.assertLess(self.clock.now, 112)

    def test_owner_receipt_requires_full_accounting_and_live_denial_stays_failed(self):
        for live in (False, True):
            with self.subTest(live=live), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root/'state').mkdir()
                (root/'run').mkdir()
                ns = old.owner_namespace(root)
                owner = ns['Owner'](root/'run', {'owner_id': 'fixture', 'max_runtime_seconds': 60})
                ids, pairs = self.six_owned(live)
                owner.identities = ids
                owner.child = mock.Mock(returncode=0)
                owner.child.poll.return_value = 0
                owner.memory = mock.Mock()
                owner.memory.close.return_value = {'error': None}
                owner.listener = mock.Mock()
                self.assertEqual(owner.finish(), int(live))
                result = json.loads((root/'run/result.json').read_text())
                self.assertEqual(result['cleanup_confirmed'], not live)
                self.assertEqual(result['processes']['confirmed_exits'], 5 if live else 6)
                self.assertEqual(result['state'], 'failed' if live else 'stopped')
                self.assertEqual(result['running'], None if live else False)
                if live:
                    self.assertEqual(result['cleanup_errors'][0]['operation'], 'TerminateProcess')
                    self.assertEqual(result['cleanup_errors'][0]['winerror'], 5)
                owner.child.wait.assert_called_once_with(timeout=2)
                owner.listener.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
