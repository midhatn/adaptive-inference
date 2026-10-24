"""CPU fixtures use the real TaskStore locks, transactions and demand component."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from unittest.mock import patch

from adaptive_inference.control_mailbox import Mailbox, ControlBlocked, REQUESTS, ACKS, MAX_REQUESTS
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore, OwnershipError, TaskBusyError, TerminalTaskError

NOW = '2026-10-24T18:00:00Z'


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name)/'tasks.sqlite3')
        self.identity = DemandIdentity('registered', 'target', 'trusted-host', NOW)
        self.original = self.store.create('target', 'Retain the original task and finish it.',
            metadata={NAMESPACE: self.identity.metadata()})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.capability = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.capability)

    def claim(self):
        return self.store.claim('target', expected_revision=self.store.load('target').revision)

    def submit(self, ident, command):
        return self.box.submit(self.capability, ident, command)

    def consume(self, owned):
        return self.box.consume(owned, updated_at_utc=NOW)

    def test_recording_does_not_wait_for_target_owner_rlock_or_acknowledge(self):
        held = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        failures = []
        lock = threading.RLock()
        def owner_wait():
            try:
                with self.claim() as owned, lock:
                    self.registry.transition('registered', owned, 'waiting',
                        expected_revision=owned.checkpoint.revision, updated_at_utc=NOW)
                    held.set()
                    if not release.wait(4):
                        raise AssertionError('Fixture owner wait timed out')
                    self.consume(owned)
            except BaseException as exc:
                failures.append(exc)
            finally:
                finished.set()
        worker = threading.Thread(target=owner_wait)
        worker.start()
        try:
            self.assertTrue(held.wait(2))
            before = self.store.load('target')
            receipt = self.submit('cancel-1', 'cancel')
            self.assertEqual(receipt['outcome'], 'pending')
            self.assertFalse(receipt['owner_acknowledged'])
            self.assertFalse(finished.is_set())
            self.assertEqual(self.store.load('target'), before)
            with self.assertRaises(TaskBusyError):
                with self.claim():
                    pass
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.box.status('cancel-1')['outcome'], 'applied')
        self.assertEqual(self.store.load('target').state[NAMESPACE]['state'], 'cancelled')

    def test_ordered_pause_resume_cancel_and_late_resume_rejection(self):
        for ident, command in (('p','pause'),('r','resume'),('c','cancel'),('r2','resume')):
            self.submit(ident, command)
        with self.claim() as owned:
            boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual(boundary['pending'], 0)
            receipts = owned.checkpoint.state[ACKS]['receipts']
            self.assertEqual([r['outcome'] for r in receipts], ['applied']*3+['rejected'])
            self.assertEqual([r['demand_state'] for r in receipts],
                             ['paused','waiting','cancelled','cancelled'])
            self.assertEqual(owned.checkpoint.state['status'], 'pending')
            self.assertEqual(owned.checkpoint.state['attempts'], 0)
            self.assertEqual(owned.checkpoint.prompt, self.original.prompt)
            before = self.store.history('target')
            self.consume(owned)
            self.assertEqual(self.store.history('target'), before)

    def test_duplicate_and_conflicting_ids_do_not_write_or_reapply(self):
        self.submit('stable','pause')
        history = self.store.history(self.box.task_id)
        self.assertEqual(self.submit('stable','pause')['outcome'], 'pending')
        with self.assertRaises(ValueError):
            self.submit('stable','resume')
        self.assertEqual(self.store.history(self.box.task_id), history)
        with self.claim() as owned:
            self.consume(owned)
            target_history = self.store.history('target')
            self.assertEqual(self.submit('stable','pause')['outcome'], 'applied')
            self.assertEqual(self.store.history('target'), target_history)
            self.assertEqual(self.store.history(self.box.task_id), history)

    def test_crash_between_transition_and_ack_reapplies_idempotently_after_reclaim(self):
        self.submit('pause-crash','pause')
        with self.claim() as owned:
            real_save = owned.save_checkpoint
            def interrupted_ack(state, **kwargs):
                if ACKS in state:
                    raise OSError('Fixture interruption before ACK commit')
                return real_save(state, **kwargs)
            with mock.patch.object(owned, 'save_checkpoint', side_effect=interrupted_ack):
                with self.assertRaises(OSError):
                    self.consume(owned)
            self.assertEqual(owned.checkpoint.state[NAMESPACE]['state'], 'paused')
            self.assertNotIn(ACKS, owned.checkpoint.state)
            self.assertEqual(self.box.status('pause-crash')['outcome'], 'pending')
            old_owner = owned
        # Reconstruct trusted host objects; commands survive without an in-memory queue.
        self.store = TaskStore(self.store.path)
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.capability = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.capability)
        with self.claim() as replacement:
            with self.assertRaises(OwnershipError):
                self.consume(old_owner)
            before = replacement.checkpoint.revision
            self.consume(replacement)
            # The repeated demand transition is a verified no-op; only ACK writes.
            self.assertEqual(replacement.checkpoint.revision, before+1)
            self.assertTrue(self.box.status('pause-crash')['owner_acknowledged'])
            self.assertEqual(len(replacement.checkpoint.state[ACKS]['receipts']),1)

    def test_requester_crash_after_commit_can_repeat_id_without_owner_available(self):
        real_status = self.box.status
        with mock.patch.object(self.box, 'status', side_effect=OSError('Lost response after commit')):
            with self.assertRaises(OSError):
                self.submit('durable','cancel')
        history = self.store.history(self.box.task_id)
        self.assertEqual(real_status('durable')['outcome'], 'pending')
        self.assertEqual(self.submit('durable','cancel')['outcome'], 'pending')
        self.assertEqual(self.store.history(self.box.task_id),history)

    def test_later_queued_cancel_cannot_overtake_interrupted_pause_ack(self):
        self.submit('p','pause')
        with self.claim() as owned:
            real_save=owned.save_checkpoint
            def interrupt_ack(state,**kwargs):
                if ACKS in state:
                    raise OSError('Fixture interruption at first pause ACK')
                return real_save(state,**kwargs)
            with mock.patch.object(owned,'save_checkpoint',side_effect=interrupt_ack):
                with self.assertRaises(OSError):
                    self.consume(owned)
            self.assertEqual(owned.checkpoint.state[NAMESPACE]['state'],'paused')
        self.submit('c','cancel')
        with self.claim() as replacement:
            before=replacement.checkpoint.revision
            self.assertFalse(self.consume(replacement)['allowed'])
            # Pause is already durable: ACK pause, transition cancel, ACK cancel.
            self.assertEqual(replacement.checkpoint.revision,before+3)
            receipts=replacement.checkpoint.state[ACKS]['receipts']
            self.assertEqual([r['request_id'] for r in receipts],['p','c'])
            self.assertEqual([r['demand_state'] for r in receipts],['paused','cancelled'])
            self.assertEqual(replacement.checkpoint.state[NAMESPACE]['state'],'cancelled')

    def test_pending_cancel_never_acknowledges_or_terminates_active_operation(self):
        with self.claim() as owned:
            self.registry.transition('registered', owned, 'active',
                expected_revision=owned.checkpoint.revision, updated_at_utc=NOW)
            running = owned.begin_operation('generation',expected_revision=owned.checkpoint.revision)
            self.submit('cancel-active','cancel')
            before = self.store.history('target')
            boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual(self.store.history('target'),before)
            self.assertEqual(self.store.load('target').operation,running.operation)
            self.assertEqual(self.box.status('cancel-active')['outcome'],'pending')
            owned.complete_operation(running.operation['id'], result={'fixture_response_completed':True},
                state=deepcopy(owned.checkpoint.state), expected_revision=owned.checkpoint.revision)
            with self.assertRaises(ControlBlocked):
                self.box.begin_operation(owned,'generation',updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)
            self.assertEqual(self.box.status('cancel-active')['outcome'],'applied')

    def test_interrupted_effect_requires_reconciliation_before_ack(self):
        with self.claim() as owned:
            running = owned.begin_operation('effect',details={'fixture_only':True},
                                            expected_revision=owned.checkpoint.revision)
            self.submit('c','cancel')
        with self.claim() as owned:
            self.assertTrue(owned.checkpoint.requires_reconciliation)
            before = self.store.history('target')
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.store.history('target'),before)
            self.assertEqual(self.box.status('c')['outcome'],'pending')
            owned.reconcile_operation(running.operation['id'], resolution='not_performed',
                result={'fixture_no_external_effect':True},state=deepcopy(owned.checkpoint.state),
                expected_revision=owned.checkpoint.revision)
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.box.status('c')['outcome'],'applied')

    def test_resume_allows_existing_operation_api_but_pause_blocks_next(self):
        self.submit('r','resume')
        with self.claim() as owned:
            running=self.box.begin_operation(owned,'generation',updated_at_utc=NOW,
                                             details={'fixture_only':True})
            self.assertEqual(running.operation['kind'],'generation')
            self.submit('p','pause')
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.box.status('p')['outcome'],'pending')
            owned.complete_operation(running.operation['id'],result={'completed':True},
                state=deepcopy(owned.checkpoint.state),expected_revision=owned.checkpoint.revision)
            with self.assertRaises(ControlBlocked):
                self.box.begin_operation(owned,'effect',updated_at_utc=NOW)
            self.assertEqual(self.box.status('p')['outcome'],'applied')

    def test_forged_capability_wrong_target_and_wrong_registration_refuse(self):
        before=self.store.history(self.box.task_id)
        with self.assertRaises(OwnershipError):
            self.box.submit(object(),'p','pause')
        self.assertEqual(self.store.history(self.box.task_id),before)
        with self.assertRaises(KeyError):
            Mailbox(self.registry,'unknown',requester_capability=object())
        mismatch=DemandIdentity('registered','target','different-host',NOW)
        with self.assertRaises(ValueError):
            DemandRegistry((Registration(self.store,mismatch),))
        other=self.store.create('other','Another original task.')
        with self.store.claim('other',expected_revision=other.revision) as wrong_owner:
            with self.assertRaises(OwnershipError):
                self.consume(wrong_owner)

    def test_mailbox_contention_reports_busy_without_waiting_for_target(self):
        first=self.store.load(self.box.task_id)
        with self.store.claim(self.box.task_id,expected_revision=first.revision):
            with self.assertRaises(TaskBusyError):
                self.submit('p','pause')
        with self.assertRaises(KeyError):
            self.box.status('p')
        self.assertEqual(self.submit('p','pause')['outcome'],'pending')

    def test_full_lifetime_capacity_retains_all_requests_and_duplicate_access(self):
        for number in range(MAX_REQUESTS):
            self.submit('p'+str(number),'pause')
        before=self.store.history(self.box.task_id)
        with self.assertRaises(ControlBlocked):
            self.submit('overflow','resume')
        self.assertEqual(self.store.history(self.box.task_id),before)
        self.assertEqual(self.submit('p0','pause')['outcome'],'pending')
        with self.claim() as owned:
            self.consume(owned)
            self.assertEqual(len(owned.checkpoint.state[ACKS]['receipts']),MAX_REQUESTS)
        with self.assertRaises(ControlBlocked):
            self.submit('overflow','cancel')
        self.assertEqual(self.submit('p0','pause')['outcome'],'applied')

    def test_terminal_task_pending_control_rejected_without_fabricated_ack(self):
        self.submit('p','pause')
        with self.claim() as owned:
            state=deepcopy(owned.checkpoint.state)
            state.update(status='accepted',output='Fixture accepted result')
            owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        receipt=self.box.status('p')
        self.assertEqual(receipt['outcome'],'rejected')
        self.assertFalse(receipt['owner_acknowledged'])
        self.assertEqual(receipt['reason'],'target_task_terminal')
        with self.assertRaises(TerminalTaskError):
            self.submit('new','resume')

    def test_corrupt_ack_prefix_is_not_adopted_or_used_to_dispatch(self):
        self.submit('p','pause')
        with self.claim() as owned:
            self.consume(owned)
            state=deepcopy(owned.checkpoint.state)
            state[ACKS]['receipts'][0]['request_id']='different'
            owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
            with self.assertRaises(ControlBlocked):
                self.box.begin_operation(owned,'generation',updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)

    def test_fulfilled_demand_cannot_be_reopened_by_resume(self):
        self.submit('r','resume')
        with self.claim() as owned:
            for demand in ('active','fulfilled'):
                self.registry.transition('registered',owned,demand,
                    expected_revision=owned.checkpoint.revision,updated_at_utc=NOW)
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.box.status('r')['outcome'],'rejected')
            self.assertEqual(owned.checkpoint.state[NAMESPACE]['state'],'fulfilled')

    def test_request_after_final_poll_stays_pending_until_operation_is_safe(self):
        # Deliberately exposes the documented non-atomic boundary. A submitted
        # command is never misreported as applied while this operation executes.
        self.submit('r','resume')
        with self.claim() as owned:
            real_begin=owned.begin_operation
            def arrive_after_last_poll(*args,**kwargs):
                self.submit('late','cancel')
                return real_begin(*args,**kwargs)
            with mock.patch.object(owned,'begin_operation',side_effect=arrive_after_last_poll):
                running=self.box.begin_operation(owned,'generation',updated_at_utc=NOW)
            self.assertEqual(self.box.status('late')['outcome'],'pending')
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(owned.checkpoint.operation,running.operation)
            owned.complete_operation(running.operation['id'],result={'fixture_completed':True},
                state=deepcopy(owned.checkpoint.state),expected_revision=owned.checkpoint.revision)
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.box.status('late')['outcome'],'applied')

    def test_lost_ack_response_does_not_repeat_ack_commit(self):
        self.submit('p','pause')
        with self.claim() as owned:
            real_save=owned.save_checkpoint
            def lose_ack_response(state,**kwargs):
                result=real_save(state,**kwargs)
                if ACKS in state:
                    raise OSError('Fixture lost response after successful ACK commit')
                return result
            with mock.patch.object(owned,'save_checkpoint',side_effect=lose_ack_response):
                with self.assertRaises(OSError):
                    self.consume(owned)
            self.assertEqual(self.box.status('p')['outcome'],'applied')
            before=self.store.history('target')
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertEqual(self.store.history('target'),before)

    def test_status_does_not_mistake_concurrent_new_ack_for_corruption(self):
        self.submit('p','pause')
        with self.claim() as owned:
            self.consume(owned)
            real_requests=self.box._requests
            interleaved=False
            def append_and_ack_after_request_snapshot():
                nonlocal interleaved
                snapshot=real_requests()
                if not interleaved:
                    interleaved=True
                    self.submit('r','resume')
                    self.consume(owned)
                return snapshot
            with mock.patch.object(self.box,'_requests',side_effect=append_and_ack_after_request_snapshot):
                receipt=self.box.status('p')
            self.assertEqual(receipt['outcome'],'applied')
            self.assertEqual(self.box.status('r')['outcome'],'applied')
            self.assertEqual(len(owned.checkpoint.state[ACKS]['receipts']),2)


class IndependentBoundaryTests(unittest.TestCase):
    setUp = MailboxTests.setUp
    claim = MailboxTests.claim
    submit = MailboxTests.submit
    consume = MailboxTests.consume

    def test_ended_owner_cannot_acknowledge_after_replacement_claim(self):
        self.submit('cancel', 'cancel')
        with self.claim() as ended:
            pass
        with self.claim() as replacement:
            history = self.store.history('target')
            with self.assertRaises(OwnershipError):
                self.consume(ended)
            self.assertEqual(history, self.store.history('target'))
            self.assertEqual('pending', self.box.status('cancel')['outcome'])
            self.assertFalse(self.consume(replacement)['allowed'])
            self.assertEqual('applied', self.box.status('cancel')['outcome'])

    def test_active_validation_is_not_a_control_safe_point(self):
        with self.claim() as owned:
            running = owned.begin_operation('validation', details={'fixture_only': True},
                expected_revision=owned.checkpoint.revision)
            self.submit('pause', 'pause')
            history = self.store.history('target')
            boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual('operation_inflight_or_reconciliation', boundary['reason'])
            self.assertEqual(history, self.store.history('target'))
            self.assertEqual(running.operation, owned.checkpoint.operation)
            self.assertFalse(self.box.status('pause')['owner_acknowledged'])
            owned.complete_operation(running.operation['id'], result={'fixture_complete': True},
                state=deepcopy(owned.checkpoint.state), expected_revision=owned.checkpoint.revision)
            self.assertFalse(self.consume(owned)['allowed'])
            self.assertTrue(self.box.status('pause')['owner_acknowledged'])

    def test_ack_failure_propagates_before_new_operation_is_started(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            original = owned.save_checkpoint
            def fail_ack(state, **kwargs):
                if ACKS in state:
                    raise OSError('Independent fixture: ACK write unavailable')
                return original(state, **kwargs)
            with patch.object(owned, 'save_checkpoint', side_effect=fail_ack):
                with self.assertRaises(OSError):
                    self.box.begin_operation(owned, 'effect', updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)
            self.assertNotIn('operation_started', [row['event'] for row in self.store.history('target')])
            self.assertEqual('pending', self.box.status('resume')['outcome'])
            self.assertTrue(self.consume(owned)['allowed'])
            self.assertTrue(self.box.status('resume')['owner_acknowledged'])

    def test_command_appended_during_ack_is_pending_and_blocks_next_operation(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            original = owned.save_checkpoint
            appended = False
            def append_after_ack(state, **kwargs):
                nonlocal appended
                saved = original(state, **kwargs)
                if ACKS in state and not appended:
                    appended = True
                    self.submit('cancel-later', 'cancel')
                return saved
            with patch.object(owned, 'save_checkpoint', side_effect=append_after_ack):
                boundary = self.consume(owned)
            self.assertFalse(boundary['allowed'])
            self.assertEqual('pending_control', boundary['reason'])
            self.assertEqual(1, boundary['pending'])
            self.assertIsNone(owned.checkpoint.operation)
            self.assertEqual('pending', self.box.status('cancel-later')['outcome'])
            with self.assertRaises(ControlBlocked):
                self.box.begin_operation(owned, 'generation', updated_at_utc=NOW)
            self.assertIsNone(owned.checkpoint.operation)
            self.assertTrue(self.box.status('cancel-later')['owner_acknowledged'])


if __name__ == '__main__':
    unittest.main()
