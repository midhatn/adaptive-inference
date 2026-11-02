# SPDX-License-Identifier: Apache-2.0
"""Private storage/projection prototype; not a host launch or release authority.

Reuses TaskStore, its existing claims and BEGIN IMMEDIATE transaction, immutable
expiry seals and current recovery receipt checks. See API.private.md and retained
Temporal/LangGraph/SQLite research. No SDK, executor, new database or renewal loop.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import math
from pathlib import Path

from adaptive_inference.task_store import (
    TaskStore, OwnedTask, OwnershipError, RevisionConflict, ReconciliationRequired,
    _copy, _task_id,
)
from adaptive_inference.control_mailbox import (
    EXECUTION_OUTCOME, ACKS, CLOCK_EXPIRY_SCHEMA, COMMANDS,
    execution_outcome, control_prefix_digest, WAIT_EXPIRY_SCHEMA,
    Mailbox, MailboxSnapshot,
)
from adaptive_inference.demand import DemandIdentity, NAMESPACE, _record, _utc
from adaptive_inference.execution_clock import CLOCK_ID, execution_now
from adaptive_inference.desktop.execution_budget import BUDGET, BudgetError, validate_budget
from adaptive_inference.desktop.hermes.recovery import digest, verify_tool_rows, verify_validation_rows

AUTHORITY = 'adaptive_inference.continuation_authority.v1'
LINK = 'adaptive_inference.execution_authorization.v1'
MAX_GRANTS = 32
PENDING_DISPOSITION = 'adaptive.pending-request-supersession.v1'
STATE_REQUIRED = frozenset(('status', 'messages', 'attempts', 'feedback', 'output', 'phase',
    'session_id', 'native_history', 'tools', 'requests', 'admission_attempts', 'admission_deferrals',
    'pending_request', 'deadline_monotonic', 'deadline_clock', NAMESPACE))
STATE_OPTIONAL = frozenset(('validation_rejections', 'completion_candidate', ACKS, EXECUTION_OUTCOME, BUDGET))
SCOPE_FIELDS = frozenset(('plan_sha256', 'session_id', 'native_db', 'work_dir',
                          'effect_receipts', 'wire_observations', 'gateway'))
WIRE_FIELDS = frozenset(('phase', 'url', 'method', 'class', 'model', 'quality', 'body_sha256',
    'messages_sha256', 'tools_sha256', 'tool_names', 'started_at', 'finished_at', 'finish_reason',
    'usage', 'gateway_request_id', 'response_sha256', 'assistant_sha256'))


def require(condition, message):
    if not condition:
        raise ReconciliationRequired(message)


def sha(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'Exact SHA256 identity required')
    return value


def identity(metadata):
    row = metadata[NAMESPACE]
    require(type(row) is dict and type(row.get('schema')) is int and row['schema'] == 1 and set(row) ==
            {'schema', 'registration_id', 'task_id', 'owner_id', 'arrived_at_utc'}, 'Demand identity changed')
    return DemandIdentity(**{key: value for key, value in row.items() if key != 'schema'})


def safe_state(cp, *, sealed):
    state = cp.state
    require(STATE_REQUIRED <= set(state) <= STATE_REQUIRED | STATE_OPTIONAL, 'Unknown recovery state field')
    marker = execution_outcome(state)
    waiting = sealed and marker is not None and marker['schema'] == WAIT_EXPIRY_SCHEMA
    safe_phase = (state['phase'] == 'waiting_admission' and type(state['pending_request']) is dict
                  and state['pending_request'].get('model') == cp.metadata.get('model')) if waiting else (
                  state['phase'] == 'ready' and state['pending_request'] is None)
    require(cp.max_attempts == 8 and state['status'] == 'pending' and safe_phase
            and cp.operation is None and not cp.requires_reconciliation,
            'Execution is not a complete safe checkpoint')
    require(state['deadline_clock'] == CLOCK_ID and cp.metadata.get('deadline_clock') == CLOCK_ID,
            'Execution clock changed')
    if BUDGET in state:
        try:
            budget = validate_budget(state[BUDGET])
        except BudgetError as error:
            raise ReconciliationRequired('Invalid execution-budget record') from error
        require(budget['episode']['deadline'] == state['deadline_monotonic'],
                'Execution-budget deadline changed')
    for field, maximum in (('attempts', 8), ('requests', 8), ('admission_attempts', 32)):
        require(type(state[field]) is int and 0 <= state[field] <= maximum, 'Cumulative counter malformed')
    require(type(state['admission_deferrals']) is list and
            state['attempts'] == state['requests'] and
            state['admission_attempts'] == state['requests'] + len(state['admission_deferrals']),
            'Cumulative admission/request accounting differs')
    require((marker is not None) is sealed, 'Execution seal state differs')
    verify_tool_rows(state['native_history'], state['tools'])
    verify_validation_rows(state['native_history'], state, cp.metadata.get('pre_effect_validator'))
    return marker


def wire_rows(raw, cp, scope):
    from adaptive_inference.desktop.hermes.recovery import task_contract
    spec = task_contract(cp)
    compiler = spec is not None and spec.compiler is not None
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate wire key')
            result[key] = value
        return result
    require(len(raw) <= 1024 * 1024, 'Wire ledger exceeds bound')
    rows = json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite wire field')))
    require(type(rows) is list and len(rows) == cp.state['requests'] <= 8, 'Wire count differs from cumulative requests')
    bodies = set()
    for row in rows:
        require(type(row) is dict and set(row) == WIRE_FIELDS, 'Incomplete or unknown wire row')
        for field in ('body_sha256', 'messages_sha256', 'tools_sha256', 'response_sha256', 'assistant_sha256'):
            sha(row[field])
        require(row['body_sha256'] not in bodies, 'Duplicate serialized wire request')
        bodies.add(row['body_sha256'])
        require(row['model'] == cp.metadata['model'] and digest(row['quality']) == digest(cp.metadata['quality'])
                and row['method'] == 'POST' and row['url'] == scope['gateway'] + '/chat/completions'
                and row['phase'] == 'parent' and row['class'] == 'normal'
                and row['finish_reason'] in ('stop', 'tool_calls'), 'Wire model/quality/route changed')
        if compiler:
            require(type(row['tool_names']) is list and len(row['tool_names']) == 3
                    and set(row['tool_names']) == {'read_file', 'write_file', 'build_and_test'},
                    'Wire compiler tool scope changed')
        else:
            require(type(row['tool_names']) is list and {'read_file', 'write_file'} <= set(row['tool_names'])
                    <= {'read_file', 'write_file', 'patch', 'search_files'}, 'Wire tool scope changed')
        times = [row[k] for k in ('started_at', 'finished_at')]
        require(all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in times)
                and times[0] <= times[1], 'Incomplete wire response')
        usage = row['usage']
        require(type(usage) is dict and all(type(usage.get(k)) is int and usage[k] >= 0
                for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                and usage['prompt_tokens'] + usage['completion_tokens'] == usage['total_tokens']
                and usage['completion_tokens'] <= 10923
                and usage['prompt_tokens'] + 10923 + 8 <= 65536, 'Wire usage accounting changed')
    return rows


class ContinuationAuthority:
    def __init__(self, store, logical_task_id, scope, *, host_generation, clock=execution_now):
        require(type(store) is TaskStore, 'Exact TaskStore required')
        self.store, self.logical_task_id, self.clock = store, _task_id(logical_task_id), clock
        self.host_generation = _task_id(host_generation)
        require(callable(clock) and type(scope) is dict and set(scope) == SCOPE_FIELDS, 'Explicit continuation scope required')
        self.scope = _copy(scope)
        sha(scope['plan_sha256'])
        require(all(type(value) is str and value for value in scope.values()), 'Scope fields must be explicit')
        for name in ('native_db', 'work_dir', 'effect_receipts', 'wire_observations'):
            require(str(Path(scope[name]).resolve()) == scope[name], 'Scope paths must be resolved')
        original = store.load(logical_task_id)
        require(original.state['session_id'] == scope['session_id'], 'Original session scope changed')
        self.declaration = {AUTHORITY: {'logical_task_id': logical_task_id, 'host_generation': host_generation, 'scope': self.scope,
            'prompt': original.prompt, 'max_attempts': original.max_attempts, 'metadata': original.metadata}}
        self.task_id = 'continue.' + digest(logical_task_id)
        self.prompt = 'Record explicit continuation grants for ' + logical_task_id + '.'
        try:
            cp = store.load(self.task_id)
        except KeyError:
            try:
                cp = store.create(self.task_id, self.prompt, max_attempts=1, metadata=self.declaration,
                    state={'status': 'pending', 'messages': [{'role': 'user', 'content': self.prompt}],
                           'attempts': 0, 'feedback': [], 'output': '',
                           AUTHORITY: {'selected_execution': logical_task_id, 'execution_generation': 0, 'grants': []}})
            except RevisionConflict:
                cp = store.load(self.task_id)
        # Binding an existing authority is read-only, including for historical
        # duplicate lookup during an unfinished lifecycle. Mutation gates below
        # still require a clean authority under its actual claim.
        self._authority(cp, historical_lookup=True)

    def _authority(self, cp, *, historical_lookup=False):
        require(cp.task_id == self.task_id and cp.prompt == self.prompt and cp.max_attempts == 1
                and digest(cp.metadata) == digest(self.declaration),
                'Logical authority identity or operation changed')
        if not historical_lookup:
            require(cp.operation is None and not cp.requires_reconciliation,
                    'Logical authority has an unfinished worker lifecycle')
        require(set(cp.state) == {'status', 'messages', 'attempts', 'feedback', 'output', AUTHORITY}
                and cp.state['status'] == 'pending' and cp.state['attempts'] == 0, 'Authority state changed')
        row = cp.state[AUTHORITY]
        require(type(row) is dict and set(row) == {'selected_execution', 'execution_generation', 'grants'}
                and type(row['grants']) is list and len(row['grants']) <= MAX_GRANTS
                and type(row['execution_generation']) is int and row['execution_generation'] == len(row['grants']),
                'Authority generation/count changed')
        previous, commands, executions = self.logical_task_id, set(), {self.logical_task_id}
        for number, grant in enumerate(row['grants'], 1):
            payload = grant['payload']
            require(grant['payload_sha256'] == digest(payload) and payload['command_id'] not in commands
                    and payload['predecessor_id'] == previous and payload['successor_id'] not in executions
                    and type(grant['execution_generation']) is int and grant['execution_generation'] == number,
                    'Grant chain or command changed')
            commands.add(payload['command_id']); previous = payload['successor_id']; executions.add(previous)
        require(row['selected_execution'] == previous, 'Selected execution differs from grant chain')
        return row

    def request(self, *, command_id, predecessor_id, predecessor_revision, predecessor_seal_sha256,
                successor_id, identity, host_generation, release_evidence_sha256, budget_s=900):
        for value in (command_id, predecessor_id, successor_id, host_generation):
            _task_id(value)
        require(host_generation == self.host_generation, 'Authority belongs to another host generation')
        require(type(predecessor_revision) is int and predecessor_revision >= 0
                and type(budget_s) is int and budget_s == 900, 'Explicit bounded authorization required')
        require(type(identity) is DemandIdentity and identity.task_id == successor_id
                and successor_id not in (self.task_id, predecessor_id, self.logical_task_id), 'Fresh execution identity required')
        return {'command_id': command_id, 'logical_task_id': self.logical_task_id,
                'predecessor_id': predecessor_id, 'predecessor_revision': predecessor_revision,
                'predecessor_seal_sha256': sha(predecessor_seal_sha256), 'successor_id': successor_id,
                'demand_identity': identity.metadata(), 'host_generation': host_generation,
                'release_evidence_sha256': sha(release_evidence_sha256), 'budget_s': budget_s,
                'deadline_clock': CLOCK_ID, 'scope_sha256': digest(self.scope)}

    def _payload(self, payload):
        require(type(payload) is dict and set(payload) == {'command_id', 'logical_task_id', 'predecessor_id',
            'predecessor_revision', 'predecessor_seal_sha256', 'successor_id', 'demand_identity', 'host_generation',
            'release_evidence_sha256', 'budget_s', 'deadline_clock', 'scope_sha256'}, 'Authorization payload fields changed')
        reconstructed = self.request(**{key: payload[key] for key in ('command_id', 'predecessor_id',
            'predecessor_revision', 'predecessor_seal_sha256', 'successor_id', 'host_generation',
            'release_evidence_sha256', 'budget_s')}, identity=identity({NAMESPACE: payload['demand_identity']}))
        require(digest(reconstructed) == digest(payload), 'Authorization identity changed')
        return deepcopy(payload)

    @staticmethod
    def _find(row, payload):
        for grant in row['grants']:
            if grant['payload']['command_id'] == payload['command_id']:
                if digest(grant['payload']) != digest(payload):
                    raise RevisionConflict('Command ID already binds another authorization')
                return deepcopy(grant)
        return None

    def lookup(self, payload):
        payload = self._payload(payload)
        # Historical response only: an active/unknown lifecycle does not erase
        # the immutable grant and this read cannot clear its execution fence.
        return self._find(self._authority(self.store.load(self.task_id), historical_lookup=True), payload)

    def _owned(self, owned, db):
        if type(owned) is not OwnedTask or owned._store.path != self.store.path or owned.checkpoint.task_id != self.task_id:
            raise OwnershipError('Exact logical authority claim required')
        cp = owned._check(db, owned.checkpoint.revision)
        return cp, self._authority(cp)

    def _predecessor(self, db, payload, authority):
        require(authority['selected_execution'] == payload['predecessor_id'], 'Predecessor already has a selected successor')
        cp = self.store._read(db, payload['predecessor_id'])
        self.store._revision(cp, payload['predecessor_revision'])
        require(cp.owner_epoch is None, 'Predecessor still has an owner')
        marker = safe_state(cp, sealed=True)
        require(marker['schema'] in (CLOCK_EXPIRY_SCHEMA, WAIT_EXPIRY_SCHEMA)
                and digest(marker) == payload['predecessor_seal_sha256']
                and cp.revision == marker['pre_seal_revision'] + 1, 'Exact predecessor seal required')
        history = list(db.execute('SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision', (cp.task_id,)))
        require(len(history) == cp.revision + 1 and [row[0] for row in history] == list(range(cp.revision + 1)),
                'Incomplete predecessor history')
        before = json.loads(history[-2][2])['state']; final = json.loads(history[-1][2])
        require(digest(before) == marker['pre_seal_state_sha256'] and final['state'] == cp.state
                and final['operation'] is None and final['requires_reconciliation'] is False,
                'Predecessor history differs from exact seal')
        inherited = deepcopy(cp.metadata); inherited.pop(NAMESPACE); inherited.pop(LINK, None)
        original = deepcopy(self.declaration[AUTHORITY]['metadata']); original.pop(NAMESPACE)
        require(digest(inherited) == digest(original) and cp.prompt == self.declaration[AUTHORITY]['prompt']
                and cp.max_attempts == self.declaration[AUTHORITY]['max_attempts']
                and cp.state['session_id'] == self.scope['session_id'], 'Logical objective/session/quality changed')
        if authority['grants']:
            previous = authority['grants'][-1]
            require(cp.metadata.get(LINK) == {'logical_task_id': self.logical_task_id, 'execution_id': cp.task_id,
                'execution_generation': previous['execution_generation'], 'command_id': previous['payload']['command_id'],
                'payload_sha256': previous['payload_sha256']}, 'Predecessor execution linkage changed')
        else:
            require(LINK not in cp.metadata, 'Initial task unexpectedly has an execution link')
        old_identity = identity(cp.metadata); new_identity = identity({NAMESPACE: payload['demand_identity']})
        require(new_identity.registration_id != old_identity.registration_id
                and new_identity.owner_id == old_identity.owner_id, 'Fresh demand registration and same host lineage required')
        if marker['schema'] == WAIT_EXPIRY_SCHEMA:
            self._wait_prefix(db, cp)
        else:
            require(_record(cp, old_identity)['state'] == 'paused', 'Predecessor demand is not paused')
            acks = cp.state[ACKS]['receipts']
            requests = [{k: receipt[k] for k in ('sequence', 'request_id', 'command')} for receipt in acks]
            require(bool(acks) and len(acks) <= 32 and [r['sequence'] for r in requests] == list(range(1, len(acks)+1))
                    and len({r['request_id'] for r in requests}) == len(acks), 'Pause prefix is incomplete')
            for receipt in acks:
                require(set(receipt) == {'sequence', 'request_id', 'command', 'outcome', 'demand_state', 'acknowledged_at_utc'}
                        and type(receipt['sequence']) is int and receipt['command'] in COMMANDS
                        and receipt['outcome'] in ('applied', 'rejected'), 'Pause receipt changed')
                _utc(receipt['acknowledged_at_utc'])
            require(acks[-1]['command'] == 'pause' and acks[-1]['outcome'] == 'applied'
                    and acks[-1]['request_id'] == marker['pause_request_id'] and acks[-1]['sequence'] == marker['pause_sequence']
                    and control_prefix_digest(requests, acks) == marker['control_prefix_sha256'], 'Sealed Pause prefix changed')
        require(cp.state['requests'] < 8 and cp.state['attempts'] < 8 and cp.state['admission_attempts'] < 32,
                'Cumulative capacity is spent')
        return cp, marker, history

    def _wait_prefix(self, db, cp):
        """Use existing validators without provisioning or opening a second SQL view."""
        # Mailbox.__init__ is the trusted provisioning API. Authorization must
        # instead fail when its existing mailbox is missing, so bind only the
        # identity needed by its pure checkpoint/prefix validators.
        box = object.__new__(Mailbox)
        box.identity = identity(cp.metadata)
        box.declaration = {'schema': 1, 'target': box.identity.metadata()}
        box.task_id = 'control.' + digest(json.dumps(box.declaration, sort_keys=True, separators=(',', ':')).encode())
        box.prompt = 'Record trusted host controls for ' + box.identity.task_id + '.'
        mailbox, requests = box._request_checkpoint(self.store._read(db, box.task_id))
        receipts = box._acks(cp, requests)
        snapshot = MailboxSnapshot(cp, mailbox.revision, tuple(requests), tuple(receipts),
                                  deepcopy(_record(cp, box.identity)))
        return box.admission_wait_candidate(snapshot, allow_sealed=True)

    def authorize(self, owned_authority, payload):
        payload = self._payload(payload)
        with self.store._connection(write=True) as db:
            authority_cp, authority = self._owned(owned_authority, db)
            duplicate = self._find(authority, payload)
            if duplicate is not None:
                return duplicate
            require(len(authority['grants']) < MAX_GRANTS, 'Continuation grant bound reached')
            cp, marker, history = self._predecessor(db, payload, authority)
            raw = Path(self.scope['wire_observations']).read_bytes()
            rows = wire_rows(raw, cp, self.scope)
            if authority['grants']:
                self._inherited_grant(db, cp, authority['grants'][-1], rows)
            now = self.clock()
            require(type(now) in (int, float) and math.isfinite(now) and now >= marker['sealed_at_monotonic']
                    and math.isfinite(now + 900) and now + 900 > now,
                    'Current host clock does not follow sealed predecessor')
            generation = authority['execution_generation'] + 1
            grant = {'payload': payload, 'payload_sha256': digest(payload), 'execution_generation': generation,
                     'authorized_at': now, 'deadline_monotonic': now + 900, 'deadline_clock': CLOCK_ID,
                     'predecessor_state_sha256': digest(cp.state),
                     'predecessor_history_sha256': digest([list(row) for row in history]),
                     'wire_prefix_count': len(rows), 'wire_prefix_sha256': digest(rows),
                     'wire_row_sha256': [digest(row) for row in rows],
                     'wire_body_sha256': [row['body_sha256'] for row in rows],
                     'wire_file_sha256': digest(raw), 'release_proven_by_store': False}
            state = deepcopy(cp.state)
            if marker['schema'] == WAIT_EXPIRY_SCHEMA:
                grant['pending_request_disposition'] = {
                    'schema': PENDING_DISPOSITION, 'mode': 'rebuild_from_saved_conversation',
                    'request_sha256': marker['pending_request_sha256']}
                # Hermes rebuilds its next turn from saved native history. The
                # exact superseded provider request remains in the predecessor.
                state.update(phase='ready', pending_request=None)
            del state[EXECUTION_OUTCOME]; state.pop(ACKS, None)
            # Continue grants a distinct execution. Preserve the expired policy
            # only in its sealed predecessor; this grant is not reboot-qualified.
            state.pop(BUDGET, None)
            state['deadline_monotonic'] = grant['deadline_monotonic']
            state[NAMESPACE] = {**payload['demand_identity'], 'state': 'paused',
                'updated_at_utc': payload['demand_identity']['arrived_at_utc'],
                'reason': 'Explicit continuation selected; awaiting retained launch and fresh Resume'}
            metadata = deepcopy(cp.metadata); metadata[NAMESPACE] = payload['demand_identity']
            metadata[LINK] = {'logical_task_id': self.logical_task_id, 'execution_id': payload['successor_id'],
                'execution_generation': generation, 'command_id': payload['command_id'], 'payload_sha256': digest(payload)}
            grant['successor_initial_state_sha256'] = digest(state)
            grant['successor_metadata_sha256'] = digest(metadata)
            self.store._create_in_transaction(db, payload['successor_id'], cp.prompt,
                                              max_attempts=cp.max_attempts, metadata=metadata, state=state)
            changed = deepcopy(authority_cp.state)
            changed[AUTHORITY]['grants'].append(grant)
            changed[AUTHORITY].update(selected_execution=payload['successor_id'], execution_generation=generation)
            require(Path(self.scope['wire_observations']).read_bytes() == raw, 'Wire ledger changed during authorization')
            saved = self.store._write(db, authority_cp, state=changed, operation=None, reconciliation=False,
                epoch=owned_authority._epoch, event='continuation_authorized', event_data={'payload_sha256': digest(payload)})
        owned_authority.checkpoint = saved
        return deepcopy(grant)

    def _inherited_grant(self, db, current, grant, rows):
        """Preserve an execution's original anchor at entry AND next selection."""
        payload = grant['payload']
        expected_link = {'logical_task_id': self.logical_task_id, 'execution_id': current.task_id,
            'execution_generation': grant['execution_generation'], 'command_id': payload['command_id'],
            'payload_sha256': grant['payload_sha256']}
        require(current.task_id == payload['successor_id'] and current.metadata.get(LINK) == expected_link
                and digest(current.metadata) == grant['successor_metadata_sha256']
                and current.metadata[NAMESPACE] == payload['demand_identity']
                and current.prompt == self.declaration[AUTHORITY]['prompt']
                and current.max_attempts == self.declaration[AUTHORITY]['max_attempts']
                and current.state['session_id'] == self.scope['session_id']
                and current.state['deadline_monotonic'] == grant['deadline_monotonic'],
                'Selected execution identity changed')
        prefix = rows[:grant['wire_prefix_count']]
        require(len(prefix) == grant['wire_prefix_count']
                and digest(prefix) == grant['wire_prefix_sha256']
                and [digest(row) for row in prefix] == grant['wire_row_sha256']
                and [row['body_sha256'] for row in prefix] == grant['wire_body_sha256'],
                'Inherited wire prefix changed')
        row = db.execute('SELECT payload FROM history WHERE task_id=? AND revision=0', (current.task_id,)).fetchone()
        require(row is not None, 'Successor creation record missing')
        first = json.loads(row[0])
        require(digest(first['state']) == grant['successor_initial_state_sha256']
                and first['metadata'] == current.metadata and first['prompt'] == current.prompt
                and first['max_attempts'] == current.max_attempts, 'Successor creation record changed')
        predecessor = self.store._read(db, payload['predecessor_id'])
        marker = execution_outcome(predecessor.state)
        require(marker is not None and digest(marker) == payload['predecessor_seal_sha256'],
                'Inherited predecessor seal changed')
        if marker['schema'] == WAIT_EXPIRY_SCHEMA:
            safe_state(predecessor, sealed=True)
            require(predecessor.owner_epoch is None and predecessor.revision == payload['predecessor_revision']
                    and predecessor.revision == marker['pre_seal_revision'] + 1
                    and digest(predecessor.state) == grant['predecessor_state_sha256'],
                    'Superseded predecessor identity changed')
            history = list(db.execute('SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',
                                      (predecessor.task_id,)))
            require(digest([list(row) for row in history]) == grant['predecessor_history_sha256'],
                    'Superseded predecessor history changed')
            self._wait_prefix(db, predecessor)
            require(grant.get('pending_request_disposition') == {
                'schema': PENDING_DISPOSITION, 'mode': 'rebuild_from_saved_conversation',
                'request_sha256': marker['pending_request_sha256']}, 'Pending request disposition changed')
            expected = deepcopy(predecessor.state)
            expected.pop(EXECUTION_OUTCOME); expected.pop(ACKS, None)
            expected.pop(BUDGET, None)
            expected.update(phase='ready', pending_request=None, deadline_monotonic=grant['deadline_monotonic'])
            expected[NAMESPACE] = {**payload['demand_identity'], 'state': 'paused',
                'updated_at_utc': payload['demand_identity']['arrived_at_utc'],
                'reason': 'Explicit continuation selected; awaiting retained launch and fresh Resume'}
            require(first['state'] == expected, 'Superseded successor projection changed')
            expected_metadata = deepcopy(predecessor.metadata)
            expected_metadata[NAMESPACE] = payload['demand_identity']; expected_metadata[LINK] = expected_link
            require(first['metadata'] == expected_metadata, 'Superseded successor metadata changed')
        else:
            require('pending_request_disposition' not in grant, 'Unexpected pending request disposition')
        for name in ('messages', 'native_history', 'tools', 'feedback', 'admission_deferrals', 'validation_rejections'):
            original, actual = first['state'].get(name, []), current.state.get(name, [])
            require(type(actual) is list and actual[:len(original)] == original, 'Inherited task/effect history changed')
        for name in ('attempts', 'requests', 'admission_attempts'):
            require(current.state[name] >= first['state'][name], 'Inherited cumulative counter reset')

    @contextmanager
    def claim_selected(self, grant, *, host_generation):
        """Storage ownership only; controller must still prove release/launch safety."""
        payload = self._payload(grant['payload'])
        require(payload['host_generation'] == host_generation, 'Host generation changed')
        authority_cp = self.store.load(self.task_id)
        with self.store.claim(self.task_id, expected_revision=authority_cp.revision,
                              owner_id='continuation-execution') as authority_owner:
            authority = self._authority(authority_owner.checkpoint)
            require(digest(self._find(authority, payload)) == digest(grant)
                    and authority['selected_execution'] == payload['successor_id'],
                    'Execution is not the selected authorization')
            cp = self.store.load(payload['successor_id'])
            require(cp.owner_epoch is None, 'Execution owner has not released')
            safe_state(cp, sealed=False)
            now = self.clock()
            require(type(now) in (int, float) and math.isfinite(now)
                    and grant['authorized_at'] <= now < grant['deadline_monotonic'], 'Selected execution budget spent or clock changed')
            with self.store.claim(cp.task_id, expected_revision=cp.revision,
                                  owner_id='selected-continuation') as execution_owner:
                current = execution_owner.checkpoint
                rows = wire_rows(Path(self.scope['wire_observations']).read_bytes(), current, self.scope)
                with self.store._connection() as db:
                    self._inherited_grant(db, current, grant, rows)
                yield authority_owner, execution_owner
