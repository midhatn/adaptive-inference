# SPDX-License-Identifier: Apache-2.0
"""One opted-in compiler tool using existing TaskStore and native recovery.

The pinned Hermes public PluginContext.register_tool API runs this synchronous
handler only after native authorization. Its generic dispatcher does not pass
tool_call_id, so our middleware carries a verified call through a ContextVar.
https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_cli/plugins.py
https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/model_tools.py
Completed native call identities fence repeat effects, following the existing
TaskStore ledger and the durable-execution idempotency pattern:
https://docs.temporal.io/activity-definition#idempotency
"""
from contextvars import ContextVar
from copy import deepcopy
import json
import math
import os
import re

from adaptive_inference.desktop.hermes.compiler_evidence import (
    TOOL_NAME, verify_recipe_evidence, verify_recipe_result)
from adaptive_inference.desktop.hermes.recovery import (
    Recovery, RecoveryStop, ReconciliationRequired, native_history, assert_prefix, digest,
    task_contract, verify_artifacts, verify_tool_rows, verify_validation_rows)
from adaptive_inference.control_mailbox import execution_outcome
from adaptive_inference.task_spec import strict_json
from adaptive_inference.desktop.recipe_dispatch import definition, recipe_kind

TOOLSET = 'adaptive_compiler'
_CALL = ContextVar('adaptive_compiler_native_call', default=None)


def _identity(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value) is not None


def reconcile_recipe(owned, db, work, receipt, *, expected_operation_id):
    """Explicitly restore feedback for an already completed, verified recipe.

    Reuse reconcile_write's native-lease/native-first checkpoint sequence. The
    original operation_completed row is proof; an unresolved effect stays fenced.
    Repeated recovery recognizes the identical native row instead of dispatching
    again, including loss after append but before checkpoint. Design references:
    https://docs.temporal.io/activity-definition#idempotency
    https://docs.langchain.com/oss/python/langgraph/functional-api
    """
    cp = owned.checkpoint
    state = deepcopy(cp.state)
    spec = task_contract(cp)
    kind = recipe_kind(spec)
    if (kind is None or cp.operation or cp.requires_reconciliation
            or execution_outcome(state) is not None or state.get('status') != 'pending'
            or state.get('phase') not in ('awaiting_native_flush', 'ready')
            or type(receipt) is not dict or not _identity(expected_operation_id)
            or receipt.get('operation_id') != expected_operation_id):
        raise ReconciliationRequired('Expected completed recipe checkpoint required')
    selected = definition(kind)
    if (receipt.get('name') != selected.tool_name or not state['tools']
            or state['tools'][-1] != receipt
            or sum(row.get('operation_id') == expected_operation_id for row in state['tools']) != 1):
        raise ReconciliationRequired('Receipt differs from the last durable completed recipe')
    session_id = state['session_id']
    holder = f'pid={os.getpid()}:adaptive-recipe-reconcile={expected_operation_id}'
    if not db.acquire_session_turn_lease(session_id, holder, wait_seconds=0):
        raise ReconciliationRequired('Native session is still owned')
    try:
        history = native_history(db, session_id)
        assert_prefix(state['native_history'], history)
        verify_artifacts(state, work, task_spec=spec)
        verify_validation_rows(history, state, cp.metadata.get('pre_effect_validator'))
        verify_tool_rows(history, state['tools'][:-1])
        ready = state['phase'] == 'ready'
        verify_recipe_evidence(cp, owned._store.path.parent, history,
            store_path=owned._store.path, require_native_results=ready)
        if ready:
            if history != state['native_history']:
                raise ReconciliationRequired('Ready recipe checkpoint differs from native history')
            return cp
        rows = [row for row in history if row.get('role') == 'tool'
                and row.get('tool_call_id') == receipt['tool_call_id']]
        if rows and (len(rows) != 1 or rows[0].get('content') != receipt['result']):
            raise ReconciliationRequired('Conflicting native recipe result exists')
        # No new agent turn may have advanced past this unfinished flush.
        suffix = history[len(state['native_history']):]
        if suffix != rows:
            raise ReconciliationRequired('Unexpected native messages after completed recipe')
        if not rows:
            db.append_message(session_id, 'tool', content=receipt['result'],
                tool_name=selected.tool_name, tool_call_id=receipt['tool_call_id'],
                turn_lease_holder=holder)
        history = native_history(db, session_id)
        assert_prefix(state['native_history'], history)
        suffix = history[len(state['native_history']):]
        if (len(suffix) != 1 or suffix[0].get('role') != 'tool'
                or suffix[0].get('tool_call_id') != receipt['tool_call_id']
                or suffix[0].get('content') != receipt['result']):
            raise ReconciliationRequired('Native history advanced during recipe feedback repair')
        verify_tool_rows(history, state['tools'])
        verify_validation_rows(history, state, cp.metadata.get('pre_effect_validator'))
        verify_recipe_evidence(cp, owned._store.path.parent, history,
            store_path=owned._store.path)
        state.update(phase='ready', native_history=history)
        return owned.save_checkpoint(state, expected_revision=cp.revision)
    finally:
        db.release_session_turn_lease(session_id, holder)


class CompilerRecovery(Recovery):
    def __init__(self, *args, compiler_client, host_epoch, task_id, execution_id, kind='compiler', **kwargs):
        super().__init__(*args, **kwargs)
        self.definition = definition(kind)
        cp = self.owned.checkpoint
        logical = cp.metadata.get('adaptive_inference.execution_authorization.v1', {}).get('logical_task_id', cp.task_id)
        if (self.definition.contract(self.task_spec) is None or not callable(compiler_client)
                or not all(_identity(value) for value in (host_epoch, task_id, execution_id))
                or execution_id != cp.task_id or task_id != logical):
            raise ReconciliationRequired('Explicit compiler task and selected host/execution binding required')
        deadline = cp.state.get('deadline_monotonic')
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0:
            raise ReconciliationRequired('Compiler requires the original execution deadline')
        self.compiler_client = compiler_client
        self.host_epoch, self.task_id, self.execution_id = host_epoch, task_id, execution_id
        self.compiler_deadline = deadline

    def register_tool(self, ctx):
        return ctx.register_tool(name=self.definition.tool_name, toolset=self.definition.toolset,
            schema=self.definition.tool_schema(self.task_spec),
            handler=self._handle_compiler, is_async=False, override=False)

    def _intent(self, args, session_id, tool_call_id):
        cp, state = self.owned.checkpoint, self.state()
        if (self.fatal or cp.task_id != self.execution_id or cp.operation or cp.requires_reconciliation
                or session_id != state['session_id'] or not _identity(tool_call_id)
                or any(row.get('tool_call_id') == tool_call_id for row in state['tools'])
                or state.get('deadline_monotonic') != self.compiler_deadline):
            raise ReconciliationRequired('Compiler identity, ownership or pending operation changed')
        self.task_spec.verify_inputs(self.work)
        history = native_history(self.db, session_id)
        assert_prefix(state['native_history'], history)
        calls = [call for row in history for call in row.get('tool_calls', []) if call.get('id') == tool_call_id]
        if (len(calls) != 1 or calls[0]['function']['name'] != self.definition.tool_name
                or strict_json(calls[0]['function']['arguments']) != args):
            raise ReconciliationRequired('Exact compiler intent must already be native-durable')
        return state, history

    def tool(self, tool_name, args, next_call, session_id='', tool_call_id='', **kwargs):
        if tool_name != self.definition.tool_name:
            return super().tool(tool_name, args, next_call, session_id=session_id, tool_call_id=tool_call_id, **kwargs)
        with self.lock:
            try:
                if self.fatal:
                    return self._deny(self.fatal)
                self.control_safe_point()
                self._intent(args, session_id, tool_call_id)
                verdict = self.definition.validate_args(self.task_spec, args, completed_runs=len(self.recipe_receipts()))
                if not verdict.accepted:
                    return json.dumps({'error': self.definition.kind + '_proposal_rejected', 'dispatched': False,
                                       'feedback': verdict.feedback}, ensure_ascii=False)
                binding = {'controller': self, 'args': deepcopy(args), 'session_id': session_id,
                           'tool_call_id': tool_call_id, 'entered': False, 'result': None}
                token = _CALL.set(binding)
                try:
                    result = next_call(args)
                finally:
                    _CALL.reset(token)
                if self.fatal or self.owned.checkpoint.operation:
                    return self._deny(self.fatal or 'Unresolved compiler operation')
                if not isinstance(result, str):
                    raise ReconciliationRequired('Compiler result must be a serialized native tool result')
                # An authorization refusal can return without reaching our handler.
                # In that case there is no compiler effect, grant or invented receipt.
                if binding['entered'] and result != binding['result']:
                    raise ReconciliationRequired('Native compiler result changed after the handler')
                return result
            except RecoveryStop:
                raise
            except Exception as exc:
                return self._deny(type(exc).__name__)

    def _handle_compiler(self, args, task_id=None, session_id=None, **_):
        with self.lock:
            try:
                binding = _CALL.get()
                if (not binding or binding['controller'] is not self or binding['entered']
                        or args != binding['args'] or session_id != binding['session_id']
                        or task_id != self.task_id):
                    raise ReconciliationRequired('Authorized compiler dispatch lacks its exact native binding')
                binding['entered'] = True
                state, history = self._intent(args, session_id, binding['tool_call_id'])
                prior = self.recipe_receipts()
                verdict = self.definition.validate_args(self.task_spec, args, completed_runs=len(prior))
                if not verdict.accepted:
                    raise ReconciliationRequired('Compiler proposal changed before authorized dispatch')
                activity = getattr(self.controls, 'wait_activity', None)
                if activity is not None:
                    activity.check_final(self.agent)
                details = {'name': self.definition.tool_name, 'args': deepcopy(args), 'tool_call_id': binding['tool_call_id'],
                           'session_id': session_id, 'fingerprint': digest({'name': self.definition.tool_name, 'args': args}),
                           'host_epoch': self.host_epoch, 'task_id': self.task_id, 'execution_id': self.execution_id,
                           'owner_epoch': self.owned.checkpoint.owner_epoch, 'spec_sha256': self.task_spec.sha256}
                state.update(phase='tool_running', native_history=history)
                cp = self.owned.begin_operation('effect', details=details, state=state,
                                               expected_revision=self.owned.checkpoint.revision)
                request = {'schema': self.definition.request_schema, 'host_epoch': self.host_epoch,
                           'task_id': self.task_id, 'execution_id': self.execution_id,
                           'owner_epoch': cp.owner_epoch, 'operation_id': cp.operation['id'],
                           'tool_call_id': binding['tool_call_id'], 'recipe_id': args['recipe_id']}
                projected = self.compiler_client(deepcopy(request))
                normalized = self._compiler_receipt(args, cp.operation['id'], binding['tool_call_id'], projected)
                self.definition.completion(self.task_spec, prior + [normalized])
                result = json.dumps(projected, sort_keys=True, ensure_ascii=False, allow_nan=False)
                if len(result.encode('utf-8')) > 24576:
                    raise ReconciliationRequired('Compiler feedback exceeds its bound')
                receipt = {**details, 'operation_id': cp.operation['id'], 'result': result,
                           self.definition.receipt_key: normalized, 'reused': False}
                with (self.run / 'effect-receipts.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(json.dumps(receipt, ensure_ascii=False) + '\n'); stream.flush(); os.fsync(stream.fileno())
                state['tools'].append(receipt)
                state['phase'] = 'awaiting_native_flush'
                self.owned.complete_operation(cp.operation['id'], result=receipt, state=state,
                                              expected_revision=self.owned.checkpoint.revision)
                binding['result'] = result
                return result
            except RecoveryStop:
                raise
            except Exception as exc:
                return self._deny(type(exc).__name__)

    def _compiler_receipt(self, args, operation_id, tool_call_id, result):
        # A newly returned result always uses this execution's original deadline.
        return verify_recipe_result(task_root=self.run, task_spec=self.task_spec,
            args=args, operation_id=operation_id, tool_call_id=tool_call_id,
            result=result, expected_deadline=self.compiler_deadline)

    def compiler_receipts(self):
        return self.recipe_receipts() if self.definition.kind == 'compiler' else None

    def recipe_receipts(self):
        with self.lock:
            checkpoint = self.owned.checkpoint
            history = native_history(self.db, checkpoint.state['session_id'])
            return verify_recipe_evidence(checkpoint, self.run, history,
                store_path=self.owned._store.path,
                require_native_results=checkpoint.state.get('phase') != 'awaiting_native_flush')

    def control_safe_point(self):
        with self.lock:
            self.recipe_receipts()
            return super().control_safe_point()

    def bootstrap_controls(self):
        with self.lock:
            self.recipe_receipts()
            return super().bootstrap_controls()
