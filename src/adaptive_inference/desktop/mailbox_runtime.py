# SPDX-License-Identifier: Apache-2.0
"""One prepared task's actual mailbox adapter; lifecycle remains host-supplied.

No listener, process discovery, native control or target ownership lives here.
Database operations use the existing TaskStore/Mailbox. Read observations are
not reservations against subsequent external controls. See README.md.
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import math
import threading
import time

from adaptive_inference.control_mailbox import Mailbox, MailboxSnapshot, ControlNotRecorded, ControlBlocked, execution_outcome, WAIT_EXPIRY_SCHEMA
from adaptive_inference.demand import _label
from adaptive_inference.execution_clock import CLOCK_ID, execution_now
from adaptive_inference.desktop.control_transport import PreparedTask, execution as checked_execution, Refused
from adaptive_inference.desktop.ui_intent import UIBinding, UIIntentGate


class RuntimeUnavailable(RuntimeError):
    """Unavailable observation or unresolved lifecycle; never an invented state."""


@dataclass(frozen=True)
class Observation:
    snapshot: MailboxSnapshot
    started: float
    finished: float


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _control(value):
    return {key: value[key] for key in
            ('request_id', 'command', 'sequence', 'outcome', 'owner_acknowledged')}


class MailboxRuntime:
    def __init__(self, prepared, mailbox, *, requester_capability, gate,
                 intent_capability, lifecycle, max_pending=4, max_age_s=1,
                 clock=time.monotonic):
        if (type(prepared) is not PreparedTask or type(mailbox) is not Mailbox
                or type(gate) is not UIIntentGate or type(requester_capability) is not object
                or type(intent_capability) is not object):
            raise TypeError('Exact prepared task, mailbox, gate and private capabilities required')
        if (prepared.task_id != mailbox.identity.task_id or gate.host_epoch != prepared.host_epoch
                or requester_capability is not mailbox._capability
                or intent_capability is not gate._capability
                or gate._thread is not threading.current_thread()):
            raise ValueError('Trusted task, host and requester binding mismatch')
        if type(max_pending) is not int or not 1 <= max_pending <= 32:
            raise ValueError('Bound pending database operations from 1 to 32')
        if not _number(max_age_s) or not 0 < max_age_s <= 60 or not callable(clock):
            raise ValueError('Finite observation lifetime and monotonic clock required')
        for name in ('session_is_live', 'window_ready', 'window_closed', 'status',
                     'fence_admission', 'cooperative_stop'):
            if not callable(getattr(lifecycle, name, None)):
                raise TypeError('Explicit trusted lifecycle hook required: ' + name)
        self.prepared, self.mailbox, self.gate = prepared, mailbox, gate
        self._requester, self._intent = requester_capability, intent_capability
        self.lifecycle = lifecycle
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self._serial = asyncio.Lock()
        self._pending = set()
        self._faults = set()
        self._cache = self._binding = self._stop_task = self._stop_receipt = None
        self._stopping = False
        self._clock, self.max_age_s, self.max_pending = clock, max_age_s, max_pending
        self._selection = {'execution_id': prepared.task_id, 'execution_generation': 0}
        self._transitioning = False
        self._continuation = None
        self._continuation_tasks = set()
        self._continuation_phase, self._continuation_request = 'unavailable', None
        self._task_retired = False

    def _owns_intent(self):
        binding = self.gate._binding
        return binding is not None and binding.task_id == self.prepared.task_id

    def retire_task(self):
        """Trusted handover fence; retain reads/Status/Stop for this exact task."""
        self._owner()
        self.deactivate_intent()
        self._task_retired = True

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise RuntimeError('Runtime belongs to its original host loop and thread')

    def _observe(self, mailbox=None):
        started = self._clock()
        snapshot = (self.mailbox if mailbox is None else mailbox).snapshot()
        return Observation(snapshot, started, self._clock())

    def _check_observation(self, observation, *, execution=None):
        now = self._clock()
        if (type(observation) is not Observation or type(observation.snapshot) is not MailboxSnapshot
                or not all(_number(value) for value in (observation.started, observation.finished, now))
                or not observation.started <= observation.finished <= now
                or now - observation.started > self.max_age_s):
            raise RuntimeUnavailable('Observation is unavailable or stale')
        target = observation.snapshot.target
        selected = self._selection if execution is None else execution
        if target.task_id != selected['execution_id'] or target.prompt != self.prepared.objective:
            raise RuntimeUnavailable('Original task binding changed')
        return observation.snapshot

    def _install(self, observation):
        snapshot = self._check_observation(observation)
        if self._cache is not None:
            previous = self._cache.snapshot
            if (snapshot.target.revision < previous.target.revision
                    or snapshot.mailbox_revision < previous.mailbox_revision):
                raise RuntimeUnavailable('Observed history moved backward')
        self._cache = observation
        latest = snapshot.requests[-1] if snapshot.requests else None
        resume_pending = (latest is not None and latest['command'] == 'resume'
                          and snapshot.status(latest['request_id'])['outcome'] == 'pending')
        # A newly observed later durable Pause/Cancel revokes known stale
        # intent even when it came from another trusted mailbox submitter.
        # A latest pending Resume is explicit intent while its preceding
        # paused state awaits the actual owner's ACK; it is not an ACK itself.
        if (execution_outcome(snapshot.target.state) is not None
                or latest is not None and latest['command'] in ('pause', 'cancel')
                or snapshot.demand is None
                or snapshot.demand['state'] == 'paused' and not resume_pending):
            self.deactivate_intent()
        if (self._binding is not None and (snapshot.target.state['status'] != 'pending'
                or snapshot.demand is not None and snapshot.demand['state'] in ('cancelled', 'fulfilled'))):
            if self._owns_intent():
                self.gate.terminal(self._intent, self.prepared.task_id)
            self._binding = None
        return snapshot

    async def _database(self, function, apply):
        self._owner()
        if self._stopping:
            raise RuntimeUnavailable('Host is stopping')
        if len(self._pending) >= self.max_pending:
            raise RuntimeUnavailable('Bounded database capacity is occupied')

        async def work():
            async with self._serial:
                # This private retained task is never cancelled by a client or
                # shutdown. Host loop teardown must wait for cooperative_stop.
                value = await asyncio.to_thread(function)
                return apply(value)

        task = self._loop.create_task(work())
        self._pending.add(task)

        def completed(done):
            try:
                if done.cancelled():
                    self._faults.add('database_task_cancelled')
                elif done.exception() is not None:
                    self._faults.add('database_operation_failed')
                    self._cache = None
                    try:
                        self.deactivate_intent()
                    except Exception:
                        self._faults.add('intent_revocation_failed')
            finally:
                self._pending.discard(done)

        task.add_done_callback(completed)
        # A cancelled/timeout waiter cannot cancel the retained offload.
        return await asyncio.shield(task)

    async def refresh(self):
        if self._transitioning:
            return self.status()
        mailbox = self.mailbox
        def apply(observation):
            # A refresh accepted before Continue still joins its real read. Once
            # transition has fenced intent, that old observation is no longer a
            # candidate for installation or admission. Actual read failures and
            # all mutation/Resume-authority apply paths retain their usual guards.
            if self._transitioning and mailbox is self.mailbox:
                return None
            return self._install(observation)
        await self._database(lambda: self._observe(mailbox), apply)
        return self.status()

    def selected_execution(self):
        self._owner()
        return dict(self._selection)

    def _require_execution(self, execution):
        self._owner()
        value = dict(self._selection) if execution is None else checked_execution(execution)
        if value != self._selection:
            raise Refused('stale_execution')
        return value

    async def submit_control(self, request_id, command, *, execution=None, _transition=False):
        selected = self._require_execution(execution)
        if self._task_retired:
            raise Refused('task_retired')
        if self._transitioning and not _transition:
            raise Refused('continuation_unavailable')
        mailbox, requester = self.mailbox, self._requester
        def submit():
            # Verify actual immutable task binding before the first possible
            # mutation, even if a caller did not explicitly refresh at startup.
            if selected != self._selection:
                raise Refused('stale_execution')
            self._check_observation(self._observe(mailbox))
            value = mailbox.submit(requester, request_id, command)
            return value, self._observe(mailbox)

        def apply(value):
            result, observation = value
            self._install(observation)
            return result if type(result) is ControlNotRecorded else _control(result)

        return await self._database(submit, apply)

    async def resume_authority(self, request_id, *, execution=None):
        self._require_execution(execution)
        if self._task_retired:
            return False
        mailbox = self.mailbox
        _label(request_id, 'request_id')

        def authority(observation):
            snapshot = self._install(observation)
            latest = snapshot.requests[-1] if snapshot.requests else None
            target = snapshot.target
            if (self._faults or execution_outcome(target.state) is not None
                    or not self._execution_live(target.state)
                    or latest is None or latest['request_id'] != request_id or latest['command'] != 'resume'
                    or target.state['status'] != 'pending' or target.requires_reconciliation
                    or target.operation is not None or snapshot.demand is None
                    or snapshot.demand['state'] not in ('active', 'waiting', 'paused')):
                return False
            return snapshot.status(request_id)['outcome'] in ('pending', 'applied')

        return await self._database(lambda: self._observe(mailbox), authority)

    def status(self):
        self._owner()
        # A retained transition projects its exact captured snapshot explicitly;
        # this branch does not grant admission from an expired observation.
        snapshot = (self._cache.snapshot if (self._transitioning or self._stopping) and self._cache is not None
                    else self._check_observation(self._cache))
        host = self.lifecycle.status()
        if (type(host) is not dict or set(host) != {'host_phase', 'waiting_reason'}
                or host['host_phase'] not in ('starting', 'ready', 'parked', 'restoring', 'stopping', 'closed', 'fault')
                or host['waiting_reason'] not in (None, 'foreground', 'resources', 'paused',
                                                'reconciliation', 'stop_requested', 'operation_inflight', 'unknown')):
            raise RuntimeUnavailable('Trusted lifecycle projection is unavailable')
        target, demand = snapshot.target, snapshot.demand
        reason = host['waiting_reason']
        if self._faults:
            host = {'host_phase': 'fault', 'waiting_reason': 'unknown'}
            reason = 'unknown'
        elif self._stopping:
            reason = 'stop_requested'
        elif target.requires_reconciliation:
            reason = 'reconciliation'
        elif target.operation is not None:
            reason = 'operation_inflight'
        elif demand is None:
            reason = 'unknown'
        elif execution_outcome(target.state) is not None:
            reason = 'budget_expired'
        elif demand['state'] == 'paused':
            reason = 'paused'
        phase, request = self._continuation_phase, self._continuation_request
        if not self._transitioning and self._continuation is not None and execution_outcome(target.state) is not None:
            marker = execution_outcome(target.state)
            available = not self._faults
            if marker['schema'] == WAIT_EXPIRY_SCHEMA:
                # Cached availability is not a grant. Selection verifies the
                # joined worker and rechecks the predecessor in its transaction.
                try:
                    self.mailbox.admission_wait_candidate(snapshot, allow_sealed=True)
                except ControlBlocked:
                    available = False
                else:
                    available = (available and not self._stopping and not self._task_retired
                        and target.owner_epoch is None and target.state['requests'] < 8
                        and target.state['admission_attempts'] < 32)
            phase, request = ('available', None) if available else ('blocked', request)
        return {'host_phase': host['host_phase'], 'task_status': target.state['status'],
                'task_revision': target.revision, 'demand': None if demand is None else demand['state'],
                'waiting_reason': reason,
                **self._selection, 'continuation': {'phase': phase, 'request_id': request},
                'controls': [_control(snapshot.status(row['request_id'])) for row in snapshot.requests]}

    def session_is_live(self, session_id):
        self._owner()
        return self.lifecycle.session_is_live(session_id) is True

    def window_ready(self, session_id):
        self._owner()
        if self._stopping or self._task_retired:
            return False
        binding = self.lifecycle.window_ready(session_id)
        if (type(binding) is not UIBinding or binding.host_epoch != self.prepared.host_epoch
                or binding.task_id != self.prepared.task_id or binding.session_id != session_id
                or not self.session_is_live(session_id)):
            return False
        self.gate.bind(self._intent, binding)
        self._binding = binding
        return True

    def deactivate_intent(self):
        self._owner()
        if self._owns_intent():
            self.gate.deactivate(self._intent)

    def activate_intent(self, session_id, *, execution=None):
        self._owner()
        self._require_execution(execution)
        if self._stopping or self._task_retired or not self.session_is_live(session_id):
            raise RuntimeUnavailable('Session cannot activate during close or identity loss')
        # Authority was read asynchronously. A seal may follow that read, but
        # cannot precede this original deadline; no loop-thread DB read needed.
        snapshot = self._check_observation(self._cache)
        if execution_outcome(snapshot.target.state) is not None or not self._execution_live(snapshot.target.state):
            self.deactivate_intent()
            return False
        self.gate.activate(self._intent, session_id=session_id, task_id=self.prepared.task_id)
        return True

    def _execution_live(self, state):
        if 'deadline_monotonic' not in state:
            return True  # Existing tasks without the explicit execution budget.
        if 'deadline_clock' in state and state['deadline_clock'] != CLOCK_ID:
            raise RuntimeUnavailable('Original execution clock is unknown')
        deadline = state['deadline_monotonic']
        now = execution_now() if 'deadline_clock' in state else self._clock()
        if not _number(deadline) or deadline <= 0 or not _number(now):
            raise RuntimeUnavailable('Original execution deadline is malformed')
        return now < deadline

    def window_closed(self, session_id):
        self._owner()
        self.deactivate_intent()
        if self._binding is not None and self._binding.session_id == session_id:
            if self._owns_intent():
                self.gate.revoke(self._intent, session_id)
            self._binding = None
        self.lifecycle.window_closed(session_id)

    def fence_admission(self):
        self._owner()
        self._stopping = True
        self.gate.deactivate(self._intent)
        try:
            self.lifecycle.fence_admission()
        except BaseException:
            self._faults.add('host_fence_failed')
            raise

    async def cooperative_stop(self):
        self._owner()
        if self._stop_task is None:
            if not self._stopping:
                self.fence_admission()
            self._stop_task = self._loop.create_task(self._finish_stop())
        return await asyncio.shield(self._stop_task)

    async def _finish_stop(self):
        # No new database work enters after the fence; already accepted work
        # must finish, even if the original UI handler disappeared.
        while self._continuation_tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._continuation_tasks)), return_exceptions=True)
            await asyncio.sleep(0)
        while self._pending:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._pending)), return_exceptions=True)
            await asyncio.sleep(0)
        if (self._continuation is not None and any(not row['authorization_resolved']
                for row in self._continuation.records.values())):
            raise RuntimeUnavailable('Continuation authorization outcome is unresolved')
        if (self._continuation is not None and self._continuation.current is not None
                and self.lifecycle._selected is not self._continuation.current):
            raise RuntimeUnavailable('Committed selection lacks its lifecycle obligation')
        value = await self.lifecycle.cooperative_stop()
        self._stop_receipt = deepcopy(value)
        if (type(value) is not dict or set(value) != {'worker_joined', 'host_closed', 'uncertain', 'fault'}
                or any(type(value[key]) is not bool for key in ('worker_joined', 'host_closed', 'uncertain'))):
            raise RuntimeUnavailable('Host did not supply a complete join/close receipt')
        if self._faults and value['fault'] is None:
            value = {**value, 'fault': 'runtime_operation_failed'}
        return deepcopy(value)

    def configure_continuation(self, continuation):
        self._owner()
        if self._continuation is not None or continuation.runtime is not self or self._stopping:
            raise RuntimeUnavailable('Continuation must bind this runtime once')
        self._continuation = continuation

    async def _retain_continuation(self, operation):
        self._owner()
        if self._continuation is None:
            raise Refused('continuation_unavailable')
        task = self._loop.create_task(operation())
        self._continuation_tasks.add(task)
        def completed(done):
            try:
                if done.cancelled() or done.exception() is not None and not isinstance(done.exception(), Refused):
                    self._faults.add('continuation_failed')
                    self._continuation_phase = 'blocked'
                    self.deactivate_intent()
            finally:
                self._continuation_tasks.discard(done)
        task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def select_continuation(self, request, *, intent_valid):
        if self._task_retired:
            raise Refused('task_retired')
        return await self._retain_continuation(lambda: self._continuation.select(request, intent_valid=intent_valid))

    async def continue_selected(self, grant, *, intent_valid):
        if self._task_retired:
            raise Refused('task_retired')
        return await self._retain_continuation(lambda: self._continuation.continue_selected(grant, intent_valid=intent_valid))

    async def lookup_continuation(self, request):
        if self._task_retired:
            raise Refused('task_retired')
        return await self._retain_continuation(lambda: self._continuation.lookup(request))

    def diagnostics(self):
        self._owner()
        return {'pending_database': len(self._pending), 'stopping': self._stopping,
                'faults': sorted(self._faults),
                'snapshot_revisions': None if self._cache is None else {
                    'task': self._cache.snapshot.target.revision,
                    'mailbox': self._cache.snapshot.mailbox_revision}}
