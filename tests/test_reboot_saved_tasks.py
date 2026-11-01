"""Real task-store and recovery paths with controlled clocks/boot observations.

Desktop edges and provider transport are inert. This is not a physical reboot
or installed IQ3_S qualification.
"""
from contextlib import closing
from copy import deepcopy
import unittest
from unittest import mock

from adaptive_inference import execution_clock
from adaptive_inference.desktop import saved_tasks as saved, composition
from adaptive_inference.desktop.execution_budget import BUDGET, BudgetError, create_budget, tighten_budget
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.task_store import ReconciliationRequired, OwnedTask
from adaptive_inference.demand import NAMESPACE
import test_desktop_saved_tasks as fixture
from test_desktop_saved_tasks import BOOT, PACKAGE
from test_desktop_report_feedback import NativeDB
from test_execution_budget import observed

OTHER_BOOT = {**BOOT, 'boot_utc': '2026-11-01T08:17:13.1234567Z'}
A, B = rec.digest(BOOT), rec.digest(OTHER_BOOT)


class RebootSavedTasksTests(unittest.TestCase):
    setUp = fixture.SavedTasksTests.setUp

    def budget(self, *, stopped=True):
        value = create_budget(boot_id=A, deadline=1000.0, observation=observed(0, 100))
        if stopped:
            value = tighten_budget(value, boot_id=A, observation=observed(100, 200))
        cp = self.store.load('task')
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state); state[BUDGET] = value
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        return self.store.load('task')

    def inspect(self, **changes):
        args = dict(profile_sha256=self.profile_sha, installed=PACKAGE,
                    boot=OTHER_BOOT, now=10, observation=observed(300, 10, 12))
        args.update(changes)
        return saved.inspect_saved(self.work, **args)

    def test_changed_boot_preview_is_readonly_then_owned_transition_preserves_progress(self):
        original = self.budget(); before = (self.work / 'task.sqlite3').read_bytes()
        selected = self.inspect()
        self.assertEqual(selected['checkpoint'], original)
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before)
        with closing(saved.claim_host(self.work)):
            resumed = saved.activate_saved_budget(selected, self.store, boot=OTHER_BOOT,
                                                   observation=observed(305, 15, 17))
        cp = resumed['checkpoint']
        self.assertEqual(cp.state['deadline_monotonic'], 610.0)
        self.assertEqual(cp.state[BUDGET]['remaining_cap_ns'], 593_000_000_000)
        self.assertFalse(cp.state[BUDGET]['clean_stop'])
        self.assertEqual(cp.metadata, original.metadata)
        self.assertEqual(cp.prompt, original.prompt)
        self.assertIsNone(cp.owner_epoch)
        self.assertGreater(cp.revision, original.revision)
        preserved = deepcopy(cp.state)
        for key in (BUDGET, 'deadline_monotonic'): preserved[key] = original.state[key]
        self.assertEqual(preserved, original.state)
        self.assertTrue(any(row['payload']['state'].get(BUDGET) == original.state[BUDGET]
                            for row in self.store.history('task')))
        self.assertEqual(saved.worker_budget(cp.state, cp.metadata[saved.CONTEXT],
            deadline=610, boot_id=B), cp.state)
        with self.assertRaises(BudgetError):
            saved.worker_budget(cp.state, cp.metadata[saved.CONTEXT], deadline=610, boot_id=A)

    def test_same_boot_reopen_never_changes_deadline_or_refunds_time(self):
        self.budget()
        first = self.inspect(boot=BOOT, now=300, observation=observed(200, 300))
        with closing(saved.claim_host(self.work)):
            first = saved.activate_saved_budget(first, self.store, boot=BOOT, observation=observed(201, 301))
        self.assertEqual(first['deadline'], 1000)
        second = self.inspect(boot=BOOT, now=350, observation=observed(250, 350))
        with closing(saved.claim_host(self.work)):
            second = saved.activate_saved_budget(second, self.store, boot=BOOT, observation=observed(251, 351))
        self.assertEqual(second['deadline'], 1000)
        self.assertLess(second['checkpoint'].state[BUDGET]['remaining_cap_ns'],
                        first['checkpoint'].state[BUDGET]['remaining_cap_ns'])
        with self.assertRaises(ReconciliationRequired): self.inspect()

    def test_expired_changed_machine_or_unclean_boot_refuses_without_state_mutation(self):
        self.budget()
        before = (self.work / 'task.sqlite3').read_bytes()
        for changes in ({'observation': observed(901, 10)},
                        {'boot': {**OTHER_BOOT, 'computer_name': 'another-machine'}},
                        {'installed': {'version': 'changed'}}, {'profile_sha256': 'f' * 64}):
            with self.subTest(changes=changes), self.assertRaises(ReconciliationRequired):
                self.inspect(**changes)
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before)
        self.budget(stopped=False)
        before = (self.work / 'task.sqlite3').read_bytes()
        with self.assertRaises(ReconciliationRequired): self.inspect()
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before)

    def test_failed_commit_does_not_change_grant_or_mark_transition_complete(self):
        original = self.budget(); selected = self.inspect()
        with closing(saved.claim_host(self.work)), mock.patch.object(OwnedTask, 'save_checkpoint',
                side_effect=OSError('Injected storage failure')):
            with self.assertRaises(OSError):
                saved.activate_saved_budget(selected, self.store, boot=OTHER_BOOT,
                                             observation=observed(305, 15))
        current = self.store.load('task')
        self.assertEqual(current.state, original.state)
        self.assertIsNone(current.owner_epoch)

    def test_only_fresh_observed_worker_grant_receives_budget_legacy_is_not_retrofitted(self):
        state = deepcopy(self.store.load('task').state)
        self.assertEqual(saved.worker_budget(state, self.context, deadline=1000,
                                            boot_id=A), state)
        state['deadline_monotonic'] = None
        legacy = saved.worker_budget(state, self.context, deadline=1000, boot_id=None)
        self.assertNotIn(BUDGET, legacy)
        fresh = saved.worker_budget(state, self.context, deadline=1000, boot_id=A,
                                    observation=observed(0, 100, 102))
        self.assertEqual(fresh[BUDGET]['remaining_cap_ns'], 898_000_000_000)
        self.assertNotIn(BUDGET, state)
        with self.assertRaises(BudgetError):
            saved.worker_budget(state, self.context, deadline=1000, boot_id=B,
                                observation=observed(0, 100))

    def test_clock_observation_brackets_utc(self):
        with mock.patch.object(execution_clock, 'execution_now', side_effect=[10.0, 11.0]), \
                mock.patch.object(execution_clock.time, 'time_ns', return_value=123):
            self.assertEqual(execution_clock.execution_observation(),
                {'utc_ns': 123, 'qpc_before': 10.0, 'qpc_after': 11.0})


class RebootRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.AdmissionWaitReopenTests.asyncSetUp
    _prepare_order = fixture.AdmissionWaitReopenTests._prepare_order
    close_database = fixture.AdmissionWaitReopenTests.close_database
    controller = fixture.AdmissionWaitReopenTests.controller
    request = fixture.AdmissionWaitReopenTests.request
    tool = fixture.AdmissionWaitReopenTests.tool
    read_then_stop = fixture.AdmissionWaitReopenTests.read_then_stop

    async def test_clean_stop_changed_boot_paused_composition_and_resume_preserve_confirmed_read(self):
        cp = self.store.load('task')
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            state = saved.worker_budget(owned.checkpoint.state, self.context,
                deadline=self.deadline, boot_id=A, observation=observed(0, self.now))
            state['deadline_monotonic'] = self.deadline
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        with mock.patch.object(execution_clock, 'execution_observation',
                side_effect=lambda: observed(int(self.now-100), self.now)):
            original = self.read_then_stop()
        self.assertTrue(original.state[BUDGET]['clean_stop'])
        self.assertEqual(self.stop_receipt['state_sha256'], rec.digest(original.state))
        self.assertEqual(self.stop_receipt['revision'], original.revision)
        self.assertEqual(original.state['deadline_monotonic'], 1000)
        self.assertEqual(self.effects, ['read_file'])
        self.now = 10.0
        self.case = composition.DesktopComposition(self.profile, self.runs/'session-reopened', saved_task=self.work)
        self.case.root.mkdir()
        try:
            with mock.patch.object(saved, 'observe_boot', return_value=OTHER_BOOT), \
                    mock.patch.object(saved, 'execution_observation', return_value=observed(300, 10)), \
                    mock.patch.object(composition, 'execution_now', side_effect=lambda: self.now):
                await self._prepare_order(self.spec, reopened=True)
            paused = self.store.load('task')
            self.deadline = self.case.deadline
            self.assertEqual(self.deadline, 610.0)
            self.assertEqual(self.case.reopen_context['boot'], OTHER_BOOT)
            self.assertEqual(paused.metadata[saved.CONTEXT]['boot'], BOOT)
            self.assertEqual(paused.state['native_history'], original.state['native_history'])
            self.assertEqual(paused.state['pending_request'], original.state['pending_request'])
            self.assertEqual(paused.state[NAMESPACE]['state'], 'paused')
            self.assertEqual(len(self.dispatched), 1)
            self.db = NativeDB(self.work/'native.sqlite3'); self.admitted = True
            self.case.box.submit(self.case.capability, 'fresh-resume', 'resume')
            with self.store.claim('task', expected_revision=paused.revision) as owned:
                self.assertEqual(rec.resumable(owned, self.db, self.work/'work'), original.state['native_history'])
                controller = self.controller(owned, self.case.box)
                controller.bootstrap_controls()
                controller.llm(self.request(), None, session_id='session')
                self.assertEqual([row['content'] for row in self.dispatched[1]['messages']
                    if row.get('tool_call_id') == 'confirmed-read'], [self.read_result])
                self.tool(controller, 'write_file', {'path': 'answer.txt', 'content': 'Two short notes.'}, 'single-write')
                controller.llm(self.request(), None, session_id='session')
                self.db.append({'role': 'assistant', 'content': 'Created answer.txt.'})
                controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                                   'final_response': 'Created answer.txt.'})
            self.close_database()
            final = self.store.load('task')
            self.assertEqual(final.state['status'], 'accepted')
            self.assertEqual(final.state['deadline_monotonic'], 610)
            self.assertEqual((final.state['requests'], final.state['attempts'], final.state['admission_attempts']), (3, 3, 3))
            self.assertEqual(self.effects, ['read_file', 'write_file'])
            self.assertEqual(len((self.work/'effect-receipts.jsonl').read_text().splitlines()), 1)
        finally:
            for child in self.case.handles:
                if child.poll() is None: child.finish(0)
                await self.case.join_child(child)
            for lock in self.case.reopen_locks: lock.close()


if __name__ == '__main__': unittest.main()
