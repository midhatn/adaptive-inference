# SPDX-License-Identifier: Apache-2.0
"""Sequential task admission using the existing TaskStore ownership/receipts.

This component does not launch a worker, authenticate a user, or prove OS/native
cleanup. The host supplies a verified cleanup receipt digest, retains all child
handles, and performs staging/launch between the explicit operation boundaries.
An interrupted preparation or launch remains fenced; lookup never retries it.
Task-local stores remain separate. No atomic cross-database commit is claimed.

Reuse: TaskStore's existing BEGIN IMMEDIATE/revision/operation mechanism and
ContinuationAuthority's immutable command lookup pattern. See TaskStore for
the retained Strata attribution, and docs/task-spec.md for Hermes lifecycle work.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from adaptive_inference.demand import DemandIdentity, NAMESPACE, _record
from adaptive_inference.task_store import (
    TaskStore, OwnedTask, OwnershipError, ReconciliationRequired, RevisionConflict,
    _copy, _task_id, _FileLock,
)
from adaptive_inference.task_spec import TaskSpec


AUTHORITY = 'adaptive_inference.task_admission.v1'
MAX_ADMISSIONS = 16


def _require(condition, message):
    if not condition:
        raise ReconciliationRequired(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Exact SHA256 required')
    return value


def _directory(value):
    path = Path(value)
    _require(path.is_absolute() and str(path) == str(path.resolve(strict=True))
             and path.is_dir(), 'Explicit existing resolved private directory required')
    return path


def _snapshot(cp):
    return _digest({'task_id': cp.task_id, 'prompt': cp.prompt, 'metadata': cp.metadata,
                    'max_attempts': cp.max_attempts, 'revision': cp.revision, 'state': cp.state,
                    'operation': cp.operation, 'requires_reconciliation': cp.requires_reconciliation})


def _task_store(run):
    path = run / 'task.sqlite3'
    _require(path.is_file() and str(path) == str(path.resolve(strict=True))
             and path.stat().st_nlink == 1, 'Exact task-local store file required')
    return TaskStore(path)


class TaskAdmission:
    """One selected task, one pending admission, bounded retained history.

    Keep the authority claim through preparation and the selected worker's
    lifetime. Status/lookup are independent reads. Closing a claim with an
    unfinished operation makes it require reconciliation, not replay permission.
    A cleanup digest is a trusted host evidence reference, not an OS verifier.
    """

    def __init__(self, store, *, host_generation, tasks_root, initial_task_id, initial_run):
        if type(store) is not TaskStore:
            raise TypeError('Exact TaskStore required')
        self.store, self.host_generation = store, _task_id(host_generation)
        self.tasks_root = _directory(tasks_root)
        initial_run = _directory(initial_run)
        _task_id(initial_task_id)
        _task_store(initial_run).load(initial_task_id)
        self.initial = {'task_id': initial_task_id, 'run': str(initial_run)}
        # Same-host bindings only. Keeping the verifier does not establish child
        # exit or native release: the composition still owns those obligations.
        self._execution_bindings = {}
        self.task_id = 'admission.' + _digest(host_generation)
        self.prompt = 'Record explicit tasks for host ' + host_generation + '.'
        self.declaration = {AUTHORITY: {'host_generation': host_generation,
            'tasks_root': str(self.tasks_root), 'initial': self.initial}}
        try:
            cp = store.load(self.task_id)
        except KeyError:
            try:
                cp = store.create(self.task_id, self.prompt, max_attempts=1,
                    metadata=self.declaration, state={'status': 'pending',
                    'messages': [{'role': 'user', 'content': self.prompt}],
                    'attempts': 0, 'feedback': [], 'output': '',
                    AUTHORITY: {'selection_revision': 0, 'selected': self.initial, 'admissions': []}})
            except RevisionConflict:
                cp = store.load(self.task_id)
        self._state(cp)

    def request(self, *, command_id, expected_selection_revision, predecessor_execution_id,
                predecessor_revision, spec, arrived_at_utc, source=None):
        """Build once and retain this exact payload for all retries of a command."""
        _task_id(command_id); _task_id(predecessor_execution_id)
        if (type(expected_selection_revision) is not int or not 0 <= expected_selection_revision < MAX_ADMISSIONS
                or type(predecessor_revision) is not int or not 0 <= predecessor_revision < 256
                or type(spec) is not TaskSpec):
            raise ValueError('Explicit TaskSpec and bounded predecessor/selection revisions required')
        suffix = _digest({'host': self.host_generation, 'command': command_id})
        task_id = 'task.' + suffix
        demand = DemandIdentity('demand.' + suffix, task_id, self.host_generation, arrived_at_utc)
        payload = {'command_id': command_id, 'host_generation': self.host_generation,
            'expected_selection_revision': expected_selection_revision,
            'predecessor_execution_id': predecessor_execution_id, 'predecessor_revision': predecessor_revision,
            'task_id': task_id, 'session_id': 'session.' + suffix, 'run': str(self.tasks_root / task_id),
            'task_spec': spec.data, 'task_spec_sha256': spec.sha256, 'demand_identity': demand.metadata()}
        if source is not None:
            if type(source) is not dict or set(source) != {'task_spec_path', 'task_spec_sha256', 'task_inputs'}:
                raise ValueError('Exact task source paths and raw specification digest required')
            _sha(source['task_spec_sha256'])
            for key in ('task_spec_path', 'task_inputs'):
                path = source[key]
                if (type(path) is not str or not path or '\0' in path
                        or len(path.encode('utf-8')) > 1024 or not Path(path).is_absolute()):
                    raise ValueError('Bounded absolute task source paths required')
            # Paths are part of command identity, not proof of file contents.
            # Do not reopen them during historical lookup; preparation pins and
            # stages the actual spec/input bytes before a worker may launch.
            payload['source'] = deepcopy(source)
        return payload

    def _payload(self, payload):
        required = {'command_id', 'host_generation',
            'expected_selection_revision', 'predecessor_execution_id', 'predecessor_revision', 'task_id',
            'session_id', 'run', 'task_spec', 'task_spec_sha256', 'demand_identity'}
        _require(type(payload) is dict and set(payload) in (required, required | {'source'}),
                 'Admission fields changed')
        _require('source' not in payload or payload['source'] is not None, 'Task source cannot be null')
        spec = TaskSpec(payload['task_spec'])
        restored = self.request(command_id=payload['command_id'],
            expected_selection_revision=payload['expected_selection_revision'],
            predecessor_execution_id=payload['predecessor_execution_id'],
            predecessor_revision=payload['predecessor_revision'], spec=spec,
            arrived_at_utc=payload['demand_identity']['arrived_at_utc'], source=payload.get('source'))
        _require(restored == payload, 'Admission identity changed')
        return _copy(payload)

    def _state(self, cp):
        _require(cp.task_id == self.task_id and cp.prompt == self.prompt and cp.max_attempts == 1
            and cp.metadata == self.declaration and set(cp.state) ==
            {'status', 'messages', 'attempts', 'feedback', 'output', AUTHORITY}
            and cp.state['status'] == 'pending' and cp.state['attempts'] == 0,
            'Host admission identity changed')
        state = cp.state[AUTHORITY]
        _require(type(state) is dict and set(state) == {'selection_revision', 'selected', 'admissions'}
            and type(state['admissions']) is list and len(state['admissions']) <= MAX_ADMISSIONS,
            'Admission authority shape changed')
        selected, revision, commands = self.initial, 0, set()
        for index, row in enumerate(state['admissions']):
            _require(type(row) is dict and set(row) == {'reservation', 'phase', 'prepared', 'release'},
                     'Admission record changed')
            grant = row['reservation']; payload = self._payload(grant['payload'])
            _require(set(grant) == {'payload', 'payload_sha256', 'predecessor', 'selection_revision'}
                and grant['payload_sha256'] == _digest(payload)
                and payload['command_id'] not in commands
                and payload['expected_selection_revision'] == revision
                and grant['selection_revision'] == revision + 1
                and grant['predecessor']['selected'] == selected,
                'Admission chain or command changed')
            commands.add(payload['command_id'])
            phase = row['phase']
            _require(phase in ('reserved', 'preparing', 'prepared', 'running', 'released', 'abandoned', 'stopped'),
                     'Unknown admission phase')
            if phase in ('reserved', 'preparing', 'abandoned'):
                _require((phase == 'abandoned' or index == len(state['admissions']) - 1) and row['prepared'] is None,
                         'Unfinished preparation cannot have a successor')
            else:
                _require(type(row['prepared']) is dict, 'Selected admission lacks preparation receipt')
                revision += 1; selected = {'task_id': payload['task_id'], 'run': payload['run']}
            _require((phase in ('released', 'abandoned', 'stopped')) == (row['release'] is not None), 'Release state changed')
            if index < len(state['admissions']) - 1:
                _require(phase in ('released', 'abandoned'), 'Prior task was not released')
        _require(type(state['selection_revision']) is int and state['selection_revision'] == revision
                 and state['selected'] == selected, 'Selected task differs from admission chain')
        return deepcopy(state)

    def _owned(self, owned):
        if (type(owned) is not OwnedTask or owned._store.path != self.store.path
                or owned.checkpoint.task_id != self.task_id):
            raise OwnershipError('Exact host admission claim required')
        with self.store._connection() as db:
            cp = owned._check(db, owned.checkpoint.revision)
        return cp, self._state(cp)

    @staticmethod
    def _find(state, payload):
        for row in state['admissions']:
            if row['reservation']['payload']['command_id'] == payload['command_id']:
                if row['reservation']['payload'] != payload:
                    raise RevisionConflict('Command ID already binds a different task')
                return row
        return None

    def lookup(self, payload):
        """Immutable reservation only; never clear an operation or retry effects."""
        row = self._find(self._state(self.store.load(self.task_id)), self._payload(payload))
        return None if row is None else deepcopy(row['reservation'])

    def status(self):
        cp = self.store.load(self.task_id); state = self._state(cp)
        # A reservation is still a retained staging obligation, even before an
        # operation exists. The caller must not infer clean Stop from no PID.
        return {'selection_revision': state['selection_revision'], 'selected': state['selected'],
                'admissions': state['admissions'], 'operation': cp.operation,
                'requires_reconciliation': cp.requires_reconciliation,
                'host_stopped': bool(state['admissions'] and state['admissions'][-1]['phase'] == 'stopped'),
                'stop_fenced': bool(cp.operation or cp.requires_reconciliation or
                    (state['admissions'] and state['admissions'][-1]['phase'] not in ('released', 'abandoned', 'stopped')))}

    def retain_execution_binding(self, binding):
        """Retain the existing continuation verifier, never a caller boolean.

        The caller joins its retained child and verifies native release before
        reserve/finish. We independently recheck the exact released continuation
        authority and result using that binding while both store locks are held.
        """
        from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
        if type(binding) is not SelectedWorkerStopBinding:
            raise TypeError('Exact retained selected-worker binding required')
        _require(binding.authority.host_generation == self.host_generation,
                 'Continued execution belongs to another host')
        key = binding.original.task_id
        previous = self._execution_bindings.get(key)
        _require(previous is None or previous is binding, 'Retained execution binding changed')
        self._execution_bindings[key] = binding

    @contextmanager
    def _released_checkpoint(self, selected, execution_id, revision, *, stop_binding=None):
        run = _directory(selected['run'])
        store = _task_store(run)
        # Reuse TaskStore.claim's exact stable sidecar without changing the
        # released checkpoint's revision. Held through the host write, this
        # prevents a cooperating claim from changing cancelled A during select.
        with ExitStack() as locks:
            def hold(task_id):
                lock = _FileLock(str(store.path) + '.task-' + hashlib.sha256(task_id.encode()).hexdigest() + '.lock')
                locks.callback(lock.close)
            binding = None
            if stop_binding is not None:
                from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding
                from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
                _require(type(stop_binding) in (WorkerStopBinding, SelectedWorkerStopBinding)
                    and stop_binding.run == run and stop_binding.original.task_id == execution_id
                    and stop_binding.mailbox.store.path == store.path,
                    'Exact stopped task worker binding required')
            if execution_id != selected['task_id']:
                from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
                binding = stop_binding or self._execution_bindings.get(execution_id)
                _require(type(binding) is SelectedWorkerStopBinding,
                         'Unverified successor execution is unsupported')
                authority = binding.authority
                _require(binding.run == run and authority.store.path == store.path
                    and authority.logical_task_id == selected['task_id']
                    and authority.host_generation == self.host_generation,
                    'Continued execution does not belong to the selected task')
                # Same order as ContinuationAuthority.claim_selected: authority
                # first, execution second. Keep both through the admission write.
                hold(authority.task_id)
                authority_cp = authority.store.load(authority.task_id)
                authority_state = authority._authority(authority_cp)
                _require(authority_cp.owner_epoch is None
                    and authority_state['selected_execution'] == execution_id,
                    'Continued execution authority is owned or selects another execution')
            else:
                # An old original-worker binding must not close the lifetime
                # after Continue selected another execution (even before launch).
                from adaptive_inference.desktop.hermes.continuation import (
                    ContinuationAuthority, AUTHORITY as CONTINUATION, digest as continuation_digest)
                authority_id = 'continue.' + continuation_digest(selected['task_id'])
                # The authority may be created for the first time concurrently.
                # Lock its deterministic identity even before a row exists.
                hold(authority_id)
                try:
                    authority_cp = store.load(authority_id)
                except KeyError:
                    authority_cp = None
                if authority_cp is not None:
                    authority = ContinuationAuthority(store, selected['task_id'],
                        authority_cp.metadata[CONTINUATION]['scope'], host_generation=self.host_generation)
                    authority_state = authority._authority(authority_cp)
                    _require(authority_cp.owner_epoch is None
                        and authority_state['selected_execution'] == execution_id,
                        'Original worker no longer represents the selected execution')
            hold(execution_id)
            cp = store.load(execution_id)
            store._revision(cp, revision)
            _require(cp.owner_epoch is None and cp.operation is None and not cp.requires_reconciliation,
                     'Predecessor is still owned or unknown')
            declaration = cp.metadata[NAMESPACE]
            identity = DemandIdentity(**{k: declaration[k] for k in
                ('registration_id', 'task_id', 'owner_id', 'arrived_at_utc')})
            demand = _record(cp, identity)
            if stop_binding is None:
                _require(cp.state['status'] == 'accepted' or (demand is not None and demand['state'] == 'cancelled'),
                         'Previous task must complete or be cancelled explicitly')
            verifier = stop_binding or binding
            if verifier is not None:
                code = verifier.worker.poll()
                _require(type(code) is int, 'Continued child is not known to have exited')
                outcome = type(verifier)._verify_exit(verifier, code)
                allowed = ('task_completed', 'task_cancelled') if stop_binding is None else (
                    'task_completed', 'task_cancelled', 'service_stopped', 'paused_budget_expired',
                    'admission_wait_budget_expired')
                _require(outcome in allowed,
                         'Continued task has not completed or been explicitly cancelled')
            yield cp

    def reserve(self, owned, payload, *, predecessor_cleanup_sha256):
        payload = self._payload(payload); _sha(predecessor_cleanup_sha256)
        cp, state = self._owned(owned)
        previous = self._find(state, payload)
        if previous is not None:
            return deepcopy(previous['reservation'])
        _require(cp.operation is None and not cp.requires_reconciliation, 'Unknown host operation blocks admission')
        _require(not state['admissions'] or state['admissions'][-1]['phase'] in ('released', 'abandoned'),
                 'A task admission or selected worker is still retained')
        if state['selection_revision'] != payload['expected_selection_revision']:
            raise RevisionConflict('Selected task changed')
        _require(len(state['admissions']) < MAX_ADMISSIONS, 'Sequential admission bound reached')
        with self._released_checkpoint(state['selected'], payload['predecessor_execution_id'],
                                       payload['predecessor_revision']) as old:
            _require(not os.path.lexists(payload['run']), 'New task directory already exists')
            grant = {'payload': payload, 'payload_sha256': _digest(payload),
                'selection_revision': state['selection_revision'] + 1,
                'predecessor': {'selected': state['selected'], 'execution_id': old.task_id,
                    'revision': old.revision, 'checkpoint_sha256': _snapshot(old),
                    'cleanup_sha256': predecessor_cleanup_sha256}}
            state['admissions'].append({'reservation': grant, 'phase': 'reserved', 'prepared': None, 'release': None})
            new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
            owned.save_checkpoint(new_state, expected_revision=cp.revision)
        return deepcopy(grant)

    def _current(self, owned, reservation):
        cp, state = self._owned(owned)
        row = self._find(state, self._payload(reservation['payload']))
        _require(row is not None and row['reservation'] == reservation
                 and row is state['admissions'][-1], 'Exact current reservation required')
        return cp, state, row

    def begin(self, owned, reservation, *, action):
        """Call before any preparation or launch side effect; retain exact claim."""
        cp, state, row = self._current(owned, reservation)
        _require(action in ('prepare', 'launch') and row['phase'] ==
                 ('reserved' if action == 'prepare' else 'prepared'), 'Unexpected lifecycle transition')
        payload = reservation['payload']
        if action == 'prepare':
            _require(not os.path.lexists(payload['run']), 'Unowned staging already exists')
        else:
            task = _task_store(_directory(payload['run'])).load(payload['task_id'])
            _require(task.owner_epoch is None and _snapshot(task) == row['prepared']['checkpoint_sha256'],
                     'Prepared checkpoint changed before launch')
            TaskSpec(payload['task_spec']).verify_inputs(Path(payload['run']) / 'work')
        row['phase'] = 'preparing' if action == 'prepare' else 'running'
        new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
        result = owned.begin_operation('effect', details={'authority': AUTHORITY, 'action': action,
            'payload_sha256': reservation['payload_sha256']}, state=new_state, expected_revision=cp.revision)
        return result.operation['id']

    def abandon(self, owned, reservation, *, cleanup_sha256):
        """Stop before staging: preserve the command, leave A selected, never retry B.

        The retained host must assert no launch/staging action occurred. This
        narrow path also verifies no operation and no directory entry; it cannot
        resolve a preparing/running or otherwise uncertain operation.
        """
        _sha(cleanup_sha256)
        cp, state, row = self._current(owned, reservation)
        _require(row['phase'] == 'reserved' and cp.operation is None and not cp.requires_reconciliation
                 and not os.path.lexists(reservation['payload']['run']),
                 'Only a known unstaged reservation may be abandoned')
        row['phase'] = 'abandoned'
        row['release'] = {'outcome': 'not_started', 'cleanup_sha256': cleanup_sha256}
        new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
        owned.save_checkpoint(new_state, expected_revision=cp.revision)
        return deepcopy(row['release'])

    def _operation(self, cp, reservation, operation_id, action):
        _require(cp.operation is not None and cp.operation['id'] == operation_id
            and cp.operation['kind'] == 'effect' and cp.operation['details'] ==
            {'authority': AUTHORITY, 'action': action, 'payload_sha256': reservation['payload_sha256']}
            and not cp.requires_reconciliation, 'Exact uninterrupted lifecycle operation required')

    def prepared(self, owned, reservation, *, operation_id):
        """Select only the actual fresh task-local store with exact prompt/spec/demand."""
        cp, state, row = self._current(owned, reservation)
        self._operation(cp, reservation, operation_id, 'prepare')
        _require(row['phase'] == 'preparing', 'Task is not preparing')
        payload = reservation['payload']; run = _directory(payload['run'])
        _require(run.parent == self.tasks_root and (run / 'task.sqlite3').is_file(), 'Prepared store path changed')
        task = _task_store(run).load(payload['task_id'])
        spec = TaskSpec.from_metadata(task.metadata)
        identity = DemandIdentity(**{k: payload['demand_identity'][k] for k in
            ('registration_id', 'task_id', 'owner_id', 'arrived_at_utc')})
        demand = _record(task, identity)
        _require(task.revision == 0 and task.owner_epoch is None and task.operation is None
            and not task.requires_reconciliation and task.state['status'] == 'pending'
            and task.max_attempts == 8 and task.prompt == TaskSpec(payload['task_spec']).prompt
            and spec is not None and spec.sha256 == payload['task_spec_sha256']
            and task.state.get('session_id') == payload['session_id'] and demand is None,
            'Prepared task prompt, spec, session, demand or fresh state changed')
        spec.verify_inputs(run / 'work')
        old = reservation['predecessor']
        with self._released_checkpoint(old['selected'], old['execution_id'], old['revision']) as predecessor:
            _require(_snapshot(predecessor) == old['checkpoint_sha256'], 'Predecessor changed during staging')
            row['phase'] = 'prepared'; row['prepared'] = {'checkpoint_sha256': _snapshot(task), 'revision': task.revision}
            state['selection_revision'] = reservation['selection_revision']
            state['selected'] = {'task_id': payload['task_id'], 'run': payload['run']}
            new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
            owned.complete_operation(operation_id, result=row['prepared'], state=new_state, expected_revision=cp.revision)
        return deepcopy(row['prepared'])

    def finish(self, owned, reservation, *, execution_id, task_revision, cleanup_sha256, operation_id=None):
        """Hand back completed/cancelled B so C can be admitted, with caller cleanup proof.

        The caller must verify retained child joins/native/effects first. A task
        cancelled before launch may finish without a launch operation; an
        interrupted operation cannot be cleared by this method.
        """
        _sha(cleanup_sha256)
        cp, state, row = self._current(owned, reservation)
        _require(row['phase'] in ('prepared', 'running'), 'No selected task can be released')
        if row['phase'] == 'running':
            self._operation(cp, reservation, operation_id, 'launch')
        else:
            _require(operation_id is None and cp.operation is None and not cp.requires_reconciliation,
                     'Unknown launch cannot be treated as no child')
        with self._released_checkpoint(state['selected'], execution_id, task_revision) as task:
            if operation_id is None:
                # Accepted work cannot be reconciled as a never-launched task.
                # The no-operation handback is exclusively explicit cancellation.
                _require(task.state['status'] != 'accepted' and
                         task.state.get(NAMESPACE, {}).get('state') == 'cancelled',
                         'No-launch handback requires explicit cancellation without accepted work')
            release = {'execution_id': execution_id, 'revision': task.revision,
                       'checkpoint_sha256': _snapshot(task), 'cleanup_sha256': cleanup_sha256}
            row['phase'] = 'released'; row['release'] = release
            new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
            if operation_id is None:
                owned.save_checkpoint(new_state, expected_revision=cp.revision)
            else:
                owned.complete_operation(operation_id, result=release, state=new_state, expected_revision=cp.revision)
        return deepcopy(release)

    @contextmanager
    def _unlaunched_checkpoint(self, selected, continuation):
        from adaptive_inference.desktop.continuation_host import HostContinuation
        _require(type(continuation) is HostContinuation, 'Exact unlaunched continuation coordinator required')
        record = continuation.current
        _require(type(record) is dict, 'No committed continuation can stop')
        authority, grant = record['authority'], record['grant']
        run = _directory(selected['run']); store = _task_store(run)
        _require(authority.store.path == store.path
            and authority.host_generation == self.host_generation
            and authority.logical_task_id == selected['task_id']
            and continuation.runtime.prepared.host_epoch == self.host_generation
            and continuation.runtime.prepared.task_id == selected['task_id'],
            'Unlaunched continuation does not belong to the selected task')
        with ExitStack() as locks:
            for task_id in (authority.task_id, grant['payload']['successor_id']):
                lock = _FileLock(str(store.path) + '.task-' + hashlib.sha256(task_id.encode()).hexdigest() + '.lock')
                locks.callback(lock.close)
            authority_cp = store.load(authority.task_id)
            _require(authority._authority(authority_cp)['selected_execution'] == grant['payload']['successor_id'],
                     'Unlaunched continuation is no longer selected')
            proof = HostContinuation.verify_unlaunched(continuation, record)
            _require(proof['outcome'] == 'selected_not_launched', 'Unlaunched verification failed')
            yield store.load(grant['payload']['successor_id']), proof['outcome']

    def stop(self, owned, reservation, *, cleanup_sha256, operation_id=None, binding=None, continuation=None):
        """Close this host's known lifetime without cancelling its pending task.

        Call only after actual child joins and native cleanup. A prepared task
        with no launch remains pending. A running task must pass its existing
        safe-exit verifier. Neither case may admit another task in this host;
        reboot/restart recovery requires its own authority and qualification.
        """
        _sha(cleanup_sha256)
        cp, state, row = self._current(owned, reservation)
        _require(row['phase'] in ('prepared', 'running'), 'No known task lifetime can stop')
        payload = reservation['payload']
        if row['phase'] == 'prepared':
            _require(operation_id is None and binding is None and continuation is None and cp.operation is None
                and not cp.requires_reconciliation, 'Unknown launch cannot be treated as no child')
            store = _task_store(_directory(payload['run']))
            lock = _FileLock(str(store.path) + '.task-' + hashlib.sha256(payload['task_id'].encode()).hexdigest() + '.lock')
            try:
                task = store.load(payload['task_id'])
                _require(task.owner_epoch is None and _snapshot(task) == row['prepared']['checkpoint_sha256'],
                         'Prepared task changed before host Stop')
                release = {'execution_id': task.task_id, 'revision': task.revision,
                    'checkpoint_sha256': _snapshot(task), 'cleanup_sha256': cleanup_sha256,
                    'outcome': 'not_launched'}
                row['phase'], row['release'] = 'stopped', release
                new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
                owned.save_checkpoint(new_state, expected_revision=cp.revision)
            finally:
                lock.close()
        else:
            from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding
            from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
            self._operation(cp, reservation, operation_id, 'launch')
            @contextmanager
            def verified():
                if continuation is None:
                    _require(type(binding) in (WorkerStopBinding, SelectedWorkerStopBinding),
                             'Running host Stop requires its exact retained worker binding')
                    task = binding.mailbox.snapshot().target
                    with self._released_checkpoint(state['selected'], task.task_id, task.revision,
                                                   stop_binding=binding) as task:
                        yield task, type(binding)._verify_exit(binding, binding.worker.poll())
                    return
                _require(binding is None, 'Unlaunched continuation cannot borrow a worker binding')
                with self._unlaunched_checkpoint(state['selected'], continuation) as value:
                    yield value
            with verified() as (task, outcome):
                release = {'execution_id': task.task_id, 'revision': task.revision,
                    'checkpoint_sha256': _snapshot(task), 'cleanup_sha256': cleanup_sha256,
                    'outcome': outcome}
                row['phase'], row['release'] = 'stopped', release
                new_state = deepcopy(cp.state); new_state[AUTHORITY] = state
                owned.complete_operation(operation_id, result=release, state=new_state, expected_revision=cp.revision)
        return deepcopy(release)
