"""CPU/real SQLite component checks; no host, SDK, child, model or OS cleanup claim."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from adaptive_inference.demand import DemandIdentity, NAMESPACE, DemandRegistry, Registration
from adaptive_inference.task_store import TaskStore, OwnedTask, TaskBusyError, RevisionConflict, ReconciliationRequired
from adaptive_inference.task_spec import TaskSpec, BUDGET
from adaptive_inference.desktop.task_admission import TaskAdmission


UTC = '2026-10-26T12:00:00Z'
PROOF = '1' * 64  # Trusted caller evidence reference, not fabricated OS proof.


def spec(prompt='Summarize these ideas in your final response.'):
    return TaskSpec({'schema': 'adaptive.task-spec.v1', 'prompt': prompt,
        'inputs': [], 'outputs': [], 'budget': BUDGET, 'validation': {'validator': None}})


def create_task(store, identity, task_spec, session, *, accepted=False, metadata=None):
    return store.create(identity.task_id, task_spec.prompt, max_attempts=8,
        metadata={**task_spec.metadata(), NAMESPACE: identity.metadata(), **(metadata or {})},
        state={'status': 'accepted' if accepted else 'pending', 'messages': [
            {'role': 'user', 'content': task_spec.prompt}], 'attempts': 0, 'feedback': [],
            'output': 'Completed.' if accepted else '', 'session_id': session})


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.initial = self.root / 'initial'; self.initial.mkdir()
        self.tasks = self.root / 'tasks'; self.tasks.mkdir()
        self.store = TaskStore(self.root / 'host.sqlite3')
        self.old_store = TaskStore(self.initial / 'task.sqlite3')
        self.old_identity = DemandIdentity('initial-demand', 'initial-task', 'host-one', UTC)
        self.old = create_task(self.old_store, self.old_identity, spec('Initial task.'), 'initial-session', accepted=True)
        self.admission = TaskAdmission(self.store, host_generation='host-one', tasks_root=self.tasks,
                                      initial_task_id=self.old.task_id, initial_run=self.initial)

    def claim(self):
        cp = self.store.load(self.admission.task_id)
        return self.store.claim(cp.task_id, expected_revision=cp.revision, owner_id='retained-host')

    def request(self, command='command-one', *, task_spec=None, predecessor=None, revision=None):
        status = self.admission.status()
        selected = status['selected']
        cp = TaskStore(Path(selected['run']) / 'task.sqlite3').load(selected['task_id'])
        return self.admission.request(command_id=command,
            expected_selection_revision=status['selection_revision'],
            predecessor_execution_id=predecessor or cp.task_id,
            predecessor_revision=cp.revision if revision is None else revision,
            spec=task_spec or spec(), arrived_at_utc=UTC)

    def reserve(self, owner, request=None):
        return self.admission.reserve(owner, request or self.request(), predecessor_cleanup_sha256=PROOF)

    def stage(self, grant, *, override=None):
        payload = deepcopy(grant['payload'])
        if override:
            override(payload)
        run = Path(grant['payload']['run']); run.mkdir(); (run / 'work').mkdir()
        store = TaskStore(run / 'task.sqlite3')
        identity = DemandIdentity(**{k: payload['demand_identity'][k] for k in
            ('registration_id', 'task_id', 'owner_id', 'arrived_at_utc')})
        cp = create_task(store, identity, TaskSpec(payload['task_spec']), payload['session_id'])
        return store, cp, identity

    def prepare(self, owner, request=None):
        grant = self.reserve(owner, request)
        operation = self.admission.begin(owner, grant, action='prepare')
        staged = self.stage(grant)
        self.admission.prepared(owner, grant, operation_id=operation)
        return grant, staged

    def complete_task(self, store, cp, identity, *, cancel=False):
        with store.claim(cp.task_id, expected_revision=cp.revision) as owner:
            if cancel:
                registry = DemandRegistry([Registration(store, identity)])
                registry.transition(identity.registration_id, owner, 'cancelled',
                    expected_revision=owner.checkpoint.revision, updated_at_utc=UTC,
                    reason='Explicit user cancellation before launch')
            else:
                state = deepcopy(owner.checkpoint.state); state['status'] = 'accepted'; state['output'] = 'Done.'
                owner.save_checkpoint(state, expected_revision=owner.checkpoint.revision)
        return store.load(cp.task_id)

    def test_three_distinct_tasks_keep_history_and_independent_task_stores(self):
        originals = self.old_store.history(self.old.task_id)
        selected = []
        with self.claim() as owner:
            for n, prompt in enumerate(('List three coding ideas.', 'Explain photosynthesis.', 'Write a short poem.')):
                request = self.request('command-' + str(n), task_spec=spec(prompt))
                grant, (store, cp, identity) = self.prepare(owner, request)
                self.assertEqual(cp.prompt, prompt)
                self.assertEqual(self.admission.status()['selection_revision'], n + 1)
                operation = self.admission.begin(owner, grant, action='launch')
                cp = self.complete_task(store, cp, identity)
                self.admission.finish(owner, grant, execution_id=cp.task_id, task_revision=cp.revision,
                                      operation_id=operation, cleanup_sha256=PROOF)
                selected.append(cp.task_id)
                self.assertFalse(self.admission.status()['stop_fenced'])
        self.assertEqual(len(set(selected)), 3)
        self.assertEqual(len(list(self.tasks.iterdir())), 3)
        self.assertEqual(self.old_store.history(self.old.task_id), originals)

    def test_duplicate_is_immutable_without_repeat_effect_or_revision(self):
        request = self.request()
        with self.claim() as owner:
            grant = self.reserve(owner, request)
            revision = owner.checkpoint.revision
            self.assertEqual(self.reserve(owner, request), grant)
            self.assertEqual(self.admission.lookup(request), grant)
            self.assertEqual(owner.checkpoint.revision, revision)
            changed = deepcopy(request); changed['task_spec'] = spec('Different prompt.').data
            changed['task_spec_sha256'] = spec('Different prompt.').sha256
            with self.assertRaises(RevisionConflict):
                self.admission.lookup(changed)

    def test_preparation_interruption_remains_fenced_without_replay(self):
        request = self.request()
        with self.claim() as owner:
            grant = self.reserve(owner, request)
            operation = self.admission.begin(owner, grant, action='prepare')
        self.assertTrue(self.admission.status()['requires_reconciliation'])
        self.assertTrue(self.admission.status()['stop_fenced'])
        self.assertEqual(self.admission.lookup(request), grant)
        self.assertFalse(Path(request['run']).exists())
        with self.claim() as owner:
            with self.assertRaises(ReconciliationRequired):
                self.admission.prepared(owner, grant, operation_id=operation)

    def test_lost_reserve_return_is_resolved_by_exact_lookup(self):
        original = OwnedTask.save_checkpoint
        def lost(owner, *args, **kwargs):
            original(owner, *args, **kwargs)
            raise OSError('Injected lost return after SQLite commit')
        request = self.request()
        with self.claim() as owner:
            with patch.object(OwnedTask, 'save_checkpoint', lost), self.assertRaises(OSError):
                self.reserve(owner, request)
        grant = self.admission.lookup(request)
        self.assertIsNotNone(grant)
        self.assertEqual(len(self.admission.status()['admissions']), 1)
        with self.claim() as owner:
            self.assertEqual(self.reserve(owner, request), grant)
            operation = self.admission.begin(owner, grant, action='prepare')
            self.stage(grant)
            self.admission.prepared(owner, grant, operation_id=operation)

    def test_lost_prepared_return_selects_once_without_launch(self):
        original = OwnedTask.complete_operation
        def lost(owner, *args, **kwargs):
            original(owner, *args, **kwargs)
            raise OSError('Injected lost return after preparation commit')
        with self.claim() as owner:
            request = self.request(); grant = self.reserve(owner, request)
            operation = self.admission.begin(owner, grant, action='prepare'); self.stage(grant)
            with patch.object(OwnedTask, 'complete_operation', lost), self.assertRaises(OSError):
                self.admission.prepared(owner, grant, operation_id=operation)
        self.assertEqual(self.admission.status()['selection_revision'], 1)
        self.assertIsNone(self.admission.status()['operation'])
        self.assertEqual(self.admission.lookup(request), grant)
        self.assertTrue(self.admission.status()['stop_fenced'])

    def test_unknown_launch_cannot_be_relabelled_no_child(self):
        with self.claim() as owner:
            grant, (store, cp, identity) = self.prepare(owner)
            operation = self.admission.begin(owner, grant, action='launch')
        cp = self.complete_task(store, cp, identity, cancel=True)
        with self.claim() as owner:
            with self.assertRaises(ReconciliationRequired):
                self.admission.finish(owner, grant, execution_id=cp.task_id,
                    task_revision=cp.revision, operation_id=operation, cleanup_sha256=PROOF)
        self.assertTrue(self.admission.status()['stop_fenced'])

    def test_cancel_before_launch_hands_back_for_another_task(self):
        with self.claim() as owner:
            grant, (store, cp, identity) = self.prepare(owner)
            cp = self.complete_task(store, cp, identity, cancel=True)
            self.admission.finish(owner, grant, execution_id=cp.task_id,
                                  task_revision=cp.revision, cleanup_sha256=PROOF)
            self.assertFalse(self.admission.status()['stop_fenced'])
            next_grant = self.reserve(owner, self.request('next-command'))
            self.assertNotEqual(next_grant['payload']['task_id'], cp.task_id)

    def test_stop_before_staging_abandons_without_replaying_or_selecting(self):
        with self.claim() as owner:
            request = self.request(); grant = self.reserve(owner, request)
            self.assertTrue(self.admission.status()['stop_fenced'])
            self.admission.abandon(owner, grant, cleanup_sha256=PROOF)
            status = self.admission.status()
            self.assertFalse(status['stop_fenced'])
            self.assertEqual(status['selection_revision'], 0)
            self.assertEqual(status['selected']['task_id'], self.old.task_id)
            self.assertEqual(self.reserve(owner, request), grant)
            with self.assertRaises(ReconciliationRequired):
                self.admission.begin(owner, grant, action='prepare')
            next_grant = self.reserve(owner, self.request('another-command'))
            self.assertEqual(next_grant['selection_revision'], 1)
            self.assertNotEqual(next_grant['payload']['task_id'], grant['payload']['task_id'])

    def test_abandon_refuses_existing_staging_or_started_operation(self):
        with self.claim() as owner:
            grant = self.reserve(owner)
            Path(grant['payload']['run']).mkdir()
            with self.assertRaises(ReconciliationRequired):
                self.admission.abandon(owner, grant, cleanup_sha256=PROOF)
            with self.assertRaises(ReconciliationRequired):
                self.admission.begin(owner, grant, action='prepare')
            Path(grant['payload']['run']).rmdir()  # Exact empty fixture directory.
            self.admission.begin(owner, grant, action='prepare')
            with self.assertRaises(ReconciliationRequired):
                self.admission.abandon(owner, grant, cleanup_sha256=PROOF)

    def test_cancelled_prepared_task_cannot_launch_from_stale_preparation(self):
        with self.claim() as owner:
            grant, (store, cp, identity) = self.prepare(owner)
            self.complete_task(store, cp, identity, cancel=True)
            with self.assertRaises(ReconciliationRequired):
                self.admission.begin(owner, grant, action='launch')
            self.assertIsNone(self.admission.status()['operation'])

    def test_accepted_without_recorded_launch_cannot_clear_obligation(self):
        with self.claim() as owner:
            grant, (store, cp, identity) = self.prepare(owner)
            cp = self.complete_task(store, cp, identity)
            with self.assertRaisesRegex(ReconciliationRequired, 'explicit cancellation'):
                self.admission.finish(owner, grant, execution_id=cp.task_id,
                                      task_revision=cp.revision, cleanup_sha256=PROOF)
            status = self.admission.status()
            self.assertTrue(status['stop_fenced'])
            self.assertEqual(status['admissions'][-1]['phase'], 'prepared')
            self.assertIsNone(status['admissions'][-1]['release'])

    def test_same_prompt_spec_unrelated_execution_refused(self):
        other = DemandIdentity('other-demand', 'unrelated', 'host-one', UTC)
        create_task(self.old_store, other, spec('Initial task.'), 'other-session', accepted=True)
        with self.claim() as owner, self.assertRaises(ReconciliationRequired):
            self.reserve(owner, self.request(predecessor='unrelated', revision=0))

    def test_stale_predecessor_and_selection_revisions_refused(self):
        with self.claim() as owner:
            with self.assertRaises(RevisionConflict):
                self.reserve(owner, self.request(revision=1))
            request = self.request(); request['expected_selection_revision'] = 1
            with self.assertRaises(RevisionConflict):
                self.reserve(owner, request)

    def test_prepared_exact_prompt_spec_session_demand_required(self):
        variants = (
            lambda p: p.update(task_spec=spec('A substituted task.').data),
            lambda p: p.update(session_id='another-session'),
            lambda p: p['demand_identity'].update(owner_id='another-owner'),
        )
        for index, change in enumerate(variants):
            with self.subTest(variant=index):
                # Every refusal gets an independent authority/store; no failed
                # operation is cleared merely to continue the next fixture.
                case = AdmissionTests('runTest'); case.setUp()
                try:
                    with case.claim() as owner:
                        grant = case.reserve(owner)
                        operation = case.admission.begin(owner, grant, action='prepare')
                        case.stage(grant, override=change)
                        with self.assertRaises((ReconciliationRequired, ValueError)):
                            case.admission.prepared(owner, grant, operation_id=operation)
                        self.assertEqual(case.admission.status()['selection_revision'], 0)
                finally:
                    case.doCleanups()

    def test_missing_task_store_is_not_created_by_verification(self):
        with self.claim() as owner:
            grant = self.reserve(owner); operation = self.admission.begin(owner, grant, action='prepare')
            run = Path(grant['payload']['run']); run.mkdir()
            with self.assertRaises(ReconciliationRequired):
                self.admission.prepared(owner, grant, operation_id=operation)
            self.assertFalse((run / 'task.sqlite3').exists())

    def test_predecessor_claim_is_blocked_through_selection_write(self):
        original = OwnedTask.complete_operation
        attempted = []
        def observe(owner, *args, **kwargs):
            with self.assertRaises(TaskBusyError):
                with self.old_store.claim(self.old.task_id, expected_revision=self.old.revision):
                    self.fail('Old task claim crossed the selection boundary')
            attempted.append(True)
            return original(owner, *args, **kwargs)
        with self.claim() as owner:
            grant = self.reserve(owner); operation = self.admission.begin(owner, grant, action='prepare')
            self.stage(grant)
            with patch.object(OwnedTask, 'complete_operation', observe):
                self.admission.prepared(owner, grant, operation_id=operation)
        self.assertEqual(attempted, [True])

    def test_foreign_host_and_mutated_paths_refused(self):
        request = self.request()
        for key, value in (('host_generation', 'other-host'), ('run', str(self.initial)),
                           ('task_spec_sha256', 'f' * 64), ('task_id', 'other-task')):
            changed = deepcopy(request); changed[key] = value
            with self.subTest(field=key), self.assertRaises(ReconciliationRequired):
                self.admission.lookup(changed)

    def test_declared_input_must_exist_and_match_before_selection(self):
        data = spec().data
        data['inputs'] = [{'name': 'notes.txt', 'bytes': 1, 'sha256': 'f' * 64}]
        with self.claim() as owner:
            grant = self.reserve(owner, self.request(task_spec=TaskSpec(data)))
            operation = self.admission.begin(owner, grant, action='prepare'); self.stage(grant)
            with self.assertRaises(FileNotFoundError):
                self.admission.prepared(owner, grant, operation_id=operation)
            self.assertEqual(self.admission.status()['selected']['task_id'], self.old.task_id)


if __name__ == '__main__':
    unittest.main()
