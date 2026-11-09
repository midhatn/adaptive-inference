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
    TOOL_NAME, verify_compiler_evidence, verify_compiler_result)
from adaptive_inference.desktop.hermes.recovery import (
    Recovery, RecoveryStop, ReconciliationRequired, native_history, assert_prefix, digest)
from adaptive_inference.task_spec import strict_json

TOOLSET = 'adaptive_compiler'
_CALL = ContextVar('adaptive_compiler_native_call', default=None)


def _identity(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value) is not None


class CompilerRecovery(Recovery):
    def __init__(self, *args, compiler_client, host_epoch, task_id, execution_id, **kwargs):
        super().__init__(*args, **kwargs)
        cp = self.owned.checkpoint
        logical = cp.metadata.get('adaptive_inference.execution_authorization.v1', {}).get('logical_task_id', cp.task_id)
        if (self.task_spec is None or self.task_spec.compiler is None or not callable(compiler_client)
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
        compiler = self.task_spec.compiler
        return ctx.register_tool(name=TOOL_NAME, toolset=TOOLSET,
            schema={'name': TOOL_NAME, 'description': 'Compile and test C++17 source using this task\'s fixed recipe. '
                    'Compiler diagnostics can be corrected in a new attempt within the original allowance.',
                    'parameters': {'type': 'object', 'properties': {
                        'recipe_id': {'type': 'string', 'enum': [compiler['recipe_id']]},
                        'source': {'type': 'string', 'minLength': 1, 'maxLength': compiler['max_source_chars']}},
                        'required': ['recipe_id', 'source'], 'additionalProperties': False}},
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
        if (len(calls) != 1 or calls[0]['function']['name'] != TOOL_NAME
                or strict_json(calls[0]['function']['arguments']) != args):
            raise ReconciliationRequired('Exact compiler intent must already be native-durable')
        return state, history

    def tool(self, tool_name, args, next_call, session_id='', tool_call_id='', **kwargs):
        if tool_name != TOOL_NAME:
            return super().tool(tool_name, args, next_call, session_id=session_id, tool_call_id=tool_call_id, **kwargs)
        with self.lock:
            try:
                if self.fatal:
                    return self._deny(self.fatal)
                self.control_safe_point()
                self._intent(args, session_id, tool_call_id)
                verdict = self.task_spec.validate_compiler_args(args, completed_runs=len(self.compiler_receipts()))
                if not verdict.accepted:
                    return json.dumps({'error': 'compiler_proposal_rejected', 'dispatched': False,
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
                prior = self.compiler_receipts()
                verdict = self.task_spec.validate_compiler_args(args, completed_runs=len(prior))
                if not verdict.accepted:
                    raise ReconciliationRequired('Compiler proposal changed before authorized dispatch')
                activity = getattr(self.controls, 'wait_activity', None)
                if activity is not None:
                    activity.check_final(self.agent)
                details = {'name': TOOL_NAME, 'args': deepcopy(args), 'tool_call_id': binding['tool_call_id'],
                           'session_id': session_id, 'fingerprint': digest({'name': TOOL_NAME, 'args': args}),
                           'host_epoch': self.host_epoch, 'task_id': self.task_id, 'execution_id': self.execution_id,
                           'owner_epoch': self.owned.checkpoint.owner_epoch, 'spec_sha256': self.task_spec.sha256}
                state.update(phase='tool_running', native_history=history)
                cp = self.owned.begin_operation('effect', details=details, state=state,
                                               expected_revision=self.owned.checkpoint.revision)
                request = {'schema': 'compiler-operation.v1', 'host_epoch': self.host_epoch,
                           'task_id': self.task_id, 'execution_id': self.execution_id,
                           'owner_epoch': cp.owner_epoch, 'operation_id': cp.operation['id'],
                           'tool_call_id': binding['tool_call_id'], 'recipe_id': args['recipe_id']}
                projected = self.compiler_client(deepcopy(request))
                normalized = self._compiler_receipt(args, cp.operation['id'], binding['tool_call_id'], projected)
                self.task_spec.compiler_completion(prior + [normalized])
                result = json.dumps(projected, sort_keys=True, ensure_ascii=False, allow_nan=False)
                if len(result.encode('utf-8')) > 24576:
                    raise ReconciliationRequired('Compiler feedback exceeds its bound')
                receipt = {**details, 'operation_id': cp.operation['id'], 'result': result,
                           'compiler_receipt': normalized, 'reused': False}
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
        return verify_compiler_result(task_root=self.run, task_spec=self.task_spec,
            args=args, operation_id=operation_id, tool_call_id=tool_call_id,
            result=result, expected_deadline=self.compiler_deadline)

    def compiler_receipts(self):
        with self.lock:
            checkpoint = self.owned.checkpoint
            history = native_history(self.db, checkpoint.state['session_id'])
            return verify_compiler_evidence(checkpoint, self.run, history,
                store_path=self.owned._store.path,
                require_native_results=checkpoint.state.get('phase') != 'awaiting_native_flush')

    def control_safe_point(self):
        with self.lock:
            self.compiler_receipts()
            return super().control_safe_point()

    def bootstrap_controls(self):
        with self.lock:
            self.compiler_receipts()
            return super().bootstrap_controls()
