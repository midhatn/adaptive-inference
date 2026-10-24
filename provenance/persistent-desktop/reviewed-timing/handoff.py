"""Cooperative resource handoff at an acknowledged inference boundary.

The controller never stops an active gateway owner, changes model settings, or
replays a tool. A native adapter must enforce process identity, verified exits,
and exclusion of other cooperating launchers. Capacity is observed, not reserved
by the OS. A host receiving a tool interruption must stop its own tool safely.
"""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import inspect
import math
import time
import uuid


def number(value, *, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


class ForegroundPolicy:
    """Explicit conservative desktop policy using observations, never prompts.

    Recent input protects an actual foreground process even when it uses little
    CPU. Sustained foreground CPU protects work without input. Separate engage
    and recovery thresholds prevent repeated load/unload transitions. The dwell
    principle reuses this project's HeadroomPolicy contract and its attributed
    Strata/medking82 lineage; this foreground policy is original implementation.
    """
    def __init__(self, *, input_hold_s=60, cpu_engage_cores=.15,
                 cpu_release_cores=.05, min_available_gib=4,
                 recovery_s=5, max_age_s=1, engage_samples=2,
                 ignored_identities=()):
        for value in (input_hold_s, cpu_engage_cores, cpu_release_cores,
                      min_available_gib, recovery_s, max_age_s):
            if not number(value) or value > 3600:
                raise ValueError("Invalid foreground policy bound")
        if (max_age_s == 0 or cpu_release_cores > cpu_engage_cores
                or type(engage_samples) is not int or not 1 <= engage_samples <= 100):
            raise ValueError("Invalid foreground policy thresholds")
        self.input_hold_s, self.cpu_engage_cores = input_hold_s, cpu_engage_cores
        self.cpu_release_cores, self.min_available_gib = cpu_release_cores, min_available_gib
        self.recovery_s, self.max_age_s, self.engage_samples = recovery_s, max_age_s, engage_samples
        self.ignored = frozenset(tuple(identity) for identity in ignored_identities)
        if any(len(identity) != 2 or any(type(v) is not int or v <= 0 for v in identity)
               for identity in self.ignored):
            raise ValueError("Ignored foreground identities need PID and creation time")
        self.allowed = False
        self.yield_requested = False
        self.reason = "awaiting_activity_sample"
        self.last = None
        self.last_now = None
        self.clear_since = None
        self.busy_samples = 0

    def _invalid(self, reason):
        self.allowed = False
        self.clear_since = None
        self.busy_samples = 0
        self.reason = reason
        return False

    def observe(self, sample, now):
        if not number(now) or self.last_now is not None and now < self.last_now:
            return self._invalid("activity_clock_regressed")
        self.last_now = now
        if not isinstance(sample, dict) or sample.get("errors"):
            return self._invalid("activity_unavailable")
        stamp = sample.get("monotonic_s")
        if not number(stamp) or not 0 <= now - stamp <= self.max_age_s:
            return self._invalid("activity_stale")
        if self.last is not None:
            previous = self.last["monotonic_s"]
            if stamp < previous:
                return self._invalid("activity_regressed")
            if stamp == previous:
                if sample != self.last:
                    return self._invalid("activity_conflict")
                return self.allowed
            if stamp - previous > self.max_age_s:
                self._invalid("activity_gap")
        foreground, host = sample.get("foreground", {}), sample.get("host", {})
        if not isinstance(foreground, dict) or not isinstance(host, dict):
            return self._invalid("activity_unavailable")
        identity = foreground.get("pid"), foreground.get("creation_time_100ns")
        idle = sample.get("session_input_idle_s")
        cpu = foreground.get("cpu_cores_used")
        ram, commit = host.get("ram_available_gib"), host.get("commit_available_gib")
        if (foreground.get("valid") is not True
                or any(type(v) is not int or v <= 0 for v in identity)
                or not all(number(v) for v in (idle, ram, commit))):
            return self._invalid("activity_unavailable")
        ignored = identity in self.ignored
        recent = not ignored and idle <= self.input_hold_s
        if cpu is not None and not number(cpu):
            return self._invalid("activity_unavailable")
        if cpu is None and not recent and not ignored:
            return self._invalid("activity_cpu_warming")
        self.last = deepcopy(sample)
        pressure = min(ram, commit) < self.min_available_gib
        busy = recent or not ignored and cpu is not None and cpu >= self.cpu_engage_cores
        clear = ignored or not recent and cpu is not None and cpu <= self.cpu_release_cores
        if pressure or busy:
            self.allowed = False
            self.clear_since = None
            self.busy_samples += 1
            self.reason = "host_memory_pressure" if pressure else "foreground_activity"
            if pressure or self.busy_samples >= self.engage_samples:
                self.yield_requested = True
            return False
        self.busy_samples = 0
        if not clear:
            self.allowed = False
            self.clear_since = None
            self.reason = "foreground_recovery_margin"
            return False
        if self.clear_since is None:
            self.clear_since = stamp
        self.allowed = stamp - self.clear_since >= self.recovery_s
        self.reason = "foreground_clear" if self.allowed else "foreground_recovery_dwell"
        if self.allowed:
            self.yield_requested = False
        return self.allowed

    def fresh(self, now):
        return (self.last is not None and number(now)
                and 0 <= now - self.last["monotonic_s"] <= self.max_age_s)


@dataclass(frozen=True)
class ToolRequirements:
    ram_gib: float = 0
    commit_gib: float = 0
    vram_mib: float = 0

    def __post_init__(self):
        if not all(number(v) and v <= 1048576 for v in (self.ram_gib, self.commit_gib, self.vram_mib)):
            raise ValueError("Tool capacity requirements must be finite nonnegative numbers")


@dataclass
class ToolGrant:
    token: str
    requirements: ToolRequirements
    deadline: float
    interruption: asyncio.Event = field(default_factory=asyncio.Event)
    capacity: dict | None = None
    granted: bool = False


class HandoffController:
    """One in-process host coordinates one gateway and an identity-safe adapter.

    Call observe from a continuous sampler independently of step, so pressure
    closes admission even while a native start/stop is awaiting acknowledgement.
    Neither a timeout nor an exception authorizes a different actor to restart
    the backend or replay a tool; both latch a closed fault state.
    """
    def __init__(self, adapter, policy=None, *, clock=time.monotonic,
                 demand=None, idle_grace_s=30, demand_max_age_s=1,
                 restore_requirements=None, on_verified_owner=None):
        if on_verified_owner is not None and (not callable(on_verified_owner)
                or inspect.iscoroutinefunction(on_verified_owner)):
            raise TypeError("Verified-owner callback must be synchronous")
        self.on_verified_owner = on_verified_owner
        self.adapter, self.policy, self.clock = adapter, policy or ForegroundPolicy(), clock
        self.scheduler = None
        self.identity = None
        self.state = "uninitialized"
        self.fault = None
        self.tool = None
        self.events = deque(maxlen=256)
        self.lock = asyncio.Lock()
        # Private opt-in M2 composition. Default M1 admission and handoff stay
        # unchanged. A trusted registry is read-only here; only its actual
        # OwnedTask can checkpoint pause/cancel intent at a safe point.
        if demand is not None:
            from adaptive_inference.demand import DemandRegistry
            if type(demand) is not DemandRegistry:
                raise TypeError("Demand must be the trusted durable registry")
            if not isinstance(restore_requirements, ToolRequirements):
                raise ValueError("Demand mode needs explicit model headroom floors")
        if (not number(idle_grace_s) or idle_grace_s > 3600
                or not number(demand_max_age_s, minimum=.001) or demand_max_age_s > 60):
            raise ValueError("Demand observation and idle grace need bounded durations")
        self.demand = demand
        self.idle_grace_s, self.demand_max_age_s = idle_grace_s, demand_max_age_s
        self.restore_requirements = restore_requirements
        self._demand_rows = ()
        self._demand_stamp = None
        self._demand_valid = False
        self._demand_revisions = {}
        self._demand_lock = asyncio.Lock()
        self._idle_since = None
        self._previous_owner_id = None

    async def refresh_demand(self):
        """Trusted host polling, independent of step/start and HTTP tickets.

        Age starts before the read, not after it. No externally supplied
        observation can be injected. Reads never claim ownership or acknowledge
        a cancellation request. A failed/slow/reversed read earns no permission.
        """
        if self.demand is None:
            raise RuntimeError("Demand mode is not configured")
        async with self._demand_lock:
            now = self.clock()
            if self._demand_state() != "absent":
                self._idle_since = None
            self._demand_stamp = None
            self._demand_valid = False
            try:
                rows = await asyncio.to_thread(self.demand.observations)
                keys = set(self.demand._registered)
                valid = len(rows) == len(keys) and {r.registration_id for r in rows} == keys
                for row in rows:
                    previous = self._demand_revisions.get(row.registration_id)
                    if (type(row.revision) is not int or row.revision < 0
                            or previous is not None and row.revision < previous):
                        valid = False
                    elif row.reason != "unavailable_or_invalid_checkpoint":
                        self._demand_revisions[row.registration_id] = row.revision
                self._demand_rows = tuple(rows)
                self._demand_stamp = now
                self._demand_valid = valid
            except Exception:
                self._demand_rows = ()
            if self._demand_state() != "absent":
                self._idle_since = None
            return self._demand_state()

    def _demand_state(self):
        if self.demand is None:
            return "disabled"
        if (not self._demand_valid or not number(self._demand_stamp)
                or not number(self.clock())
                or not 0 <= self.clock() - self._demand_stamp <= self.demand_max_age_s):
            return "unknown"
        absent = {"no_demand", "demand_paused", "demand_cancelled",
                  "demand_fulfilled", "task_terminal"}
        reasons = {row.reason for row in self._demand_rows}
        if not reasons <= absent | {"safe_task_demand", "operation_inflight"}:
            return "unknown"
        if any(row.eligible is True and row.reason == "safe_task_demand"
               for row in self._demand_rows):
            return "eligible"
        if "operation_inflight" in reasons:
            return "busy"
        return "absent" if reasons <= absent else "unknown"

    def _idle_release_requested(self):
        # Ineligible is not absent. Even durable cancellation cannot preempt an
        # active dispatch, discard a pending ticket, or reconcile an operation.
        if (self.demand is None or self._demand_state() != "absent"
                or self.scheduler.active is not None or self.scheduler.pending
                or self.tool is not None):
            self._idle_since = None
            return False
        now = self.clock()
        if self._idle_since is None or now < self._idle_since:
            self._idle_since = now
        return now - self._idle_since >= self.idle_grace_s

    def bind_scheduler(self, scheduler):
        if self.scheduler is not None or scheduler.capacity is not self:
            raise ValueError("Bind exactly the gateway scheduler using this admission gate")
        self.scheduler = scheduler

    def _state(self, state):
        if state != self.state:
            self.events.append({"at": self.clock(), "from": self.state, "to": state})
            self.state = state

    def _fail(self, reason):
        self.fault = reason
        self._state("fault")
        if self.tool is not None:
            self.tool.interruption.set()

    def _gateway_open(self):
        if self.scheduler is None or self.scheduler.uncertain:
            self._fail("gateway_completion_unreconciled")
            return False
        # Orderly shutdown closes admission but does not revoke an in-flight
        # native transition or turn acknowledged completion into uncertainty.
        # Check uncertainty first: closing must never hide an unknown outcome.
        return self.fault is None and not self.scheduler.closing

    @staticmethod
    def _ready(identity):
        return (isinstance(identity, dict) and isinstance(identity.get("owner_id"), str)
                and bool(identity["owner_id"]) and identity.get("ready") is True
                and identity.get("loaded") is True)

    def _activate_verified_owner(self):
        if self.on_verified_owner is None:
            return
        try:
            result = self.on_verified_owner(deepcopy(self.identity))
            if result is not None:
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("Verified-owner callback must return None synchronously")
        except BaseException:
            self._fail("runtime_timing_activation_failed")
            raise

    async def initialize(self, *, parked=False):
        async with self.lock:
            if self.state != "uninitialized" or self.scheduler is None:
                raise RuntimeError("Controller initialization requires its bound scheduler")
            try:
                if parked:
                    if self.demand is None:
                        raise RuntimeError("Cold parking requires explicit demand mode")
                    proof = await self.adapter.prepare_parked()
                    if (not isinstance(proof, dict) or proof.get("state") != "parked"
                            or any(proof.get(k) is not False for k in
                                   ("running", "ready", "loaded", "native_launch_attempted"))
                            or any(proof.get(k) is not True for k in
                                   ("startup_barrier_held", "owner_lock_observed_idle",
                                    "backend_port_free", "containing_job_empty"))
                            or proof.get("owner_id") is not None
                            or "release" not in proof or proof["release"] is not None):
                        raise RuntimeError("Cold parked ownership was not verified")
                    previous = proof.get("previous_owner_id")
                    if previous is not None and (type(previous) is not str or not previous):
                        raise RuntimeError("Invalid prior owner identity")
                    self._previous_owner_id = previous
                    if not self._gateway_open():
                        return
                    self.events.append({"at": self.clock(), "cold_parked": deepcopy(proof)})
                    self._state("parked")
                    return
                identity = await self.adapter.status()
                if not self._ready(identity):
                    raise RuntimeError("An explicitly owned ready backend is required")
                self.identity = deepcopy(identity)
                if not self._gateway_open():
                    return
                self._activate_verified_owner()
                self._state("ready")
            except BaseException:
                if self.fault != "runtime_timing_activation_failed":
                    self._fail("initial_owner_unverified")
                raise

    def observe(self, sample):
        self.policy.observe(sample, self.clock())
        if self.tool is not None and (not self.policy.allowed or not self.policy.fresh(self.clock())):
            self.tool.interruption.set()

    def __call__(self):
        return (self.state == "ready" and self.fault is None and self.tool is None
                and self.scheduler is not None and not self.scheduler.uncertain
                and not self.scheduler.closing
                and self.policy.allowed and self.policy.fresh(self.clock()))

    def _capacity_fits(self, sample, requirements):
        if not isinstance(sample, dict) or sample.get("complete") is not True:
            return False
        stamp = sample.get("sampled_at")
        if not number(stamp) or not 0 <= self.clock() - stamp <= self.policy.max_age_s:
            return False
        for key, floor in (("available_ram_gib", requirements.ram_gib),
                           ("available_commit_gib", requirements.commit_gib),
                           ("available_vram_mib", requirements.vram_mib)):
            if not number(sample.get(key)) or sample[key] < floor:
                return False
        return True

    async def step(self):
        async with self.lock:
            if self.fault is not None or self.scheduler is None or self.state == "uninitialized":
                return
            if not self._gateway_open():
                return
            if not self.policy.fresh(self.clock()) and self.tool is not None:
                self.tool.interruption.set()
            try:
                release = (self.policy.yield_requested or self.tool is not None
                           or self._idle_release_requested())
                if release and self.state in ("ready", "awaiting_demand"):
                    self._state("draining")
                if self.state == "awaiting_demand":
                    demand_state = self._demand_state()
                    if (demand_state in ("eligible", "busy") and self.policy.allowed
                            and self.policy.fresh(self.clock())):
                        self._state("ready")
                    elif (demand_state == "absent" and self.scheduler.active is None
                          and not self.scheduler.pending):
                        self._state("draining")
                if self.state == "draining":
                    if self.scheduler.active is not None:
                        return
                    self._state("releasing")
                    proof = await self.adapter.stop(deepcopy(self.identity))
                    count = proof.get("retained_processes") if isinstance(proof, dict) else None
                    if (not isinstance(proof, dict) or proof.get("owner_id") != self.identity["owner_id"]
                            or any(proof.get(k) is not True for k in ("released", "cleanup_confirmed", "port_free"))
                            or type(count) is not int or count < 1
                            or type(proof.get("confirmed_process_exits")) is not int
                            or proof["confirmed_process_exits"] != count):
                        raise RuntimeError("Native release was not verified")
                    self.events.append({"at": self.clock(), "release": deepcopy(proof)})
                    self._state("parked")
                    if not self._gateway_open():
                        return
                if self.state == "parked" and self.tool is not None:
                    grant = self.tool
                    if grant.granted:
                        return
                    if (not self.policy.allowed or not self.policy.fresh(self.clock())
                            or self.clock() >= grant.deadline):
                        return
                    capacity = await self.adapter.fresh_capacity()
                    # A canceled acquisition may have disappeared or been
                    # replaced while observing capacity. Only this exact grant
                    # can consume this observation, and only before its deadline.
                    if not self._gateway_open() or self.tool is not grant:
                        return
                    if (self.clock() < grant.deadline and self.policy.allowed
                            and self.policy.fresh(self.clock())
                            and self._capacity_fits(capacity, grant.requirements)):
                        grant.capacity = deepcopy(capacity)
                        grant.granted = True
                        grant.interruption.clear()
                        self.events.append({"at": self.clock(), "tool_granted": grant.token,
                                            "capacity": deepcopy(capacity)})
                    return
                if self.state == "parked" and self.policy.allowed and self.policy.fresh(self.clock()):
                    if self.demand is not None:
                        if self._demand_state() != "eligible" or self.scheduler.active is not None:
                            return
                        capacity = await self.adapter.fresh_capacity()
                        await self.refresh_demand()
                        if (not self._gateway_open() or self.tool is not None
                                or self.scheduler.active is not None
                                or self._demand_state() != "eligible"
                                or not self.policy.allowed or not self.policy.fresh(self.clock())
                                or not self._capacity_fits(capacity, self.restore_requirements)):
                            return
                    old_owner = self.identity["owner_id"] if self.identity else self._previous_owner_id
                    self._state("restoring")
                    if self.demand is not None:
                        self.events.append({"at": self.clock(), "restore_requested": True})
                    identity = await self.adapter.start()
                    if not self._ready(identity) or identity["owner_id"] == old_owner:
                        raise RuntimeError("Fresh owner readiness was not verified")
                    self.identity = deepcopy(identity)
                    if self.demand is not None:
                        await self.refresh_demand()
                    if not self._gateway_open():
                        return
                    self._activate_verified_owner()
                    if (self.demand is not None
                            and (self._demand_state() not in ("eligible", "busy")
                                 or not self.policy.allowed or not self.policy.fresh(self.clock())
                                 or self.tool is not None)):
                        # Keep the exact returned owner. Unknown state holds
                        # admission; it does not prove release authority. Fresh
                        # operation_inflight is allowed to dispatch its already
                        # prepared request without demanding eligibility again.
                        self._state("awaiting_demand")
                    else:
                        self._state("ready")
                    # A sample arriving during startup still closes the callable gate.
            except BaseException as exc:
                if self.fault != "runtime_timing_activation_failed":
                    self._fail(type(exc).__name__ + ":native_transition_unconfirmed")
                raise

    async def acquire_tool(self, requirements, *, timeout_s=120):
        if not isinstance(requirements, ToolRequirements) or not number(timeout_s, minimum=.01) or timeout_s > 3600:
            raise ValueError("Explicit bounded tool requirements are required")
        if self.tool is not None or self.fault is not None or self.state == "uninitialized":
            raise RuntimeError("Tool owner already exists or controller unavailable")
        if not self._gateway_open():
            raise RuntimeError("Controller requires reconciliation")
        grant = ToolGrant(uuid.uuid4().hex, requirements, self.clock() + timeout_s)
        self.tool = grant  # closes new dispatch before the first await
        try:
            while True:
                if not self._gateway_open() or self.tool is not grant:
                    raise RuntimeError("Controller requires reconciliation")
                if self.clock() >= grant.deadline:
                    raise TimeoutError("Tool admission expired without executing a tool")
                if grant.granted:
                    # Grant and delivery are separate event-loop turns. Demand,
                    # freshness, closure or the deadline may change between them.
                    if (grant.interruption.is_set() or not self.policy.allowed
                            or not self.policy.fresh(self.clock())):
                        raise RuntimeError("Tool admission interrupted before delivery")
                    if not self._capacity_fits(grant.capacity, grant.requirements):
                        raise RuntimeError("Tool capacity expired before delivery")
                    return grant
                await asyncio.sleep(.02)
        except BaseException:
            if grant.granted:
                self._fail("tool_acquisition_cancelled_after_grant")
            elif self.tool is grant:
                self.tool = None
            raise

    def complete_tool(self, grant, *, owned_processes_exited):
        if self.tool is not grant or not grant.granted:
            raise RuntimeError("Only the granted tool owner may release its handoff")
        if owned_processes_exited is not True:
            self._fail("tool_exit_unconfirmed")
            raise RuntimeError("Keep the backend parked until owned tool exit is confirmed")
        self.events.append({"at": self.clock(), "tool_completed": grant.token,
                            "interrupted": grant.interruption.is_set()})
        self.tool = None

    def status(self):
        result = {"handoff_state": self.state, "admission_allowed": self(), "fault": self.fault,
                "foreground_reason": self.policy.reason, "tool_owner": self.tool.token if self.tool else None,
                "tool_interruption_requested": self.tool.interruption.is_set() if self.tool else False,
                "scope": "cooperating owned backend and tools; no active inference preemption or OS reservation"}
        if self.demand is not None:
            result["demand"] = {"classification": self._demand_state(),
                "idle_grace_s": self.idle_grace_s,
                "intents": [{"registration_id": row.registration_id, "revision": row.revision,
                             "state": row.state, "reason": row.reason}
                            for row in self._demand_rows],
                "scope": "observed durable intent; no cancellation request acknowledgement"}
        return result
