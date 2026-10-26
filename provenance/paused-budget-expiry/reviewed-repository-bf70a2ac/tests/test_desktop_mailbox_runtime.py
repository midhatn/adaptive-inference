"""Real SQLite/mailbox and bounded owned threads; fake streams/UI/lifecycle."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, ControlBlocked, ACKS
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore, TaskBusyError
from adaptive_inference.desktop.control_transport import ControlTransport, PreparedTask
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime, RuntimeUnavailable
from test_desktop_control_transport import Reader, Writer
from adaptive_inference.desktop.ui_intent import UIBinding, UIIntentGate, VerifiedUIObservation

NOW = '2026-10-24T18:00:00Z'
OBJECTIVE = 'Keep the original task and finish the validated artifact.'


class DataFixture:
    def data(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui-mailbox-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / 'task.sqlite')
        self.identity = DemandIdentity('registered', 'task', 'trusted-host', NOW)
        self.store.create('task', OBJECTIVE, metadata={NAMESPACE: self.identity.metadata()})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.cap = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.cap)

    def claim(self):
        return self.store.claim('task', expected_revision=self.store.load('task').revision)

    def demand(self, state='waiting'):
        with self.claim() as owned:
            self.registry.transition('registered', owned, state,
                expected_revision=owned.checkpoint.revision, updated_at_utc=NOW)

    def submit(self, ident, command):
        return self.box.submit(self.cap, ident, command)

    def consume(self):
        with self.claim() as owned:
            return self.box.consume(owned, updated_at_utc=NOW)




class FakeLifecycle:
    """Only explicit fixture events establish simulated join; no native proof."""
    def __init__(self):
        self.bindings = {'session': UIBinding('host', 'session', 'task', 101, 202, 303)}
        self.live = {'session'}
        self.fenced = False
        self.join_entered = asyncio.Event()
        self.join = asyncio.Event()
        self.join.set()
        self.stop_calls = 0
        self.result = {'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None}

    def session_is_live(self, session):
        return session in self.live

    def window_ready(self, session):
        return self.bindings.get(session)

    def window_closed(self, session):
        self.live.discard(session)

    def status(self):
        return {'host_phase': 'ready', 'waiting_reason': None}

    def fence_admission(self):
        self.fenced = True

    async def cooperative_stop(self):
        self.stop_calls += 1
        self.join_entered.set()
        await self.join.wait()
        return deepcopy(self.result)


class RuntimeTests(DataFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data()
        self.demand()
        self.intent = object()
        self.gate = UIIntentGate(host_epoch='host', capability=self.intent,
            verify_current=lambda binding: VerifiedUIObservation(binding, time.monotonic(), True, True))
        self.host = FakeLifecycle()
        self.prepared = PreparedTask('host', 'task', OBJECTIVE)
        self.runtime = MailboxRuntime(self.prepared, self.box, requester_capability=self.cap,
            gate=self.gate, intent_capability=self.intent, lifecycle=self.host, max_age_s=3)
        self.transport_cap = object()
        self.transport = ControlTransport(self.prepared, self.runtime, capability=self.transport_cap,
            runner_credential='b' * 64, io_timeout=.25)
        self.transport.bind_session(self.transport_cap, 'session', 'a' * 64)
        self.releases = []
        await self.runtime.refresh()
        self.assertTrue((await self.request('window_ready'))['ok'])

    async def asyncTearDown(self):
        for event in self.releases:
            event.set()
        self.host.join.set()
        await self.transport.aclose(timeout=3)
        await self.runtime.cooperative_stop()

    def frame(self, method, **changes):
        value = {'host_epoch': 'host', 'task_id': 'task', 'session_id': 'session',
                 'token': 'a' * 64, 'method': method}
        if method in ('pause', 'resume', 'cancel'):
            value['request_id'] = 'one'
        value.update(changes)
        return (json.dumps(value) + '\n').encode()

    async def request(self, method, **changes):
        writer = Writer()
        task = self.transport.admit(Reader(self.frame(method, **changes)), writer)
        await task
        return json.loads(writer.data)

    async def completed_control(self, method, *, request_id):
        # A handler may truthfully return pending before the retained mutation
        # and its authority read finish. Final-intent assertions need that task.
        reply = await self.request(method, request_id=request_id)
        self.assertTrue(reply['ok'])
        await asyncio.wait_for(asyncio.shield(self.transport._records[request_id]['task']), 3)
        return reply

    def matches(self):
        now = time.monotonic()
        return self.gate.matches({'monotonic_s': now, 'foreground': {
            'valid': True, 'hwnd': 101, 'pid': 202, 'creation_time_100ns': 303}}, now)

    async def signal(self, event):
        # Bounded waiting uses the actual threading event, not a timing premise.
        self.assertTrue(await asyncio.to_thread(event.wait, 2))

    def block_observation(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        actual = self.box.snapshot

        def blocked():
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture snapshot release timed out')
            return actual()
        return entered, release, blocked

    async def test_real_latest_resume_authority_pending_and_applied(self):
        self.demand('paused')
        value = await self.runtime.submit_control('new-resume', 'resume')
        self.assertEqual(value['outcome'], 'pending')
        self.assertFalse(value['owner_acknowledged'])
        self.assertIs(await self.runtime.resume_authority('new-resume'), True)
        self.consume()
        self.assertIs(await self.runtime.resume_authority('new-resume'), True)
        self.assertTrue(self.runtime.status()['controls'][0]['owner_acknowledged'])

    async def test_historical_applied_resume_followed_by_pause_never_activates(self):
        self.submit('old-resume', 'resume'); self.consume()
        self.submit('later-pause', 'pause'); self.consume()
        history = self.store.history(self.box.task_id)
        value = await self.completed_control('resume', request_id='old-resume')
        self.assertTrue(value['ok'])
        self.assertFalse(self.matches())
        self.assertEqual(history, self.store.history(self.box.task_id))
        self.assertIs(await self.runtime.resume_authority('old-resume'), False)

    async def test_new_resume_activates_real_gate_then_pause_revokes(self):
        result = await self.completed_control('resume', request_id='fresh')
        self.assertTrue(result['ok'])
        self.assertTrue(self.matches())
        await self.completed_control('pause', request_id='pause')
        self.assertFalse(self.matches())
        self.assertEqual(self.store.load('task').prompt, OBJECTIVE)
        self.assertEqual(self.runtime.status()['controls'][0]['outcome'], 'pending')

    async def test_missing_demand_refuses_authority(self):
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state.pop(NAMESPACE)
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        await self.runtime.submit_control('resume', 'resume')
        self.assertIs(await self.runtime.resume_authority('resume'), False)

    async def test_inflight_and_interrupted_replacement_are_never_authority(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            owned.begin_operation('effect', details={'fixture': 'not executed'},
                expected_revision=owned.checkpoint.revision)
            self.assertIs(await self.runtime.resume_authority('resume'), False)
            self.assertEqual(self.runtime.status()['waiting_reason'], 'operation_inflight')
        with self.claim() as replacement:
            self.assertTrue(replacement.checkpoint.requires_reconciliation)
            self.assertIs(await self.runtime.resume_authority('resume'), False)
            self.assertEqual(self.runtime.status()['waiting_reason'], 'reconciliation')

    async def test_terminal_target_revokes_intent_and_refuses_authority(self):
        await self.completed_control('resume', request_id='resume')
        self.assertTrue(self.matches())
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state.update(status='accepted', output='Validated fixture result')
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        self.assertIs(await self.runtime.resume_authority('resume'), False)
        self.assertFalse(self.matches())

    async def test_changed_objective_is_refused_without_claiming_target(self):
        self.runtime.prepared = PreparedTask('host', 'task', 'Different objective')
        with self.assertRaises(RuntimeUnavailable):
            await self.runtime.refresh()
        self.assertIsNone(self.store.load('task').owner_epoch)

    async def test_mismatched_objective_refuses_before_any_new_control_commit(self):
        self.runtime.prepared = PreparedTask('host', 'task', 'Different objective')
        before = self.store.history(self.box.task_id)
        with self.assertRaises(RuntimeUnavailable):
            await self.runtime.submit_control('must-not-record', 'cancel')
        self.assertEqual(before, self.store.history(self.box.task_id))

    async def test_wrong_intent_capability_is_rejected_before_async_work(self):
        with self.assertRaises(ValueError):
            MailboxRuntime(self.prepared, self.box, requester_capability=self.cap,
                gate=self.gate, intent_capability=object(), lifecycle=self.host)

    async def test_refresh_revokes_external_later_pause_even_before_owner_ack(self):
        await self.completed_control('resume', request_id='resume')
        self.assertTrue(self.matches())
        self.consume()
        self.submit('external-pause', 'pause')
        await self.runtime.refresh()
        self.assertFalse(self.matches())
        self.assertEqual(self.runtime.status()['controls'][-1]['outcome'], 'pending')
        self.consume()
        await self.runtime.refresh()
        self.assertEqual(self.runtime.status()['demand'], 'paused')
        self.assertFalse(self.matches())

    async def test_latest_pending_resume_can_keep_intent_while_owner_is_paused(self):
        self.demand('paused')
        await self.completed_control('resume', request_id='resume')
        self.assertTrue(self.matches())
        await self.runtime.refresh()
        self.assertEqual(self.runtime.status()['demand'], 'paused')
        self.assertTrue(self.matches())

    async def test_pending_reply_precedes_retained_resume_authority_completion(self):
        entered, release, blocked = self.block_observation()
        actual_authority = self.runtime.resume_authority
        actual_request = self.request
        responded = asyncio.get_running_loop().create_future()
        async def held_authority(request_id):
            with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
                return await actual_authority(request_id)
        async def observed_request(*args, **kwargs):
            reply = await actual_request(*args, **kwargs)
            responded.set_result(reply)
            return reply
        with mock.patch.object(self.runtime, 'resume_authority', side_effect=held_authority), \
                mock.patch.object(self, 'request', side_effect=observed_request):
            completed = asyncio.create_task(self.completed_control('resume', request_id='resume'))
            try:
                await self.signal(entered)
                operation = self.transport._records['resume']['task']
                # Observe the actual response before releasing authority; no sleep
                # or assumption about SQLite/CI scheduling establishes this order.
                reply = await asyncio.wait_for(asyncio.shield(responded), 2)
                self.assertEqual(reply, {'ok': True, 'state': 'pending', 'request_id': 'resume', 'recorded': None})
                self.assertFalse(operation.done())
                self.assertFalse(completed.done())
                self.assertFalse(self.matches())
            finally:
                release.set()
                # Settle the extra fixture task even if an assertion failed;
                # shield keeps its retained control operation uncancelled.
                await asyncio.wait_for(asyncio.shield(
                    asyncio.gather(completed, return_exceptions=True)), 3)
            self.assertEqual(completed.result(), reply)
        self.assertTrue(operation.done())
        self.assertTrue(self.matches())
        self.assertEqual(len(self.box.snapshot().requests), 1)

    async def test_crash_gap_pending_resume_does_not_invent_ack_or_reapply(self):
        self.demand('paused')
        self.submit('resume', 'resume')
        with self.claim() as owned:
            real_save = owned.save_checkpoint
            def fail_ack(state, **kwargs):
                if ACKS in state:
                    raise OSError('Fixture failed ACK commit')
                return real_save(state, **kwargs)
            with mock.patch.object(owned, 'save_checkpoint', side_effect=fail_ack):
                with self.assertRaises(OSError):
                    self.box.consume(owned, updated_at_utc=NOW)
            revision = owned.checkpoint.revision
            self.assertIs(await self.runtime.resume_authority('resume'), True)
            self.assertEqual(self.runtime.status()['controls'][0]['outcome'], 'pending')
            self.assertEqual(owned.checkpoint.revision, revision)
        with self.claim() as replacement:
            before = replacement.checkpoint.revision
            self.box.consume(replacement, updated_at_utc=NOW)
            self.assertEqual(replacement.checkpoint.revision, before + 1)
        await self.runtime.refresh()
        self.assertEqual(self.runtime.status()['controls'][0]['outcome'], 'applied')

    async def test_cancelled_refresh_retains_thread_and_stop_waits_for_it(self):
        entered, release, blocked = self.block_observation()
        with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
            waiter = asyncio.create_task(self.runtime.refresh())
            await self.signal(entered)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(self.runtime.diagnostics()['pending_database'], 1)
            stopping = asyncio.create_task(self.runtime.cooperative_stop())
            await asyncio.sleep(0)
            self.assertFalse(self.host.join_entered.is_set())
            self.assertFalse(stopping.done())
            release.set()
            result = await asyncio.wait_for(stopping, 3)
            self.assertTrue(result['worker_joined'] and result['host_closed'])
            self.assertEqual(self.runtime.diagnostics()['pending_database'], 0)

    async def test_cancelled_submit_commits_once_then_explicit_retry_observes_it(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        actual = self.box.submit
        def blocked(*args):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture submit timed out')
            return actual(*args)
        with mock.patch.object(self.box, 'submit', side_effect=blocked):
            waiter = asyncio.create_task(self.runtime.submit_control('stable', 'pause'))
            await self.signal(entered)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(self.runtime.diagnostics()['pending_database'], 1)
            release.set()
            await self.runtime.refresh()
        before = self.store.history(self.box.task_id)
        result = await self.runtime.submit_control('stable', 'pause')
        self.assertEqual(result['outcome'], 'pending')
        self.assertEqual(before, self.store.history(self.box.task_id))

    async def test_disconnected_transport_keeps_real_commit_and_stop_join_obligation(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        actual = self.box.submit
        def hold_after_commit(*args):
            value = actual(*args)
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture postcommit wait exceeded bound')
            return value
        with mock.patch.object(self.box, 'submit', side_effect=hold_after_commit):
            writer = Writer(broken=True)
            handler = self.transport.admit(Reader(self.frame('pause', request_id='durable')), writer)
            await self.signal(entered)
            handler.cancel()
            await asyncio.gather(handler, return_exceptions=True)
            pending = await self.transport.aclose(timeout=.02)
            self.assertFalse(pending['closed'])
            self.assertFalse(self.host.join_entered.is_set())
            self.assertEqual(self.runtime.diagnostics()['pending_database'], 1)
            self.assertEqual(self.box.status('durable')['outcome'], 'pending')
            release.set()
            final = await self.transport.aclose(timeout=3)
        self.assertTrue(final['closed'])
        self.assertTrue(writer.closed and writer.joined)
        self.assertEqual(len(self.box.snapshot().requests), 1)

    async def test_capacity_remains_bound_while_cancelled_waiter_thread_runs(self):
        self.runtime.max_pending = 1
        entered, release, blocked = self.block_observation()
        with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
            waiter = asyncio.create_task(self.runtime.refresh())
            await self.signal(entered)
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            with self.assertRaises(RuntimeUnavailable):
                await self.runtime.refresh()
            release.set()
            await self.runtime.cooperative_stop()

    async def test_status_cache_expires_and_does_not_do_database_io(self):
        self.runtime.max_age_s = .01
        await asyncio.sleep(.02)
        with mock.patch.object(self.box, 'snapshot', side_effect=AssertionError('Blocking status read')):
            with self.assertRaises(RuntimeUnavailable):
                self.runtime.status()
        self.runtime.max_age_s = 3
        await self.runtime.refresh()

    async def test_slow_snapshot_uses_start_time_not_completion_for_freshness(self):
        self.runtime.max_age_s = .02
        entered, release, blocked = self.block_observation()
        with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
            waiter = asyncio.create_task(self.runtime.refresh())
            await self.signal(entered)
            await asyncio.sleep(.03)
            release.set()
            with self.assertRaises(RuntimeUnavailable):
                await waiter

    async def test_failed_snapshot_does_not_turn_into_successful_cleanup(self):
        with mock.patch.object(self.box, 'snapshot', side_effect=OSError('Private fixture path')):
            with self.assertRaises(OSError):
                await self.runtime.resume_authority('one')
        receipt = await self.runtime.cooperative_stop()
        self.assertTrue(receipt['worker_joined'] and receipt['host_closed'])
        self.assertEqual(receipt['fault'], 'runtime_operation_failed')
        self.assertNotIn('Private fixture path', str(self.runtime.diagnostics()))

    async def test_prior_runtime_fault_cannot_be_hidden_by_later_resume_observation(self):
        self.submit('resume', 'resume')
        with mock.patch.object(self.box, 'snapshot', side_effect=OSError('Fixture read failed')):
            with self.assertRaises(OSError):
                await self.runtime.refresh()
        self.assertIs(await self.runtime.resume_authority('resume'), False)
        self.assertEqual(self.runtime.status()['host_phase'], 'fault')
        self.assertFalse(self.matches())

    async def test_postcommit_read_failure_retry_observes_commit_but_does_not_clear_fault(self):
        actual_snapshot = self.box.snapshot
        count = 0
        def fail_second_read():
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('Fixture observation lost after actual commit')
            return actual_snapshot()
        with mock.patch.object(self.box, 'snapshot', side_effect=fail_second_read):
            with self.assertRaises(OSError):
                await self.runtime.submit_control('resume', 'resume')
        before = self.store.history(self.box.task_id)
        self.assertEqual(self.box.status('resume')['outcome'], 'pending')
        retried = await self.runtime.submit_control('resume', 'resume')
        self.assertEqual(retried['outcome'], 'pending')
        self.assertEqual(before, self.store.history(self.box.task_id))
        self.assertIs(await self.runtime.resume_authority('resume'), False)
        stopped = await self.runtime.cooperative_stop()
        self.assertTrue(stopped['worker_joined'] and stopped['host_closed'])
        self.assertEqual(stopped['fault'], 'runtime_operation_failed')

    async def test_malformed_real_ack_prefix_never_becomes_resume_authority(self):
        self.submit('resume', 'resume'); self.consume()
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state[ACKS]['receipts'][0]['request_id'] = 'different'
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        with self.assertRaises(ControlBlocked):
            await self.runtime.resume_authority('resume')
        self.assertFalse(self.matches())

    async def test_failed_host_fence_remains_visible_even_if_worker_later_joins(self):
        with mock.patch.object(self.host, 'fence_admission', side_effect=RuntimeError('Fixture fence failure')):
            with self.assertRaises(RuntimeError):
                self.runtime.fence_admission()
        receipt = await self.runtime.cooperative_stop()
        self.assertTrue(receipt['worker_joined'] and receipt['host_closed'])
        self.assertEqual(receipt['fault'], 'runtime_operation_failed')

    async def test_stop_waiter_cancellation_preserves_worker_join_and_host_fault(self):
        self.host.join.clear()
        self.host.result['fault'] = 'fixture_host_fault'
        waiter = asyncio.create_task(self.runtime.cooperative_stop())
        await self.host.join_entered.wait()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        self.assertFalse(self.runtime._stop_task.done())
        self.host.join.set()
        result = await self.runtime.cooperative_stop()
        self.assertEqual(result['fault'], 'fixture_host_fault')
        self.assertEqual(self.host.stop_calls, 1)

    async def test_pause_during_real_authority_read_prevents_late_activation(self):
        entered, release, blocked = self.block_observation()
        actual_authority = self.runtime.resume_authority
        async def held_authority(request_id):
            with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
                return await actual_authority(request_id)
        with mock.patch.object(self.runtime, 'resume_authority', side_effect=held_authority):
            first = self.transport.admit(Reader(self.frame('resume', request_id='resume')), Writer())
            await self.signal(entered)
            pause = await self.request('pause', request_id='pause')
            self.assertTrue(pause['ok'])
            self.assertFalse(self.matches())
            release.set()
            await first
            await self.transport._records['pause']['task']
        self.assertFalse(self.matches())

    async def test_rotation_during_real_authority_read_prevents_late_activation(self):
        entered, release, blocked = self.block_observation()
        actual_authority = self.runtime.resume_authority
        async def held_authority(request_id):
            with mock.patch.object(self.box, 'snapshot', side_effect=blocked):
                return await actual_authority(request_id)
        with mock.patch.object(self.runtime, 'resume_authority', side_effect=held_authority):
            first = self.transport.admit(Reader(self.frame('resume', request_id='resume')), Writer())
            await self.signal(entered)
            self.transport.bind_session(self.transport_cap, 'new-session', 'c' * 64)
            self.host.live.add('new-session')
            self.host.bindings['new-session'] = UIBinding('host', 'new-session', 'task', 404, 505, 606)
            self.assertTrue((await self.request('window_ready', session_id='new-session', token='c' * 64))['ok'])
            release.set()
            await first
        self.assertFalse(self.matches())

    async def test_projection_keeps_only_bounded_fields_and_objective(self):
        await self.request('pause', request_id='pause')
        value = await self.request('status')
        text = json.dumps(value)
        self.assertTrue(value['ok'])
        self.assertEqual(value['status']['objective'], OBJECTIVE)
        for forbidden in ('owner_epoch', 'metadata', str(self.store.path), 'a' * 64, 'b' * 64):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
