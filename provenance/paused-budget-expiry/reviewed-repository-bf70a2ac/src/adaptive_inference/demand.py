# SPDX-License-Identifier: Apache-2.0
"""Durable task demand, never resource ownership.

Reuse the canonical TaskStore and actual OwnedTask; no SQL, second database,
HTTP queue, dispatch, provider, model start or effect retry lives here.
This component is in development and is not wired to a persistent controller.
See docs/durable-demand.md for sources, scope and integration limitations.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Iterable

from adaptive_inference.task_store import (
    Checkpoint, OwnedTask, OwnershipError, ReconciliationRequired,
    TaskStore, TaskStoreError,
)

NAMESPACE = "adaptive_inference.demand.v1"
MAX_REGISTRATIONS = 1000
STATES = frozenset(("active", "waiting", "paused", "cancelled", "fulfilled"))
_NEXT = {
    None: frozenset(("active", "waiting", "paused", "cancelled")),
    "active": frozenset(("waiting", "paused", "cancelled", "fulfilled")),
    "waiting": frozenset(("active", "paused", "cancelled", "fulfilled")),
    "paused": frozenset(("active", "waiting", "cancelled", "fulfilled")),
    "cancelled": frozenset(),
    "fulfilled": frozenset(),
}


def _label(value, name):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError(f"{name} must be a stable identifier of at most 128 characters")
    return value


def _utc(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value):
        raise ValueError("Time must be an explicit UTC ISO-8601 string ending in Z")
    datetime.fromisoformat(value[:-1] + "+00:00")
    return value


@dataclass(frozen=True, slots=True)
class DemandIdentity:
    """Stable task-lifetime declaration supplied by the trusted host.

    owner_id is a logical host/agent lineage label, not an OS PID, TaskStore
    ownership epoch, credential, permission or proof that a runner is alive.
    Arrival is retained for inspection/accounting, never used to grant eligibility.
    """
    registration_id: str
    task_id: str
    owner_id: str
    arrived_at_utc: str

    def __post_init__(self):
        for name in ("registration_id", "task_id", "owner_id"):
            _label(getattr(self, name), name)
        _utc(self.arrived_at_utc)

    def metadata(self):
        return {"schema": 1, "registration_id": self.registration_id,
                "task_id": self.task_id, "owner_id": self.owner_id,
                "arrived_at_utc": self.arrived_at_utc}


@dataclass(frozen=True, slots=True)
class Registration:
    store: TaskStore
    identity: DemandIdentity

    def __post_init__(self):
        if type(self.store) is not TaskStore or type(self.identity) is not DemandIdentity:
            raise TypeError("Register an explicit TaskStore and DemandIdentity")


@dataclass(frozen=True, slots=True)
class DemandObservation:
    registration_id: str
    task_id: str
    owner_id: str
    arrived_at_utc: str
    revision: int | None
    state: str | None
    eligible: bool
    reason: str


def _record(checkpoint, identity):
    declaration = checkpoint.metadata.get(NAMESPACE)
    if (checkpoint.task_id != identity.task_id or type(declaration) is not dict
            or type(declaration.get("schema")) is not int or declaration != identity.metadata()):
        raise ValueError("Trusted registry identity does not match immutable task metadata")
    if NAMESPACE not in checkpoint.state:
        return None
    record = checkpoint.state[NAMESPACE]
    if type(record) is not dict or set(record) != set(identity.metadata()) | {"state", "updated_at_utc", "reason"}:
        raise ValueError("Malformed namespaced demand record")
    if type(record.get("schema")) is not int or any(record.get(key) != value for key, value in identity.metadata().items()):
        raise ValueError("Demand changed its immutable task identity or original arrival")
    if type(record["state"]) is not str or record["state"] not in STATES:
        raise ValueError("Unknown demand state")
    _utc(record["updated_at_utc"])
    if type(record["reason"]) is not str or len(record["reason"]) > 512:
        raise ValueError("Demand reason must be text of at most 512 characters")
    return record


class DemandRegistry:
    """Explicit trusted bindings, reconstructed from trusted settings after restart.

    No file discovery, arbitrary caller path or untrusted request header is
    accepted. Observations can become stale immediately and are not permits.
    """
    def __init__(self, registrations: Iterable[Registration]):
        self._registered = {}
        tasks = set()
        for registration in registrations:
            if type(registration) is not Registration:
                raise TypeError("Expected an explicit Registration")
            if len(self._registered) >= MAX_REGISTRATIONS:
                raise ValueError("Demand registry limit reached")
            identity = registration.identity
            key = (registration.store.path, identity.task_id)
            if identity.registration_id in self._registered or key in tasks:
                raise ValueError("Duplicate demand registration or task binding")
            _record(registration.store.load(identity.task_id), identity)
            self._registered[identity.registration_id] = registration
            tasks.add(key)

    def _binding(self, registration_id):
        _label(registration_id, "registration_id")
        try:
            return self._registered[registration_id]
        except KeyError:
            raise KeyError("Task is not explicitly registered for inference demand") from None

    def observe(self, registration_id):
        """Read an advisory restoration candidate, without writes or claims.

        False for in-flight or unknown state is not absence of resource
        ownership and must never authorize unloading an active model. Existing
        scheduler/native drain and release checks remain the authority.
        """
        binding = self._binding(registration_id)
        identity = binding.identity
        revision = None
        state = None
        eligible = False
        try:
            checkpoint = binding.store.load(identity.task_id)
            revision = checkpoint.revision
            record = _record(checkpoint, identity)
            state = None if record is None else record["state"]
            if checkpoint.state["status"] != "pending":
                reason = "task_terminal"
            elif checkpoint.requires_reconciliation:
                reason = "reconciliation_required"
            elif checkpoint.operation is not None:
                reason = "operation_inflight"
            elif record is None:
                reason = "no_demand"
            elif state not in ("active", "waiting"):
                reason = "demand_" + state
            else:
                eligible, reason = True, "safe_task_demand"
        except (TaskStoreError, OSError, ValueError, KeyError, TypeError):
            reason = "unavailable_or_invalid_checkpoint"
        return DemandObservation(identity.registration_id, identity.task_id, identity.owner_id,
                                 identity.arrived_at_utc, revision, state, eligible, reason)

    def observations(self):
        """Inspect only the explicitly registered tasks, in registration order."""
        return tuple(self.observe(key) for key in self._registered)

    def transition(self, registration_id, owned: OwnedTask, state, *, expected_revision,
                   updated_at_utc, reason="") -> Checkpoint:
        """Checkpoint a safe task-lifetime transition through its actual owner.

        Same-state calls verify current ownership/revision but do not write a
        heartbeat or replace timestamps/reasons. Fulfilled/cancelled do not reopen.
        This is cooperative intent, not cancellation of an executing operation.
        """
        binding = self._binding(registration_id)
        if type(owned) is not OwnedTask:
            raise TypeError("Demand changes require the actual TaskStore OwnedTask")
        if owned._store.path != binding.store.path or owned.checkpoint.task_id != binding.identity.task_id:
            raise OwnershipError("Owned task does not match the registered store and task")
        if type(state) is not str or state not in STATES:
            raise ValueError("Unknown demand state")
        _utc(updated_at_utc)
        if type(reason) is not str or len(reason) > 512:
            raise ValueError("Demand reason must be text of at most 512 characters")
        # Reuse the existing read transaction and owner/revision fence even for
        # an idempotent no-op. save_checkpoint remains the sole writer below.
        with owned._store._connection() as db:
            checkpoint = owned._check(db, expected_revision)
            record = _record(checkpoint, binding.identity)
            if checkpoint.requires_reconciliation or checkpoint.operation is not None:
                raise ReconciliationRequired("Demand cannot authorize or cancel unresolved execution")
            previous = None if record is None else record["state"]
            if previous == state:
                return checkpoint
            if state not in _NEXT[previous]:
                raise ValueError("Demand cannot transition from its current state")
            next_state = deepcopy(checkpoint.state)
            next_state[NAMESPACE] = {**binding.identity.metadata(), "state": state,
                                     "updated_at_utc": updated_at_utc, "reason": reason}
        return owned.save_checkpoint(next_state, expected_revision=expected_revision)
