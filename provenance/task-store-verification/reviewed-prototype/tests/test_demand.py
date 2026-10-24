"""Real TaskStore demand-component tests; no model, provider, GPU or UI."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from adaptive_inference.task_store import (
    OwnershipError, ReconciliationRequired, RevisionConflict, TaskBusyError,
    TaskStore, TerminalTaskError,
)

from adaptive_inference.demand import DemandIdentity, DemandRegistry, NAMESPACE, Registration

ARRIVAL = "2026-10-24T05:00:00Z"
LATER = "2026-10-24T05:05:00Z"


class DemandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.sqlite3"
        self.store = TaskStore(self.path)
        self.identity = DemandIdentity("report-demand", "report", "host-agent-root", ARRIVAL)
        self.original = "Produce the original report and retain completed results."
        self.initial = self.store.create("report", self.original, max_attempts=3,
            metadata={NAMESPACE: self.identity.metadata(), "existing": "preserved"})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))

    def claim(self, store=None):
        store = store or self.store
        return store.claim("report", expected_revision=store.load("report").revision,
                           owner_id="trusted-host-worker")

    def transition(self, owned, state, *, registry=None, expected_revision=None, when=LATER):
        return (registry or self.registry).transition("report-demand", owned, state,
            expected_revision=owned.checkpoint.revision if expected_revision is None else expected_revision,
            updated_at_utc=when, reason="test transition")

    def test_explicit_new_demand_is_eligible_without_http_ticket(self):
        self.assertEqual(self.registry.observe("report-demand").reason, "no_demand")
        with self.claim() as owned:
            updated = self.transition(owned, "waiting")
            observed = self.registry.observe("report-demand")
            self.assertTrue(observed.eligible)
            self.assertEqual(observed.reason, "safe_task_demand")
            self.assertEqual(observed.arrived_at_utc, ARRIVAL)
            self.assertEqual(updated.state["attempts"], 0)
            self.assertEqual(updated.state["messages"], self.initial.state["messages"])
            self.assertEqual(updated.metadata, self.initial.metadata)
            self.assertIsNone(updated.operation)
        self.assertTrue(self.registry.observe("report-demand").eligible)

    def test_polling_and_same_state_calls_do_not_consume_revisions_or_attempts(self):
        with self.claim() as owned:
            updated = self.transition(owned, "active")
            history = self.store.history("report")
            before_bytes = self.path.read_bytes()
            for index in range(300):
                self.assertTrue(self.registry.observe("report-demand").eligible)
                same = self.registry.transition("report-demand", owned, "active",
                    expected_revision=updated.revision, updated_at_utc="2026-10-24T07:00:00Z",
                    reason=f"ignored same-state polling reason {index}")
                self.assertEqual(same.revision, updated.revision)
            self.assertEqual(self.store.history("report"), history)
            self.assertEqual(self.path.read_bytes(), before_bytes)
            self.assertEqual(owned.checkpoint.state["attempts"], 0)
            self.assertEqual(owned.checkpoint.state[NAMESPACE]["updated_at_utc"], LATER)

    def test_real_transitions_preserve_arrival_and_task_history(self):
        with self.claim() as owned:
            first = self.transition(owned, "active")
            for state in ("waiting", "active", "waiting", "paused", "waiting", "active"):
                before = owned.checkpoint.revision
                updated = self.transition(owned, state)
                self.assertEqual(updated.revision, before + 1)
                self.assertEqual(updated.state[NAMESPACE]["arrived_at_utc"], ARRIVAL)
                self.assertEqual(updated.state["messages"], first.state["messages"])
                self.assertEqual(updated.state["attempts"], 0)

    def test_pause_resume_and_durable_cancellation(self):
        with self.claim() as owned:
            self.transition(owned, "waiting")
            self.transition(owned, "paused")
            self.assertEqual(self.registry.observe("report-demand").reason, "demand_paused")
            self.transition(owned, "active")
            self.assertTrue(self.registry.observe("report-demand").eligible)
            cancelled = self.transition(owned, "cancelled")
            self.assertEqual(self.transition(owned, "cancelled").revision, cancelled.revision)
            with self.assertRaises(ValueError):
                self.transition(owned, "active")
        reopened = TaskStore(self.path)
        registry = DemandRegistry((Registration(reopened, self.identity),))
        self.assertFalse(registry.observe("report-demand").eligible)
        self.assertEqual(registry.observe("report-demand").reason, "demand_cancelled")
        with self.claim(reopened) as owned:
            with self.assertRaises(ValueError):
                self.transition(owned, "waiting", registry=registry)

    def test_cancel_before_first_demand_is_persistent_without_fake_completion(self):
        with self.claim() as owned:
            result = self.transition(owned, "cancelled")
            self.assertEqual(result.state["status"], "pending")
            self.assertEqual(result.state["output"], "")
        self.assertFalse(self.registry.observe("report-demand").eligible)

    def test_fulfilled_means_task_lifetime_need_finished(self):
        with self.claim() as owned:
            with self.assertRaises(ValueError):
                self.transition(owned, "fulfilled")
            self.transition(owned, "active")
            result = self.transition(owned, "fulfilled")
            self.assertFalse(self.registry.observe("report-demand").eligible)
            self.assertEqual(result.state["status"], "pending")
            self.assertEqual(self.transition(owned, "fulfilled").revision, result.revision)
            with self.assertRaises(ValueError):
                self.transition(owned, "waiting")

    def test_active_operation_and_interrupted_operation_are_never_eligible(self):
        for kind in ("generation", "validation", "effect"):
            with self.subTest(kind=kind):
                if self.store.load("report").operation is not None:
                    with self.claim() as owned:
                        checkpoint = owned.checkpoint
                        owned.reconcile_operation(checkpoint.operation["id"], resolution="not_performed",
                            result={"fixture_only": "no external executor exists"}, state=checkpoint.state,
                            expected_revision=checkpoint.revision)
                with self.claim() as owned:
                    self.transition(owned, "waiting")
                    operation = owned.begin_operation(kind, expected_revision=owned.checkpoint.revision)
                    self.assertEqual(self.registry.observe("report-demand").reason, "operation_inflight")
                    for target in ("waiting", "cancelled", "fulfilled"):
                        with self.assertRaises(ReconciliationRequired):
                            self.transition(owned, target)
                    self.assertEqual(owned.checkpoint.operation, operation.operation)
                self.assertEqual(self.registry.observe("report-demand").reason, "reconciliation_required")
                with self.claim() as owned:
                    before = owned.checkpoint
                    with self.assertRaises(ReconciliationRequired):
                        self.transition(owned, "cancelled")
                    self.assertEqual(owned.checkpoint, before)

    def test_fulfillment_of_one_operation_does_not_finish_task_demand(self):
        with self.claim() as owned:
            self.transition(owned, "active")
            op = owned.begin_operation("generation", expected_revision=owned.checkpoint.revision)
            owned.complete_operation(op.operation["id"], result={"output": "fixture"},
                                     state=op.state, expected_revision=op.revision)
            self.assertTrue(self.registry.observe("report-demand").eligible)
            self.assertEqual(owned.checkpoint.state[NAMESPACE]["state"], "active")

    def test_task_terminal_states_override_demand_and_reject_changes(self):
        for terminal in ("accepted", "exhausted"):
            with self.subTest(terminal=terminal):
                path = Path(self.temp.name) / (terminal + ".sqlite3")
                store = TaskStore(path)
                identity = DemandIdentity(terminal, terminal, "host-agent-root", ARRIVAL)
                initial = store.create(terminal, "Keep original", max_attempts=3,
                    metadata={NAMESPACE: identity.metadata()})
                registry = DemandRegistry((Registration(store, identity),))
                with store.claim(terminal, expected_revision=initial.revision) as owned:
                    updated = registry.transition(terminal, owned, "active",
                        expected_revision=owned.checkpoint.revision, updated_at_utc=LATER)
                    state = deepcopy(updated.state)
                    state.update(status=terminal, attempts=3 if terminal == "exhausted" else 0)
                    ended = owned.save_checkpoint(state, expected_revision=updated.revision)
                    self.assertEqual(registry.observe(terminal).reason, "task_terminal")
                    with self.assertRaises(TerminalTaskError):
                        registry.transition(terminal, owned, "cancelled",
                            expected_revision=ended.revision, updated_at_utc=LATER)

    def test_stale_revision_and_closed_owner_are_rejected_even_for_noop(self):
        with self.claim() as owned:
            before = owned.checkpoint.revision
            active = self.transition(owned, "active")
            with self.assertRaises(RevisionConflict):
                self.transition(owned, "active", expected_revision=before)
            with self.assertRaises(TaskBusyError):
                with self.claim():
                    self.fail("Second writer claimed an already owned task")
        with self.assertRaises(OwnershipError):
            self.transition(owned, "active", expected_revision=active.revision)
        with self.claim() as replacement:
            with self.assertRaises(OwnershipError):
                self.transition(owned, "cancelled", expected_revision=replacement.checkpoint.revision)

    def test_unregistered_identity_and_wrong_owner_task_are_rejected(self):
        with self.assertRaises(KeyError):
            self.registry.observe("made-up-header-id")
        with self.assertRaises(TypeError):
            self.registry.transition("report-demand", object(), "active",
                expected_revision=0, updated_at_utc=LATER)
        self.store.create("other", "Different task")
        with self.store.claim("other", expected_revision=0) as other:
            with self.assertRaises(OwnershipError):
                self.transition(other, "cancelled")
        for identity in (
            DemandIdentity("report-demand", "report", "different-owner", ARRIVAL),
            DemandIdentity("report-demand", "report", "host-agent-root", LATER),
        ):
            with self.assertRaises(ValueError):
                DemandRegistry((Registration(self.store, identity),))
        with self.assertRaises(ValueError):
            DemandRegistry((Registration(self.store, self.identity), Registration(self.store, self.identity)))

    def test_malformed_record_is_ineligible_and_not_overwritten(self):
        with self.claim() as owned:
            active = self.transition(owned, "active")
            good = deepcopy(active.state[NAMESPACE])
            for bad in (None, [], {**good, "arrived_at_utc": LATER},
                        {**good, "state": []}, {**good, "schema": True},
                        {**good, "updated_at_utc": 12345}):
                with self.subTest(bad=bad):
                    state = deepcopy(owned.checkpoint.state)
                    state[NAMESPACE] = bad
                    owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
                    self.assertEqual(self.registry.observe("report-demand").reason, "unavailable_or_invalid_checkpoint")
                    with self.assertRaises((ValueError, TypeError)):
                        self.transition(owned, "cancelled")
                    state[NAMESPACE] = good
                    owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)

    def test_no_monotonic_or_naive_clock_value_is_accepted(self):
        for value in (123.4, "2026-10-24T05:00:00", "2026-10-24T05:00:00+03:00", "2026-99-24T05:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DemandIdentity("report-demand", "report", "host-agent-root", value)
        with self.claim() as owned:
            self.transition(owned, "waiting")
            # A wall-clock correction cannot grant or revoke execution permission.
            self.transition(owned, "paused", when="2026-10-23T05:00:00Z")
            self.assertFalse(self.registry.observe("report-demand").eligible)
            self.assertEqual(owned.checkpoint.state[NAMESPACE]["arrived_at_utc"], ARRIVAL)

    def test_observer_unavailable_checkpoint_fails_closed_without_claim(self):
        with mock.patch.object(self.store, "load", side_effect=OSError("unavailable")), \
             mock.patch.object(self.store, "claim", side_effect=AssertionError("observer must not claim")):
            observation = self.registry.observe("report-demand")
        self.assertFalse(observation.eligible)
        self.assertEqual(observation.reason, "unavailable_or_invalid_checkpoint")

    def test_waiting_survives_new_worker_process_and_store_reopen(self):
        with self.claim() as owned:
            waiting = self.transition(owned, "waiting")
        child = '''
import json,sys
sys.path.insert(0,sys.argv[1])
from adaptive_inference.task_store import TaskStore
from adaptive_inference.demand import DemandIdentity,DemandRegistry,Registration,NAMESPACE
store=TaskStore(sys.argv[2])
identity=DemandIdentity('report-demand','report','host-agent-root','2026-10-24T05:00:00Z')
registry=DemandRegistry((Registration(store,identity),))
before=store.load('report')
with store.claim('report',expected_revision=before.revision,owner_id='replacement-worker') as owned:
 updated=registry.transition('report-demand',owned,'waiting',expected_revision=owned.checkpoint.revision,updated_at_utc='2026-10-25T01:00:00Z')
 print(json.dumps({'eligible':registry.observe('report-demand').eligible,'record':updated.state[NAMESPACE],'attempts':updated.state['attempts'],'revision':updated.revision,'prompt':updated.prompt}))
'''
        source_root = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", child, str(source_root), str(self.path)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["eligible"])
        self.assertEqual(receipt["record"], waiting.state[NAMESPACE])
        self.assertEqual(receipt["prompt"], self.original)
        self.assertEqual(receipt["attempts"], 0)
        self.assertEqual(receipt["revision"], waiting.revision + 1)  # one real owner claim, no polling write
        reopened = TaskStore(self.path).load("report")
        self.assertIsNone(reopened.owner_epoch)
        self.assertEqual(reopened.state[NAMESPACE], waiting.state[NAMESPACE])


if __name__ == "__main__":
    unittest.main()
