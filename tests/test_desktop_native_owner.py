import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.native_owner_adapter import (CapacityMonitor, NativeOwnerAdapter, OwnerPackage,
                                  OwnerStartupError, identity, validate_handoff_config)


def live(owner="a"):
    return {"owner_id": owner, "run": "runs/" + owner,
            "owner": {"pid": 10, "created_filetime": 111 if owner == "a" else 222, "exe": "python.exe"},
            "state": "ready", "running": True, "ready": True, "loaded": True, "port": 18098,
            "model": "qwen3.8-flash-next-iq3_s-adaptive-media-beta",
            "processes": {"retained_total": 3, "confirmed_exits": 1,
                          "active": [{"pid": 11, "created_filetime": 112, "exe": "strata.exe"},
                                     {"pid": 12, "created_filetime": 113, "exe": "strata-vision.exe"}]}}


def stopped(before):
    out = copy.deepcopy(before)
    out.update(state="stopped", running=False, ready=False, loaded=False,
               cleanup_confirmed=True, server_exit_code=0, error=None, memory={"error": None})
    out["processes"].update(confirmed_exits=3, active=[])
    return out


class Handle:
    def __init__(self, record, driver):
        self.record = record
        self.driver = driver
        self.closed = False

    def exited(self):
        return self.driver.exit_handles

    def close(self):
        self.closed = True


class Driver:
    def __init__(self):
        self.state = live()
        self.locked = False
        self.stops = 0
        self.starts = 0
        self.exit_handles = True
        self.free = True
        self.handles = []
        self.fail_receipt = False
        self.reuse_owner = False

    def status(self):
        return copy.deepcopy(self.state)

    def verify(self):
        return {"verified": True}

    def lock_start(self):
        if self.locked:
            raise OSError("already locked")
        self.locked = True
        return object()

    def unlock_start(self, token):
        self.locked = False

    def retain(self, state):
        self.handles = [Handle(r, self) for r in [state["owner"], *state["processes"]["active"]]]
        return self.handles

    def stop_owner(self, expected):
        if not self.locked:
            raise RuntimeError("missing handoff lock")
        self.stops += 1
        self.state = stopped(self.state)
        if self.fail_receipt:
            self.state["processes"]["confirmed_exits"] = 2
        return self.status()

    def port_free(self, port):
        return self.free

    def start_owner(self, runtime):
        if not self.locked:
            raise RuntimeError("missing handoff lock")
        self.starts += 1
        self.state = live("a" if self.reuse_owner else "b")
        return self.status()

    def capacity(self):
        return {"sampled_at": 123.0, "complete": True, "available_ram_gib": 40.0,
                "available_commit_gib": 60.0, "available_vram_mib": 7800.0}

    def close(self):
        pass


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = Driver()
        self.adapter = NativeOwnerAdapter(_driver=self.driver)

    async def test_complete_cycle_retains_barrier_until_distinct_ready_owner(self):
        observed = await self.adapter.status()
        proof = await self.adapter.stop(observed["owner_id"])
        self.assertTrue(proof["released"])
        self.assertEqual(proof["retained_processes"], proof["confirmed_process_exits"])
        self.assertEqual(len(proof["retained_at_stop"]), 3)
        self.assertTrue(all(h.closed for h in self.driver.handles))
        self.assertTrue(self.driver.locked)
        self.assertTrue((await self.adapter.fresh_capacity())["complete"])
        with self.assertRaises(OSError):
            self.driver.lock_start()  # Ordinary launcher remains excluded.
        restarted = await self.adapter.start()
        self.assertNotEqual(restarted["owner_id"], observed["owner_id"])
        self.assertTrue(restarted["loaded"])
        self.assertFalse(self.driver.locked)
        await self.adapter.close()

    async def test_changed_creation_identity_never_stops(self):
        old = await self.adapter.status()
        self.driver.state["owner"]["created_filetime"] += 1
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await self.adapter.stop(old["owner_id"])
        self.assertEqual(self.driver.stops, 0)

    async def test_full_controller_status_is_valid_stop_identity(self):
        observed = await self.adapter.status()
        self.assertTrue((await self.adapter.stop(observed))["released"])

    async def test_actual_handoff_controller_drains_then_stops_and_restores(self):
        from types import SimpleNamespace
        from adaptive_inference.handoff import ForegroundPolicy, HandoffController
        now = [10.0]
        policy = ForegroundPolicy(input_hold_s=1, recovery_s=0, engage_samples=1)
        controller = HandoffController(self.adapter, policy, clock=lambda: now[0])
        scheduler = SimpleNamespace(capacity=controller, active=object(), uncertain=False, closing=False)
        controller.bind_scheduler(scheduler)
        await controller.initialize()
        def sample(idle):
            return {"monotonic_s": now[0], "session_input_idle_s": idle, "errors": [],
                    "foreground": {"pid": 44, "creation_time_100ns": 55, "valid": True,
                                   "cpu_cores_used": 0.0},
                    "host": {"ram_available_gib": 40.0, "commit_available_gib": 60.0}}
        controller.observe(sample(0))
        await controller.step()
        self.assertEqual(controller.state, "draining")
        self.assertEqual(self.driver.stops, 0)
        scheduler.active = None
        await controller.step()
        self.assertEqual(controller.state, "parked")
        self.assertTrue(self.driver.locked)
        now[0] += .5
        controller.observe(sample(100))
        await controller.step()
        self.assertEqual(controller.state, "ready")
        self.assertEqual(controller.identity["owner_id"], "b")
        self.assertFalse(self.driver.locked)

    async def test_unobserved_owner_cannot_be_stopped(self):
        with self.assertRaisesRegex(RuntimeError, "previously observed"):
            await self.adapter.stop("a")
        self.assertFalse(self.driver.locked)

    async def test_incomplete_receipt_never_releases_or_restarts(self):
        await self.adapter.status()
        self.driver.fail_receipt = True
        with self.assertRaisesRegex(RuntimeError, "not proved"):
            await self.adapter.stop("a")
        self.assertTrue(self.driver.locked)
        with self.assertRaisesRegex(RuntimeError, "release proof"):
            await self.adapter.start()
        self.assertEqual(self.driver.starts, 0)

    async def test_unexited_retained_handle_blocks_tool_proof(self):
        await self.adapter.status()
        self.driver.exit_handles = False
        with self.assertRaisesRegex(RuntimeError, "not proved"):
            await self.adapter.stop("a")
        self.assertTrue(all(h.closed for h in self.driver.handles))

    async def test_occupied_port_blocks_release(self):
        await self.adapter.status()
        self.driver.free = False
        with self.assertRaisesRegex(RuntimeError, "not proved"):
            await self.adapter.stop("a")

    async def test_same_owner_replacement_rejected_and_barrier_kept(self):
        await self.adapter.status()
        await self.adapter.stop("a")
        self.driver.reuse_owner = True
        with self.assertRaisesRegex(RuntimeError, "Distinct"):
            await self.adapter.start()
        self.assertTrue(self.driver.locked)

    async def test_close_cannot_silently_release_parked_barrier(self):
        await self.adapter.status()
        await self.adapter.stop("a")
        with self.assertRaisesRegex(RuntimeError, "confirm competing work"):
            await self.adapter.close()
        self.assertTrue(self.driver.locked)
        await self.adapter.close(release_parked=True)
        self.assertFalse(self.driver.locked)

    async def test_repeated_stop_is_idempotent_but_owner_change_is_not(self):
        await self.adapter.status()
        first = await self.adapter.stop("a")
        self.assertEqual(await self.adapter.stop("a"), first)
        self.assertEqual(self.driver.stops, 1)
        self.driver.state["owner_id"] = "other"
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await self.adapter.stop("a")

    async def test_can_start_from_previously_stopped_clean_package(self):
        self.driver.state = stopped(self.driver.state)
        await self.adapter.status()
        self.assertTrue((await self.adapter.start())["ready"])

    async def test_failed_own_launch_preserves_attempt_and_never_adopts_active_status(self):
        previous = await self.adapter.status()
        await self.adapter.stop(previous)
        proc = SimpleNamespace(pid=20, poll=lambda: 1)
        failure = OwnerStartupError("Own startup exited", owner_id="b", run="runs/b", process=proc)
        def failed(runtime):
            self.driver.starts += 1
            self.driver.state = live("foreign")
            raise failure from PermissionError(5, "Denied during collection")
        self.driver.start_owner = failed
        with self.assertRaises(OwnerStartupError) as raised:
            await self.adapter.start()
        self.assertIs(raised.exception, failure)
        self.assertIsInstance(failure.__cause__, PermissionError)
        self.assertIs(failure.process, proc)
        self.assertIsNone(self.adapter._released)
        self.assertEqual(self.adapter._expected, identity(previous))
        # An unrelated active.json must never be adopted merely to repair status.
        self.driver.status = lambda: (_ for _ in ()).throw(AssertionError("Active status was consulted"))
        with self.assertRaises(OwnerStartupError) as status:
            await self.adapter.status()
        self.assertIs(status.exception, failure)
        with self.assertRaises(OwnerStartupError):
            await self.adapter.start()
        with self.assertRaises(OwnerStartupError):
            await self.adapter.stop(previous)
        self.assertEqual(self.driver.starts, 1)
        diagnostic = await self.adapter.failed_start_status()
        self.assertEqual(diagnostic["owner_id"], "b")
        self.assertEqual(diagnostic["owner_exit_code"], 1)
        self.assertTrue(diagnostic["owner_exit_confirmed"])
        self.assertFalse(diagnostic["cleanup_confirmed"])
        await self.adapter.close(release_parked=True)
        self.assertIsNone(self.adapter._released)

    async def test_failed_start_keeps_barrier_until_original_handle_exits_and_port_is_free(self):
        self.driver.state = stopped(self.driver.state)
        await self.adapter.status()
        code = [None]
        failure = OwnerStartupError("Still starting", owner_id="b", run="runs/b",
                                    process=SimpleNamespace(pid=20, poll=lambda: code[0]))
        self.driver.start_owner = lambda _: (_ for _ in ()).throw(failure)
        with self.assertRaises(OwnerStartupError):
            await self.adapter.start()
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            await self.adapter.close(release_parked=True)
        self.assertTrue(self.driver.locked)
        code[0] = 1
        self.driver.free = False
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            await self.adapter.close(release_parked=True)
        self.assertTrue(self.driver.locked)
        self.driver.free = True
        await self.adapter.close(release_parked=True)
        self.assertFalse(self.driver.locked)
        self.assertIsNone(self.adapter._released)

    async def test_failed_start_observation_error_is_not_exit(self):
        self.driver.state = stopped(self.driver.state)
        await self.adapter.status()
        proc = SimpleNamespace(pid=20, poll=lambda: (_ for _ in ()).throw(PermissionError("poll failed")))
        failure = OwnerStartupError("Failed", owner_id="b", run="runs/b", process=proc)
        self.driver.start_owner = lambda _: (_ for _ in ()).throw(failure)
        with self.assertRaises(OwnerStartupError):
            await self.adapter.start()
        diagnostic = await self.adapter.failed_start_status()
        self.assertFalse(diagnostic["owner_exit_confirmed"])
        self.assertEqual(diagnostic["process_observation_error"], "PermissionError")
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            await self.adapter.close(release_parked=True)
        self.assertTrue(self.driver.locked)


class StartupAttemptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = Driver()
        self.adapter = NativeOwnerAdapter(_driver=self.driver)

    def test_actual_short_child_exit_is_observed_through_retained_popen(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with subprocess.Popen([sys.executable, "-I", "-c", "raise SystemExit(7)"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=flags) as proc:
            failure = OwnerStartupError("Exited", owner_id="b", run="nonexistent-run", process=proc)
            self.assertEqual(proc.wait(timeout=10), 7)
            diagnostic = failure.diagnostic()
            self.assertIs(failure.process, proc)
            self.assertEqual(diagnostic["pid"], proc.pid)
            self.assertEqual(diagnostic["owner_exit_code"], 7)
            self.assertTrue(diagnostic["owner_exit_confirmed"])
            self.assertFalse(diagnostic["cleanup_confirmed"])

    def test_mismatched_receipt_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "owner.json").write_text(json.dumps({"owner_id":"foreign", "run":str(run),
                "owner":{"pid":20}, "state":"ready", "error":"foreign"}), encoding="utf-8")
            failure = OwnerStartupError("Exited", owner_id="b", run=run,
                                        process=SimpleNamespace(pid=20, poll=lambda: 1))
            diagnostic = failure.diagnostic()
            self.assertFalse(diagnostic["receipt_matches_attempt"])
            self.assertNotIn("receipt_state", diagnostic)
            self.assertFalse(diagnostic["cleanup_confirmed"])

    @unittest.skipUnless(os.name == "nt", "Windows owner launch flags")
    def test_package_exit_before_readiness_retains_generated_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = OwnerPackage.__new__(OwnerPackage)
            package.root = root
            package.verify = lambda: {"verified":True}
            package.module = SimpleNamespace(private_directory=lambda path:path.mkdir(parents=True,exist_ok=True),
                lock=lambda _:object(), unlock=lambda _:None,
                read=lambda _:{"dependencies":{"owner_python":sys.executable}},
                save=lambda path,value:path.write_text(json.dumps(value),encoding="utf-8"),
                status=lambda: (_ for _ in ()).throw(AssertionError("No global status without own receipt")))
            proc = SimpleNamespace(pid=20, poll=lambda: 9)
            with mock.patch("adaptive_inference.desktop.native_owner_adapter.subprocess.Popen", return_value=proc):
                with self.assertRaises(OwnerStartupError) as raised:
                    package.start_owner(900)
            failure = raised.exception
            request = json.loads((Path(failure.run) / "request.json").read_text())
            self.assertEqual(failure.owner_id, request["owner_id"])
            self.assertEqual(len(failure.owner_id), 32)
            self.assertTrue(Path(failure.run).is_relative_to(root / "runs"))
            self.assertIs(failure.process, proc)
            self.assertEqual(failure.diagnostic()["owner_exit_code"], 9)
            self.assertIn("exited before readiness", str(failure.__cause__))

    @unittest.skipUnless(os.name == "nt", "Windows owner launch flags")
    def test_package_failed_or_replaced_receipt_never_becomes_ready(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign), tempfile.TemporaryDirectory() as temporary:
                root, state = Path(temporary), {}
                package = OwnerPackage.__new__(OwnerPackage)
                package.root = root
                package.verify = lambda: {"verified":True}
                package.module = SimpleNamespace(private_directory=lambda path:path.mkdir(parents=True,exist_ok=True),
                    lock=lambda _:object(), unlock=lambda _:None,
                    read=lambda _:{"dependencies":{"owner_python":sys.executable}},
                    save=lambda path,value:path.write_text(json.dumps(value),encoding="utf-8"),
                    status=lambda:state)
                proc = SimpleNamespace(pid=20, poll=lambda: 1)
                def spawn(command, **_):
                    run, owner_id = Path(command[-2]), command[-1]
                    state.update(owner_id="foreign" if foreign else owner_id, run=str(run),
                        owner={"pid":20,"created_filetime":222,"exe":sys.executable},
                        state="ready" if foreign else "failed", running=False, cleanup_confirmed=False,
                        error="Denied during collection")
                    package.module.save(run / "owner.json", state)
                    return proc
                with mock.patch("adaptive_inference.desktop.native_owner_adapter.subprocess.Popen", side_effect=spawn):
                    with self.assertRaises(OwnerStartupError) as raised:
                        package.start_owner(900)
                diagnostic = raised.exception.diagnostic()
                self.assertEqual(diagnostic["receipt_matches_attempt"], not foreign)
                self.assertFalse(diagnostic["cleanup_confirmed"])
                self.assertIn("replaced" if foreign else "failed before readiness", str(raised.exception))

    async def test_cancel_waits_for_transition_thread_without_unlocking(self):
        import threading
        began, finish = threading.Event(), threading.Event()
        real = self.driver.stop_owner
        def slow(expected):
            began.set()
            finish.wait(2)
            return real(expected)
        self.driver.stop_owner = slow
        await self.adapter.status()
        task = asyncio.create_task(self.adapter.stop("a"))
        await asyncio.to_thread(began.wait, 2)
        task.cancel()
        await asyncio.sleep(.02)
        self.assertFalse(task.done())
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.driver.locked)
        self.assertEqual(self.driver.stops, 1)
        self.assertTrue((await self.adapter.stop("a"))["released"])

    def test_exact_identity_and_runtime_bound_validation(self):
        with self.assertRaises(RuntimeError):
            identity({"owner_id": "a", "run": "r", "owner": {"pid": 10}})
        for value in (0, 59, True, float("nan"), float("inf"), 604801):
            with self.assertRaises(ValueError):
                NativeOwnerAdapter(_driver=self.driver, max_runtime_seconds=value)


class CapacityTests(unittest.TestCase):
    def test_independent_native_idle_controller_is_refused(self):
        validate_handoff_config({"idle_unload_s": 0})
        for config in ({}, {"idle_unload_s": 60}, {"idle_unload_s": False}, {"idle_unload_s": 0.0}):
            with self.assertRaisesRegex(RuntimeError, "independent native idle timer"):
                validate_handoff_config(config)

    def test_slow_read_keeps_earliest_acquisition_timestamp(self):
        import time
        def read():
            time.sleep(1.05)
            return (40, 60, 7800)
        monitor = CapacityMonitor(lambda: (read, lambda: None)).start()
        try:
            self.assertGreaterEqual(time.monotonic() - monitor.snapshot()["sampled_at"], 1.0)
        finally:
            monitor.close()

    def test_low_valid_observation_recovers_without_resetting_owner_guard(self):
        import time
        values = [(1.0, 2.0, 100.0)]
        closed = []
        monitor = CapacityMonitor(lambda: (lambda: values[0], lambda: closed.append(True))).start()
        try:
            first = monitor.snapshot()
            self.assertEqual(first["available_ram_gib"], 1)
            self.assertTrue(first["complete"])
            values[0] = (40.0, 60.0, 7800.0)
            until = time.monotonic() + 2
            while monitor.snapshot()["sampled_at"] == first["sampled_at"] and time.monotonic() < until:
                time.sleep(.01)
            self.assertEqual(monitor.snapshot()["available_ram_gib"], 40)
        finally:
            monitor.close()
        self.assertEqual(closed, [True])

    def test_invalid_sensor_data_never_becomes_complete(self):
        monitor = CapacityMonitor(lambda: (lambda: (float("nan"), 20, 4000), lambda: None))
        with self.assertRaisesRegex(RuntimeError, "Invalid"):
            monitor.start()
        with self.assertRaises(RuntimeError):
            monitor.snapshot()
        with self.assertRaises(RuntimeError):
            monitor.close()

    def test_stale_timestamp_is_not_replaced_with_query_time(self):
        import time
        monitor = CapacityMonitor(lambda: (lambda: (40, 60, 7800), lambda: None)).start()
        try:
            with monitor.lock:
                monitor.row["sampled_at"] = time.monotonic() - 5
            with self.assertRaisesRegex(RuntimeError, "stale"):
                monitor.snapshot()
        finally:
            monitor.close()


if __name__ == "__main__":
    unittest.main()
