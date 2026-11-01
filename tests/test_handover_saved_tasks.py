"""Actual later-task preparation/store/Stop/reopen; inert desktop/provider edges."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.demand import NAMESPACE
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.task_store import TaskBusyError, TaskStore
from adaptive_inference.desktop import composition, installation, saved_tasks as saved
from adaptive_inference.desktop.hermes import admission, recovery as rec, run_recovery as worker
from adaptive_inference.desktop.hermes.control_bridge import Controls
from adaptive_inference.desktop.hermes.service_stop import ProductStop, STOP_EXIT, StopAtPause
from adaptive_inference.desktop.profile import WindowsProfile
from test_desktop_composition import Child
import test_desktop_composition as composition_fixture
from test_desktop_installation import profile_value
from test_desktop_report_feedback import NativeDB
from test_desktop_saved_tasks import BOOT
import test_task_handover as fixture
from task_spec_support import spec_data


class HandoverSavedTasksTests(unittest.IsolatedAsyncioTestCase):
    request = fixture.HandoverTests.request
    reserve = fixture.HandoverTests.reserve
    paused_worker = fixture.HandoverTests.paused_worker
    open_grant = fixture.HandoverTests.open_grant
    _prepare_order = composition_fixture.CompositionTests._prepare_order

    async def asyncSetUp(self):
        original_make = fixture.make_case
        def make(root):
            case = original_make(root)
            case.root = root / 'runs/session-first'
            case.root.parent.mkdir()
            return case
        with mock.patch.object(fixture, 'make_case', side_effect=make):
            await fixture.HandoverTests.asyncSetUp(self)
        self.runs = self.c.root.parent
        self.package = {'version': 'fixture', 'files': {}}
        self.c.profile_path.write_text(json.dumps(profile_value(self.root)), encoding='utf-8')
        self.c.profile_sha256 = composition.sha(self.c.profile_path)
        self.c.reopen_context = saved.new_context(self.c.profile_sha256, self.package, BOOT)
        rec.save(self.c.root / 'reopen-context.private.json', self.c.reopen_context)
        rec.save(self.c.root / 'installed-package.private.json', self.package)
        self.new_spec = TaskSpec(spec_data())
        self.spec_path.write_text(json.dumps(self.new_spec.data), encoding='utf-8')
        (self.inputs / 'notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.db = None
        self.dispatched, self.effects = [], []
        self.now, self.admitted, self.stop_queued = 100.0, True, False

    async def asyncTearDown(self):
        if self.db is not None:
            self.db.close(); self.db = None
        await fixture.HandoverTests.asyncTearDown(self)
        for lock in self.c.reopen_locks:
            lock.close()
        if hasattr(self, 'case'):
            for child in self.case.handles:
                if child.poll() is None: child.finish(0)
                await self.case.join_child(child)
            for lock in self.case.reopen_locks: lock.close()

    def real_prepare(self, command, label):
        # Reuse the actual worker prepare command, including TaskSpec staging,
        # TaskAdmission's reserved identity and original-context binding.
        values = dict(zip(command[command.index('prepare')+1::2], command[command.index('prepare')+2::2]))
        args = SimpleNamespace(**{key[2:].replace('-', '_'): value for key, value in values.items()},
            fixture=False, fixture_scenario='normal', validate_report_before_write=False)
        for name in ('run', 'profile', 'package_identity', 'task_spec', 'task_inputs', 'demand_identity', 'reopen_context'):
            if hasattr(args, name): setattr(args, name, Path(getattr(args, name)))
        base = SimpleNamespace(git=lambda *args: worker.SDK_REV if args[0] == 'rev-parse' else '',
                               config=lambda work: {'cwd': str(work)})
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(worker, 'verify_execution_clock'))
            stack.enter_context(mock.patch.object(WindowsProfile, 'load', return_value=self.c.profile))
            stack.enter_context(mock.patch.object(installation, 'package_identity', return_value=self.package))
            stack.enter_context(mock.patch.object(installation, 'verify_interpreter', return_value=self.c.profile.worker_python))
            stack.enter_context(mock.patch.object(installation, 'verify_sdk', return_value=self.c.profile.hermes_source))
            stack.enter_context(mock.patch.object(worker, 'setup', return_value=(rec, base)))
            worker.prepare(args)
        child = Child(pid=42, code=0); self.c.handles.append(child)
        return child

    def controller(self, owned, box, capability):
        outer = self
        controls = Controls(box, deadline=self.deadline, deadline_clock=saved.CLOCK_ID,
            clock=lambda: self.now, utc_now=lambda: fixture.UTC,
            sleep=lambda _: self.fail('Unexpected paused control loop'))
        class Provider(admission.Provider):
            def __init__(self):
                self.model, self.instance = composition.MODEL, 'a' * 32
                self.deadline, self.clock = outer.deadline, lambda: outer.now
                self.current_attempt = self.body_sha256 = None
                self.status_reader = lambda: {'service': 'adaptive-inference', 'instance': self.instance,
                    'scheduler': {'active': False, 'pending': 0, 'closing': False,
                                  'backend_completion_uncertain': False},
                    'resources': {'admission_allowed': outer.admitted}}
                def create(**request):
                    outer.dispatched.append(deepcopy(request)); return {'scripted_transport': True}
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                def sleep(seconds):
                    outer.now += seconds
                    if not outer.stop_queued:
                        outer.stop_queued = True
                        box.submit(capability, 'ordinary-stop', 'pause')
                self.sleep = sleep
        value = rec.Recovery(owned, self.db, self.work / 'work', self.work, controls=controls)
        value.provider = Provider()
        return value

    def request_from_history(self):
        return {'model': composition.MODEL, 'messages': rec.native_history(self.db, self.session_id),
                'stream': False, 'max_tokens': 10923, 'extra_body': deepcopy(composition.QUALITY)}

    def tool(self, controller, name, args, call_id):
        self.db.append({'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]})
        def effect(value):
            self.effects.append(name)
            path = self.work / 'work' / value['path']
            if name == 'read_file': return json.dumps({'content': path.read_text()})
            path.write_text(value['content'], encoding='utf-8'); return json.dumps({'verified': True})
        result = controller.tool(name, args, effect, session_id=self.session_id, tool_call_id=call_id)
        self.assertNotIn('error', json.loads(result))
        self.db.append({'role': 'tool', 'tool_call_id': call_id, 'content': result})
        controller.control_safe_point()
        return result

    async def test_later_task_real_prepare_stop_discover_reopen_and_complete(self):
        grant = await self.reserve()
        with mock.patch.object(fixture.handover, 'execution_now', side_effect=lambda: self.now):
            await self.open_grant(self.initial_runtime, grant)
        self.work = self.c.work; self.task_id = self.c.identity.task_id
        plan = json.loads((self.work / 'plan.json').read_bytes())
        self.session_id = plan['session_id']; self.deadline = self.c.deadline
        bound = saved.bind_context(self.c.reopen_context, self.work)
        self.assertEqual(plan[saved.CONTEXT], bound)
        self.assertEqual(self.c.store.load(self.task_id).metadata[saved.CONTEXT], bound)
        before_discovery = (self.work / 'task.sqlite3').read_bytes()
        with mock.patch.object(saved.sqlite3, 'connect', side_effect=AssertionError('Discovery must not open stores')), \
                mock.patch.object(saved, 'observe_boot', side_effect=AssertionError('Discovery must not poll boot')):
            self.assertEqual(saved.discover(self.runs), [{'saved_task': str(self.work), 'label': self.new_spec.prompt}])
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before_discovery)
        with self.assertRaises(TaskBusyError): saved.claim_host(self.work)
        self.assertEqual(self.deadline, 1000.0)

        owned, claim = self.owners[self.task_id]
        self.db = NativeDB(self.work / 'native.sqlite3')
        self.c.box.submit(self.c.capability, 'first-resume', 'resume')
        controller = self.controller(owned, self.c.box, self.c.capability)
        controller.controls.safe_boundary = StopAtPause(controller, 'ordinary-stop')
        controller.bootstrap_controls()
        self.db.append({'role': 'user', 'content': self.new_spec.prompt})
        controller.llm(self.request_from_history(), None, session_id=self.session_id)
        read_result = self.tool(controller, 'read_file', {'path': 'notes.txt'}, 'saved-read')
        self.admitted = False
        with self.assertRaises(ProductStop):
            controller.llm(self.request_from_history(), None, session_id=self.session_id)
        claim.__exit__(None, None, None); self.claims.remove(claim)
        self.db.close(); self.db = None
        self.c.worker.finish(STOP_EXIT); await self.c.join_child(self.c.worker)
        for lock in self.c.reopen_locks: lock.close()
        stopped = self.c.store.load(self.task_id)
        self.assertEqual(stopped.state['phase'], 'waiting_admission')
        self.assertEqual(self.effects, ['read_file'])
        self.assertIsNone(stopped.owner_epoch); self.assertIsNone(stopped.operation)
        self.assertFalse(stopped.requires_reconciliation)

        self.case = composition.DesktopComposition(self.c.profile_path, self.runs / 'session-reopened', saved_task=self.work)
        self.case.root.mkdir()
        with mock.patch.object(saved, 'observe_boot', return_value=BOOT), \
                mock.patch.object(composition, 'execution_now', side_effect=lambda: self.now):
            await self._prepare_order(self.new_spec, reopened=True)
        paused = self.c.store.load(self.task_id)
        self.assertEqual(self.case.original, stopped)
        self.assertEqual(self.case.deadline, self.deadline)
        for key in ('requests', 'attempts', 'admission_attempts', 'native_history', 'tools', 'pending_request'):
            self.assertEqual(paused.state[key], stopped.state[key])
        self.assertEqual(paused.state[NAMESPACE]['state'], 'paused')
        self.assertEqual(len(self.dispatched), 1)
        self.db = NativeDB(self.work / 'native.sqlite3'); self.admitted = True
        self.case.box.submit(self.case.capability, 'new-resume', 'resume')
        with self.c.store.claim(self.task_id, expected_revision=paused.revision) as owner:
            self.assertEqual(rec.resumable(owner, self.db, self.work / 'work'), stopped.state['native_history'])
            controller = self.controller(owner, self.case.box, self.case.capability)
            controller.bootstrap_controls()
            self.db.append({'role': 'user', 'content': worker.CONTINUE})
            controller.llm(self.request_from_history(), None, session_id=self.session_id)
            self.assertEqual([row['content'] for row in self.dispatched[1]['messages']
                              if row.get('tool_call_id') == 'saved-read'], [read_result])
            self.tool(controller, 'write_file', {'path': 'answer.txt', 'content': 'Two short notes.'}, 'one-write')
            controller.llm(self.request_from_history(), None, session_id=self.session_id)
            self.db.append({'role': 'assistant', 'content': 'Created answer.txt.'})
            controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                               'final_response': 'Created answer.txt.'})
        self.db.close(); self.db = None
        final = self.c.store.load(self.task_id)
        self.assertEqual(final.state['status'], 'accepted')
        self.assertEqual(final.state['deadline_monotonic'], self.deadline)
        self.assertEqual(tuple(final.state[key] for key in ('requests', 'attempts', 'admission_attempts')), (3, 3, 3))
        self.assertEqual(self.effects, ['read_file', 'write_file'])
        self.assertEqual(len((self.work / 'effect-receipts.jsonl').read_text().splitlines()), 1)
        before = (self.work / 'task.sqlite3').read_bytes()
        self.assertEqual(saved.completed_result(saved.read_saved(self.work))['provider_calls'], 0)
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before)

    async def test_handover_without_original_context_stays_unlisted(self):
        self.c.reopen_context = None
        grant = await self.reserve()
        record = self.coordinator.records[grant['request_id']]
        with mock.patch.object(self.c, 'launch', side_effect=self.real_prepare):
            await self.coordinator.prepare_episode(record)
        work = Path(record['reservation']['payload']['run'])
        plan = json.loads((work / 'plan.json').read_bytes())
        checkpoint = TaskStore(work / 'task.sqlite3').load(plan['task_id'])
        self.assertNotIn(saved.CONTEXT, plan)
        self.assertNotIn(saved.CONTEXT, checkpoint.metadata)
        self.assertNotIn('deadline_monotonic', checkpoint.state)
        self.assertEqual(saved.discover(self.runs), [])
        self.assertEqual(self.c.reopen_locks, [])
