"""Actual SQLite/OS-claim prototype tests; synthetic state, no SDK/model/service."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from adaptive_inference import task_store as storage
from adaptive_inference.task_store import TaskStore, RevisionConflict, ReconciliationRequired, TaskBusyError, TaskStoreError
from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME, ACKS
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.desktop.execution_budget import BUDGET, create_budget, tighten_budget
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from adaptive_inference.desktop.hermes.recovery import digest
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, AUTHORITY, LINK

NOW = '2026-10-25T12:00:00Z'


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.seed()

    def seed(self, *, requests=2, deferrals=0, state_changes=None):
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
            state = deepcopy(owned.checkpoint.state)
            state.update(deadline_monotonic=1000., attempts=requests, requests=requests,
                         admission_attempts=requests+deferrals,
                         admission_deferrals=[{'attempt_id': 'deferred-'+str(i)} for i in range(deferrals)],
                         native_history=[{'role': 'user', 'content': 'Preserve original task'}])
            state.update(state_changes or {})
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
            self.mailbox.submit(self.cap, 'pause-old', 'pause')
            self.mailbox.consume(owned, updated_at_utc=NOW)
            observed = self.mailbox.paused_execution_observation(owned)
            self.mailbox.seal_paused_execution(owned, deadline_monotonic=1000., pause_observed_at_monotonic=999.,
                observed_pause=observed, sealed_at_monotonic=1100., deadline_clock=CLOCK_ID)
        self.old = self.store.load('orders-report')
        self.scope = {'plan_sha256': digest('immutable-plan'), 'session_id': 'same-session',
                      'native_db': str(self.root/'native.sqlite3'), 'work_dir': str(self.root/'work'),
                      'effect_receipts': str(self.root/'effect-receipts.jsonl'),
                      'wire_observations': str(self.root/'wire-observations.json'), 'gateway': 'http://127.0.0.1:1/v1'}
        self.now = 1200.
        self.authority = ContinuationAuthority(self.store, 'orders-report', self.scope, host_generation='host-epoch', clock=lambda: self.now)
        self.payload = self.authority.request(command_id='continue-1', predecessor_id=self.old.task_id,
            predecessor_revision=self.old.revision, predecessor_seal_sha256=digest(self.old.state[EXECUTION_OUTCOME]),
            successor_id='orders-report.run-1', identity=DemandIdentity('execution-1', 'orders-report.run-1', 'host', NOW),
            host_generation='host-epoch', release_evidence_sha256=digest('synthetic controller proof reference'))

    def wire_row(self, number):
        return {'phase': 'parent', 'url': 'http://127.0.0.1:1/v1/chat/completions', 'method': 'POST',
                'class': 'normal', 'model': 'iq3_s-fixture', 'quality': {'max_tokens': 10923},
                'body_sha256': digest('body'+str(number)), 'messages_sha256': digest('messages'),
                'tools_sha256': digest('tools'), 'tool_names': ['read_file', 'write_file'],
                'started_at': float(number), 'finished_at': float(number)+.1, 'finish_reason': 'tool_calls',
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
                'gateway_request_id': 'request-'+str(number), 'response_sha256': digest('response'+str(number)),
                'assistant_sha256': digest('assistant'+str(number))}

    def write_wire(self, rows):
        (self.root/'wire-observations.json').write_text(json.dumps(rows), encoding='utf-8')

    def authorize(self, payload=None):
        cp = self.store.load(self.authority.task_id)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            return self.authority.authorize(owned, payload or self.payload)

    def raw_old(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            return (db.execute('SELECT * FROM tasks WHERE task_id=?', ('orders-report',)).fetchall(),
                    db.execute('SELECT * FROM history WHERE task_id=? ORDER BY revision', ('orders-report',)).fetchall())

    def corrupt(self, task_id, field, value):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('UPDATE tasks SET '+field+'=? WHERE task_id=?', (value, task_id))

    def test_atomic_projection_preserves_original_row_and_history_bytes(self):
        before = self.raw_old()
        grant = self.authorize()
        new = self.store.load(self.payload['successor_id'])
        self.assertEqual(self.raw_old(), before)
        self.assertEqual(grant['deadline_monotonic'], 2100.)
        self.assertEqual(grant['execution_generation'], 1)
        self.assertFalse(grant['release_proven_by_store'])
        expected = deepcopy(self.old.state)
        expected.pop(EXECUTION_OUTCOME); expected.pop(ACKS)
        expected['deadline_monotonic'] = 2100.; expected[NAMESPACE] = new.state[NAMESPACE]
        self.assertEqual(new.state, expected)
        self.assertEqual(new.state[NAMESPACE]['state'], 'paused')
        self.assertEqual(new.metadata[LINK]['logical_task_id'], 'orders-report')
        self.assertEqual(new.prompt, self.old.prompt)
        self.assertEqual(new.max_attempts, 8)
        self.assertEqual(new.revision, 0)

    def test_expired_reboot_budget_stays_only_in_original_execution(self):
        origin_utc = 1_700_000_000_000_000_000
        budget = create_budget(boot_id='a'*64, deadline=1000.,
            observation={'utc_ns': origin_utc, 'qpc_before': 100., 'qpc_after': 100.})
        budget = tighten_budget(budget, boot_id='a'*64,
            observation={'utc_ns': origin_utc+900_000_000_000, 'qpc_before': 1000., 'qpc_after': 1000.})
        self.assertEqual(budget['remaining_cap_ns'], 0)
        self.root = self.root/'versioned'; self.root.mkdir()
        self.seed(state_changes={BUDGET: budget})
        before = self.raw_old()
        grant = self.authorize()
        new = self.store.load(self.payload['successor_id'])
        self.assertEqual(self.raw_old(), before)
        self.assertEqual(self.store.load(self.old.task_id).state[BUDGET], budget)
        self.assertNotIn(BUDGET, new.state)
        expected = deepcopy(self.old.state)
        expected.pop(EXECUTION_OUTCOME); expected.pop(ACKS); expected.pop(BUDGET)
        expected['deadline_monotonic'] = 2100.; expected[NAMESPACE] = new.state[NAMESPACE]
        self.assertEqual(new.state, expected)
        self.assertEqual(grant['predecessor_state_sha256'], digest(self.old.state))
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, owned):
            self.assertEqual(owned.checkpoint.state['deadline_monotonic'], 2100.)
            self.assertNotIn(BUDGET, owned.checkpoint.state)
        self.assertEqual(self.raw_old(), before)

    def test_duplicate_lost_reply_returns_same_deadline_without_new_grant(self):
        first = self.authorize()
        self.now = 2000.
        self.assertEqual(self.authorize(), first)
        self.assertEqual(self.authority.lookup(self.payload), first)
        authority = self.store.load(self.authority.task_id)
        self.assertEqual(len(authority.state[AUTHORITY]['grants']), 1)

    def test_conflicting_same_command_refused(self):
        self.authorize()
        changed = deepcopy(self.payload); changed['release_evidence_sha256'] = digest('different')
        with self.assertRaises(RevisionConflict): self.authority.lookup(changed)
        with self.assertRaises(RevisionConflict): self.authorize(changed)

    def test_other_command_cannot_select_second_successor(self):
        self.authorize()
        changed = deepcopy(self.payload); changed['command_id'] = 'continue-2'
        with self.assertRaisesRegex(ReconciliationRequired, 'already has a selected successor'):
            self.authorize(changed)

    def test_rollback_after_successor_insert_leaves_no_selection_or_child(self):
        before = self.raw_old()
        cp = self.store.load(self.authority.task_id)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            original = self.store._write
            def fail(db, old, **kwargs):
                if kwargs.get('event') == 'continuation_authorized':
                    raise RuntimeError('injected post-insert failure')
                return original(db, old, **kwargs)
            with mock.patch.object(self.store, '_write', side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, 'post-insert'): self.authority.authorize(owned, self.payload)
            self.assertEqual(owned.checkpoint.state[AUTHORITY]['grants'], [])
        with self.assertRaises(KeyError): self.store.load(self.payload['successor_id'])
        self.assertEqual(self.raw_old(), before)
        self.assertIsNone(self.authority.lookup(self.payload))
        self.authorize()

    def test_task_capacity_refusal_is_atomic(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            count = db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        with mock.patch.object(storage, 'MAX_TASKS', count):
            with self.assertRaisesRegex(TaskStoreError, 'Task count'): self.authorize()
        self.assertIsNone(self.authority.lookup(self.payload))
        with self.assertRaises(KeyError): self.store.load(self.payload['successor_id'])

    def test_authority_history_capacity_rolls_back_new_execution(self):
        cp = self.store.load(self.authority.task_id)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            with mock.patch.object(storage, 'MAX_REVISIONS', owned.checkpoint.revision+1):
                with self.assertRaises(TaskStoreError): self.authority.authorize(owned, self.payload)
        with self.assertRaises(KeyError): self.store.load(self.payload['successor_id'])
        self.assertIsNone(self.authority.lookup(self.payload))

    def test_concurrent_connections_have_one_grant_and_read_only_retry(self):
        entered = threading.Event(); release = threading.Event(); rows = []; errors = []
        def writer():
            try:
                other_store = TaskStore(self.store.path)
                other = ContinuationAuthority(other_store, 'orders-report', self.scope, host_generation='host-epoch', clock=lambda: 1200.)
                cp = other_store.load(other.task_id)
                with other_store.claim(cp.task_id, expected_revision=cp.revision) as owned:
                    rows.append(other.authorize(owned, self.payload)); entered.set()
                    if not release.wait(5): raise AssertionError('test release deadline')
            except BaseException as error:
                errors.append(error); entered.set()
        thread = threading.Thread(target=writer); thread.start()
        try:
            self.assertTrue(entered.wait(5)); self.assertEqual(errors, [])
            before = self.store.load(self.authority.task_id).revision
            self.assertEqual(self.authority.lookup(self.payload), rows[0])
            self.assertEqual(self.store.load(self.authority.task_id).revision, before)
            with self.assertRaises(TaskBusyError): self.authorize()
        finally:
            release.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        self.assertEqual(self.authorize(), rows[0])

    def test_owner_present_refused_without_mutating_sealed_predecessor(self):
        self.corrupt('orders-report', 'owner_epoch', 'a'*32)
        before = self.raw_old()
        with self.assertRaisesRegex(ReconciliationRequired, 'still has an owner'): self.authorize()
        self.assertEqual(before, self.raw_old())

    def test_unknown_operation_and_reconciliation_refused(self):
        operation = {'id': 'a'*32, 'kind': 'effect', 'details': {'outcome': 'unknown'}}
        self.corrupt('orders-report', 'inflight', json.dumps(operation))
        self.corrupt('orders-report', 'reconciliation', 1)
        with self.assertRaisesRegex(ReconciliationRequired, 'safe checkpoint'): self.authorize()

    def test_changed_seal_and_missing_history_refused(self):
        state = deepcopy(self.old.state); state[EXECUTION_OUTCOME]['pre_seal_state_sha256'] = 'a'*64
        self.corrupt('orders-report', 'state', json.dumps(state))
        with self.assertRaises(TaskStoreError): self.authorize()

    def test_missing_predecessor_history_refused(self):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('DELETE FROM history WHERE task_id=? AND revision=?', ('orders-report', self.old.revision-1))
        with self.assertRaisesRegex(ReconciliationRequired, 'history'): self.authorize()

    def test_unknown_state_cannot_silently_cross_execution(self):
        state = deepcopy(self.old.state); state['unknown_execution_specific_field'] = 'old'
        self.corrupt('orders-report', 'state', json.dumps(state))
        with self.assertRaisesRegex(ReconciliationRequired, 'Unknown recovery state field'): self.authorize()

    def test_missing_or_partial_wire_ledger_refused(self):
        for changed in (self.wire[:1], [self.wire[0], {k: v for k, v in self.wire[1].items() if k != 'response_sha256'}]):
            with self.subTest(changed=changed):
                self.write_wire(changed)
                with self.assertRaises(ReconciliationRequired): self.authorize()
        (self.root/'wire-observations.json').unlink()
        with self.assertRaises(FileNotFoundError): self.authorize()

    def test_duplicate_wire_and_wrong_quality_refused(self):
        duplicate = [self.wire[0], self.wire[0]]
        quality = deepcopy(self.wire); quality[0]['quality'] = {'max_tokens': 10}
        for changed in (duplicate, quality):
            with self.subTest(changed=changed):
                self.write_wire(changed)
                with self.assertRaises(ReconciliationRequired): self.authorize()

    def test_scope_and_session_rebinding_refused(self):
        changed = deepcopy(self.scope); changed['plan_sha256'] = digest('new-plan')
        with self.assertRaisesRegex(ReconciliationRequired, 'authority identity'):
            ContinuationAuthority(self.store, 'orders-report', changed, host_generation='host-epoch')
        changed = deepcopy(self.scope); changed['session_id'] = 'another-session'
        with self.assertRaisesRegex(ReconciliationRequired, 'session scope'):
            ContinuationAuthority(self.store, 'orders-report', changed, host_generation='host-epoch')

    def test_logical_authority_cannot_be_reopened_under_a_new_host(self):
        with self.assertRaisesRegex(ReconciliationRequired, 'authority identity'):
            ContinuationAuthority(self.store, 'orders-report', self.scope, host_generation='another-host')
        changed = deepcopy(self.payload); changed['host_generation'] = 'another-host'
        with self.assertRaisesRegex(ReconciliationRequired, 'another host generation'):
            self.authorize(changed)

    def test_clock_cannot_grant_before_the_original_seal(self):
        self.now = 100.
        with self.assertRaisesRegex(ReconciliationRequired, 'clock'): self.authorize()
        self.assertIsNone(self.authority.lookup(self.payload))

    def test_spent_request_or_admission_capacity_gets_no_grant(self):
        original_root = self.root
        for name, arguments in (('requests', {'requests': 8}), ('admissions', {'requests': 2, 'deferrals': 30})):
            with self.subTest(name=name):
                self.root = original_root/name; self.root.mkdir()
                self.seed(**arguments)
                with self.assertRaisesRegex(ReconciliationRequired, 'Cumulative capacity is spent'):
                    self.authorize()
                self.assertIsNone(self.authority.lookup(self.payload))

    def test_counter_inconsistency_is_refused_even_with_a_valid_seal(self):
        self.root = self.root/'accounting'; self.root.mkdir()
        self.seed(state_changes={'attempts': 1})
        with self.assertRaisesRegex(ReconciliationRequired, 'accounting differs'):
            self.authorize()

    def test_selected_claim_holds_both_existing_locks(self):
        grant = self.authorize()
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (authority, execution):
            self.assertNotEqual(authority.checkpoint.task_id, execution.checkpoint.task_id)
            self.assertEqual(self.authority.lookup(self.payload), grant)
            with self.assertRaises(TaskBusyError):
                with self.authority.claim_selected(grant, host_generation='host-epoch'): pass
            cp = self.store.load(execution.checkpoint.task_id)
            with self.assertRaises(TaskBusyError):
                with self.store.claim(cp.task_id, expected_revision=cp.revision): pass
        self.assertIsNone(self.store.load(self.authority.task_id).owner_epoch)
        self.assertIsNone(self.store.load(self.payload['successor_id']).owner_epoch)

    def test_selected_safe_restart_allows_valid_wire_growth(self):
        grant = self.authorize()
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, execution):
            state = deepcopy(execution.checkpoint.state)
            state.update(attempts=3, requests=3, admission_attempts=3)
            state['native_history'].append({'role': 'assistant', 'content': 'More safe progress'})
            execution.save_checkpoint(state, expected_revision=execution.checkpoint.revision)
            self.write_wire(self.wire+[self.wire_row(3)])
        self.now = 1500.
        with self.authority.claim_selected(grant, host_generation='host-epoch') as (_, execution):
            self.assertEqual(execution.checkpoint.state['requests'], 3)
            self.assertEqual(self.authority.lookup(self.payload), grant)

    def test_second_authorization_advances_execution_generation_only(self):
        original_bytes = self.raw_old()
        first = self.authorize()
        new_identity = DemandIdentity('execution-1', 'orders-report.run-1', 'host', NOW)
        registry = DemandRegistry((Registration(self.store, new_identity),))
        capability = object(); box = Mailbox(registry, new_identity.registration_id, requester_capability=capability)
        with self.authority.claim_selected(first, host_generation='host-epoch') as (_, execution):
            box.submit(capability, 'pause-second', 'pause')
            box.consume(execution, updated_at_utc=NOW)
            box.seal_paused_execution(execution, deadline_monotonic=2100., pause_observed_at_monotonic=2099.,
                observed_pause=box.paused_execution_observation(execution), sealed_at_monotonic=2200., deadline_clock=CLOCK_ID)
        previous = self.store.load(first['payload']['successor_id'])
        next_payload = self.authority.request(command_id='continue-2', predecessor_id=previous.task_id,
            predecessor_revision=previous.revision, predecessor_seal_sha256=digest(previous.state[EXECUTION_OUTCOME]),
            successor_id='orders-report.run-2', identity=DemandIdentity('execution-2', 'orders-report.run-2', 'host', NOW),
            host_generation='host-epoch', release_evidence_sha256=digest('second synthetic proof reference'))
        self.now = 2300.
        second = self.authorize(next_payload)
        self.assertEqual(second['execution_generation'], 2)
        self.assertEqual(second['deadline_monotonic'], 3200.)
        self.assertEqual(self.authority.lookup(self.payload), first)
        self.assertEqual(self.store.load('orders-report.run-2').state['requests'], 2)
        self.assertEqual(self.raw_old(), original_bytes)
        with self.assertRaisesRegex(ReconciliationRequired, 'selected authorization'):
            with self.authority.claim_selected(first, host_generation='host-epoch'): pass

    def test_grant_and_demand_numeric_types_cannot_be_relabelled(self):
        payload = deepcopy(self.payload); payload['demand_identity']['schema'] = True
        with self.assertRaises(ReconciliationRequired): self.authorize(payload)
        grant = self.authorize(); grant['execution_generation'] = True
        with self.assertRaisesRegex(ReconciliationRequired, 'selected authorization'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_selected_ledger_prefix_cannot_be_replaced(self):
        grant = self.authorize()
        altered = deepcopy(self.wire); altered[0]['body_sha256'] = digest('different-body')
        self.write_wire(altered)
        with self.assertRaisesRegex(ReconciliationRequired, 'Inherited wire prefix'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_selected_counter_reset_refused(self):
        grant = self.authorize(); cp = self.store.load(self.payload['successor_id'])
        state = deepcopy(cp.state); state.update(attempts=1, requests=1, admission_attempts=1)
        self.corrupt(cp.task_id, 'state', json.dumps(state)); self.write_wire(self.wire[:1])
        with self.assertRaises(ReconciliationRequired):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_selected_metadata_rebinding_refused(self):
        grant = self.authorize(); cp = self.store.load(self.payload['successor_id'])
        metadata = deepcopy(cp.metadata); metadata['sdk_revision'] = 'different-sdk'
        self.corrupt(cp.task_id, 'metadata', json.dumps(metadata))
        with self.assertRaisesRegex(ReconciliationRequired, 'identity changed'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_unknown_selected_operation_refuses_before_worker_claim(self):
        grant = self.authorize(); cp = self.store.load(self.payload['successor_id'])
        self.corrupt(cp.task_id, 'inflight', json.dumps({'id': 'a'*32, 'kind': 'effect', 'details': {}}))
        revision = self.store.load(cp.task_id).revision
        with self.assertRaises(ReconciliationRequired):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass
        self.assertEqual(self.store.load(cp.task_id).revision, revision)

    def test_stale_host_generation_or_spent_successor_budget_refused(self):
        grant = self.authorize()
        with self.assertRaisesRegex(ReconciliationRequired, 'Host generation'):
            with self.authority.claim_selected(grant, host_generation='old-host'): pass
        self.now = grant['deadline_monotonic']
        with self.assertRaisesRegex(ReconciliationRequired, 'budget spent'):
            with self.authority.claim_selected(grant, host_generation='host-epoch'): pass

    def test_actual_sqlite_integrity_after_selection_and_claim(self):
        grant = self.authorize()
        with self.authority.claim_selected(grant, host_generation='host-epoch'): pass
        with closing(sqlite3.connect(self.store.path)) as db, db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
