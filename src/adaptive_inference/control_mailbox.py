# SPDX-License-Identifier: Apache-2.0
"""Bounded trusted controls, reusing TaskStore and DemandRegistry unchanged.

Recording is not acknowledgement. Only the actual owner applies demand at a
safe boundary. No service, transport, new schema, process control or replay.
See docs/task-controls.md for the authority boundary and two-commit crash gap.
"""
from copy import deepcopy
import hashlib
import json

from adaptive_inference.demand import DemandRegistry, _label, _record, _utc
from adaptive_inference.task_store import (
    OwnedTask, OwnershipError, RevisionConflict,
    TaskStoreError, TerminalTaskError,
)

REQUESTS = 'adaptive_inference.control_requests.v1'
ACKS = 'adaptive_inference.control_acks.v1'
MAX_REQUESTS = 32
COMMANDS = {'pause': 'paused', 'resume': 'waiting', 'cancel': 'cancelled'}


class ControlBlocked(TaskStoreError):
    """Cooperating host must not start another operation at this boundary."""


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
        if (cp.prompt != self.prompt or cp.max_attempts != 1
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
        found = next((row for row in requests if row['request_id'] == request_id), None)
        if found is None:
            raise KeyError(request_id)
        receipts = self._acks(target, requests)
        for receipt in receipts:
            if receipt['request_id'] == request_id:
                return {**receipt, 'owner_acknowledged': True}
        # A terminal TaskStore cannot accept another checkpoint. This rejection
        # is derived from its durable terminal record, not invented owner ACK.
        if target.state['status'] != 'pending':
            return {**found, 'outcome': 'rejected', 'owner_acknowledged': False,
                    'reason': 'target_task_terminal'}
        return {**found, 'outcome': 'pending', 'owner_acknowledged': False}

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
        if target.state['status'] != 'pending':
            raise TerminalTaskError('Cannot submit new controls to a terminal task')
        if len(requests) >= MAX_REQUESTS:
            raise ControlBlocked('Mailbox lifetime request limit reached; no command removed')
        with self.store.claim(self.task_id, expected_revision=cp.revision,
                              owner_id='trusted-control-requester') as mailbox_owner:
            state = deepcopy(mailbox_owner.checkpoint.state)
            state[REQUESTS].append({'sequence': len(requests) + 1,
                                   'request_id': request_id, 'command': command})
            mailbox_owner.save_checkpoint(state,
                expected_revision=mailbox_owner.checkpoint.revision)
        return self.status(request_id)

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
