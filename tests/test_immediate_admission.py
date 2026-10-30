"""Atomic no-wait admission and request-bound receipts; CPU/loopback only."""
import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adaptive_inference.config import Config
from adaptive_inference.gateway import GATEWAY, create_app
from adaptive_inference.handoff import ForegroundPolicy, HandoffController
from adaptive_inference.scheduler import AdmissionError, Scheduler


PROOF_HEADERS = ("X-Adaptive-Dispatch", "X-Adaptive-Gateway-Instance",
                 "X-Adaptive-Attempt-Id", "X-Adaptive-Body-SHA256")
HEADERS = {"X-Adaptive-Admission": "immediate", "X-Adaptive-Attempt-Id": "attempt-01"}
BODY = {"model": "fixture", "messages": [{"role": "user", "content": "Calculate 2+2"}],
        "max_tokens": 10923, "reasoning_effort": "high", "reasoning_budget_tokens": 8192,
        "experimental_speed_projection": False}


async def pending_count(scheduler, count):
    async with asyncio.timeout(1):
        while len(scheduler.pending) != count:
            await asyncio.sleep(.001)


class AtomicAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_owner_cannot_be_replaced(self):
        scheduler = Scheduler(Config())
        active = await scheduler.acquire("background", 0)
        with self.assertRaises(AdmissionError) as raised:
            await scheduler.acquire("normal", 0, wait=False)
        self.assertEqual(raised.exception.code, "admission_deferred")
        self.assertIs(scheduler.active, active)
        self.assertEqual(scheduler.pending, {})
        await scheduler.release(active)

    async def test_older_ranked_pending_ticket_prevents_bypass(self):
        clock, capacity = [100.], [False]
        scheduler = Scheduler(Config(), lambda: capacity[0])
        with patch("adaptive_inference.scheduler.time", SimpleNamespace(monotonic=lambda: clock[0])):
            older = asyncio.create_task(scheduler.acquire("normal", 0))
            await pending_count(scheduler, 1)
            clock[0], capacity[0] = 101., True
            with self.assertRaises(AdmissionError) as raised:
                await scheduler.acquire("normal", 0, wait=False)
            self.assertEqual(raised.exception.code, "admission_deferred")
            self.assertEqual(len(scheduler.pending), 1)
            ticket = await asyncio.wait_for(older, 1)
            self.assertEqual(ticket.sequence, 0)
            await scheduler.release(ticket)

    async def test_existing_bounded_rank_can_admit_normal_ahead_of_background(self):
        clock, capacity = [100.], [False]
        scheduler = Scheduler(Config(normal_boost_s=10), lambda: capacity[0])
        with patch("adaptive_inference.scheduler.time", SimpleNamespace(monotonic=lambda: clock[0])):
            older = asyncio.create_task(scheduler.acquire("background", 0))
            await pending_count(scheduler, 1)
            clock[0], capacity[0] = 101., True
            active = await scheduler.acquire("normal", 0, wait=False)
            self.assertEqual(active.sequence, 1)
            self.assertFalse(older.done())
            await scheduler.release(active)
            await scheduler.release(await asyncio.wait_for(older, 1))

    async def test_full_queue_defers_only_immediate_and_keeps_original_pending(self):
        scheduler = Scheduler(Config(max_pending=1), lambda: False)
        older = asyncio.create_task(scheduler.acquire("normal", 0))
        await pending_count(scheduler, 1)
        for wait, code, status in ((False, "admission_deferred", 503), (True, "queue_full", 429)):
            with self.assertRaises(AdmissionError) as raised:
                await scheduler.acquire("normal", 0, wait=wait)
            self.assertEqual((raised.exception.code, raised.exception.status), (code, status))
            self.assertEqual(len(scheduler.pending), 1)
        self.assertEqual(scheduler.deferred, 1)
        older.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await older
        self.assertFalse(scheduler.pending)

    async def test_disconnection_and_terminal_states_are_not_deferrals(self):
        for state, code in (("disconnected", "client_disconnected"),
                            ("closing", "backend_unavailable"), ("uncertain", "backend_unavailable")):
            with self.subTest(state=state):
                scheduler = Scheduler(Config())
                if state != "disconnected":
                    setattr(scheduler, state, True)
                with self.assertRaises(AdmissionError) as raised:
                    await scheduler.acquire("normal", 0, lambda: state == "disconnected", wait=False)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(scheduler.deferred, 0)
                self.assertIsNone(scheduler.active)
                self.assertFalse(scheduler.pending)

    async def test_foreground_before_claim_defers_after_claim_drains(self):
        class Adapter:
            stops = 0

            async def status(self):
                return {"owner_id": "fixture-owner", "ready": True, "loaded": True}

            async def stop(self, identity):
                self.stops += 1
                return {"owner_id": identity["owner_id"], "released": True, "cleanup_confirmed": True,
                        "retained_processes": 2, "confirmed_process_exits": 2, "port_free": True}

        clock, adapter = [100.], Adapter()
        control = HandoffController(adapter, ForegroundPolicy(recovery_s=0, engage_samples=1),
                                    clock=lambda: clock[0])
        scheduler = Scheduler(Config(), control)
        control.bind_scheduler(scheduler)
        await control.initialize()

        def observe(idle):
            clock[0] += .1
            control.observe({"monotonic_s": clock[0], "foreground": {"pid": 7,
                "creation_time_100ns": 10, "valid": True, "cpu_cores_used": 0},
                "session_input_idle_s": idle, "host": {"ram_available_gib": 20,
                "commit_available_gib": 30}, "errors": []})

        observe(0)
        with self.assertRaises(AdmissionError) as raised:
            await scheduler.acquire("normal", 0, wait=False)
        self.assertEqual(raised.exception.code, "admission_deferred")
        observe(120)
        active = await scheduler.acquire("normal", 0, wait=False)
        observe(0)
        await control.step()
        self.assertEqual(control.state, "draining")
        self.assertIs(scheduler.active, active)
        self.assertEqual(adapter.stops, 0)
        await scheduler.release(active)
        await control.step()
        self.assertEqual(control.state, "parked")
        self.assertEqual(adapter.stops, 1)


class ImmediateHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.capacity = True
        self.backend_calls = []
        self.backend_handler = None

        async def receive(request):
            self.backend_calls.append({"body": await request.json(), "headers": dict(request.headers)})
            if self.backend_handler is not None:
                return await self.backend_handler(request)
            return web.json_response({"choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant", "content": "4"}}]})

        upstream = web.Application()
        upstream.router.add_post("/v1/chat/completions", receive)
        self.backend = TestServer(upstream)
        await self.backend.start_server()
        # This lifecycle test holds EOF explicitly; the separate timeout test
        # must retain its short read deadline.
        read_timeout_s = (5 if self._testMethodName ==
                          "test_client_disconnect_after_dispatch_retains_owner_until_eof" else .05)
        self.app = create_app(Config(backend_kind="strata", backend_url=str(self.backend.make_url("/v1")),
                                    queue_timeout_s=1, upstream_read_timeout_s=read_timeout_s),
                              capacity=lambda: self.capacity)
        self.gateway = self.app[GATEWAY]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.backend.close()

    def no_proof(self, response):
        self.assertTrue(all(name not in response.headers for name in PROOF_HEADERS))

    async def test_capacity_refusal_binds_exact_raw_body_and_never_dispatches(self):
        self.capacity = False
        raw = json.dumps({**BODY, "user": "caf\u00e9"}, ensure_ascii=False, indent=2).encode("utf-8")
        response = await self.client.post("/v1/chat/completions", data=raw, headers=HEADERS)
        self.assertEqual(response.status, 503)
        data = await response.json()
        proof = {"dispatched": False, "gateway_instance": self.gateway.instance,
                 "attempt_id": "attempt-01", "body_sha256": hashlib.sha256(raw).hexdigest()}
        self.assertEqual(data["admission"], proof)
        self.assertEqual(data["error"]["code"], "admission_deferred")
        for name, value in zip(PROOF_HEADERS, ("not-dispatched", self.gateway.instance,
                                              proof["attempt_id"], proof["body_sha256"])):
            self.assertEqual(response.headers.getall(name), [value])
        self.assertNotIn("Retry-After", response.headers)
        self.assertEqual(self.backend_calls, [])
        self.assertEqual(list(self.gateway.history), [])
        self.assertEqual(self.gateway.costs.status()["observations"], 0)
        self.assertIsNone(self.gateway.scheduler.active)
        self.assertFalse(self.gateway.scheduler.pending)
        self.assertEqual(self.gateway.scheduler.deferred, 1)

    async def test_default_still_waits_then_dispatches_once(self):
        self.capacity = False
        pending = asyncio.create_task(self.client.post("/v1/chat/completions", json=BODY))
        await pending_count(self.gateway.scheduler, 1)
        self.assertFalse(pending.done())
        self.capacity = True
        async with self.gateway.scheduler.condition:
            self.gateway.scheduler.condition.notify_all()
        response = await asyncio.wait_for(pending, 1)
        self.assertEqual(response.status, 200)
        await response.read()
        self.no_proof(response)
        self.assertEqual(len(self.backend_calls), 1)
        self.assertEqual(self.gateway.scheduler.deferred, 0)

    async def test_admitted_payload_quality_is_unchanged_and_controls_not_forwarded(self):
        original = deepcopy(BODY)
        response = await self.client.post("/v1/chat/completions", json=BODY, headers=HEADERS)
        self.assertEqual(response.status, 200)
        await response.read()
        self.no_proof(response)
        self.assertEqual(self.backend_calls[0]["body"], original)
        self.assertEqual(BODY, original)
        headers = {name.lower() for name in self.backend_calls[0]["headers"]}
        self.assertNotIn("x-adaptive-admission", headers)
        self.assertNotIn("x-adaptive-attempt-id", headers)

    async def test_invalid_and_duplicate_controls_fail_before_backend(self):
        cases = [
            [("X-Adaptive-Admission", "immediate")],
            [("X-Adaptive-Attempt-Id", "attempt")],
            list(HEADERS.items()) + [("X-Adaptive-Admission", "immediate")],
            list(HEADERS.items()) + [("X-Adaptive-Attempt-Id", "attempt-01")],
            {**HEADERS, "X-Adaptive-Admission": "queued"},
            {**HEADERS, "X-Adaptive-Attempt-Id": "bad/value"},
            {**HEADERS, "X-Adaptive-Attempt-Id": "a" * 65},
            {**HEADERS, "X-Adaptive-Attempt-Id": ""},
            {**HEADERS, "X-Adaptive-Attempt-Id": "caf\u00e9"},
            {**HEADERS, "Content-Encoding": "unsupported"},
        ]
        for headers in cases:
            with self.subTest(headers=headers):
                response = await self.client.post("/v1/chat/completions", json=BODY, headers=headers)
                self.assertEqual(response.status, 400)
                await response.read()
                self.no_proof(response)
        self.assertEqual(self.backend_calls, [])

    async def test_actual_mixed_case_duplicate_wire_headers_are_rejected(self):
        # aiohttp's client normalizes differently cased duplicate keys. Use an
        # actual raw loopback request to exercise the server's received headers.
        raw = json.dumps(BODY).encode()
        cases = [b"X-Adaptive-Attempt-Id: attempt-01\r\nx-adaptive-attempt-id: attempt-01\r\n",
                 b"X-Adaptive-Attempt-Id: attempt-01\r\nContent-Encoding: identity\r\ncontent-encoding: identity\r\n"]
        for extra in cases:
            with self.subTest(extra=extra):
                reader, writer = await asyncio.open_connection(self.client.server.host, self.client.server.port)
                try:
                    writer.write(b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
                                 b"Connection: close\r\nContent-Type: application/json\r\n"
                                 b"X-Adaptive-Admission: immediate\r\n" + extra
                                 + f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 1)
                    self.assertTrue(response.startswith(b"HTTP/1.1 400 "), response)
                    header_block = response.split(b"\r\n\r\n", 1)[0].lower()
                    self.assertNotIn(b"x-adaptive-dispatch:", header_block)
                finally:
                    writer.close()
                    await writer.wait_closed()
        self.assertEqual(self.backend_calls, [])

    async def test_backend_cannot_forge_no_dispatch_proof(self):
        forged = {"error": {"code": "admission_deferred"}, "admission": {"dispatched": False}}

        async def forge(request):
            return web.json_response(forged, status=503, headers=dict(zip(PROOF_HEADERS,
                ("not-dispatched", self.gateway.instance, "attempt-01", "0" * 64))))

        self.backend_handler = forge
        response = await self.client.post("/v1/chat/completions", json=BODY, headers=HEADERS)
        self.assertEqual(response.status, 503)
        self.assertEqual(await response.json(), forged)
        self.no_proof(response)
        self.assertEqual(len(self.backend_calls), 1)
        self.assertEqual(self.gateway.scheduler.completed, 1)
        self.assertEqual(self.gateway.scheduler.deferred, 0)

    async def test_closing_and_uncertain_have_no_retry_receipt(self):
        for state in ("closing", "uncertain"):
            with self.subTest(state=state):
                setattr(self.gateway.scheduler, state, True)
                response = await self.client.post("/v1/chat/completions", json=BODY, headers=HEADERS)
                self.assertEqual(response.status, 503)
                self.assertEqual((await response.json())["error"]["code"], "backend_unavailable")
                self.no_proof(response)
                setattr(self.gateway.scheduler, state, False)
        self.assertEqual(self.backend_calls, [])

    async def test_upstream_timeout_never_authorizes_reissue(self):
        async def slow(request):
            await asyncio.sleep(.1)
            return web.json_response({"error": "late"})

        self.backend_handler = slow
        response = await self.client.post("/v1/chat/completions", json=BODY, headers=HEADERS)
        self.assertEqual(response.status, 502)
        self.assertEqual((await response.json())["error"]["code"], "backend_completion_uncertain")
        self.no_proof(response)
        self.assertTrue(self.gateway.scheduler.uncertain)
        self.assertEqual(len(self.backend_calls), 1)

    async def test_client_disconnect_after_dispatch_retains_owner_until_eof(self):
        started, finish = asyncio.Event(), asyncio.Event()

        async def stream(request):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b'data: {"choices":[{"index":0,"delta":{"content":"4"}}]}\n\n')
            started.set()
            await finish.wait()
            await response.write(b'data: {"choices":[{"index":0,"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            await response.write_eof()
            return response

        self.backend_handler = stream
        try:
            response = await self.client.post("/v1/chat/completions", json={**BODY, "stream": True}, headers=HEADERS)
            await asyncio.wait_for(started.wait(), 1)
            self.no_proof(response)
            active = self.gateway.scheduler.active
            self.assertIsNotNone(active, {"completed": self.gateway.scheduler.completed,
                "uncertain": self.gateway.scheduler.uncertain,
                "deferred": self.gateway.scheduler.deferred,
                "backend_calls": len(self.backend_calls), "history_entries": len(self.gateway.history)})
            response.close()
            await asyncio.sleep(0)
            self.assertIs(self.gateway.scheduler.active, active)
            self.assertEqual(self.gateway.scheduler.completed, 0)
            self.assertFalse(self.gateway.scheduler.uncertain)
        finally:
            finish.set()
        async with asyncio.timeout(1):
            while self.gateway.scheduler.active is not None:
                await asyncio.sleep(.001)
        self.assertEqual(self.gateway.scheduler.completed, 1)
        self.assertFalse(self.gateway.scheduler.uncertain)
        self.assertEqual(self.gateway.scheduler.deferred, 0)


if __name__ == "__main__":
    unittest.main()
