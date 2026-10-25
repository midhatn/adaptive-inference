# SPDX-License-Identifier: Apache-2.0
"""Opt-in, bounded Hermes file-task recovery through public middleware/SessionDB.

This is an integration consumer of adaptive_inference.task_store, not a fork of
Hermes. Both databases are private. Cross-database uncertainty always blocks.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from adaptive_inference.task_store import ReconciliationRequired
from adaptive_inference.feedback import Verdict
from adaptive_inference.desktop.hermes.admission import AdmissionStop


class RecoveryStop(BaseException):
    """Escape Hermes' deliberately fail-open Exception middleware boundary."""


class ControlStop(RecoveryStop):
    """Cooperative user control; never a failed provider attempt or replay permit."""
    def __init__(self, state, reason):
        self.control_state, self.reason = state, reason
        super().__init__('Task control: ' + state + ' (' + reason + ')')


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def initial_state(prompt, session_id):
    return {'status': 'pending', 'messages': [{'role': 'user', 'content': prompt}],
            'attempts': 0, 'feedback': [], 'output': '', 'phase': 'ready',
            'session_id': session_id, 'native_history': [], 'tools': [], 'requests': 0,
            'admission_attempts': 0, 'admission_deferrals': [], 'pending_request': None}


def native_history(db, session_id):
    if db.resolve_resume_session_id(session_id) != session_id:
        raise ReconciliationRequired('Session lineage changed; bounded recovery cannot guess a new tip')
    return db.get_messages_as_conversation(session_id, include_row_ids=True)


def assert_prefix(old, new):
    if len(new) < len(old) or new[:len(old)] != old:
        raise ReconciliationRequired('Native transcript changed outside the owned append-only run')


def verify_tool_rows(history, tools):
    for tool in tools:
        found = [row for row in history if row.get('role') == 'tool'
                 and row.get('tool_call_id') == tool['tool_call_id']]
        if len(found) != 1 or found[0].get('content') != tool['result']:
            raise ReconciliationRequired('A completed tool receipt is not exactly present in native history')


def verify_validation_rows(history, state, validator_identity=None):
    """Rejected proposals are durable tool feedback, never dispatched effects."""
    rows=state.get('validation_rejections',[])
    if type(rows) is not list:
        raise ReconciliationRequired('Validation receipt collection is invalid')
    ids={row['tool_call_id'] for row in state['tools']}
    for row in rows:
        if (type(row) is not dict or row.get('dispatched') is not False
                or row.get('name')!='write_file' or not row.get('operation_id')
                or not row.get('tool_call_id') or row['tool_call_id'] in ids
                or validator_identity is None or row.get('validator_identity')!=validator_identity):
            raise ReconciliationRequired('Rejected proposal receipt is invalid')
        ids.add(row['tool_call_id'])
        calls=[call for message in history for call in message.get('tool_calls',[])
               if call.get('id')==row['tool_call_id']]
        if (len(calls)!=1 or calls[0]['function']['name']!=row['name']
                or json.loads(calls[0]['function']['arguments'])!=row['args']
                or row['fingerprint']!=digest({'name':row['name'],'path':Path(row['args']['path']).name,
                    'args':{k:v for k,v in row['args'].items() if k!='path'}})):
            raise ReconciliationRequired('Rejected proposal intent differs from native history')
    verify_tool_rows(history,rows)


def resumable(owned, db, work):
    """Called under TaskStore ownership, before agent construction/model discovery."""
    checkpoint = owned.checkpoint
    state = checkpoint.state
    if checkpoint.operation or checkpoint.requires_reconciliation:
        raise ReconciliationRequired('Interrupted operation requires explicit reconciliation')
    if state['phase'] not in ('ready', 'waiting_admission', 'accepted'):
        raise ReconciliationRequired('No verified native checkpoint exists for the last operation')
    history = native_history(db, state['session_id'])
    if history != state['native_history']:
        raise ReconciliationRequired('Native state differs from the durable safe checkpoint')
    verify_tool_rows(history, state['tools'])
    verify_validation_rows(history,state,checkpoint.metadata.get('pre_effect_validator'))
    verify_artifacts(state, work)
    return history


def verify_artifacts(state, work):
    """Same bounded artifact check reused before accepting controls after flush."""
    for tool in state['tools']:
        if tool['name'] == 'write_file':
            path = (Path(work).resolve() / tool['args']['path']).resolve()
            if (path != Path(work).resolve() / 'report.json' or not path.is_file()
                    or digest(path.read_bytes()) != tool['artifact_sha256']):
                raise ReconciliationRequired('A completed artifact changed after its durable receipt')


class Recovery:
    """One cooperating task owner; native tool effects are serialized by this lock.

    Only the declared CSV read and report write are admitted by this bounded
    adapter. A file-write receipt is durable before a later model call; a replay
    of an identical completed write returns its prior result without dispatch.
    """
    def __init__(self, owned, db, work, run, *, pause=None, max_requests=8, controls=None,
                 pre_effect_validator=None, validator_identity=None):
        if ((pre_effect_validator is None)!=(validator_identity is None)
                or pre_effect_validator is not None and not callable(pre_effect_validator)):
            raise ValueError('Validator callback and identity must be configured together')
        if validator_identity is not None and (type(validator_identity) is not dict or not validator_identity
                or len(validator_identity)>8 or any(type(k) is not str or type(v) is not str
                    or not k or not v or len(k)>128 or len(v)>128 for k,v in validator_identity.items())):
            raise ValueError('Validator identity must be a bounded versioned string mapping')
        if getattr(getattr(owned,'checkpoint',None),'metadata',{}).get('pre_effect_validator')!=validator_identity:
            raise ReconciliationRequired('Prepared validator identity differs; explicit migration required')
        self.pre_effect_validator=pre_effect_validator
        self.validator_identity=copy.deepcopy(validator_identity)
        self.owned, self.db = owned, db
        self.work, self.run = Path(work).resolve(), Path(run).resolve()
        self.pause, self.max_requests = pause, max_requests
        self.lock = threading.RLock()
        self.fatal = None
        self.agent = None
        self.provider = None
        self.controls = controls

    def state(self):
        return copy.deepcopy(self.owned.checkpoint.state)

    def checkpoint(self, state):
        return self.owned.save_checkpoint(state, expected_revision=self.owned.checkpoint.revision)

    def control_safe_point(self):
        """Owner-only gate after actual native history/receipts are safe to retain."""
        if self.controls is None:
            return
        if self.owned.checkpoint.operation or self.owned.checkpoint.requires_reconciliation:
            raise ReconciliationRequired('Controls cannot acknowledge unresolved execution')
        state = self.state()
        if state['phase'] not in ('ready', 'waiting_admission', 'awaiting_native_flush'):
            raise ReconciliationRequired('Unknown application checkpoint phase')
        history = native_history(self.db, state['session_id'])
        assert_prefix(state['native_history'], history)
        verify_tool_rows(history, state['tools'])
        verify_validation_rows(history,state,self.validator_identity)
        verify_artifacts(state, self.work)
        if state['phase'] == 'awaiting_native_flush' and len(history) <= len(state['native_history']):
            raise ReconciliationRequired('Native completion has not reached durable history')
        if history != state['native_history'] or state['phase'] == 'awaiting_native_flush':
            state.update(native_history=history,
                         phase='waiting_admission' if state['phase']=='waiting_admission' else 'ready')
            self.checkpoint(state)
        self.controls.poll(self.owned)
        # Callers must take a NEW state copy after this gate. Controls may have
        # committed demand/ACKs while the owner waited; old copies are unsafe.

    def bootstrap_controls(self):
        """Before readiness/agent construction; metadata must be prepared already."""
        if self.controls is None:
            raise ValueError('Bootstrap requires explicit opted-in controls')
        resumable(self.owned, self.db, self.work)
        self.controls.bootstrap(self.owned)

    def barrier(self, label):
        if self.pause != label:
            return
        save(self.run / 'pause.json', {'boundary': label, 'pid': os.getpid(),
             'revision': self.owned.checkpoint.revision,
             'history_sha256': digest(self.owned.checkpoint.state['native_history'])})
        # The outer owner kills THIS retained process; never an arbitrary PID/name.
        # Finite even if the owner disappears. No provider/tool call occurs here.
        until = time.monotonic() + 600
        while time.monotonic() < until:
            time.sleep(.1)
        raise RecoveryStop('Checkpoint pause exceeded its external ownership window')

    def _deny(self, reason):
        self.fatal = reason
        if self.agent is not None:
            try:
                self.agent.interrupt(hard_cancel=True, tool_reason='gateway_shutdown')
            except Exception:
                # Interrupt notification is advisory. Its failure must not escape
                # this short circuit into Hermes' fail-open middleware handling.
                pass
        return json.dumps({'error': 'Recovery stopped before another effect', 'recovery_required': True})

    def llm(self, request, next_call, session_id='', **_):
        # Never raise ordinary Exception before next_call: Hermes would fail open.
        with self.lock:
            try:
                if self.fatal:
                    raise ReconciliationRequired(self.fatal)
                state = self.state()
                if session_id != state['session_id'] or self.owned.checkpoint.operation:
                    raise ReconciliationRequired('Wrong session or unfinished operation')
                history = native_history(self.db, session_id)
                assert_prefix(state['native_history'], history)
                verify_tool_rows(history, state['tools'])
                verify_validation_rows(history,state,self.validator_identity)
                if not any(row.get('role') == 'user' and row.get('content') == self.owned.checkpoint.prompt
                           for row in history):
                    raise ReconciliationRequired('Original objective missing from native history')
                self.control_safe_point()
                state = self.state()
                state.update(phase='ready', native_history=history)
                self.checkpoint(state)
                if any(row['name'] == 'write_file' for row in state['tools']):
                    self.barrier('safe_after_write')
                if state['requests'] >= self.max_requests:
                    raise ReconciliationRequired('Task request bound reached')
                if self.provider is None:
                    raise ReconciliationRequired('Explicit admission-aware provider is required')
                def waiting(pending):
                    current=self.state()
                    if self.owned.checkpoint.operation:
                        raise ReconciliationRequired('Cannot wait with an uncertain provider operation')
                    if current.get('phase')!='waiting_admission' or current.get('pending_request')!=pending:
                        current.update(phase='waiting_admission',pending_request=copy.deepcopy(pending))
                        self.checkpoint(current)
                        self.admission_event('waiting',request_sha256=digest(pending))
                def begin(attempt):
                    self.control_safe_point()
                    current=self.state()
                    if current.get('admission_attempts',0)>=32:
                        raise ReconciliationRequired('Whole task admission-attempt bound reached')
                    current.update(phase='generating',admission_attempts=current.get('admission_attempts',0)+1)
                    cp=self.owned.begin_operation('generation',details={
                        'request_sha256':digest(request),'attempt_id':attempt,
                        'pure_provider_request':True},state=current,
                        expected_revision=self.owned.checkpoint.revision)
                    self.admission_event('attempt',attempt_id=attempt,request_sha256=digest(request))
                    return cp.operation['id']
                def deferred(operation,evidence):
                    current=self.state()
                    if evidence['attempt_id']!=self.owned.checkpoint.operation['details']['attempt_id']:
                        raise ReconciliationRequired('Deferral operation does not match')
                    current.update(phase='waiting_admission')
                    current['admission_deferrals'].append(copy.deepcopy(evidence))
                    self.owned.complete_operation(operation,result={'dispatched':False,'proof':evidence},
                        state=current,expected_revision=self.owned.checkpoint.revision)
                    self.admission_event('deferred',proof=evidence)
                def completed(operation):
                    current=self.state()
                    current.update(phase='awaiting_native_flush',pending_request=None,
                                   requests=current['requests']+1,attempts=current['attempts']+1)
                    self.owned.complete_operation(operation,result={'provider_returned':True},
                        state=current,expected_revision=self.owned.checkpoint.revision)
                    self.admission_event('completed',provider_calls=current['requests'])
                # Supported public short-circuit: do not invoke the single-use
                # next_call. The genuine SDK response still enters the native
                # Hermes response/tool/transcript pipeline after this returns.
                callbacks=dict(waiting=waiting,begin=begin,deferred=deferred,completed=completed)
                if self.controls is not None:
                    callbacks['poll_control']=self.control_safe_point
                return self.provider.execute(request,**callbacks)
            except RecoveryStop:
                raise
            except AdmissionStop as exc:
                raise RecoveryStop(str(exc)) from exc
            except Exception as exc:
                self.fatal = type(exc).__name__
                raise RecoveryStop('Provider dispatch stopped by recovery boundary: ' + type(exc).__name__) from exc

    def admission_event(self,kind,**fields):
        row={'kind':kind,'monotonic_s':time.monotonic(),**fields}
        with (self.run/'admission-events.jsonl').open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())

    def tool(self, tool_name, args, next_call, session_id='', tool_call_id='', **_):
        with self.lock:
            try:
                if self.fatal:
                    return self._deny(self.fatal)
                if session_id != self.owned.checkpoint.state['session_id']:
                    raise ReconciliationRequired('Wrong tool session')
                self.control_safe_point()
                state = self.state()
                if session_id != state['session_id'] or not tool_call_id or self.owned.checkpoint.operation:
                    raise ReconciliationRequired('Wrong tool identity or unfinished operation')
                if not isinstance(args, dict) or not isinstance(args.get('path'), str):
                    raise ReconciliationRequired('Malformed file arguments')
                path = (self.work / args['path']).resolve()
                read_ok = tool_name == 'read_file' and path in (self.work / 'orders.csv', self.work / 'report.json')
                write_ok = (tool_name == 'write_file' and path == self.work / 'report.json'
                            and isinstance(args.get('content'), str) and len(args['content']) <= 4096)
                if not (read_ok or write_ok):
                    raise ReconciliationRequired('Tool is outside this adapter capability')
                history = native_history(self.db, session_id)
                assert_prefix(state['native_history'], history)
                calls = [call for row in history for call in row.get('tool_calls', [])
                         if call.get('id') == tool_call_id]
                if (len(calls) != 1 or calls[0]['function']['name'] != tool_name
                        or json.loads(calls[0]['function']['arguments']) != args):
                    raise ReconciliationRequired('Exact tool intent must already be native-durable')
                key = digest({'name': tool_name, 'path': path.name, 'args': {k:v for k,v in args.items() if k != 'path'}})
                previous = [row for row in state['tools'] if row['name'] == 'write_file' and row['fingerprint'] == key]
                if write_ok and previous:
                    receipt = previous[-1]
                    if not path.is_file() or digest(path.read_bytes()) != receipt['artifact_sha256']:
                        raise ReconciliationRequired('Completed write artifact changed')
                    reused = {**receipt, 'tool_call_id': tool_call_id, 'reused': True}
                    state['tools'].append(reused)
                    state['phase'] = 'awaiting_native_flush'
                    self.checkpoint(state)
                    return receipt['result']
                if write_ok and path.exists():
                    raise ReconciliationRequired('Unreceipted destination exists; no overwrite/replay')
                if write_ok and self.pre_effect_validator is not None:
                    candidate=copy.deepcopy(args)
                    original_fingerprint=digest(candidate)
                    verdict=self.pre_effect_validator(tool_name,candidate)
                    if (digest(candidate)!=original_fingerprint or type(verdict) is not Verdict
                            or type(verdict.accepted) is not bool or type(verdict.feedback) is not str
                            or len(verdict.feedback)>2048 or not verdict.accepted and not verdict.feedback):
                        raise ReconciliationRequired('Invalid or mutating pre-effect validator')
                    if not verdict.accepted:
                        # The genuine SDK will append this returned tool result.
                        # Until that flush is observed, restart stays fail-closed.
                        result=json.dumps({'error':'proposal_validation_failed','dispatched':False,
                            'feedback':verdict.feedback},ensure_ascii=False)
                        state.update(phase='validating',native_history=history)
                        details={'name':tool_name,'tool_call_id':tool_call_id,'args':copy.deepcopy(args),
                            'fingerprint':key,'session_id':session_id,
                            'validator_identity':copy.deepcopy(self.validator_identity)}
                        cp=self.owned.begin_operation('validation',details=details,state=state,
                            expected_revision=self.owned.checkpoint.revision)
                        receipt={**details,'operation_id':cp.operation['id'],'result':result,'dispatched':False}
                        state.setdefault('validation_rejections',[]).append(receipt)
                        state['feedback'].append(verdict.feedback)
                        state['phase']='awaiting_native_flush'
                        self.owned.complete_operation(cp.operation['id'],result=receipt,state=state,
                            expected_revision=self.owned.checkpoint.revision)
                        return result
                state.update(phase='tool_running', native_history=history)
                details = {'name': tool_name, 'tool_call_id': tool_call_id, 'args': args,
                           'fingerprint': key, 'session_id': session_id}
                cp = self.owned.begin_operation('effect' if write_ok else 'validation', details=details,
                    state=state, expected_revision=self.owned.checkpoint.revision)
                result = next_call(args)
                parsed = json.loads(result) if isinstance(result, str) else result
                if not isinstance(result, str) or not isinstance(parsed, dict) or parsed.get('error'):
                    raise ReconciliationRequired('Tool outcome was not a successful serialized native result')
                receipt = {**details, 'result': result, 'operation_id': cp.operation['id'], 'reused': False}
                if write_ok:
                    if parsed.get('verified') is not True or not path.is_file():
                        raise ReconciliationRequired('Native write was not verified')
                    receipt['artifact_sha256'] = digest(path.read_bytes())
                    with (self.run / 'effect-receipts.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                        stream.write(json.dumps(receipt, ensure_ascii=False) + '\n')
                        stream.flush(); os.fsync(stream.fileno())
                    self.barrier('uncertain_after_write')
                state['tools'].append(receipt)
                state['phase'] = 'awaiting_native_flush'
                self.owned.complete_operation(cp.operation['id'], result=receipt, state=state,
                    expected_revision=self.owned.checkpoint.revision)
                return result
            except RecoveryStop:
                raise
            except Exception as exc:
                return self._deny(type(exc).__name__)

    def finish(self, outcome=None):
        with self.lock:
            return self._finish_owned(outcome)

    def _finish_owned(self, outcome):
        if outcome is None and self.controls is not None:
            outcome = self.state().get('completion_candidate')
            if (type(outcome) is not dict
                    or set(outcome) != {'completed','failed','interrupted','final_response'}
                    or outcome['completed'] is not True or outcome['failed'] is not False
                    or outcome['interrupted'] is not False or type(outcome['final_response']) is not str):
                raise ReconciliationRequired('Persisted completion candidate schema is invalid')
        if type(outcome) is not dict:
            raise ReconciliationRequired('No verified completion candidate is available')
        if self.fatal or not outcome.get('completed') or outcome.get('failed') or outcome.get('interrupted'):
            raise ReconciliationRequired('Native task did not complete successfully')
        state = self.state()
        if self.owned.checkpoint.operation:
            raise ReconciliationRequired('Operation still pending at completion')
        history = native_history(self.db, state['session_id'])
        assert_prefix(state['native_history'], history)
        verify_tool_rows(history, state['tools'])
        verify_validation_rows(history,state,self.validator_identity)
        if self.controls is not None:
            verify_artifacts(state, self.work)
            if state['phase'] not in ('ready','waiting_admission','awaiting_native_flush'):
                raise ReconciliationRequired('Completion has an unknown application phase')
            if state['phase'] == 'awaiting_native_flush' and len(history) <= len(state['native_history']):
                raise ReconciliationRequired('Completion outcome is not native-durable')
            candidate = {'completed': True, 'failed': False, 'interrupted': False,
                         'final_response': str(outcome.get('final_response', ''))}
            state.update(phase='ready', native_history=history, completion_candidate=candidate)
            self.checkpoint(state)
            self.control_safe_point()
            state = self.state()
        state.update(status='accepted', phase='accepted', native_history=history,
                     output=str(outcome.get('final_response', '')))
        self.checkpoint(state)


def reconcile_write(owned, db, work, receipt, *, expected_operation_id):
    """Explicit host call; never automatic. An observed, exact verified receipt is required.

    Native append occurs before TaskStore reconciliation. If the process dies
    between these commits, the next explicit call recognizes the exact row.
    """
    cp = owned.checkpoint
    op = cp.operation
    if (not cp.requires_reconciliation or not op or op['id'] != expected_operation_id
            or op['kind'] != 'effect' or receipt.get('operation_id') != expected_operation_id):
        raise ReconciliationRequired('Expected interrupted write operation does not match')
    detail = op['details']
    for key in ('name', 'tool_call_id', 'args', 'fingerprint', 'session_id'):
        if receipt.get(key) != detail.get(key):
            raise ReconciliationRequired('Receipt differs from recorded intent')
    path = (Path(work).resolve() / detail['args']['path']).resolve()
    if (detail['name'] != 'write_file' or path != Path(work).resolve() / 'report.json'
            or not path.is_file() or digest(path.read_bytes()) != receipt.get('artifact_sha256')
            or path.read_text(encoding='utf-8') != detail['args']['content']):
        raise ReconciliationRequired('Current artifact does not prove this exact recorded write')
    parsed = json.loads(receipt['result'])
    if parsed.get('verified') is not True or parsed.get('error'):
        raise ReconciliationRequired('Receipt is not a successful verified native write')
    session_id = cp.state['session_id']
    holder = f'pid={os.getpid()}:adaptive-reconcile={op["id"]}'
    if not db.acquire_session_turn_lease(session_id, holder, wait_seconds=0):
        raise ReconciliationRequired('Native session is still owned')
    try:
        history = native_history(db, session_id)
        assert_prefix(cp.state['native_history'], history)
        rows = [row for row in history if row.get('role') == 'tool' and row.get('tool_call_id') == detail['tool_call_id']]
        if rows and (len(rows) != 1 or rows[0].get('content') != receipt['result']):
            raise ReconciliationRequired('Conflicting native tool result exists')
        if not rows:
            db.append_message(session_id, 'tool', content=receipt['result'], tool_name='write_file',
                              tool_call_id=detail['tool_call_id'], turn_lease_holder=holder)
        state = copy.deepcopy(cp.state)
        state['tools'].append(receipt)
        state.update(phase='ready', native_history=native_history(db, session_id))
        verify_tool_rows(state['native_history'], state['tools'])
        verify_validation_rows(state['native_history'],state,cp.metadata.get('pre_effect_validator'))
        return owned.reconcile_operation(expected_operation_id, resolution='completed', result=receipt,
                    state=state, expected_revision=cp.revision)
    finally:
        db.release_session_turn_lease(session_id, holder)


ACTIVE = None


def register(ctx):
    if ACTIVE is None:
        raise RuntimeError('Recovery requires an explicitly owned host task')
    ctx.register_middleware('llm_execution', ACTIVE.llm)
    ctx.register_middleware('tool_execution', ACTIVE.tool)
