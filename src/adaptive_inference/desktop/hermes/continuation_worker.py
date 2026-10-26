# SPDX-License-Identifier: Apache-2.0
"""Selected execution view and owned worker entry; no launcher or release oracle."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path

from adaptive_inference.task_store import TaskStore, ReconciliationRequired
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, require, wire_rows
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.report_validator import distinct_object
from adaptive_inference.desktop.hermes.service_stop import flushed_tools


def read_json(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 1024 * 1024, 'Selected worker input exceeds bound')
    return json.loads(raw, object_pairs_hook=distinct_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite selected-worker input')))


def scope_for(run, plan, raw):
    return {'plan_sha256': rec.digest(raw), 'session_id': plan['session_id'],
        'native_db': str(run/'home/state.db'), 'work_dir': str(run/'work'),
        'effect_receipts': str(run/'effect-receipts.jsonl'),
        'wire_observations': str(run/'wire-observations.json'), 'gateway': plan['gateway']}


def effect_receipts(owned, run):
    """The shared append-only physical writes must match durable non-reused writes."""
    expected = [row for row in owned.checkpoint.state['tools']
                if row['name'] == 'write_file' and row.get('reused') is False]
    path = Path(run)/'effect-receipts.jsonl'
    raw = path.read_bytes() if path.is_file() else b''
    require(len(raw) <= 1024 * 1024, 'Effect receipt file exceeds bound')
    rows = [json.loads(line, object_pairs_hook=distinct_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite effect receipt')))
        for line in raw.splitlines() if line.strip()]
    require(rec.digest(rows) == rec.digest(expected), 'Physical effect receipts differ from durable writes')
    return rec.digest(raw)


class SelectedWorker:
    def __init__(self, run, original, original_raw, authority, authority_owner, owned, grant):
        self.run, self.original, self.original_raw = run, deepcopy(original), original_raw
        self.authority, self.authority_owner, self.owned = authority, authority_owner, owned
        self.grant = deepcopy(grant)
        self.execution_id = grant['payload']['successor_id']
        self.execution_generation = grant['execution_generation']
        self.plan = deepcopy(original)
        self.plan['task_id'] = self.execution_id
        self.plan['demand_identity'] = {key: value for key, value in grant['payload']['demand_identity'].items() if key != 'schema'}
        self.diagnostics = (run/'executions'/self.execution_id).resolve()
        require(self.diagnostics.is_relative_to(run/'executions'), 'Execution diagnostics escaped original run')
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        self.result_path = self.diagnostics/f'result-{os.getpid()}.json'
        require(not self.result_path.exists(), 'Selected worker result path already exists')
        self.cleanup_proof = None
        self.lifecycle = authority_owner.begin_operation('effect', expected_revision=authority_owner.checkpoint.revision,
            details={'schema': 'adaptive.selected-worker-lifetime.v1', 'execution_id': self.execution_id,
                     'execution_generation': self.execution_generation, 'payload_sha256': grant['payload_sha256']})

    def exact_plan(self):
        require((self.run/'plan.json').read_bytes() == self.original_raw, 'Immutable original plan changed')
        return deepcopy(self.plan)

    def load_wire(self, *, final=False):
        """Called after both claims; never seed Boundary from preclaim observations."""
        with self.authority.store._connection() as db:
            if final:
                # _check is a mutation guard and correctly refuses accepted
                # checkpoints. This final read must not reopen their state.
                cp = self.authority.store._read(db, self.execution_id)
                require(not self.owned._closed and self.owned._lock.held
                        and self.owned._pid == os.getpid() and self.owned._epoch is not None
                        and cp.owner_epoch == self.owned._epoch and cp == self.owned.checkpoint,
                        'Final wire read lost its exact retained execution ownership')
            else:
                cp = self.owned._check(db, self.owned.checkpoint.revision)
            rows = wire_rows((self.run/'wire-observations.json').read_bytes(), cp, self.authority.scope)
            self.authority._inherited_grant(db, cp, self.grant, rows)
        return rows

    def verify_native(self, db):
        history = rec.resumable(self.owned, db, self.run/'work')
        flushed_tools(self.owned.checkpoint.state)
        effect_receipts(self.owned, self.run)
        return history

    def ready_path(self, path):
        path = Path(path).resolve()
        require(path.parent == self.diagnostics, 'Selected readiness must use its execution directory')
        return path

    def read_ready(self, path):
        ready = read_json(self.ready_path(path))
        pair = ready.get('selected_execution')
        require(type(pair) is dict and type(pair.get('execution_generation')) is int
                and pair == {'execution_id': self.execution_id,
                    'execution_generation': self.execution_generation},
                'Controller readiness belongs to another selected execution')
        return ready

    def note_cleanup(self, proof):
        # Only the reused native cleanup helper or exact expiry finalizer supplies
        # this internal evidence. No host/UI request can invoke this as a permit.
        require(type(proof) is dict and proof.get('resources_closed') is True
                and proof['state_sha256'] == rec.digest(self.owned.checkpoint.state)
                and proof['native_history_sha256'] == rec.digest(self.owned.checkpoint.state['native_history']),
                'Selected cleanup proof differs from the owned checkpoint')
        self.cleanup_proof = deepcopy(proof)

    def finish(self, returncode):
        self.exact_plan()
        require(self.cleanup_proof is not None, 'Selected worker cleanup is unconfirmed')
        result = read_json(self.result_path)
        require(result.get('selected_execution') == {'execution_id': self.execution_id,
                    'execution_generation': self.execution_generation, 'logical_task_id': self.original['task_id']}
                and not result.get('cleanup_errors') and result.get('continuation_cleanup_verified') is True,
                'Selected result obligation is not complete')
        require(self.owned.checkpoint.operation is None and not self.owned.checkpoint.requires_reconciliation,
                'Selected execution still has an unknown operation')
        require(self.cleanup_proof['state_sha256'] == rec.digest(self.owned.checkpoint.state),
                'Selected checkpoint changed after cleanup')
        require(self.cleanup_proof['effect_receipts_sha256'] == effect_receipts(self.owned, self.run),
                'Physical effect receipts changed after cleanup')
        self.load_wire(final=True)
        raw = self.result_path.read_bytes()
        self.authority_owner.complete_operation(self.lifecycle.operation['id'],
            expected_revision=self.authority_owner.checkpoint.revision, state=self.authority_owner.checkpoint.state,
            result={'execution_id': self.execution_id, 'returncode': returncode,
                    'result_sha256': rec.digest(raw), 'cleanup': self.cleanup_proof,
                    'physical_child_exit_proven': False})


@contextmanager
def selected_worker(run, grant, *, host_generation, deadline, clock=None):
    """Both claims enclose SDK setup, all cleanup, restoration and result persistence."""
    from adaptive_inference.desktop.hermes.run_recovery import MODEL, QUALITY, SDK_REV, prepared_contract
    run = Path(run).resolve(strict=True)
    raw = (run/'plan.json').read_bytes(); original = read_json(run/'plan.json')
    prepared_contract(original)
    require(original.get('max_requests') == 8
            and original.get('model') == MODEL and rec.digest(original.get('quality')) == rec.digest(QUALITY)
            and original.get('sdk_revision') == SDK_REV and type(original.get('fixture')) is bool,
            'Original selected-worker plan differs')
    require(type(deadline) in (int, float) and deadline == grant['deadline_monotonic'], 'Caller deadline differs from grant')
    store = TaskStore(run/'task.sqlite3')
    # Entry cannot create a new authority or use a grant file as authority.
    store.load('continue.'+rec.digest(original['task_id']))
    options = {} if clock is None else {'clock': clock}
    authority = ContinuationAuthority(store, original['task_id'], scope_for(run, original, raw),
                                      host_generation=host_generation, **options)
    require(rec.digest(authority.lookup(grant['payload'])) == rec.digest(grant), 'Grant file differs from durable authorization')
    with authority.claim_selected(grant, host_generation=host_generation) as (authority_owner, owned):
        selected = SelectedWorker(run, original, raw, authority, authority_owner, owned, grant)
        yield selected
        # Missing finish deliberately leaves the existing operation/reconciliation
        # fence durable; releasing an OS lock cannot make that launch safe to retry.
        require(selected.authority_owner.checkpoint.operation is None,
                'Selected worker did not finish its retained result/cleanup obligations')
