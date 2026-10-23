"""Bounded deadline and complete-output regressions; local fake HTTP only."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adaptive_inference.config import Config
from adaptive_inference.gateway import GATEWAY, StreamCompletion, complete_json, create_app, expected_choice_count
from adaptive_inference.scheduler import AdmissionError, Scheduler


class StreamChecks(unittest.TestCase):
    def test_expected_choice_count_requires_every_requested_index(self):
        stream = StreamCompletion(2)
        stream.feed(b'data: {"choices":[{"index":0,"finish_reason":"stop"}]}\n\n'
                    b'data: [DONE]\n\n')
        self.assertFalse(stream.complete)

    def test_expected_choices_accept_separate_completion_events(self):
        stream = StreamCompletion(2)
        stream.feed(b'data: {"choices":[{"index":0,"finish_reason":"stop"}]}\n\n')
        stream.feed(b'data: {"choices":[{"index":1,"finish_reason":"length"}]}\n\n'
                    b'data: [DONE]\n\n')
        self.assertTrue(stream.complete)

    def test_nonstream_requires_expected_unique_complete_choices(self):
        for choices, expected in (([{"index": 0, "finish_reason": "stop"}], False),
                                  ([{"index": 0, "finish_reason": "stop"},
                                    {"index": 0, "finish_reason": "stop"}], False),
                                  ([{"index": 0, "finish_reason": "stop"},
                                    {"index": 1, "finish_reason": None}], False),
                                  ([{"index": 0, "finish_reason": "stop"},
                                    {"index": 1, "finish_reason": "length"}], True)):
            with self.subTest(choices=choices):
                self.assertEqual(complete_json(json.dumps({"choices": choices}).encode(),
                                               '/chat/completions', 2), expected)

    def test_choice_bookkeeping_handles_batch_and_disables_unbounded_learning(self):
        cases = [({'n': 2}, '/chat/completions', 2),
                 ({'n': 2, 'prompt': ['one', 'two']}, '/completions', 4),
                 ({'n': 2, 'prompt': [1, 2]}, '/completions', 2),
                 ({'n': True}, '/chat/completions', 0),
                 ({'n': 1025}, '/chat/completions', 0)]
        for body, endpoint, expected in cases:
            with self.subTest(body=body, endpoint=endpoint):
                before = json.dumps(body)
                self.assertEqual(expected_choice_count(body, endpoint), expected)
                self.assertEqual(json.dumps(body), before)

    def test_one_finished_choice_does_not_complete_another_seen_choice(self):
        stream = StreamCompletion()
        stream.feed(b'data: {"choices":[{"index":0,"finish_reason":"stop"},'
                    b'{"index":1,"delta":{"content":"unfinished"},"finish_reason":null}]}\n\n')
        stream.feed(b'data: [DONE]\n\n')
        self.assertFalse(stream.complete)

    def test_all_seen_choices_can_finish_across_separate_events(self):
        stream = StreamCompletion()
        stream.feed(b'data: {"choices":[{"index":0,"finish_reason":"stop"},'
                    b'{"index":1,"finish_reason":null}]}\n\n')
        stream.feed(b'data: {"choices":[{"index":1,"finish_reason":"length"}]}\n\n')
        stream.feed(b'data: [DONE]\n\n')
        self.assertTrue(stream.complete)


class DeadlineChecks(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_woken_after_deadline_cannot_dispatch_into_newly_free_slot(self):
        clock = [100.0]
        scheduler = Scheduler(Config(queue_timeout_s=1), lambda: True)
        # Replace the scheduler's clock object, not asyncio's monotonic clock.
        with patch('adaptive_inference.scheduler.time', SimpleNamespace(monotonic=lambda: clock[0])):
            owner = await scheduler.acquire('normal', None)
            follower = asyncio.create_task(scheduler.acquire('normal', None))
            await asyncio.sleep(0)
            self.assertEqual(len(scheduler.pending), 1)
            clock[0] = 101.1
            await scheduler.release(owner)
            try:
                with self.assertRaises(AdmissionError) as raised:
                    await follower
                self.assertEqual(raised.exception.code, 'queue_timeout')
                self.assertIsNone(scheduler.active)
                self.assertFalse(scheduler.pending)
            finally:
                if scheduler.active is not None:
                    await scheduler.release(scheduler.active)


class CompleteRequestChecks(unittest.IsolatedAsyncioTestCase):
    async def test_nonstream_missing_choice_is_forwarded_without_training(self):
        raw = b'{"choices":[{"index":0,"message":{"content":"one"},"finish_reason":"stop"}]}'

        async def reply(request):
            self.assertEqual((await request.json())['n'], 2)
            return web.Response(body=raw, content_type='application/json')

        backend_app = web.Application()
        backend_app.router.add_post('/v1/chat/completions', reply)
        backend = TestServer(backend_app)
        await backend.start_server()
        app = create_app(Config(backend_url=str(backend.make_url('/v1')), upstream_timeout_s=2))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post('/v1/chat/completions', json={
                'model': 'fixture', 'messages': [{'role': 'user', 'content': 'hello'}], 'n': 2})
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), raw)
            self.assertFalse(app[GATEWAY].history[-1]['trained'])
            self.assertFalse(app[GATEWAY].scheduler.status()['active'])
        finally:
            await client.close()
            await backend.close()

    async def test_models_reads_delayed_chunks_to_eof_under_cap(self):
        raw = b'{"data":[' + b' ' * 1024 + b'{"id":"fixture"}]}'

        async def reply(request):
            response = web.StreamResponse(headers={'Content-Type': 'application/json'})
            await response.prepare(request)
            await response.write(raw[:10])
            await asyncio.sleep(.02)
            await response.write(raw[10:])
            await response.write_eof()
            return response

        backend_app = web.Application()
        backend_app.router.add_get('/v1/models', reply)
        backend = TestServer(backend_app)
        await backend.start_server()
        client = TestClient(TestServer(create_app(Config(
            backend_url=str(backend.make_url('/v1')), max_response_bytes=2048, upstream_timeout_s=2))))
        await client.start_server()
        try:
            response = await client.get('/v1/models')
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), raw)
        finally:
            await client.close()
            await backend.close()

    async def test_models_rejects_accumulated_chunks_over_cap(self):
        async def reply(request):
            response = web.StreamResponse(headers={'Content-Type': 'application/json'})
            await response.prepare(request)
            await response.write(b' ' * 800)
            await asyncio.sleep(.02)
            await response.write(b' ' * 800)
            await response.write_eof()
            return response

        backend_app = web.Application()
        backend_app.router.add_get('/v1/models', reply)
        backend = TestServer(backend_app)
        await backend.start_server()
        client = TestClient(TestServer(create_app(Config(
            backend_url=str(backend.make_url('/v1')), max_response_bytes=1024, upstream_timeout_s=2))))
        await client.start_server()
        try:
            response = await client.get('/v1/models')
            self.assertEqual(response.status, 502)
            self.assertEqual((await response.json())['error']['code'], 'response_too_large')
        finally:
            await client.close()
            await backend.close()

    async def test_requested_choice_missing_from_sse_does_not_train(self):
        raw = (b'data: {"choices":[{"index":0,"delta":{"content":"one"},"finish_reason":"stop"}]}\n\n'
               b'data: [DONE]\n\n')

        async def reply(request):
            self.assertEqual((await request.json())['n'], 2)
            return web.Response(body=raw, headers={'Content-Type': 'text/event-stream'})

        backend_app = web.Application()
        backend_app.router.add_post('/v1/chat/completions', reply)
        backend = TestServer(backend_app)
        await backend.start_server()
        app = create_app(Config(backend_url=str(backend.make_url('/v1')), upstream_timeout_s=2))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post('/v1/chat/completions', json={
                'model': 'fixture', 'messages': [{'role': 'user', 'content': 'hello'}], 'n': 2, 'stream': True})
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), raw)
            await asyncio.sleep(0)
            self.assertEqual(len(app[GATEWAY].history), 1)
            self.assertFalse(app[GATEWAY].history[-1]['trained'])
            self.assertFalse(app[GATEWAY].scheduler.status()['active'])
        finally:
            await client.close()
            await backend.close()


if __name__ == '__main__': unittest.main()
