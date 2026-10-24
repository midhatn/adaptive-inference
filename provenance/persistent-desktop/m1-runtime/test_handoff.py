import asyncio
from copy import deepcopy
import time
import unittest

from adaptive_inference.config import Config
from adaptive_inference.handoff import ForegroundPolicy, HandoffController, ToolRequirements
from adaptive_inference.scheduler import Scheduler, AdmissionError


def sample(stamp, *, cpu=0, idle=120, ram=20, pid=7, creation=100):
    return {"monotonic_s": stamp, "foreground": {"pid": pid, "creation_time_100ns": creation,
            "valid": True, "cpu_cores_used": cpu}, "session_input_idle_s": idle,
            "host": {"ram_available_gib": ram, "commit_available_gib": 30}, "errors": []}


class ForegroundTests(unittest.TestCase):
    def test_two_live_samples_engage_and_fresh_dwell_recovers(self):
        policy = ForegroundPolicy(recovery_s=1, max_age_s=1)
        self.assertFalse(policy.observe(sample(1, idle=0), 1))
        self.assertFalse(policy.yield_requested)
        self.assertFalse(policy.observe(sample(1.5, idle=.5), 1.5))
        self.assertTrue(policy.yield_requested)
        for stamp in (2, 2.5):
            self.assertFalse(policy.observe(sample(stamp), stamp))
        self.assertTrue(policy.observe(sample(3), 3))
        self.assertFalse(policy.yield_requested)

    def test_replayed_sample_never_earns_dwell_or_second_engage_sample(self):
        policy = ForegroundPolicy(recovery_s=1, max_age_s=2)
        busy = sample(1, idle=0)
        policy.observe(busy, 1)
        policy.observe(busy, 1.2)
        self.assertFalse(policy.yield_requested)
        clear = sample(2)
        policy.observe(clear, 2)
        self.assertFalse(policy.observe(clear, 3))
        self.assertTrue(policy.observe(sample(3), 3))

    def test_recent_input_and_cpu_activity_are_independent(self):
        for kwargs in ({"idle": 0, "cpu": 0}, {"idle": 120, "cpu": .3}):
            with self.subTest(kwargs=kwargs):
                policy = ForegroundPolicy(engage_samples=1)
                policy.observe(sample(1, **kwargs), 1)
                self.assertTrue(policy.yield_requested)
        policy = ForegroundPolicy(recovery_s=0)
        self.assertTrue(policy.observe(sample(1), 1))
        self.assertFalse(policy.observe(sample(1.2, cpu=.1), 1.2))
        self.assertEqual(policy.reason, "foreground_recovery_margin")

    def test_input_without_cpu_first_sample_still_protects_user(self):
        policy = ForegroundPolicy(engage_samples=1)
        self.assertFalse(policy.observe(sample(1, cpu=None, idle=0), 1))
        self.assertTrue(policy.yield_requested)
        self.assertFalse(policy.observe(sample(1.5, cpu=None), 1.5))

    def test_identity_ignore_needs_both_pid_and_creation(self):
        policy = ForegroundPolicy(ignored_identities=[(7, 100)], recovery_s=0, engage_samples=1)
        self.assertTrue(policy.observe(sample(1, idle=0, cpu=3), 1))
        self.assertFalse(policy.observe(sample(1.2, idle=0, cpu=3, creation=101), 1.2))
        self.assertTrue(policy.yield_requested)

    def test_invalid_stale_conflicting_and_clock_regressed_samples_close_gate(self):
        for invalid, now in ((None, 1.2), (sample(0), 2), (sample(2), 1.2),
                             (sample(1, ram=19), 1.2), (sample(1.2, ram=float("nan")), 1.2),
                             (sample(1.2, cpu=-1), 1.2), (sample(1.2, pid=0), 1.2)):
            with self.subTest(invalid=invalid):
                policy = ForegroundPolicy(recovery_s=0)
                self.assertTrue(policy.observe(sample(1), 1))
                self.assertFalse(policy.observe(invalid, now))
        policy = ForegroundPolicy(recovery_s=0)
        policy.observe(sample(1), 1)
        self.assertFalse(policy.observe(sample(.5), .5))

    def test_host_pressure_is_immediate_even_ignored_foreground(self):
        policy = ForegroundPolicy(ignored_identities=[(7, 100)])
        policy.observe(sample(1, ram=1), 1)
        self.assertTrue(policy.yield_requested)
        self.assertEqual(policy.reason, "host_memory_pressure")

    def test_sample_gap_restarts_recovery(self):
        policy = ForegroundPolicy(recovery_s=1, max_age_s=.5)
        policy.observe(sample(1), 1)
        self.assertFalse(policy.observe(sample(3), 3))
        policy.observe(sample(3.5), 3.5)
        self.assertTrue(policy.observe(sample(4), 4))


class Adapter:
    def __init__(self):
        self.calls = []
        self.identity = {"owner_id": "first", "ready": True, "loaded": True}
        self.on_stop = self.on_start = self.on_capacity = None

    async def status(self):
        return deepcopy(self.identity)

    async def stop(self, identity):
        self.calls.append(("stop", deepcopy(identity)))
        if self.on_stop:
            return await self.on_stop(identity)
        return {"owner_id": identity["owner_id"], "released": True, "cleanup_confirmed": True,
                "retained_processes": 2, "confirmed_process_exits": 2, "port_free": True}

    async def start(self):
        self.calls.append(("start",))
        if self.on_start:
            return await self.on_start()
        self.identity = {"owner_id": "next", "ready": True, "loaded": True}
        return deepcopy(self.identity)

    async def fresh_capacity(self):
        if self.on_capacity:
            return await self.on_capacity()
        return {"complete": True, "sampled_at": time.perf_counter(), "available_ram_gib": 30,
                "available_commit_gib": 40, "available_vram_mib": 7000}


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = Adapter()
        self.control = HandoffController(self.adapter, ForegroundPolicy(recovery_s=0, engage_samples=1), clock=time.perf_counter)
        self.scheduler = Scheduler(Config(queue_timeout_s=1), self.control)
        self.control.bind_scheduler(self.scheduler)
        await self.control.initialize()
        self.observe()

    def observe(self, **kwargs):
        self.control.observe(sample(time.perf_counter(), **kwargs))

    async def park(self):
        self.observe(idle=0)
        await self.control.step()
        self.assertEqual(self.control.state, "parked")

    async def test_active_owner_drains_without_new_pending_dispatch(self):
        active = await self.scheduler.acquire("background", 1)
        pending = asyncio.create_task(self.scheduler.acquire("normal", 1))
        await asyncio.sleep(.01)
        self.observe(idle=0)
        await self.control.step()
        self.assertEqual(self.control.state, "draining")
        self.assertEqual(self.adapter.calls, [])
        await self.scheduler.release(active)
        await asyncio.sleep(.02)
        self.assertFalse(pending.done())
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.observe()
        await self.control.step()
        self.assertEqual(self.control.identity["owner_id"], "next")
        ticket = await pending
        await self.scheduler.release(ticket)
        self.assertEqual([row[0] for row in self.adapter.calls], ["stop", "start"])

    async def test_unknown_backend_completion_never_becomes_release_authority(self):
        ticket = await self.scheduler.acquire("background", 1)
        await self.scheduler.release(ticket, uncertain=True)
        self.observe(idle=0)
        await self.control.step()
        self.assertEqual(self.control.state, "fault")
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse(self.control())

    async def test_release_proof_requires_identity_all_exits_and_free_listener(self):
        for difference in ({"owner_id": "other"}, {"confirmed_process_exits": 1},
                           {"port_free": False}, {"retained_processes": True}, {"cleanup_confirmed": False}):
            with self.subTest(difference=difference):
                adapter = Adapter()
                controller = HandoffController(adapter, ForegroundPolicy(engage_samples=1), clock=time.perf_counter)
                scheduler = Scheduler(Config(), controller)
                controller.bind_scheduler(scheduler)
                await controller.initialize()
                async def bad(identity):
                    return {"owner_id": "first", "released": True, "cleanup_confirmed": True,
                            "retained_processes": 2, "confirmed_process_exits": 2, "port_free": True, **difference}
                adapter.on_stop = bad
                controller.observe(sample(time.perf_counter(), idle=0))
                with self.assertRaises(RuntimeError):
                    await controller.step()
                self.assertFalse(controller())
                self.assertEqual(controller.state, "fault")

    async def test_demand_during_start_never_reopens_admission(self):
        await self.park()
        self.observe()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def start():
            entered.set()
            await asyncio.wait_for(finish.wait(), 1)
            return {"owner_id": "new", "ready": True, "loaded": True}
        self.adapter.on_start = start
        operation = asyncio.create_task(self.control.step())
        await asyncio.wait_for(entered.wait(), 1)
        self.observe(idle=0)
        finish.set()
        await operation
        self.assertFalse(self.control())
        await self.control.step()
        self.assertEqual(self.control.state, "parked")

    async def test_cancelled_native_transition_latches_fault(self):
        entered = asyncio.Event()
        async def stop(identity):
            entered.set()
            await asyncio.Event().wait()
        self.adapter.on_stop = stop
        self.observe(idle=0)
        operation = asyncio.create_task(self.control.step())
        await asyncio.wait_for(entered.wait(), 1)
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        self.assertEqual(self.control.state, "fault")
        self.assertFalse(self.control())

    async def test_tool_requires_release_capacity_and_confirmed_tool_exit(self):
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(ram_gib=10, vram_mib=6000)))
        await asyncio.sleep(.01)
        self.assertFalse(self.control())
        await self.control.step()
        grant = await pending
        self.assertTrue(grant.granted)
        self.assertEqual(self.control.state, "parked")
        with self.assertRaises(RuntimeError):
            await self.control.acquire_tool(ToolRequirements())
        await self.control.step()
        self.assertEqual([row[0] for row in self.adapter.calls], ["stop"])
        self.observe(idle=0)
        self.assertTrue(grant.interruption.is_set())
        self.control.complete_tool(grant, owned_processes_exited=True)
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.observe()
        await self.control.step()
        self.assertTrue(self.control())

    async def test_tool_capacity_is_fresh_and_rechecked_after_await(self):
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(vram_mib=6000), timeout_s=.08))
        await asyncio.sleep(.01)
        async def capacity():
            self.observe(idle=0)
            return {"complete": True, "sampled_at": time.perf_counter(), "available_ram_gib": 30,
                    "available_commit_gib": 40, "available_vram_mib": 7000}
        self.adapter.on_capacity = capacity
        await self.control.step()
        self.assertFalse(self.control.tool.granted)
        with self.assertRaises(TimeoutError):
            await pending
        self.assertIsNone(self.control.tool)
        self.assertEqual(self.control.state, "parked")

    async def test_stale_capacity_and_insufficient_vram_cannot_grant(self):
        for changes in ({"sampled_at": 0}, {"available_vram_mib": 5999}, {"complete": False},
                        {"available_ram_gib": float("inf")}):
            with self.subTest(changes=changes):
                pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(vram_mib=6000), timeout_s=.05))
                await asyncio.sleep(.005)
                async def capacity():
                    return {"complete": True, "sampled_at": time.perf_counter(), "available_ram_gib": 30,
                            "available_commit_gib": 40, "available_vram_mib": 7000, **changes}
                self.adapter.on_capacity = capacity
                await self.control.step()
                with self.assertRaises(TimeoutError):
                    await pending
                self.assertEqual(self.control.state, "parked")

    async def test_failed_tool_exit_does_not_restart_backend(self):
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements()))
        await asyncio.sleep(.01)
        await self.control.step()
        grant = await pending
        with self.assertRaises(RuntimeError):
            self.control.complete_tool(grant, owned_processes_exited=False)
        await self.control.step()
        self.assertEqual(self.control.state, "fault")
        self.assertEqual([row[0] for row in self.adapter.calls], ["stop"])

    async def test_ready_gate_expires_if_sampler_stops(self):
        self.assertTrue(self.control())
        self.control.policy.last["monotonic_s"] -= 2
        self.assertFalse(self.control())

    async def blocked_capacity(self, *, timeout_s=1):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def capacity():
            entered.set()
            await asyncio.wait_for(finish.wait(), 1)
            return {"complete": True, "sampled_at": self.control.clock(),
                    "available_ram_gib": 30, "available_commit_gib": 40,
                    "available_vram_mib": 7000}
        self.adapter.on_capacity = capacity
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(), timeout_s=timeout_s))
        await asyncio.sleep(0)
        operation = asyncio.create_task(self.control.step())
        await asyncio.wait_for(entered.wait(), 1)
        return pending, operation, finish

    async def test_capacity_observation_cannot_grant_cancelled_or_replacement_owner(self):
        pending, operation, finish = await self.blocked_capacity()
        original = self.control.tool
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertIsNone(self.control.tool)
        replacement = asyncio.create_task(self.control.acquire_tool(ToolRequirements(vram_mib=6000)))
        await asyncio.sleep(0)
        replacement_grant = self.control.tool
        finish.set()
        await asyncio.wait_for(operation, 1)
        self.assertIsNone(self.control.fault)
        self.assertFalse(original.granted)
        self.assertFalse(replacement_grant.granted)
        # The replacement needs its own capacity observation.
        await self.control.step()
        self.assertIs(await asyncio.wait_for(replacement, 1), replacement_grant)
        self.control.complete_tool(replacement_grant, owned_processes_exited=True)

    async def test_cancelled_capacity_without_replacement_is_not_a_native_fault(self):
        pending, operation, finish = await self.blocked_capacity()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        finish.set()
        await asyncio.wait_for(operation, 1)
        self.assertIsNone(self.control.fault)
        self.assertIsNone(self.control.tool)
        self.assertEqual(self.control.state, "parked")

    async def test_gateway_close_or_uncertainty_during_capacity_refuses_grant(self):
        for flag in ("closing", "uncertain"):
            with self.subTest(flag=flag):
                await self.asyncSetUp()
                pending, operation, finish = await self.blocked_capacity()
                grant = self.control.tool
                setattr(self.scheduler, flag, True)
                finish.set()
                await asyncio.wait_for(operation, 1)
                with self.assertRaises(RuntimeError):
                    await asyncio.wait_for(pending, 1)
                self.assertFalse(grant.granted)
                self.assertEqual(self.control.state, "fault" if flag == "uncertain" else "parked")
                self.assertEqual(self.control.fault, "gateway_completion_unreconciled" if flag == "uncertain" else None)
                self.assertFalse(self.control())

    async def test_deadline_during_capacity_refuses_grant(self):
        now = [time.perf_counter()]
        self.control.clock = lambda: now[0]
        self.control.observe(sample(now[0]))
        pending, operation, finish = await self.blocked_capacity(timeout_s=.1)
        grant = self.control.tool
        now[0] = grant.deadline  # exact boundary, not a timing-dependent sleep
        self.control.observe(sample(now[0]))
        finish.set()
        await asyncio.wait_for(operation, 1)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(pending, 1)
        self.assertFalse(grant.granted)
        self.assertIsNone(self.control.fault)
        self.assertIsNone(self.control.tool)

    async def test_deadline_between_grant_and_delivery_refuses_execution(self):
        now = [time.perf_counter()]
        self.control.clock = lambda: now[0]
        self.control.observe(sample(now[0]))
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(), timeout_s=.1))
        await asyncio.sleep(0)
        async def capacity():
            return {"complete": True, "sampled_at": now[0], "available_ram_gib": 30,
                    "available_commit_gib": 40, "available_vram_mib": 7000}
        self.adapter.on_capacity = capacity
        await self.control.step()
        grant = self.control.tool
        self.assertTrue(grant.granted)
        now[0] = grant.deadline
        self.control.observe(sample(now[0]))
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(pending, 1)
        self.assertEqual(self.control.state, "fault")
        self.assertTrue(grant.interruption.is_set())
        self.assertFalse(self.control())

    async def test_demand_between_grant_and_delivery_refuses_execution(self):
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements()))
        await asyncio.sleep(0)
        await self.control.step()
        grant = self.control.tool
        self.assertTrue(grant.granted)
        self.observe(idle=0)
        with self.assertRaisesRegex(RuntimeError, "interrupted before delivery"):
            await asyncio.wait_for(pending, 1)
        self.assertTrue(grant.interruption.is_set())
        self.assertFalse(self.control())

    async def test_gateway_close_or_uncertainty_during_stop_never_restarts(self):
        for flag in ("closing", "uncertain"):
            with self.subTest(flag=flag):
                await self.asyncSetUp()
                entered, finish = asyncio.Event(), asyncio.Event()
                async def stop(identity):
                    entered.set()
                    await asyncio.wait_for(finish.wait(), 1)
                    return {"owner_id": identity["owner_id"], "released": True,
                            "cleanup_confirmed": True, "retained_processes": 2,
                            "confirmed_process_exits": 2, "port_free": True}
                self.adapter.on_stop = stop
                self.observe(idle=0)
                operation = asyncio.create_task(self.control.step())
                await asyncio.wait_for(entered.wait(), 1)
                setattr(self.scheduler, flag, True)
                self.observe()
                finish.set()
                await asyncio.wait_for(operation, 1)
                self.assertEqual(self.control.state, "fault" if flag == "uncertain" else "parked")
                self.assertEqual(self.control.fault, "gateway_completion_unreconciled" if flag == "uncertain" else None)
                self.assertEqual([r[0] for r in self.adapter.calls], ["stop"])

    async def test_gateway_close_or_uncertainty_during_start_keeps_gate_closed(self):
        for flag in ("closing", "uncertain"):
            with self.subTest(flag=flag):
                await self.asyncSetUp()
                await self.park()
                self.observe()
                entered, finish = asyncio.Event(), asyncio.Event()
                async def start():
                    entered.set()
                    await asyncio.wait_for(finish.wait(), 1)
                    return {"owner_id": "new", "ready": True, "loaded": True}
                self.adapter.on_start = start
                operation = asyncio.create_task(self.control.step())
                await asyncio.wait_for(entered.wait(), 1)
                setattr(self.scheduler, flag, True)
                finish.set()
                await asyncio.wait_for(operation, 1)
                self.assertEqual(self.control.state, "fault" if flag == "uncertain" else "restoring")
                self.assertEqual(self.control.fault, "gateway_completion_unreconciled" if flag == "uncertain" else None)
                self.assertEqual(self.control.identity["owner_id"], "new")
                self.assertFalse(self.control())

    async def test_gateway_close_during_initial_status_keeps_gate_closed(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        adapter = Adapter()
        controller = HandoffController(adapter, clock=time.perf_counter)
        scheduler = Scheduler(Config(), controller)
        controller.bind_scheduler(scheduler)
        async def status():
            entered.set()
            await asyncio.wait_for(finish.wait(), 1)
            return {"owner_id": "initial", "ready": True, "loaded": True}
        adapter.status = status
        initialization = asyncio.create_task(controller.initialize())
        await asyncio.wait_for(entered.wait(), 1)
        await scheduler.close()
        finish.set()
        await asyncio.wait_for(initialization, 1)
        self.assertEqual(controller.state, "uninitialized")
        self.assertIsNone(controller.fault)
        self.assertEqual(controller.identity["owner_id"], "initial")
        self.assertFalse(controller())

    async def test_orderly_close_awaits_release_proof_and_never_restores(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        proof = {"owner_id": "first", "released": True, "cleanup_confirmed": True,
                 "retained_processes": 2, "confirmed_process_exits": 2, "port_free": True}
        async def stop(identity):
            self.assertEqual(identity, self.control.identity)
            entered.set()
            await asyncio.wait_for(finish.wait(), 1)
            return deepcopy(proof)
        self.adapter.on_stop = stop
        self.observe(idle=0)
        operation = asyncio.create_task(self.control.step())
        await asyncio.wait_for(entered.wait(), 1)
        await self.scheduler.close()
        self.observe()  # Recovery demand must not start a new owner on shutdown.
        self.assertEqual(self.control.state, "releasing")
        self.assertIsNone(self.control.fault)
        self.assertFalse(any("release" in row for row in self.control.events))
        self.assertFalse(operation.done())
        self.assertFalse(self.control())
        with self.assertRaises(AdmissionError):
            await self.scheduler.acquire("normal", 1, wait=False)
        finish.set()
        await asyncio.wait_for(operation, 1)
        self.assertEqual(self.control.state, "parked")
        self.assertIsNone(self.control.fault)
        self.assertEqual([row["release"] for row in self.control.events if "release" in row], [proof])
        self.assertEqual(self.control.identity["owner_id"], "first")
        await self.control.step()
        await self.control.step()
        with self.assertRaises(RuntimeError):
            await self.control.acquire_tool(ToolRequirements())
        self.assertEqual([row[0] for row in self.adapter.calls], ["stop"])
        self.assertIsNone(self.control.tool)
        self.assertIsNone(self.control.fault)

    async def test_orderly_close_retains_active_request_until_its_acknowledgement(self):
        ticket = await self.scheduler.acquire("background", 1)
        pending = asyncio.create_task(self.scheduler.acquire("normal", 1))
        await asyncio.sleep(0)
        self.assertEqual(len(self.scheduler.pending), 1)
        self.observe(idle=0)
        await self.control.step()
        self.assertEqual(self.control.state, "draining")
        await self.scheduler.close()
        with self.assertRaises(AdmissionError):
            await asyncio.wait_for(pending, 1)
        await self.control.step()
        self.assertIs(self.scheduler.active, ticket)
        self.assertEqual(self.scheduler.completed, 0)
        self.assertEqual(self.adapter.calls, [])
        self.assertIsNone(self.control.fault)
        await self.scheduler.release(ticket)
        await self.control.step()
        self.assertIsNone(self.scheduler.active)
        self.assertEqual(self.scheduler.completed, 1)
        self.assertFalse(self.scheduler.uncertain)
        self.assertEqual(self.adapter.calls, [])  # Host owns final native cleanup.
        self.assertIsNone(self.control.fault)
        self.assertFalse(self.control())

    async def test_closing_cannot_mask_uncertainty_after_verified_release(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def stop(identity):
            entered.set()
            await asyncio.wait_for(finish.wait(), 1)
            return {"owner_id": identity["owner_id"], "released": True, "cleanup_confirmed": True,
                    "retained_processes": 2, "confirmed_process_exits": 2, "port_free": True}
        self.adapter.on_stop = stop
        self.observe(idle=0)
        operation = asyncio.create_task(self.control.step())
        await asyncio.wait_for(entered.wait(), 1)
        await self.scheduler.close()
        self.scheduler.uncertain = True
        self.observe()
        finish.set()
        await asyncio.wait_for(operation, 1)
        self.assertEqual(self.control.state, "fault")
        self.assertEqual(self.control.fault, "gateway_completion_unreconciled")
        self.assertEqual(len([row for row in self.control.events if "release" in row]), 1)
        await self.control.step()
        self.assertEqual([row[0] for row in self.adapter.calls], ["stop"])
        self.assertFalse(self.control())

    async def test_closing_does_not_clear_an_existing_fault(self):
        self.control._fail("prior_unresolved_transition")
        await self.scheduler.close()
        self.assertFalse(self.control._gateway_open())
        self.assertEqual(self.control.fault, "prior_unresolved_transition")
        self.assertEqual(self.control.state, "fault")
        self.assertEqual(self.adapter.calls, [])

    async def test_missing_scheduler_remains_unreconciled(self):
        self.control.scheduler = None
        self.assertFalse(self.control._gateway_open())
        self.assertEqual(self.control.fault, "gateway_completion_unreconciled")
        self.assertEqual(self.control.state, "fault")

    async def test_cancellation_after_grant_keeps_ownership_closed(self):
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements()))
        await asyncio.sleep(0)
        await self.control.step()
        grant = self.control.tool
        self.assertTrue(grant.granted)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertIs(self.control.tool, grant)
        self.assertTrue(grant.interruption.is_set())
        self.assertEqual(self.control.state, "fault")
        self.assertFalse(self.control())

    async def test_capacity_ages_before_delivery_despite_fresh_activity(self):
        now = [time.perf_counter()]
        self.control.clock = lambda: now[0]
        self.control.observe(sample(now[0]))
        pending = asyncio.create_task(self.control.acquire_tool(ToolRequirements(), timeout_s=10))
        await asyncio.sleep(0)
        async def capacity():
            return {"complete": True, "sampled_at": now[0], "available_ram_gib": 30,
                    "available_commit_gib": 40, "available_vram_mib": 7000}
        self.adapter.on_capacity = capacity
        await self.control.step()
        grant = self.control.tool
        self.assertTrue(grant.granted)
        now[0] += self.control.policy.max_age_s + .01
        self.control.observe(sample(now[0]))
        self.assertTrue(self.control.policy.allowed)
        self.assertTrue(self.control.policy.fresh(now[0]))
        with self.assertRaisesRegex(RuntimeError, "capacity expired before delivery"):
            await asyncio.wait_for(pending, 1)
        self.assertEqual(self.control.state, "fault")
        self.assertTrue(grant.interruption.is_set())
        self.assertFalse(self.control())


if __name__ == "__main__":
    unittest.main()
