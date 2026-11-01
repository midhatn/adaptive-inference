"""Bounded CPU-fixture readiness observation, not product recovery behavior."""
import asyncio
import ast
import ctypes
from ctypes import wintypes
import json
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_continuation_host import wait_original_ready
import continuation_diagnostics_lineage as diagnostics
from paused_expiry_lineage import fingerprint
from task_file_alias_lineage import continuation_observation_predecessor


class ReadinessLineageTests(unittest.TestCase):
    def test_support_readers_restore_original_assertions_and_reject_unknown_edits(self):
        root=diagnostics.ROOT
        rows=json.loads((root/diagnostics.READINESS/'support-source-lineage.json').read_bytes())
        self.assertEqual(set(rows['files']),{'tests/test_continuation_diagnostics_lineage.py',
            'tests/test_pause_observation_lineage.py','tests/test_safe_wait_lineage.py'})
        self.assertEqual(rows['runtime_changes'],[])
        for relative,row in rows['files'].items():
            with self.subTest(relative=relative):
                current=continuation_observation_predecessor(relative, (root/relative).read_bytes(), root=root)
                before=(root/row['predecessor_source']).read_bytes()
                self.assertEqual(diagnostics.readiness_support_predecessor(relative,current),before)
                self.assertEqual(diagnostics.readiness_support_predecessor(relative,before),before)
                for rule in reversed(row['replacements']):
                    new=rule['new'].encode();old=rule['old'].encode()
                    self.assertEqual(current.count(new),rule['count'])
                    current=current.replace(new,old)
                self.assertEqual(current,before)
                with self.assertRaisesRegex(AssertionError,'complete readiness support source'):
                    diagnostics.readiness_support_predecessor(relative,current+b'\n# unreviewed\n')

    def test_only_readiness_observation_changed_and_old_fixture_is_exact(self):
        root=diagnostics.ROOT
        row=json.loads((root/diagnostics.READINESS/'source-lineage.json').read_bytes())
        current=(root/diagnostics.FIXTURE).read_bytes()
        old=diagnostics.readiness_predecessor(current)
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         '9aba2b541f1b08bca5a07fe3283d887bd53d01e4d48ae2679986aa5a20a1504d')
        self.assertEqual(hashlib.sha256(current).hexdigest(),row['successor_sha256'])
        self.assertEqual(row['runtime_changes'],[])
        tree=ast.parse(current);before=ast.parse(old)
        method=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)
                    and n.name=='wait_original_ready')
        prior=next(n for n in before.body if isinstance(n,ast.AsyncFunctionDef)
                   and n.name=='wait_original_ready')
        self.assertEqual(fingerprint(method),row['changed_helper_ast_sha256'])
        tree.body[tree.body.index(method)]=prior
        self.assertEqual(fingerprint(tree),fingerprint(before))

    def test_unreviewed_readiness_and_historical_source_mutations_are_refused(self):
        root=diagnostics.ROOT;current=(root/diagnostics.FIXTURE).read_bytes()
        for changed in (current+b'\n# unreviewed\n',
                        current.replace(b'timeout_s=30',b'timeout_s=31',1)):
            with self.assertRaisesRegex(AssertionError,'complete CI diagnostic fixture'):
                diagnostics.predecessor(changed)
        with tempfile.TemporaryDirectory() as directory:
            scratch=Path(directory);archive=scratch/diagnostics.READINESS
            archive.mkdir(parents=True)
            for name in ('source-lineage.json','predecessor-test_continuation_host.py'):
                (archive/name).write_bytes((root/diagnostics.READINESS/name).read_bytes())
            old=archive/'predecessor-test_continuation_host.py'
            old.write_bytes(old.read_bytes()+b'\n# unreviewed\n')
            with self.assertRaisesRegex(AssertionError,'readiness predecessor'):
                diagnostics.readiness_predecessor(current,scratch)


class ReadinessObservationTests(unittest.TestCase):
    def child(self):
        return SimpleNamespace(pid=123,poll=mock.Mock(return_value=None))

    def test_transient_open_conflicts_observe_same_child(self):
        for error in (PermissionError(13,'sharing'),FileNotFoundError(2,'publication')):
            with self.subTest(error=type(error).__name__):
                child=self.child();path=mock.Mock()
                path.read_text.side_effect=[error,json.dumps({'pid':123,'work_guard_s':15})]
                with mock.patch.object(asyncio,'sleep',new_callable=mock.AsyncMock) as slept:
                    asyncio.run(wait_original_ready(child,path,clock=mock.Mock(side_effect=[0.,1.])))
                self.assertEqual(path.read_text.call_count,2)
                child.poll.assert_called_once_with();slept.assert_awaited_once_with(.01)

    def test_persistent_denial_does_not_extend_startup_deadline(self):
        child=self.child();path=mock.Mock();path.read_text.side_effect=PermissionError(13,'persistent')
        clock=mock.Mock(side_effect=[0.,29.,30.])
        with mock.patch.object(asyncio,'sleep',new_callable=mock.AsyncMock) as slept:
            with self.assertRaisesRegex(TimeoutError,'startup deadline'):
                asyncio.run(wait_original_ready(child,path,clock=clock))
        self.assertEqual(path.read_text.call_count,2);self.assertEqual(child.poll.call_count,2)
        slept.assert_awaited_once_with(.01)

    def test_denied_marker_does_not_hide_original_child_exit(self):
        child=self.child();child.poll.return_value=124;child.returncode=124
        path=mock.Mock();path.read_text.side_effect=PermissionError(13,'sharing')
        with mock.patch.object(asyncio,'sleep',new_callable=mock.AsyncMock) as slept:
            with self.assertRaisesRegex(AssertionError,'before readiness: 124'):
                asyncio.run(wait_original_ready(child,path))
        slept.assert_not_awaited();self.assertEqual(path.read_text.call_count,1)

    def test_content_and_other_io_failures_are_not_retried(self):
        values=[('not json',json.JSONDecodeError),
                (json.dumps({'pid':999,'work_guard_s':15}),AssertionError),
                (json.dumps({'pid':123,'work_guard_s':16}),AssertionError),
                (OSError(5,'unrelated IO'),OSError)]
        for value,error in values:
            with self.subTest(value=str(value)):
                child=self.child();path=mock.Mock()
                if isinstance(value,Exception):path.read_text.side_effect=value
                else:path.read_text.return_value=value
                with mock.patch.object(asyncio,'sleep',new_callable=mock.AsyncMock) as slept:
                    with self.assertRaises(error):asyncio.run(wait_original_ready(child,path))
                slept.assert_not_awaited();child.poll.assert_not_called()
                self.assertEqual(path.read_text.call_count,1)

    @unittest.skipUnless(os.name=='nt','Windows file sharing observation')
    def test_actual_windows_share_denial_then_readable_marker(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                         ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ready.json'
            path.write_text(json.dumps({'pid':123,'work_guard_s':15}),encoding='utf-8')
            handle=create(str(path),0x80000000,0,None,3,0,None)
            if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            async def release(_):
                nonlocal handle
                if not close(handle):raise ctypes.WinError(ctypes.get_last_error())
                handle=None
            try:
                with self.assertRaises(PermissionError):path.read_text(encoding='utf-8')
                with mock.patch.object(asyncio,'sleep',side_effect=release) as slept:
                    asyncio.run(wait_original_ready(self.child(),path,
                                                   clock=mock.Mock(side_effect=[0.,1.])))
                slept.assert_awaited_once_with(.01)
            finally:
                if handle is not None:close(handle)


if __name__=='__main__':unittest.main()
