# SPDX-License-Identifier: Apache-2.0
"""Ordinary saved-task reopening through the existing store and native history.

Discovery reads plans only. Inspection opens SQLite read-only and never repairs
an archive or grants a new execution budget. New versioned tasks may preserve
their remaining allowance after a clean Stop and changed boot; legacy tasks
retain their same-boot rule. Actual execution still requires
the existing worker claim, native-history verification and user Resume.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from adaptive_inference.control_mailbox import ACKS, ControlBlocked, admission_wait_state, execution_outcome
from adaptive_inference.demand import NAMESPACE
from adaptive_inference.execution_clock import CLOCK_ID, execution_observation
from adaptive_inference.task_store import TaskStore, ReconciliationRequired, _FileLock
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.execution_budget import BUDGET, BudgetError, create_budget, reopen_budget, validate_budget

CONTEXT = 'adaptive_inference.desktop_reopen.v1'
BOOT_SOURCE = 'windows-cim-LastBootUpTime.v1'


def observe_boot():
    """One bounded local query, not polling or a psutil uptime estimate.

    https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem
    https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-5.1
    This is a conservative OS-restart observation, not a boot GUID or physical
    sleep/hibernate/Fast Startup qualification. QPC budgets include offline time.
    """
    if os.name != 'nt':
        raise RuntimeError('Saved-task execution requires the Windows boot observation')
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = """
$ErrorActionPreference = 'Stop'
$rows = @(Get-CimInstance -Namespace root/cimv2 -ClassName Win32_OperatingSystem -Property LastBootUpTime,CSName -OperationTimeoutSec 5 -ErrorAction Stop)
if ($rows.Count -ne 1) { throw 'One local operating system required' }
$boot = $rows[0].LastBootUpTime
if ($boot -isnot [datetime] -or $boot.Kind -eq [DateTimeKind]::Unspecified) { throw 'Unambiguous boot datetime required' }
if ($boot.Kind -eq [DateTimeKind]::Local -and ([TimeZoneInfo]::Local.IsAmbiguousTime($boot) -or [TimeZoneInfo]::Local.IsInvalidTime($boot))) { throw 'Ambiguous local boot time' }
@{source='windows-cim-LastBootUpTime.v1';boot_utc=$boot.ToUniversalTime().ToString('O',[Globalization.CultureInfo]::InvariantCulture);computer_name=$rows[0].CSName} | ConvertTo-Json -Compress
"""
    # run() kills and waits for its owned child on timeout. Saved data never
    # enters the command; -NoProfile avoids invoking personal startup scripts.
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, check=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if len(result.stdout) > 4096:
        raise RuntimeError('Boot observation exceeded its bound')
    return validate_boot(json.loads(result.stdout))


def validate_boot(value):
    if (type(value) is not dict or set(value) != {'source', 'boot_utc', 'computer_name'}
            or value['source'] != BOOT_SOURCE or type(value['boot_utc']) is not str
            or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z', value['boot_utc'])
            or type(value['computer_name']) is not str or not value['computer_name'].strip()
            or len(value['computer_name']) > 255):
        raise ValueError('A recognized exact Windows boot observation is required')
    datetime.fromisoformat(value['boot_utc'].replace('Z', '+00:00'))
    return deepcopy(value)


def new_context(profile_sha256, installed, boot):
    return {'schema': CONTEXT, 'deadline_clock': CLOCK_ID, 'boot': validate_boot(boot),
            'profile_sha256': profile_sha256, 'package_sha256': rec.digest(installed)}


def bind_context(value, task_root):
    if (type(value) is not dict or set(value) != {'schema', 'deadline_clock', 'boot',
            'profile_sha256', 'package_sha256'} or value['schema'] != CONTEXT
            or value['deadline_clock'] != CLOCK_ID
            or any(type(value[key]) is not str or not re.fullmatch('[0-9a-f]{64}', value[key])
                   for key in ('profile_sha256', 'package_sha256'))):
        raise ValueError('Fresh task reopen context is invalid')
    validate_boot(value['boot'])
    return {**deepcopy(value), 'task_root': str(Path(task_root).resolve())}


def read_plan(task_root):
    with (Path(task_root) / 'plan.json').open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Saved task plan exceeds its bound')
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError('Saved task plan must be an object')
    return value


def discover(runs):
    """Plans are labels, not execution authorization; no DB open or boot query."""
    rows, seen = [], set()
    root = Path(runs)
    paths = set(root.glob('session-*/hermes-task/plan.json'))
    paths.update(root.glob('session-*/tasks/*/plan.json'))
    for path in sorted(paths, reverse=True)[:500]:
        try:
            task_root = path.parent.resolve()
            if task_root in seen:
                continue
            seen.add(task_root)
            plan = read_plan(task_root)
            context = plan.get(CONTEXT)
            if type(context) is not dict or context.get('schema') != CONTEXT:
                continue  # Never retrofit historical runs into eligible tasks.
            rows.append({'saved_task': str(task_root),
                         'label': str(plan.get('task_spec', {}).get('prompt', plan['task_id']))[:160]})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return rows


def readonly_checkpoint(task_root, task_id):
    path = Path(task_root) / 'task.sqlite3'
    if not path.is_file() or any(Path(str(path) + suffix).exists()
                                for suffix in ('-journal', '-wal', '-shm')):
        raise ReconciliationRequired('Saved store is missing or needs explicit recovery')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA locking_mode=EXCLUSIVE')
        db.execute('BEGIN')
        TaskStore._verify_schema(db)
        if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete' or db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ReconciliationRequired('Saved store layout or integrity differs')
        return TaskStore._read(db, task_id)
    finally:
        db.close()


def read_saved(task_root):
    """Read original integrity and results without granting execution authority."""
    task_root = Path(task_root).resolve(strict=True)
    plan = read_plan(task_root)
    context = plan.get(CONTEXT)
    if type(context) is not dict or context != bind_context(
            {key: value for key, value in context.items() if key != 'task_root'}, task_root):
        raise ReconciliationRequired('Saved task original context differs or is missing')
    cp = readonly_checkpoint(task_root, plan['task_id'])
    if cp.metadata.get(CONTEXT) != context or cp.state.get('deadline_clock') != CLOCK_ID:
        raise ReconciliationRequired('Saved checkpoint has no matching original reopen context')
    if cp.owner_epoch is not None or cp.operation is not None or cp.requires_reconciliation:
        raise ReconciliationRequired('Saved task has an owner or unresolved operation')
    if execution_outcome(cp.state) is not None:
        raise ReconciliationRequired('Saved execution is sealed')
    if cp.state.get('pending_request') is not None:
        # Ordinary Stop can preserve a known undispatched admission wait. Reuse
        # its bounded state/accounting and native-tool checks; do not erase the
        # request or renew its deadline. The owned worker verifies native history
        # before its normal conversation rebuild after a fresh Resume.
        from adaptive_inference.desktop.hermes.service_stop import flushed_tools
        try:
            admission_wait_state(cp.state)
            if (cp.state['pending_request']['model'] != cp.metadata.get('model')
                    or cp.state.get(NAMESPACE, {}).get('state') != 'paused'):
                raise ControlBlocked('Saved admission wait differs from its paused task')
            flushed_tools(cp.state)
        except (ControlBlocked, rec.RecoveryStop) as error:
            raise ReconciliationRequired('Saved request is not a known stopped admission wait') from error
    if cp.state.get('phase') not in ('ready', 'waiting_admission', 'accepted'):
        raise ReconciliationRequired('Saved task has no safe checkpoint')
    for name, expected_sha in plan['pins'].items():
        if rec.digest(Path(name).read_bytes()) != expected_sha:
            raise ReconciliationRequired('Saved task input or configuration changed')
    spec = rec.task_contract(cp)
    rec.verify_artifacts(cp.state, task_root / 'work', task_spec=spec)
    compiler_receipts = rec.verified_compiler_receipts(cp, task_root)
    completed = cp.state['status'] == 'accepted' and cp.state['phase'] == 'accepted'
    if completed and spec is not None and spec.compiler is not None:
        spec.completion(task_root/'work', cp.state['tools'], cp.state['output'],
                        compiler_receipts=compiler_receipts)
    deadline = cp.state.get('deadline_monotonic')
    if not completed:
        if cp.state['status'] != 'pending' or cp.state.get(NAMESPACE, {}).get('state') == 'cancelled':
            raise ReconciliationRequired('Saved task is not resumable')
    return {'work': task_root, 'plan': plan, 'checkpoint': cp, 'deadline': deadline,
            'completed': completed, 'spec': spec}


def task_budget(state, context):
    """Bind the versioned allowance to its immutable creation context and state."""
    value = validate_budget(state[BUDGET])
    if (value['origin']['boot_id'] != rec.digest(validate_boot(context['boot']))
            or value['episode']['deadline'] != state.get('deadline_monotonic')):
        raise BudgetError('Budget differs from its original context or current deadline')
    return value


def worker_budget(state, context, *, deadline, boot_id, observation=None):
    """Called by the existing owner before native setup, never renew a grant."""
    state = deepcopy(state)
    if BUDGET in state:
        value = task_budget(state, context)
        if (boot_id != value['episode']['boot_id'] or value['episode']['deadline'] != deadline
                or value['clean_stop']):
            raise BudgetError('Worker lacks the committed current-boot budget transition')
    elif state.get('deadline_monotonic') is None and boot_id is not None:
        if context is None or boot_id != rec.digest(validate_boot(context['boot'])):
            raise BudgetError('Fresh budget requires its observed original boot context')
        state[BUDGET] = create_budget(boot_id=boot_id, deadline=deadline,
            observation=execution_observation() if observation is None else observation)
    return state


def inspect_saved(task_root, *, profile_sha256, installed, boot, now, observation=None):
    """Read-only eligibility; changed-boot time is committed later under ownership."""
    value = read_saved(task_root)
    if value['completed']:
        return value
    expected = bind_context(new_context(profile_sha256, installed, boot), value['work'])
    if BUDGET in value['checkpoint'].state:
        original_boot = value['plan'][CONTEXT]['boot']
        if boot['computer_name'] != original_boot['computer_name']:
            raise ReconciliationRequired('Saved task belongs to a different computer')
        expected['boot'] = original_boot
    if value['plan'][CONTEXT] != expected:
        raise ReconciliationRequired('Saved task boot, profile or package context differs or is missing')
    deadline = value['deadline']
    if BUDGET in value['checkpoint'].state:
        try:
            budget = task_budget(value['checkpoint'].state, value['plan'][CONTEXT])
            proposed = reopen_budget(budget, boot_id=rec.digest(validate_boot(boot)),
                observation=execution_observation() if observation is None else observation)
            deadline = proposed['episode']['deadline']
        except BudgetError as error:
            raise ReconciliationRequired(str(error)) from error
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or not 0 < deadline - now <= 900):
        raise ReconciliationRequired('Original saved execution budget is exhausted or invalid')
    return value


def activate_saved_budget(saved, store, *, boot, observation=None):
    """Commit only the budget transition before the host's paused snapshot.

    The composition retains its task-specific host lock. TaskStore's revision
    claim and ordinary checkpoint transaction retain the earlier state in history.
    No provider, native history, tool effect, prompt or request counter is changed.
    """
    cp = saved['checkpoint']
    if BUDGET not in cp.state:
        return saved
    with store.claim(cp.task_id, expected_revision=cp.revision) as owned:
        state = deepcopy(owned.checkpoint.state)
        value = task_budget(state, saved['plan'][CONTEXT])
        state[BUDGET] = reopen_budget(value, boot_id=rec.digest(validate_boot(boot)),
            observation=execution_observation() if observation is None else observation)
        state['deadline_monotonic'] = state[BUDGET]['episode']['deadline']
        owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
    return read_saved(saved['work'])


def claim_host(task_root):
    """Reuse the existing OS lock to prevent two desktop owners before Pause."""
    return _FileLock(str(Path(task_root) / 'desktop-host.lock'))


def assert_paused_saved(cp, original, deadline, host):
    before, after = deepcopy(original.state), deepcopy(cp.state)
    old_acks, new_acks = before.pop(ACKS, {}), after.pop(ACKS, {})
    before.pop(NAMESPACE, None); after.pop(NAMESPACE, None)
    if (before != after or cp.prompt != original.prompt or cp.metadata != original.metadata
            or cp.max_attempts != original.max_attempts or cp.operation is not None or cp.requires_reconciliation
            or cp.state.get('deadline_monotonic') != deadline
            or cp.state[NAMESPACE]['state'] != 'paused'):
        raise ReconciliationRequired('Saved progress changed before the new Resume')
    rec.assert_prefix(old_acks.get('receipts', []), new_acks.get('receipts', []))
    if (host.adapter.launch_intent is not None or host.adapter.started_owner
            or host.gateway._runtime_context is not None or host.gateway.history
            or host.gateway.scheduler.active is not None or host.gateway.scheduler.pending
            or host.gateway.scheduler.uncertain or host.controller.fault is not None):
        raise ReconciliationRequired('Reopened host performed work before Resume')


def completed_result(saved):
    cp = saved['checkpoint']
    if not saved['completed']:
        raise ValueError('Only a completed task has a saved result view')
    return {'task_id': cp.task_id, 'objective': cp.prompt, 'output': cp.state['output'],
            'artifacts': [row['args']['path'] for row in cp.state['tools'] if row['name'] == 'write_file'],
            'provider_calls': 0, 'task_completed': True, 'read_only': True}
