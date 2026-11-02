"""Real TaskStore/mailbox/native SQLite, loopback HTTP and inert runner only."""
import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.desktop.compiler_bridge import HEADER, ROUTE
from adaptive_inference.desktop.compiler_host import CompilerHost
from adaptive_inference.desktop.compiler_recipe import Executable, RecipeCleanupError
from adaptive_inference.desktop.compiler_template import CompilerSettings, prepare_cpp_recipe
from adaptive_inference.desktop.control_transport import PreparedTask
from adaptive_inference.desktop.hermes.recovery import initial_state, digest
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.ui_intent import UIIntentGate, VerifiedUIObservation
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_spec import TaskSpec
from adaptive_inference.task_store import TaskStore
from test_compiler_task_spec import compiler_data
from test_desktop_mailbox_runtime import FakeLifecycle

NOW = '2026-11-02T10:00:00Z'
LINK = 'adaptive_inference.execution_authorization.v1'


class CompilerHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compiler-host-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'work').mkdir()
        self.now, self.deadline = 100.0, 1000.0
        self.spec = TaskSpec(compiler_data(max_runs=3))
        self.native_path = self.root / 'native.sqlite3'
        with closing(sqlite3.connect(self.native_path)) as db, db:
            db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        self.append({'role': 'user', 'content': self.spec.prompt})
        self.store = TaskStore(self.root / 'task.sqlite3')
        self.identity = DemandIdentity('registered', 'task', 'host-1', NOW)
        self.create('task', self.identity)
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.cap = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.cap)
        self.context = None
        self.claim('task')
        self.registry.transition('registered', self.owned, 'active',
            expected_revision=self.owned.checkpoint.revision, updated_at_utc=NOW)
        self.intent = object()
        self.gate = UIIntentGate(host_epoch='host-1', capability=self.intent,
            verify_current=lambda binding: VerifiedUIObservation(binding, time.monotonic(), True, True))
        self.runtime = MailboxRuntime(PreparedTask('host-1', 'task', self.spec.prompt), self.box,
            requester_capability=self.cap, gate=self.gate, intent_capability=self.intent,
            lifecycle=FakeLifecycle(), max_age_s=3)
        self.worker, self.live, self.joined = object(), True, False
        self.reader = self.native
        self.read_entered, self.read_release = threading.Event(), threading.Event()
        self.read_release.set()
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.runs, self.recipes, self.mode = [], [], 'failed'
        pins = []
        for name in ('cmake', 'ctest', 'clang-cl', 'ninja', 'lld-link'):
            path = self.root / (name + '.exe')
            path.write_bytes(b'inert fixture: ' + name.encode())
            pins.append(Executable(path, hashlib.sha256(path.read_bytes()).hexdigest()))
        self.settings = CompilerSettings(*pins, environment=())
        self.capability = 'c' * 64
        self.host = CompilerHost(object(), self.settings, host_epoch='host-1',
            clock=lambda: self.now, runner=self.runner)
        app = web.Application()
        self.host.add_route(app)
        self.client = TestClient(TestServer(app, handler_cancellation=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.read_release.set()
        self.release.set()
        await self.host.close(timeout=3)
        tasks = [row['close_task'] for row in self.host.obligations() if row['close_task']]
        tasks.extend(task for row in self.host.obligations() for op in row['operations']
                     for task in (op['task'], op['runner']) if task is not None)
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        if self.runtime._pending:
            await asyncio.wait_for(asyncio.gather(*tuple(self.runtime._pending)), 5)
        await self.client.close()
        if self.context is not None:
            self.context.__exit__(None, None, None)
            self.context = None

    def create(self, task, identity, *, link=None):
        state = initial_state(self.spec.prompt, 'session')
        state.update(deadline_monotonic=self.deadline, deadline_clock=CLOCK_ID,
                     native_history=self.native('session'))
        metadata = {**self.spec.metadata(), 'pre_effect_validator': self.spec.validator_identity(),
                    NAMESPACE: identity.metadata()}
        if link is not None:
            metadata[LINK] = link
        return self.store.create(task, self.spec.prompt, max_attempts=8, metadata=metadata, state=state)

    def claim(self, task):
        if self.context is not None:
            self.context.__exit__(None, None, None)
        self.context = self.store.claim(task, expected_revision=self.store.load(task).revision)
        self.owned = self.context.__enter__()

    def append(self, row):
        with closing(sqlite3.connect(self.native_path)) as db, db:
            db.execute('INSERT INTO messages(body) VALUES (?)', (json.dumps(row),))

    def native(self, session):
        # Fixture projection, not a live Hermes SDK connection. The connection
        # is created/read/closed on the same offload thread as in production.
        if session != 'session':
            raise ValueError('Unknown fixture session')
        with closing(sqlite3.connect(self.native_path.as_uri() + '?mode=ro', uri=True)) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM messages ORDER BY id')]

    def current(self, worker):
        self.assertIs(worker, self.worker)
        return self.live

    def was_joined(self, worker):
        self.assertIs(worker, self.worker)
        return self.joined

    async def bind(self, **changes):
        return await self.host.bind(**{**dict(runtime=self.runtime, worker=self.worker,
            is_current_worker=self.current, is_worker_joined=self.was_joined,
            read_native_history=lambda session: self.reader(session), task_root=self.root,
            capability=self.capability, task_deadline=self.deadline), **changes})

    def intent_operation(self, *, source='int main() { broken; }'):
        cp = self.owned.checkpoint
        args = {'recipe_id': 'cpp17-stdout.v1', 'source': source}
        call = 'native-call-1'
        self.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': call, 'type': 'function', 'function': {
                'name': 'build_and_test', 'arguments': json.dumps(args)}}]})
        details = {'name': 'build_and_test', 'args': args, 'tool_call_id': call,
                   'session_id': 'session', 'fingerprint': digest({'name': 'build_and_test', 'args': args}),
                   'host_epoch': 'host-1', 'task_id': 'task', 'execution_id': cp.task_id,
                   'owner_epoch': cp.owner_epoch, 'spec_sha256': self.spec.sha256}
        state = deepcopy(cp.state)
        state.update(phase='tool_running', native_history=self.native('session'))
        cp = self.owned.begin_operation('effect', details=details, state=state, expected_revision=cp.revision)
        self.request = {'schema': 'compiler-operation.v1', 'host_epoch': 'host-1', 'task_id': 'task',
            'execution_id': cp.task_id, 'owner_epoch': cp.owner_epoch, 'operation_id': cp.operation['id'],
            'tool_call_id': call, 'recipe_id': args['recipe_id']}
        return args

    def receipt(self, recipe, status, *, exited=True):
        recipe.run.mkdir(exist_ok=True)
        receipt = {'schema': 'compiler-recipe.v1', 'status': status, 'passed': False,
            'task_deadline': self.deadline, 'deadline': self.deadline,
            'owned_processes_exited': exited, 'children': [], 'stages': []}
        (recipe.run / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        return receipt

    async def runner(self, controller, recipe, *, task_deadline):
        self.runs.append(task_deadline)
        self.recipes.append(recipe)
        self.started.set()
        if self.mode == 'unknown':
            error = RecipeCleanupError('inert unknown fixture')
            error.owner, error.receipt = self.worker, self.receipt(recipe, 'cleanup_unconfirmed', exited=False)
            raise error
        try:
            if self.mode == 'held':
                await self.release.wait()
        except asyncio.CancelledError:
            self.receipt(recipe, 'cancelled')
            raise
        return self.receipt(recipe, 'failed')

    async def post(self, request=None):
        async with self.client.post(ROUTE, json=request or self.request,
                headers={HEADER: self.capability}) as response:
            return response.status, await response.json()

    async def terminal(self):
        async with asyncio.timeout(3):
            while True:
                code, value = await self.post()
                if value.get('state') != 'pending':
                    return code, value
                await asyncio.sleep(.001)

    async def test_unbound_route_has_no_deadline_recipe_or_dispatch_authority(self):
        self.request = {'untrusted': 'arbitrary'}
        code, reply = await self.post()
        self.assertEqual((code, reply['error']), (409, 'compiler_unbound'))
        self.assertFalse(self.host.lifecycle()['bound'])
        self.assertFalse((self.root / 'compiler').exists())
        self.assertEqual(self.runs, [])
        with self.assertRaises(ValueError):
            await self.bind(task_deadline=self.deadline + 1)
        self.assertFalse(self.host.lifecycle()['bound'])

    async def test_exact_durable_source_prepared_once_and_result_poll_is_unchanged(self):
        binding = await self.bind()
        args = self.intent_operation()
        status, done = await self.terminal()
        self.assertEqual((status, done['state'], done['result']['status']), (200, 'completed', 'failed'))
        self.assertEqual(await self.post(), (status, done))
        self.assertEqual(self.runs, [self.deadline])
        self.assertEqual((self.recipes[0].source / 'program.cpp').read_text(), args['source'])
        self.assertEqual(self.recipes[0].source.parent.parent, self.root / 'compiler')
        self.assertEqual(binding['task_deadline'], self.deadline)
        self.assertNotIn(self.capability, repr(self.host) + repr(self.host.obligations()) + repr(binding))

    async def test_paused_owner_can_bind_but_durable_pause_prevents_dispatch(self):
        self.box.submit(self.cap, 'pause-first', 'pause')
        self.box.consume(self.owned, updated_at_utc=NOW)
        await self.bind()
        self.intent_operation()
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'binding_refused')
        self.assertEqual(self.runs, [])
        self.assertFalse((self.root / 'compiler').exists())

    async def test_foreign_request_identity_and_worker_loss_are_refused(self):
        await self.bind()
        self.intent_operation()
        for key in ('host_epoch', 'task_id', 'execution_id', 'owner_epoch', 'operation_id', 'tool_call_id', 'recipe_id'):
            with self.subTest(key=key):
                altered = {**self.request, key: 'other'}
                self.assertFalse(await self.host._validate(self.host._binding, altered))
        self.live = False
        self.assertFalse(await self.host._validate(self.host._binding, self.request))
        self.assertEqual(self.runs, [])

    async def test_native_intent_changed_after_durable_operation_is_refused(self):
        await self.bind()
        self.intent_operation()
        self.append({'role': 'tool', 'tool_call_id': self.request['tool_call_id'], 'content': 'unexpected'})
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'binding_refused')
        self.assertFalse((self.root / 'compiler').exists())

    async def test_control_change_between_native_and_mailbox_reads_refuses_dispatch(self):
        await self.bind()
        self.intent_operation()
        called = []
        def changed(session):
            if not called:
                called.append(True)
                self.box.submit(self.cap, 'pause-during-read', 'pause')
            return self.native(session)
        self.reader = changed
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'binding_refused')
        self.assertEqual(self.runs, [])

    def block_read(self):
        self.read_release.clear()
        def blocked(session):
            self.read_entered.set()
            if not self.read_release.wait(3):
                raise RuntimeError('Fixture read did not release')
            return self.native(session)
        self.reader = blocked

    async def test_deadline_expiry_during_retained_read_does_not_refund_time(self):
        await self.bind()
        self.intent_operation()
        self.block_read()
        request = asyncio.create_task(self.post())
        self.assertTrue(await asyncio.to_thread(self.read_entered.wait, 2))
        self.now = self.deadline
        self.read_release.set()
        await request
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'binding_refused')
        self.assertEqual(reply['result']['task_deadline'], self.deadline)
        self.assertEqual(self.runs, [])

    async def test_stop_during_retained_read_joins_read_without_preparing(self):
        await self.bind()
        self.intent_operation()
        self.block_read()
        request = asyncio.create_task(self.post())
        self.assertTrue(await asyncio.to_thread(self.read_entered.wait, 2))
        self.host.interrupt()
        self.assertTrue(self.runtime._pending)
        self.assertIsNotNone(self.host.obligations()[0]['close_task'])
        self.read_release.set()
        await request
        _, reply = await self.terminal()
        self.assertEqual(reply['state'], 'completed')
        self.assertTrue(reply['result']['owned_processes_exited'])
        self.assertEqual(self.runs, [])
        self.assertFalse((self.root / 'compiler').exists())
        self.assertTrue((await self.host.close())['bridge']['closed'])

    async def test_stop_returns_joined_cancellation_to_polling_worker_before_retire(self):
        await self.bind()
        self.intent_operation()
        self.mode = 'held'
        request = asyncio.create_task(self.post())
        await asyncio.wait_for(self.started.wait(), 2)
        self.host.interrupt()
        self.assertIsNotNone(self.host.obligations()[0]['close_task'])
        await request
        _, reply = await self.terminal()
        self.assertEqual((reply['state'], reply['result']['status']), ('completed', 'cancelled'))
        self.assertTrue(reply['result']['owned_processes_exited'])
        self.assertEqual(reply['result']['task_deadline'], self.deadline)
        with self.assertRaises(ValueError):
            await self.host.retire()
        self.live, self.joined = False, True
        self.assertFalse((await self.host.retire())['bound'])
        self.assertEqual(self.host.obligations(), ())

    async def test_unknown_cleanup_retains_original_owner_and_blocks_retire(self):
        await self.bind()
        self.intent_operation()
        self.mode = 'unknown'
        _, reply = await self.terminal()
        self.assertEqual(reply['state'], 'unknown')
        self.live, self.joined = False, True
        with self.assertRaises(ValueError):
            await self.host.retire()
        self.assertIs(self.host.obligations()[0]['operations'][0]['owner'], self.worker)

    async def test_explicit_retire_then_new_owner_binding_no_implicit_replacement(self):
        first = await self.bind()
        with self.assertRaises(ValueError):
            await self.bind()
        self.live, self.joined = False, True
        await self.host.retire()
        self.claim('task')
        self.worker, self.live, self.joined = object(), True, False
        second = await self.bind(capability='d' * 64)
        self.assertNotEqual(first['owner_epoch'], second['owner_epoch'])
        self.assertEqual(first['task_deadline'], second['task_deadline'])

    async def test_selected_successor_keeps_logical_task_and_execution_distinct(self):
        successor = DemandIdentity('continued', 'execution-2', 'host-1', NOW)
        self.create('execution-2', successor, link={'logical_task_id': 'task', 'execution_id': 'execution-2',
            'execution_generation': 1, 'command_id': 'continue-1', 'payload_sha256': 'f' * 64})
        self.claim('execution-2')
        registry = DemandRegistry((Registration(self.store, successor),))
        self.box = Mailbox(registry, 'continued', requester_capability=self.cap)
        registry.transition('continued', self.owned, 'active',
            expected_revision=self.owned.checkpoint.revision, updated_at_utc=NOW)
        # Trusted host selection fixture; it does not purport to test a real Continue grant.
        self.runtime.mailbox = self.box
        self.runtime._selection = {'execution_id': 'execution-2', 'execution_generation': 1}
        binding = await self.bind()
        self.intent_operation()
        self.assertEqual((binding['task_id'], binding['execution_id']), ('task', 'execution-2'))
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'failed')
        self.assertEqual(self.runs, [self.deadline])

    async def test_worker_change_during_preparation_prevents_runner_entry(self):
        await self.bind()
        self.intent_operation()
        def changed(*args, **kwargs):
            recipe = prepare_cpp_recipe(*args, **kwargs)
            self.live = False
            return recipe
        with mock.patch('adaptive_inference.desktop.compiler_host.prepare_cpp_recipe', side_effect=changed):
            _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'preparation_failed')
        self.assertEqual(self.runs, [])
        self.assertTrue((self.root / 'compiler' / self.request['operation_id'] / 'source' / 'program.cpp').exists())

    async def test_transition_can_bind_observed_owner_before_dispatch_becomes_available(self):
        self.runtime._transitioning = True
        binding = await self.bind()
        self.intent_operation()
        self.assertFalse(await self.host._validate(self.host._binding, self.request))
        self.assertEqual(self.runs, [])
        self.assertFalse((self.root / 'compiler').exists())
        self.assertEqual(binding['task_deadline'], self.deadline)
        # The trusted lifecycle finishes its real transition before releasing
        # worker readiness. No refused HTTP operation is automatically retried.
        self.runtime._transitioning = False
        _, reply = await self.terminal()
        self.assertEqual(reply['result']['status'], 'failed')
        self.assertEqual(self.runs, [self.deadline])
