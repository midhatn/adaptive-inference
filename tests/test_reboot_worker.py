"""Actual worker startup with real SQLite, inert SDK edges and controlled clocks.

These checks reach the ordinary paused bootstrap and expiry or reject startup
before native database/provider creation. They do not qualify a physical reboot.
"""
from copy import deepcopy
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import EXECUTION_OUTCOME
from adaptive_inference.desktop import saved_tasks as saved
from adaptive_inference.desktop.execution_budget import BUDGET, create_budget, reopen_budget, tighten_budget
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from test_desktop_saved_tasks import BOOT, PACKAGE
from test_execution_budget import observed, UTC
import test_desktop_expiry_worker as fixture

OTHER_BOOT = {**BOOT, 'boot_utc': '2026-11-01T08:17:13.1234567Z'}
A, B = rec.digest(BOOT), rec.digest(OTHER_BOOT)


class RebootWorkerTests(unittest.TestCase):
    def cleanup_fixture(self, value):
        # Retain a nested cleanup failure alongside the outer primary outcome.
        with mock.patch.object(value, '_outcome', self._outcome):
            value.doCleanups()

    def fresh(self):
        f = fixture.WorkerExpiryTests()
        self.addCleanup(self.cleanup_fixture, f)
        def prepare_with_context(store, identity, prompt, session_id, *, metadata, **kwargs):
            context = saved.bind_context(saved.new_context('a'*64, PACKAGE, BOOT), f.run)
            return prepare_task(store, identity, prompt, session_id,
                metadata={**deepcopy(metadata), saved.CONTEXT: context}, **kwargs)
        # Keep the existing fixed report task, prompt and identity contract.
        with mock.patch.object(fixture, 'prepare_task', side_effect=prepare_with_context):
            f.setUp()
        f.plan[saved.CONTEXT] = deepcopy(f.original.metadata[saved.CONTEXT])
        rec.save(f.run/'plan.json', f.plan)
        return f

    def persist(self, f, **changes):
        cp = f.store.load(f.identity.task_id)
        with f.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state); state.update(changes)
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        return f.store.load(cp.task_id)

    def committed_episode(self, f):
        value = create_budget(boot_id=A, deadline=1000., observation=observed(0, 100))
        value = tighten_budget(value, boot_id=A, observation=observed(100, 200))
        value = reopen_budget(value, boot_id=B, observation=observed(899, 9))
        self.assertEqual(value['episode']['deadline'], 10.)
        self.assertEqual(value['episode']['index'], 1)
        self.assertFalse(value['clean_stop'])
        self.persist(f, deadline_monotonic=10., **{BUDGET: value})
        return value

    def assert_paused_expiry(self, f, code):
        result = f.result(); cp = f.store.load(f.identity.task_id)
        self.assertEqual(code, 5, result)
        self.assertIsNone(cp.owner_epoch); self.assertIsNone(cp.operation)
        self.assertFalse(cp.requires_reconciliation)
        self.assertIn(EXECUTION_OUTCOME, cp.state)
        self.assertEqual(result['provider_calls'], 0)
        self.assertNotIn('context', result)
        self.assertEqual([db.close_calls for db in f.opened], [1, 1])
        self.assertEqual((cp.state['requests'], cp.state['attempts'], cp.state['admission_attempts']), (0, 0, 0))
        return cp

    def test_fresh_worker_boot_argument_persists_exact_initial_budget(self):
        f = self.fresh(); f.args.execution_boot_id = A
        sample = observed(0, 9, 9.25)
        with mock.patch.object(saved, 'execution_observation', return_value=sample) as clock:
            cp = self.assert_paused_expiry(f, f.invoke())
        clock.assert_called_once_with()
        expected = {
            'schema': BUDGET, 'max_seconds': 900,
            'origin': {'boot_id': A, 'deadline': 10., 'observation': sample},
            'expires_utc_ns': UTC+750_000_000, 'remaining_cap_ns': 750_000_000,
            'episode': {'index': 0, 'boot_id': A, 'deadline': 10.,
                        'observation': sample, 'granted_ns': 750_000_000},
            'last_observation': sample, 'clean_stop': False,
        }
        self.assertEqual(cp.state[BUDGET], expected)
        self.assertEqual(cp.state['deadline_monotonic'], 10.)
        self.assertEqual(cp.metadata, f.original.metadata)
        created = [row['payload']['state'] for row in f.store.history(cp.task_id)
                   if BUDGET in row['payload']['state']]
        self.assertTrue(created)
        self.assertEqual(created[0][BUDGET], expected)
        self.assertEqual(created[0]['deadline_monotonic'], 10.)

    def test_worker_accepts_committed_changed_boot_episode_without_new_grant(self):
        f = self.fresh(); value = self.committed_episode(f)
        f.args.execution_boot_id = B
        with mock.patch.object(saved, 'execution_observation', side_effect=AssertionError('No startup rebase')), \
                mock.patch.object(saved, 'create_budget', side_effect=AssertionError('No renewed grant')):
            cp = self.assert_paused_expiry(f, f.invoke())
        self.assertEqual(cp.state[BUDGET], value)
        self.assertEqual(cp.state['deadline_monotonic'], 10.)
        self.assertEqual(cp.metadata[saved.CONTEXT]['boot'], BOOT)

    def test_wrong_current_boot_or_deadline_refuses_before_native_or_provider(self):
        for label, boot, deadline, error_type, message in (
                ('boot', A, 10., 'BudgetError', 'committed current-boot budget transition'),
                ('deadline', B, 9.5, 'ReconciliationRequired', 'deadline cannot reset')):
            with self.subTest(case=label):
                f = self.fresh(); self.committed_episode(f)
                before = f.store.load(f.identity.task_id)
                f.args.execution_boot_id = boot; f.args.deadline_monotonic = deadline
                self.assertEqual(f.invoke(), 2)
                result = f.result(); after = f.store.load(f.identity.task_id)
                self.assertEqual(result['error_type'], error_type, result)
                self.assertIn(message, result['error'])
                self.assertEqual(result['provider_calls'], 0)
                self.assertEqual(f.opened, [])
                self.assertIsNone(after.owner_epoch); self.assertIsNone(after.operation)
                self.assertFalse(after.requires_reconciliation)
                self.assertEqual(after.state, before.state)
                self.assertEqual(after.metadata, before.metadata)

    def test_legacy_worker_without_boot_argument_is_not_retrofitted(self):
        f = self.fresh()
        with mock.patch.object(saved, 'execution_observation', side_effect=AssertionError('Legacy has no new policy')):
            cp = self.assert_paused_expiry(f, f.invoke())
        self.assertNotIn(BUDGET, cp.state)
        self.assertEqual(cp.state['deadline_monotonic'], 10.)

    def test_existing_legacy_deadline_with_boot_argument_is_not_retrofitted(self):
        f = self.fresh(); f.args.execution_boot_id = A
        self.persist(f, deadline_monotonic=10.)
        with mock.patch.object(saved, 'execution_observation', side_effect=AssertionError('Legacy has no new policy')):
            cp = self.assert_paused_expiry(f, f.invoke())
        self.assertNotIn(BUDGET, cp.state)
        self.assertEqual(cp.state['deadline_monotonic'], 10.)


if __name__ == '__main__':
    unittest.main()
