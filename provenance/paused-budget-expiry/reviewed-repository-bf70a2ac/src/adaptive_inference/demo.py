"""A transparent, no-model demonstration using actual loopback HTTP."""
import asyncio
from dataclasses import asdict
import json

from aiohttp import ClientSession, ClientTimeout, web

from .config import Config
from .feedback import Verdict, run_with_feedback
from .gateway import create_app


async def start_app(app):
    runner = web.AppRunner(app, access_log=None, handler_cancellation=False, shutdown_timeout=5)
    try:
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        return runner, f"http://127.0.0.1:{port}"
    except BaseException:
        await runner.cleanup()
        raise


async def run_demo():
    try:
        async with asyncio.timeout(30):
            return await _run_demo()
    except TimeoutError:
        raise RuntimeError("Demo did not finish within 30 seconds") from None


async def _run_demo():
    dispatches = []
    active_started = asyncio.Event()
    active_release = asyncio.Event()

    async def fixture(request):
        body = await request.json()
        prompt = body["messages"][0]["content"]
        dispatches.append(prompt)
        if prompt == "held":
            active_started.set()
            await active_release.wait()
        await asyncio.sleep(.015)
        answer = "437" if prompt == "Calculate 19 times 23" else "493"
        if prompt == "Return the exact word complete":
            answer = "complete" if len(body["messages"]) > 1 else "incomplete"
        return web.json_response({"model": body["model"], "choices": [{"index": 0,
            "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})

    backend = web.Application()
    backend.router.add_post("/v1/chat/completions", fixture)
    backend.router.add_get("/v1/models", lambda request: web.json_response({"data": [{"id": "fixture"}]}))
    back_runner, back_url = await start_app(backend)
    gateway_runner = None
    tasks = []
    try:
        app = create_app(Config(backend_url=back_url + "/v1"))
        gateway_runner, url = await start_app(app)
        async with ClientSession(timeout=ClientTimeout(total=10), trust_env=False) as client:
            async def call(prompt, background=False, messages=None, model="fixture"):
                body = {"model": model, "messages": messages if messages is not None else [{"role": "user", "content": prompt}], "max_tokens": 128}
                route = "/background/v1/chat/completions" if background else "/v1/chat/completions"
                async with client.post(url + route, json=body) as response:
                    data = await response.json()
                    if response.status != 200:
                        raise RuntimeError("Demo request failed: " + str(response.status))
                    return data["choices"][0]["message"]["content"]

            for background, prompt, expected in ((False, "Calculate 19 times 23", "437"),
                                                  (True, "Calculate 17 times 29", "493")):
                for _ in range(4):
                    if await call(prompt, background) != expected:
                        raise RuntimeError("Simulated answer differs")
            async with client.get(url + "/metrics") as response:
                learned = await response.json()
            for offset in (0, 4):
                rows = learned["history"][offset:offset + 4]
                if [row["prediction"]["samples"] for row in rows] != [0, 1, 2, 3]:
                    raise RuntimeError("Timing groups failed to accumulate")
                if rows[-1]["prediction"]["reason"] != "measured":
                    raise RuntimeError("Measured feedback did not engage")

            # Use a separate fixture identity so both waiting classes have the
            # same cold cost estimate. A warmed background request can otherwise
            # correctly outrank an unmatched cold normal request (30 s vs 10 s).
            owner = asyncio.create_task(call("held", model="ordering-fixture"))
            tasks.append(owner)
            await asyncio.wait_for(active_started.wait(), 2)
            background_task = asyncio.create_task(call("earlier background", True, model="ordering-fixture"))
            tasks.append(background_task)
            # Observe its admission before sending the later normal request;
            # task creation order alone does not prove HTTP arrival order.
            for _ in range(100):
                async with client.get(url + "/status") as response:
                    state = await response.json()
                if state["scheduler"]["background_pending"] == 1:
                    break
                await asyncio.sleep(.01)
            else:
                raise RuntimeError("Background request did not enter the queue")
            normal_task = asyncio.create_task(call("later normal", model="ordering-fixture"))
            tasks.append(normal_task)
            for _ in range(100):
                async with client.get(url + "/status") as response:
                    state = await response.json()
                if state["scheduler"]["pending"] == 2:
                    break
                await asyncio.sleep(.01)
            else:
                raise RuntimeError("Concurrent demo requests did not enter the queue")
            active_release.set()
            await asyncio.gather(owner, background_task, normal_task)
            if dispatches[-3:] != ["held", "later normal", "earlier background"]:
                raise RuntimeError("Priority ordering differed")
            async with client.get(url + "/metrics") as response:
                ordered = await response.json()
            if any(row["prediction"]["samples"] != 0 for row in ordered["history"][-3:]):
                raise RuntimeError("Ordering demo unexpectedly reused measured costs")

            async def generate(messages):
                return await call("", messages=messages)

            outcome = await run_with_feedback("Return the exact word complete", generate,
                         lambda output: Verdict(output == "complete", "Return complete, not incomplete."))
            if not outcome.accepted or outcome.attempts != 2:
                raise RuntimeError("Correction loop did not reach the acceptance criterion")
            async with client.get(url + "/status") as response:
                final = await response.json()
            if final["scheduler"]["active"] or final["scheduler"]["pending"]:
                raise RuntimeError("Admission did not settle")
            return {"passed": True, "backend": "simulated fixture; no LLM or GPU",
                    "transport": "actual loopback HTTP", "feedback_requests": 8,
                    "learned_predictions": 2, "dispatch_order": dispatches[8:11],
                    "ordering_cost_condition": "both waiting classes cold; background observed queued first",
                    "task_correction": asdict(outcome), "pending": 0, "active": False,
                    "speedup_claim": False}
    finally:
        active_release.set()
        for task in tasks:
            if not task.done(): task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if gateway_runner:
            await gateway_runner.cleanup()
        await back_runner.cleanup()
