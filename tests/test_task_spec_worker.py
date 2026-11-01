"""Preparation and continuation contract boundaries, using real TaskStore only."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.task_spec import TaskSpec, NAMESPACE, digest
from adaptive_inference.task_store import TaskStore
from adaptive_inference.desktop.hermes import recovery as rec, run_recovery as worker
from adaptive_inference.desktop import installation
from adaptive_inference.desktop.profile import WindowsProfile
from task_spec_support import spec_data
import test_continuation_storage as continuation_fixture
import test_desktop_expiry_worker as expiry_fixture


class TaskPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'inputs'; self.source.mkdir()
        (self.source/'notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.spec = TaskSpec(spec_data())
        self.spec_path = self.root/'task.json'; self.spec_path.write_bytes(json.dumps(self.spec.data).encode())
        self.profile_path = self.root/'profile.json'; self.profile_path.write_text('{}')
        self.package = self.root/'package.json'; self.package.write_text('{}')
        self.dependencies = self.root/'dependencies'; self.dependencies.mkdir()
        self.args = SimpleNamespace(run=self.root/'run',profile=self.profile_path,
            profile_sha256=digest(self.profile_path.read_bytes()),package_identity=self.package,
            task_spec=self.spec_path,task_spec_sha256=digest(self.spec_path.read_bytes()),task_inputs=self.source,
            task_id='task-A',session_id='native-A',fixture=False,fixture_scenario='normal',
            control_case='complete',validate_report_before_write=False)
        self.profile = SimpleNamespace(worker_python=self.root/'python',worker_python_sha256='a'*64,
            hermes_source=self.root/'sdk',hermes_site_packages=self.dependencies,gateway=SimpleNamespace(port=18100))
        self.base = SimpleNamespace(git=lambda *a: worker.SDK_REV if a[0]=='rev-parse' else '',
            config=lambda work: {'cwd':str(work)})

    def invoke(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(worker,'verify_execution_clock'))
            stack.enter_context(mock.patch.object(WindowsProfile,'load',return_value=self.profile))
            stack.enter_context(mock.patch.object(installation,'package_identity',return_value={'files':{}}))
            stack.enter_context(mock.patch.object(installation,'verify_interpreter',return_value=self.profile.worker_python))
            stack.enter_context(mock.patch.object(installation,'verify_sdk',return_value=self.profile.hermes_source))
            stack.enter_context(mock.patch.object(worker,'setup',return_value=(rec,self.base)))
            worker.prepare(self.args)

    def reserve(self, **changes):
        row = {'registration_id':'reserved-A','task_id':'task-A','owner_id':'host',
            'arrived_at_utc':'2026-10-26T12:00:00Z',**changes}
        path = self.root/'identity.json'; path.write_bytes(json.dumps(row).encode())
        self.args.demand_identity = path; self.args.demand_identity_sha256 = digest(path.read_bytes())
        return row

    def test_exact_prompt_spec_inputs_and_reserved_identity_prepared_once(self):
        reserved = self.reserve(); self.invoke()
        plan = json.loads((self.args.run/'plan.json').read_text())
        cp = TaskStore(self.args.run/'task.sqlite3').load('task-A')
        self.assertEqual(plan['demand_identity'],reserved)
        self.assertEqual(cp.prompt,self.spec.prompt); self.assertEqual(cp.state['session_id'],'native-A')
        self.assertEqual(TaskSpec.from_metadata(cp.metadata),self.spec)
        self.assertEqual(worker.prepared_contract(plan),self.spec)
        self.assertEqual((self.args.run/'work/notes.txt').read_bytes(),(self.source/'notes.txt').read_bytes())
        self.assertFalse((self.args.run/'work/orders.csv').exists())
        for path, expected in plan['pins'].items(): self.assertEqual(digest(Path(path).read_bytes()),expected)
        with self.assertRaises(FileExistsError): self.invoke()
        self.assertEqual(TaskStore(self.args.run/'task.sqlite3').load('task-A'),cp)

    def test_fresh_reopen_context_is_bound_in_both_plan_and_immutable_metadata(self):
        from adaptive_inference.desktop import saved_tasks
        context = saved_tasks.new_context(self.args.profile_sha256, {'files':{}}, {
            'source':saved_tasks.BOOT_SOURCE,'boot_utc':'2026-11-01T08:12:13.1234567Z','computer_name':'fixture'})
        self.args.reopen_context = self.root/'reopen.json'
        rec.save(self.args.reopen_context, context)
        self.invoke()
        plan=json.loads((self.args.run/'plan.json').read_text())
        cp=TaskStore(self.args.run/'task.sqlite3').load('task-A')
        expected=saved_tasks.bind_context(context,self.args.run)
        self.assertEqual(plan[saved_tasks.CONTEXT], expected)
        self.assertEqual(cp.metadata[saved_tasks.CONTEXT], expected)
        self.assertIsNone(cp.state.get('deadline_monotonic'))

    def test_malformed_reserved_identity_pair_refuses_before_run_creation(self):
        self.reserve(); self.args.demand_identity_sha256 = None
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse(self.args.run.exists())

    def test_wrong_reserved_task_refuses_before_run_creation(self):
        self.reserve(task_id='another')
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse(self.args.run.exists())

    def test_duplicate_identity_key_refuses_even_with_matching_raw_hash(self):
        self.reserve(); raw = self.args.demand_identity.read_bytes().rstrip()[:-1] + b',"task_id":"task-A"}'
        self.args.demand_identity.write_bytes(raw); self.args.demand_identity_sha256 = digest(raw)
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse(self.args.run.exists())

    def test_changed_input_or_spec_refuses_before_run_creation(self):
        (self.source/'notes.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse(self.args.run.exists())


class TaskContinuationTests(unittest.TestCase):
    def test_successor_preserves_spec_prompt_scope_and_predecessor_bytes(self):
        fixture = continuation_fixture.ContinuationTests()
        self.addCleanup(fixture.doCleanups)
        spec = TaskSpec(spec_data(prompt='Preserve original task',inputs={},outputs=[]))
        original_prepare = continuation_fixture.prepare_task
        def prepare(store,identity,prompt,session_id,*,metadata,**kwargs):
            return original_prepare(store,identity,prompt,session_id,
                metadata={**metadata,**spec.metadata(),'pre_effect_validator':spec.validator_identity()},**kwargs)
        with mock.patch.object(continuation_fixture,'prepare_task',side_effect=prepare): fixture.setUp()
        before = fixture.raw_old(); grant = fixture.authorize()
        cp = fixture.store.load(grant['payload']['successor_id'])
        self.assertEqual(fixture.raw_old(),before)
        self.assertEqual(rec.task_contract(cp),spec); self.assertEqual(cp.prompt,spec.prompt)
        self.assertNotIn(NAMESPACE,cp.state)
        self.assertEqual(cp.state['requests'],2); self.assertEqual(cp.state['session_id'],'same-session')
        self.assertEqual(fixture.authority.lookup(grant['payload']),grant)

    def test_generic_worker_expires_and_refuses_sealed_restart_with_its_own_spec(self):
        from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
        from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME
        from adaptive_inference.desktop.hermes.control_bridge import prepare_task
        from adaptive_inference.execution_clock import CLOCK_ID
        fixture = expiry_fixture.WorkerExpiryTests(); self.addCleanup(fixture.doCleanups); fixture.setUp()
        spec = TaskSpec(spec_data(inputs={},outputs=[],prompt='Explain an ordinary scheduling idea.'))
        identity = DemandIdentity('generic-registration','generic-task','worker',expiry_fixture.NOW)
        metadata = {'sdk_revision':worker.SDK_REV,'model':worker.MODEL,'quality':worker.QUALITY,
                    'deadline_clock':CLOCK_ID,**spec.metadata(),'pre_effect_validator':spec.validator_identity()}
        cp = prepare_task(fixture.store,identity,spec.prompt,'generic-native',metadata=metadata)
        registry = DemandRegistry((Registration(fixture.store,identity),))
        fixture.box = Mailbox(registry,identity.registration_id,requester_capability=fixture.cap)
        fixture.box.submit(fixture.cap,'generic-pause','pause')
        fixture.plan.update(task_id=cp.task_id,session_id='generic-native',task_spec=spec.data,
            task_spec_sha256=spec.sha256,pre_effect_validator=spec.validator_identity(),
            demand_identity={key:getattr(identity,key) for key in ('registration_id','task_id','owner_id','arrived_at_utc')})
        (fixture.run/'plan.json').write_text(json.dumps(fixture.plan),encoding='utf-8')
        self.assertEqual(fixture.invoke(),5)
        current = fixture.store.load(cp.task_id)
        self.assertIn(EXECUTION_OUTCOME,current.state); self.assertEqual(rec.task_contract(current),spec)
        self.assertEqual(current.state['status'],'pending'); self.assertIsNone(current.owner_epoch)
        with mock.patch.object(worker,'setup',side_effect=AssertionError('no SDK construction')):
            with self.assertRaises(rec.ReconciliationRequired): worker.worker(fixture.args)
        self.assertEqual(fixture.store.load(cp.task_id),current)
