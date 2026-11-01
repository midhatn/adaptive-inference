"""Worker capability and native-failure ordering; real SQLite, scripted SDK edges."""
from copy import deepcopy
import json
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.desktop.hermes import recovery as rec, run_recovery as worker
from adaptive_inference.desktop.hermes.control_bridge import prepare_task
from recovery_capability_support import ReadWriteToolsets, definitions
from task_spec_support import spec_data
import test_desktop_expiry_worker as fixture


class RecoveryCapabilityTests(unittest.TestCase):
    def cleanup_fixture(self, value):
        # Share the outer unittest outcome so a nested cleanup error is retained
        # alongside any primary failure, as in the existing host fixture.
        with mock.patch.object(value, '_outcome', self._outcome):
            value.doCleanups()

    def exercise(self, *, names=('read_file', 'write_file'), valid_names=None,
                 fatal=None, outcome=None, outputs=None):
        f = fixture.WorkerExpiryTests()
        self.addCleanup(self.cleanup_fixture, f)
        f.setUp()
        self.fixture = f
        spec = TaskSpec(spec_data(inputs={}, outputs=outputs))
        identity = DemandIdentity('capability-registration', 'capability-task', 'worker', fixture.NOW)
        metadata = {'sdk_revision': worker.SDK_REV, 'model': worker.MODEL,
                    'quality': worker.QUALITY, 'deadline_clock': CLOCK_ID,
                    **spec.metadata(), 'pre_effect_validator': spec.validator_identity()}
        cp = prepare_task(f.store, identity, spec.prompt, 'capability-native', metadata=metadata)
        f.box = Mailbox(DemandRegistry((Registration(f.store, identity),)),
                        identity.registration_id, requester_capability=f.cap)
        f.box.submit(f.cap, 'resume', 'resume')
        f.plan.update(task_id=cp.task_id, session_id='capability-native', task_spec=spec.data,
                      task_spec_sha256=spec.sha256, pre_effect_validator=spec.validator_identity(),
                      demand_identity={key: getattr(identity, key) for key in
                          ('registration_id', 'task_id', 'owner_id', 'arrived_at_utc')})
        rec.save(f.run / 'plan.json', f.plan)
        f.args.deadline_monotonic = 900.0
        f.args.gateway_instance = 'capability-gateway'
        f.args.controller_ready = f.run / 'ready.json'
        rec.save(f.args.controller_ready, {'ready': True, 'model': worker.MODEL,
            'quality': worker.QUALITY, 'gateway': f.plan['gateway'],
            'gateway_instance': f.args.gateway_instance, 'observed_at': time.time()})
        self.calls, self.closed = [], []
        self.toolsets = ReadWriteToolsets()
        outer = self

        class Boundary:
            def __init__(self, *_):
                self.rows = []; self.steps = {'parent': 0}; self.seen = set()

        base = SimpleNamespace(Boundary=Boundary,
            git=lambda *a: worker.SDK_REV if a[0] == 'rev-parse' else '',
            snapshot=lambda _: {'fixture': 'scripted SDK capabilities'})

        class Provider:
            def __init__(self, **_):
                pass  # No request is sent by this conversation-return fixture.

            def close(self):
                outer.closed.append('provider')

        class Agent:
            def __init__(self, **kwargs):
                outer.agent_kwargs = kwargs
                self.session_id = kwargs['session_id']
                self._session_db = kwargs['session_db']
                self._active_session_turn_lease_holder = None
                # Deliberately allow an SDK declaration mismatch so the actual
                # worker gate, rather than the stub, must reject it.
                self.tools = definitions(names)
                self.valid_tool_names = set(names) if valid_names is None else valid_names

            def run_conversation(self, prompt, conversation_history=None, **_):
                outer.calls.append((prompt, deepcopy(conversation_history)))
                self._session_db.append({'role': 'user', 'content': prompt})
                self._session_db.append({'role': 'assistant', 'content': 'Native turn returned.'})
                rec.ACTIVE.fatal = fatal
                return deepcopy(outcome if outcome is not None else {
                    'completed': True, 'failed': False, 'interrupted': False,
                    'final_response': 'Native turn returned.'})

            def close(self):
                outer.closed.append('agent')

        sdk = ModuleType('run_agent'); sdk.AIAgent = Agent
        plugins = ModuleType('hermes_cli.plugins')
        plugins.get_plugin_manager = lambda: SimpleNamespace(_plugins={
            'recovery-checkpoint': SimpleNamespace(enabled=True, error=None)})
        interrupt = ModuleType('tools.interrupt'); interrupt.is_interrupted = lambda: False
        completion = TaskSpec.completion
        self.completions = []

        def observe_completion(task, *args, **kwargs):
            outer.completions.append(task.sha256)
            return completion(task, *args, **kwargs)

        code = f.invoke(patches=(
            mock.patch.object(worker, 'setup', return_value=(rec, base)),
            mock.patch('adaptive_inference.desktop.hermes.admission.Provider', Provider),
            mock.patch.object(rec, 'ACTIVE', None),
            mock.patch.object(TaskSpec, 'completion', observe_completion),
            mock.patch.dict(sys.modules, {'run_agent': sdk, 'toolsets': self.toolsets,
                'hermes_cli.plugins': plugins, 'tools.interrupt': interrupt})))
        self.result = f.result()
        self.checkpoint = f.store.load(cp.task_id)
        self.assertEqual(self.closed, ['agent', 'provider'])
        self.assertEqual([db.close_calls for db in f.opened], [1])
        self.assertIsNone(self.checkpoint.owner_epoch)
        self.assertIsNone(self.checkpoint.operation)
        self.assertFalse(self.checkpoint.requires_reconciliation)
        self.assertEqual(self.checkpoint.state['deadline_monotonic'], 900.0)
        self.assertEqual(self.result['provider_calls'], 0)
        return code

    def test_supported_worker_registers_only_read_write_and_completes(self):
        self.assertEqual(self.exercise(outputs=[]), 0, self.result)
        self.assertEqual(self.agent_kwargs['enabled_toolsets'], ['adaptive_file_read_write'])
        self.assertEqual(len(self.toolsets.registrations), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.result['passed'])
        self.assertEqual(self.checkpoint.state['status'], 'accepted')

    def test_extra_missing_duplicate_or_dispatch_mismatch_refused_before_conversation(self):
        cases = [('extra', ('read_file', 'write_file', 'search_files'), None),
                 ('missing', ('read_file',), None),
                 ('duplicate', ('read_file', 'read_file'), None),
                 ('dispatcher', ('read_file', 'write_file'), {'read_file', 'write_file', 'patch'})]
        for label, names, valid in cases:
            with self.subTest(case=label):
                self.assertEqual(self.exercise(names=names, valid_names=valid), 2, self.result)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.completions, [])
                self.assertEqual(self.result['error_type'], 'RecoveryStop')
                self.assertIn('SDK tool declarations', self.result['error'])
                self.assertEqual(self.checkpoint.state['status'], 'pending')

    def test_recovery_fatal_is_reported_before_missing_output(self):
        self.assertEqual(self.exercise(fatal='ReconciliationRequired'), 2, self.result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.completions, [])
        self.assertEqual(self.result['error_type'], 'RecoveryStop')
        self.assertIn('ReconciliationRequired', self.result['error'])
        self.assertNotIn('Required output', self.result['error'])

    def test_failed_and_interrupted_native_turns_precede_missing_output(self):
        for flag in ('failed', 'interrupted'):
            with self.subTest(flag=flag):
                outcome = {'completed': False, 'failed': False, 'interrupted': False,
                           'final_response': 'Native turn did not finish.'}
                outcome[flag] = True
                self.assertEqual(self.exercise(outcome=outcome), 2, self.result)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.completions, [])
                self.assertEqual(self.result['error_type'], 'RecoveryStop')
                self.assertIn('verified completed result', self.result['error'])
                self.assertNotIn('Required output', self.result['error'])

    def test_completed_native_turn_still_requires_the_durable_output(self):
        self.assertEqual(self.exercise(), 2, self.result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.completions), 1)
        self.assertEqual(self.result['error_type'], 'ValueError')
        self.assertEqual(self.result['error'], 'Required output has no durable write receipt')
        self.assertEqual(self.checkpoint.state['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
