"""Safe-wait continuation projection/release; SQLite and simulated host edges.

No model, native engine, actual GUI or OS child joining is established here.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.composition import DesktopComposition
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.control_transport import Refused
from adaptive_inference.desktop.hermes import service_stop
from adaptive_inference.execution_clock import CLOCK_ID
import test_admission_wait_expiry as wait_fixture
from test_continuation_host import Adapter


class WaitAvailabilityTests(unittest.TestCase):
    setUp = wait_fixture.WaitSealTests.setUp
    release = wait_fixture.WaitSealTests.release
    finalize = wait_fixture.WaitSealTests.finalize

    def runtime(self):
        ui = object.__new__(MailboxRuntime)
        ui._owner = lambda: None
        ui._cache = SimpleNamespace(snapshot=self.box.snapshot())
        ui._check_observation = lambda value: value.snapshot
        ui._transitioning = ui._stopping = ui._task_retired = False
        ui._faults = set()
        ui.mailbox = self.box
        ui.lifecycle = SimpleNamespace(status=lambda: {
            'host_phase': 'parked', 'waiting_reason': 'resources'})
        ui._continuation_phase, ui._continuation_request = 'unavailable', None
        ui._continuation = object()
        ui._selection = {'execution_id': 'task', 'execution_generation': 0}
        return ui

    def test_released_wait_offers_continue_without_database_work_or_mutation(self):
        self.finalize(); self.release()
        ui = self.runtime()
        before = self.box.snapshot()
        with mock.patch.object(self.store, '_connection', side_effect=AssertionError('loop-thread SQL')):
            status = ui.status()
        self.assertEqual(status['continuation'], {'phase': 'available', 'request_id': None})
        self.assertEqual(status['waiting_reason'], 'budget_expired')
        self.assertEqual(status['task_status'], 'pending')
        self.assertEqual(self.box.snapshot(), before)

    def test_sealed_but_still_owned_task_does_not_offer_continue(self):
        self.finalize()
        self.assertEqual(self.runtime().status()['continuation']['phase'], 'blocked')

    def test_exhausted_request_capacity_does_not_offer_continue(self):
        state = deepcopy(self.owned.checkpoint.state)
        state.update(requests=8, attempts=8, admission_attempts=8)
        self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)
        self.finalize(); self.release()
        self.assertEqual(self.runtime().status()['continuation']['phase'], 'blocked')

    def test_changed_cached_control_prefix_does_not_offer_continue(self):
        self.finalize(); self.release()
        ui = self.runtime(); snapshot = ui._cache.snapshot
        ui._cache.snapshot = replace(snapshot, requests=(*snapshot.requests,
            {'sequence': len(snapshot.requests)+1, 'request_id': 'invented', 'command': 'pause'}))
        self.assertEqual(ui.status()['continuation']['phase'], 'blocked')

    def test_stop_and_retired_endpoint_keep_continue_blocked(self):
        self.finalize(); self.release()
        for field in ('_stopping', '_task_retired'):
            with self.subTest(field=field):
                ui = self.runtime(); setattr(ui, field, True)
                self.assertEqual(ui.status()['continuation']['phase'], 'blocked')

    def test_retention_uses_current_worker_binding_not_first_task(self):
        c = object.__new__(DesktopComposition)
        c.original = SimpleNamespace(task_id='first-task')
        c.deadline = 10.0
        binding = object.__new__(service_stop.WorkerStopBinding)
        binding.original = self.original; binding.mailbox = self.box
        binding.deadline = 10.0; binding.deadline_clock = CLOCK_ID
        c.stop_binding = binding
        c.runtime = SimpleNamespace(refresh=mock.AsyncMock(),
                                    _cache=SimpleNamespace(snapshot=self.box.snapshot()))
        with mock.patch.object(self.store, '_connection', side_effect=AssertionError('identity SQL')):
            self.assertTrue(asyncio.run(c._admission_wait_expiry_candidate()))


class WaitReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.order = []
        self.code = 6
        self.outcome = 'admission_wait_budget_expired'
        c = object.__new__(DesktopComposition); self.c = c
        c.worker = SimpleNamespace(pid=123, poll=lambda: self.code)
        def verify(code):
            self.order.append('verified')
            self.assertEqual(code, self.code)
            return self.outcome
        c.stop_binding = SimpleNamespace(original=SimpleNamespace(task_id='selected'), _verify_exit=verify)
        async def join(child):
            self.assertIs(child, c.worker); self.order.append('joined')
            return self.code
        c.join_child = join
        c.runtime = SimpleNamespace(_stopping=False)
        c.host = SimpleNamespace(adapter=Adapter(), controller=SimpleNamespace(
            state='parked', fault=None, tool=None, identity=None, lock=asyncio.Lock()),
            gateway=SimpleNamespace(scheduler=SimpleNamespace(active=None, pending=[], uncertain=False)))

    async def release(self, **kwargs):
        return await self.c.continuation_release({'execution_id': 'selected'}, lambda: True, **kwargs)

    async def test_wait_release_requires_join_then_proof_and_parked_native_owner(self):
        result = await self.release()
        self.assertEqual(self.order, ['joined', 'verified'])
        self.assertEqual((result['exit_code'], result['outcome']), (6, 'admission_wait_budget_expired'))
        self.assertTrue(result['worker_joined'])
        self.assertTrue(result['native']['owner_lock_idle'])

    async def test_generic_failure_cannot_authorize_continuation(self):
        self.code = 2
        with self.assertRaises(Refused): await self.release()
        self.assertEqual(self.order, ['joined'])

    async def test_wait_exit_cannot_be_relabelled_as_paused_expiry(self):
        self.outcome = 'paused_budget_expired'
        with self.assertRaises(Refused): await self.release()

    async def test_incomplete_wait_cannot_authorize_another_task(self):
        with self.assertRaises(Refused): await self.release(task_handover=True)

    async def test_native_capacity_ownership_must_be_released(self):
        self.c.host.adapter.driver.port_free = lambda port: False
        with self.assertRaisesRegex(RuntimeError, 'still occupied'): await self.release()
        self.assertEqual(self.order, ['joined', 'verified'])


if __name__ == '__main__':
    unittest.main()
