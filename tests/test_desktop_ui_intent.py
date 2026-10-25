"""CPU-only identity/clock/policy fixtures; no WinAPI, window or process launch."""
from copy import deepcopy
from dataclasses import replace
import threading
import unittest

from desktop_support.policy import ForegroundPolicy
from adaptive_inference.desktop.ui_intent import UIBinding, UIIntentGate, VerifiedUIObservation


from adaptive_inference import handoff as ORIGINAL


def sample(now, *, hwnd=100, pid=7, creation=80, idle=0, cpu=0, ram=20, commit=30):
    return {'monotonic_s':now, 'foreground':{'hwnd':hwnd, 'pid':pid,
        'creation_time_100ns':creation, 'valid':True, 'cpu_cores_used':cpu},
        'session_input_idle_s':idle, 'host':{'ram_available_gib':ram,
        'commit_available_gib':commit}, 'errors':[]}


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.
        self.capability = object()
        self.binding = UIBinding('host-epoch', 'ui-session', 'task', 100, 7, 80)
        self.calls = []
        def verify(binding):
            self.calls.append(binding)
            return VerifiedUIObservation(binding, self.now, True, True)
        self.verify = verify
        self.gate = self.make_gate()
        self.gate.bind(self.capability, self.binding)

    def make_gate(self, **kwargs):
        return UIIntentGate(host_epoch='host-epoch', capability=self.capability,
            verify_current=kwargs.pop('verify_current', self.verify), clock=lambda:self.now, **kwargs)

    def activate(self, gate=None, **kwargs):
        return (gate or self.gate).activate(self.capability, session_id='ui-session',
            task_id='task', **kwargs)

    def policy(self, **kwargs):
        return ForegroundPolicy(ui_intent=self.gate, recovery_s=kwargs.pop('recovery_s',0),
            engage_samples=1, **kwargs)

    def test_binding_without_explicit_activation_is_not_permission(self):
        self.assertFalse(self.gate.matches(sample(1),1))
        self.assertFalse(self.policy().observe(sample(1),1))
        self.assertEqual(self.calls,[])
        self.activate()
        self.assertTrue(self.policy().observe(sample(1),1))

    def test_sample_boolean_or_receipt_cannot_grant_permission(self):
        raw=sample(1); raw['trusted_ui']=True
        raw['foreground']['verified']=True
        self.assertFalse(self.policy().observe(raw,1))
        self.activate()
        for value in (True, {'binding':self.binding,'process_alive':True}, None):
            with self.subTest(value=value):
                gate=self.make_gate(verify_current=lambda binding:value)
                gate.bind(self.capability,self.binding);self.activate(gate)
                self.assertFalse(gate.matches(raw,1))

    def test_exact_window_and_process_identity_all_required(self):
        self.activate()
        for kwargs in ({'hwnd':101}, {'pid':8}, {'creation':81}, {'hwnd':None}, {'hwnd':True}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.gate.matches(sample(1,**kwargs),1))
                self.assertFalse(self.policy().observe(sample(1,**kwargs),1))
        missing=sample(1);del missing['foreground']['hwnd']
        self.assertFalse(self.gate.matches(missing,1))

    def test_verifier_binding_alive_and_window_must_be_exact(self):
        changes=({'host_epoch':'other'}, {'session_id':'other'}, {'task_id':'other'},
                 {'hwnd':101}, {'pid':8}, {'creation_time_100ns':81})
        receipts=[VerifiedUIObservation(replace(self.binding,**change),1,True,True)
                  for change in changes]
        receipts += [VerifiedUIObservation(self.binding,1,False,True),
                     VerifiedUIObservation(self.binding,1,True,False),
                     VerifiedUIObservation(self.binding,1,1,True)]
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                gate=self.make_gate(verify_current=lambda binding:receipt)
                gate.bind(self.capability,self.binding);self.activate(gate)
                self.assertFalse(gate.matches(sample(1),1))

    def test_stale_future_malformed_receipt_and_exception_fail_closed(self):
        for stamp in (-1,0,2,None,True,float('nan'),float('inf'),10**1000):
            gate=self.make_gate(verify_current=lambda binding:VerifiedUIObservation(binding,stamp,True,True))
            gate.bind(self.capability,self.binding);self.activate(gate)
            self.assertFalse(gate.matches(sample(1),1))
        def broken(binding):raise OSError('Fixture unavailable identity')
        gate=self.make_gate(verify_current=broken)
        gate.bind(self.capability,self.binding);self.activate(gate)
        self.assertFalse(gate.matches(sample(1),1))

    def test_sample_age_future_pre_activation_and_errors_fail_closed(self):
        self.activate()
        for raw in (sample(0),sample(2),None,{},dict(sample(1),errors=['fixture'])):
            self.assertFalse(self.gate.matches(raw,1))
        self.now=3
        self.assertFalse(self.gate.matches(sample(1),3))
        self.assertFalse(self.gate.matches(sample(3),4))
        self.assertFalse(self.gate.matches(sample(3),1))

    def test_stale_observation_closes_classification_without_cancelling_intent(self):
        self.activate()
        policy=self.policy(); raw=sample(1)
        self.assertTrue(policy.observe(raw,1))
        self.now=1.5
        self.assertTrue(policy.fresh(self.now))
        self.now=2.1
        self.assertFalse(policy.fresh(self.now))
        self.assertFalse(policy.observe(raw,self.now))
        self.assertEqual(policy.reason,'activity_stale')
        self.assertIsNotNone(self.gate._active)
        self.assertTrue(self.gate.matches(sample(self.now),self.now))

    def test_task_lifetime_intent_with_fresh_observations_during_long_request(self):
        self.activate()
        original=self.gate._active
        # Twelve minutes of simulated live UI observations, no sleep/process.
        for now in range(1,722,20):
            self.now=float(now)
            self.assertTrue(self.gate.matches(sample(self.now),self.now))
            self.assertEqual(self.gate._active,original)
        self.assertFalse(hasattr(self.gate,'renew'))

    def test_fresh_verification_cannot_reopen_paused_or_terminal_intent(self):
        self.activate()
        self.gate.deactivate(self.capability)
        self.now=300
        self.assertFalse(self.gate.matches(sample(self.now),self.now))
        self.activate();self.gate.terminal(self.capability,'task')
        self.now=600
        self.assertFalse(self.gate.matches(sample(self.now),self.now))

    def test_regressed_verifier_receipt_and_unknown_gap_do_not_reuse_dwell(self):
        self.activate();policy=self.policy(recovery_s=.5)
        self.assertFalse(policy.observe(sample(1),1))
        self.now=1.5
        self.assertTrue(policy.observe(sample(1.5),1.5))
        self.gate._verify=lambda binding:VerifiedUIObservation(binding,1.4,True,True)
        self.assertFalse(policy.fresh(1.5));self.assertFalse(policy.allowed)
        self.gate._verify=self.verify
        self.assertFalse(policy.observe(sample(1.5),1.5))
        self.now=1.6
        self.assertFalse(policy.observe(sample(1.6),1.6))
        self.now=2.1
        self.assertTrue(policy.observe(sample(2.1),2.1))

    def test_clock_regression_and_invalid_clock_require_new_gate(self):
        for invalid in (.5, None, True, float('inf'), 10**1000):
            self.now=1;gate=self.make_gate();gate.bind(self.capability,self.binding);self.activate(gate)
            self.assertTrue(gate.matches(sample(1),1))
            self.now=invalid
            self.assertFalse(gate.matches(sample(1),1))
            self.now=2
            self.assertFalse(gate.matches(sample(2),2))
            with self.assertRaises(ValueError):self.activate(gate)

    def test_deactivate_revoke_and_terminal_do_not_replay_cached_permission(self):
        self.activate();policy=self.policy();raw=sample(1)
        self.assertTrue(policy.observe(raw,1))
        self.gate.deactivate(self.capability)
        self.assertFalse(policy.fresh(1));self.assertFalse(policy.observe(raw,1))
        self.now=1.1;self.activate()
        self.assertTrue(self.policy().observe(sample(1.1),1.1))
        self.gate.revoke(self.capability,'ui-session')
        with self.assertRaises(ValueError):self.activate()
        with self.assertRaises(ValueError):self.gate.bind(self.capability,self.binding)
        second=replace(self.binding,session_id='new-session')
        self.gate.bind(self.capability,second)
        self.gate.activate(self.capability,session_id='new-session',task_id='task')
        self.gate.terminal(self.capability,'task')
        self.assertFalse(self.gate.matches(sample(1.1),1.1))
        with self.assertRaises(ValueError):
            self.gate.bind(self.capability,replace(second,session_id='third-session'))

    def test_replacement_retires_old_session_and_changed_identity_rejected(self):
        self.activate()
        with self.assertRaises(ValueError):
            self.gate.bind(self.capability,replace(self.binding,hwnd=101))
        new=replace(self.binding,session_id='second',hwnd=101)
        self.gate.bind(self.capability,new)
        with self.assertRaises(ValueError):self.activate()
        with self.assertRaises(ValueError):self.gate.bind(self.capability,self.binding)
        self.gate.activate(self.capability,session_id='second',task_id='task')
        self.assertFalse(self.gate.matches(sample(1),1))
        self.assertTrue(self.gate.matches(sample(1,hwnd=101),1))

    def test_session_task_limits_do_not_forget_retired_or_terminal_ids(self):
        gate=self.make_gate(max_sessions=2,max_tasks=2)
        gate.bind(self.capability,self.binding);gate.terminal(self.capability,'task')
        second=replace(self.binding,session_id='second',task_id='second-task')
        gate.bind(self.capability,second);gate.revoke(self.capability,'second')
        with self.assertRaises(ValueError):
            gate.bind(self.capability,replace(second,session_id='third'))
        with self.assertRaises(ValueError):
            gate.bind(self.capability,replace(self.binding,session_id='fourth'))
        gate=self.make_gate(max_sessions=3,max_tasks=1)
        gate.bind(self.capability,self.binding);gate.revoke(self.capability,'ui-session')
        with self.assertRaises(ValueError):gate.bind(self.capability,second)

    def test_capability_task_host_and_owner_thread_are_required(self):
        with self.assertRaises(PermissionError):self.gate.deactivate(object())
        with self.assertRaises(ValueError):self.gate.bind(self.capability,replace(self.binding,host_epoch='old-host'))
        with self.assertRaises(ValueError):
            self.gate.activate(self.capability,session_id='ui-session',task_id='different')
        self.activate();results=[]
        def foreign():
            results.append(self.gate.matches(sample(1),1))
            try:self.gate.deactivate(self.capability)
            except Exception as exc:results.append(type(exc))
        worker=threading.Thread(target=foreign);worker.start();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(results,[False,PermissionError])
        ended=[]
        def create_then_exit():
            gate=self.make_gate();gate.bind(self.capability,self.binding);self.activate(gate)
            ended.append(gate)
        creator=threading.Thread(target=create_then_exit);creator.start();creator.join(2)
        self.assertFalse(creator.is_alive());self.assertEqual(len(ended),1)
        later=[]
        successor=threading.Thread(target=lambda:later.append(ended[0].matches(sample(1),1)))
        successor.start();successor.join(2)
        self.assertFalse(successor.is_alive());self.assertEqual(later,[False])

    def test_verifier_cannot_race_revoke_or_exceed_freshness_deadline(self):
        def revoke(binding):
            self.gate.deactivate(self.capability)
            return VerifiedUIObservation(binding,1,True,True)
        self.gate=self.make_gate(verify_current=revoke)
        self.gate.bind(self.capability,self.binding);self.activate()
        self.assertFalse(self.gate.matches(sample(1),1))
        def slow(binding):
            self.now=3
            return VerifiedUIObservation(binding,1,True,True)
        self.gate=self.make_gate(verify_current=slow)
        self.gate.bind(self.capability,self.binding);self.activate()
        self.assertFalse(self.gate.matches(sample(1),1))

    def test_own_input_never_bypasses_cpu_memory_or_raw_sensor_values(self):
        self.activate()
        cases=[({'cpu':None},'activity_cpu_warming'),({'cpu':.3},'foreground_activity'),
               ({'cpu':.1},'foreground_recovery_margin'),({'ram':1},'host_memory_pressure'),
               ({'commit':1},'host_memory_pressure')]
        for kwargs, reason in cases:
            raw=sample(1,**kwargs);before=deepcopy(raw);policy=self.policy()
            self.assertFalse(policy.observe(raw,1));self.assertEqual(policy.reason,reason)
            self.assertEqual(raw,before)
        raw=sample(1);before=deepcopy(raw)
        self.assertTrue(self.policy().observe(raw,1));self.assertEqual(raw,before)
        self.assertEqual(raw['session_input_idle_s'],0)

    def test_recovery_dwell_and_foreground_switch_remain_effective(self):
        self.activate();policy=self.policy(recovery_s=1)
        for now, expected in ((1,False),(1.5,False),(2,True)):
            self.now=now;self.assertEqual(policy.observe(sample(now),now),expected)
        self.now=2.1
        self.assertFalse(policy.observe(sample(2.1,hwnd=200),2.1))
        self.assertTrue(policy.yield_requested)
        self.now=2.2
        self.assertFalse(policy.observe(sample(2.2),2.2))
        self.assertEqual(policy.reason,'foreground_recovery_dwell')

    def test_no_intent_default_matches_preserved_policy_state(self):
        for kwargs in ({},{'ignored_identities':[(7,80)]},{'recovery_s':0,'engage_samples':1}):
            old,new=ORIGINAL.ForegroundPolicy(**kwargs),ForegroundPolicy(**kwargs)
            for i in range(40):
                now=i*.2
                raw=sample(now,idle=(0 if i%7==0 else 120),cpu=(None if i%11==0 else (i%4)*.1),
                           ram=(2 if i%13==0 else 20),hwnd=100+i%2)
                self.assertEqual(old.observe(deepcopy(raw),now),new.observe(deepcopy(raw),now))
                for key,value in vars(old).items():self.assertEqual(value,getattr(new,key),key)
                self.assertEqual(old.fresh(now),new.fresh(now))

    def test_invalid_identity_and_bound_arguments_refused(self):
        for kwargs in ({'hwnd':True},{'pid':2**32},{'creation_time_100ns':0},
                       {'session_id':'x'*129},{'task_id':'two words'}):
            with self.assertRaises(ValueError):replace(self.binding,**kwargs)
        for kwargs in ({'max_sessions':0},{'max_tasks':1001},{'max_age_s':0},
                       {'max_age_s':float('inf')}):
            with self.assertRaises(ValueError):self.make_gate(**kwargs)


if __name__=='__main__':unittest.main()
