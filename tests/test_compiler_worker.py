"""Worker binding and public plugin selection; real SQLite, no SDK/model/compiler."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.hermes import recovery as rec, run_recovery as worker
from adaptive_inference.desktop.hermes.compiler_worker import make_recovery, SCHEMA
from adaptive_inference.desktop.hermes.compiler_recovery import CompilerRecovery
from adaptive_inference.desktop.hermes.continuation import wire_rows
from adaptive_inference.task_store import ReconciliationRequired
from recovery_capability_support import definitions
import test_compiler_recovery as recovery_fixture
import test_continuation_storage as continuation_fixture


class CompilerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = f = recovery_fixture.CompilerRecoveryTests()
        self.addCleanup(f.doCleanups)
        f.setUp()
        self.plan = {'gateway': 'http://127.0.0.1:18100/v1'}
        self.args = SimpleNamespace(compiler_binding=f.run/'binding.json', compiler_binding_sha256=None,
                                    gateway_instance='gateway-1', deadline_monotonic=900.)
        self.binding = {'schema': SCHEMA, 'host_epoch': 'host-1', 'task_id': 'task',
                        'execution_id': 'task', 'task_deadline': 900.,
                        'gateway_instance': 'gateway-1', 'capability': 'a'*64}
        self.save_binding()

    def save_binding(self):
        raw = json.dumps(self.binding).encode()
        self.args.compiler_binding.write_bytes(raw)
        self.args.compiler_binding_sha256 = rec.digest(raw)

    def build(self, spec=True):
        f = self.fixture
        return make_recovery(f.owned, f.db, f.work, f.run, task_spec=f.spec if spec else None,
                             plan=self.plan, args=self.args, controls=f.controller.controls)

    def test_selected_binding_uses_original_deadline_and_same_gateway(self):
        controller = self.build()
        self.assertIs(type(controller), CompilerRecovery)
        self.assertEqual(controller.compiler_client.port, 18100)
        self.assertEqual(controller.compiler_client.task_deadline, 900.)
        self.assertEqual(controller.task_id, 'task')
        self.assertEqual(controller.execution_id, 'task')
        self.assertNotIn('a'*64, repr(controller.compiler_client))
        self.assertEqual(self.fixture.calls, [])

    def test_missing_changed_or_wrong_task_binding_refused_before_client(self):
        original = deepcopy(self.binding)
        for key, value in [('task_id', 'other'), ('execution_id', 'other'),
                           ('task_deadline', 1800.), ('gateway_instance', 'old'),
                           ('schema', 'unknown')]:
            with self.subTest(key=key):
                self.binding = {**original, key: value}; self.save_binding()
                with self.assertRaises(ReconciliationRequired): self.build()
        self.binding = original; self.save_binding()
        self.args.compiler_binding_sha256 = 'f'*64
        with self.assertRaises(ReconciliationRequired): self.build()
        self.args.compiler_binding = None
        with self.assertRaises(ReconciliationRequired): self.build()
        self.assertIsNone(self.fixture.owned.checkpoint.operation)

    def test_file_only_task_refuses_compiler_launch_data(self):
        with self.assertRaises(ReconciliationRequired): self.build(spec=False)

    def test_compiler_tool_is_registered_before_middlewares_with_public_context(self):
        controller = self.build()
        calls = []
        def register_tool(**kwargs):
            calls.append(('tool', kwargs)); return object()
        ctx = SimpleNamespace(register_tool=register_tool,
            register_middleware=lambda name, callback: calls.append((name, callback)))
        with mock.patch.object(rec, 'ACTIVE', controller): rec.register(ctx)
        self.assertEqual([row[0] for row in calls], ['tool', 'llm_execution', 'tool_execution'])
        tool = calls[0][1]
        self.assertEqual(tool['name'], 'build_and_test')
        self.assertIs(tool['is_async'], False)
        self.assertEqual(set(tool['schema']['parameters']['properties']), {'recipe_id', 'source'})
        self.assertNotIn('capability', json.dumps(tool['schema']))

    def test_plugin_registration_refusal_blocks_middleware_installation(self):
        controller = self.build()
        callbacks = []
        ctx = SimpleNamespace(register_tool=lambda **_: None,
                              register_middleware=lambda *row: callbacks.append(row))
        with mock.patch.object(rec, 'ACTIVE', controller), self.assertRaises(RuntimeError): rec.register(ctx)
        self.assertEqual(callbacks, [])

    def test_advertised_capabilities_follow_explicit_task_contract(self):
        for names, spec, accepted in [
                (('read_file', 'write_file'), None, True),
                (('read_file', 'write_file', 'build_and_test'), self.fixture.spec, True),
                (('read_file', 'write_file'), self.fixture.spec, False),
                (('read_file', 'write_file', 'build_and_test'), None, False),
                (('read_file', 'write_file', 'build_and_test', 'terminal'), self.fixture.spec, False)]:
            agent = SimpleNamespace(tools=definitions(names), valid_tool_names=set(names))
            with self.subTest(names=names, compiler=spec is not None):
                if accepted: worker.verify_task_tools(agent, spec)
                else:
                    with self.assertRaises(rec.RecoveryStop): worker.verify_task_tools(agent, spec)

    def test_compiler_wire_scope_survives_original_contract_validation(self):
        f = self.fixture
        state = deepcopy(f.owned.checkpoint.state); state['requests'] = 1
        f.owned.save_checkpoint(state, expected_revision=f.owned.checkpoint.revision)
        cp = f.owned.checkpoint
        row = continuation_fixture.ContinuationTests().wire_row(1)
        cp.metadata.update(model=row['model'], quality=row['quality'])
        row['tool_names'].append('build_and_test')
        scope = {'gateway': 'http://127.0.0.1:1/v1'}
        self.assertEqual(wire_rows(json.dumps([row]).encode(), cp, scope), [row])
        row['tool_names'].append('terminal')
        with self.assertRaises(ReconciliationRequired): wire_rows(json.dumps([row]).encode(), cp, scope)

    def test_continuation_verifies_compiler_effects_in_the_existing_receipt_file(self):
        from adaptive_inference.desktop.hermes.continuation_worker import effect_receipts
        f = self.fixture
        call, args = f.intent()
        result = f.dispatch(call, args); f.flush(call, result)
        raw = (f.run/'effect-receipts.jsonl').read_bytes()
        self.assertEqual(effect_receipts(f.owned, f.run), rec.digest(raw))
        (f.run/'effect-receipts.jsonl').write_bytes(b'')
        with self.assertRaises(ReconciliationRequired): effect_receipts(f.owned, f.run)


if __name__ == '__main__': unittest.main()
