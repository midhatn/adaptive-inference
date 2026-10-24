import asyncio
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace
import unittest

from aiohttp import ClientSession
from adaptive_inference.config import Config
from adaptive_inference.handoff import ForegroundPolicy
from native_owner_adapter import NativeOwnerAdapter, OwnerStartupError
from test_native_owner_adapter import Driver, live, stopped
from windows_host import DesktopHost


class Job:
    def __init__(self):
        self.contained = False
        self.children = set()

    def contain_current_process(self):
        self.contained = True

    def active_process_ids(self):
        return {os.getpid(), *self.children}


class Reader:
    busy = False

    def sample(self):
        return {"monotonic_s": time.monotonic(), "session_input_idle_s": 0 if self.busy else 100,
                "foreground": {"pid": 44, "creation_time_100ns": 55, "valid": True, "cpu_cores_used": 0},
                "host": {"ram_available_gib": 40, "commit_available_gib": 60}, "errors": []}


class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve() / "run"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.config = Config(port=self.port, backend_kind="strata", backend_url="http://127.0.0.1:18098/v1")
        self.job, self.reader, self.driver = Job(), Reader(), Driver()
        self.driver.state = stopped(self.driver.state)
        self.adapter = NativeOwnerAdapter(_driver=self.driver)
        self.host = DesktopHost({}, self.config, self.path,
            ForegroundPolicy(input_hold_s=1, recovery_s=0, engage_samples=1),
            _adapter=self.adapter, _reader=self.reader, _job=self.job)

    async def asyncTearDown(self):
        self.job.children.clear()
        if self.host.started_at is not None and not self.host.closed:
            await self.host.close(timeout_s=5)
        self.temp.cleanup()

    async def test_actual_gateway_controller_and_adapter_composition(self):
        ready = await self.host.start(timeout_s=5)
        self.assertTrue(self.job.contained)
        self.assertTrue(ready["ready"])
        async with ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{self.port}/status") as response:
                self.assertEqual(response.status, 200)
                status = await response.json()
                self.assertTrue(status["resources"]["admission_allowed"])
        self.reader.busy = True
        until = time.monotonic() + 3
        while self.host.controller.state != "parked" and time.monotonic() < until:
            await asyncio.sleep(.05)
        self.assertEqual(self.host.controller.state, "parked")
        self.assertTrue(self.driver.locked)
        self.reader.busy = False
        # The replacement must be a fresh identity, including this fake driver.
        original = self.driver.start_owner
        def restart(runtime):
            self.driver.reuse_owner = True  # b -> a is distinct for this transition.
            return original(runtime)
        self.driver.start_owner = restart
        new = await self.host.wait_ready(timeout_s=3)
        self.assertNotEqual(ready["owner_id"], new["owner_id"])
        self.assertFalse(self.driver.locked)
        result = await self.host.close(timeout_s=5)
        self.assertTrue(result["owned_children_exited"])
        self.assertTrue(result["release"]["released"])
        self.assertTrue(json.loads((self.path / "result.json").read_text())["closed"])

    async def test_external_owned_worker_blocks_normal_close_until_exit(self):
        await self.host.start(timeout_s=5)
        self.job.children.add(99999)
        with self.assertRaisesRegex(RuntimeError, "external worker"):
            await self.host.close(timeout_s=5)
        self.assertFalse(self.host.closed)
        self.assertEqual(self.driver.stops, 0)
        self.job.children.clear()
        self.assertTrue((await self.host.close(timeout_s=5))["closed"])

    async def test_close_waits_for_actual_scheduler_active_owner(self):
        await self.host.start(timeout_s=5)
        scheduler = self.host.gateway.scheduler
        ticket = await scheduler.acquire("normal", None)
        closing = asyncio.create_task(self.host.close(timeout_s=5))
        while not scheduler.closing:
            await asyncio.sleep(.01)
        await asyncio.sleep(.05)
        self.assertIs(scheduler.active, ticket)
        self.assertEqual(self.driver.stops, 0)
        self.assertFalse(closing.done())
        await scheduler.release(ticket)
        result = await closing
        self.assertEqual(self.driver.stops, 1)
        self.assertTrue(result["release"]["released"])

    async def test_preexisting_live_owner_is_not_adopted_or_stopped(self):
        from test_native_owner_adapter import live
        self.driver.state = live()
        with self.assertRaisesRegex(RuntimeError, "refuses to adopt"):
            await self.host.start(timeout_s=5)
        self.assertEqual(self.driver.starts, 0)
        await self.host.close(timeout_s=5)
        self.assertEqual(self.driver.stops, 0)

    async def test_cancel_after_native_start_still_stops_new_owned_identity(self):
        actual_start = self.adapter.start
        async def cancelled_after_start():
            await actual_start()
            raise asyncio.CancelledError()
        self.adapter.start = cancelled_after_start
        with self.assertRaises(asyncio.CancelledError):
            await self.host.start(timeout_s=5)
        self.assertTrue(self.host.started_owner)
        self.assertTrue(self.driver.state["running"])
        self.assertFalse(self.host.controller())
        self.assertFalse((self.path / "ready.json").exists())
        result = await self.host.close(timeout_s=5)
        self.assertEqual(self.driver.stops, 1)
        self.assertTrue(result["release"]["released"])

    def failed_launch(self, code):
        failure = OwnerStartupError("New owner exited before readiness", owner_id="new-attempt",
            run=self.path / "owner-run", process=SimpleNamespace(pid=20068, poll=lambda:code[0]))
        def start(runtime):
            self.driver.starts += 1
            self.driver.state = live("foreign-observation")
            raise failure from PermissionError(5, "Original collection failure")
        self.driver.start_owner = start
        return failure

    async def test_failed_start_cleanup_preserves_primary_error_without_adopting_status(self):
        failure = self.failed_launch([1])
        with self.assertRaises(OwnerStartupError) as raised:
            await self.host.start(timeout_s=5)
        self.assertIs(raised.exception, failure)
        self.driver.status = lambda: (_ for _ in ()).throw(AssertionError("Do not adopt current active owner"))
        primary = json.loads((self.path / "startup-error.private.json").read_text())
        self.assertIn("Original collection failure", primary["traceback"])
        self.assertEqual(primary["type"], "OwnerStartupError")
        result = await self.host.close(timeout_s=5)
        self.assertTrue(result["closed"])
        self.assertTrue(result["owned_children_exited"])
        self.assertTrue(result["startup_failed"])
        self.assertFalse(result["native_cleanup_confirmed"])
        self.assertIsNone(result["release"])
        self.assertEqual(self.driver.stops, 0)
        self.assertFalse(self.driver.locked)
        self.assertFalse(self.host.activity_thread.is_alive())
        diagnostic = json.loads((self.path / "failed-start-cleanup.private.json").read_text())
        self.assertEqual(diagnostic["owner_id"], "new-attempt")
        self.assertEqual(diagnostic["owner_exit_code"], 1)
        self.assertFalse(diagnostic["cleanup_confirmed"])
        self.assertFalse((self.path / "ready.json").exists())

    async def test_failed_owner_exit_does_not_prove_its_children_exited(self):
        failure = self.failed_launch([1])
        with self.assertRaises(OwnerStartupError):
            await self.host.start(timeout_s=5)
        self.job.children.add(99999)
        with self.assertRaisesRegex(RuntimeError, "descendants remain") as raised:
            await self.host.close(timeout_s=5)
        self.assertIs(raised.exception.__cause__, failure)
        self.assertFalse(self.host.closed)
        self.assertTrue(self.driver.locked)
        self.assertEqual(self.driver.stops, 0)
        self.assertFalse((self.path / "result.json").exists())
        self.job.children.clear()
        self.assertTrue((await self.host.close(timeout_s=5))["closed"])

    async def test_failed_start_live_handle_blocks_close_even_with_empty_job_snapshot(self):
        code = [None]
        self.failed_launch(code)
        with self.assertRaises(OwnerStartupError):
            await self.host.start(timeout_s=5)
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            await self.host.close(timeout_s=5)
        self.assertFalse(self.host.closed)
        self.assertTrue(self.driver.locked)
        code[0] = 1
        self.assertTrue((await self.host.close(timeout_s=5))["closed"])

    async def test_failed_start_port_occupation_blocks_close(self):
        self.failed_launch([1])
        with self.assertRaises(OwnerStartupError):
            await self.host.start(timeout_s=5)
        self.driver.free = False
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            await self.host.close(timeout_s=5)
        self.assertFalse(self.host.closed)
        self.assertTrue(self.driver.locked)
        self.driver.free = True
        self.assertTrue((await self.host.close(timeout_s=5))["closed"])

    async def test_spawn_failure_with_no_returned_handle_does_not_claim_owner_exit(self):
        failure = OwnerStartupError("CreateProcess failed", owner_id="attempt-before-handle",
                                    run=self.path / "owner-run", process=None)
        self.driver.start_owner = lambda _: (_ for _ in ()).throw(failure)
        with self.assertRaises(OwnerStartupError):
            await self.host.start(timeout_s=5)
        result = await self.host.close(timeout_s=5)
        self.assertTrue(result["closed"])
        self.assertIsNone(result["release"])
        self.assertFalse(result["native_cleanup_confirmed"])
        diagnostic = json.loads((self.path / "failed-start-cleanup.private.json").read_text())
        self.assertFalse(diagnostic["process_created"])
        self.assertFalse(diagnostic["owner_exit_confirmed"])
        self.assertIsNone(diagnostic["owner_exit_code"])

    async def test_startup_status_updates_while_foreground_blocks_start(self):
        self.reader.busy = True
        starting = asyncio.create_task(self.host.start(timeout_s=5))
        while not (self.path / "status.json").exists():
            await asyncio.sleep(.01)
        await asyncio.sleep(.1)
        first = json.loads((self.path / "status.json").read_text())
        await asyncio.sleep(.55)
        second = json.loads((self.path / "status.json").read_text())
        self.assertEqual(second["host_phase"], "waiting_foreground")
        self.assertGreater(second["observed_at"], first["observed_at"])
        self.assertFalse(second["controller"]["admission_allowed"])
        self.assertEqual(self.driver.starts, 0)
        self.reader.busy = False
        self.assertTrue((await starting)["ready"])

    async def test_native_start_consumes_deadline_and_is_closed_without_admission(self):
        actual_start = self.adapter.start
        async def slow_start():
            state = await actual_start()
            await asyncio.sleep(1.1)
            return state
        self.adapter.start = slow_start
        with self.assertRaisesRegex(TimeoutError, "Startup deadline elapsed"):
            await self.host.start(timeout_s=1)
        self.assertTrue(self.host.closed)
        self.assertEqual(self.driver.stops, 1)
        self.assertFalse(self.host.controller())
        self.assertFalse((self.path / "ready.json").exists())
        self.assertIsNone(self.host.runner)
        self.assertTrue(self.host.close_result["release"]["released"])

    async def test_controller_initialization_consumes_same_startup_deadline(self):
        actual_initialize = self.host.controller.initialize
        async def slow_initialize():
            await actual_initialize()
            await asyncio.sleep(1.1)
        self.host.controller.initialize = slow_initialize
        with self.assertRaisesRegex(TimeoutError, "Startup deadline elapsed"):
            await self.host.start(timeout_s=1)
        self.assertTrue(self.host.closed)
        self.assertFalse(self.host.controller())
        self.assertFalse((self.path / "ready.json").exists())
        self.assertEqual(self.driver.stops, 1)

    async def test_existing_output_directory_is_refused(self):
        self.path.mkdir()
        with self.assertRaisesRegex(ValueError, "new run directory"):
            DesktopHost({}, self.config, self.path, _adapter=self.adapter, _reader=self.reader, _job=self.job)


if __name__ == "__main__":
    unittest.main()
