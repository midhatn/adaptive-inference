import asyncio
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web

from adaptive_inference.config import Config
from adaptive_inference.costs import RequestCostModel
from adaptive_inference.demo import run_demo, start_app
from adaptive_inference.feedback import Verdict, run_with_feedback
from adaptive_inference.gateway import GATEWAY, StreamCompletion, cost_key, create_app
from adaptive_inference.scheduler import Scheduler, AdmissionError


class CoreTests(unittest.TestCase):
    def test_key_pools_seeds_preserves_quality_and_body(self):
        body = {"model": "test", "messages": [{"role": "user", "content": "private text"}], "max_tokens": 123, "seed": 4}
        original = copy.deepcopy(body)
        key = cost_key(Config(), "/chat/completions", body, "normal")
        self.assertEqual(key, cost_key(Config(), "/chat/completions", {**body, "seed": 71}, "normal"))
        self.assertNotEqual(key, cost_key(Config(), "/chat/completions", {**body, "max_tokens": 9}, "normal"))
        self.assertNotEqual(key, cost_key(Config(), "/chat/completions", body, "background"))
        self.assertEqual(body, original)
        self.assertNotIn("private text", key)

    def test_costs_expiry_failure_and_spike(self):
        costs = RequestCostModel(ttl_s=10)
        for i, value in enumerate((1, 1, 10)):
            costs.observe("key", value, now=i)
        self.assertEqual(costs.predict("key", now=3)["estimate_s"], 10)
        self.assertEqual(costs.predict("key", now=20)["reason"], "expired")
        for i in range(3):
            costs.observe("key", 1, now=21 + i)
        costs.observe("key", .01, now=25, success=False)
        self.assertIsNone(costs.predict("key", now=26)["estimate_s"])

    def test_strict_configuration(self):
        for raw in ({"unknown": True}, {"listen": {"host": "0.0.0.0"}},
                    {"backend": {"base_url": "http://secret:password@localhost/v1"}},
                    {"scheduler": {"max_pending": True}}, {"scheduler": {"normal_boost_s": 11}}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                Config.from_dict(raw)

    def test_sse_split_completion_and_error(self):
        detector = StreamCompletion()
        for piece in (b'data: {"choices":[{"finish_reason":"st', b'op"}]}\r\n\r\ndata: [DO', b'NE]\n\n'):
            detector.feed(piece)
        self.assertTrue(detector.complete)
        detector.feed(b'data: {"error":"failed"}\n\n')
        self.assertFalse(detector.complete)


class AsyncCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_actual_http_and_feedback(self):
        result = await run_demo()
        self.assertTrue(result["passed"])
        self.assertEqual(result["task_correction"]["attempts"], 2)

    async def test_repair_exhaustion_preserves_original(self):
        calls = []
        async def generate(messages):
            calls.append(messages)
            return "still wrong"
        result = await run_with_feedback("original exact task", generate, lambda text: Verdict(False, "failed check"), max_attempts=3)
        self.assertFalse(result.accepted)
        self.assertEqual(result.attempts, 3)
        self.assertTrue(all(row[0]["content"] == "original exact task" for row in calls))
        self.assertEqual(len(calls[-1]), 5)

    async def test_pressure_wait_and_pending_cancellation(self):
        available = False
        scheduler = Scheduler(Config(queue_timeout_s=.5), lambda: available)
        task = asyncio.create_task(scheduler.acquire("normal", None))
        await asyncio.sleep(.03)
        self.assertEqual(scheduler.status()["pending"], 1)
        available = True
        ticket = await task
        pending = asyncio.create_task(scheduler.acquire("background", None))
        await asyncio.sleep(.03)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(scheduler.status()["pending"], 0)
        await scheduler.release(ticket)

    async def test_queue_full_and_unknown_completion(self):
        scheduler = Scheduler(Config(max_pending=1))
        active = await scheduler.acquire("normal", None)
        pending = asyncio.create_task(scheduler.acquire("background", None))
        await asyncio.sleep(.01)
        with self.assertRaises(AdmissionError) as caught:
            await scheduler.acquire("normal", None)
        self.assertEqual(caught.exception.code, "queue_full")
        await scheduler.release(active, uncertain=True)
        with self.assertRaises(AdmissionError):
            await pending
        self.assertTrue(scheduler.status()["backend_completion_uncertain"])


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.wire = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\\"x\\\":1}"}}]},"finish_reason":null}]}\n\n'
                     b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n')
        async def backend(request):
            body = await request.json()
            self.received.append((body, dict(request.headers)))
            if body.get("hold"):
                self.started.set()
                await self.release.wait()
            if body.get("failure"):
                return web.json_response({"error": "fixture failure"}, status=500)
            if body.get("stream"):
                response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
                await response.prepare(request)
                for part in (self.wire[:17], self.wire[17:80], self.wire[80:]):
                    await response.write(part)
                await response.write_eof()
                return response
            return web.json_response({"model": body["model"], "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})
        app = web.Application()
        app.router.add_post("/v1/chat/completions", backend)
        app.router.add_get("/v1/models", lambda request: web.json_response({"data": [{"id": "fixture"}]}))
        self.backend_runner, self.backend_url = await start_app(app)
        self.app = create_app(Config(backend_url=self.backend_url + "/v1", upstream_timeout_s=2))
        self.runner, self.url = await start_app(self.app)
        self.client = ClientSession()

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()
        await self.runner.cleanup()
        await self.backend_runner.cleanup()

    async def test_transparent_tools_stream_and_metadata(self):
        body = {"model": "fixture", "messages": [{"role": "user", "content": "use tool"}],
                "tools": [{"type": "function", "function": {"name": "check", "parameters": {"type": "object"}}}],
                "max_tokens": 777, "temperature": .7, "seed": 98, "stream": True,
                "adaptive_scheduling": {"class": "background"}}
        original = copy.deepcopy(body)
        async with self.client.post(self.url + "/v1/chat/completions", json=body) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), self.wire)
        self.assertEqual(body, original)
        expected = copy.deepcopy(body)
        del expected["adaptive_scheduling"]
        self.assertEqual(self.received[0][0], expected)
        row = self.app[GATEWAY].history[-1]
        self.assertTrue(row["trained"])
        self.assertEqual(row["class"], "background")

    async def test_auth_is_separate_and_not_forwarded(self):
        await self.runner.cleanup()
        with patch.dict(os.environ, {"TEST_GATEWAY_TOKEN": "gateway-only", "TEST_BACKEND_TOKEN": "backend-only"}):
            self.app = create_app(Config(backend_url=self.backend_url + "/v1", api_key_env="TEST_GATEWAY_TOKEN", backend_key_env="TEST_BACKEND_TOKEN"))
        self.runner, self.url = await start_app(self.app)
        async with self.client.get(self.url + "/status") as response:
            self.assertEqual(response.status, 401)
        body = {"model": "fixture", "messages": []}
        async with self.client.post(self.url + "/v1/chat/completions", json=body, headers={"Authorization": "Bearer gateway-only"}) as response:
            self.assertEqual(response.status, 200)
            await response.read()
        self.assertEqual(self.received[-1][1]["Authorization"], "Bearer backend-only")

    async def test_invalid_metadata_never_dispatches(self):
        for extra in ({"adaptive_scheduling": {"class": "urgent"}},
                      {"adaptive_scheduling": {"class": "normal"}, "strata_scheduling": {"class": "background"}},
                      {"strata_tune": {"pcie_frac": .37}}):
            async with self.client.post(self.url + "/v1/chat/completions", json={"model": "fixture", "messages": [], **extra}) as response:
                self.assertEqual(response.status, 400)
        self.assertEqual(self.received, [])

    async def test_http_failure_not_trained_or_retried(self):
        async with self.client.post(self.url + "/v1/chat/completions", json={"model": "fixture", "messages": [], "failure": True}) as response:
            self.assertEqual(response.status, 500)
            await response.read()
        self.assertEqual(len(self.received), 1)
        self.assertFalse(self.app[GATEWAY].history[-1]["trained"])

    async def test_queued_disconnect_never_reaches_backend(self):
        body = {"model": "fixture", "messages": [], "hold": True}
        owner = asyncio.create_task(self.client.post(self.url + "/v1/chat/completions", json=body))
        await self.started.wait()
        pending = asyncio.create_task(self.client.post(self.url + "/v1/chat/completions", json={"model": "fixture", "messages": []}))
        for _ in range(100):
            if self.app[GATEWAY].scheduler.status()["pending"]:
                break
            await asyncio.sleep(.01)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        await asyncio.sleep(.2)
        self.release.set()
        response = await owner
        await response.read()
        self.assertEqual(len(self.received), 1)

    async def test_timeout_quarantines_without_retry(self):
        await self.runner.cleanup()
        self.app = create_app(Config(backend_url=self.backend_url + "/v1", upstream_timeout_s=.08))
        self.runner, self.url = await start_app(self.app)
        async with self.client.post(self.url + "/v1/chat/completions", json={"model": "fixture", "messages": [], "hold": True}) as response:
            self.assertEqual(response.status, 502)
            await response.read()
        self.assertTrue(self.app[GATEWAY].scheduler.uncertain)
        async with self.client.post(self.url + "/v1/chat/completions", json={"model": "fixture", "messages": []}) as response:
            self.assertEqual(response.status, 503)
        self.assertEqual(len(self.received), 1)


if __name__ == "__main__":
    unittest.main()
