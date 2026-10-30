"""Selected repeated expiry with real SQLite; scripted SDK/transport edges only."""
import asyncio
from copy import deepcopy
import json
import os
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME, WAIT_EXPIRY_SCHEMA
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding, HostContinuation
from adaptive_inference.desktop.hermes import recovery as rec, run_recovery as worker, service_stop, admission
from adaptive_inference.desktop.hermes.continuation_worker import SelectedWorker
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_store import ReconciliationRequired
import test_continuation_worker as existing


class SelectedWaitTests(unittest.TestCase):
    def setUp(self):
        self.f = existing.SelectedWorkerTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        # Use the production admission branch and the selected execution's
        # deadline. The legacy simulation branch has its own fixed 900 clock.
        self.f.f.plan['fixture'] = False
        rec.save(self.f.run/'plan.json', self.f.f.plan)
        self.f.original_bytes = (self.f.run/'plan.json').read_bytes()
        self.f.authorize(report=True, requests=1)
        self.original = self.f.store.load(self.f.identity.task_id)
        self.f.ready()
        self.f.f.args.stop_request_id = 'host-stop'
        self.f.f.now = self.f.grant['deadline_monotonic'] - 1
        self.effects = (self.f.run/'effect-receipts.jsonl').read_bytes()
        self.report = (self.f.run/'work/report.json').read_bytes()

    def wait_patches(self, *, close_error=False, stop=False):
        outer, f = self, self.f
        class Boundary:
            def __init__(self, *a): self.rows=[]; self.steps={'parent':0}; self.seen=set()
        base = SimpleNamespace(Boundary=Boundary, git=lambda *a: worker.SDK_REV if a[0]=='rev-parse' else '',
                               snapshot=lambda a: {'fixture':'scripted SDK admission wait'})
        class Provider(admission.Provider):
            def __init__(self, *, base_url, model, instance, boundary, deadline, **kwargs):
                f.assert_owned()
                self.base_url,self.model,self.instance=base_url,model,instance
                self.boundary,self.deadline=boundary,deadline
                self.clock=lambda:f.f.now
                self.current_attempt=self.body_sha256=None
                self.status_reader=lambda: {'service':'adaptive-inference','instance':instance,
                    'scheduler':{'active':False,'pending':0,'closing':False,'backend_completion_uncertain':False},
                    'resources':{'admission_allowed':False}}
                def forbidden(**request): raise AssertionError('Waiting request dispatched')
                self.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=forbidden)))
                def advance(seconds):
                    f.f.now += seconds
                    if stop and not getattr(self,'stop_queued',False):
                        self.stop_queued=True;f.box.submit(f.cap,'host-stop','pause')
                self.sleep=advance
            def close(self): f.assert_owned()
        class Agent:
            def __init__(self, **kwargs):
                f.assert_owned()
                self.session_id=kwargs['session_id'];self._session_db=kwargs['session_db']
                self._active_session_turn_lease_holder='selected-holder'
                self.activity=[]
            def _touch_activity(self,label):
                self.activity.append(label)  # Scripted SDK activity; no watchdog thread.
            def run_conversation(self, prompt, conversation_history=None):
                outer.assertEqual(prompt,worker.CONTINUE)
                outer.assertEqual(conversation_history,rec.native_history(self._session_db,'native'))
                self._session_db.append({'role':'user','content':prompt})
                request={'model':worker.MODEL,'messages':rec.native_history(self._session_db,'native'),
                         'stream':False,'max_tokens':10923,'extra_body':worker.QUALITY}
                outer.pending=deepcopy(request)
                rec.ACTIVE.llm(request,None,session_id='native')
                raise AssertionError('Waiting request returned')
            def close(self):
                f.assert_owned();self._active_session_turn_lease_holder=None
                if close_error: raise OSError('selected wait close failed')
        sdk=ModuleType('run_agent');sdk.AIAgent=Agent
        plugins=ModuleType('hermes_cli.plugins')
        plugins.get_plugin_manager=lambda:SimpleNamespace(_plugins={'recovery-checkpoint':SimpleNamespace(enabled=True,error=None)})
        interrupt=ModuleType('tools.interrupt');interrupt.is_interrupted=lambda:False
        return (mock.patch.object(worker,'setup',return_value=(rec,base)),
                mock.patch.object(admission,'Provider',Provider),
                mock.patch.dict(sys.modules,{'run_agent':sdk,'hermes_cli.plugins':plugins,'tools.interrupt':interrupt}))

    def expire(self, *, extra=(), close_error=False, stop=False):
        class DB(existing.existing.ClosingDB):
            def session_turn_lease_expires_at(self, session, holder):
                if (session,holder)!=('native','selected-holder'):raise AssertionError('Unexpected lease')
                return time.time()+1000
        return self.f.f.invoke(database=DB, patches=(*self.wait_patches(close_error=close_error,stop=stop),*extra))

    def verify(self, code=6, *, mutate=None):
        async def run():
            f=self.f
            child=SimpleNamespace(pid=os.getpid(),poll=lambda:code,wait=lambda:code)
            binding=SelectedWorkerStopBinding(child,f.run,f.box,grant=f.grant,authority=f.authority,
                requester_capability=f.cap,capability=object(),stop_request_id='host-stop',
                original=self.original,deadline_monotonic=f.grant['deadline_monotonic'],deadline_clock=CLOCK_ID,
                model=worker.MODEL,quality=worker.QUALITY,fence=lambda:None)
            if mutate:mutate(binding)
            with mock.patch('adaptive_inference.desktop.hermes.service_stop.execution_now',return_value=f.f.now):
                return binding._verify_exit(code)
        return asyncio.run(run())

    def test_selected_wait_expiry_completes_exact_lifetime_and_preserves_effects(self):
        self.assertEqual(self.expire(),6,self.f.result())
        cp=self.f.store.load(self.f.identity.task_id)
        self.assertEqual(cp.state[EXECUTION_OUTCOME]['schema'],WAIT_EXPIRY_SCHEMA)
        self.assertEqual(cp.state['pending_request'],self.pending)
        self.assertEqual((cp.state['requests'],cp.state['attempts'],cp.state['admission_attempts']),(1,1,1))
        self.assertIsNone(cp.owner_epoch);self.assertIsNone(cp.operation)
        self.assertIsNone(self.f.store.load(self.f.authority.task_id).operation)
        self.assertEqual(self.verify(),'admission_wait_budget_expired')
        self.assertEqual((self.f.run/'effect-receipts.jsonl').read_bytes(),self.effects)
        self.assertEqual((self.f.run/'work/report.json').read_bytes(),self.report)
        self.f.unchanged_original()

    def test_selected_wait_result_byte_change_refused(self):
        self.assertEqual(self.expire(),6)
        path=self.f.diagnostics/f'result-{os.getpid()}.json';raw=path.read_bytes()
        path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ReconciliationRequired,'exact result'):self.verify()
        path.write_bytes(raw);self.assertEqual(self.verify(),'admission_wait_budget_expired')

    def test_original_binding_and_changed_selected_identity_cannot_accept_wait(self):
        self.assertEqual(self.expire(),6)
        with self.assertRaises((rec.RecoveryStop,ReconciliationRequired)):
            self.verify(mutate=lambda b:b.grant.__setitem__('execution_generation',99))
        with self.assertRaises((rec.RecoveryStop,ReconciliationRequired)):
            self.verify(mutate=lambda b:b.grant['payload'].__setitem__('successor_id','wrong-execution'))
        with self.assertRaisesRegex(rec.RecoveryStop,'Original admission'):
            service_stop.WorkerStopBinding._admission_wait_identity(SimpleNamespace(),self.f.store.load(self.f.identity.task_id))

    def test_failed_selected_wait_cleanup_leaves_authority_fenced(self):
        with self.assertRaisesRegex(ReconciliationRequired,'cleanup is unconfirmed'):self.expire(close_error=True)
        self.assertNotIn('admission_wait_expiry',self.f.result())
        self.f.assert_fenced()

    def test_stop_before_selected_wait_deadline_keeps_distinct_cooperative_outcome(self):
        self.assertEqual(self.expire(stop=True),4,self.f.result())
        self.assertEqual(self.verify(4),'service_stopped')
        cp=self.f.store.load(self.f.identity.task_id)
        self.assertNotIn(EXECUTION_OUTCOME,cp.state)
        self.assertEqual(cp.state['pending_request'],self.pending)
        self.assertEqual(cp.state['requests'],1)

    def test_wait_result_publication_failure_keeps_exact_lifetime_unfinished(self):
        original=rec.save
        def fail(path,value):
            if path==self.f.diagnostics/f'result-{os.getpid()}.json':
                raise OSError('selected wait result failed')
            return original(path,value)
        with self.assertRaisesRegex(OSError,'selected wait result failed'):
            self.expire(extra=(mock.patch.object(rec,'save',side_effect=fail),))
        self.f.assert_fenced()

    def test_identity_candidate_is_pure_but_exit_still_requires_durable_authority(self):
        self.assertEqual(self.expire(),6)
        async def run():
            f=self.f
            child=SimpleNamespace(pid=os.getpid(),poll=lambda:6,wait=lambda:6)
            binding=SelectedWorkerStopBinding(child,f.run,f.box,grant=f.grant,authority=f.authority,
                requester_capability=f.cap,capability=object(),stop_request_id='host-stop',
                original=self.original,deadline_monotonic=f.grant['deadline_monotonic'],deadline_clock=CLOCK_ID,
                model=worker.MODEL,quality=worker.QUALITY,fence=lambda:None)
            cp=f.store.load(f.identity.task_id)
            with mock.patch.object(f.authority,'lookup',side_effect=OSError('durable read unavailable')):
                binding._admission_wait_identity(cp)
                with mock.patch('adaptive_inference.desktop.hermes.service_stop.execution_now',return_value=f.f.now):
                    with self.assertRaisesRegex(OSError,'durable read unavailable'):binding._verify_exit(6)
        asyncio.run(run())

    def test_effect_change_after_wait_close_cannot_complete_lifetime(self):
        original=service_stop.close_safe_resources
        def changed(*a,**k):
            proof=original(*a,**k)
            (self.f.run/'effect-receipts.jsonl').write_text('[]\n')
            return proof
        with self.assertRaisesRegex(ReconciliationRequired,'cleanup is unconfirmed'):
            self.expire(extra=(mock.patch.object(service_stop,'close_safe_resources',side_effect=changed),))
        self.f.assert_fenced()

    def next_grant(self):
        f=self.f;old=f.store.load(f.identity.task_id)
        generation=f.grant['execution_generation']+1
        identity=DemandIdentity('registration-'+str(generation),'execution-'+str(generation),'worker',existing.existing.NOW)
        payload=f.authority.request(command_id='continue-'+str(generation),predecessor_id=old.task_id,
            predecessor_revision=old.revision,predecessor_seal_sha256=rec.digest(old.state[EXECUTION_OUTCOME]),
            successor_id=identity.task_id,identity=identity,host_generation=f.host,
            release_evidence_sha256=rec.digest('component synthetic retained release'))
        cp=f.store.load(f.authority.task_id)
        with f.store.claim(cp.task_id,expected_revision=cp.revision) as owned:grant=f.authority.authorize(owned,payload)
        return old,identity,payload,grant

    def use_grant(self,identity,payload,grant):
        f=self.f;f.identity,f.payload,f.grant=identity,payload,grant
        rec.save(f.grant_file,grant);f.f.args.deadline_monotonic=grant['deadline_monotonic']
        f.cap=object();f.box=Mailbox(DemandRegistry((Registration(f.store,identity),)),identity.registration_id,requester_capability=f.cap)
        f.box.submit(f.cap,'fresh-pause','pause');f.diagnostics=f.run/'executions'/identity.task_id
        self.original=f.store.load(identity.task_id);f.ready();f.f.args.stop_request_id='host-stop'
        f.f.now=grant['deadline_monotonic']-1

    def test_second_wait_expiry_and_third_execution_completion_keep_original_effect(self):
        self.assertEqual(self.expire(),6)
        first,identity,payload,grant=self.next_grant()
        self.assertEqual(grant['pending_request_disposition']['request_sha256'],rec.digest(first.state['pending_request']))
        self.use_grant(identity,payload,grant)
        self.assertEqual(self.expire(),6,self.f.result())
        self.assertEqual(self.verify(),'admission_wait_budget_expired')
        self.assertEqual(self.f.store.load(first.task_id),first)
        second,identity,payload,grant=self.next_grant();self.use_grant(identity,payload,grant)
        self.assertEqual(self.f.f.invoke(patches=self.f.normal_patches()),0,self.f.result())
        self.assertEqual(self.verify(0),'task_completed')
        self.assertEqual(self.f.store.load(first.task_id),first)
        self.assertEqual(self.f.store.load(second.task_id),second)
        self.assertEqual((self.f.run/'effect-receipts.jsonl').read_bytes(),self.effects)
        self.assertEqual((self.f.run/'work/report.json').read_bytes(),self.report)
        self.assertEqual(self.f.store.load(identity.task_id).state['requests'],1)

    def test_committed_unlaunched_successor_after_wait_has_distinct_safe_stop(self):
        self.assertEqual(self.expire(),6)
        outcome=self.verify()
        old,identity,payload,grant=self.next_grant()
        host=object.__new__(HostContinuation)
        record={'committed':True,'launch_attempted':False,'child':None,'binding':None,
                'grant':grant,'authority':self.f.authority,'payload':payload,
                'release':{'worker_joined':True,'outcome':outcome}}
        host.current=record
        self.assertEqual(host.verify_unlaunched(record)['outcome'],'selected_not_launched')
        record['launch_attempted']=True
        with self.assertRaises(ReconciliationRequired):host.verify_unlaunched(record)
