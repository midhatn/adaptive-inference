"""Durable-demand controller fixtures; no native process, model or UI."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from adaptive_inference.config import Config
from adaptive_inference.scheduler import Scheduler, AdmissionError
from adaptive_inference.task_store import TaskStore, ReconciliationRequired, OwnershipError
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE


import test_handoff as legacy
from adaptive_inference.handoff import HandoffController, ForegroundPolicy, ToolRequirements


class Clock:
    now = 10.0
    def __call__(self):
        return self.now


class Adapter:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.identity = {"owner_id": "first", "ready": True, "loaded": True}
        self.parked = {"state": "parked", "running": False, "ready": False,
            "loaded": False, "owner_id": None, "previous_owner_id": None,
            "startup_barrier_held": True, "owner_lock_observed_idle": True,
            "backend_port_free": True, "containing_job_empty": True,
            "native_launch_attempted": False, "release": None}
        self.capacity = {"complete": True, "sampled_at": clock(),
            "available_ram_gib": 30, "available_commit_gib": 40,
            "available_vram_mib": 7000}
        self.on_start = self.on_capacity = None

    async def status(self):
        return deepcopy(self.identity)

    async def prepare_parked(self):
        self.calls.append("prepare")
        return deepcopy(self.parked)

    async def fresh_capacity(self):
        self.calls.append("capacity")
        if self.on_capacity:
            await self.on_capacity()
        return {**self.capacity, "sampled_at": self.clock()}

    async def start(self):
        self.calls.append("start")
        if self.on_start:
            return await self.on_start()
        self.identity = {"owner_id": "owner-" + str(self.calls.count("start")),
                         "ready": True, "loaded": True}
        return deepcopy(self.identity)

    async def stop(self, identity):
        self.calls.append(("stop", deepcopy(identity)))
        return {"owner_id": identity["owner_id"], "released": True,
            "cleanup_confirmed": True, "port_free": True,
            "retained_processes": 2, "confirmed_process_exits": 2}


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "tasks.sqlite3")
        self.identity = DemandIdentity("r1", "task1", "trusted-worker", "2026-10-24T12:00:00Z")
        self.store.create("task1", "Retain the original task.", max_attempts=3,
                          metadata={NAMESPACE: self.identity.metadata()})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.claim_context = self.store.claim("task1", expected_revision=self.store.load("task1").revision)
        self.owned = self.claim_context.__enter__()
        self.addCleanup(self.claim_context.__exit__, None, None, None)
        self.clock = Clock()
        self.adapter = Adapter(self.clock)
        self.control, self.scheduler = self.make_controller()
        self.observe()

    def make_controller(self, **changes):
        kwargs = {"demand": self.registry, "idle_grace_s": 2,
            "demand_max_age_s": 1, "restore_requirements": ToolRequirements(8, 10, 2000)}
        kwargs.update(changes)
        control = HandoffController(self.adapter,
            ForegroundPolicy(recovery_s=0, engage_samples=1), clock=self.clock, **kwargs)
        scheduler = Scheduler(Config(queue_timeout_s=2), control)
        control.bind_scheduler(scheduler)
        return control, scheduler

    def observe(self, **changes):
        self.control.observe(legacy.sample(self.clock(), **changes))

    def transition(self, state):
        return self.registry.transition("r1", self.owned, state,
            expected_revision=self.owned.checkpoint.revision,
            updated_at_utc="2026-10-24T12:01:00Z", reason="fixture safe point")

    async def tick(self, seconds=.5, **changes):
        self.clock.now += seconds
        self.observe(**changes)
        await self.control.refresh_demand()
        await self.control.step()

    async def ready(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        await self.control.step()
        self.assertEqual(self.control.state, "ready")

    def stops(self):
        return [call for call in self.adapter.calls if isinstance(call, tuple)]

    async def test_cold_quiet_initialization_has_no_owner_or_invented_release(self):
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.control.state, "parked")
        self.assertIsNone(self.control.identity)
        self.assertFalse(self.control())
        self.assertEqual(self.adapter.calls, ["prepare"])
        self.assertFalse(any("release" in event for event in self.control.events))

    async def test_bootstrap_durable_demand_precedes_provider_or_http_ticket(self):
        await self.ready()
        self.assertIsNone(self.scheduler.active)
        self.assertEqual(self.scheduler.pending, {})
        self.assertEqual(self.adapter.calls, ["prepare", "capacity", "start"])
        self.assertTrue(self.control())
        self.assertEqual(self.owned.checkpoint.state["attempts"], 0)
        self.assertIsNone(self.owned.checkpoint.operation)

    async def test_operation_begins_before_dispatch_ineligible_does_not_deadlock(self):
        await self.ready()
        op = self.owned.begin_operation("generation", expected_revision=self.owned.checkpoint.revision)
        self.assertEqual(await self.control.refresh_demand(), "busy")
        self.assertFalse(self.registry.observe("r1").eligible)
        ticket = await self.scheduler.acquire("background", 1, wait=False)
        await self.tick()
        self.assertEqual(self.stops(), [])
        await self.scheduler.release(ticket)
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.stops(), [])
        self.owned.complete_operation(op.operation["id"], result={"fixture": "completed"},
                                     state=op.state, expected_revision=op.revision)
        self.assertEqual(await self.control.refresh_demand(), "eligible")

    async def test_only_verified_absence_with_no_active_or_pending_parks_after_grace(self):
        await self.ready()
        self.transition("fulfilled")
        await self.control.refresh_demand()
        await self.control.step()
        for _ in range(3):
            await self.tick()
            self.assertEqual(self.stops(), [])
        await self.tick()
        self.assertEqual(self.control.state, "parked")
        self.assertEqual(len(self.stops()), 1)
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.adapter.calls.count("start"), 1)

    async def test_stale_observation_authorizes_neither_wake_nor_idle_release(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        self.clock.now += 2
        self.observe()
        await self.control.step()
        self.assertNotIn("start", self.adapter.calls)
        await self.control.refresh_demand()
        await self.control.step()
        self.transition("paused")
        await self.control.refresh_demand()
        await self.control.step()
        self.clock.now += 3
        self.observe()
        await self.control.step()
        self.assertEqual(self.stops(), [])
        await self.control.refresh_demand()
        await self.control.step()
        self.assertEqual(self.stops(), [])

    async def test_pause_cancel_cannot_acknowledge_or_terminate_active_generation(self):
        await self.ready()
        op = self.owned.begin_operation("generation", expected_revision=self.owned.checkpoint.revision)
        ticket = await self.scheduler.acquire("background", 1, wait=False)
        for intent in ("paused", "cancelled"):
            with self.assertRaises(ReconciliationRequired):
                self.transition(intent)
            await self.tick(3)
            self.assertEqual(self.owned.checkpoint.operation, op.operation)
            self.assertEqual(self.owned.checkpoint.state[NAMESPACE]["state"], "waiting")
            self.assertEqual(self.stops(), [])
            self.assertIs(self.scheduler.active, ticket)
        await self.scheduler.release(ticket)

    async def test_durable_cancel_still_waits_for_independent_active_http_owner(self):
        await self.ready()
        ticket = await self.scheduler.acquire("background", 1, wait=False)
        self.transition("cancelled")
        for _ in range(6):
            await self.tick()
        self.assertIs(self.scheduler.active, ticket)
        self.assertEqual(self.stops(), [])
        await self.scheduler.release(ticket)
        for _ in range(5):
            await self.tick()
        self.assertEqual(self.control.state, "parked")

    async def test_pending_queue_is_not_cancelled_or_used_as_idle_release_permission(self):
        await self.ready()
        self.transition("paused")
        self.observe(cpu=None)  # unknown CPU closes gate without a yield request
        pending = asyncio.create_task(self.scheduler.acquire("normal", 1))
        await asyncio.sleep(.01)
        self.assertEqual(len(self.scheduler.pending), 1)
        for _ in range(6):
            await self.tick(cpu=None)
        self.assertFalse(pending.done())
        self.assertEqual(self.stops(), [])
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(self.scheduler.pending, {})

    async def test_unavailable_checkpoint_is_not_no_demand(self):
        await self.ready()
        self.transition("paused")
        with patch.object(self.store, "load", side_effect=OSError("fixture read denied")):
            for _ in range(6):
                await self.tick()
            self.assertEqual(self.control._demand_state(), "unknown")
            self.assertEqual(self.stops(), [])
        self.assertFalse(self.control.fault)

    async def test_reconciliation_is_not_absence(self):
        await self.ready()
        self.owned.begin_operation("generation", expected_revision=self.owned.checkpoint.revision)
        self.claim_context.__exit__(None, None, None)
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.registry.observe("r1").reason, "reconciliation_required")
        self.assertEqual(self.control._demand_state(), "unknown")
        self.assertEqual(self.stops(), [])

    async def test_revision_rollback_is_unknown_and_observation_polling_has_no_writes(self):
        older = self.owned.checkpoint
        await self.ready()
        before = self.store.history("task1")
        for _ in range(10):
            await self.control.refresh_demand()
        self.assertEqual(self.store.history("task1"), before)
        with patch.object(self.store, "load", return_value=older):
            for _ in range(6):
                await self.tick()
            self.assertEqual(self.control._demand_state(), "unknown")
            self.assertEqual(self.stops(), [])

    async def test_fault_never_authorizes_wake_or_release(self):
        await self.ready()
        self.transition("cancelled")
        self.scheduler.uncertain = True
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.control.state, "fault")
        self.assertEqual(self.stops(), [])
        self.assertEqual(self.adapter.calls.count("start"), 1)

    async def test_cold_proof_requires_every_existing_boundary(self):
        original = deepcopy(self.adapter.parked)
        for change in ({"backend_port_free": False}, {"owner_lock_observed_idle": False},
                       {"startup_barrier_held": False}, {"containing_job_empty": False},
                       {"owner_id": "adopted"}, {"release": {}}, {"native_launch_attempted": True}):
            with self.subTest(change=change):
                self.adapter.parked = {**original, **change}
                control, _ = self.make_controller()
                with self.assertRaises(RuntimeError):
                    await control.initialize(parked=True)
                self.assertEqual(control.state, "fault")
                self.assertIsNone(control.identity)
                self.assertFalse(control())

    async def test_start_failure_latches_without_retry_or_fake_release(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def failure():
            self.assertTrue(any(e.get("restore_requested") for e in self.control.events))
            raise RuntimeError("fixture failed startup")
        self.adapter.on_start = failure
        with self.assertRaises(RuntimeError):
            await self.control.step()
        await self.control.step()
        self.assertEqual(self.adapter.calls.count("start"), 1)
        self.assertEqual(self.control.state, "fault")
        self.assertEqual(self.stops(), [])

    async def test_capacity_shortage_is_parked_then_fresh_clearance_can_wake(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        self.adapter.capacity["available_ram_gib"] = 1
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.assertNotIn("start", self.adapter.calls)
        self.adapter.capacity["available_ram_gib"] = 30
        await self.control.step()
        self.assertEqual(self.control.state, "ready")

    async def test_cancel_during_capacity_read_is_rechecked_before_launch(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def cancelled():
            self.transition("cancelled")
        self.adapter.on_capacity = cancelled
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.assertNotIn("start", self.adapter.calls)

    async def test_cancel_during_start_retains_owner_but_never_opens_admission(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def cancelled():
            self.transition("cancelled")
            return {"owner_id": "new", "ready": True, "loaded": True}
        self.adapter.on_start = cancelled
        await self.control.step()
        self.assertEqual(self.control.identity["owner_id"], "new")
        self.assertEqual(self.control.state, "awaiting_demand")
        with self.assertRaises(AdmissionError):
            await self.scheduler.acquire("background", 1, wait=False)
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.assertEqual(self.stops()[0][1]["owner_id"], "new")

    async def test_unknown_after_start_holds_owner_without_dispatch_or_release(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        fault = patch.object(self.store, "load", side_effect=OSError("fixture missing checkpoint"))
        async def unknown():
            fault.start()
            return {"owner_id": "new", "ready": True, "loaded": True}
        self.adapter.on_start = unknown
        try:
            await self.control.step()
            await self.tick(3)
            self.assertEqual(self.control.state, "awaiting_demand")
            self.assertFalse(self.control())
            self.assertEqual(self.stops(), [])
        finally:
            fault.stop()
        await self.control.refresh_demand()
        await self.control.step()
        self.assertTrue(self.control())

    async def test_prepared_operation_during_start_can_dispatch_after_readiness(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def prepared():
            self.owned.begin_operation("generation", expected_revision=self.owned.checkpoint.revision)
            return {"owner_id": "new", "ready": True, "loaded": True}
        self.adapter.on_start = prepared
        await self.control.step()
        self.assertEqual(self.control._demand_state(), "busy")
        ticket = await self.scheduler.acquire("background", 1, wait=False)
        await self.scheduler.release(ticket)

    async def test_foreground_during_start_closes_gate_then_exact_owner_drains(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def busy():
            self.clock.now += .1
            self.observe(idle=0)
            return {"owner_id": "new", "ready": True, "loaded": True}
        self.adapter.on_start = busy
        await self.control.step()
        self.assertFalse(self.control())
        await self.control.step()
        self.assertEqual(self.control.state, "parked")
        self.assertEqual(self.stops()[0][1]["owner_id"], "new")

    async def test_previous_owner_identity_cannot_be_adopted_on_first_cold_start(self):
        self.adapter.parked["previous_owner_id"] = "previous"
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.refresh_demand()
        async def same():
            return {"owner_id": "previous", "ready": True, "loaded": True}
        self.adapter.on_start = same
        with self.assertRaises(RuntimeError):
            await self.control.step()
        self.assertEqual(self.control.state, "fault")
        self.assertFalse(self.control())

    async def test_closed_task_owner_cannot_publish_cancel_acknowledgement(self):
        await self.ready()
        before = self.store.load("task1")
        self.claim_context.__exit__(None, None, None)
        with self.assertRaises(OwnershipError):
            self.transition("cancelled")
        self.assertEqual(self.store.load("task1").state[NAMESPACE], before.state[NAMESPACE])
        await self.control.refresh_demand()
        self.assertEqual(self.control.status()["demand"]["intents"][0]["state"], "waiting")

    async def test_unknown_or_unobserved_demand_never_wakes_cold_backend(self):
        self.transition("waiting")
        await self.control.initialize(parked=True)
        await self.control.step()
        self.assertNotIn("start", self.adapter.calls)
        with patch.object(self.store, "load", side_effect=OSError("fixture read failure")):
            await self.control.refresh_demand()
            await self.control.step()
        self.assertNotIn("start", self.adapter.calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
