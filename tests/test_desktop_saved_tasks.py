"""Actual saved stores/controls plus inert startup seams; no installed agent/UI."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, ACKS
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.task_store import TaskStore, ReconciliationRequired, TaskBusyError
from adaptive_inference.desktop import saved_tasks as saved
from adaptive_inference.desktop import composition
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from adaptive_inference.desktop.hermes import recovery as rec
from test_desktop_report_feedback import NativeDB
from test_desktop_installation import profile_value
from task_spec_support import spec_data
import test_desktop_composition as composition_fixture

BOOT = {'source': saved.BOOT_SOURCE, 'boot_utc': '2026-11-01T08:12:13.1234567Z', 'computer_name': 'fixture'}
PACKAGE = {'version': 'fixture', 'files': {'fixture.py': 'a' * 64}}


class SavedTasksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runs = self.root / 'runs'; self.runs.mkdir()
        self.work = self.runs / 'session-original/hermes-task'
        (self.work / 'work').mkdir(parents=True)
        (self.work / 'work/notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.profile = self.root / 'profile.json'
        self.profile.write_text(json.dumps(profile_value(self.root)), encoding='utf-8')
        self.profile_sha = composition.sha(self.profile)
        self.context = saved.bind_context(saved.new_context(self.profile_sha, PACKAGE, BOOT), self.work)
        self.spec = TaskSpec(spec_data())
        self.identity = DemandIdentity('registration', 'task', 'worker', '2026-11-01T10:00:00Z')
        self.store = TaskStore(self.work / 'task.sqlite3')
        cp = prepare_task(self.store, self.identity, self.spec.prompt, 'session', metadata={
            **self.spec.metadata(), 'pre_effect_validator': self.spec.validator_identity(),
            'deadline_clock': saved.CLOCK_ID, saved.CONTEXT: self.context})
        self.db = NativeDB(self.work / 'native.sqlite3'); self.addCleanup(self.db.close)
        self.db.append({'role': 'user', 'content': self.spec.prompt})
        self.db.append({'role': 'tool', 'tool_call_id': 'read-1', 'content': 'First note. Second note.'})
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state)
            state.update(deadline_monotonic=1000.0, requests=2, attempts=1, admission_attempts=3,
                         native_history=rec.native_history(self.db, 'session'),
                         tools=[{'name': 'read_file', 'tool_call_id': 'read-1',
                                 'args': {'path': 'notes.txt'}, 'result': 'First note. Second note.'}])
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        self.plan = {'task_id': 'task', 'session_id': 'session', saved.CONTEXT: self.context,
                     'task_spec': self.spec.data, 'demand_identity': self.identity.metadata(),
                     'pins': {str(self.work / 'work/notes.txt'): rec.digest((self.work / 'work/notes.txt').read_bytes())}}
        rec.save(self.work / 'plan.json', self.plan)

    def inspect(self, **overrides):
        args = dict(profile_sha256=self.profile_sha, installed=PACKAGE, boot=BOOT, now=250.0)
        args.update(overrides)
        return saved.inspect_saved(self.work, **args)

    def test_plan_only_discovery_does_not_open_or_repair_database(self):
        journal = self.work / 'task.sqlite3-journal'; journal.write_bytes(b'preserve unknown journal')
        before = {p: p.read_bytes() for p in self.work.rglob('*') if p.is_file()}
        with mock.patch.object(saved.sqlite3, 'connect', side_effect=AssertionError('No database discovery')), \
                mock.patch.object(saved, 'observe_boot', side_effect=AssertionError('No polling')):
            self.assertEqual(saved.discover(self.runs), [{'saved_task': str(self.work), 'label': self.spec.prompt}])
        self.assertEqual(before, {p: p.read_bytes() for p in self.work.rglob('*') if p.is_file()})
        with self.assertRaises(ReconciliationRequired): self.inspect()
        self.assertEqual(journal.read_bytes(), b'preserve unknown journal')

    def test_same_task_read_history_and_budget_survive_readonly_reopen_and_new_pause(self):
        original = self.store.load('task'); before = (self.work / 'task.sqlite3').read_bytes()
        selected = self.inspect(now=800.0)
        self.assertEqual(selected['checkpoint'], original)
        self.assertEqual(selected['deadline'], 1000.0)
        self.assertEqual(before, (self.work / 'task.sqlite3').read_bytes())
        registry = DemandRegistry((Registration(self.store, self.identity),)); capability = object()
        box = Mailbox(registry, self.identity.registration_id, requester_capability=capability)
        box.submit(capability, 'new-host-startup-pause', 'pause')
        host = SimpleNamespace(adapter=SimpleNamespace(launch_intent=None, started_owner=False),
            gateway=SimpleNamespace(_runtime_context=None, history=[], scheduler=SimpleNamespace(
                active=None, pending=0, uncertain=False)), controller=SimpleNamespace(fault=None))
        with self.store.claim('task', expected_revision=original.revision) as owned:
            self.assertEqual(rec.resumable(owned, self.db, self.work / 'work'), original.state['native_history'])
            box.consume(owned, updated_at_utc='2026-11-01T10:01:00Z')
            saved.assert_paused_saved(owned.checkpoint, original, 1000.0, host)
            self.assertTrue(box.status('new-host-startup-pause')['owner_acknowledged'])
            for key in ('requests', 'attempts', 'admission_attempts', 'native_history', 'tools', 'deadline_monotonic'):
                self.assertEqual(owned.checkpoint.state[key], original.state[key])

    def test_changed_missing_context_expiry_and_unknown_effect_refuse_without_reset(self):
        original = (self.work / 'task.sqlite3').read_bytes()
        for options in ({'boot': {**BOOT, 'boot_utc': '2026-11-02T08:12:13.1234567Z'}},
                        {'profile_sha256': 'b' * 64}, {'installed': {'version': 'other'}}, {'now': 1000.0}):
            with self.subTest(options=options), self.assertRaises(ReconciliationRequired): self.inspect(**options)
        self.assertEqual(original, (self.work / 'task.sqlite3').read_bytes())
        plan = deepcopy(self.plan); plan.pop(saved.CONTEXT); rec.save(self.work / 'plan.json', plan)
        self.assertEqual(saved.discover(self.runs), [])
        with self.assertRaises(ReconciliationRequired): self.inspect()
        rec.save(self.work / 'plan.json', self.plan)
        cp = self.store.load('task')
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            owned.begin_operation('effect', details={'unknown': True}, expected_revision=owned.checkpoint.revision)
        with self.assertRaises(ReconciliationRequired): self.inspect()

    def test_host_lock_excludes_second_owner_and_releases(self):
        first = saved.claim_host(self.work)
        try:
            with self.assertRaises(TaskBusyError): saved.claim_host(self.work)
        finally: first.close()
        second = saved.claim_host(self.work); second.close()

    def test_actual_fresh_process_reads_the_original_budget_and_progress(self):
        source = '''
import json, sys
from adaptive_inference.desktop.saved_tasks import inspect_saved
value=inspect_saved(sys.argv[1], **json.loads(sys.argv[2]))
cp=value['checkpoint']
print(json.dumps({'deadline':value['deadline'],'requests':cp.state['requests'],
 'attempts':cp.state['attempts'],'read':cp.state['tools'][0]['result']}))
'''
        env = os.environ.copy(); env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        result = subprocess.run([sys.executable, '-B', '-c', source, str(self.work), json.dumps({
            'profile_sha256': self.profile_sha, 'installed': PACKAGE, 'boot': BOOT, 'now': 600.0})],
            env=env, capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), {'deadline':1000.0, 'requests':2, 'attempts':1,
                                                     'read':'First note. Second note.'})

    def test_completed_task_opens_result_without_model_or_budget_renewal(self):
        cp = self.store.load('task')
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state)
            state.update(status='accepted', phase='accepted', output='Saved completed answer.')
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        before = (self.work / 'task.sqlite3').read_bytes()
        selected = self.inspect(now=2000.0)
        self.assertEqual(saved.completed_result(selected)['output'], 'Saved completed answer.')
        case = composition.DesktopComposition(self.profile, self.runs / 'session-reopened', saved_task=self.work)
        with mock.patch.object(composition, 'os', SimpleNamespace(name='nt', getpid=os.getpid)), \
                mock.patch.object(composition, 'sys', SimpleNamespace(version_info=(3,11,9))), \
                mock.patch.object(composition, 'verify_execution_clock'), \
                mock.patch.object(composition, 'verify_interpreter') as interpreter, \
                mock.patch.object(composition, 'verify_sdk', side_effect=AssertionError('No SDK for result view')), \
                mock.patch.object(composition, 'package_identity', return_value={'version': 'new installation'}), \
                mock.patch.object(saved, 'observe_boot', side_effect=AssertionError('No boot query for result view')), \
                mock.patch.object(composition, 'execution_now', return_value=2000.0), \
                mock.patch.object(case, 'launch', side_effect=AssertionError('No child for saved result')):
            import asyncio
            result = asyncio.run(case.run())
        self.assertTrue(result['clean_stop'] and result['task_completed'])
        self.assertEqual(result['saved_result']['provider_calls'], 0)
        self.assertEqual(before, (self.work / 'task.sqlite3').read_bytes())
        self.assertIsNone(case.host); self.assertEqual(case.handles, [])
        self.assertEqual(interpreter.call_count, 1)


class AdmissionWaitReopenTests(unittest.IsolatedAsyncioTestCase):
    """Real wait/Stop/store/rebuild path; only transport and desktop edges are inert."""

    _prepare_order = composition_fixture.CompositionTests._prepare_order

    async def asyncSetUp(self):
        from adaptive_inference.desktop.hermes import admission
        from adaptive_inference.desktop.hermes.control_bridge import Controls
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runs = self.root / 'runs'; self.runs.mkdir()
        self.work = self.runs / 'session-original/hermes-task'
        (self.work / 'work').mkdir(parents=True)
        (self.work / 'work/notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.profile = self.root / 'profile.json'
        self.profile.write_text(json.dumps(profile_value(self.root)), encoding='utf-8')
        self.package = {'version': 'fixture', 'files': {}}
        self.context = saved.bind_context(saved.new_context(composition.sha(self.profile), self.package, BOOT), self.work)
        self.spec = TaskSpec(spec_data())
        self.identity = DemandIdentity('registration', 'task', 'worker', '2026-11-01T10:00:00Z')
        self.store = TaskStore(self.work / 'task.sqlite3')
        prepare_task(self.store, self.identity, self.spec.prompt, 'session', metadata={
            'model': composition.MODEL, 'quality': composition.QUALITY,
            **self.spec.metadata(), 'pre_effect_validator': self.spec.validator_identity(),
            'deadline_clock': saved.CLOCK_ID, saved.CONTEXT: self.context})
        registry = DemandRegistry((Registration(self.store, self.identity),))
        self.capability = object()
        self.box = Mailbox(registry, self.identity.registration_id, requester_capability=self.capability)
        rec.save(self.work / 'plan.json', {'task_id': 'task', 'session_id': 'session',
            'deadline_clock': saved.CLOCK_ID, saved.CONTEXT: self.context,
            'task_spec': self.spec.data, 'task_spec_sha256': self.spec.sha256,
            'base_python': str(self.root / 'worker.exe'), 'gateway': 'http://127.0.0.1:18100/v1',
            'demand_identity': {key: getattr(self.identity, key) for key in
                                ('registration_id', 'task_id', 'owner_id', 'arrived_at_utc')},
            'pins': {str(self.work / 'work/notes.txt'): rec.digest((self.work / 'work/notes.txt').read_bytes())}})
        self.db = NativeDB(self.work / 'native.sqlite3')
        self.addCleanup(self.close_database)
        self.now, self.deadline = 100.0, 1000.0
        self.dispatched, self.effects = [], []
        self.admitted, self.unknown_dispatch, self.stop_queued = True, False, False
        outer = self

        class Provider(admission.Provider):
            def __init__(self):
                # Reuse execute/admitted and actual recovery callbacks. No SDK,
                # socket or model is constructed by these external edge stubs.
                self.model, self.instance = composition.MODEL, 'a' * 32
                self.deadline, self.clock = outer.deadline, lambda: outer.now
                self.current_attempt = self.body_sha256 = None
                self.status_reader = lambda: {'service': 'adaptive-inference', 'instance': self.instance,
                    'scheduler': {'active': False, 'pending': 0, 'closing': False,
                                  'backend_completion_uncertain': False},
                    'resources': {'admission_allowed': outer.admitted}}
                def create(**request):
                    outer.dispatched.append(deepcopy(request))
                    if outer.unknown_dispatch:
                        raise OSError('Dispatched response outcome is unknown')
                    return {'scripted_transport': True}
                self.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                def sleep(seconds):
                    outer.now += seconds
                    if not outer.stop_queued:
                        outer.stop_queued = True
                        outer.box.submit(outer.capability, 'ordinary-stop', 'pause')
                self.sleep = sleep

        self.provider_type = Provider
        self.controls_type = Controls

    def close_database(self):
        if self.db is not None:
            self.db.close(); self.db = None

    def controller(self, owned, box):
        controls = self.controls_type(box, deadline=self.deadline, deadline_clock=saved.CLOCK_ID,
            clock=lambda: self.now, utc_now=lambda: '2026-11-01T10:00:00Z',
            sleep=lambda seconds: self.fail('No unobserved pause loop expected'))
        value = rec.Recovery(owned, self.db, self.work / 'work', self.work, controls=controls)
        value.provider = self.provider_type()
        return value

    def request(self):
        return {'model': composition.MODEL, 'messages': rec.native_history(self.db, 'session'),
                'stream': False, 'max_tokens': 10923, 'extra_body': deepcopy(composition.QUALITY)}

    def tool(self, controller, name, args, call_id):
        self.db.append({'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]})
        def effect(value):
            self.effects.append(name)
            if name == 'read_file':
                return json.dumps({'content': (self.work / 'work' / value['path']).read_text()})
            (self.work / 'work' / value['path']).write_text(value['content'], encoding='utf-8')
            return json.dumps({'verified': True})
        result = controller.tool(name, args, effect, session_id='session', tool_call_id=call_id)
        self.assertNotIn('error', json.loads(result))
        self.db.append({'role': 'tool', 'tool_call_id': call_id, 'content': result})
        controller.control_safe_point()
        return result

    def read_then_stop(self, *, unknown=False):
        from adaptive_inference.desktop.hermes.service_stop import StopAtPause, ProductStop
        cp = self.store.load('task')
        self.box.submit(self.capability, 'initial-resume', 'resume')
        with self.store.claim('task', expected_revision=cp.revision) as owned:
            state = deepcopy(owned.checkpoint.state); state['deadline_monotonic'] = self.deadline
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
            controller = self.controller(owned, self.box)
            controller.controls.safe_boundary = StopAtPause(controller, 'ordinary-stop')
            controller.bootstrap_controls()
            self.db.append({'role': 'user', 'content': self.spec.prompt})
            controller.llm(self.request(), None, session_id='session')
            self.read_result = self.tool(controller, 'read_file', {'path': 'notes.txt'}, 'confirmed-read')
            self.pending = self.request()
            self.admitted, self.unknown_dispatch = unknown, unknown
            if unknown:
                with self.assertRaises(rec.RecoveryStop):
                    controller.llm(self.pending, None, session_id='session')
            else:
                with self.assertRaises(ProductStop) as stopped:
                    controller.llm(self.pending, None, session_id='session')
                self.stop_receipt = stopped.exception.receipt
                self.assertEqual(self.stop_receipt['phase'], 'waiting_admission')
                self.assertEqual(self.box.status('ordinary-stop')['outcome'], 'applied')
        self.close_database()
        return self.store.load('task')

    async def test_real_admission_wait_stop_reopens_paused_then_resumes_saved_read(self):
        original = self.read_then_stop()
        self.assertIsNone(original.owner_epoch); self.assertIsNone(original.operation)
        self.assertFalse(original.requires_reconciliation)
        self.assertEqual(original.state['pending_request'], self.pending)
        self.assertEqual((original.state['requests'], original.state['attempts'],
                          original.state['admission_attempts']), (1, 1, 1))
        self.assertEqual(self.effects, ['read_file']); self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(saved.discover(self.runs)[0]['saved_task'], str(self.work))
        old_bytes = (self.work / 'task.sqlite3').read_bytes()
        selected = saved.inspect_saved(self.work, profile_sha256=composition.sha(self.profile),
            installed=self.package, boot=BOOT, now=self.now)
        self.assertEqual(selected['checkpoint'], original)
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), old_bytes)

        self.case = composition.DesktopComposition(self.profile, self.runs / 'session-reopened', saved_task=self.work)
        self.case.root.mkdir()
        with mock.patch.object(saved, 'observe_boot', return_value=BOOT), \
                mock.patch.object(composition, 'execution_now', side_effect=lambda: self.now):
            await self._prepare_order(self.spec, reopened=True)
        paused = self.store.load('task')
        self.assertEqual(self.case.deadline, original.state['deadline_monotonic'])
        self.assertEqual(paused.state['pending_request'], self.pending)
        self.assertEqual(paused.state['native_history'], original.state['native_history'])
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(paused.state[NAMESPACE]['state'], 'paused')

        self.db = NativeDB(self.work / 'native.sqlite3')
        self.admitted = True
        self.case.box.submit(self.case.capability, 'fresh-resume', 'resume')
        with self.store.claim('task', expected_revision=paused.revision) as owned:
            self.assertEqual(rec.resumable(owned, self.db, self.work / 'work'), original.state['native_history'])
            controller = self.controller(owned, self.case.box)
            controller.bootstrap_controls()
            # The ordinary worker passes CONTINUE with the same native history.
            from adaptive_inference.desktop.hermes.run_recovery import CONTINUE
            self.db.append({'role': 'user', 'content': CONTINUE})
            controller.llm(self.request(), None, session_id='session')
            resumed = self.dispatched[1]
            self.assertEqual([row['content'] for row in resumed['messages'] if row.get('tool_call_id') == 'confirmed-read'],
                             [self.read_result])
            self.tool(controller, 'write_file', {'path': 'answer.txt', 'content': 'Two short notes.'}, 'single-write')
            controller.llm(self.request(), None, session_id='session')
            self.db.append({'role': 'assistant', 'content': 'Created answer.txt.'})
            controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                               'final_response': 'Created answer.txt.'})
        self.close_database()
        final = self.store.load('task')
        self.assertEqual(final.state['status'], 'accepted')
        self.assertEqual(final.state['deadline_monotonic'], self.deadline)
        self.assertEqual((final.state['requests'], final.state['attempts'], final.state['admission_attempts']), (3, 3, 3))
        self.assertEqual(self.effects, ['read_file', 'write_file'])
        self.assertEqual(len((self.work / 'effect-receipts.jsonl').read_text().splitlines()), 1)
        self.assertTrue(any(row['payload']['state'].get('pending_request') == self.pending
                            for row in self.store.history('task')))
        self.assertEqual(saved.completed_result(saved.read_saved(self.work))['provider_calls'], 0)

    async def test_dispatched_unknown_generation_stays_refused(self):
        cp = self.read_then_stop(unknown=True)
        self.assertEqual(len(self.dispatched), 2)
        self.assertEqual(cp.operation['kind'], 'generation')
        self.assertTrue(cp.requires_reconciliation)
        before = (self.work / 'task.sqlite3').read_bytes()
        with self.assertRaises(ReconciliationRequired):
            saved.inspect_saved(self.work, profile_sha256=composition.sha(self.profile),
                installed=self.package, boot=BOOT, now=self.now)
        self.assertEqual((self.work / 'task.sqlite3').read_bytes(), before)
        self.assertEqual(self.effects, ['read_file'])


class BootObservationTests(unittest.TestCase):
    def test_documented_observer_is_single_bounded_local_hidden_call(self):
        with mock.patch.object(saved, 'os', SimpleNamespace(name='nt', environ={'SystemRoot':'C:/Windows'})), \
                mock.patch.object(saved.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
                mock.patch.object(saved.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(BOOT))) as run:
            self.assertEqual(saved.observe_boot(), BOOT)
        run.assert_called_once(); args, kwargs = run.call_args
        self.assertEqual(kwargs['timeout'], 10); self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['creationflags'], 0x08000000)
        self.assertIn('-NoProfile', args[0]); self.assertIn('-NonInteractive', args[0])
        self.assertIn('Get-CimInstance', args[0][-1]); self.assertNotIn('-ComputerName', args[0][-1])

    def test_missing_or_ambiguous_boot_value_is_not_guessed(self):
        for value in (None, {}, {**BOOT, 'boot_utc':'2026-11-01T08:12:13'},
                      {**BOOT, 'boot_utc':'2026-99-01T08:12:13.1234567Z'}):
            with self.subTest(value=value), self.assertRaises(ValueError): saved.validate_boot(value)


if __name__ == '__main__': unittest.main()
