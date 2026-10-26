# SPDX-License-Identifier: Apache-2.0
"""Bounded trusted controls, reusing TaskStore and DemandRegistry unchanged.

Recording is not acknowledgement. Only the actual owner applies demand at a
safe boundary. No service, transport, new schema, process control or replay.
See docs/task-controls.md for the authority boundary and two-commit crash gap.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re

from adaptive_inference.demand import DemandRegistry, _label, _record, _utc
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_store import (
    OwnedTask, OwnershipError, RevisionConflict,
    TaskStoreError, TerminalTaskError, MAX_REVISIONS,
)

REQUESTS = 'adaptive_inference.control_requests.v1'
ACKS = 'adaptive_inference.control_acks.v1'
MAX_REQUESTS = 32
COMMANDS = {'pause': 'paused', 'resume': 'waiting', 'cancel': 'cancelled'}
EXECUTION_OUTCOME = 'adaptive_inference.execution_outcome.v1'
EXPIRY_SCHEMA = 'adaptive.paused-budget-expiry.v1'
CLOCK_EXPIRY_SCHEMA = 'adaptive.paused-budget-expiry.v2'
WAIT_EXPIRY_SCHEMA = 'adaptive.admission-wait-budget-expiry.v1'


class ControlBlocked(TaskStoreError):
    """Cooperating host must not start another operation at this boundary."""


def _execution_digest(value):
    # Same canonical JSON encoding as the existing recovery receipt digest;
    # the generic mailbox must not import a desktop/agent integration.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def control_prefix_digest(requests, receipts):
    return _execution_digest({'requests': list(requests), 'receipts': list(receipts)})


def execution_outcome(state):
    """Strict optional execution seal; a malformed present value is not absence."""
    if EXECUTION_OUTCOME not in state:
        return None
    value = state[EXECUTION_OUTCOME]
    if type(value) is dict and value.get('schema') == WAIT_EXPIRY_SCHEMA:
        return _admission_wait_outcome(state, value)
    keys = {'schema', 'deadline_monotonic', 'pause_observed_at_monotonic', 'sealed_at_monotonic',
            'owner_epoch', 'pre_seal_revision', 'pre_seal_state_sha256', 'pause_request_id',
            'pause_sequence', 'control_prefix_sha256'}
    if type(value) is dict and value.get('schema') == CLOCK_EXPIRY_SCHEMA:
        keys.add('deadline_clock')
        if value.get('deadline_clock') != CLOCK_ID or state.get('deadline_clock') != CLOCK_ID:
            raise ControlBlocked('Execution clock binding is malformed')
    elif 'deadline_clock' in state:
        raise ControlBlocked('Tagged execution requires its clock-bound outcome')
    if type(value) is not dict or set(value) != keys or value['schema'] not in (EXPIRY_SCHEMA, CLOCK_EXPIRY_SCHEMA):
        raise ControlBlocked('Execution outcome is malformed')
    times = [value[key] for key in ('pause_observed_at_monotonic', 'deadline_monotonic', 'sealed_at_monotonic')]
    try:
        valid_times = all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in times)
    except OverflowError:
        valid_times = False
    if (not valid_times or not times[0] < times[1] <= times[2]
            or type(state.get('deadline_monotonic')) not in (int, float)
            or value['deadline_monotonic'] != state.get('deadline_monotonic')
            or type(value['owner_epoch']) is not str or not re.fullmatch('[0-9a-f]{32}', value['owner_epoch'])
            or type(value['pre_seal_revision']) is not int or not 0 <= value['pre_seal_revision'] < MAX_REVISIONS - 1
            or type(value['pause_sequence']) is not int or not 1 <= value['pause_sequence'] <= MAX_REQUESTS):
        raise ControlBlocked('Execution outcome binding is malformed')
    _label(value['pause_request_id'], 'pause_request_id')
    for key in ('pre_seal_state_sha256', 'control_prefix_sha256'):
        if type(value[key]) is not str or not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise ControlBlocked('Execution outcome digest is malformed')
    before = deepcopy(state)
    del before[EXECUTION_OUTCOME]
    if value['pre_seal_state_sha256'] != _execution_digest(before):
        raise ControlBlocked('Sealed execution state changed')
    return deepcopy(value)


def admission_wait_state(state):
    """Validate the bounded saved, undispatched request without rebuilding it."""
    request = state.get('pending_request')
    if (state.get('status') != 'pending' or state.get('phase') != 'waiting_admission'
            or state.get('deadline_clock') != CLOCK_ID
            or type(request) is not dict or not request or request.get('stream', False) is not False
            or type(request.get('model')) is not str or not request['model']
            or type(request.get('messages')) is not list or not request['messages']
            or type(state.get('native_history')) is not list or not state['native_history']):
        raise ControlBlocked('Execution is not a saved admission wait')
    try:
        encoded = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ControlBlocked('Saved admission request is malformed') from exc
    if len(encoded) > 512 * 1024:
        raise ControlBlocked('Saved admission request exceeds its bound')
    for name, maximum in (('requests', 8), ('attempts', 8), ('admission_attempts', 32)):
        if type(state.get(name)) is not int or not 0 <= state[name] <= maximum:
            raise ControlBlocked('Admission accounting is malformed')
    if (type(state.get('admission_deferrals')) is not list
            or state['requests'] != state['attempts']
            or state['admission_attempts'] != state['requests'] + len(state['admission_deferrals'])):
        raise ControlBlocked('Admission accounting differs')
    return _execution_digest(request)


def _admission_wait_outcome(state, value):
    keys = {'schema', 'deadline_clock', 'deadline_monotonic', 'sealed_at_monotonic',
            'owner_epoch', 'pre_seal_revision', 'pre_seal_state_sha256',
            'pending_request_sha256', 'native_history_sha256', 'control_prefix_sha256',
            'request_count', 'ack_count', 'demand_state'}
    if set(value) != keys or value['deadline_clock'] != CLOCK_ID:
        raise ControlBlocked('Admission expiry schema or clock changed')
    request_hash = admission_wait_state(state)
    times = [value['deadline_monotonic'], value['sealed_at_monotonic']]
    try:
        valid = all(type(t) in (int, float) and math.isfinite(t) and t > 0 for t in times)
    except OverflowError:
        valid = False
    if (not valid or not times[0] <= times[1]
            or type(state.get('deadline_monotonic')) not in (int, float)
            or state['deadline_monotonic'] != times[0]
            or type(value['owner_epoch']) is not str or not re.fullmatch('[0-9a-f]{32}', value['owner_epoch'])
            or type(value['pre_seal_revision']) is not int or not 0 <= value['pre_seal_revision'] < MAX_REVISIONS - 1
            or type(value['request_count']) is not int or not 0 <= value['request_count'] <= MAX_REQUESTS
            or type(value['ack_count']) is not int or not 0 <= value['ack_count'] <= value['request_count']
            or value['demand_state'] not in ('waiting', 'active')):
        raise ControlBlocked('Admission expiry identity or time changed')
    for name in ('pre_seal_state_sha256', 'pending_request_sha256', 'native_history_sha256', 'control_prefix_sha256'):
        if type(value[name]) is not str or not re.fullmatch('[0-9a-f]{64}', value[name]):
            raise ControlBlocked('Admission expiry digest is malformed')
    before = deepcopy(state); del before[EXECUTION_OUTCOME]
    if (value['pre_seal_state_sha256'] != _execution_digest(before)
            or value['pending_request_sha256'] != request_hash
            or value['native_history_sha256'] != _execution_digest(state['native_history'])):
        raise ControlBlocked('Sealed admission wait changed')
    return deepcopy(value)


@dataclass(frozen=True)
class ControlNotRecorded:
    """A proved no-append outcome, distinct from an ACK or uncertain mutation."""
    request_id: str
    command: str
    reason: str = 'execution_budget_expired'

    def __post_init__(self):
        _label(self.request_id, 'request_id')
        if (type(self.command) is not str or self.command not in COMMANDS
                or type(self.reason) is not str or self.reason != 'execution_budget_expired'):
            raise ValueError('Exact bounded non-recorded refusal required')


def _find_request(requests, request_id):
    found = next((row for row in requests if row['request_id'] == request_id), None)
    if found is None:
        raise KeyError(request_id)
    return found


def _status_from_snapshot(target, found, receipts):
    """Existing result semantics shared by the original read and a full snapshot."""
    for receipt in receipts:
        if receipt['request_id'] == found['request_id']:
            return {**receipt, 'owner_acknowledged': True}
    # A terminal TaskStore cannot accept another checkpoint. This rejection
    # is derived from its durable terminal record, not invented owner ACK.
    if target.state['status'] != 'pending':
        return {**found, 'outcome': 'rejected', 'owner_acknowledged': False,
                'reason': 'target_task_terminal'}
    return {**found, 'outcome': 'pending', 'owner_acknowledged': False}


@dataclass(frozen=True)
class MailboxSnapshot:
    """Detached, bounded read evidence; never an admission reservation.

    Nested records are private copies, not a second durable log. Callers must
    not expose raw checkpoint state/metadata through a UI projection.
    """
    target: object
    mailbox_revision: int
    requests: tuple
    receipts: tuple
    demand: dict | None

    def status(self, request_id):
        _label(request_id, 'request_id')
        return _status_from_snapshot(self.target, _find_request(self.requests, request_id), self.receipts)


class Mailbox:
    def __init__(self, registry, registration_id, *, requester_capability):
        if type(registry) is not DemandRegistry or type(requester_capability) is not object:
            raise TypeError('Explicit trusted registry and private host capability required')
        self.registry = registry
        self.binding = registry._binding(registration_id)
        self.store = self.binding.store
        self.identity = self.binding.identity
        self._capability = requester_capability
        self.declaration = {'schema': 1, 'target': self.identity.metadata()}
        encoded = json.dumps(self.declaration, sort_keys=True, separators=(',', ':')).encode()
        self.task_id = 'control.' + hashlib.sha256(encoded).hexdigest()
        self.prompt = 'Record trusted host controls for ' + self.identity.task_id + '.'
        _record(self.store.load(self.identity.task_id), self.identity)
        try:
            self._requests()
        except KeyError:
            try:
                self.store.create(self.task_id, self.prompt, max_attempts=1,
                    metadata={REQUESTS: self.declaration}, state={
                        'status': 'pending', 'messages': [{'role': 'user', 'content': self.prompt}],
                        'attempts': 0, 'feedback': [], 'output': '', REQUESTS: []})
            except RevisionConflict:
                # Concurrent explicit provisioning may have won; verify exact identity.
                pass
            self._requests()

    def _requests(self):
        cp = self.store.load(self.task_id)
        return self._request_checkpoint(cp)

    def _request_checkpoint(self, cp):
        if (cp.task_id != self.task_id or cp.prompt != self.prompt or cp.max_attempts != 1
                or cp.metadata != {REQUESTS: self.declaration}
                or cp.state['status'] != 'pending' or cp.state['attempts'] != 0
                or cp.operation is not None or cp.requires_reconciliation):
            raise ControlBlocked('Mailbox identity or safe state changed')
        rows = cp.state.get(REQUESTS)
        if type(rows) is not list or len(rows) > MAX_REQUESTS:
            raise ControlBlocked('Invalid bounded mailbox')
        ids = set()
        for number, row in enumerate(rows, 1):
            if (type(row) is not dict or set(row) != {'sequence', 'request_id', 'command'}
                    or type(row['sequence']) is not int or row['sequence'] != number
                    or type(row['command']) is not str or row['command'] not in COMMANDS):
                raise ControlBlocked('Invalid ordered control request')
            _label(row['request_id'], 'request_id')
            if row['request_id'] in ids:
                raise ControlBlocked('Duplicate persisted control identity')
            ids.add(row['request_id'])
        return cp, deepcopy(rows)

    def _acks(self, cp, requests):
        _record(cp, self.identity)
        record = cp.state.get(ACKS)
        if record is None:
            return []
        if (type(record) is not dict or set(record) != {'mailbox_task_id', 'receipts'}
                or record['mailbox_task_id'] != self.task_id
                or type(record['receipts']) is not list
                or len(record['receipts']) > len(requests)):
            raise ControlBlocked('Acknowledgement binding or count changed')
        for request, receipt in zip(requests, record['receipts']):
            if (type(receipt) is not dict
                    or set(receipt) != set(request) | {'outcome', 'demand_state', 'acknowledged_at_utc'}
                    or type(receipt['sequence']) is not int
                    or any(receipt.get(key) != value for key, value in request.items())
                    or receipt['outcome'] not in ('applied', 'rejected')
                    or receipt['demand_state'] not in ('active', 'waiting', 'paused', 'cancelled', 'fulfilled')):
                raise ControlBlocked('Acknowledgement is not an ordered request prefix')
            if (receipt['outcome'] == 'applied'
                    and receipt['demand_state'] != COMMANDS[request['command']]):
                raise ControlBlocked('Applied receipt disagrees with requested transition')
            if receipt['outcome'] == 'rejected' and receipt['demand_state'] not in ('cancelled', 'fulfilled'):
                raise ControlBlocked('Rejection lacks terminal demand evidence')
            _utc(receipt['acknowledged_at_utc'])
        return deepcopy(record['receipts'])

    def status(self, request_id):
        """Read recorded versus owner-acknowledged state; never claims ownership."""
        _label(request_id, 'request_id')
        # Read ACKs first: every ACK follows its append-only request commit.
        # The later request snapshot can contain extra commands, but cannot
        # legitimately contain fewer than this earlier ACK prefix. Reversing
        # these reads could mistake concurrent valid progress for corruption.
        target = self.store.load(self.identity.task_id)
        _, requests = self._requests()
        found = _find_request(requests, request_id)
        receipts = self._acks(target, requests)
        return _status_from_snapshot(target, found, receipts)

    def snapshot(self):
        """Validate bound task, requests and ACK prefix in one read transaction.

        The existing TaskStore gate covers the entire transaction. Do not call
        connection-opening helpers within this context. No target is claimed,
        no operation is acknowledged, and a later command can follow this read.
        """
        with self.store._connection() as db:
            target = self.store._read(db, self.identity.task_id)
            mailbox, requests = self._request_checkpoint(self.store._read(db, self.task_id))
            receipts = self._acks(target, requests)
            demand = deepcopy(_record(target, self.identity))
            return MailboxSnapshot(target, mailbox.revision, tuple(requests), tuple(receipts), demand)

    def submit(self, capability, request_id, command):
        """Commit promptly without the target's owner lock or Recovery RLock.

        TaskStore may report bounded SQLite contention or a busy mailbox writer.
        The caller may retry the same ID; no hidden overwrite, sleep or rotation.
        """
        if capability is not self._capability:
            raise OwnershipError('Caller lacks the trusted host control capability')
        _label(request_id, 'request_id')
        if type(command) is not str or command not in COMMANDS:
            raise ValueError('Only pause, resume and cancel are supported')
        cp, requests = self._requests()
        for row in requests:
            if row['request_id'] == request_id:
                if row['command'] != command:
                    raise ValueError('Request ID cannot be reused for a different command')
                return self.status(request_id)
        target = self.store.load(self.identity.task_id)
        _record(target, self.identity)
        if execution_outcome(target.state) is not None:
            return ControlNotRecorded(request_id, command)
        if target.state['status'] != 'pending':
            raise TerminalTaskError('Cannot submit new controls to a terminal task')
        if len(requests) >= MAX_REQUESTS:
            raise ControlBlocked('Mailbox lifetime request limit reached; no command removed')
        with self.store.claim(self.task_id, expected_revision=cp.revision,
                              owner_id='trusted-control-requester') as mailbox_owner:
            # The target seal and mailbox append share the existing SQLite
            # writer transaction; an earlier observation is not a reservation.
            with self.store._connection(write=True) as db:
                current = mailbox_owner._check(db, mailbox_owner.checkpoint.revision)
                _, current_requests = self._request_checkpoint(current)
                if current_requests != requests:
                    raise ControlBlocked('Mailbox changed before append')
                target = self.store._read(db, self.identity.task_id)
                _record(target, self.identity)
                if execution_outcome(target.state) is not None:
                    return ControlNotRecorded(request_id, command)
                state = deepcopy(current.state)
                state[REQUESTS].append({'sequence': len(requests) + 1,
                                       'request_id': request_id, 'command': command})
                saved = self.store._write(db, current, state=state, operation=None,
                    reconciliation=False, epoch=mailbox_owner._epoch, event='checkpoint')
            mailbox_owner.checkpoint = saved
        return self.status(request_id)

    def admission_wait_candidate(self, snapshot, *, allow_sealed=False):
        """Strict coherent state only; not proof of cleanup or a resource grant."""
        if type(snapshot) is not MailboxSnapshot:
            raise ControlBlocked('Exact mailbox snapshot required')
        cp = snapshot.target
        requests, receipts = list(snapshot.requests), list(snapshot.receipts)
        demand = _record(cp, self.identity)
        marker = execution_outcome(cp.state)
        if (cp.task_id != self.identity.task_id or cp.operation is not None or cp.requires_reconciliation
                or demand is None or demand['state'] not in ('waiting', 'active')
                or demand != snapshot.demand or self._acks(cp, requests) != receipts
                or any(row['command'] != 'pause' for row in requests[len(receipts):])
                or marker is not None and (not allow_sealed or marker['schema'] != WAIT_EXPIRY_SCHEMA)):
            raise ControlBlocked('Admission wait or unapplied control prefix is unsafe')
        pending_hash = admission_wait_state(cp.state)
        if marker is None:
            if type(cp.owner_epoch) is not str or not re.fullmatch('[0-9a-f]{32}', cp.owner_epoch):
                raise ControlBlocked('Admission wait has no exact current owner')
        elif (marker['control_prefix_sha256'] != control_prefix_digest(requests, receipts)
                or marker['request_count'] != len(requests) or marker['ack_count'] != len(receipts)
                or marker['demand_state'] != demand['state']):
            raise ControlBlocked('Sealed admission control prefix changed')
        return {'owner_epoch': cp.owner_epoch, 'target_revision': cp.revision,
                'state_sha256': _execution_digest(cp.state), 'pending_request_sha256': pending_hash,
                'native_history_sha256': _execution_digest(cp.state['native_history']),
                'demand_state': demand['state'], 'requests': requests, 'receipts': receipts}

    def _owned_admission_wait(self, db, owned):
        if (type(owned) is not OwnedTask or owned._store.path != self.store.path
                or owned.checkpoint.task_id != self.identity.task_id):
            raise OwnershipError('Admission expiry requires the exact target owner')
        cp = owned._check(db, owned.checkpoint.revision)
        mailbox, requests = self._request_checkpoint(self.store._read(db, self.task_id))
        receipts = self._acks(cp, requests)
        snapshot = MailboxSnapshot(cp, mailbox.revision, tuple(requests), tuple(receipts),
                                  deepcopy(_record(cp, self.identity)))
        return cp, self.admission_wait_candidate(snapshot)

    def admission_wait_observation(self, owned):
        with self.store._connection() as db:
            return self._owned_admission_wait(db, owned)[1]

    def seal_admission_wait(self, owned, *, observed_wait, deadline_monotonic,
                            sealed_at_monotonic, deadline_clock):
        """Preserve the saved request; only late unapplied Pause may extend controls."""
        with self.store._connection(write=True) as db:
            cp, current = self._owned_admission_wait(db, owned)
            if (type(observed_wait) is not dict or set(observed_wait) != set(current)
                    or any(type(observed_wait[k]) is not type(v) or observed_wait[k] != v
                           for k, v in current.items() if k not in ('requests', 'receipts'))
                    or observed_wait['receipts'] != current['receipts']
                    or type(observed_wait['requests']) is not list
                    or current['requests'][:len(observed_wait['requests'])] != observed_wait['requests']
                    or deadline_clock != CLOCK_ID or cp.metadata.get('deadline_clock') != CLOCK_ID):
                raise ControlBlocked('Observed admission checkpoint changed during cleanup')
            marker = {'schema': WAIT_EXPIRY_SCHEMA, 'deadline_clock': CLOCK_ID,
                'deadline_monotonic': deadline_monotonic, 'sealed_at_monotonic': sealed_at_monotonic,
                'owner_epoch': cp.owner_epoch, 'pre_seal_revision': cp.revision,
                'pre_seal_state_sha256': current['state_sha256'],
                'pending_request_sha256': current['pending_request_sha256'],
                'native_history_sha256': current['native_history_sha256'],
                'control_prefix_sha256': control_prefix_digest(current['requests'], current['receipts']),
                'request_count': len(current['requests']), 'ack_count': len(current['receipts']),
                'demand_state': current['demand_state']}
            state = deepcopy(cp.state); state[EXECUTION_OUTCOME] = marker
            execution_outcome(state)
            saved = self.store._write(db, cp, state=state, operation=None,
                reconciliation=False, epoch=owned._epoch, event='checkpoint')
        owned.checkpoint = saved
        return deepcopy(marker)

    def _paused_execution(self, db, owned, *, allow_pending=False):
        if (type(owned) is not OwnedTask or owned._store.path != self.store.path
                or owned.checkpoint.task_id != self.identity.task_id):
            raise OwnershipError('Execution seal requires the exact target owner')
        cp = owned._check(db, owned.checkpoint.revision)
        _, requests = self._request_checkpoint(self.store._read(db, self.task_id))
        receipts = self._acks(cp, requests)
        demand = _record(cp, self.identity)
        if (execution_outcome(cp.state) is not None or cp.state['status'] != 'pending'
                or cp.operation is not None or cp.requires_reconciliation
                or demand is None or demand['state'] != 'paused'
                or not requests or not receipts
                or receipts[-1]['command'] != 'pause' or receipts[-1]['outcome'] != 'applied'):
            raise ControlBlocked('Execution expiry lacks its complete applied Pause prefix')
        if len(receipts) != len(requests):
            # A host append after consume is ordinary observation progress.
            # Ownership/schema/ACK checks above still precede this classification.
            if allow_pending is True:
                return None
            raise ControlBlocked('Execution expiry lacks its complete applied Pause prefix')
        return cp, requests, receipts

    def paused_execution_observation(self, owned):
        """Bind a coherent applied Pause, or return None for validated new controls."""
        with self.store._connection() as db:
            observed = self._paused_execution(db, owned, allow_pending=True)
            if observed is None:
                return None
            cp, requests, receipts = observed
            return {'owner_epoch': cp.owner_epoch, 'target_revision': cp.revision,
                    'pause_request_id': requests[-1]['request_id'],
                    'pause_sequence': requests[-1]['sequence'],
                    'control_prefix_sha256': control_prefix_digest(requests, receipts)}

    def seal_paused_execution(self, owned, *, deadline_monotonic,
                              pause_observed_at_monotonic, observed_pause, sealed_at_monotonic,
                              deadline_clock=None):
        """Seal only the exact previously observed Pause, atomically with its prefix."""
        with self.store._connection(write=True) as db:
            cp, requests, receipts = self._paused_execution(db, owned)
            expected = {'owner_epoch': cp.owner_epoch, 'target_revision': cp.revision,
                        'pause_request_id': requests[-1]['request_id'],
                        'pause_sequence': requests[-1]['sequence'],
                        'control_prefix_sha256': control_prefix_digest(requests, receipts)}
            if (type(observed_pause) is not dict or observed_pause != expected
                    or any(type(observed_pause[k]) is not type(v) for k, v in expected.items())):
                raise ControlBlocked('Applied Pause changed after its pre-deadline observation')
            marker = {'schema': EXPIRY_SCHEMA, 'deadline_monotonic': deadline_monotonic,
                      'pause_observed_at_monotonic': pause_observed_at_monotonic,
                      'sealed_at_monotonic': sealed_at_monotonic, 'owner_epoch': cp.owner_epoch,
                      'pre_seal_revision': cp.revision, 'pre_seal_state_sha256': _execution_digest(cp.state),
                      'pause_request_id': expected['pause_request_id'], 'pause_sequence': expected['pause_sequence'],
                      'control_prefix_sha256': expected['control_prefix_sha256']}
            if deadline_clock is not None:
                if deadline_clock != CLOCK_ID or cp.state.get('deadline_clock') != CLOCK_ID:
                    raise ControlBlocked('Execution clock changed before sealing')
                marker.update(schema=CLOCK_EXPIRY_SCHEMA, deadline_clock=CLOCK_ID)
            state = deepcopy(cp.state)
            state[EXECUTION_OUTCOME] = marker
            execution_outcome(state)
            saved = self.store._write(db, cp, state=state, operation=None,
                reconciliation=False, epoch=owned._epoch, event='checkpoint')
        owned.checkpoint = saved
        return deepcopy(marker)

    def _owned_snapshot(self, owned):
        if (type(owned) is not OwnedTask or owned._store.path != self.store.path
                or owned.checkpoint.task_id != self.identity.task_id):
            raise OwnershipError('Control acknowledgement requires the exact target owner')
        with self.store._connection() as db:
            cp = owned._check(db, owned.checkpoint.revision)
            _record(cp, self.identity)
            return cp

    def consume(self, owned, *, updated_at_utc):
        """Apply ordered controls on the owner thread at an explicitly safe point.

        Existing demand.transition and ACK save are separate durable commits.
        A failure between them leaves the request pending; the next call repeats
        the same idempotent transition before acknowledging. No operation may
        start between these steps or after a consume failure.
        """
        _utc(updated_at_utc)
        cp = self._owned_snapshot(owned)
        _, requests = self._requests()
        receipts = self._acks(cp, requests)
        if cp.operation is not None or cp.requires_reconciliation:
            return {'allowed': False, 'reason': 'operation_inflight_or_reconciliation',
                    'pending': len(requests) - len(receipts), 'acknowledged': len(receipts)}
        for request in requests[len(receipts):]:
            # No ValueError catch around transition: malformed state/identity
            # remains a hard refusal, never converted to a normal rejection.
            record = _record(owned.checkpoint, self.identity)
            state = None if record is None else record['state']
            wanted = COMMANDS[request['command']]
            rejected = state in ('cancelled', 'fulfilled') and state != wanted
            if not rejected:
                self.registry.transition(self.identity.registration_id, owned, wanted,
                    expected_revision=owned.checkpoint.revision,
                    updated_at_utc=updated_at_utc, reason='trusted host control ' + request['request_id'])
                state = wanted
            receipt = {**request, 'outcome': 'rejected' if rejected else 'applied',
                       'demand_state': state, 'acknowledged_at_utc': updated_at_utc}
            next_state = deepcopy(owned.checkpoint.state)
            next_state[ACKS] = {'mailbox_task_id': self.task_id,
                               'receipts': receipts + [receipt]}
            owned.save_checkpoint(next_state, expected_revision=owned.checkpoint.revision)
            receipts.append(receipt)
        record = _record(owned.checkpoint, self.identity)
        state = None if record is None else record['state']
        # Re-read pending commands because another requester may have appended
        # during consumption. This is a safe-point observation, not reservation.
        _, latest = self._requests()
        self._acks(owned.checkpoint, latest)
        pending = len(latest) - len(receipts)
        return {'allowed': pending == 0 and state in ('active', 'waiting'),
                'reason': 'pending_control' if pending else 'demand_' + str(state),
                'pending': pending, 'acknowledged': len(receipts)}

    def begin_operation(self, owned, kind, *, updated_at_utc, details=None):
        """Cooperative final safe point before the existing operation ledger.

        A request recorded after the last mailbox read can remain pending while
        this operation executes. It is not acknowledged until a later safe point.
        This is not an atomic cross-record admission gate or forced cancellation.
        """
        boundary = self.consume(owned, updated_at_utc=updated_at_utc)
        if not boundary['allowed']:
            raise ControlBlocked(boundary['reason'])
        return owned.begin_operation(kind, details=details,
                                     expected_revision=owned.checkpoint.revision)
