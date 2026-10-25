"""Existing progress, transport and policy-consumer fixtures; no GUI or model."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.ui_intent import UIBinding, UIIntentGate, VerifiedUIObservation
from adaptive_inference.desktop.ui_progress import CooperativeProgress
from adaptive_inference.desktop.control_transport import ControlTransport, PreparedTask
from adaptive_inference.desktop.serial_listener import SerialListener
from adaptive_inference.desktop.foreground_policy import ForegroundPolicy
import test_desktop_control_transport as fixtures


def sample(now, *, host_cpu=.25, cpu=.20, idle=0, pid=7, hwnd=100, creation=80,
           ram=20, commit=20):
    return {'monotonic_s':now, 'errors':[], 'session_input_idle_s':idle,
        'foreground':{'valid':True,'hwnd':hwnd,'pid':pid,
            'creation_time_100ns':creation,'cpu_cores_used':cpu},
        'host':{'cpu_busy_fraction':host_cpu,'ram_available_gib':ram,'commit_available_gib':commit}}



class GateFixture:
    def __init__(self):
        self.now=1.; self.cap=object(); self.valid=True
        self.binding=UIBinding('host','session','task',100,7,80)
        self.gate=UIIntentGate(host_epoch='host',capability=self.cap,clock=lambda:self.now,
            verify_current=lambda binding:VerifiedUIObservation(binding,self.now,True,self.valid))
        self.progress=CooperativeProgress(self.gate,self.cap)
        self.gate.bind(self.cap,self.binding)
        self.activate()

    def activate(self):
        self.gate.activate(self.cap,session_id='session',task_id='task')

    def exchange(self, arrival, *, elapsed=.05):
        self.now=arrival; ticket=self.progress.begin('session')
        self.now=arrival+elapsed; return self.progress.complete(ticket)

    def pair(self):
        self.exchange(1); self.exchange(2)

    def policy(self):
        return ForegroundPolicy(ui_intent=self.gate,cooperative_progress=self.progress)

    def advance(self, policy, stamp, **changes):
        self.exchange(stamp-.05); self.now=stamp
        return policy.observe(sample(stamp,**changes),stamp)

    def allowed_policy(self):
        self.pair(); policy=self.policy()
        for i in range(6):self.advance(policy,2.1+i)
        assert policy.allowed
        return policy



class ProgressTests(unittest.TestCase):
    def setUp(self):self.f=GateFixture()

    def test_two_successes_following_confirmed_closure_are_required(self):
        f=self.f; ticket=f.progress.begin('session')
        self.assertFalse(f.progress.healthy(sample(f.now),f.now))
        f.now=1.05; self.assertTrue(f.progress.complete(ticket))
        self.assertFalse(f.progress.healthy(sample(f.now),f.now))
        f.exchange(2); self.assertTrue(f.progress.healthy(sample(f.now),f.now))

    def test_exact_boundaries_and_no_old_ticket_replay(self):
        f=self.f; f.exchange(1,elapsed=.5)
        f.now=4; ticket=f.progress.begin('session'); f.now=4.5
        self.assertTrue(f.progress.complete(ticket))
        self.assertTrue(f.progress.healthy(sample(f.now),f.now))
        f.now=7; self.assertTrue(f.progress.healthy(sample(f.now),f.now))
        self.assertFalse(f.progress.complete(ticket))
        self.assertFalse(f.progress.healthy(sample(f.now),f.now))

    def test_slow_completion_is_not_health(self):
        f=self.f; f.exchange(1,elapsed=.500001)
        self.assertEqual(f.progress.consecutive,0)
        self.assertIsNone(f.progress.completed)
        self.assertGreater(f.progress.snapshot()['totals']['max_observed_exchange_s'],.5)
        self.assertEqual(f.progress.snapshot()['totals']['max_successful_exchange_s'],0)

    def test_long_arrival_gap_restarts_pair(self):
        f=self.f; f.pair(); f.exchange(4.550001)
        self.assertEqual(f.progress.consecutive,1)
        self.assertGreater(f.progress.snapshot()['totals']['max_observed_arrival_gap_s'],2.5)

    def test_stale_health_expires_without_new_request(self):
        f=self.f; f.pair(); f.now=4.550001
        self.assertFalse(f.progress.healthy(sample(f.now),f.now))
        self.assertEqual(f.progress.consecutive,0)
        self.assertGreater(f.progress.snapshot()['totals']['max_observed_completed_age_s'],2.5)

    def test_inflight_status_timeout_expires_previous_health(self):
        f=self.f; f.pair(); f.now=2.2; f.progress.begin('session'); f.now=2.700001
        self.assertFalse(f.progress.healthy(sample(f.now),f.now))
        self.assertEqual(f.progress.reason,'progress_exchange_timeout')

    def test_activation_during_completion_rejects_old_generation(self):
        f=self.f; f.now=2; ticket=f.progress.begin('session'); f.activate(); f.now=2.05
        self.assertFalse(f.progress.complete(ticket))
        self.assertEqual(f.progress.consecutive,0)

    def test_deactivation_revocation_terminal_and_binding_change_invalidate(self):
        for action in ('deactivate','revoke','terminal','bind'):
            with self.subTest(action=action):
                f=GateFixture();f.pair()
                if action=='deactivate':f.gate.deactivate(f.cap)
                elif action=='revoke':f.gate.revoke(f.cap,'session')
                elif action=='terminal':f.gate.terminal(f.cap,'task')
                else:f.gate.bind(f.cap,replace(f.binding,session_id='next',pid=8))
                self.assertIsNone(f.progress.completed)

    def test_clock_regression_and_nonfinite_clock_revoke(self):
        for now in (1.,float('nan'),float('inf')):
            with self.subTest(now=now):
                f=GateFixture();f.pair();f.now=now
                self.assertIsNone(f.progress.begin('session'))
                self.assertIsNone(f.gate._active)
                self.assertEqual(f.progress.consecutive,0)

    def test_overlap_cannot_publish_replaced_ticket(self):
        f=self.f; first=f.progress.begin('session'); second=f.progress.begin('session')
        self.assertFalse(f.progress.complete(first))
        self.assertFalse(f.progress.complete(second))

    def test_ticket_cannot_be_reconstructed_with_equal_values(self):
        f=self.f;ticket=f.progress.begin('session')
        self.assertFalse(f.progress.complete(replace(ticket)))

    def test_owner_thread_and_capability_are_required(self):
        f=self.f; errors=[]
        def other():
            try:f.progress.begin('session')
            except BaseException as e:errors.append(type(e))
        worker=threading.Thread(target=other);worker.start();worker.join(1)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[PermissionError])
        with self.assertRaises(PermissionError):CooperativeProgress(f.gate,object())

    def test_lifetime_diagnostics_survive_revocation_and_are_bounded(self):
        f=self.f;f.pair();f.gate.deactivate(f.cap)
        for i in range(200):f.progress.invalidate('injected_'+str(i))
        report=f.progress.snapshot()
        self.assertEqual(report['totals']['successful_exchanges'],2)
        self.assertEqual(report['totals']['successful_pairs'],1)
        self.assertEqual(report['invalidations']['other'],200)
        self.assertLessEqual(len(report['events']),128)



class PolicyTests(unittest.TestCase):
    def test_exact_owned_progress_allows_above_old_cpu_floor_after_dwell(self):
        f=GateFixture();p=f.allowed_policy()
        self.assertTrue(p.allowed);self.assertFalse(p.yield_requested)
        self.assertEqual(p.reason,'cooperative_clear')
        self.assertEqual(p.last['foreground']['cpu_cores_used'],.2)

    def test_missing_progress_never_falls_through_low_cpu_old_allowance(self):
        f=GateFixture();p=f.policy()
        for i in range(8):
            f.now=1+i*.5
            self.assertFalse(p.observe(sample(f.now,cpu=0,idle=100),f.now))
        self.assertTrue(p.yield_requested)

    def test_host_pressure_even_low_gui_cpu_denies_and_yields_after_two_samples(self):
        f=GateFixture();p=f.allowed_policy()
        self.assertFalse(f.advance(p,7.6,host_cpu=.95,cpu=.001))
        self.assertFalse(p.yield_requested)
        self.assertFalse(f.advance(p,8.1,host_cpu=.99,cpu=.001))
        self.assertTrue(p.yield_requested)

    def test_host_cpu_middle_band_blocks_and_restarts_dwell(self):
        f=GateFixture();p=f.allowed_policy()
        self.assertFalse(f.advance(p,7.6,host_cpu=.81))
        self.assertIsNone(p.clear_since)
        self.assertFalse(f.advance(p,8.1,host_cpu=.80))
        self.assertEqual(p.clear_since,8.1)

    def test_missing_bad_host_cpu_and_memory_never_use_strict_fallback(self):
        for changes in ({'host_cpu':None},{'host_cpu':float('nan')},{'host_cpu':1.01},
                        {'ram':3.9},{'commit':3.9}):
            with self.subTest(changes=changes):
                f=GateFixture();p=f.allowed_policy()
                self.assertFalse(f.advance(p,7.6,cpu=0,idle=100,**changes))

    def test_foreign_identity_strict_policy_and_destroys_own_health(self):
        f=GateFixture();p=f.allowed_policy();f.now=7.6
        self.assertFalse(p.observe(sample(7.6,pid=8,cpu=0),7.6))
        self.assertEqual(p.reason,'foreground_activity');self.assertIsNone(f.progress.completed)
        f.now=8.1
        self.assertFalse(p.observe(sample(8.1,cpu=0),8.1))

    def test_foreign_idle_low_cpu_retains_existing_policy_not_host_profile(self):
        f=GateFixture();p=f.policy()
        for i in range(6):
            f.now=1+i
            p.observe(sample(f.now,pid=8,cpu=.01,idle=100,host_cpu=.99),f.now)
        self.assertTrue(p.allowed);self.assertEqual(p.reason,'foreground_clear')

    def test_fresh_denies_between_samples_when_intent_or_progress_lost(self):
        f=GateFixture();p=f.allowed_policy();f.progress.invalidate('fixture_failure')
        self.assertFalse(p.fresh(f.now));self.assertFalse(p.allowed);self.assertTrue(p.yield_requested)
        self.assertIsNone(p.clear_since)

    def test_new_generation_cannot_inherit_dwell_even_with_two_new_completions(self):
        f=GateFixture();p=f.allowed_policy();f.activate()
        f.exchange(7.2);f.exchange(7.4);f.now=7.5
        self.assertFalse(p.observe(sample(7.5),7.5));self.assertEqual(p.clear_since,7.5)

    def test_duplicate_observation_cannot_advance_dwell(self):
        f=GateFixture();f.pair();p=f.policy();raw=sample(f.now)
        self.assertFalse(p.observe(raw,f.now));since=p.clear_since
        for i in range(5):self.assertFalse(p.observe(deepcopy(raw),f.now))
        self.assertEqual(p.clear_since,since)

    def test_stale_activity_and_memory_pressure_remain_denied(self):
        f=GateFixture();p=f.allowed_policy();f.now=8.2
        self.assertFalse(p.observe(sample(7.1),8.2))
        f.now=8.3;self.assertFalse(p.observe(sample(8.3,ram=3),8.3))
        self.assertTrue(p.yield_requested)

    def test_fixed_opt_in_bounds_and_no_ignored_identity(self):
        f=GateFixture()
        for kwargs in ({'recovery_s':0},{'max_age_s':2},{'ignored_identities':((7,80),)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(TypeError):
                ForegroundPolicy(ui_intent=f.gate,cooperative_progress=f.progress,**kwargs)



class Runtime(fixtures.Runtime):
    def __init__(self,f):super().__init__();self.f=f;self.gate=f.gate
    def deactivate_intent(self):
        super().deactivate_intent();self.gate.deactivate(self.f.cap)
    def activate_intent(self,session):
        super().activate_intent(session);self.f.activate()



class RawSocket:
    def __init__(self):self.closed=False
    def fileno(self):return -1 if self.closed else 55
    def close(self):self.closed=True



class Writer(fixtures.Writer):
    def __init__(self,raw,**kwargs):super().__init__(**kwargs);self.raw=raw;self.wait_count=0
    async def wait_closed(self):
        self.wait_count+=1
        await super().wait_closed();self.raw.close()



class TransportProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f=GateFixture();self.runtime=Runtime(self.f);self.cap=object()
        self.t=ControlTransport(PreparedTask('host','task','Keep the original objective.\nIncluding this line.'),self.runtime,
            capability=self.cap,runner_credential='b'*64,io_timeout=.1,
            cooperative_progress=self.f.progress)
        self.t.bind_session(self.cap,'session','a'*64);self.t._ready=True;self.f.activate()
        self.listener=SerialListener(self.t);self.tasks=[];self.release=[]

    def request(self,method='status',**changes):
        data={'host_epoch':'host','session_id':'session','task_id':'task','token':'a'*64,'method':method}
        data.update(changes);return (json.dumps(data)+'\n').encode()

    def start(self,data=None,**kwargs):
        raw=RawSocket();writer=Writer(raw,**kwargs)
        handler=self.t.admit(fixtures.Reader(data if data is not None else self.request()),writer)
        self.tasks.append(handler)
        record={'socket':raw,'setup':None,'pair':(None,writer),'handler':handler,
            'transferred':True,'cleanup':None,'raw_close_attempted':False,'raw_closed':False}
        self.listener._record=record
        return handler,record,writer

    async def exchange(self,arrival,**kwargs):
        self.f.now=arrival;handler,record,writer=self.start(**kwargs)
        await handler;self.f.now=arrival+.05
        await self.listener._reap(record)
        return handler,record,writer

    async def asyncTearDown(self):
        for event in self.release:event.set()
        if self.tasks:await asyncio.gather(*self.tasks,return_exceptions=True)
        await self.t.aclose(timeout=1)
        await self.listener.aclose(timeout=1)

    async def test_handler_completion_alone_cannot_publish(self):
        handler,record,writer=self.start();await handler
        self.assertTrue(writer.joined);self.assertIsNone(self.f.progress.completed)
        self.f.now=1.05;await self.listener._reap(record)
        self.assertEqual(self.f.progress.consecutive,1)
        await self.exchange(2);self.assertEqual(self.f.progress.consecutive,2)

    async def test_reap_waits_for_its_own_successful_wait_closed_and_closed_socket(self):
        handler,record,writer=self.start();await handler
        close=asyncio.Event();self.release.append(close);writer.close_wait=close
        work=asyncio.create_task(self.listener._reap(record))
        await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertFalse(work.done());self.assertIsNone(self.f.progress.completed)
        close.set();self.f.now=1.05;await work
        self.assertEqual(self.f.progress.consecutive,1);self.assertGreaterEqual(writer.wait_count,2)

    async def test_partial_write_swallowed_drain_error_and_projection_failure_are_not_health(self):
        await self.exchange(1);await self.exchange(2)
        await self.exchange(3,broken=True)
        self.assertEqual(self.f.progress.consecutive,0)
        self.runtime.projection['host_phase']='invalid'
        await self.exchange(4)
        self.assertEqual(self.f.progress.consecutive,0)

    async def test_failed_authentication_invalidates_then_clean_pair_can_recover(self):
        await self.exchange(1);await self.exchange(2)
        await self.exchange(3,data=self.request(token='c'*64))
        self.assertEqual(self.f.progress.consecutive,0)
        await self.exchange(4);await self.exchange(5)
        self.assertEqual(self.f.progress.consecutive,2)

    async def test_actual_activation_during_cleanup_cannot_publish(self):
        close=asyncio.Event();self.release.append(close)
        handler,record,writer=self.start(close_wait=close)
        for _ in range(10):await asyncio.sleep(0)
        self.assertIsNotNone(self.f.progress.pending)
        self.f.activate();close.set();await handler
        await self.listener._reap(record)
        self.assertIsNone(self.f.progress.completed)

    async def test_retained_transport_fault_prevents_later_successful_health(self):
        await self.exchange(1);await self.exchange(2)
        self.t._faults.add('stream_close_failed');self.t.invalidate_progress('fixture_close_failure')
        await self.exchange(3);await self.exchange(4)
        self.assertIsNone(self.f.progress.completed)

    async def test_real_close_timeout_cannot_publish_even_if_later_close_resolves(self):
        close=asyncio.Event();self.release.append(close)
        handler,record,writer=self.start(close_wait=close)
        with self.assertRaises(asyncio.TimeoutError):await handler
        self.assertIn('stream_close_failed',self.t.lifecycle()['faults'])
        close.set();await self.listener._reap(record)
        await self.exchange(2);await self.exchange(3)
        self.assertEqual(self.f.progress.consecutive,0)

    async def test_stop_window_close_pause_and_resume_reset_health(self):
        for method in ('pause','resume','stop','window_closed'):
            # Each control is checked after an independent complete pair; Stop
            # ends this transport and must be last before window_closed.
            if method in ('pause','resume'):
                self.f.activate();await self.exchange(self.f.now+1);await self.exchange(self.f.now+1)
                await self.exchange(self.f.now+1,data=self.request(method,request_id=method+'-id'))
            else:await self.exchange(self.f.now+1,data=self.request(method))
            self.assertEqual(self.f.progress.consecutive,0)

    async def test_publication_failure_retains_closed_resource_result_and_fences_listener(self):
        handler,record,writer=self.start();await handler
        with mock.patch.object(self.f.progress,'complete',side_effect=RuntimeError('fixture publication')):
            with self.assertRaisesRegex(RuntimeError,'fixture publication'):
                await self.listener._reap(record)
        self.assertIsNone(self.listener._record);self.assertEqual(record['socket'].fileno(),-1)
        self.assertTrue(self.listener._closing)
        self.assertIn('progress_publication_failed',self.listener.lifecycle()['faults'])
        self.assertIsNone(self.f.progress.completed)



class SafeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_loss_drains_ready_owner_only_after_active_work_finishes(self):
        from adaptive_inference.handoff import HandoffController
        f=GateFixture();p=f.allowed_policy();stops=[]
        async def stop(identity):
            stops.append(deepcopy(identity))
            return {'owner_id':identity['owner_id'],'released':True,'cleanup_confirmed':True,
                'port_free':True,'retained_processes':2,'confirmed_process_exits':2}
        controller=HandoffController(SimpleNamespace(stop=stop),p,clock=lambda:f.now)
        active=object()
        controller.scheduler=SimpleNamespace(active=active,pending=0,uncertain=False,closing=False)
        controller.identity={'owner_id':'exact-owner','ready':True,'loaded':True}
        controller.state='ready'
        self.assertTrue(controller())
        f.progress.invalidate('progress_write_failed')
        self.assertFalse(controller());self.assertTrue(p.yield_requested)
        await controller.step()
        self.assertEqual(controller.state,'draining');self.assertEqual(stops,[])
        self.assertIs(controller.scheduler.active,active)
        controller.scheduler.active=None
        await controller.step()
        self.assertEqual(controller.state,'parked');self.assertEqual(len(stops),1)
        self.assertEqual(stops[0]['owner_id'],'exact-owner')
        self.assertIsNone(controller.fault)


if __name__ == '__main__':
    unittest.main()
