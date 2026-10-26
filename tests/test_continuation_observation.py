# SPDX-License-Identifier: Apache-2.0
"""Real SQLite observations; explicit CPU-child fixture, no installed/model claim."""
import asyncio
from dataclasses import replace
import os
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop import composition as product
from adaptive_inference.desktop.control_transport import PreparedTask
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime, Observation, RuntimeUnavailable, ExpiredObservation
from adaptive_inference.desktop.ui_intent import UIIntentGate, VerifiedUIObservation
import test_desktop_mailbox_runtime as fixtures
import test_continuation_host as host_fixture
from adaptive_inference.control_mailbox import EXECUTION_OUTCOME, ControlBlocked


class AckReadTests(fixtures.DataFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data(); self.demand('paused')
        self.intent = object()
        self.gate = UIIntentGate(host_epoch='host', capability=self.intent,
            verify_current=lambda binding: VerifiedUIObservation(binding, time.monotonic(), True, True))
        self.runtime = MailboxRuntime(PreparedTask('host', 'task', fixtures.OBJECTIVE), self.box,
            requester_capability=self.cap, gate=self.gate, intent_capability=self.intent,
            lifecycle=fixtures.FakeLifecycle(), clock=lambda: 20.)
        await self.runtime.refresh(); self.runtime.window_ready('session')
        self.c = product.DesktopComposition.__new__(product.DesktopComposition)
        self.c.runtime = self.runtime
        self.child = SimpleNamespace(poll=lambda: None)
        self.record = {'child': self.child, 'mailbox': self.box,
            'grant': {'payload': {'successor_id': 'task'}, 'deadline_monotonic': 100.}}
        self.clock = mock.patch.object(product, 'execution_now', return_value=10.)
        self.clock.start(); self.addCleanup(self.clock.stop)

    async def asyncTearDown(self):
        await self.runtime.cooperative_stop()

    async def wait(self, request_id='control', intent_valid=lambda: True):
        return await asyncio.wait_for(self.c.wait_continuation_ack(
            self.record, request_id, intent_valid), 3)

    def aged(self, snapshot=None):
        return Observation(self.box.snapshot() if snapshot is None else snapshot, 18., 19.)

    def gate_state(self):
        return self.gate._revision, self.gate._active, self.gate._verified_stamp

    async def expired_then_fresh(self, command):
        self.submit('control', command)
        with self.claim() as owned:
            self.box.consume(owned, updated_at_utc=fixtures.NOW)
            if command == 'resume':
                self.assertTrue(await self.runtime.resume_authority('control'))
                self.assertTrue(self.runtime.activate_intent('session'))
            else:
                await self.runtime.refresh()
            cache, gate = self.runtime._cache, self.gate_state()
            snapshot = self.box.snapshot(); calls = []
            def observe(mailbox):
                calls.append(mailbox)
                if len(calls) == 1: return self.aged(snapshot)
                self.assertIs(self.runtime._cache, cache)
                self.assertEqual(self.gate_state(), gate)
                self.assertFalse(self.runtime._faults)
                return Observation(snapshot, 20., 20.)
            before = self.store.history('task')
            with mock.patch.object(self.runtime, '_observe', side_effect=observe):
                ack = await self.wait()
            self.assertEqual(len(calls), 2)
            self.assertTrue(ack['owner_acknowledged'])
            self.assertEqual(ack['outcome'], 'applied')
            self.assertEqual(before, self.store.history('task'))
            self.assertFalse(self.runtime._faults)
            self.assertFalse(hasattr(self.c, 'first_ready'))

    async def test_expired_pause_read_preserves_inactive_intent_until_fresh_ack(self):
        await self.expired_then_fresh('pause')

    async def test_expired_resume_read_preserves_fresh_authorized_intent_until_fresh_ack(self):
        await self.expired_then_fresh('resume')

    async def test_permanent_expiry_reaches_original_deadline_without_ack(self):
        cache = self.runtime._cache; gate = self.gate_state()
        with mock.patch.object(self.runtime, '_observe', side_effect=lambda box: self.aged()), \
             mock.patch.object(product, 'execution_now', side_effect=[10., 10., 100.]):
            with self.assertRaisesRegex(RuntimeError, 'deadline'): await self.wait()
        self.assertIs(self.runtime._cache, cache); self.assertEqual(self.gate_state(), gate)
        self.assertFalse(self.runtime._faults)

    async def test_expired_read_stop_returns_without_retry(self):
        actual = self.runtime._install
        def stopped(observation):
            self.runtime.fence_admission()
            return actual(observation)
        with mock.patch.object(self.runtime, '_observe', side_effect=lambda box: self.aged()) as read, \
             mock.patch.object(self.runtime, '_install', side_effect=stopped):
            self.assertIsNone(await self.wait())
        self.assertEqual(read.call_count, 1); self.assertIsNone(self.gate._active)
        self.assertFalse(self.runtime._faults)

    async def test_expired_read_lost_intent_returns_without_retry(self):
        with mock.patch.object(self.runtime, '_observe', side_effect=lambda box: self.aged()) as read:
            self.assertIsNone(await self.wait(intent_valid=mock.Mock(side_effect=[True, False])))
        self.assertEqual(read.call_count, 1); self.assertFalse(self.runtime._faults)

    async def test_expired_read_child_exit_refuses_before_retry(self):
        self.child.poll = mock.Mock(side_effect=[None, 1])
        with mock.patch.object(self.runtime, '_observe', side_effect=lambda box: self.aged()) as read:
            with self.assertRaisesRegex(RuntimeError, 'deadline'): await self.wait()
        self.assertEqual(read.call_count, 1); self.assertFalse(self.runtime._faults)

    async def test_fresh_applied_ack_returned_at_deadline_is_not_accepted(self):
        self.submit('control', 'pause')
        with self.claim() as owned:
            self.box.consume(owned, updated_at_utc=fixtures.NOW)
            with mock.patch.object(product, 'execution_now', side_effect=[99., 100.]):
                with self.assertRaisesRegex(RuntimeError, 'deadline'): await self.wait()

    async def test_deadline_or_dead_child_prevents_initial_read(self):
        with mock.patch.object(self.runtime, '_observe') as read:
            with mock.patch.object(product, 'execution_now', return_value=100.):
                with self.assertRaisesRegex(RuntimeError, 'deadline'): await self.wait()
            self.child.poll = lambda: 1
            with self.assertRaisesRegex(RuntimeError, 'deadline'): await self.wait()
        read.assert_not_called()

    async def test_invalid_expired_observations_are_not_typed_as_expiry(self):
        snap = self.box.snapshot()
        invalid = [None, Observation(None, 18., 19.),
            Observation(snap, float('nan'), 19.), Observation(snap, 18., float('inf')),
            Observation(snap, 19., 18.), Observation(snap, 18., 21.),
            Observation(replace(snap, target=replace(snap.target, task_id='other')), 18., 19.),
            Observation(replace(snap, target=replace(snap.target, prompt='other')), 18., 19.),
            Observation(replace(snap, target=replace(snap.target, revision=snap.target.revision-1)), 18., 19.),
            Observation(replace(snap, mailbox_revision=snap.mailbox_revision-1), 18., 19.)]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeUnavailable) as caught: self.runtime._install(value)
                self.assertNotIsInstance(caught.exception, ExpiredObservation)
        for now in (float('nan'), float('inf'), -1., 17.):
            with self.subTest(clock=now), mock.patch.object(self.runtime, '_clock', return_value=now):
                with self.assertRaises(RuntimeUnavailable) as caught: self.runtime._install(self.aged(snap))
                self.assertNotIsInstance(caught.exception, ExpiredObservation)

    async def test_wrong_binding_is_sticky_in_selected_ack_poll(self):
        snap = self.box.snapshot()
        wrong = self.aged(replace(snap, target=replace(snap.target, task_id='other')))
        with mock.patch.object(self.runtime, '_observe', return_value=wrong) as read:
            with self.assertRaisesRegex(RuntimeUnavailable, 'binding'): await self.wait()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.runtime._faults, {'database_operation_failed'})
        self.assertIsNone(self.runtime._cache)

    async def test_malformed_outcome_in_expired_actual_sqlite_read_is_sticky(self):
        with self.claim() as owned:
            state = dict(owned.checkpoint.state)
            state[EXECUTION_OUTCOME] = {'schema': 'unknown'}
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        snapshot = self.box.snapshot()
        with mock.patch.object(self.runtime, '_observe', return_value=self.aged(snapshot)) as read:
            with self.assertRaises(ControlBlocked): await self.wait()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.runtime._faults, {'database_operation_failed'})
        self.assertIsNone(self.runtime._cache)

    async def test_real_sqlite_failure_is_sticky_not_retried(self):
        def failed(box):
            with sqlite3.connect(':memory:') as db: db.execute('SELECT * FROM absent_actual_table')
        with mock.patch.object(self.runtime, '_observe', side_effect=failed) as read:
            with self.assertRaises(sqlite3.OperationalError): await self.wait()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(self.runtime._faults, {'database_operation_failed'})
        self.assertIsNone(self.runtime._cache)

    async def test_normal_refresh_expiry_remains_sticky(self):
        with mock.patch.object(self.runtime, '_observe', side_effect=lambda box: self.aged()):
            with self.assertRaises(ExpiredObservation): await self.runtime.refresh()
        self.assertEqual(self.runtime._faults, {'database_operation_failed'})

    async def test_post_mutation_expiry_is_sticky_and_append_not_retried(self):
        calls = []
        def observe(box):
            calls.append(box); snap = box.snapshot()
            return Observation(snap, 20., 20.) if len(calls) == 1 else self.aged(snap)
        with mock.patch.object(self.runtime, '_observe', side_effect=observe):
            with self.assertRaises(ExpiredObservation): await self.runtime.submit_control('mutation', 'resume')
        self.assertEqual(len(calls), 2)
        self.assertEqual([row['request_id'] for row in self.box.snapshot().requests], ['mutation'])
        self.assertEqual(self.runtime._faults, {'database_operation_failed'})

    async def test_cancelled_ack_waiter_retains_database_work_until_join(self):
        entered, release = threading.Event(), threading.Event()
        snapshot = self.box.snapshot()
        def observe(box):
            entered.set()
            if not release.wait(2): raise AssertionError('Fixture read was not released')
            return self.aged(snapshot)
        with mock.patch.object(self.runtime, '_observe', side_effect=observe):
            task = asyncio.create_task(self.wait())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertEqual(len(self.runtime._pending), 1)
                release.set()
                await asyncio.gather(*(asyncio.shield(t) for t in tuple(self.runtime._pending)))
            finally: release.set()
        self.assertFalse(self.runtime._pending); self.assertFalse(self.runtime._faults)


class CPUChildTests(host_fixture.HostTests):
    async def expired_recovery(self, command):
        c = self.c; grant = await self.select()
        actual_wait, actual_observe = c.wait_continuation_ack, c.runtime._observe
        injected = []
        async def wait(record, request_id, intent_valid):
            if request_id != record[command + '_id']:
                return await actual_wait(record, request_id, intent_valid)
            def observe(mailbox=None):
                real = actual_observe(mailbox)
                if not injected:
                    injected.append(True)
                    return Observation(real.snapshot, real.started-2., real.finished)
                return real
            with mock.patch.object(c.runtime, '_observe', side_effect=observe):
                return await actual_wait(record, request_id, intent_valid)
        with mock.patch.object(c, 'wait_continuation_ack', side_effect=wait):
            await self.continue_task(grant)
        record = c.continuation.current
        self.assertEqual(await c.join_child(record['child']), 0)
        self.assertEqual(record['binding']._verify_exit(0), 'task_completed')
        self.assertEqual(len(injected), 1); self.assertFalse(c.runtime._faults)
        self.assertEqual(len(c.handles), 2)
        self.assertEqual([r['command'] for r in record['mailbox'].snapshot().requests], ['pause', 'resume'])

    async def test_actual_selected_pause_expiry_reacquires_and_completes_once(self):
        await self.expired_recovery('pause')

    async def test_actual_selected_resume_expiry_reacquires_and_completes_once(self):
        await self.expired_recovery('resume')


def load_tests(loader, standard_tests, pattern):
    # unittest owns setup/teardown; inherited baseline tests are NOT rediscovered.
    return unittest.TestSuite([loader.loadTestsFromTestCase(AckReadTests),
        CPUChildTests('test_actual_selected_pause_expiry_reacquires_and_completes_once'),
        CPUChildTests('test_actual_selected_resume_expiry_reacquires_and_completes_once')])
