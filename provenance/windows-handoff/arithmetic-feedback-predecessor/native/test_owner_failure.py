"""Portable CPU-only failure injection against actual owner definitions.

Load the real AST definitions without importing installation-only provenance,
Strata or Windows resources. No implementation is copied into the fixtures.
"""
import ast
import ctypes
from ctypes import wintypes
from collections import deque
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types
import unittest
from unittest import mock
import uuid

HERE=Path(__file__).resolve().parent/'owner_source'


def definitions(filename,names,namespace):
    path=HERE/filename
    source=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    selected=[node for node in source.body if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in names]
    if {node.name for node in selected}!=set(names):
        raise AssertionError('Expected actual source definitions are missing')
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def denied(code=5):
    error=PermissionError(errno.EACCES,'injected Windows denial')
    error.winerror=code
    return error


class NativeFunction:
    def __init__(self,result):
        self.result=result
        self.calls=[]
    def __call__(self,*args):
        self.calls.append(args)
        return self.result


def owner_namespace(root):
    return definitions('engine.py',('Owner','exception_diagnostic','save'),{
        'Path':Path,'ROOT':root,'json':json,'uuid':uuid,'os':os,'time':time,
        'traceback':traceback,'sys':sys,'subprocess':subprocess,
        'threading':types.SimpleNamespace(Event=threading.Event,RLock=threading.RLock,Thread=mock.Mock()),
        'lock':mock.Mock(return_value=object()),'unlock':mock.Mock(),
        'owned_job':types.SimpleNamespace(contain_current_process=mock.Mock()),
        'ProcessHandle':mock.Mock(return_value=types.SimpleNamespace(record={'pid':101},close=mock.Mock())),
        'verify':mock.Mock(return_value={'verified':True}),
    })


def ownership_namespace():
    return definitions('ownership.py',('win_error','ProcessHandle','Identities'),{
        'C':ctypes,'W':wintypes,'threading':threading,'deque':deque,'os':os,'time':time,
        'psutil':types.SimpleNamespace(pid_exists=mock.Mock(return_value=True)),
    })


class ProcessFailureTests(unittest.TestCase):
    def test_windows_error_keeps_code_type_and_context(self):
        ns=ownership_namespace()
        with mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
            error=ns['win_error']('OpenProcess',42,0x101001,5)
        self.assertIsInstance(error,PermissionError)
        self.assertEqual((error.winerror,error.operation,error.pid,error.access_mask),(5,'OpenProcess',42,0x101001))
        self.assertIn('operation=OpenProcess',error.__notes__[0])

    def test_open_failure_preserves_required_rights_and_native_code(self):
        ns=ownership_namespace()
        functions={name:NativeFunction(0) for name in ('OpenProcess','GetProcessTimes','QueryFullProcessImageNameW',
            'WaitForSingleObject','TerminateProcess','IsProcessInJob','CloseHandle')}
        with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
             mock.patch.object(ctypes,'get_last_error',return_value=5,create=True), \
             mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
            with self.assertRaises(PermissionError) as caught:
                ns['ProcessHandle'](42)
        self.assertEqual(functions['OpenProcess'].calls,[(0x101001,False,42)])
        self.assertEqual(caught.exception.operation,'OpenProcess')
        self.assertEqual(caught.exception.winerror,5)

    def test_metadata_failure_records_stage_and_closes_opened_handle(self):
        ns=ownership_namespace()
        functions={name:NativeFunction(0) for name in ('OpenProcess','GetProcessTimes','QueryFullProcessImageNameW',
            'WaitForSingleObject','TerminateProcess','IsProcessInJob','CloseHandle')}
        functions['OpenProcess'].result=987
        with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
             mock.patch.object(ctypes,'get_last_error',return_value=5,create=True), \
             mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
            with self.assertRaises(PermissionError) as caught:
                ns['ProcessHandle'](42)
        self.assertEqual(caught.exception.operation,'GetProcessTimes')
        self.assertEqual(functions['CloseHandle'].calls,[(987,)])

    def test_cleanup_collection_error_still_attempts_each_verified_handle(self):
        ns=ownership_namespace()
        job=types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42,43})
        identities=ns['Identities'](job)
        primary=denied()
        identities.collect=mock.Mock(side_effect=primary)
        first=types.SimpleNamespace(terminate=mock.Mock(side_effect=RuntimeError('termination failed')))
        second=types.SimpleNamespace(terminate=mock.Mock())
        identities.active={(42,1):first,(43,2):second}
        with self.assertRaises(PermissionError) as caught:
            identities.cleanup()
        self.assertIs(caught.exception,primary)
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        self.assertEqual(identities.confirmed_exits,0)
        self.assertEqual(len(identities.active),2)

    def image_failure_kernel(self, wait_result):
        functions={name:NativeFunction(0) for name in ('OpenProcess','GetProcessTimes','QueryFullProcessImageNameW',
            'WaitForSingleObject','TerminateProcess','IsProcessInJob','CloseHandle')}
        functions['OpenProcess'].result=987
        functions['GetProcessTimes'].result=1
        functions['WaitForSingleObject'].result=wait_result
        functions['CloseHandle'].result=1
        return functions

    def test_image_failure_skipped_only_after_same_handle_signal_without_owned_exit_count(self):
        for code in (5,31):
            with self.subTest(code=code):
                ns=ownership_namespace(); functions=self.image_failure_kernel(0)
                identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
                with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
                     mock.patch.object(ctypes,'get_last_error',return_value=code,create=True), \
                     mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
                    identities.collect()
                self.assertEqual(functions['WaitForSingleObject'].calls,[(987,50)])
                self.assertEqual(functions['CloseHandle'].calls,[(987,)])
                self.assertEqual(functions['TerminateProcess'].calls,[])
                self.assertEqual(functions['IsProcessInJob'].calls,[])
                ns['psutil'].pid_exists.assert_not_called()
                snapshot=identities.snapshot()
                self.assertEqual((snapshot['retained_total'],snapshot['confirmed_exits']),(0,0))
                self.assertEqual(snapshot['active'],[])
                self.assertEqual(snapshot['exited_during_identity_capture'],1)
                self.assertEqual(snapshot['capture_exit_tail'],[{'pid':42,'operation':'QueryFullProcessImageNameW',
                    'winerror':code,'same_handle_exit_confirmed':True,'wait_bound_ms':50,'ownership_verified':False}])

    def test_image_denial_for_live_handle_still_fails_after_bounded_wait(self):
        ns=ownership_namespace(); functions=self.image_failure_kernel(258)
        identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
        with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
             mock.patch.object(ctypes,'get_last_error',return_value=5,create=True), \
             mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
            with self.assertRaises(PermissionError) as caught: identities.collect()
        self.assertEqual(caught.exception.operation,'QueryFullProcessImageNameW')
        self.assertEqual(caught.exception.winerror,5)
        self.assertFalse(caught.exception.capture_exit_confirmed)
        self.assertEqual(functions['WaitForSingleObject'].calls,[(987,50)])
        self.assertEqual(functions['CloseHandle'].calls,[(987,)])
        self.assertEqual(identities.capture_exits,0)
        ns['psutil'].pid_exists.assert_not_called()

    def test_failed_or_unexpected_wait_retains_original_image_error(self):
        for wait_result in (0xffffffff,128):
            with self.subTest(wait_result=wait_result):
                ns=ownership_namespace(); functions=self.image_failure_kernel(wait_result)
                identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
                with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
                     mock.patch.object(ctypes,'get_last_error',side_effect=[5,6],create=True), \
                     mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
                    with self.assertRaises(PermissionError) as caught: identities.collect()
                self.assertEqual((caught.exception.operation,caught.exception.winerror),('QueryFullProcessImageNameW',5))
                self.assertIn('Same-handle exit check failed',caught.exception.__notes__[-1])
                self.assertFalse(getattr(caught.exception,'capture_exit_confirmed',False))
                self.assertEqual(functions['CloseHandle'].calls,[(987,)])
                self.assertEqual(identities.capture_exits,0)

    def test_strict_identity_capture_still_raises_even_with_confirmed_exit(self):
        ns=ownership_namespace(); functions=self.image_failure_kernel(0)
        with mock.patch.object(ctypes,'WinDLL',return_value=types.SimpleNamespace(**functions),create=True), \
             mock.patch.object(ctypes,'get_last_error',return_value=5,create=True), \
             mock.patch.object(ctypes,'WinError',side_effect=denied,create=True):
            with self.assertRaises(PermissionError) as caught:
                ns['ProcessHandle'](42,expected={'created_filetime':1,'exe':'expected.exe'})
        self.assertTrue(caught.exception.capture_exit_confirmed)
        self.assertEqual(functions['CloseHandle'].calls,[(987,)])

    def test_denied_acquisition_remains_error_even_if_pid_is_absent(self):
        ns=ownership_namespace()
        error=denied(); error.operation='OpenProcess'
        ns['ProcessHandle']=mock.Mock(side_effect=error)
        ns['psutil'].pid_exists.return_value=False
        identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
        with self.assertRaises(PermissionError) as caught:
            identities.collect()
        self.assertIs(caught.exception,error)
        ns['psutil'].pid_exists.assert_not_called()
        self.assertEqual((identities.retained,identities.confirmed_exits),(0,0))
        self.assertEqual(identities.active,{})

    def test_missing_openprocess_race_requires_independent_absence(self):
        for present in (True,False):
            with self.subTest(present=present):
                ns=ownership_namespace()
                error=OSError('injected missing PID'); error.winerror=87; error.operation='OpenProcess'
                ns['ProcessHandle']=mock.Mock(side_effect=error)
                ns['psutil'].pid_exists.return_value=present
                identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
                if present:
                    with self.assertRaises(OSError) as caught: identities.collect()
                    self.assertIs(caught.exception,error)
                else:
                    identities.collect()
                ns['psutil'].pid_exists.assert_called_once_with(42)
                self.assertEqual((identities.retained,identities.confirmed_exits),(0,0))
                self.assertEqual(identities.active,{})

    def test_other_api_failures_are_not_missing_pid_proof(self):
        for operation,code in (('GetProcessTimes',87),('QueryFullProcessImageNameW',87),
                               ('IsProcessInJob',5),('OpenProcess',6),('OpenProcess',0)):
            with self.subTest(operation=operation,code=code):
                ns=ownership_namespace()
                error=OSError('injected API failure'); error.winerror=code; error.operation=operation
                ns['ProcessHandle']=mock.Mock(side_effect=error)
                ns['psutil'].pid_exists.return_value=False
                identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
                with self.assertRaises(OSError) as caught: identities.collect()
                self.assertIs(caught.exception,error)
                ns['psutil'].pid_exists.assert_not_called()
                self.assertEqual((identities.retained,identities.confirmed_exits),(0,0))

    def test_absence_probe_failure_retains_original_acquisition_error(self):
        ns=ownership_namespace()
        error=OSError('injected missing PID'); error.winerror=87; error.operation='OpenProcess'
        ns['ProcessHandle']=mock.Mock(side_effect=error)
        ns['psutil'].pid_exists.side_effect=RuntimeError('absence unavailable')
        identities=ns['Identities'](types.SimpleNamespace(active_process_ids=lambda:{os.getpid(),42}))
        with self.assertRaises(OSError) as caught: identities.collect()
        self.assertIs(caught.exception,error)
        self.assertIn('absence unavailable',error.__notes__[0])
        self.assertEqual((identities.retained,identities.confirmed_exits),(0,0))

    def test_close_failure_does_not_skip_other_retained_handles(self):
        ns=ownership_namespace()
        identities=ns['Identities'](object())
        first=types.SimpleNamespace(close=mock.Mock(side_effect=RuntimeError('close failed')))
        second=types.SimpleNamespace(close=mock.Mock())
        identities.active={(42,1):first,(43,2):second}
        with self.assertRaisesRegex(RuntimeError,'close failed'):
            identities.close()
        first.close.assert_called_once(); second.close.assert_called_once()
        self.assertEqual(list(identities.active),[(42,1)])
        self.assertEqual(identities.confirmed_exits,0)


class OwnerFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'state').mkdir()
        self.run=self.root/'run'; self.run.mkdir()
        self.ns=owner_namespace(self.root)
        self.owner=self.ns['Owner'](self.run,{'owner_id':'fixture-owner','max_runtime_seconds':60})
        self.ids=mock.Mock()
        self.ids.cleanup.return_value=True
        self.ids.snapshot.return_value={'retained_total':1,'confirmed_exits':1,'active':[],'completed_tail':[]}
        self.owner.identities=self.ids
        self.owner.child=mock.Mock(returncode=0)
        self.owner.child.poll.return_value=0
        self.owner.memory=mock.Mock()
        self.owner.memory.close.return_value={'error':None}
        self.owner.listener=mock.Mock()

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self):
        return json.loads((self.run/'result.json').read_text())

    def test_primary_and_cleanup_tracebacks_survive_complete_failure(self):
        primary=denied()
        primary.operation='OpenProcess'; primary.pid=42; primary.access_mask=0x101001
        self.ids.collect.side_effect=primary
        self.ids.cleanup.side_effect=RuntimeError('cleanup collection failed')
        self.ids.snapshot.side_effect=RuntimeError('snapshot failed')
        self.ns['Identities']=mock.Mock(return_value=self.ids)
        self.owner.start_control=mock.Mock()
        self.owner.launch=mock.Mock()
        with mock.patch.object(sys,'stderr',new_callable=io.StringIO) as log:
            self.assertEqual(self.owner.run_owner(),1)
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'failed')
        self.assertIsNone(receipt['running'])
        self.assertFalse(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['error'],str(primary))
        self.assertEqual(receipt['error_diagnostic']['winerror'],5)
        self.assertEqual(receipt['error_diagnostic']['pid'],42)
        self.assertIn('run_owner',receipt['error_diagnostic']['traceback'])
        self.assertIn('PermissionError',log.getvalue())
        self.assertEqual(receipt['cleanup_error'],'cleanup collection failed')
        self.assertEqual([row['stage'] for row in receipt['cleanup_errors']],['cleanup_owned_processes','snapshot_owned_processes'])
        self.assertIsNone(receipt['processes'])
        self.assertFalse(receipt['process_snapshot_available'])
        self.owner.child.stdin.close.assert_called_once()
        self.owner.child.wait.assert_called_once_with(timeout=2)
        self.owner.memory.close.assert_called_once()
        self.ids.close.assert_called_once()
        self.owner.listener.close.assert_called_once()
        self.assertTrue(self.owner.finished.is_set())
        self.assertTrue(self.owner.control_done.is_set())

    def test_drain_failure_does_not_skip_later_cleanup(self):
        self.owner.child.poll.return_value=None
        self.ids.collect.side_effect=RuntimeError('drain observation failed')
        self.assertEqual(self.owner.finish(),1)
        receipt=self.receipt()
        self.assertFalse(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['cleanup_errors'][0]['stage'],'drain_owned_server')
        self.ids.cleanup.assert_called_once()
        self.owner.memory.close.assert_called_once()
        self.assertEqual(receipt['processes']['confirmed_exits'],1)

    def test_unconfirmed_cleanup_never_claims_stopped(self):
        self.ids.cleanup.return_value=False
        self.assertEqual(self.owner.finish(),1)
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'failed')
        self.assertIsNone(receipt['running'])
        self.assertFalse(receipt['cleanup_confirmed'])

    def test_late_handle_close_failure_is_in_terminal_receipt(self):
        self.ids.close.side_effect=RuntimeError('handle close failed')
        self.assertEqual(self.owner.finish(),1)
        receipt=self.receipt()
        self.assertFalse(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['cleanup_errors'][0]['stage'],'close_retained_handles')
        self.owner.listener.close.assert_called_once()

    def test_successful_cleanup_keeps_actual_exit_evidence(self):
        self.assertEqual(self.owner.finish(),0)
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'stopped')
        self.assertFalse(receipt['running'])
        self.assertTrue(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['processes'],self.ids.snapshot.return_value)
        self.assertNotIn('cleanup_errors',receipt)

    def test_terminal_publication_failure_still_writes_failed_result(self):
        self.owner.publish=mock.Mock(side_effect=[None,OSError('owner publication failed')])
        self.assertEqual(self.owner.finish(),1)
        receipt=self.receipt()
        self.assertEqual(receipt['state'],'failed')
        self.assertIsNone(receipt['running'])
        self.assertFalse(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['cleanup_errors'][0]['stage'],'publish_terminal')

    def test_result_write_failure_republishes_uncertainty_without_losing_primary(self):
        original_save=self.ns['save']
        self.owner.state['error']='original operation failed'
        def fail_result(path,value):
            if Path(path).name=='result.json':
                raise OSError('result publication failed')
            return original_save(path,value)
        self.ns['save']=fail_result
        with mock.patch.object(sys,'stderr',new_callable=io.StringIO):
            self.assertEqual(self.owner.finish(),1)
        self.assertFalse((self.run/'result.json').exists())
        receipt=json.loads((self.run/'owner.json').read_text())
        self.assertEqual(receipt['error'],'original operation failed')
        self.assertEqual(receipt['state'],'failed')
        self.assertIsNone(receipt['running'])
        self.assertFalse(receipt['cleanup_confirmed'])
        self.assertEqual(receipt['cleanup_errors'][0]['stage'],'save_terminal_result')


if __name__=='__main__':
    unittest.main()
