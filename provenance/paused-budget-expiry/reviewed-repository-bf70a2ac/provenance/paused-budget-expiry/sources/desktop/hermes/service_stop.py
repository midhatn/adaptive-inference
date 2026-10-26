# SPDX-License-Identifier: Apache-2.0
"""Cooperative service Stop through an existing durable Pause and retained child.

No process discovery/signalling, native cleanup or new control database. The
trusted host owns launch, immediate admission fencing and eventual GUI/native
cleanup. Only known fully flushed checkpoints earn a safe-worker receipt.
"""
import asyncio
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import threading

from adaptive_inference.control_mailbox import Mailbox, ACKS
from adaptive_inference.demand import _label, _record
from adaptive_inference.task_store import TerminalTaskError
from adaptive_inference.desktop.hermes.recovery import ControlStop, RecoveryStop, digest, resumable, verify_artifacts, verify_tool_rows

STOP_EXIT = 4
SCHEMA = 'adaptive.cooperative-worker-stop.v1'


def flushed_tools(state):
    """Conservative known checkpoint: no unresolved native tool-call continuation."""
    verify_tool_rows(state['native_history'], state['tools'])
    calls = [call.get('id') for row in state['native_history']
             for call in row.get('tool_calls', [])]
    if any(type(call) is not str or not call for call in calls) or len(set(calls)) != len(calls):
        raise RecoveryStop('Native tool intent is not a known bounded checkpoint')
    results = [row.get('tool_call_id') for row in state['native_history'] if row.get('role') == 'tool']
    if any(results.count(call) != 1 for call in calls):
        raise RecoveryStop('Pending native tool continuation cannot confirm product Stop')


class ProductStop(ControlStop):
    def __init__(self, receipt):
        self.receipt = deepcopy(receipt)
        super().__init__('stopped', 'cooperative_service_stop_acknowledged')


class StopAtPause:
    """Invoked only by the actual worker's existing owner-safe control loop."""
    def __init__(self, recovery, stop_request_id):
        self.recovery = recovery
        self.request_id = _label(stop_request_id, 'stop_request_id')

    def __call__(self, owned, boundary):
        if owned is not self.recovery.owned:
            raise RecoveryStop('Product Stop belongs to this exact task owner')
        mailbox = self.recovery.controls.mailbox
        receipts = owned.checkpoint.state.get(ACKS, {}).get('receipts', [])
        match = next((row for row in receipts if row['request_id'] == self.request_id), None)
        if match is None:
            return
        record = _record(owned.checkpoint, mailbox.identity)
        if (match['command'] == 'pause' and match['outcome'] == 'rejected'
                and record is not None and record['state'] == 'cancelled'):
            # Existing durable cancellation wins; let Controls raise its normal
            # distinct cancellation exit rather than fabricating a Pause ACK.
            return
        if (match['command'] != 'pause' or match['outcome'] != 'applied'
                or record is None or record['state'] != 'paused'
                or owned.checkpoint.state['status'] != 'pending'
                or boundary.get('reason') != 'demand_paused'):
            raise RecoveryStop('Product Stop lacks its exact safe Pause acknowledgement')
        resumable(owned, self.recovery.db, self.recovery.work)
        state = owned.checkpoint.state
        flushed_tools(state)
        raise ProductStop({'schema': SCHEMA, 'request_id': self.request_id,
            'task_id': mailbox.identity.task_id, 'registration_id': mailbox.identity.registration_id,
            'pid': os.getpid(), 'owner_epoch': owned.checkpoint.owner_epoch,
            'revision': owned.checkpoint.revision, 'state_sha256': digest(state),
            'native_history_sha256': digest(state['native_history']), 'phase': state['phase'],
            'task_completed': False})


class WorkerStopBinding:
    """Trusted owner-loop lifecycle for one already-retained worker.

    join() timeout or cancellation never cancels the retained operation. This
    component never calls host.close: the facade must join both worker and GUI
    before the existing host checks its containing job and releases native work.
    """
    def __init__(self, worker, run, mailbox, *, requester_capability, capability,
                 stop_request_id, original, deadline_monotonic, model, quality, fence):
        if (type(mailbox) is not Mailbox or type(requester_capability) is not object
                or requester_capability is not mailbox._capability or type(capability) is not object
                or original.task_id != mailbox.identity.task_id or not callable(fence)):
            raise TypeError('Exact trusted mailbox, task and private host capabilities required')
        if (type(worker.pid) is not int or worker.pid <= 0
                or not callable(worker.poll) or not callable(worker.wait)):
            raise TypeError('Actual retained launch object required; no PID lookup')
        if (type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic) or deadline_monotonic <= 0):
            raise ValueError('Original finite task deadline required')
        self.worker, self.run, self.mailbox = worker, Path(run).resolve(strict=True), mailbox
        self.request_id = _label(stop_request_id, 'stop_request_id')
        self._requester, self._capability, self.fence = requester_capability, capability, fence
        self.original, self.deadline = original, deadline_monotonic
        self.model, self.quality = model, deepcopy(quality)
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self._work = None
        self._fault = None
        self._joined = False
        self._exit_code = None

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise RuntimeError('Worker Stop belongs to its host loop/thread')

    def request_stop(self, capability):
        self._owner()
        if capability is not self._capability:
            raise PermissionError('Trusted host Stop capability required')
        if self._work is None:
            try:
                self.fence()
            except Exception:
                self._fault = 'admission_fence_failed'
            self._work = self._loop.create_task(self._finish())
        return {'state': 'stop_requested', 'worker_joined': self._joined}

    def _request(self):
        snapshot = self.mailbox.snapshot()
        self._original(snapshot.target, allow_unstarted=True)
        if self.worker.poll() is None and snapshot.target.state['status'] == 'pending':
            if any(row['request_id'] == self.request_id for row in snapshot.requests):
                raise RecoveryStop('Stop request ID was already recorded before this binding submitted it')
            try:
                self.mailbox.submit(self._requester, self.request_id, 'pause')
            except TerminalTaskError:
                # A genuine completed target can win the race with Stop. Do not
                # turn that known terminal result into a fabricated Stop ACK.
                if self.mailbox.snapshot().target.state['status'] == 'pending':
                    raise

    def _original(self, cp, *, allow_unstarted=False):
        # The launcher supplies this deadline once. Stop can precede the worker's
        # first claim; only the unchanged initial state may lack its saved copy.
        deadline_ok = cp.state.get('deadline_monotonic') == self.deadline
        if (allow_unstarted and cp.state.get('deadline_monotonic') is None
                and cp.state == self.original.state and cp.operation is None
                and not cp.requires_reconciliation):
            deadline_ok = True
        if (cp.task_id != self.original.task_id or cp.prompt != self.original.prompt
                or cp.metadata != self.original.metadata or cp.max_attempts != self.original.max_attempts
                or cp.state['messages'][0] != self.original.state['messages'][0]
                or not deadline_ok):
            raise RecoveryStop('Original task identity/accounting binding changed')

    def _verify_exit(self, code):
        snapshot = self.mailbox.snapshot()
        cp = snapshot.target
        self._original(cp)
        if type(code) is not int or cp.owner_epoch is not None or cp.operation is not None or cp.requires_reconciliation:
            raise RecoveryStop('Exited worker did not leave a released safe checkpoint')
        if cp.state['phase'] not in ('ready', 'waiting_admission', 'accepted'):
            raise RecoveryStop('Worker application checkpoint is not resumable')
        flushed_tools(cp.state)
        verify_artifacts(cp.state, self.run/'work')
        path = self.run/f'result-{self.worker.pid}.json'
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024:
            raise RecoveryStop('Worker result exceeds its bounded receipt')
        result = json.loads(raw)
        if result.get('model') != self.model or result.get('quality') != self.quality:
            raise RecoveryStop('Worker quality/source-bound result differs')
        if code == 0:
            if (result.get('passed') is not True or cp.state['status'] != 'accepted'
                    or cp.state['phase'] != 'accepted'):
                raise RecoveryStop('Ordinary worker exit is not a verified completed task')
            return 'task_completed'
        if code == 3:
            if (result.get('controlled') is not True or result.get('passed') is not False
                    or cp.state['status'] != 'pending' or result.get('control_state') != 'cancelled'
                    or snapshot.demand is None or snapshot.demand['state'] != 'cancelled'):
                raise RecoveryStop('Cancellation exit lacks durable cancelled demand')
            return 'task_cancelled'
        if code != STOP_EXIT:
            raise RecoveryStop('Worker exited without a known cooperative outcome')
        proof = result.get('service_stop')
        keys = {'schema','request_id','task_id','registration_id','pid','owner_epoch','revision',
                'state_sha256','native_history_sha256','phase','task_completed'}
        ack = snapshot.status(self.request_id)
        if (type(proof) is not dict or set(proof) != keys or proof['schema'] != SCHEMA
                or proof['request_id'] != self.request_id or proof['task_id'] != cp.task_id
                or proof['registration_id'] != self.mailbox.identity.registration_id
                or type(proof['pid']) is not int or proof['pid'] != self.worker.pid
                or type(proof['revision']) is not int or cp.revision != proof['revision']
                or type(proof['owner_epoch']) is not str or len(proof['owner_epoch']) != 32
                or any(c not in '0123456789abcdef' for c in proof['owner_epoch'])
                or result.get('owner_epoch') != proof['owner_epoch']
                or proof['state_sha256'] != digest(cp.state)
                or proof['native_history_sha256'] != digest(cp.state['native_history'])
                or proof['phase'] != cp.state['phase'] or proof['task_completed'] is not False
                or result.get('passed') is not False or result.get('controlled') is not True
                or result.get('control_state') != 'stopped'
                or cp.state['status'] != 'pending' or snapshot.demand is None
                or snapshot.demand['state'] != 'paused' or ack['outcome'] != 'applied'
                or ack['owner_acknowledged'] is not True
                or not snapshot.requests or snapshot.requests[-1]['request_id'] != self.request_id):
            raise RecoveryStop('Cooperative exit receipt differs from durable safe checkpoint')
        return 'service_stopped'

    def _result(self, *, safe=False, outcome=None):
        return {'worker_joined': self._joined, 'safe_checkpoint': safe,
                'outcome': outcome, 'exit_code': self._exit_code,
                'uncertain': not safe or self._fault is not None, 'fault': self._fault}

    async def _finish(self):
        try:
            await asyncio.to_thread(self._request)
        except (Exception, RecoveryStop):
            self._fault = self._fault or 'stop_request_unconfirmed'
        try:
            self._exit_code = await asyncio.to_thread(self.worker.wait)
            self._joined = True
            outcome = await asyncio.to_thread(self._verify_exit, self._exit_code)
            return self._result(safe=True, outcome=outcome)
        except (Exception, RecoveryStop):
            self._fault = self._fault or 'worker_checkpoint_unverified'
            return self._result()

    async def join(self, *, timeout=2):
        self._owner()
        if type(timeout) not in (int,float) or not 0 < timeout <= 600:
            raise ValueError('Bounded caller wait required')
        if self._work is None:
            raise RuntimeError('Stop must be explicitly requested first')
        try:
            return deepcopy(await asyncio.wait_for(asyncio.shield(self._work), timeout))
        except asyncio.TimeoutError:
            if self._work.done():
                return deepcopy(self._work.result())
            return self._result()
