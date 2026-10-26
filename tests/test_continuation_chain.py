"""Focused real-SQLite checks for inherited authorization across a second grant."""
from copy import deepcopy
import unittest

import test_continuation_storage as fixtures
NOW = fixtures.NOW
from adaptive_inference.task_store import TaskStoreError
from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.desktop.hermes.recovery import digest


class GrantChainTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContinuationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def second_payload(self, *, changed_deadline=False, state_change=None):
        f = self.f
        first = f.authorize()
        identity = DemandIdentity('execution-1', 'orders-report.run-1', 'host', NOW)
        registry = DemandRegistry((Registration(f.store, identity),))
        cap = object()
        box = Mailbox(registry, identity.registration_id, requester_capability=cap)
        deadline = first['deadline_monotonic'] + (100 if changed_deadline else 0)
        with f.authority.claim_selected(first, host_generation='host-epoch') as (_, execution):
            if state_change is not None:
                state = deepcopy(execution.checkpoint.state)
                state.update(state_change)
                execution.save_checkpoint(state, expected_revision=execution.checkpoint.revision)
            if changed_deadline:
                state = deepcopy(execution.checkpoint.state)
                state['deadline_monotonic'] = deadline
                execution.save_checkpoint(state, expected_revision=execution.checkpoint.revision)
            box.submit(cap, 'pause-second', 'pause')
            box.consume(execution, updated_at_utc=NOW)
            box.seal_paused_execution(execution, deadline_monotonic=deadline,
                pause_observed_at_monotonic=deadline-1,
                observed_pause=box.paused_execution_observation(execution),
                sealed_at_monotonic=deadline+100, deadline_clock=CLOCK_ID)
        previous = f.store.load(first['payload']['successor_id'])
        f.now = deadline+200
        return f.authority.request(command_id='continue-2', predecessor_id=previous.task_id,
            predecessor_revision=previous.revision, predecessor_seal_sha256=digest(previous.state[EXECUTION_OUTCOME]),
            successor_id='orders-report.run-2', identity=DemandIdentity('execution-2','orders-report.run-2','host',NOW),
            host_generation='host-epoch', release_evidence_sha256=digest('second synthetic release proof'))

    def test_second_grant_cannot_replace_prior_inherited_wire_prefix(self):
        payload = self.second_payload()
        changed = deepcopy(self.f.wire)
        changed[0]['body_sha256'] = digest('replacement-of-original-request')
        self.f.write_wire(changed)
        with self.assertRaises(TaskStoreError):
            self.f.authorize(payload)

    def test_second_grant_cannot_accept_seal_with_rewritten_prior_deadline(self):
        payload = self.second_payload(changed_deadline=True)
        with self.assertRaises(TaskStoreError):
            self.f.authorize(payload)

    def test_second_grant_cannot_drop_inherited_native_history(self):
        payload = self.second_payload(state_change={'native_history': []})
        with self.assertRaisesRegex(TaskStoreError, 'Inherited task/effect history'):
            self.f.authorize(payload)

    def test_second_grant_cannot_reset_admission_counter_and_deferral_prefix(self):
        self.f.root = self.f.root/'deferrals'; self.f.root.mkdir()
        self.f.seed(deferrals=1)
        payload = self.second_payload(state_change={'admission_attempts': 2, 'admission_deferrals': []})
        with self.assertRaises(TaskStoreError):
            self.f.authorize(payload)
