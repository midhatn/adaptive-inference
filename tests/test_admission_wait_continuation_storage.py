"""Real SQLite continuation projection; synthetic provider state, no SDK/model."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, ACKS, EXECUTION_OUTCOME, REQUESTS, ControlBlocked
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_store import TaskStore, ReconciliationRequired, RevisionConflict
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, AUTHORITY, LINK, PENDING_DISPOSITION
from adaptive_inference.desktop.hermes.recovery import digest
import test_continuation_storage as old

NOW = old.NOW


class WaitContinuationTests(unittest.TestCase):
    wire_row = old.ContinuationTests.wire_row
    write_wire = old.ContinuationTests.write_wire
    authorize = old.ContinuationTests.authorize
    raw_old = old.ContinuationTests.raw_old
    corrupt = old.ContinuationTests.corrupt

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.seed_wait()

    def seed_wait(self, *, requests=2, deferrals=1, late_pause=True, pending_model=None):
        self.store = TaskStore(self.root/'task.sqlite3')
        self.old_identity = DemandIdentity('initial', 'orders-report', 'host', NOW)
        self.metadata = {'deadline_clock': CLOCK_ID, 'sdk_revision': 'pinned-sdk-fixture',
                         'model': 'iq3_s-fixture', 'quality': {'max_tokens': 10923}}
        cp = prepare_task(self.store, self.old_identity, 'Preserve original task', 'same-session', metadata=self.metadata)
        registry = DemandRegistry((Registration(self.store, self.old_identity),))
        self.cap = object(); self.mailbox = Mailbox(registry, 'initial', requester_capability=self.cap)
        self.wire = [self.wire_row(number) for number in range(1, requests+1)]
        self.write_wire(self.wire)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            self.mailbox.submit(self.cap, 'resume-old', 'resume')
            self.mailbox.consume(owned, updated_at_utc=NOW)
            state = deepcopy(owned.checkpoint.state)
            history = [{'role': 'user', 'content': 'Preserve original task'}]
            self.pending = {'model': pending_model or self.metadata['model'], 'stream': False,
                            'messages': deepcopy(history), 'max_tokens': 10923}
            state.update(deadline_monotonic=1000., attempts=requests, requests=requests,
                         admission_attempts=requests+deferrals,
                         admission_deferrals=[{'attempt_id': 'deferred-'+str(i)} for i in range(deferrals)],
                         phase='waiting_admission', pending_request=deepcopy(self.pending), native_history=history)
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
            if late_pause:
                self.mailbox.submit(self.cap, 'stop-late', 'pause')
            observation = self.mailbox.admission_wait_observation(owned)
            self.mailbox.seal_admission_wait(owned, observed_wait=observation, deadline_monotonic=1000.,
                                             sealed_at_monotonic=1100., deadline_clock=CLOCK_ID)
        self.old = self.store.load(cp.task_id)
        self.scope = {'plan_sha256': digest('immutable-plan'), 'session_id': 'same-session',
                      'native_db': str(self.root/'native.sqlite3'), 'work_dir': str(self.root/'work'),
                      'effect_receipts': str(self.root/'effect-receipts.jsonl'),
                      'wire_observations': str(self.root/'wire-observations.json'), 'gateway': 'http://127.0.0.1:1/v1'}
        self.now = 1200.
        self.authority = ContinuationAuthority(self.store, cp.task_id, self.scope, host_generation='host-epoch', clock=lambda: self.now)
        self.payload = self.request(self.old, 1)

    def request(self, cp, number):
        task = 'orders-report.run-'+str(number)
        return self.authority.request(command_id='continue-'+str(number), predecessor_id=cp.task_id,
            predecessor_revision=cp.revision, predecessor_seal_sha256=digest(cp.state[EXECUTION_OUTCOME]),
            successor_id=task, identity=DemandIdentity('execution-'+str(number), task, 'host', NOW),
            host_generation='host-epoch', release_evidence_sha256=digest('synthetic retained release '+str(number)))

    def mailbox_rows(self):
        with closing(sqlite3.connect(self.store.path)) as db:
            return db.execute('SELECT * FROM tasks WHERE task_id=?', (self.mailbox.task_id,)).fetchall(), db.execute(
                'SELECT * FROM history WHERE task_id=? ORDER BY revision', (self.mailbox.task_id,)).fetchall()

    def replace_grant(self, changed):
        cp = self.store.load(self.authority.task_id)
        state = deepcopy(cp.state); state[AUTHORITY]['grants'][-1] = changed
        self.corrupt(cp.task_id, 'state', json.dumps(state))

    def expire_selected(self, grant, *, wait=True, grow=True):
        ident = DemandIdentity(**{k: v for k, v in grant['payload']['demand_identity'].items() if k != 'schema'})
        cap = object(); box = Mailbox(DemandRegistry((Registration(self.store, ident),)), ident.registration_id,
                                     requester_capability=cap)
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, execution):
            if wait:
                box.submit(cap, 'resume-selected', 'resume'); box.consume(execution, updated_at_utc=NOW)
                state = deepcopy(execution.checkpoint.state)
                if grow:
                    state['requests'] += 1; state['attempts'] += 1; state['admission_attempts'] += 1
                    state['native_history'].append({'role': 'assistant', 'content': 'Retained progress'})
                    self.wire.append(self.wire_row(state['requests'])); self.write_wire(self.wire)
                state.update(phase='waiting_admission', pending_request={**self.pending, 'messages': deepcopy(state['native_history'])})
                execution.save_checkpoint(state, expected_revision=execution.checkpoint.revision)
                # Final wire validation must support legitimately progressed waiting state.
                with self.store._connection() as db:
                    self.authority._inherited_grant(db, execution.checkpoint, grant, self.wire)
                box.submit(cap, 'late-pause', 'pause')
                box.seal_admission_wait(execution, observed_wait=box.admission_wait_observation(execution),
                    deadline_monotonic=grant['deadline_monotonic'],
                    sealed_at_monotonic=grant['deadline_monotonic']+100., deadline_clock=CLOCK_ID)
            else:
                box.submit(cap, 'pause-selected', 'pause'); box.consume(execution, updated_at_utc=NOW)
                box.seal_paused_execution(execution, observed_pause=box.paused_execution_observation(execution),
                    deadline_monotonic=grant['deadline_monotonic'], pause_observed_at_monotonic=grant['deadline_monotonic']-1.,
                    sealed_at_monotonic=grant['deadline_monotonic']+100., deadline_clock=CLOCK_ID)
            with self.store._connection() as db:
                self.authority._inherited_grant(db, execution.checkpoint, grant, self.wire)
        return self.store.load(ident.task_id)

    def test_exact_supersession_preserves_predecessor_and_mailbox_bytes(self):
        original, mailbox = self.raw_old(), self.mailbox_rows()
        grant = self.authorize(); successor = self.store.load(self.payload['successor_id'])
        self.assertEqual(self.raw_old(), original); self.assertEqual(self.mailbox_rows(), mailbox)
        self.assertEqual(grant['pending_request_disposition'], {'schema': PENDING_DISPOSITION,
            'mode': 'rebuild_from_saved_conversation', 'request_sha256': digest(self.pending)})
        expected = deepcopy(self.old.state); expected.pop(EXECUTION_OUTCOME); expected.pop(ACKS)
        expected.update(phase='ready', pending_request=None, deadline_monotonic=2100.)
        expected[NAMESPACE] = successor.state[NAMESPACE]
        self.assertEqual(successor.state, expected); self.assertEqual(successor.prompt, self.old.prompt)
        self.assertEqual(successor.state[NAMESPACE]['state'], 'paused')
        self.assertEqual(successor.max_attempts, 8); self.assertEqual(successor.revision, 0)
        self.assertEqual(self.store.load(self.old.task_id).state['pending_request'], self.pending)
        self.assertEqual((self.old.state[EXECUTION_OUTCOME]['request_count'], self.old.state[EXECUTION_OUTCOME]['ack_count']), (2, 1))
        self.assertEqual(grant['wire_prefix_count'], 2); self.assertFalse(grant['release_proven_by_store'])

    def test_duplicate_and_lost_reply_return_immutable_grant_without_renewal(self):
        grant = self.authorize(); self.now = 3000.
        self.assertEqual(self.authorize(), grant); self.assertEqual(self.authority.lookup(self.payload), grant)
        self.assertEqual(len(self.store.load(self.authority.task_id).state[AUTHORITY]['grants']), 1)
        bad = deepcopy(self.payload); bad['release_evidence_sha256'] = digest('other')
        with self.assertRaises(RevisionConflict): self.authorize(bad)

    def test_missing_mailbox_is_refused_without_provisioning(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('DELETE FROM tasks WHERE task_id=?', (self.mailbox.task_id,))
        with self.assertRaises(KeyError): self.authorize()
        with self.assertRaises(KeyError): self.store.load(self.mailbox.task_id)
        self.assertIsNone(self.authority.lookup(self.payload))

    def test_actual_pending_prefix_not_reconstructed_from_acks(self):
        cp = self.store.load(self.mailbox.task_id); state = deepcopy(cp.state)
        state[REQUESTS].pop()  # Removing unacknowledged Pause must invalidate the seal.
        self.corrupt(cp.task_id, 'state', json.dumps(state))
        with self.assertRaises(ControlBlocked): self.authorize()
        self.assertIsNone(self.authority.lookup(self.payload))

    def test_pending_resume_and_cancel_or_other_identity_refuse(self):
        cp = self.store.load(self.mailbox.task_id)
        for changes in ({'command': 'resume'}, {'command': 'cancel'}, {'request_id': 'different'}, {'sequence': True}):
            with self.subTest(changes=changes):
                state = deepcopy(cp.state); state[REQUESTS][-1].update(changes)
                self.corrupt(cp.task_id, 'state', json.dumps(state))
                with self.assertRaises(ControlBlocked): self.authorize()
                self.assertIsNone(self.authority.lookup(self.payload))
        self.corrupt(cp.task_id, 'state', json.dumps(cp.state))
        self.authorize()

    def test_changed_ack_or_request_bytes_refuse(self):
        cp = self.old
        for key in ('pending_request', ACKS):
            with self.subTest(key=key):
                state = deepcopy(cp.state)
                if key == 'pending_request': state[key]['messages'][0]['content'] = 'Changed original prompt'
                else: state[key]['receipts'][0]['acknowledged_at_utc'] = '2026-10-25T12:01:00Z'
                self.corrupt(cp.task_id, 'state', json.dumps(state))
                with self.assertRaises(ControlBlocked): self.authorize()
        self.corrupt(cp.task_id, 'state', json.dumps(cp.state))

    def test_wrong_model_fails_even_with_a_self_consistent_seal(self):
        self.root = self.root/'wrong-model'; self.root.mkdir()
        self.seed_wait(pending_model='other-model')
        with self.assertRaises(ReconciliationRequired): self.authorize()

    def test_limits_remain_cumulative(self):
        root = self.root
        for label, options in (('request', {'requests': 8, 'deferrals': 0}), ('admission', {'requests': 2, 'deferrals': 30})):
            self.root = root/label; self.root.mkdir(); self.seed_wait(**options)
            with self.subTest(label=label), self.assertRaisesRegex(ReconciliationRequired, 'capacity is spent'):
                self.authorize()
            self.assertIsNone(self.authority.lookup(self.payload))

    def test_wait_without_late_pause_remains_supported(self):
        self.root = self.root/'no-late-pause'; self.root.mkdir(); self.seed_wait(late_pause=False)
        grant = self.authorize()
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, cp):
            self.assertIsNone(cp.checkpoint.state['pending_request'])

    def test_disposition_missing_changed_or_extra_fields_refuse_on_claim(self):
        original = self.authorize()
        for value in (None, {'schema': PENDING_DISPOSITION, 'mode': 'raw_replay', 'request_sha256': digest(self.pending)},
                      {**original['pending_request_disposition'], 'request_sha256': 'a'*64},
                      {**original['pending_request_disposition'], 'extra': True}):
            with self.subTest(value=value):
                grant = deepcopy(original)
                if value is None: grant.pop('pending_request_disposition')
                else: grant['pending_request_disposition'] = value
                self.replace_grant(grant)
                with self.assertRaisesRegex(ReconciliationRequired, 'disposition'):
                    with self.authority.claim_selected(grant, host_generation='host-epoch'): pass
        self.replace_grant(original)
        with self.authority.claim_selected(original, host_generation='host-epoch'): pass

    def test_creation_projection_cannot_be_relabelled_by_rehashing(self):
        grant = self.authorize(); cp = self.store.load(self.payload['successor_id'])
        state = deepcopy(cp.state); state['feedback'].append('invented')
        self.corrupt(cp.task_id, 'state', json.dumps(state))
        with closing(sqlite3.connect(self.store.path)) as db, db:
            row = json.loads(db.execute('SELECT payload FROM history WHERE task_id=? AND revision=0', (cp.task_id,)).fetchone()[0])
            row['state'] = state
            db.execute('UPDATE history SET payload=? WHERE task_id=? AND revision=0', (json.dumps(row), cp.task_id))
        grant['successor_initial_state_sha256'] = digest(state); self.replace_grant(grant)
        with self.assertRaisesRegex(ReconciliationRequired, 'projection changed'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_predecessor_request_anchor_rechecked_on_claim(self):
        grant = self.authorize(); state = deepcopy(self.old.state)
        state['pending_request']['messages'][0]['content'] = 'Other request'
        self.corrupt(self.old.task_id, 'state', json.dumps(state))
        with self.assertRaises(ControlBlocked):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_three_explicit_generations_preserve_each_request_and_counters(self):
        original = self.raw_old(); first = self.authorize()
        previous = self.expire_selected(first)
        first_saved = deepcopy(previous)
        self.now = 2300.; second = self.authorize(self.request(previous, 2))
        self.assertEqual(second['execution_generation'], 2)
        self.assertEqual(self.store.load(previous.task_id), first_saved)
        self.assertNotEqual(first['pending_request_disposition']['request_sha256'], second['pending_request_disposition']['request_sha256'])
        previous = self.expire_selected(second)
        second_saved = deepcopy(previous)
        self.now = 3400.; third = self.authorize(self.request(previous, 3))
        self.assertEqual(third['execution_generation'], 3); self.assertEqual(third['deadline_monotonic'], 4300.)
        self.assertEqual(self.store.load(previous.task_id), second_saved)
        state = self.store.load(third['payload']['successor_id']).state
        self.assertEqual((state['requests'], state['attempts'], state['admission_attempts']), (4, 4, 5))
        self.assertEqual(len(state['native_history']), 3); self.assertEqual(self.raw_old(), original)
        self.assertEqual(self.authority.lookup(first['payload']), first)
        with self.authority.claim_selected(third, host_generation='host-epoch'): pass

    def test_wait_then_legacy_paused_grant_keeps_legacy_shape(self):
        first = self.authorize(); previous = self.expire_selected(first, wait=False)
        self.now = 2300.; second = self.authorize(self.request(previous, 2))
        self.assertNotIn('pending_request_disposition', second)
        with self.authority.claim_selected(second, host_generation='host-epoch'): pass

    def test_later_wait_cannot_reset_inherited_history_or_counters(self):
        grant = self.authorize(); previous = self.expire_selected(grant)
        # A self-consistent replacement seal is still bound by the grant's creation prefix.
        state = deepcopy(previous.state); state['admission_deferrals'] = []
        state['admission_attempts'] = state['requests']
        marker = state.pop(EXECUTION_OUTCOME); marker['pre_seal_state_sha256'] = digest(state)
        state[EXECUTION_OUTCOME] = marker
        self.corrupt(previous.task_id, 'state', json.dumps(state))
        with closing(sqlite3.connect(self.store.path)) as db, db:
            for revision, value in db.execute('SELECT revision,payload FROM history WHERE task_id=? ORDER BY revision', (previous.task_id,)).fetchall()[-2:]:
                record = json.loads(value); record['state'] = deepcopy(state)
                if revision == previous.revision-1: record['state'].pop(EXECUTION_OUTCOME)
                db.execute('UPDATE history SET payload=? WHERE task_id=? AND revision=?', (json.dumps(record), previous.task_id, revision))
        previous = self.store.load(previous.task_id); self.now = 2300.
        with self.assertRaisesRegex(ReconciliationRequired, 'Inherited task/effect history'):
            self.authorize(self.request(previous, 2))

    def test_atomic_rollback_keeps_predecessor_and_no_grant(self):
        original = self.raw_old(); cp = self.store.load(self.authority.task_id)
        write = self.store._write
        def fail(db, before, **kwargs):
            if kwargs.get('event') == 'continuation_authorized': raise OSError('after successor insert')
            return write(db, before, **kwargs)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            with mock.patch.object(self.store, '_write', side_effect=fail):
                with self.assertRaisesRegex(OSError, 'after successor'): self.authority.authorize(owned, self.payload)
        self.assertEqual(self.raw_old(), original); self.assertIsNone(self.authority.lookup(self.payload))
        with self.assertRaises(KeyError): self.store.load(self.payload['successor_id'])

    def test_actual_mailbox_read_uses_authorization_transaction_without_constructor(self):
        read = self.store._read; seen = []
        def observed(db, task_id):
            if task_id in (self.old.task_id, self.mailbox.task_id):
                seen.append((db, task_id, db.in_transaction))
            return read(db, task_id)
        with mock.patch.object(self.store, '_read', side_effect=observed):
            with mock.patch.object(Mailbox, '__init__', side_effect=AssertionError('No provisioning in authority')):
                self.authorize()
        predecessor = next(row for row in seen if row[1] == self.old.task_id)
        mailbox = next(row for row in seen if row[1] == self.mailbox.task_id)
        self.assertIs(predecessor[0], mailbox[0]); self.assertTrue(predecessor[2]); self.assertTrue(mailbox[2])

    def test_predecessor_history_anchor_rechecked_after_authorization(self):
        grant = self.authorize()
        with closing(sqlite3.connect(self.store.path)) as db, db:
            row = json.loads(db.execute('SELECT payload FROM history WHERE task_id=? AND revision=0', (self.old.task_id,)).fetchone()[0])
            row['state']['feedback'].append('changed history')
            db.execute('UPDATE history SET payload=? WHERE task_id=? AND revision=0', (json.dumps(row), self.old.task_id))
        with self.assertRaisesRegex(ReconciliationRequired, 'predecessor history changed'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_legacy_paused_then_wait_uses_new_disposition_only_when_required(self):
        self.root = self.root/'legacy-first'; self.root.mkdir()
        old.ContinuationTests.seed(self)
        first = self.authorize(); self.assertNotIn('pending_request_disposition', first)
        previous = self.expire_selected(first)
        self.now = 2300.; second = self.authorize(self.request(previous, 2))
        self.assertEqual(second['pending_request_disposition']['request_sha256'], digest(previous.state['pending_request']))
        self.assertEqual(second['execution_generation'], 2)
        with self.authority.claim_selected(second, host_generation='host-epoch'): pass

    def test_unsealed_wait_is_not_a_selected_restart_permit(self):
        grant = self.authorize()
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, execution):
            state = deepcopy(execution.checkpoint.state)
            state.update(phase='waiting_admission', pending_request=deepcopy(self.pending))
            execution.save_checkpoint(state, expected_revision=execution.checkpoint.revision)
        with self.assertRaisesRegex(ReconciliationRequired, 'complete safe checkpoint'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass


if __name__ == '__main__':
    unittest.main()
