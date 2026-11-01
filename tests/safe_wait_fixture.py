"""Deterministic worker-path reproducer: real SQLite; scripted SDK/transport edges.

No actual model, SDK agent, GUI, native engine, process launch, or OS join proof.
The original 900-second budget is unchanged; the test starts its clock at 899.
"""
from copy import deepcopy
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock
from recovery_capability_support import ReadWriteToolsets

from adaptive_inference.control_mailbox import EXECUTION_OUTCOME
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.desktop.hermes import admission, recovery as rec, run_recovery as worker
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding, flushed_tools
from test_desktop_expiry_worker import WorkerExpiryTests
from test_desktop_paused_expiry import ClosingDB

OUTPUT = None  # Set explicitly by the private runner to a fresh directory.
RESULTS = {}


class SafeWaitCases(unittest.TestCase):
    def setUp(self):
        self.fixture = WorkerExpiryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.case = OUTPUT / self._testMethodName
        self.case.mkdir()
        self.addCleanup(self.preserve)
        self.mode = 'expiry'
        self.dispatched = []
        self.closed = []
        self.before_wait = None

    def preserve(self):
        # Called after worker cleanup; preserve the exact actual SQLite evidence.
        for item in self.fixture.run.rglob('*'):
            if item.is_file():
                relative = item.relative_to(self.fixture.run)
                target = self.case / 'run' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, target)

    def exercise(self, mode):
        self.mode = mode
        f, outer = self.fixture, self
        toolsets = ReadWriteToolsets()
        f.now = 899.0
        f.args.deadline_monotonic = 900.0
        f.args.stop_request_id = 'service-stop'
        f.args.gateway_instance = 'a' * 32
        f.args.controller_ready = f.run / 'ready.json'
        f.args.controller_ready.write_text(json.dumps({
            'ready': True, 'model': worker.MODEL, 'quality': worker.QUALITY,
            'gateway': f.plan['gateway'], 'gateway_instance': f.args.gateway_instance,
            'observed_at': time.time()}), encoding='utf-8')
        (f.run/'work/orders.csv').write_text('item,quantity\npen,1\n', encoding='utf-8')
        f.box.submit(f.cap, 'initial-resume', 'resume')

        class DB(ClosingDB):
            def session_turn_lease_expires_at(self, session, holder):
                if (session, holder) != ('native', 'scripted-holder'):
                    raise AssertionError('Unexpected synthetic SDK lease identity')
                return time.time() + 1000

        class Boundary:
            def __init__(self, *_):
                self.rows = []; self.steps = {'parent': 0}; self.seen = set()

        base = SimpleNamespace(Boundary=Boundary,
            git=lambda *a: worker.SDK_REV if a[0] == 'rev-parse' else '',
            snapshot=lambda agent: {'fixture': 'scripted SDK constructor only'})

        class Provider(admission.Provider):
            # Preserve the real execute/admitted implementation and callbacks.
            # Only constructor-side SDK clients and the external service change.
            def __init__(self, *, base_url, model, instance, boundary, deadline, **unused):
                outer.assertEqual(deadline, 900)
                self.base_url, self.model, self.instance = base_url, model, instance
                self.boundary, self.deadline = boundary, deadline
                self.clock = lambda: f.now
                self.current_attempt = self.body_sha256 = None
                self.status_reader = lambda: {
                    'service': 'adaptive-inference', 'instance': instance,
                    'scheduler': {'active': False, 'pending': 0, 'closing': False,
                                  'backend_completion_uncertain': False},
                    'resources': {'admission_allowed': not outer.dispatched}}
                def create(**request):
                    outer.dispatched.append(deepcopy(request))
                    self.boundary.rows.append({'fixture': 'completed provider transport'})
                    return {'fixture': 'assistant read_file intent'}
                self.client = SimpleNamespace(chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create)))
                def advance(seconds):
                    f.now += seconds
                    if len(outer.dispatched) == 1 and f.now >= 899.25 and not getattr(self, 'queued', False):
                        self.queued = True
                        if mode == 'stop':
                            f.box.submit(f.cap, 'service-stop', 'pause')
                        elif mode == 'cancel':
                            f.box.submit(f.cap, 'genuine-cancel', 'cancel')
                self.sleep = advance
            def close(self):
                outer.closed.append('provider')

        class Agent:
            def __init__(self, **kwargs):
                self.session_id = kwargs['session_id']
                self._session_db = kwargs['session_db']
                self._active_session_turn_lease_holder = 'scripted-holder'
                self.activity = []
                self.tools,self.valid_tool_names=toolsets.agent_tools(kwargs['enabled_toolsets'])
            def _touch_activity(self, label):
                self.activity.append(label)  # Scripted SDK activity; no watchdog thread.
            def run_conversation(self, prompt, conversation_history=None, **unused):
                outer.assertEqual(prompt, worker.PROMPT)
                outer.assertIsNone(conversation_history)
                c, db = rec.ACTIVE, self._session_db
                db.append({'role': 'user', 'content': prompt})
                c.llm({'model': worker.MODEL, 'messages': [{'role': 'user', 'content': prompt}],
                       'stream': False}, None, session_id='native')
                args = {'path': 'orders.csv'}
                db.append({'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'read-input-1', 'type': 'function', 'function': {
                        'name': 'read_file', 'arguments': json.dumps(args)}}]})
                result = c.tool('read_file', args,
                    lambda value: json.dumps({'content': (c.work/value['path']).read_text(encoding='utf-8')}),
                    session_id='native', tool_call_id='read-input-1')
                outer.assertNotIn('error', json.loads(result))
                db.append({'role': 'tool', 'tool_call_id': 'read-input-1', 'content': result})
                c.control_safe_point()
                outer.before_wait = deepcopy(c.owned.checkpoint.state)
                pending = {'model': worker.MODEL, 'messages': rec.native_history(db, 'native'),
                           'stream': False, 'max_tokens': 10923, 'extra_body': worker.QUALITY}
                outer.pending = deepcopy(pending)
                c.llm(pending, None, session_id='native')
                raise AssertionError('Second provider request must not dispatch')
            def close(self):
                outer.closed.append('agent')
                self._active_session_turn_lease_holder = None

        agent_module = ModuleType('run_agent'); agent_module.AIAgent = Agent
        plugins = ModuleType('hermes_cli.plugins')
        plugins.get_plugin_manager = lambda: SimpleNamespace(_plugins={
            'recovery-checkpoint': SimpleNamespace(enabled=True, error=None)})
        interrupt = ModuleType('tools.interrupt'); interrupt.is_interrupted = lambda: False
        code = f.invoke(database=DB, patches=(
            mock.patch.object(worker, 'setup', return_value=(rec, base)),
            mock.patch.object(admission, 'Provider', Provider),
            mock.patch.object(rec, 'ACTIVE', None),
            mock.patch.dict(sys.modules, {'run_agent': agent_module, 'toolsets': toolsets, 'hermes_cli.plugins': plugins,
                                          'tools.interrupt': interrupt})))
        self.code, self.result = code, f.result()
        self.cp = f.store.load('orders-report')
        self.native = DB(f.run/'home/state.db', read_only=True)
        try:
            self.history = rec.native_history(self.native, 'native')
        finally:
            self.native.close()
        return code

    def common_preservation(self):
        cp, f = self.cp, self.fixture
        self.assertEqual(cp.prompt, f.original.prompt)
        self.assertEqual(cp.metadata, f.original.metadata)
        self.assertEqual(cp.max_attempts, 8)
        self.assertEqual(cp.state['session_id'], 'native')
        self.assertEqual(cp.state['deadline_monotonic'], 900.0)
        self.assertEqual(cp.state['deadline_clock'], CLOCK_ID)
        self.assertEqual(cp.state['status'], 'pending')
        self.assertEqual(cp.state['phase'], 'waiting_admission')
        self.assertEqual(cp.state['pending_request'], self.pending)
        self.assertEqual(cp.state['native_history'], self.before_wait['native_history'])
        self.assertEqual(cp.state['native_history'], self.history)
        self.assertEqual(len(self.history), 3)
        self.assertEqual(cp.state['tools'], self.before_wait['tools'])
        self.assertEqual(len(cp.state['tools']), 1)
        self.assertEqual(cp.state['tools'][0]['name'], 'read_file')
        self.assertEqual((cp.state['requests'], cp.state['attempts'], cp.state['admission_attempts']), (1, 1, 1))
        self.assertIsNone(cp.owner_epoch)
        self.assertIsNone(cp.operation)
        self.assertFalse(cp.requires_reconciliation)
        flushed_tools(cp.state)
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(self.result['provider_calls'], 1)
        self.assertEqual(self.closed, ['agent', 'provider'])
        self.assertEqual([db.close_calls for db in f.opened], [1])
        self.assertNotIn('cleanup_errors', self.result)
        self.assertNotIn(EXECUTION_OUTCOME, cp.state)
        self.assertNotIn('paused_expiry', self.result)
        self.assertFalse((f.run/'work/report.json').exists())
        self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def verify_exit(self, code, *, request_before_verify=False):
        async def run():
            f = self.fixture
            # Synthetic retained launch edge: no real process or join claim.
            retained = SimpleNamespace(pid=os.getpid(), poll=lambda: None if request_before_verify else code,
                                       wait=lambda: code)
            binding = WorkerStopBinding(retained, f.run, f.box,
                requester_capability=f.cap, capability=object(), stop_request_id='service-stop',
                original=f.original, deadline_monotonic=900.0, deadline_clock=CLOCK_ID,
                model=worker.MODEL, quality=worker.QUALITY, fence=lambda: None)
            if request_before_verify:
                binding._request()  # Actual host ordering: poll says alive, worker already relinquished.
            return binding._verify_exit(code)
        # The worker uses this synthetic clock; receipt verification must use it
        # too. A host performance counter has an unrelated, undefined origin.
        with mock.patch('adaptive_inference.desktop.hermes.service_stop.execution_now',
                        side_effect=lambda: self.fixture.now):
            return asyncio.run(run())

    def record(self, **details):
        snapshot = self.fixture.box.snapshot()
        RESULTS[self._testMethodName] = {
            'exit_code': self.code, 'phase': self.cp.state['phase'], 'status': self.cp.state['status'],
            'clock': self.fixture.now, 'deadline': self.cp.state['deadline_monotonic'],
            'provider_calls': len(self.dispatched), 'native_rows': len(self.history),
            'pending_request_sha256': rec.digest(self.pending),
            'native_history_sha256': rec.digest(self.history),
            'owner_released': self.cp.owner_epoch is None, 'inflight': self.cp.operation,
            'reconciliation': self.cp.requires_reconciliation,
            'request_commands': [row['command'] for row in snapshot.requests],
            'ack_commands': [row['command'] for row in snapshot.receipts], **details}
        (self.case/'projection.private.json').write_text(json.dumps(RESULTS[self._testMethodName], indent=2)+'\n')

    def test_deadline_first_preserves_work_but_late_stop_is_not_recognized(self):
        self.assertEqual(self.exercise('expiry'), 2, self.result)
        self.common_preservation()
        self.assertEqual(self.fixture.now, 900.0)
        self.assertEqual(self.result['error_type'], 'ControlStop')
        self.assertEqual((self.result['control_state'], self.result['control_reason']),
                         ('active', 'control_wait_deadline'))
        self.assertNotIn('service_stop', self.result)
        with self.assertRaisesRegex(rec.RecoveryStop, 'known cooperative outcome'):
            self.verify_exit(2, request_before_verify=True)
        snapshot = self.fixture.box.snapshot()
        self.assertEqual(snapshot.requests[-1]['request_id'], 'service-stop')
        self.assertNotIn('service-stop', [row['request_id'] for row in snapshot.receipts])
        with self.assertRaises(rec.RecoveryStop):
            self.verify_exit(4)  # Merely relabeling the exit never produces a valid proof.
        with self.assertRaises(rec.RecoveryStop):
            self.verify_exit(5)  # It is not an acknowledged paused expiry either.
        self.record(host_outcome='refused', late_stop_acknowledged=False,
                    recognized_safe_expiry=False, error_type=self.result['error_type'])

    def test_stop_before_deadline_is_acknowledged_without_dispatch(self):
        self.assertEqual(self.exercise('stop'), 4, self.result)
        self.common_preservation()
        self.assertEqual(self.fixture.now, 899.25)
        self.assertEqual(self.verify_exit(4), 'service_stopped')
        self.assertEqual(self.result['service_stop']['request_id'], 'service-stop')
        self.record(host_outcome='service_stopped', late_stop_acknowledged=True,
                    recognized_safe_expiry=False)

    def test_cancel_before_deadline_stays_distinct(self):
        self.assertEqual(self.exercise('cancel'), 3, self.result)
        self.common_preservation()
        self.assertEqual(self.verify_exit(3), 'task_cancelled')
        self.assertNotIn('service_stop', self.result)
        self.assertEqual(self.fixture.now, 899.25)
        self.record(host_outcome='task_cancelled', recognized_safe_expiry=False)
