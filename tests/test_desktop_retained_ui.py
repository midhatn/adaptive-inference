"""CPU-only fake API fixtures: no real DLL construction, process, window or input."""
from copy import deepcopy
from dataclasses import replace
import threading
import unittest
from unittest import mock

from adaptive_inference.desktop import retained_ui as r
from desktop_support.policy import ForegroundPolicy
from adaptive_inference.desktop.ui_intent import UIBinding, UIIntentGate, VerifiedUIObservation


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.values = {'duplicate': 900, 'wait': r.WAIT_TIMEOUT,
                       'process_identity': (7,80), 'foreground': 100,
                       'root': 100, 'window_identity': (11,7), 'marker': 1,
                       'close': None}
        self.hooks = {}

    def call(self, name, *args, **kwargs):
        self.calls.append((name,args,kwargs))
        if name in self.hooks:
            return self.hooks[name](*args,**kwargs)
        return self.values[name]

    def duplicate(self, handle, **kwargs): return self.call('duplicate',handle,**kwargs)
    def wait(self, handle, timeout): return self.call('wait',handle,timeout)
    def process_identity(self, handle): return self.call('process_identity',handle)
    def foreground(self): return self.call('foreground')
    def root(self, hwnd): return self.call('root',hwnd)
    def window_identity(self, hwnd): return self.call('window_identity',hwnd)
    def marker(self, hwnd, name): return self.call('marker',hwnd,name)
    def close(self, handle): return self.call('close',handle)


def raw(now, *, cpu=0, ram=20, commit=30):
    return {'monotonic_s':now,'foreground':{'hwnd':100,'pid':7,'creation_time_100ns':80,
        'valid':True,'cpu_cores_used':cpu},'session_input_idle_s':0,
        'host':{'ram_available_gib':ram,'commit_available_gib':commit},'errors':[]}


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.now=1.; self.binding=UIBinding('host','session','task',100,7,80)
        self.api=FakeAPI(); self.verifiers=[]

    def make(self, **kwargs):
        verifier=r.RetainedUIVerifier.from_launch(kwargs.pop('binding',self.binding),
            kwargs.pop('handle',800),kwargs.pop('marker_name','Adaptive.UI.session-unique-001'),
            kwargs.pop('marker_value',1),api=kwargs.pop('api',self.api),
            clock=kwargs.pop('clock',lambda:self.now),**kwargs)
        self.verifiers.append(verifier)
        return verifier

    def tearDown(self):
        for verifier in self.verifiers:
            try:verifier.close()
            except Exception:pass  # Tests below explicitly assert intentional failed-close obligations.

    def gate(self, verifier):
        cap=object()
        gate=UIIntentGate(host_epoch='host',capability=cap,
            verify_current=verifier.verify_current,clock=lambda:self.now)
        gate.bind(cap,self.binding)
        gate.activate(cap,session_id='session',task_id='task')
        return gate,cap

    def test_exact_retained_process_root_and_marker_produce_existing_receipt(self):
        verifier=self.make(); receipt=verifier.verify_current(self.binding)
        self.assertEqual(receipt,VerifiedUIObservation(self.binding,1.,True,True))
        self.assertEqual(self.api.calls[0],('duplicate',(800,),
            {'access':0x101000,'inherit':False,'options':0}))
        for name,args,_ in self.api.calls:
            if name in ('wait','process_identity'):self.assertEqual(args[0],900)
            if name=='wait':self.assertEqual(args[1],0)
        verifier.close(); verifier.close()
        self.assertEqual([c[1] for c in self.api.calls if c[0]=='close'],[(900,)])
        self.assertTrue(verifier.status()['duplicate_close_confirmed'])
        self.assertIsNone(verifier.verify_current(self.binding))

    def test_wrong_binding_and_session_do_not_probe(self):
        verifier=self.make(); before=len(self.api.calls)
        for changes in ({'task_id':'other'},{'host_epoch':'other'},{'session_id':'other'},
                        {'hwnd':101},{'pid':8},{'creation_time_100ns':81}):
            self.assertIsNone(verifier.verify_current(replace(self.binding,**changes)))
        self.assertIsNone(verifier.verify_current(dict(hwnd=100)))
        self.assertEqual(len(self.api.calls),before)
        self.assertIsNotNone(verifier.verify_current(self.binding))

    def test_constructor_failure_closes_only_acquired_duplicate(self):
        for name,value in (('wait',0),('process_identity',(7,81)),('root',101),
                           ('window_identity',(0,7)),('marker',0)):
            with self.subTest(name=name):
                api=FakeAPI();api.values[name]=value
                with self.assertRaises(RuntimeError):self.make(api=api)
                self.assertEqual([c[1] for c in api.calls if c[0]=='close'],[(900,)])
        api=FakeAPI();api.hooks['duplicate']=mock.Mock(side_effect=PermissionError('denied'))
        with self.assertRaises(PermissionError):self.make(api=api)
        self.assertFalse(any(c[0]=='close' for c in api.calls))

    def test_constructor_partial_api_exception_preserves_original(self):
        original=OSError('query failed')
        self.api.hooks['window_identity']=mock.Mock(side_effect=original)
        with self.assertRaises(OSError) as got:self.make()
        self.assertIs(got.exception,original)
        self.assertEqual([c[1] for c in self.api.calls if c[0]=='close'],[(900,)])

    def test_constructor_cleanup_failure_keeps_both_errors_and_unavailable_record(self):
        original=OSError('query failed'); cleanup=PermissionError('close failed')
        self.api.hooks['process_identity']=mock.Mock(side_effect=original)
        self.api.hooks['close']=mock.Mock(side_effect=cleanup)
        with self.assertRaises(r.AcquisitionError) as got:self.make()
        error=got.exception
        self.assertIs(error.__cause__,original)
        self.assertIs(error.primary_error,original);self.assertIs(error.cleanup_error,cleanup)
        self.assertEqual(error.verifier.status()['close_error'],'PermissionError')
        self.assertFalse(error.verifier.status()['duplicate_close_confirmed'])
        self.assertIsNone(error.verifier.verify_current(self.binding))
        with self.assertRaises(PermissionError):error.verifier.close()
        self.assertEqual(self.api.hooks['close'].call_count,1)

    def test_failed_close_is_unavailable_unconfirmed_and_never_blindly_retried(self):
        verifier=self.make()
        self.api.hooks['close']=mock.Mock(side_effect=OSError('close uncertain'))
        for _ in range(2):
            with self.assertRaises(OSError):verifier.close()
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertFalse(verifier.status()['duplicate_close_confirmed'])
        self.assertTrue(verifier.status()['duplicate_retained'])
        self.assertEqual(self.api.hooks['close'].call_count,1)

    def test_signalled_process_and_pid_creation_change_permanently_retire(self):
        for name,value in (('wait',0),('process_identity',(8,80)),('process_identity',(7,81))):
            api=FakeAPI(); verifier=self.make(api=api); api.values[name]=value
            self.assertIsNone(verifier.verify_current(self.binding))
            self.assertTrue(verifier.status()['retired'])
            api.values['wait']=r.WAIT_TIMEOUT;api.values['process_identity']=(7,80)
            self.assertIsNone(verifier.verify_current(self.binding))

    def test_unknown_wait_and_incomplete_identity_do_not_claim_exit(self):
        for name,value in (('wait',True),('wait',r.WAIT_FAILED),('wait',128),
                           ('process_identity',None),('process_identity',(True,80)),
                           ('process_identity',(7,0)),('process_identity',(7,80,1))):
            api=FakeAPI();verifier=self.make(api=api);api.values[name]=value
            self.assertIsNone(verifier.verify_current(self.binding))
            self.assertFalse(verifier.status()['retired'])
            self.assertEqual(verifier.reason,'observation_error')

    def test_api_denials_never_authorize_or_prove_process_exit(self):
        for name in ('wait','process_identity','foreground','root','window_identity','marker'):
            with self.subTest(name=name):
                api=FakeAPI();verifier=self.make(api=api)
                api.hooks[name]=mock.Mock(side_effect=PermissionError('fixture denied'))
                self.assertIsNone(verifier.verify_current(self.binding))
                self.assertFalse(verifier.status()['retired'])
                self.assertIsInstance(verifier.last_error,PermissionError)

    def test_other_same_process_window_and_null_foreground_preserve_session_but_deny(self):
        verifier=self.make()
        for value in (101,0,None,True):
            self.api.values['foreground']=value
            self.assertIsNone(verifier.verify_current(self.binding))
            self.assertFalse(verifier.status()['retired'])
        self.api.values['foreground']=100
        self.assertIsNotNone(verifier.verify_current(self.binding))

    def test_foreground_switch_during_sample_does_not_authorize(self):
        verifier=self.make(); values=iter((100,101))
        self.api.hooks['foreground']=lambda:next(values)
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertFalse(verifier.status()['retired'])

    def test_window_creator_root_and_marker_identity_loss_permanently_retire(self):
        for name,value in (('root',0),('root',101),('window_identity',(12,7)),
                           ('window_identity',(11,8)),('window_identity',(0,7)),
                           ('window_identity',None),('marker',0),('marker',2),('marker',True)):
            with self.subTest(name=name,value=value):
                api=FakeAPI();verifier=self.make(api=api);original=api.values[name]
                api.values[name]=value
                self.assertIsNone(verifier.verify_current(self.binding))
                self.assertTrue(verifier.status()['retired'])
                api.values[name]=original
                self.assertIsNone(verifier.verify_current(self.binding))

    def test_marker_loss_during_second_observation_is_latched(self):
        verifier=self.make();values=iter((1,0))
        self.api.hooks['marker']=lambda *_:next(values)
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertTrue(verifier.status()['retired'])

    def test_process_exit_during_final_wait_is_latched(self):
        verifier=self.make();values=iter((r.WAIT_TIMEOUT,0))
        self.api.hooks['wait']=lambda *_:next(values)
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertEqual(verifier.reason,'retained_process_exit')

    def test_wrong_thread_never_reads_closes_or_revokes(self):
        verifier=self.make();before=len(self.api.calls);results=[]
        def other():
            results.append(verifier.verify_current(self.binding))
            for action in (verifier.close,verifier.revoke):
                try:action()
                except Exception as error:results.append(type(error))
        thread=threading.Thread(target=other);thread.start();thread.join(timeout=1)
        self.assertFalse(thread.is_alive());self.assertEqual(results,[None,PermissionError,PermissionError])
        self.assertEqual(len(self.api.calls),before)
        self.assertIsNotNone(verifier.verify_current(self.binding))

    def test_reentrant_close_is_refused_without_closing_handle_during_read(self):
        verifier=self.make();self.api.hooks['foreground']=lambda:verifier.close()
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertFalse(any(c[0]=='close' for c in self.api.calls))
        self.assertFalse(verifier.status()['closed'])
        self.assertIsInstance(verifier.last_error,RuntimeError)

    def test_reentrant_verification_is_refused_and_revoke_prevents_outer_receipt(self):
        verifier=self.make();inner=[]
        def hook():
            inner.append(verifier.verify_current(self.binding));verifier.revoke('host session closed')
            return 100
        self.api.hooks['foreground']=hook
        self.assertIsNone(verifier.verify_current(self.binding))
        self.assertTrue(all(value is None for value in inner))
        self.assertTrue(verifier.status()['retired'])

    def test_raw_input_unchanged_and_cpu_memory_gates_remain_authoritative(self):
        verifier=self.make();gate,_=self.gate(verifier)
        for kwargs,expected in (({},True),({'cpu':.5},False),({'ram':1},False),({'commit':1},False)):
            with self.subTest(kwargs=kwargs):
                sample=raw(self.now,**kwargs);original=deepcopy(sample)
                policy=ForegroundPolicy(ui_intent=gate,recovery_s=0,engage_samples=1)
                self.assertEqual(policy.observe(sample,self.now),expected)
                self.assertEqual(sample,original)

    def test_no_active_intent_does_not_call_verifier(self):
        verifier=self.make();before=len(self.api.calls);cap=object()
        gate=UIIntentGate(host_epoch='host',capability=cap,verify_current=verifier.verify_current,clock=lambda:self.now)
        gate.bind(cap,self.binding)
        self.assertFalse(gate.matches(raw(1),1));self.assertEqual(len(self.api.calls),before)

    def test_gate_revocation_during_callback_cannot_authorize(self):
        verifier=self.make();gate,cap=self.gate(verifier)
        def hook():gate.revoke(cap,'session');return 100
        self.api.hooks['foreground']=hook
        self.assertFalse(gate.matches(raw(1),1))

    def test_fresh_observation_after_minutes_retains_task_intent(self):
        verifier=self.make();gate,_=self.gate(verifier)
        self.assertTrue(gate.matches(raw(1),1))
        self.now=721.
        self.assertTrue(gate.matches(raw(self.now),self.now))

    def test_slow_probe_uses_initial_stamp_and_gate_rejects_age(self):
        verifier=self.make();gate,_=self.gate(verifier)
        self.api.hooks['foreground']=lambda:setattr(self,'now',self.now+2) or 100
        receipt=verifier.verify_current(self.binding)
        self.assertEqual(receipt.observed_at_monotonic,1.)
        self.assertGreater(self.now-receipt.observed_at_monotonic,1)
        sample=raw(self.now);self.assertFalse(gate.matches(sample,self.now))

    def test_future_regressed_and_invalid_clock_refuse(self):
        verifier=self.make(clock=lambda:2.)
        gate,_=self.gate(verifier)
        self.assertFalse(gate.matches(raw(1),1))
        for bad in (0.,True,None,float('nan'),float('inf'),10**1000):
            api=FakeAPI();verifier=self.make(api=api)
            self.now=1.;self.assertIsNotNone(verifier.verify_current(self.binding))
            self.now=bad
            self.assertIsNone(verifier.verify_current(self.binding))
            self.assertTrue(verifier.status()['retired'])

    def test_pause_terminal_and_session_revoke_do_not_change_task_or_raw_sensor(self):
        for action in ('deactivate','terminal','revoke'):
            verifier=self.make(api=FakeAPI());gate,cap=self.gate(verifier)
            sample=raw(1);original=deepcopy(sample)
            self.assertTrue(gate.matches(sample,1))
            if action=='deactivate':gate.deactivate(cap)
            elif action=='terminal':gate.terminal(cap,'task')
            else:gate.revoke(cap,'session')
            self.assertFalse(gate.matches(sample,1));self.assertEqual(sample,original)

    def test_invalid_constructor_inputs_never_acquire_handle(self):
        for kwargs in ({'handle':0},{'handle':True},{'handle':-1},{'marker_name':'short'},
                       {'marker_name':'x'*129},{'marker_name':'x'*17+'\0'},
                       {'marker_value':0},{'marker_value':True},{'clock':None},
                       {'binding':None}):
            with self.subTest(kwargs=kwargs):
                api=FakeAPI()
                with self.assertRaises((TypeError,ValueError)):self.make(api=api,**kwargs)
                self.assertEqual(api.calls,[])


if __name__=='__main__':unittest.main()
