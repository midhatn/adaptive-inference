"""Actual worker control flow with real task/native SQLite and no SDK/network/model."""
from contextlib import ExitStack
import json
import hashlib
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference import task_store
from adaptive_inference.desktop.hermes import run_recovery as worker, recovery as rec, service_stop
from adaptive_inference.desktop.hermes.control_bridge import Controls, prepare_task
from adaptive_inference.execution_clock import CLOCK_ID
from test_desktop_paused_expiry import ClosingDB, NOW


class WorkerExpiryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.run = Path(temp.name).resolve()
        (self.run/'home').mkdir(); (self.run/'work').mkdir()
        self.store = task_store.TaskStore(self.run/'task.sqlite3')
        self.identity = DemandIdentity('registered', 'orders-report', 'worker', NOW)
        self.original = prepare_task(self.store, self.identity, worker.PROMPT, 'native',
            metadata={'sdk_revision':worker.SDK_REV,'model':worker.MODEL,'quality':worker.QUALITY,
                      'deadline_clock':CLOCK_ID},max_attempts=8)
        registry = DemandRegistry((Registration(self.store,self.identity),))
        self.cap = object(); self.box = Mailbox(registry,'registered',requester_capability=self.cap)
        self.box.submit(self.cap,'genuine-pause','pause')
        self.now = 9.0
        self.plan = dict(sdk_revision=worker.SDK_REV, model=worker.MODEL, quality=worker.QUALITY,
            fixture=True,max_requests=8,task_id='orders-report',pins={},sdk=str(self.run),deadline_clock=CLOCK_ID,
            demand_identity={key:getattr(self.identity,key) for key in
                ('registration_id','task_id','owner_id','arrived_at_utc')},
            session_id='native',gateway='http://127.0.0.1:18100/v1')
        (self.run/'plan.json').write_text(json.dumps(self.plan),encoding='utf-8')
        self.args = SimpleNamespace(run=self.run,mode='worker',deadline_monotonic=10.0,
            stop_request_id=None,controller_ready=None,gateway_instance=None,
            qualification_hold_after_report=False)
        self.opened = []

    def invoke(self, *, database=ClosingDB, patches=()):
        outer = self
        class Boundary:
            def __init__(self, *_):
                self.rows=[]; self.steps={'parent':0}; self.seen=set()
        base = SimpleNamespace(Boundary=Boundary,git=lambda *a:worker.SDK_REV if a[0]=='rev-parse' else '')
        sdk = ModuleType('hermes_state')
        http = ModuleType('httpx')
        class Client:
            def send(self,*args,**kwargs):
                raise AssertionError('Paused bootstrap must make no HTTP request')
        http.Client=Client
        def create_db(path,read_only=False):
            value=database(path,read_only=read_only);outer.opened.append(value);return value
        sdk.SessionDB=create_db
        def advance(seconds):outer.now += seconds
        def controls(*a,**kw):return Controls(*a,**kw,clock=lambda:outer.now,sleep=advance)
        original_finalizer=service_stop.finalize_paused_expiry
        def finalize(*a,**kw):return original_finalizer(*a,**kw,clock=lambda:outer.now)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ,dict(os.environ),clear=True))
            stack.enter_context(mock.patch.object(sys,'path',list(sys.path)))
            stack.enter_context(mock.patch.dict(sys.modules,{'hermes_state':sdk,'httpx':http}))
            stack.enter_context(mock.patch.object(worker,'setup',return_value=(rec,base)))
            stack.enter_context(mock.patch.object(worker,'verify_execution_clock',return_value=CLOCK_ID))
            stack.enter_context(mock.patch.object(worker,'execution_now',side_effect=lambda:outer.now))
            stack.enter_context(mock.patch('adaptive_inference.desktop.installation.verify_sdk_imports'))
            stack.enter_context(mock.patch('adaptive_inference.desktop.hermes.control_bridge.Controls',side_effect=controls))
            stack.enter_context(mock.patch.object(service_stop,'finalize_paused_expiry',side_effect=finalize))
            stack.enter_context(mock.patch.object(worker,'time',SimpleNamespace(monotonic=lambda:outer.now,time=time.time,sleep=advance)))
            for patch in patches:stack.enter_context(patch)
            return worker.worker(self.args)

    def result(self):
        return json.loads((self.run/f'result-{os.getpid()}.json').read_text(encoding='utf-8'))

    def test_actual_worker_expires_after_owner_release_without_constructing_agent(self):
        self.assertEqual(self.invoke(),5)
        result=self.result(); cp=self.store.load('orders-report')
        self.assertIsNone(cp.owner_epoch);self.assertIn(EXECUTION_OUTCOME,cp.state)
        self.assertFalse(result['passed']);self.assertFalse(result['completed'])
        self.assertEqual(result['provider_calls'],0)
        self.assertNotIn('context',result)
        self.assertEqual([db.close_calls for db in self.opened],[1,1])
        self.assertEqual(result['paused_expiry']['revision'],cp.revision)

    def test_lock_close_error_after_release_keeps_seal_but_cannot_publish_expiry(self):
        actual=task_store._FileLock.close
        initialize=task_store._FileLock.__init__
        target=str(self.store.path)+'.task-'+hashlib.sha256(b'orders-report').hexdigest()+'.lock'
        def init(lock,path):
            initialize(lock,path);lock.expiry_fixture_target=str(path)==target
        def close(lock):
            actual(lock)
            if lock.expiry_fixture_target and EXECUTION_OUTCOME in self.store.load('orders-report').state:
                raise OSError('lock close failure after release')
        self.assertEqual(self.invoke(patches=(mock.patch.object(task_store._FileLock,'__init__',init),
            mock.patch.object(task_store._FileLock,'close',close))),2)
        cp=self.store.load('orders-report');result=self.result()
        self.assertIsNone(cp.owner_epoch);self.assertIn(EXECUTION_OUTCOME,cp.state)
        self.assertNotIn('paused_expiry',result)
        self.assertEqual(result['error_type'],'OSError')
        self.assertIn('lock close failure',result['error'])

    def test_result_publication_failure_escapes_and_cannot_return_exit_five(self):
        actual=rec.save
        def fail(path,value):
            if Path(path).name.startswith('result-'):raise OSError('receipt publication failed')
            return actual(path,value)
        with self.assertRaisesRegex(OSError,'receipt publication'):
            self.invoke(patches=(mock.patch.object(rec,'save',side_effect=fail),))
        self.assertIn(EXECUTION_OUTCOME,self.store.load('orders-report').state)
        self.assertIsNone(self.store.load('orders-report').owner_epoch)
        self.assertFalse((self.run/f'result-{os.getpid()}.json').exists())

    def test_error_after_result_replace_keeps_evidence_but_never_returns_exit_five(self):
        actual=rec.save
        def fail(path,value):
            actual(path,value)
            if Path(path).name.startswith('result-'):raise OSError('after receipt replacement')
        with self.assertRaisesRegex(OSError,'after receipt'):
            self.invoke(patches=(mock.patch.object(rec,'save',side_effect=fail),))
        self.assertIn('paused_expiry',self.result())
        self.assertIsNone(self.store.load('orders-report').owner_epoch)
        # The retained process's non-5 exit remains mandatory despite this file.

    def test_primary_finalization_error_survives_second_close_failure_and_restores_hooks(self):
        class Broken(ClosingDB):
            def close(self):
                self.close_calls += 1
                if self.close_calls==1:raise ValueError('primary close failure')
                self.connection.close();raise OSError('retry close failure')
        original=(socket.socket.connect,socket.socket.connect_ex,socket.socketpair,socket.getaddrinfo)
        self.assertEqual(self.invoke(database=Broken),2)
        result=self.result()
        self.assertEqual(result['error_type'],'ValueError')
        self.assertEqual(result['cleanup_errors'][0]['type'],'OSError')
        self.assertNotIn('paused_expiry',result)
        self.assertNotIn(EXECUTION_OUTCOME,self.store.load('orders-report').state)
        self.assertEqual(original,(socket.socket.connect,socket.socket.connect_ex,socket.socketpair,socket.getaddrinfo))

    def test_sealed_restart_is_rejected_before_sdk_or_claim(self):
        self.assertEqual(self.invoke(),5)
        before=self.store.load('orders-report')
        with mock.patch.object(worker,'setup',side_effect=AssertionError('must not import SDK')):
            with self.assertRaises(task_store.ReconciliationRequired):worker.worker(self.args)
        self.assertEqual(self.store.load('orders-report'),before)

    def test_cancelled_worker_close_failure_is_not_safe_cancellation_exit(self):
        class Broken(ClosingDB):
            def close(self):
                super().close();raise OSError('cancelled cleanup failed')
        self.box.submit(self.cap,'cancel','cancel')
        self.assertEqual(self.invoke(database=Broken),2)
        result=self.result()
        self.assertEqual(result['control_state'],'cancelled')
        self.assertEqual(result['cleanup_errors'][0]['type'],'OSError')
        self.assertNotIn(EXECUTION_OUTCOME,self.store.load('orders-report').state)

    def test_missing_or_wrong_prepared_clock_is_refused_before_claim_or_sdk(self):
        before=self.store.load('orders-report')
        for domain in (None,'unknown'):
            plan=dict(self.plan)
            if domain is None:del plan['deadline_clock']
            else:plan['deadline_clock']=domain
            (self.run/'plan.json').write_text(json.dumps(plan))
            with mock.patch.object(worker,'verify_execution_clock',return_value=CLOCK_ID), \
                    mock.patch.object(worker,'setup',side_effect=AssertionError('SDK must not load')), \
                    mock.patch.object(task_store.TaskStore,'claim',side_effect=AssertionError('must not claim')):
                with self.subTest(domain=domain),self.assertRaises(task_store.ReconciliationRequired):worker.worker(self.args)
            self.assertEqual(self.store.load('orders-report'),before)


if __name__=='__main__':unittest.main()
