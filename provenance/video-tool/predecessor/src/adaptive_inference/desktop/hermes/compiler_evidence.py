# SPDX-License-Identifier: Apache-2.0
"""Read compiler evidence without owning, repairing, or resuming a task.

Reuse TaskStore's atomic operation history and saved_tasks' read-only SQLite
pattern. A completed effect keeps its original deadline across boot/Continue;
the current episode never supplies a replacement grant for a historical result.
https://docs.temporal.io/activity-definition#idempotency
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3

from adaptive_inference.desktop.compiler_template import verify_cpp_artifacts, TEST_NAME
from adaptive_inference.desktop.execution_budget import BUDGET, validate_budget
from adaptive_inference.desktop.hermes.recovery import (
    ReconciliationRequired, assert_prefix, digest, task_contract, verify_tool_rows)
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.task_spec import strict_json, COMPILER_STATUSES
from adaptive_inference.task_store import TaskStore

TOOL_NAME = 'build_and_test'
_PRE_DISPATCH = frozenset({'binding_refused', 'preparation_failed', 'cancelled_before_dispatch'})


def verify_compiler_result(*, task_root, task_spec, args, operation_id, tool_call_id,
                           result, expected_deadline):
    """Validate one result against an explicitly supplied authoritative deadline.

    A newly returned client result must use the current original episode's
    deadline. Historical callers obtain their deadline from _origin_deadline.
    This function alone does not prove native authorization or origin history.
    """
    if (type(expected_deadline) not in (int, float) or not math.isfinite(expected_deadline)
            or expected_deadline <= 0 or type(result) is not dict
            or result.get('schema') != 'compiler-operation-result.v1'
            or result.get('operation_id') != operation_id or result.get('recipe_id') != args['recipe_id']
            or result.get('status') not in COMPILER_STATUSES
            or result.get('owned_processes_exited') is not True
            or type(result.get('dispatched')) is not bool or type(result.get('passed')) is not bool
            or result['passed'] != (result['status'] == 'passed')
            or result.get('task_deadline') != expected_deadline):
        raise ReconciliationRequired('Compiler result lacks an exact known joined outcome')
    if result['status'] in _PRE_DISPATCH:
        if result['dispatched']:
            raise ReconciliationRequired('Pre-dispatch compiler outcome reports an effect')
        checked = {'source_sha256': digest(args['source'].encode('utf-8'))}
    else:
        checked = verify_cpp_artifacts(Path(task_root) / 'compiler', spec=task_spec, args=args,
                                       operation_id=operation_id, result=result)
    normalized = {'operation_id': operation_id, 'tool_call_id': tool_call_id,
                  'spec_sha256': task_spec.sha256, 'recipe_id': args['recipe_id'],
                  'source_sha256': checked['source_sha256'], 'status': result['status'],
                  'owned_processes_exited': True}
    if result['passed']:
        if not result['dispatched'] or result.get('tests_passed') != [TEST_NAME]:
            raise ReconciliationRequired('Successful compiler result lacks its actual test')
        normalized.update(stdout_sha256=checked['stdout_sha256'], artifact_sha256=result['artifact_sha256'],
                          test_report_sha256=result['test_report_sha256'])
    return normalized


@contextmanager
def _readonly_store(path):
    # Match saved_tasks.readonly_checkpoint: never instantiate TaskStore, whose
    # constructor may initialize/repair a store or create its lock sidecar.
    path = Path(path)
    if not path.is_file() or any(Path(str(path) + suffix).exists()
                                for suffix in ('-journal', '-wal', '-shm')):
        raise ReconciliationRequired('Saved store is missing or needs explicit recovery')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA locking_mode=EXCLUSIVE')
        db.execute('BEGIN')
        TaskStore._verify_schema(db)
        if (db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete'
                or db.execute('PRAGMA quick_check').fetchone()[0] != 'ok'):
            raise ReconciliationRequired('Saved store layout or integrity differs')
        yield db
    finally:
        db.close()


def _history(db, task_id):
    # Same existing history projection as TaskStore.history, in the reader's
    # single transaction so origin and current creation records cannot drift.
    TaskStore._read(db, task_id)
    return tuple({'revision': row[0], 'event': row[1], 'payload': json.loads(row[2])}
                 for row in db.execute('SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',
                                       (task_id,)))


def _origin_deadline(db, checkpoint, task_spec, row):
    """Bind a completed result to its actual originating operation snapshot.

    Continue selection still requires the existing ContinuationAuthority; here
    its selected execution additionally needs the verbatim inherited receipt.
    """
    try:
        execution = row['execution_id']
        if type(execution) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', execution):
            raise ValueError('Invalid origin execution')
        link_name = 'adaptive_inference.execution_authorization.v1'
        logical = checkpoint.metadata.get(link_name, {}).get('logical_task_id', checkpoint.task_id)
        origin = TaskStore._read(db, execution)
        origin_logical = origin.metadata.get(link_name, {}).get('logical_task_id', origin.task_id)
        if origin_logical != logical or task_contract(origin).sha256 != task_spec.sha256:
            raise ValueError('Origin task contract differs')
        if execution != checkpoint.task_id:
            initial = _history(db, checkpoint.task_id)[0]
            link = checkpoint.metadata.get(link_name, {})
            if (initial['event'] != 'created' or initial['payload']['metadata'] != checkpoint.metadata
                    or link.get('logical_task_id') != logical or link.get('execution_id') != checkpoint.task_id
                    or initial['payload']['state']['tools'].count(row) != 1):
                raise ValueError('Historical receipt was not inherited by the selected execution')
        history = _history(db, execution)
        starts = [entry for entry in history if entry['event'] == 'operation_started'
                  and (entry['payload'].get('operation') or {}).get('id') == row['operation_id']]
        ends = [entry for entry in history if entry['event'] == 'operation_completed'
                and (entry['payload'].get('event_data') or {}).get('operation', {}).get('id') == row['operation_id']]
        if len(starts) != 1 or len(ends) != 1 or ends[0]['revision'] <= starts[0]['revision']:
            raise ValueError('Unique completed origin operation required')
        start, end = starts[0]['payload'], ends[0]['payload']
        operation, state = start['operation'], start['state']
        details = {key: row[key] for key in ('name', 'args', 'tool_call_id', 'session_id', 'fingerprint',
                   'host_epoch', 'task_id', 'execution_id', 'owner_epoch', 'spec_sha256')}
        if (operation['kind'] != 'effect' or operation['details'] != details
                or end['event_data'] != {'operation': operation, 'result': row}
                or not end['state']['tools'] or end['state']['tools'][-1] != row
                or state['phase'] != 'tool_running' or state['status'] != 'pending'
                or state['session_id'] != row['session_id'] or state.get('deadline_clock') != CLOCK_ID):
            raise ValueError('Compiler receipt differs from its durable origin')
        deadline = state['deadline_monotonic']
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0:
            raise ValueError('Invalid originating deadline')
        if BUDGET in state:
            budget = validate_budget(state[BUDGET])
            if budget['episode']['deadline'] != deadline or budget['clean_stop']:
                raise ValueError('Origin operation has no matching active budget episode')
        return deadline
    except Exception as exc:
        raise ReconciliationRequired('Compiler receipt has no exact completed origin operation') from exc


def verify_compiler_evidence(checkpoint, task_root, native_rows, *, store_path=None,
                             require_native_results=True):
    """Return verified receipt evidence; do not claim task completion/authority.

    Host/saved-task readers use the strict default. Only the active native tool
    handler may opt out of result-row verification during awaiting_native_flush;
    the existing safe point must verify the actual result before acknowledging
    control. Failed attempts and an empty list remain valid intermediate evidence.
    The caller supplies native_history's exact session projection and an existing
    checkpoint; no native DB initialization or worker claim occurs here.
    """
    task_spec = task_contract(checkpoint)
    if task_spec is None or task_spec.compiler is None:
        raise ReconciliationRequired('Compiler evidence requires an explicit compiler task')
    if type(require_native_results) is not bool:
        raise ValueError('Native result verification must be explicit')
    state = checkpoint.state
    if not require_native_results and state.get('phase') != 'awaiting_native_flush':
        raise ReconciliationRequired('Only the active native flush interval may defer result verification')
    assert_prefix(state['native_history'], native_rows)
    rows = [row for row in state['tools'] if row['name'] == TOOL_NAME]
    if require_native_results:
        verify_tool_rows(native_rows, rows)
    receipts = []
    path = Path(task_root) / 'task.sqlite3' if store_path is None else Path(store_path)
    with _readonly_store(path) as db:
        if TaskStore._read(db, checkpoint.task_id) != checkpoint:
            raise ReconciliationRequired('Compiler evidence checkpoint changed before inspection')
        for row in rows:
            args = row['args']
            if (row.get('reused') is not False or row.get('spec_sha256') != task_spec.sha256
                    or row.get('fingerprint') != digest({'name': TOOL_NAME, 'args': args})
                    or not task_spec.validate_compiler_args(args).accepted):
                raise ReconciliationRequired('Compiler receipt intent changed')
            calls = [call for message in native_rows for call in message.get('tool_calls', [])
                     if call.get('id') == row['tool_call_id']]
            if (len(calls) != 1 or calls[0]['function']['name'] != TOOL_NAME
                    or strict_json(calls[0]['function']['arguments']) != args):
                raise ReconciliationRequired('Compiler receipt differs from native intent')
            normalized = verify_compiler_result(task_root=task_root, task_spec=task_spec, args=args,
                operation_id=row['operation_id'], tool_call_id=row['tool_call_id'], result=strict_json(row['result']),
                expected_deadline=_origin_deadline(db, checkpoint, task_spec, row))
            if normalized != row.get('compiler_receipt'):
                raise ReconciliationRequired('Normalized compiler receipt changed')
            receipts.append(normalized)
    task_spec.compiler_completion(receipts)
    return receipts
