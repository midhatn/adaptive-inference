"""Bounded arrival-offset scheduling, with exclusive HTTP dispatch ownership.

Design reference: NVIDIA Dynamo policy_queue.rs at 868de572 (see references).
This asynchronous implementation does not preempt an active engine request.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import itertools
import time


class AdmissionError(Exception):
    def __init__(self, code, message, status=503):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Ticket:
    sequence: int
    request_class: str
    arrival: float
    rank: float


class Scheduler:
    def __init__(self, config, capacity=lambda: True):
        self.config, self.capacity = config, capacity
        self.condition = asyncio.Condition()
        self.pending = {}
        self.sequence = itertools.count()
        self.active = None
        self.uncertain = False
        self.closing = False
        self.completed = self.cancelled = self.rejected = 0
        self.deferred = 0

    async def acquire(self, request_class, predicted_s, disconnected=lambda: False, *, wait=True):
        if type(wait) is not bool:
            raise ValueError("wait must be a boolean")
        now = time.monotonic()
        cost = self.config.max_cost_delay_s if predicted_s is None else min(predicted_s, self.config.max_cost_delay_s)
        ticket = Ticket(next(self.sequence), request_class, now,
                        now + cost + (self.config.normal_boost_s if request_class == "background" else 0))
        deadline = now + self.config.queue_timeout_s
        async with self.condition:
            if self.closing or self.uncertain:
                raise AdmissionError("backend_unavailable", "Gateway is stopping or backend completion is uncertain; check backend and restart gateway")
            if len(self.pending) >= self.config.max_pending:
                if not wait:
                    self.deferred += 1
                    raise AdmissionError("admission_deferred", "Request was not dispatched; immediate admission is unavailable")
                self.rejected += 1
                raise AdmissionError("queue_full", "Pending queue is full", 429)
            self.pending[ticket.sequence] = ticket
            try:
                while True:
                    if disconnected():
                        raise AdmissionError("client_disconnected", "Client disconnected before dispatch", 499)
                    if self.closing or self.uncertain:
                        raise AdmissionError("backend_unavailable", "Backend completion is uncertain or gateway is stopping")
                    left = deadline - time.monotonic()
                    if wait and left <= 0:
                        raise AdmissionError("queue_timeout", "Queue or capacity wait expired", 504)
                    head = min(self.pending.values(), key=lambda value: (value.rank, value.sequence))
                    if self.active is None and head is ticket and self.capacity():
                        del self.pending[ticket.sequence]
                        self.active = ticket
                        return ticket
                    if not wait:
                        raise AdmissionError("admission_deferred", "Request was not dispatched; immediate admission is unavailable")
                    try:
                        await asyncio.wait_for(self.condition.wait(), min(left, .1))
                    except TimeoutError:
                        pass
            except BaseException as exc:
                self.pending.pop(ticket.sequence, None)
                if isinstance(exc, AdmissionError) and exc.code == "admission_deferred":
                    self.deferred += 1
                else:
                    self.cancelled += 1
                self.condition.notify_all()
                raise

    async def release(self, ticket, *, uncertain=False):
        async with self.condition:
            if self.active is not ticket:
                raise RuntimeError("Only the active dispatch owner may release admission")
            self.active = None
            self.uncertain |= uncertain
            self.completed += 1
            self.condition.notify_all()

    async def close(self):
        async with self.condition:
            self.closing = True
            self.condition.notify_all()

    def status(self):
        return {"active": self.active is not None, "pending": len(self.pending),
                "normal_pending": sum(t.request_class == "normal" for t in self.pending.values()),
                "background_pending": sum(t.request_class == "background" for t in self.pending.values()),
                "completed": self.completed, "cancelled": self.cancelled, "rejected": self.rejected,
                "deferred": self.deferred,
                "backend_completion_uncertain": self.uncertain, "closing": self.closing,
                "maximum_ordering_offset_s": self.config.normal_boost_s + self.config.max_cost_delay_s,
                "preemption": False, "resource_reservation": False}
