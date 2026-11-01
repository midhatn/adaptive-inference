"""Actual bounded CPU children/SQLite/async host; injected native/window boundary.

No installed SDK/model/native engine/network service/real UI acceptance.
"""
import asyncio
from copy import deepcopy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.config import Config
from adaptive_inference.handoff import HandoffController,ToolRequirements
from adaptive_inference.scheduler import Scheduler
from adaptive_inference.desktop import composition as product
from adaptive_inference.desktop.desktop_controls import ControlledDesktopHost,DesktopControlLifecycle
from adaptive_inference.desktop.continuation_host import HostContinuation,SelectedWorkerStopBinding,selection
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.mailbox_runtime import RuntimeUnavailable
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority
from adaptive_inference.desktop.control_transport import PreparedTask,ControlTransport,Refused
from adaptive_inference.desktop.ui_intent import UIIntentGate,UIBinding,VerifiedUIObservation
from adaptive_inference.desktop.hermes import recovery as rec,run_recovery as worker
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_store import ReconciliationRequired
import test_continuation_worker as seed_fixture
import test_desktop_lifecycle as lifecycle_fixture
from test_desktop_control_transport import Reader,Writer
import continuation_timeout_diagnostics as timeout_diagnostics

CHILD=Path(__file__).with_name('continuation_cpu_child.py')


async def wait_original_ready(child,path,*,timeout_s=30,clock=time.monotonic):
    """Bound only this CPU fixture's import/startup; never retry its work."""
    deadline=clock()+timeout_s
    while True:
        try:
            readiness=path.read_text(encoding='utf-8')
        except (FileNotFoundError,PermissionError):
            # Publication/Windows sharing can briefly prevent observation.
            # The same child and original startup bound still govern the wait.
            pass
        else:
            if json.loads(readiness)!={'pid':child.pid,'work_guard_s':15}:
                raise AssertionError('CPU fixture readiness identity differs')
            return
        if child.poll() is not None:
            raise AssertionError(f'CPU fixture exited before readiness: {child.returncode}')
        if clock()>=deadline:raise TimeoutError('CPU fixture startup deadline exceeded')
        await asyncio.sleep(.01)


class Adapter:
    """Explicit native boundary fixture; status never represents a real engine."""
    def __init__(self):
        self._barrier=object();self._cold_start_error=self._startup_failure=self._released=None
        self.started_owner=False;self._cold_prepared=True;self.parked_observation={'fixture':True}
        self.driver=SimpleNamespace(status=lambda:{'running':False,'state':'stopped','ready':False,'loaded':False},
            owner_idle=lambda:True,port_free=lambda port:True)
    def _stopped_identity(self,state):
        if state.get('running') is not False:raise RuntimeError('Fixture owner not parked')
    async def _call(self,callback,*args):return await asyncio.to_thread(callback,*args)


@unittest.skipUnless(os.name == 'nt', 'Windows retained-process creation identity fixture')
class HostTests(unittest.IsolatedAsyncioTestCase):
    # Whole-fixture orchestration guard, not a product latency requirement.
    # Reuse CPython's short test timeout for real SQLite/filesystem/child work:
    # https://github.com/python/cpython/blob/v3.12.10/Lib/test/support/__init__.py
    continuation_timeout_s = 30

    async def asyncSetUp(self):
        self.seed=seed_fixture.SelectedWorkerTests();self.seed.setUp();self.seed.seed_report()
        self.addCleanup(self.seed.doCleanups)
        f=self.seed.f
        f.plan['base_python']=sys.executable
        (f.run/'plan.json').write_text(json.dumps(f.plan),encoding='utf-8')
        c=product.DesktopComposition.__new__(product.DesktopComposition);self.c=c
        c.work=f.run;c.root=f.run/'host';c.root.mkdir()
        c.handles=[];c.logs=[];c.waits={};c.result={};c.store=f.store;c.plan=f.plan
        self.child_receipts=[];self.patches=[]
        # unittest skips asyncTearDown when asyncSetUp fails. Register retained
        # process/stream cleanup before launch, ahead of the seed directory's
        # cleanup (LIFO), just as in test_task_store_verification.py.
        self.addCleanup(self.cleanup_retained)
        launch=c.launch
        def retained_launch(command,kind):
            before=len(c.handles)
            try:return launch(command,kind)
            finally:
                for child in c.handles[before:]:
                    created=wintypes.FILETIME();exited=wintypes.FILETIME()
                    kernel=wintypes.FILETIME();user=wintypes.FILETIME()
                    get_times=ctypes.WinDLL('kernel32',use_last_error=True).GetProcessTimes
                    get_times.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
                    get_times.restype=wintypes.BOOL
                    if not get_times(int(child._handle),ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.child_receipts.append({'pid':child.pid,'created_filetime_100ns':(created.dwHighDateTime<<32)|created.dwLowDateTime,
                        'observed_created_utc':datetime.now(timezone.utc).isoformat(),'kind':kind,
                        'actual_args':child.args,'executable':sys.executable,
                        'executable_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                        'fixture_sha256':hashlib.sha256(CHILD.read_bytes()).hexdigest(),'child':child})
        c.launch=retained_launch
        c.registry=f.box.registry;c.box=f.box;c.capability=f.cap;c.identity=f.identity;c.original=f.original
        c.deadline=10.;c.stop_id='original-stop';c.worker_cap=object();c.worker_exit_verified=False
        c.host_epoch='same-host';c.qualification_hold_after_report=False;c.continuation=None
        c.worker=c.launch([sys.executable,str(CHILD),'--original','--run',str(c.work)],'worker')
        await wait_original_ready(c.worker,c.work/'original-fixture-ready.json')
        # Imports have completed and the existing 15-second emergency guard is
        # armed. Its exit124 remains a failure; only the original exit5 passes.
        self.assertEqual(await asyncio.to_thread(c.worker.wait,18),5)
        (c.work/'wire-observations.json').write_text('[]',encoding='utf-8')
        self.old=c.store.load('orders-report');self.old_hash=rec.digest(self.old.state)
        c.intent_cap=object()
        c.gate=UIIntentGate(host_epoch='same-host',capability=c.intent_cap,
            verify_current=lambda binding:VerifiedUIObservation(binding,time.monotonic(),True,True))
        c.gui=lifecycle_fixture.GUI();c.gui.release.set()
        c.gui.binding=UIBinding('same-host','session','orders-report',101,202,303)
        c.gui.process=SimpleNamespace(pid=202,poll=lambda:None)
        c.gui.verifier=SimpleNamespace(verify_current=lambda binding:VerifiedUIObservation(binding,time.monotonic(),True,True))
        host=ControlledDesktopHost.__new__(ControlledDesktopHost);c.host=host
        host.adapter=Adapter()
        policy=SimpleNamespace(reason='foreground_clear',allowed=True,fresh=lambda now:True)
        controller=HandoffController(host.adapter,policy,demand=c.registry,restore_requirements=ToolRequirements(1,1,1))
        scheduler=Scheduler(Config(),capacity=controller);controller.bind_scheduler(scheduler);controller.state='parked'
        host.controller=controller;host.gateway=SimpleNamespace(scheduler=scheduler,instance='same-gateway')
        host.closing=host.closed=False;host.phase='running'
        host.primary_error=host.cleanup_error=host.demand_error=None
        host.control_runtime=None;host._control_thread=threading.current_thread()
        host._control_loop=asyncio.get_running_loop();host._control_rebinding=False;host.closes=0
        async def close(*,timeout_s):
            self.assertTrue(all(child.poll() is not None for child in c.handles));self.assertTrue(c.gui.joined)
            host.closed=True;host.closes+=1
            return {'closed':True,'primary_error':None,'cleanup_error':None,'controller_fault':None}
        host.close=close
        c.stop_binding=WorkerStopBinding(c.worker,c.work,c.box,requester_capability=c.capability,
            capability=c.worker_cap,stop_request_id=c.stop_id,original=c.original,deadline_monotonic=10.,
            model=worker.MODEL,quality=worker.QUALITY,fence=c.fence,deadline_clock=CLOCK_ID)
        c.prepared=PreparedTask('same-host','orders-report',worker.PROMPT)
        c.facade=DesktopControlLifecycle(host,c.prepared,worker_stop=c.stop_binding,
            worker_capability=c.worker_cap,gui=c.gui,shutdown_timeout_s=5)
        c.facade.bind_window(c.gui.binding,c.gui.verifier,
            SimpleNamespace(host_epoch='same-host',task_id='orders-report',session_id='session',objective=worker.PROMPT))
        c.runtime=MailboxRuntime(c.prepared,c.box,requester_capability=c.capability,
            gate=c.gate,intent_capability=c.intent_cap,lifecycle=c.facade)
        await c.runtime.refresh();host.attach_control_runtime(c.runtime)
        c.continuation=HostContinuation(c,c.runtime)
        c.runtime.window_ready('session')
        c.job=SimpleNamespace(_HANDLE=object())
        c.launch_api=SimpleNamespace(handle=lambda child:child,identity=lambda child:(child.pid,child.pid*10),
            in_job=lambda child,job:True)
        self.behavior='complete';self.pause_delay=0.;self.tasks=[];self.releases=[]
        self.actual_popen=subprocess.Popen
        def popen(command,**kwargs):
            self.assertNotIn('--qualification-hold-after-report',command)
            command=[sys.executable,str(CHILD),*command[command.index('--run'):],
                     '--behavior',self.behavior,'--pause-delay',str(self.pause_delay)]
            return self.actual_popen(command,**kwargs)
        patch=mock.patch.object(product.subprocess,'Popen',side_effect=popen);patch.start();self.patches.append(patch)

    async def asyncTearDown(self):
        # A completed failed transition is already removed from its set,
        # but the fixture restore loop still needs its Stop fence.
        self.c.runtime.fence_admission()
        for release in self.releases:release.set()
        c=self.c
        if c.runtime._continuation_tasks:
            c.runtime.fence_admission()
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(c.runtime._continuation_tasks)),return_exceptions=True)
        if c.facade._selected is not None and c.facade._selected.get('binding') is not None:
            binding=c.facade._selected['binding']
            if binding.worker.poll() is None:
                binding.request_stop(c.facade._selected['capability'])
                await binding.join(timeout=3)
        for child in c.handles:
            # CPU emergency bounds are 15 s original / 60 s selected;
            # cleanup always joins the exact retained Popen, never PID lookup.
            await asyncio.to_thread(child.wait,18)
        if c.facade._wake is not None:await c.facade._wake
        if c.facade._stop is not None:
            await asyncio.gather(asyncio.shield(c.facade._stop),return_exceptions=True)
        for task in self.tasks:
            await asyncio.gather(asyncio.shield(task),return_exceptions=True)

    def cleanup_retained(self):
        # This also runs after incomplete setup or an asyncTearDown exception.
        # A forced stop cleans a failed fixture; it never turns it into a pass.
        c=self.c;joined=set();killed=set();errors=[]
        for child in c.handles:
            try:
                if child.poll() is None:child.kill();killed.add(child)
                child.wait(timeout=10);joined.add(child)
            except Exception as exc:errors.append(exc)
        for stream in c.logs:
            try:stream.close()
            except Exception as exc:errors.append(exc)
        for patch in reversed(self.patches):
            try:patch.stop()
            except Exception as exc:errors.append(exc)
        destination=os.environ.get('CONTINUATION_TEST_RECEIPTS')
        if destination:
            rows=[]
            for item in self.child_receipts:
                row={key:value for key,value in item.items() if key!='child'}
                row.update(exit_code=item['child'].returncode,joined=item['child'] in joined,
                           cleanup_killed=item['child'] in killed,
                           join_observed_utc=datetime.now(timezone.utc).isoformat())
                # The existing opt-in CI receipt must outlive temporary logs.
                # Capture only this exact retained label, after join and close.
                log_path=c.root/(item['kind']+'.log')
                try:
                    matching=[stream for stream in c.logs if Path(stream.name)==log_path]
                    if len(matching)!=1 or not matching[0].closed:
                        raise ValueError('Retained child log handle differs or remains open')
                    with log_path.open('rb') as stream:
                        stream.seek(0,os.SEEK_END);total=stream.tell()
                        stream.seek(max(0,total-65536));tail=stream.read(65536)
                    row['output_log']={'name':log_path.name,'total_bytes':total,
                        'captured_bytes':len(tail),'truncated':total>len(tail),
                        'tail_sha256':hashlib.sha256(tail).hexdigest(),
                        'tail_utf8':tail.decode('utf-8',errors='replace')}
                except (OSError,ValueError) as exc:
                    row['output_log']={'name':log_path.name,'capture_error':type(exc).__name__}
                rows.append(row)
            payload={'test':self.id(),'children':rows,
                'scope':'CPU Python child and actual SQLite; injected native/window/job boundaries; no SDK/model'}
            if hasattr(self,'timeout_observation'):
                try:after=timeout_diagnostics.after_join(self,joined)
                except Exception as exc:after={'capture_error':type(exc).__name__}
                payload['timeout_observation']={'before_teardown':self.timeout_observation,'after_join':after}
            output=Path(destination);output.mkdir(exist_ok=True)
            (output/(self._testMethodName+'.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
        if errors:raise ExceptionGroup('CPU fixture cleanup failed',errors)

    def request(self,ident='continue-1'):
        return {'host_epoch':'same-host','task_id':'orders-report','session_id':'session','method':'continue',
                'request_id':ident,'execution_id':'orders-report','execution_generation':0,
                'expected_task_revision':self.old.revision}

    def intent(self):return not self.c.runtime._stopping and self.c.gui.session_live('session')

    async def select(self):return await self.c.runtime.select_continuation(self.request(),intent_valid=self.intent)

    async def restore(self):
        while True:
            record=self.c.continuation.current
            if record and record.get('resume_id'):
                snap=await asyncio.to_thread(record['mailbox'].snapshot)
                if any(row['request_id']==record['resume_id'] and row['outcome']=='applied' for row in snap.receipts):
                    self.c.host.controller.state='ready'
                    return
            if self.c.runtime._stopping:return
            await asyncio.sleep(.01)

    async def continue_task(self,grant,*,restore=True):
        if restore:
            task=asyncio.create_task(self.restore());self.tasks.append(task)
        return await self.c.runtime.continue_selected(grant,intent_valid=self.intent)

    async def start_transport(self):
        c=self.c
        self.transport=ControlTransport(c.prepared,c.runtime,capability=object(),runner_credential='b'*64,io_timeout=.1)
        self.transport.bind_session(self.transport._capability,'session','a'*64)
        self.assertTrue((await self.wire('window_ready'))['ok'])

    async def wire(self,method,**values):
        request={'host_epoch':'same-host','task_id':'orders-report','session_id':'session','token':'a'*64,'method':method}
        if method=='continue':request.update(self.request())
        request.update(values);writer=Writer()
        await self.transport.admit(Reader((json.dumps(request)+'\n').encode()),writer)
        return json.loads(writer.data)

    async def test_transport_continue_preserves_live_intent_and_duplicate_does_not_launch(self):
        c=self.c;await self.start_transport()
        restoring=asyncio.create_task(self.restore());self.tasks.append(restoring)
        first=await self.wire('continue');self.assertTrue(first['ok'])
        task=self.transport._records['continue-1']['task'];self.tasks.append(task)
        try:
            await asyncio.wait_for(asyncio.shield(task), self.continuation_timeout_s)
        except TimeoutError:
            if os.environ.get('CONTINUATION_TEST_RECEIPTS'):
                try:self.timeout_observation=timeout_diagnostics.before_teardown(self,task)
                except Exception as exc:self.timeout_observation={'capture_error':type(exc).__name__}
            raise
        record=c.continuation.current
        self.assertEqual(await c.join_child(record['child']),0)
        duplicate=await self.wire('continue')
        self.assertEqual(duplicate['continuation']['phase'],'running')
        self.assertEqual(len(c.handles),2)
        self.assertEqual([r['command'] for r in record['mailbox'].snapshot().requests],['pause','resume'])
        self.assertEqual((await self.wire('status'))['status']['execution_id'],record['grant']['payload']['successor_id'])
        await self.transport.aclose(timeout=3)
        self.assertTrue(self.transport.lifecycle()['stop_confirmed'])

    async def test_old_read_error_still_faults_and_prevents_selection(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        def failed():entered.set();release.wait(4);raise OSError('actual old read failure')
        with mock.patch.object(c.box,'snapshot',side_effect=failed):
            read_task=asyncio.create_task(c.runtime.refresh());self.tasks.append(read_task)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            select_task=asyncio.create_task(self.select());self.tasks.append(select_task)
            await asyncio.sleep(.05);release.set()
            with self.assertRaisesRegex(OSError,'actual old read failure'):await read_task
            with self.assertRaisesRegex(OSError,'actual old read failure'):await select_task
        self.assertIn('database_operation_failed',c.runtime._faults)
        self.assertIsNone(c.continuation.current);self.assertEqual(len(c.handles),1)

    async def test_inflight_mutation_error_is_not_retired_as_refresh(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        before=c.box.snapshot()
        def failed(*args):entered.set();release.wait(4);raise OSError('actual mutation failure')
        with mock.patch.object(c.box,'submit',side_effect=failed):
            control=asyncio.create_task(c.runtime.submit_control('old-pause','pause'));self.tasks.append(control)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            choosing=asyncio.create_task(self.select());self.tasks.append(choosing)
            await asyncio.sleep(.05);release.set()
            with self.assertRaisesRegex(OSError,'actual mutation failure'):await control
            with self.assertRaisesRegex(OSError,'actual mutation failure'):await choosing
        self.assertIn('database_operation_failed',c.runtime._faults)
        self.assertIsNone(c.continuation.current);self.assertEqual(c.box.snapshot(),before)

    async def test_normal_refresh_still_refuses_stale_observation(self):
        with mock.patch.object(self.c.runtime,'_clock',side_effect=[10.,12.,12.]):
            with self.assertRaisesRegex(RuntimeUnavailable,'stale'):await self.c.runtime.refresh()
        self.assertIn('database_operation_failed',self.c.runtime._faults)

    async def test_stop_during_committed_authorization_retains_no_child_obligation(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        original=ContinuationAuthority.authorize
        def held(authority,*args):
            grant=original(authority,*args);entered.set();release.wait(4);return grant
        with mock.patch.object(ContinuationAuthority,'authorize',new=held):
            choosing=asyncio.create_task(self.select());self.tasks.append(choosing)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            stop=asyncio.create_task(c.runtime.cooperative_stop());self.tasks.append(stop)
            await asyncio.sleep(.05);self.assertTrue(c.runtime._stopping);self.assertFalse(stop.done())
            release.set();grant=await choosing;receipt=await stop
        self.assertFalse(receipt['uncertain']);self.assertTrue(receipt['host_closed'])
        self.assertEqual(c.facade.worker_receipt['outcome'],'selected_not_launched')
        self.assertEqual((await c.runtime.continue_selected(grant,intent_valid=self.intent))['phase'],'blocked')
        self.assertEqual(len(c.handles),1)

    async def test_cancelled_select_waiter_does_not_cancel_committed_selection(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        original=ContinuationAuthority.authorize
        def held(authority,*args):
            grant=original(authority,*args);entered.set();release.wait(4);return grant
        with mock.patch.object(ContinuationAuthority,'authorize',new=held):
            choosing=asyncio.create_task(self.select());self.tasks.append(choosing)
            self.assertTrue(await asyncio.to_thread(entered.wait,2));choosing.cancel()
            with self.assertRaises(asyncio.CancelledError):await choosing
            release.set()
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(c.runtime._continuation_tasks)))
        self.assertIs(c.facade._selected,c.continuation.current)
        self.assertEqual(len(c.handles),1);self.assertFalse(c.runtime._faults)
        self.assertTrue((await c.runtime.cooperative_stop())['host_closed'])

    async def test_staging_failure_keeps_grant_obligation_without_relabelling_old_cache(self):
        c=self.c;old_box=c.box;old_observe=c.runtime._observe
        def observe(box=None):
            if box is not None and box is not old_box:raise OSError('staging read failure')
            return old_observe(box)
        with mock.patch.object(c.runtime,'_observe',side_effect=observe):
            with self.assertRaisesRegex(OSError,'staging read failure'):await self.select()
        record=c.continuation.current
        self.assertTrue(record['committed']);self.assertIs(c.facade._selected,record)
        self.assertEqual(c.runtime.status()['execution_id'],'orders-report')
        self.assertEqual(c.runtime._cache.snapshot.target.task_id,'orders-report')
        self.assertEqual((await c.runtime.lookup_continuation(self.request()))['phase'],'blocked')
        receipt=await c.runtime.cooperative_stop()
        self.assertTrue(receipt['host_closed']);self.assertIsNotNone(receipt['fault'])
        self.assertEqual(c.facade.worker_receipt['outcome'],'selected_not_launched')

    async def test_unknown_launch_slot_cannot_use_old_worker_receipt(self):
        c=self.c;await self.select();record=c.continuation.current
        record['launch_attempted']=True
        with self.assertRaisesRegex(ReconciliationRequired,'known unstarted'):
            await c.runtime.cooperative_stop()
        self.assertFalse(c.host.closed);self.assertIsNone(c.facade.worker_receipt)

    async def test_committed_grant_lost_return_is_retained_but_never_launched(self):
        c=self.c;original=ContinuationAuthority.authorize
        def lost(authority,*args):
            original(authority,*args);raise OSError('committed grant return lost')
        with mock.patch.object(ContinuationAuthority,'authorize',new=lost):
            with self.assertRaisesRegex(OSError,'return lost'):await self.select()
        record=c.continuation.current
        self.assertTrue(record['committed']);self.assertIs(c.facade._selected,record)
        self.assertEqual(record['phase'],'blocked');self.assertIn('continuation_failed',c.runtime._faults)
        self.assertEqual(c.runtime.selected_execution(),{'execution_id':'orders-report','execution_generation':0})
        self.assertEqual((await c.runtime.lookup_continuation(self.request()))['phase'],'blocked')
        self.assertEqual(len(c.handles),1)
        receipt=await c.runtime.cooperative_stop()
        self.assertTrue(receipt['host_closed']);self.assertIsNotNone(receipt['fault'])
        self.assertEqual(c.facade.worker_receipt['outcome'],'selected_not_launched')

    async def test_unknown_grant_lookup_fences_clean_stop(self):
        c=self.c;original=ContinuationAuthority.authorize
        def lost(authority,*args):
            original(authority,*args);raise OSError('committed grant return lost')
        with mock.patch.object(ContinuationAuthority,'authorize',new=lost), \
                mock.patch.object(ContinuationAuthority,'lookup',side_effect=OSError('lookup unavailable')):
            with self.assertRaisesRegex(OSError,'return lost'):await self.select()
        self.assertIsNone(c.continuation.current)
        self.assertFalse(c.continuation.records['continue-1']['authorization_resolved'])
        with self.assertRaisesRegex(RuntimeUnavailable,'authorization outcome is unresolved'):
            await c.runtime.cooperative_stop()
        self.assertFalse(c.host.closed);self.assertIsNone(c.facade.worker_receipt)

    async def test_readiness_has_240_second_cap_with_longer_grant(self):
        c=self.c;await self.select();record=c.continuation.current
        # No new child: isolate the readiness timer with an explicitly live fixture.
        record['child']=SimpleNamespace(pid=999,poll=lambda:None)
        record['diagnostics']=c.work/'unused-readiness'
        start=record['grant']['deadline_monotonic']-900
        with mock.patch.object(product,'execution_now',side_effect=[start,start+240]):
            with self.assertRaisesRegex(TimeoutError,'readiness boundary'):
                await c.ready_continuation(record,self.intent)
        self.assertEqual(record['readiness_deadline_monotonic'],start+240)
        record['child']=None

    async def test_readiness_never_extends_shorter_grant(self):
        c=self.c;await self.select();record=c.continuation.current
        record['child']=SimpleNamespace(pid=999,poll=lambda:None);record['diagnostics']=c.work/'unused-readiness'
        deadline=record['grant']['deadline_monotonic']
        with mock.patch.object(product,'execution_now',side_effect=[deadline-30,deadline]):
            with self.assertRaisesRegex(TimeoutError,'readiness boundary'):
                await c.ready_continuation(record,self.intent)
        self.assertEqual(record['readiness_deadline_monotonic'],deadline);record['child']=None

    async def test_long_bootstrap_status_preserves_selected_pair_and_live_intent(self):
        c=self.c;self.pause_delay=1.3;self.behavior='hold'
        grant=await self.select()
        continuing=asyncio.create_task(self.continue_task(grant,restore=False));self.tasks.append(continuing)
        while c.continuation.current['child'] is None:await asyncio.sleep(.01)
        await asyncio.sleep(1.1)
        status=c.runtime.status()
        self.assertEqual(status['execution_id'],grant['execution_id']);self.assertFalse(c.runtime._faults)
        self.assertEqual(c.runtime._cache.snapshot.target.task_id,grant['execution_id'])
        receipt=await c.runtime.cooperative_stop()
        self.assertTrue(receipt['host_closed']);self.assertFalse(receipt['uncertain'])

    async def test_atomic_select_keeps_logical_identity_and_new_snapshot(self):
        c=self.c;old_box=c.box;old_binding=c.gate._binding
        grant=await self.select();record=c.continuation.current
        self.assertEqual(c.runtime.selected_execution(),selection(record['grant']))
        self.assertIs(c.host.controller.demand,c.registry);self.assertIs(c.runtime.mailbox,c.box)
        self.assertIsNot(c.box,old_box);self.assertEqual(c.runtime.status()['task_revision'],0)
        self.assertEqual(c.runtime._cache.snapshot.target.task_id,grant['execution_id'])
        self.assertEqual(c.prepared.task_id,'orders-report');self.assertEqual(c.gate._binding,old_binding)
        self.assertFalse(c.host.controller._demand_valid);self.assertEqual(c.host.controller._demand_rows,())
        self.assertEqual(rec.digest(c.store.load('orders-report').state),self.old_hash)
        self.assertEqual(len(c.handles),1)
        self.assertEqual(await c.runtime.lookup_continuation(self.request()),grant)
        self.assertEqual(len(c.handles),1)
        receipt=await c.runtime.cooperative_stop()
        self.assertEqual(receipt,{'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None})
        self.assertEqual(c.facade.worker_receipt['outcome'],'selected_not_launched')

    async def test_actual_cpu_child_one_resume_shared_report_and_lifetime(self):
        c=self.c;report=(c.work/'work/report.json').read_bytes();effects=(c.work/'effect-receipts.jsonl').read_bytes()
        grant=await self.select();reply=await self.continue_task(grant)
        record=c.continuation.current
        self.assertEqual(reply['phase'],'running')
        self.assertEqual(await c.join_child(record['child']),0)
        self.assertEqual(record['binding']._verify_exit(0),'task_completed')
        snapshot=record['mailbox'].snapshot()
        self.assertEqual([r['command'] for r in snapshot.requests],['pause','resume'])
        self.assertEqual(snapshot.requests[-1]['request_id'],record['resume_id'])
        ready=json.loads((record['diagnostics']/'controller-ready.json').read_bytes())
        self.assertEqual(ready['selected_execution'],selection(record['grant']))
        self.assertEqual((c.work/'work/report.json').read_bytes(),report)
        self.assertEqual((c.work/'effect-receipts.jsonl').read_bytes(),effects)
        self.assertEqual(snapshot.target.state['requests'],0)
        self.assertEqual(await c.runtime.lookup_continuation(self.request()),{**grant,'phase':'blocked'})
        self.assertEqual(len(c.handles),2)
        receipt=await c.runtime.cooperative_stop();self.assertTrue(receipt['host_closed']);self.assertFalse(receipt['uncertain'])

    async def test_new_task_admission_reuses_exact_completed_successor_verifier(self):
        from adaptive_inference.desktop.task_admission import TaskAdmission
        from adaptive_inference.task_store import TaskStore, TaskBusyError
        from adaptive_inference.task_spec import TaskSpec, BUDGET
        from adaptive_inference.demand import DemandIdentity
        from test_task_admission import create_task
        c=self.c
        original_binding=c.stop_binding
        grant=await self.select();await self.continue_task(grant)
        record=c.continuation.current
        self.assertEqual(await c.join_child(record['child']),0)
        cp=record['mailbox'].snapshot().target
        history=c.store.history(cp.task_id)
        tasks=c.root/'new-tasks';tasks.mkdir()
        admission=TaskAdmission(TaskStore(c.root/'admission.sqlite3'),host_generation=c.host_epoch,
            tasks_root=tasks,initial_task_id='orders-report',initial_run=c.work)
        with self.assertRaisesRegex(ReconciliationRequired,'Original worker no longer'):
            with admission._released_checkpoint(admission.initial,'orders-report',self.old.revision,
                                                stop_binding=original_binding):pass
        task_spec=TaskSpec({'schema':'adaptive.task-spec.v1','prompt':'Explain one idea.',
            'inputs':[],'outputs':[],'budget':BUDGET,'validation':{'validator':None}})
        payload=admission.request(command_id='new-task',expected_selection_revision=0,
            predecessor_execution_id=cp.task_id,predecessor_revision=cp.revision,spec=task_spec,
            arrived_at_utc='2026-10-26T12:00:00Z')
        authority_cp=admission.store.load(admission.task_id)
        with admission.store.claim(admission.task_id,expected_revision=authority_cp.revision) as owner:
            with self.assertRaisesRegex(ReconciliationRequired,'Unverified successor'):
                admission.reserve(owner,payload,predecessor_cleanup_sha256='1'*64)
            admission.retain_execution_binding(record['binding'])
            # The continuation authority cannot be claimed while admission holds
            # its stable lock; this prevents a concurrent selection during write.
            saved=owner.save_checkpoint
            def guarded_save(*args,**kwargs):
                authority=record['authority'];current=c.store.load(authority.task_id)
                with self.assertRaises(TaskBusyError):
                    with c.store.claim(current.task_id,expected_revision=current.revision):pass
                return saved(*args,**kwargs)
            with mock.patch.object(owner,'save_checkpoint',side_effect=guarded_save):
                reservation=admission.reserve(owner,payload,predecessor_cleanup_sha256='1'*64)
            operation=admission.begin(owner,reservation,action='prepare')
            run=Path(payload['run']);run.mkdir();(run/'work').mkdir()
            identity=DemandIdentity(**{key:payload['demand_identity'][key] for key in
                ('registration_id','task_id','owner_id','arrived_at_utc')})
            create_task(TaskStore(run/'task.sqlite3'),identity,task_spec,payload['session_id'])
            result_path=record['diagnostics']/f"result-{record['child'].pid}.json"
            original=result_path.read_bytes()
            try:
                changed=json.loads(original);changed['continuation_cleanup_verified']=False
                result_path.write_text(json.dumps(changed),encoding='utf-8')
                with self.assertRaisesRegex(ReconciliationRequired,'Selected result'):
                    admission.prepared(owner,reservation,operation_id=operation)
            finally:
                result_path.write_bytes(original)
            admission.prepared(owner,reservation,operation_id=operation)
            self.assertEqual(admission.status()['selected']['task_id'],payload['task_id'])
        self.assertEqual(c.store.history(cp.task_id),history)

    async def test_new_task_stop_reuses_committed_unlaunched_verifier(self):
        from adaptive_inference.desktop.task_admission import TaskAdmission
        from adaptive_inference.task_store import TaskStore, TaskBusyError
        c=self.c;grant=await self.select();record=c.continuation.current
        tasks=c.root/'new-tasks';tasks.mkdir()
        admission=TaskAdmission(TaskStore(c.root/'admission.sqlite3'),host_generation=c.host_epoch,
            tasks_root=tasks,initial_task_id='orders-report',initial_run=c.work)
        history=c.store.history(grant['execution_id'])
        with admission._unlaunched_checkpoint(admission.initial,c.continuation) as (cp,outcome):
            self.assertEqual(cp.task_id,grant['execution_id'])
            self.assertEqual(outcome,'selected_not_launched')
            for ident in (record['authority'].task_id,cp.task_id):
                current=c.store.load(ident)
                with self.assertRaises(TaskBusyError):
                    with c.store.claim(ident,expected_revision=current.revision):pass
        self.assertEqual(c.store.history(grant['execution_id']),history)
        record['launch_attempted']=True
        try:
            with self.assertRaisesRegex(ReconciliationRequired,'known unstarted'):
                with admission._unlaunched_checkpoint(admission.initial,c.continuation):pass
        finally:record['launch_attempted']=False

    async def test_new_task_release_locks_first_continuation_authority_before_row_exists(self):
        from adaptive_inference.desktop.task_admission import TaskAdmission
        from adaptive_inference.task_store import TaskStore, TaskBusyError
        from adaptive_inference.desktop.hermes.continuation_worker import scope_for
        c=self.c;tasks=c.root/'new-tasks';tasks.mkdir()
        admission=TaskAdmission(TaskStore(c.root/'admission.sqlite3'),host_generation=c.host_epoch,
            tasks_root=tasks,initial_task_id='orders-report',initial_run=c.work)
        with admission._released_checkpoint(admission.initial,'orders-report',self.old.revision,
                                            stop_binding=c.stop_binding):
            authority=ContinuationAuthority(c.store,'orders-report',
                scope_for(c.work,c.plan,(c.work/'plan.json').read_bytes()),host_generation=c.host_epoch)
            cp=c.store.load(authority.task_id)
            with self.assertRaises(TaskBusyError):
                with c.store.claim(cp.task_id,expected_revision=cp.revision):pass

    async def test_stop_before_initial_pause_ack_joins_new_child_without_resume(self):
        self.pause_delay=.5;self.behavior='hold';c=self.c
        grant=await self.select()
        task=asyncio.create_task(self.continue_task(grant,restore=False));self.tasks.append(task)
        while c.continuation.current['child'] is None:await asyncio.sleep(.01)
        receipt=await c.runtime.cooperative_stop()
        self.assertFalse(receipt['uncertain']);self.assertTrue(receipt['host_closed'])
        record=c.continuation.current
        self.assertEqual(record['child'].poll(),4)
        self.assertFalse(any(row['command']=='resume' for row in record['mailbox'].snapshot().requests))
        self.assertEqual((await task)['phase'],'blocked')

    async def test_stop_while_native_readiness_waits_keeps_resume_once(self):
        self.behavior='hold';c=self.c
        grant=await self.select()
        task=asyncio.create_task(self.continue_task(grant,restore=False));self.tasks.append(task)
        while c.continuation.current['phase']!='running':await asyncio.sleep(.01)
        receipt=await c.runtime.cooperative_stop()
        self.assertTrue(receipt['host_closed']);self.assertFalse(receipt['uncertain'])
        record=c.continuation.current
        self.assertEqual(record['child'].poll(),4)
        self.assertEqual(sum(r['command']=='resume' for r in record['mailbox'].snapshot().requests),1)

    async def test_stale_queued_control_cannot_mutate_selected_mailbox(self):
        await self.select();c=self.c
        with self.assertRaisesRegex(Refused,'stale_execution'):
            await c.runtime.submit_control('old-click','resume',execution={'execution_id':'orders-report','execution_generation':0})
        self.assertEqual(c.box.snapshot().requests,())

    async def test_status_during_old_read_drain_remains_exact_after_cache_expiry(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        actual=c.box.snapshot
        def blocked():entered.set();release.wait(4);return actual()
        with mock.patch.object(c.box,'snapshot',side_effect=blocked):
            read_task=asyncio.create_task(c.runtime.refresh());self.tasks.append(read_task)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            select_task=asyncio.create_task(self.select());self.tasks.append(select_task)
            await asyncio.sleep(1.1)
            status=c.runtime.status()
            self.assertEqual(status['execution_id'],'orders-report');self.assertEqual(status['task_revision'],self.old.revision)
            self.assertFalse(c.runtime._faults);release.set()
            await read_task;grant=await select_task
        self.assertEqual(c.runtime.status()['execution_id'],grant['execution_id'])
        self.assertEqual(c.runtime.status()['task_revision'],0)

    async def test_inflight_controller_read_is_drained_before_registry_commit(self):
        c=self.c;entered=threading.Event();release=threading.Event();self.releases.append(release)
        actual=c.registry.observations
        def blocked():entered.set();release.wait(3);return actual()
        with mock.patch.object(c.registry,'observations',side_effect=blocked):
            old_read=asyncio.create_task(c.host.controller.refresh_demand());self.tasks.append(old_read)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            choosing=asyncio.create_task(self.select());self.tasks.append(choosing)
            await asyncio.sleep(.05);self.assertFalse(choosing.done());release.set()
            await old_read;await choosing
        self.assertEqual(c.host.controller._demand_rows,());self.assertFalse(c.host.controller._demand_valid)
        await c.host.controller.refresh_demand()
        self.assertEqual({row.task_id for row in c.host.controller._demand_rows},{c.identity.task_id})

    async def test_launch_diagnostic_failure_keeps_child_and_binding_for_stop(self):
        c=self.c;grant=await self.select();actual=c.event
        def event(kind,**fields):
            if kind=='worker_launched':raise OSError('after retained CPU child')
            return actual(kind,**fields)
        with mock.patch.object(c,'event',side_effect=event):
            with self.assertRaisesRegex(OSError,'retained CPU child'):await self.continue_task(grant,restore=False)
        record=c.continuation.current
        self.assertIs(record['child'],c.handles[-1]);self.assertIsNotNone(record['binding'])
        receipt=await c.runtime.cooperative_stop()
        self.assertEqual(record['child'].poll(),4);self.assertIsNotNone(receipt['fault'])

    async def test_old_or_wrong_generation_result_refused(self):
        c=self.c;grant=await self.select();await self.continue_task(grant)
        record=c.continuation.current;self.assertEqual(await c.join_child(record['child']),0)
        path=record['diagnostics']/f"result-{record['child'].pid}.json";raw=path.read_bytes()
        value=json.loads(raw);value['selected_execution']['execution_generation']=0;rec.save(path,value)
        with self.assertRaisesRegex(ReconciliationRequired,'Selected result identity'):record['binding']._verify_exit(0)
        path.write_bytes(raw)
        self.assertEqual(record['binding']._verify_exit(0),'task_completed')
        # Even a valid selected result in the old shared root cannot substitute
        # for this execution's scoped diagnostic file.
        legacy=c.work/path.name;legacy.write_bytes(raw);path.unlink()
        try:
            with self.assertRaises(FileNotFoundError):record['binding']._verify_exit(0)
        finally:path.write_bytes(raw);legacy.unlink()

    async def test_selected_result_requires_matching_lifetime_returncode(self):
        c=self.c;grant=await self.select();await self.continue_task(grant)
        record=c.continuation.current;self.assertEqual(await c.join_child(record['child']),0)
        authority=record['authority'];history=c.store.history(authority.task_id)
        completed=next(row for row in reversed(history) if row['event']=='operation_completed')
        changed=deepcopy(completed['payload']);changed['event_data']['result']['returncode']=4
        with sqlite3.connect(c.store.path) as db:
            db.execute('UPDATE history SET payload=? WHERE task_id=? AND revision=?',
                (json.dumps(changed),authority.task_id,completed['revision']))
        with self.assertRaisesRegex(ReconciliationRequired,'exact result'):record['binding']._verify_exit(0)
        with sqlite3.connect(c.store.path) as db:
            db.execute('UPDATE history SET payload=? WHERE task_id=? AND revision=?',
                (json.dumps(completed['payload']),authority.task_id,completed['revision']))


class FixtureStartupTests(unittest.TestCase):
    def test_delayed_import_readiness_has_its_own_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ready.json'
            child=SimpleNamespace(pid=123,poll=lambda:None)
            async def release(_):
                path.write_text(json.dumps({'pid':123,'work_guard_s':15}),encoding='utf-8')
            # Deterministically simulate 11 seconds before ready, without wall
            # clock sleeps or a tiny scheduling threshold on the CI runner.
            clock=mock.Mock(side_effect=[0.,11.])
            with mock.patch.object(asyncio,'sleep',side_effect=release) as paused:
                asyncio.run(wait_original_ready(child,path,clock=clock))
            self.assertEqual(paused.call_count,1)

    def test_readiness_timeout_wrong_identity_and_emergency_exit_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ready.json'
            child=SimpleNamespace(pid=123,poll=lambda:None)
            with self.assertRaisesRegex(TimeoutError,'startup deadline'):
                asyncio.run(wait_original_ready(child,path,clock=mock.Mock(side_effect=[0.,31.])))
            path.write_text(json.dumps({'pid':999,'work_guard_s':15}),encoding='utf-8')
            with self.assertRaisesRegex(AssertionError,'identity differs'):
                asyncio.run(wait_original_ready(child,path))
            path.unlink();child.poll=lambda:124;child.returncode=124
            with self.assertRaisesRegex(AssertionError,'before readiness: 124'):
                asyncio.run(wait_original_ready(child,path))

    @unittest.skipUnless(os.name=='nt','Windows retained-process setup fixture')
    def test_async_setup_failure_still_joins_child_and_closes_streams(self):
        class FailedSetup(HostTests):
            async def test_injected_setup_failure(self):
                self.fail('Test body must not run')
        case=FailedSetup('test_injected_setup_failure')
        result=unittest.TestResult()
        with mock.patch.object(sys.modules[__name__],'wait_original_ready',
                               side_effect=RuntimeError('injected readiness failure')):
            case.run(result)
        self.assertEqual(len(result.errors),1)
        self.assertIn('injected readiness failure',result.errors[0][1])
        self.assertFalse(result.failures)
        self.assertIsNotNone(case.c.worker.returncode)
        self.assertTrue(all(stream.closed for stream in case.c.logs))
        self.assertFalse(case.c.work.exists())


    @unittest.skipUnless(os.name=='nt','Windows retained-process body failure fixture')
    def test_async_body_error_still_finishes_restore_and_retained_cleanup(self):
        class FailedBody(HostTests):
            async def test_injected_body_failure(self):
                grant=await self.select();launch=self.c.launch_continuation
                async def fail_after_pause(record,coordinator,intent_valid):
                    await launch(record,coordinator,intent_valid)
                    raise RuntimeError('injected failure after initial Pause before Resume')
                self.c.launch_continuation=fail_after_pause
                await self.continue_task(grant)

            async def asyncTearDown(self):
                try:
                    # Bound this regression itself if the old teardown bug
                    # returns; original production/fixture budgets stay intact.
                    await asyncio.wait_for(super().asyncTearDown(),20)
                finally:
                    self.c.runtime.fence_admission()
                    await asyncio.gather(*self.tasks,return_exceptions=True)
        case=FailedBody('test_injected_body_failure');result=unittest.TestResult()
        case.run(result)
        self.assertEqual(len(result.errors),1)
        self.assertIn('injected failure after initial Pause before Resume',result.errors[0][1])
        self.assertFalse(result.failures)
        self.assertTrue(case.c.runtime._stopping)
        self.assertTrue(all(task.done() and not task.cancelled() for task in case.tasks))
        self.assertFalse(case.c.runtime._continuation_tasks)
        self.assertFalse(case.c.runtime._pending)
        self.assertEqual([child.returncode for child in case.c.handles],[5,4])
        self.assertTrue(all(stream.closed for stream in case.c.logs))
        self.assertFalse(case.c.work.exists())


if __name__=='__main__':unittest.main()
