# SPDX-License-Identifier: Apache-2.0
"""Explicit same-host continuation, retaining existing storage/worker lifecycles.

No new executor or task database. The composition owns every actual child, while
the runtime owns bounded retained operations and the stable logical UI identity.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from adaptive_inference.control_mailbox import Mailbox, execution_outcome
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
from adaptive_inference.desktop.control_transport import Refused
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, require, AUTHORITY, LINK
from adaptive_inference.desktop.hermes.continuation_worker import scope_for, read_json
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding, PAUSED_EXPIRY_EXIT
from adaptive_inference.execution_clock import CLOCK_ID, execution_now


def selection(grant):
    return {'execution_id': grant['payload']['successor_id'],
            'execution_generation': grant['execution_generation']}


class SelectedWorkerStopBinding(WorkerStopBinding):
    """Reuse all native/checkpoint exit validation, then verify logical lifetime."""
    def __init__(self, *args, grant, authority, **kwargs):
        self.grant, self.authority = deepcopy(grant), authority
        run = Path(args[1]).resolve(strict=True)
        diagnostics = (run/'executions'/grant['payload']['successor_id']).resolve(strict=True)
        require(diagnostics.parent == run/'executions', 'Selected result directory differs')
        super().__init__(*args, diagnostics=diagnostics, **kwargs)
        require(self.original.task_id == grant['payload']['successor_id']
                and self.deadline == grant['deadline_monotonic'], 'Selected Stop binding differs from grant')

    def _admission_wait_identity(self, cp):
        require(type(self) is SelectedWorkerStopBinding, 'Exact selected expiry binding required')
        self._original(cp)
        grant = self.grant
        require(cp.task_id == grant['payload']['successor_id']
                and self.deadline == grant['deadline_monotonic']
                and cp.metadata.get(LINK) == {
                    'logical_task_id': self.authority.logical_task_id, 'execution_id': cp.task_id,
                    'execution_generation': grant['execution_generation'],
                    'command_id': grant['payload']['command_id'], 'payload_sha256': grant['payload_sha256']},
                'Admission expiry is not the current selected execution')

    def _verify_exit(self, code):
        # The base verifier retains all legacy Stop/expiry/native artifact rules.
        outcome = super()._verify_exit(code)
        cp = self.mailbox.snapshot().target
        grant = self.grant
        require(self.authority.lookup(grant['payload']) == grant, 'Selected authorization changed')
        authority = self.authority.store.load(self.authority.task_id)
        require(authority.owner_epoch is None and authority.operation is None
                and not authority.requires_reconciliation, 'Selected worker authority is not released')
        current = self.authority._authority(authority)
        require(current['selected_execution'] == cp.task_id
                and current['execution_generation'] == grant['execution_generation'],
                'Exited worker is not the current selected execution')
        path = self.diagnostics/f'result-{self.worker.pid}.json'
        result = read_json(path)
        require(result.get('selected_execution') == {**selection(grant), 'logical_task_id': self.authority.logical_task_id}
                and result.get('continuation_cleanup_verified') is True
                and not result.get('cleanup_errors'), 'Selected result identity/cleanup differs')
        expected = {'schema': 'adaptive.selected-worker-lifetime.v1',
                    **selection(grant), 'payload_sha256': grant['payload_sha256']}
        history = self.authority.store.history(self.authority.task_id)
        starts = [row for row in history if row['event'] == 'operation_started'
                  and row['payload']['operation'].get('details') == expected]
        require(bool(starts), 'Selected worker lifetime start missing')
        operation = starts[-1]['payload']['operation']
        ends = [row for row in history if row['event'] == 'operation_completed'
                and row['payload']['event_data']['operation'] == operation]
        require(len(ends) == 1 and ends[0]['revision'] > starts[-1]['revision'],
                'Selected worker lifetime completion missing')
        proof = ends[0]['payload']['event_data']['result']
        require(operation['kind'] == 'effect' and proof.get('execution_id') == cp.task_id
                and type(proof.get('returncode')) is int and proof['returncode'] == code
                and proof.get('result_sha256') == rec.digest(path.read_bytes())
                and proof.get('physical_child_exit_proven') is False
                and proof.get('cleanup', {}).get('resources_closed') is True
                and proof['cleanup'].get('state_sha256') == rec.digest(cp.state)
                and proof['cleanup'].get('native_history_sha256') == rec.digest(cp.state['native_history']),
                'Selected lifetime completion does not bind this exact result')
        return outcome


class HostContinuation:
    """One composition's bounded explicit continuation records, never auto-retry."""
    def __init__(self, composition, runtime, *, clock=execution_now):
        self.composition, self.runtime, self.clock = composition, runtime, clock
        self.records = {}
        self.current = None
        runtime.configure_continuation(self)

    def live(self, intent_valid):
        return not self.runtime._stopping and not self.runtime._faults and intent_valid() is True

    def reply(self, record, *, phase=None):
        grant, request = record['grant'], record['request']
        return {'request_id': request['request_id'],
                'predecessor_execution_id': request['execution_id'],
                'predecessor_generation': request['execution_generation'],
                **selection(grant), 'phase': record['phase'] if phase is None else phase}

    def phase(self, record, phase):
        record['phase'] = phase
        self.runtime._continuation_phase = phase
        self.runtime._continuation_request = record['request']['request_id']

    def remember_grant(self, record, grant):
        """Retain a committed obligation; this performs no rebind or launch."""
        require(record['grant'] is None or record['grant'] == grant, 'Historical selection changed')
        first_observation = not record['committed']
        record['grant'],record['committed'],record['authorization_resolved'] = grant,True,True
        if first_observation:
            self.current = record
            self.composition.facade.select_execution(record,self)

    async def drain(self):
        while self.runtime._pending:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.runtime._pending)))
            await asyncio.sleep(0)

    async def lookup(self, request):
        record = self.records.get(request['request_id'])
        if record is None:
            return None
        if record['request'] != request:
            raise Refused('conflicting_request_id')
        if record['payload'] is None:
            return None
        grant = await asyncio.to_thread(record['authority'].lookup, record['payload'])
        if grant is None:
            record['authorization_resolved'] = True
            return None
        require(record['grant'] is None or record['grant'] == grant, 'Historical selection changed')
        # Lookup cannot perform rebind, launch, readiness or Resume. Keep unknown
        # transitions blocked even when storage proves their grant committed.
        self.remember_grant(record,grant)
        return self.reply(record, phase='selected' if record['phase'] == 'selected' else 'blocked')

    async def select(self, request, *, intent_valid):
        runtime, composition = self.runtime, self.composition
        if request['request_id'] in self.records:
            return await self.lookup(request)
        runtime._require_execution({key: request[key] for key in ('execution_id','execution_generation')})
        if (runtime._transitioning or not self.live(intent_valid) or len(self.records) >= 32):
            raise Refused('continuation_unavailable')
        record = {'request': deepcopy(request), 'payload': None, 'grant': None, 'authority': None,
                  'phase': 'selected', 'launch_attempted': False, 'child': None, 'binding': None,
                  'capability': None, 'committed': False, 'started': False, 'release': None,
                  'authorization_resolved': True}
        self.records[request['request_id']] = record
        runtime._transitioning = True
        runtime.deactivate_intent()
        composition.host._control_rebinding = True
        try:
            await self.drain()
            if not self.live(intent_valid): raise Refused('continuation_blocked')
            record['release'] = await composition.continuation_release(request, intent_valid)
            if not self.live(intent_valid): raise Refused('continuation_blocked')
            controller = composition.host.controller
            async with controller.lock:
                async with controller._demand_lock:
                    composition.assert_continuation_parked(record['release'])
                    if not self.live(intent_valid): raise Refused('continuation_blocked')
                    def authorize():
                        plan_raw = (composition.work/'plan.json').read_bytes()
                        plan = read_json(composition.work/'plan.json')
                        authority = ContinuationAuthority(composition.store, runtime.prepared.task_id,
                            scope_for(composition.work,plan,plan_raw), host_generation=runtime.prepared.host_epoch,
                            clock=self.clock)
                        record['authority'] = authority
                        old = composition.store.load(request['execution_id'])
                        marker = execution_outcome(old.state)
                        require(marker is not None and old.revision == request['expected_task_revision'],
                                'Continue expected predecessor revision changed')
                        suffix = rec.digest({'host': runtime.prepared.host_epoch, 'command': request['request_id']})[:24]
                        successor = 'execution-'+suffix
                        identity = DemandIdentity('continue-'+suffix,successor,composition.identity.owner_id,
                            datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
                        payload = authority.request(command_id=request['request_id'],predecessor_id=old.task_id,
                            predecessor_revision=old.revision,predecessor_seal_sha256=rec.digest(marker),
                            successor_id=successor,identity=identity,host_generation=runtime.prepared.host_epoch,
                            release_evidence_sha256=rec.digest(record['release']))
                        record['payload'],record['identity'] = payload,identity
                        record['authorization_resolved'] = False
                        cp = composition.store.load(authority.task_id)
                        with composition.store.claim(cp.task_id,expected_revision=cp.revision) as owned:
                            return authority.authorize(owned,payload)
                    grant = await asyncio.to_thread(authorize)
                    # No await/fallible staging may precede this obligation.
                    self.remember_grant(record,grant)
                    def stage():
                        registry = DemandRegistry((Registration(composition.store,record['identity']),))
                        capability = object()
                        mailbox = Mailbox(registry,record['identity'].registration_id,requester_capability=capability)
                        return registry,mailbox,capability,runtime._observe(mailbox)
                    staged = await asyncio.to_thread(stage)
                    # Stop may have latched while the committed write/staging
                    # completed. Publish storage truth, but never launch for it.
                    composition.host.commit_selected_runtime(runtime,record,staged,self)
                    self.phase(record,'selected')
            return self.reply(record,phase='selected')
        except BaseException:
            if record['payload'] is not None and not record['authorization_resolved']:
                # The SQLite commit may have succeeded before a return/release
                # failure. Resolve only the exact materialized command, retaining
                # the original failure and never launching from recovery lookup.
                try:
                    saved = await asyncio.to_thread(record['authority'].lookup,record['payload'])
                    if saved is not None:self.remember_grant(record,saved)
                    else:record['authorization_resolved'] = True
                except Exception:
                    pass  # Explicit unresolved obligation fences clean Stop.
            if record['grant'] is not None:
                self.phase(record,'blocked')
            raise
        finally:
            composition.host._control_rebinding = False
            if record['grant'] is None:
                runtime._transitioning = False

    async def continue_selected(self, reply, *, intent_valid):
        record = self.records.get(reply['request_id'])
        require(record is not None and self.reply(record,phase='selected') == reply,
                'Long transition requires its exact selected grant')
        if record['started']:
            return self.reply(record)
        record['started'] = True
        try:
            if not self.live(intent_valid):
                self.phase(record,'blocked');return self.reply(record)
            self.phase(record,'preparing')
            await self.composition.launch_continuation(record,self,intent_valid)
            if not self.live(intent_valid):
                self.phase(record,'blocked');return self.reply(record)
            self.phase(record,'ready')
            selected = selection(record['grant'])
            await self.runtime.submit_control(record['resume_id'],'resume',execution=selected,_transition=True)
            if not self.live(intent_valid):
                self.phase(record,'blocked');return self.reply(record)
            if not await self.runtime.resume_authority(record['resume_id'],execution=selected):
                raise RuntimeError('Derived Resume has no current durable authority')
            if not self.live(intent_valid):
                self.phase(record,'blocked');return self.reply(record)
            self.runtime.activate_intent(record['request']['session_id'],execution=selected)
            await self.composition.wait_continuation_ack(record,record['resume_id'],intent_valid)
            if not self.live(intent_valid):
                self.phase(record,'blocked');return self.reply(record)
            self.phase(record,'running')
            await self.composition.ready_continuation(record,intent_valid)
            if not self.live(intent_valid):self.phase(record,'blocked')
            return self.reply(record)
        except BaseException:
            self.phase(record,'blocked');self.runtime.deactivate_intent()
            raise
        finally:
            self.runtime._transitioning = False

    def verify_unlaunched(self, record):
        require(record is self.current and record['committed'] and record['launch_attempted'] is False
                and record['child'] is None and record['binding'] is None, 'Selected launch state is not known unstarted')
        grant,authority = record['grant'],record['authority']
        require(authority.lookup(record['payload']) == grant, 'Unlaunched grant changed')
        cp = authority.store.load(grant['payload']['successor_id'])
        current = authority.store.load(authority.task_id)
        require(cp.owner_epoch is None and cp.operation is None and not cp.requires_reconciliation
                and rec.digest(cp.state) == grant['successor_initial_state_sha256']
                and current.owner_epoch is None and current.operation is None and not current.requires_reconciliation,
                'Unlaunched selection acquired work or has unknown authority')
        require(not any(row['event']=='operation_started' and
                        row['payload']['operation'].get('details',{}).get('payload_sha256')==grant['payload_sha256']
                        for row in authority.store.history(authority.task_id)), 'Unlaunched authority acquired a worker lifetime')
        old = record['release']
        require(old['worker_joined'] is True
                and old['outcome'] in ('paused_budget_expired', 'admission_wait_budget_expired'),
                'Unlaunched selection lacks retained predecessor release')
        return {'worker_joined':True,'safe_checkpoint':True,'outcome':'selected_not_launched',
                'exit_code':None,'uncertain':False,'fault':None}
