"""Actual loopback HTTP and inert retained runners; no compiler/model execution."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from adaptive_inference.desktop.compiler_bridge import CompilerBridge, HEADER, ROUTE
from adaptive_inference.desktop.compiler_recipe import CompilerRecipe, Executable, RecipeCleanupError
from adaptive_inference.handoff import ToolRequirements


class CompilerBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capability = 'c' * 64
        self.deadline = time.perf_counter() + 900
        self.request = {'schema': 'compiler-operation.v1', 'host_epoch': 'host-1',
            'task_id': 'task-1', 'execution_id': 'task-1', 'owner_epoch': 'd' * 32,
            'operation_id': 'e' * 32, 'tool_call_id': 'call-compiler-1', 'recipe_id': 'cpp-test'}
        self.preparations, self.runs, self.validations = [], [], []
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.allow = True
        self.mode = 'passed'
        self.cleanup_owner = object()

        async def validate(request):
            self.validations.append(deepcopy(request))
            return self.allow and request['task_id'] == 'task-1' and request['owner_epoch'] == 'd' * 32

        async def prepare(request):
            self.preparations.append(deepcopy(request))
            source = self.root / ('source-' + request['operation_id'])
            source.mkdir()
            (source / 'CMakeLists.txt').write_text('component-only preparation', encoding='utf-8')
            pin = Executable(Path(sys.executable).resolve(), 'a' * 64)
            return CompilerRecipe(pin, pin, pin, pin, source,
                (('CMakeLists.txt', hashlib.sha256((source / 'CMakeLists.txt').read_bytes()).hexdigest()),),
                self.root / ('run-' + request['operation_id']), 'answer.exe', ('answer',), 1,
                ToolRequirements(1, 1, 0), 256, 30, (('TEST_SECRET', 'SENSITIVE_VALUE_123'),))

        async def runner(controller, recipe, *, task_deadline):
            self.runs.append((recipe, task_deadline))
            self.started.set()
            if self.mode == 'held':
                await self.release.wait()
            if self.mode == 'unknown':
                receipt = self.receipt(recipe, 'cleanup_unconfirmed', exited=False)
                error = RecipeCleanupError('private cleanup detail')
                error.owner, error.receipt = self.cleanup_owner, receipt
                raise error
            return self.receipt(recipe, self.mode if self.mode in ('failed', 'passed') else 'passed')

        self.bridge = CompilerBridge(object(), {'cpp-test': prepare}, capability=self.capability,
            task_deadline=self.deadline, validate_binding=validate, runner=runner, reply_timeout=.02)
        app = web.Application()
        self.bridge.add_route(app)
        self.client = TestClient(TestServer(app, handler_cancellation=True))
        await self.client.start_server()
        self.addAsyncCleanup(self.cleanup_bridge)

    async def cleanup_bridge(self):
        self.release.set()
        state = await self.bridge.close(timeout=2)
        await self.client.close()
        self.assertEqual(state['pending'], 0)

    def receipt(self, recipe, status, *, exited=True):
        recipe.run.mkdir(exist_ok=True)
        receipt = {'schema': 'compiler-recipe.v1', 'status': status, 'passed': status == 'passed',
            'task_deadline': self.deadline, 'deadline': min(self.deadline, time.perf_counter() + 30),
            'owned_processes_exited': exited,
            'children': [{'joined': exited, 'exit_code': 1 if status == 'failed' else 0,
                          'command_delivered': True}],
            'stages': [{'stage': 'configure', 'exit_code': 0}, {'stage': 'build', 'exit_code': 1 if status == 'failed' else 0}]}
        if status == 'passed':
            receipt.update(artifact_sha256='a' * 64, artifact_bytes=10,
                           test_report_sha256='b' * 64, tests_passed=['answer'])
        if status == 'failed':
            (recipe.run / 'build.log').write_text('prefix' * 1000 + '\n'
                + 'main.cpp:4: error: expected semicolon\n'
                + 'secret=SENSITIVE_VALUE_123\ncapability=' + self.capability + '\n'
                + 'source=' + str(recipe.source) + '\n', encoding='utf-8')
        (recipe.run / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        return receipt

    async def post(self, request=None, **kwargs):
        response = await self.client.post(ROUTE, json=request or self.request,
            headers=kwargs.pop('headers', {HEADER: self.capability}), **kwargs)
        async with response:
            return response.status, await response.json()

    async def terminal(self, request=None):
        async with asyncio.timeout(2):
            while True:
                status, value = await self.post(request)
                if value.get('state') != 'pending':
                    return status, value
                await asyncio.sleep(.001)

    async def test_authentication_and_strict_recipe_request_do_not_reach_factory(self):
        for headers in ({}, {HEADER: 'd' * 64}, {HEADER: self.capability, 'Origin': 'http://example.com'}):
            status, _ = await self.post(headers=headers)
            self.assertEqual(status, 403)
        status, _ = await self.post({**self.request, 'command': 'arbitrary'})
        self.assertEqual(status, 400)
        raw = json.dumps(self.request)[:-1] + ',"recipe_id":"cpp-test"}'
        async with self.client.post(ROUTE, data=raw, headers={HEADER: self.capability}) as response:
            self.assertEqual(response.status, 400)
        async with self.client.post(ROUTE, data=b'x' * 4097, headers={HEADER: self.capability}) as response:
            self.assertEqual(response.status, 400)
        status, _ = await self.post({**self.request, 'recipe_id': 'other'})
        self.assertEqual(status, 400)
        self.assertEqual((self.preparations, self.runs, self.validations), ([], [], []))

    async def test_binding_refusal_precedes_preparation_and_dispatch(self):
        self.allow = False
        status, response = await self.terminal()
        self.assertEqual(status, 200)
        self.assertEqual(response['result']['status'], 'binding_refused')
        self.assertFalse(response['result']['dispatched'])
        self.assertEqual((self.preparations, self.runs), ([], []))

    async def test_duplicate_operation_reuses_one_preparation_runner_and_result(self):
        self.mode = 'held'
        first = asyncio.create_task(self.post())
        await asyncio.wait_for(self.started.wait(), 1)
        status, duplicate = await self.post()
        self.assertEqual((status, duplicate['state']), (200, 'pending'))
        status, conflict = await self.post({**self.request, 'tool_call_id': 'different'})
        self.assertEqual((status, conflict['error']), (409, 'conflicting_operation'))
        status, _ = await self.post({**self.request, 'operation_id': 'f' * 32})
        self.assertEqual(status, 409)
        await first
        self.release.set()
        _, completed = await self.terminal()
        _, repeated = await self.terminal()
        self.assertEqual(completed, repeated)
        self.assertTrue(completed['result']['passed'])
        self.assertEqual(len(self.preparations), 1)
        self.assertEqual(len(self.runs), 1)
        self.assertEqual(self.runs[0][1], self.deadline)

    async def test_actual_http_disconnect_does_not_cancel_owned_runner(self):
        self.mode = 'held'
        url = self.client.make_url(ROUTE)
        reader, writer = await asyncio.open_connection(url.host, url.port)
        payload = json.dumps(self.request).encode()
        writer.write((f'POST {ROUTE} HTTP/1.1\r\nHost: {url.host}\r\n'
            f'{HEADER}: {self.capability}\r\nContent-Length: {len(payload)}\r\n'
            'Content-Type: application/json\r\n\r\n').encode() + payload)
        await writer.drain()
        await asyncio.wait_for(self.started.wait(), 1)
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.bridge.lifecycle()['pending'], 1)
        self.release.set()
        _, result = await self.terminal()
        self.assertTrue(result['result']['passed'])
        self.assertEqual(len(self.runs), 1)

    async def test_close_retains_cleanup_until_cancelled_runner_receipt_is_joined(self):
        cleanup_started, finish_cleanup = asyncio.Event(), asyncio.Event()
        async def runner(controller, recipe, *, task_deadline):
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await finish_cleanup.wait()
                self.receipt(recipe, 'cancelled')
                raise
        self.bridge.runner = runner
        await self.post()
        await asyncio.wait_for(self.started.wait(), 1)
        state = await self.bridge.close(timeout=.01)
        await asyncio.wait_for(cleanup_started.wait(), 1)
        self.assertFalse(state['closed'])
        self.assertEqual(state['pending'], 1)
        finish_cleanup.set()
        state = await self.bridge.close(timeout=1)
        self.assertTrue(state['closed'])
        _, result = await self.post()
        self.assertEqual(result['result']['status'], 'cancelled')
        self.assertTrue(result['result']['owned_processes_exited'])
        self.assertTrue(all(row['task'].done() and row['runner'].done() for row in self.bridge.obligations()))
        status, _ = await self.post({**self.request, 'operation_id': 'f' * 32})
        self.assertEqual(status, 409)

    async def test_unknown_cleanup_retains_original_owner_and_blocks_new_work(self):
        self.mode = 'unknown'
        _, response = await self.terminal()
        self.assertEqual(response['state'], 'unknown')
        self.assertIsNone(response['result']['dispatched'])
        self.assertFalse(response['result']['owned_processes_exited'])
        obligation = self.bridge.obligations()[0]
        self.assertIs(obligation['owner'], self.cleanup_owner)
        self.assertIsInstance(obligation['error'], RecipeCleanupError)
        self.assertEqual(obligation['receipt']['status'], 'cleanup_unconfirmed')
        _, repeated = await self.post()
        self.assertEqual(repeated, response)
        self.assertEqual(len(self.preparations), 1)
        self.assertEqual(len(self.runs), 1)
        status, _ = await self.post({**self.request, 'operation_id': 'f' * 32})
        self.assertEqual(status, 409)
        self.assertFalse((await self.bridge.close(timeout=1))['closed'])

    async def test_known_failure_feedback_then_distinct_corrected_operation_is_fresh(self):
        self.mode = 'failed'
        _, failed = await self.terminal()
        result = failed['result']
        self.assertEqual((failed['state'], result['status']), ('completed', 'failed'))
        self.assertTrue(result['owned_processes_exited'])
        diagnostic = result['diagnostics'][0]
        self.assertIn('expected semicolon', diagnostic['text'])
        self.assertTrue(diagnostic['truncated'])
        self.assertLessEqual(len(diagnostic['text']), 4096)
        serialized = json.dumps(result)
        for forbidden in (self.capability, 'SENSITIVE_VALUE_123', str(self.root)):
            self.assertNotIn(forbidden, serialized)
        self.mode = 'passed'
        second = {**self.request, 'operation_id': 'f' * 32, 'tool_call_id': 'call-compiler-corrected'}
        _, corrected = await self.terminal(second)
        self.assertTrue(corrected['result']['passed'])
        self.assertNotEqual(result['recipe_sha256'], corrected['result']['recipe_sha256'])
        self.assertEqual(len(self.preparations), 2)
        self.assertEqual(len(self.runs), 2)
        self.assertNotEqual(self.runs[0][0].run, self.runs[1][0].run)
        self.assertEqual([deadline for _, deadline in self.runs], [self.deadline, self.deadline])

    async def test_binding_is_rechecked_after_awaited_preparation(self):
        factory = self.bridge.recipes['cpp-test']
        async def revoked(request):
            recipe = await factory(request)
            self.allow = False
            return recipe
        self.bridge.recipes['cpp-test'] = revoked
        _, response = await self.terminal()
        self.assertEqual(response['result']['status'], 'binding_refused')
        self.assertEqual(len(self.preparations), 1)
        self.assertEqual(self.runs, [])
        self.assertEqual(len(self.validations), 2)

    async def test_returned_receipt_cannot_replace_durable_terminal_evidence(self):
        async def runner(controller, recipe, *, task_deadline):
            result = self.receipt(recipe, 'passed')
            return {**result, 'task_deadline': task_deadline + 900}
        self.bridge.runner = runner
        _, response = await self.terminal()
        self.assertEqual(response['state'], 'unknown')
        self.assertEqual(response['result']['status'], 'outcome_unknown')
        self.assertFalse((await self.bridge.close(timeout=1))['closed'])


if __name__ == '__main__':
    unittest.main()
