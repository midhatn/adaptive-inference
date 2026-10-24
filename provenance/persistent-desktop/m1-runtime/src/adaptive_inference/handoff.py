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
    def __init__(self, adapter, policy=None, *, clock=time.monotonic):
        self.adapter, self.policy, self.clock = adapter, policy or ForegroundPolicy(), clock
        self.scheduler = None
        self.identity = None
        self.state = "uninitialized"
        self.fault = None
        self.tool = None
        self.events = deque(maxlen=256)
        self.lock = asyncio.Lock()

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

    async def initialize(self):
        async with self.lock:
            if self.state != "uninitialized" or self.scheduler is None:
                raise RuntimeError("Controller initialization requires its bound scheduler")
            try:
                identity = await self.adapter.status()
                if not self._ready(identity):
                    raise RuntimeError("An explicitly owned ready backend is required")
                self.identity = deepcopy(identity)
                if not self._gateway_open():
                    return
                self._state("ready")
            except BaseException:
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
                release = self.policy.yield_requested or self.tool is not None
                if release and self.state == "ready":
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
                    old_owner = self.identity["owner_id"]
                    self._state("restoring")
                    identity = await self.adapter.start()
                    if not self._ready(identity) or identity["owner_id"] == old_owner:
                        raise RuntimeError("Fresh owner readiness was not verified")
                    self.identity = deepcopy(identity)
                    if not self._gateway_open():
                        return
                    self._state("ready")
                    # A sample arriving during startup still closes the callable gate.
            except BaseException as exc:
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
        return {"handoff_state": self.state, "admission_allowed": self(), "fault": self.fault,
                "foreground_reason": self.policy.reason, "tool_owner": self.tool.token if self.tool else None,
                "tool_interruption_requested": self.tool.interruption.is_set() if self.tool else False,
                "scope": "cooperating owned backend and tools; no active inference preemption or OS reservation"}
