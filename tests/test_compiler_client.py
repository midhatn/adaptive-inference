"""Bounded compiler-client behavior; real loopback bridge, no compiler/model."""
import asyncio
from copy import deepcopy
from email.message import Message
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from aiohttp import web
from aiohttp.test_utils import TestServer
from adaptive_inference.desktop.compiler_bridge import CompilerBridge, HEADER, ROUTE, RESPONSE_LIMIT
from adaptive_inference.desktop.compiler_recipe import CompilerRecipe, Executable
from adaptive_inference.desktop.hermes.compiler_client import CompilerClient, CompilerClientError
from adaptive_inference.handoff import ToolRequirements


CAPABILITY = 'c' * 64
ENVELOPE = {'schema': 'compiler-operation.v1', 'host_epoch': 'host-1',
            'task_id': 'task-1', 'execution_id': 'task-1', 'owner_epoch': 'd' * 32,
            'operation_id': 'e' * 32, 'tool_call_id': 'call-compiler-1', 'recipe_id': 'cpp17-stdout.v1'}


def result(status='failed', deadline=100.):
    value = {'schema': 'compiler-operation-result.v1', 'operation_id': ENVELOPE['operation_id'],
        'recipe_id': ENVELOPE['recipe_id'], 'recipe_sha256': 'a' * 64, 'status': status,
        'passed': status == 'passed', 'dispatched': True, 'owned_processes_exited': True,
        'task_deadline': deadline, 'receipt_sha256': 'b' * 64,
        'stages': [{'stage': 'configure', 'exit_code': 0}, {'stage': 'build', 'exit_code': 1}]}
    if status == 'passed':
        value.update(artifact_sha256='f' * 64, artifact_bytes=12,
                     test_report_sha256='1' * 64, tests_passed=['task_stdout'])
        value['stages'] = [{'stage': name, 'exit_code': 0} for name in ('configure', 'build', 'test')]
    else:
        value['diagnostics'] = [{'stage': 'build', 'text': 'program.cpp: missing semicolon', 'truncated': False}]
    return value


def reply(value=None, state='completed'):
    return {'ok': True, 'operation_id': ENVELOPE['operation_id'], 'state': state, 'result': value}


class Clock:
    def __init__(self, now=10.):
        self.now, self.sleeps = now, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response:
    def __init__(self, value, *, raw=None, size=None, status=200, url=None):
        self.raw = json.dumps(value).encode() if raw is None else raw
        self.status, self.url, self.closed, self.read_sizes = status, url, False, []
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'
        self.headers['Content-Length'] = str(len(self.raw) if size is None else size)

    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def geturl(self): return self.url
    def read(self, size):
        self.read_sizes.append(size)
        return self.raw[:size]


class Opener:
    def __init__(self, values, *, before=None):
        self.values, self.before, self.calls = list(values), before, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.before:
            self.before(request)
        value = self.values.pop(0)
        if isinstance(value, BaseException): raise value
        if value.url is None: value.url = request.full_url
        return value


class CompilerClientTests(unittest.TestCase):
    def client(self, values, *, clock=None, **kwargs):
        clock = clock or Clock()
        opener = Opener(values)
        client = CompilerClient(18100, CAPABILITY, 100., clock=clock, sleep=clock.sleep,
                                opener=opener, **kwargs)
        return client, opener, clock

    def test_pending_uses_identical_bounded_identity_then_returns_unmodified_failure(self):
        expected = result()
        responses = [Response(reply(state='pending')), Response(reply(state='pending')), Response(reply(expected))]
        client, opener, clock = self.client(responses)
        envelope = deepcopy(ENVELOPE)
        opener.before = lambda _: envelope.update(source='must not enter a later poll')
        self.assertEqual(client(envelope), expected)
        self.assertEqual(len(opener.calls), 3)
        bodies = [request.data for request, _ in opener.calls]
        self.assertEqual(bodies, [bodies[0]] * 3)
        self.assertEqual(json.loads(bodies[0]), ENVELOPE)
        self.assertEqual(clock.sleeps, [.1, .1])
        for request, timeout in opener.calls:
            self.assertEqual(request.full_url, 'http://127.0.0.1:18100' + ROUTE)
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.get_header(HEADER.capitalize()), CAPABILITY)
            self.assertEqual(timeout, 2.)
        self.assertTrue(all(response.closed for response in responses))

    def test_known_pass_cancel_and_predispatch_outcomes_remain_distinct(self):
        for status in ('passed', 'cancelled', 'interrupted', 'timed_out'):
            with self.subTest(status=status):
                expected = result(status)
                client, _, _ = self.client([Response(reply(expected))])
                self.assertEqual(client(ENVELOPE), expected)
        expected = {key: value for key, value in result().items()
                    if key not in ('stages', 'diagnostics', 'receipt_sha256')}
        expected.update(status='cancelled_before_dispatch', dispatched=False, recipe_sha256=None)
        client, _, _ = self.client([Response(reply(expected))])
        self.assertEqual(client(ENVELOPE), expected)

    def test_transport_uncertainty_never_retries_or_allows_a_new_operation(self):
        for error in (TimeoutError(CAPABILITY), urllib.error.URLError(TimeoutError(CAPABILITY)),
                      urllib.error.URLError(ConnectionRefusedError(CAPABILITY))):
            with self.subTest(error=type(error).__name__):
                client, opener, _ = self.client([error, Response(reply(result()))])
                with self.assertRaises(CompilerClientError) as caught:
                    client(ENVELOPE)
                self.assertNotIn(CAPABILITY, str(caught.exception))
                self.assertEqual(len(opener.calls), 1)
                with self.assertRaisesRegex(CompilerClientError, 'requires_reconciliation'):
                    client({**ENVELOPE, 'operation_id': 'new-operation'})
                self.assertEqual(len(opener.calls), 1)

    def test_http_error_is_closed_redacted_and_not_a_nodispatch_result(self):
        stream = io.BytesIO(CAPABILITY.encode())
        error = urllib.error.HTTPError('http://example.invalid/' + CAPABILITY, 409, CAPABILITY, {}, stream)
        client, opener, _ = self.client([error])
        with self.assertRaisesRegex(CompilerClientError, '^http_outcome_unconfirmed$') as caught:
            client(ENVELOPE)
        self.assertNotIn(CAPABILITY, repr(caught.exception))
        self.assertTrue(stream.closed)
        self.assertEqual(len(opener.calls), 1)

    def test_original_deadline_bounds_polling_without_renewal(self):
        clock = Clock(99.95)
        client, opener, _ = self.client([Response(reply(state='pending')), Response(reply(result()))], clock=clock)
        with self.assertRaisesRegex(CompilerClientError, 'original_deadline_expired'):
            client(ENVELOPE)
        self.assertEqual(len(opener.calls), 1)
        self.assertAlmostEqual(opener.calls[0][1], .05)
        self.assertAlmostEqual(clock.sleeps[0], .05)
        self.assertEqual(client.task_deadline, 100.)
        client, opener, _ = self.client([], clock=Clock(100.))
        with self.assertRaisesRegex(CompilerClientError, 'original_deadline_expired'):
            client(ENVELOPE)
        self.assertEqual(opener.calls, [])

    def test_late_response_and_clock_rollback_are_not_accepted(self):
        for now, code in ((101., 'original_deadline_expired'), (9., 'invalid_clock')):
            with self.subTest(now=now):
                response = Response(reply(result()))
                client, opener, clock = self.client([response])
                opener.before = lambda _, now=now: setattr(clock, 'now', now)
                with self.assertRaisesRegex(CompilerClientError, code):
                    client(ENVELOPE)
                self.assertTrue(response.closed)

    def test_invalid_request_never_reaches_http(self):
        client, opener, _ = self.client([])
        for change in ({'source': 'int main(){}'}, {'command': 'cmake'}, {'path': 'file'},
                       {'operation_id': '../escape'}, {'owner_epoch': CAPABILITY}, {'recipe_id': 'x' * 4096}):
            with self.subTest(change=list(change)):
                with self.assertRaisesRegex(CompilerClientError, '^invalid_request$'):
                    client({**ENVELOPE, **change})
        self.assertEqual(opener.calls, [])

    def test_unknown_and_mismatched_reply_cannot_settle_an_effect(self):
        cases = [reply(result(), state='unknown'), reply(result(), state='pending'),
                 {**reply(result()), 'operation_id': 'different'}, {**reply(result()), 'ok': 1},
                 {**reply(result()), 'state': []}, {**reply(result()), 'extra': True},
                 reply({**result(), 'operation_id': 'different'}),
                 reply({**result(), 'recipe_id': 'different'}),
                 reply({**result(), 'task_deadline': 101.}),
                 reply({**result(), 'owned_processes_exited': False}),
                 reply({**result(), 'dispatched': None}),
                 reply({**result(), 'status': 'outcome_unknown'}),
                 reply({**result(), 'receipt_sha256': None})]
        for value in cases:
            with self.subTest(value=value.get('state')):
                client, opener, _ = self.client([Response(value)])
                with self.assertRaises(CompilerClientError): client(ENVELOPE)
                self.assertEqual(len(opener.calls), 1)

    def test_http_framing_and_json_bounds_close_every_response(self):
        oversized = Response(None, size=RESPONSE_LIMIT + 1)
        short = Response(None, raw=b'{}', size=3)
        wrong_url = Response(reply(result()), url='http://localhost:18100' + ROUTE)
        encoded = Response(reply(result())); encoded.headers['Content-Encoding'] = 'gzip'
        chunked = Response(reply(result())); chunked.headers['Transfer-Encoding'] = 'chunked'
        duplicate_length = Response(reply(result())); duplicate_length.headers['Content-Length'] = '2'
        wrong_type = Response(reply(result())); wrong_type.headers.replace_header('Content-Type', 'text/plain')
        cases = [oversized, short, wrong_url, encoded, chunked, duplicate_length, wrong_type,
                 Response(None, raw=b'{"ok":true,"ok":true}'), Response(None, raw=b'{"x":NaN}'),
                 Response(None, raw=b'\xff'), Response(reply({**result(), 'secret': CAPABILITY}))]
        for response in cases:
            with self.subTest(response=cases.index(response)):
                client, _, _ = self.client([response])
                with self.assertRaises(CompilerClientError): client(ENVELOPE)
                self.assertTrue(response.closed)
        self.assertEqual(oversized.read_sizes, [])

    def test_configuration_and_repr_do_not_expose_capability(self):
        for port in (True, 0, 65536, 'http://remote', '18100'):
            with self.assertRaisesRegex(CompilerClientError, '^invalid_configuration$'):
                CompilerClient(port, CAPABILITY, 100.)
        for deadline in (True, -1, float('inf'), float('nan')):
            with self.assertRaises(CompilerClientError): CompilerClient(18100, CAPABILITY, deadline)
        client, _, _ = self.client([])
        self.assertNotIn(CAPABILITY, repr(client))
        self.assertIn('[redacted]', repr(client))

    def test_default_opener_explicitly_disables_proxy_and_redirect(self):
        with patch.dict(os.environ, {'http_proxy': 'http://example.invalid:99',
                                     'HTTP_PROXY': 'http://example.invalid:99'}):
            client = CompilerClient(18100, CAPABILITY, 100.)
        self.assertFalse(any(isinstance(handler, urllib.request.ProxyHandler)
                             and handler.proxies for handler in client._opener.handlers))
        redirects = [handler for handler in client._opener.handlers
                     if isinstance(handler, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(None, None, 307, None, None, 'http://example.invalid'))


class CompilerClientLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_bridge_pending_polls_observe_host_stop_as_joined_cancellation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'; source.mkdir()
            (source / 'CMakeLists.txt').write_text('inert fixture', encoding='utf-8')
            tool = Executable(Path(sys.executable).resolve(), 'a' * 64)
            recipe = CompilerRecipe(tool, tool, tool, tool, source,
                (('CMakeLists.txt', hashlib.sha256((source / 'CMakeLists.txt').read_bytes()).hexdigest()),),
                root / 'run', 'answer.exe', ('task_stdout',), 1, ToolRequirements(1, 1, 0),
                256, 30, ())
            deadline = time.perf_counter() + 5
            started, allow_cleanup = asyncio.Event(), asyncio.Event()
            prepared, runs, requests = [], [], []

            async def validate(value): return value == ENVELOPE
            async def prepare(value): prepared.append(value); return recipe
            async def runner(controller, selected, *, task_deadline):
                runs.append(selected); started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await allow_cleanup.wait()
                    selected.run.mkdir()
                    receipt = {'schema': 'compiler-recipe.v1', 'task_deadline': task_deadline,
                        'deadline': task_deadline, 'status': 'cancelled', 'passed': False,
                        'owned_processes_exited': True, 'children': [], 'stages': []}
                    (selected.run / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
                    raise

            bridge = CompilerBridge(object(), {ENVELOPE['recipe_id']: prepare}, capability=CAPABILITY,
                task_deadline=deadline, validate_binding=validate, runner=runner, reply_timeout=.01)
            app = web.Application()
            bridge.add_route(app)
            server = TestServer(app)
            await server.start_server()
            client = CompilerClient(server.port, CAPABILITY, deadline, poll_interval=.01)
            native_opener = client._opener
            class RecordingOpener:
                def open(self, request, timeout):
                    requests.append(request.data)
                    return native_opener.open(request, timeout=timeout)
            client._opener = RecordingOpener()
            work = asyncio.create_task(asyncio.to_thread(client, deepcopy(ENVELOPE)))
            try:
                await asyncio.wait_for(started.wait(), 2)
                async with asyncio.timeout(2):
                    while len(requests) < 2: await asyncio.sleep(.01)
                bridge.interrupt()
                allow_cleanup.set()
                terminal = await asyncio.wait_for(asyncio.shield(work), 2)
                self.assertEqual(terminal['status'], 'cancelled')
                self.assertTrue(terminal['owned_processes_exited'])
                self.assertEqual(terminal['task_deadline'], deadline)
                self.assertEqual(len(prepared), 1)
                self.assertEqual(len(runs), 1)
                self.assertGreaterEqual(len(requests), 2)
                self.assertEqual(requests, [requests[0]] * len(requests))
                self.assertEqual(json.loads(requests[0]), ENVELOPE)
            finally:
                allow_cleanup.set()
                await bridge.close(timeout=2)
                await server.close()
                await asyncio.gather(work, return_exceptions=True)
                self.assertTrue(all(row['task'].done() and (row['runner'] is None or row['runner'].done())
                                    for row in bridge.obligations()))
