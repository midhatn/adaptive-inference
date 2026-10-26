"""Shared absolute deadlines; local timer clocks remain deliberately distinct."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference import execution_clock as clock
from adaptive_inference.control_mailbox import execution_outcome, ControlBlocked
from adaptive_inference.desktop.hermes import service_stop, recovery as rec
from adaptive_inference.desktop.hermes.control_bridge import Controls
import test_desktop_paused_expiry as fixture
NOW = fixture.NOW


class ClockTests(unittest.TestCase):
    def test_explicit_clock_calls_perf_counter_without_consulting_monotonic(self):
        with mock.patch.object(clock.time,'perf_counter',return_value=110.0), \
                mock.patch.object(clock.time,'monotonic',side_effect=AssertionError('different domain')):
            self.assertEqual(clock.execution_now(),110.0)

    def test_installed_gate_requires_exact_supported_qpc_contract(self):
        good=dict(implementation='QueryPerformanceCounter()',monotonic=True,adjustable=False,resolution=1e-7)
        with mock.patch.object(clock.os,'name','nt'),mock.patch.object(clock.time,'get_clock_info',return_value=SimpleNamespace(**good)):
            self.assertEqual(clock.verify_execution_clock(),clock.CLOCK_ID)
        for field,value in (('implementation','GetTickCount64()'),('monotonic',False),
                            ('adjustable',True),('resolution',float('nan')),('resolution',0)):
            wrong={**good,field:value}
            with self.subTest(field=field),mock.patch.object(clock.os,'name','nt'), \
                    mock.patch.object(clock.time,'get_clock_info',return_value=SimpleNamespace(**wrong)), \
                    self.assertRaises(RuntimeError):clock.verify_execution_clock()


class SharedClockExpiryTests(unittest.TestCase):
    setUp=fixture.PausedExpiryTests.setUp
    advance=fixture.PausedExpiryTests.advance
    release=fixture.PausedExpiryTests.release
    pause=fixture.PausedExpiryTests.pause
    finalize=fixture.PausedExpiryTests.finalize

    def tagged(self):
        state=deepcopy(self.owned.checkpoint.state);state['deadline_clock']=clock.CLOCK_ID
        self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
        self.original=self.owned.checkpoint
        self.controls=Controls(self.box,deadline=10,utc_now=lambda:NOW,clock=lambda:self.now,
            sleep=self.advance,deadline_clock=clock.CLOCK_ID)
        self.controller.controls=self.controls

    def test_actual_v2_seal_and_verifier_share_qpc_with_legacy_clock_eight_seconds_behind(self):
        self.tagged();self.pause();proof=self.finalize();self.release()
        self.assertEqual(proof['schema'],service_stop.CLOCK_EXPIRY_RECEIPT_SCHEMA)
        self.assertEqual(proof['deadline_clock'],clock.CLOCK_ID)
        result=dict(passed=False,completed=False,controlled=True,control_state='paused',
            control_reason='paused_budget_expired',paused_expiry=proof,owner_epoch=proof['owner_epoch'],
            model='fixture',quality={})
        rec.save(self.run/'result-123.json',result)
        async def verify():
            binding=service_stop.WorkerStopBinding(SimpleNamespace(pid=123,poll=lambda:5,wait=lambda:5),
                self.run,self.box,requester_capability=self.cap,capability=object(),stop_request_id='stop',
                original=self.original,deadline_monotonic=10,model='fixture',quality={},fence=lambda:None,
                deadline_clock=clock.CLOCK_ID)
            with mock.patch.object(service_stop.time,'monotonic',return_value=2.2), \
                    mock.patch.object(service_stop,'execution_now',return_value=10.2):
                self.assertEqual(binding._verify_exit(5),'paused_budget_expired')
            with mock.patch.object(service_stop,'execution_now',return_value=9.99),self.assertRaises(rec.RecoveryStop):
                binding._verify_exit(5)  # The future-seal predicate remains strict.
            for value in (None,'other-clock'):
                wrong=deepcopy(result)
                if value is None:del wrong['paused_expiry']['deadline_clock']
                else:wrong['paused_expiry']['deadline_clock']=value
                rec.save(self.run/'result-123.json',wrong)
                with self.subTest(domain=value),self.assertRaises(rec.RecoveryStop):binding._verify_exit(5)
        asyncio.run(verify())

    def test_v1_history_remains_readable_but_cannot_be_relabelled_qpc(self):
        self.pause();self.finalize()
        state=deepcopy(self.owned.checkpoint.state)
        self.assertEqual(execution_outcome(state)['schema'],'adaptive.paused-budget-expiry.v1')
        state['deadline_clock']=clock.CLOCK_ID
        with self.assertRaises(ControlBlocked):execution_outcome(state)

    def test_tagged_owner_cannot_enter_legacy_default_clock_controls(self):
        self.tagged()
        legacy=Controls(self.box,deadline=10,utc_now=lambda:NOW,clock=lambda:9)
        with self.assertRaisesRegex(Exception,'clock differs'):legacy.poll(self.owned)
