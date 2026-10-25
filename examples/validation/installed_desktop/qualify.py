# SPDX-License-Identifier: Apache-2.0
"""Accepted cold/full scenarios against the ordinary installed desktop package.

No resources are acquired on import. Run with the explicitly selected full
Python interpreter. The separately retained parent must also verify exit zero.
"""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

from adaptive_inference.desktop import composition as installed
from adaptive_inference.desktop.composition import (DesktopComposition, INITIAL_PAUSE, TITLE,
    read, sha, diagnostic, no_work, join_retained, complete_ledger, hard_deadline)
from adaptive_inference.desktop.installation import package_identity
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.run_recovery import MODEL, QUALITY, PROMPT
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding, STOP_EXIT
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore
from adaptive_inference.control_mailbox import Mailbox

HERE = Path(__file__).resolve().parent
REPORT = {'rows':4,'units':17,'total_cents':4350,
          'by_item':{'folder':1100,'notebook':2250,'pen':1000}}
CONTEXT = {'context_length':65536,'threshold':.8,'threshold_tokens':46421,
           'reserved_output':10923,'max_tokens':10923}
REPORT_PAUSE = 'pause-after-safe'


def verify_closure():
    manifest = read(HERE/'source-manifest.json')
    for relative, row in manifest['files'].items():
        path = (HERE/relative).resolve(strict=True)
        if not path.is_relative_to(HERE) or sha(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise RuntimeError('Qualification source changed: '+relative)
    return {'manifest_sha256':sha(HERE/'source-manifest.json'), 'files':len(manifest['files']),
            'installed_package':package_identity()}


def gui_controls(transport,box,stop_id):
    """Only authenticated transport records establish GUI-origin command IDs."""
    snapshot=box.snapshot();observed=[]
    if any(row['command']!='pause' for row in snapshot.requests):
        raise RuntimeError('Cold trial permits no Resume or Cancel')
    for request_id,record in transport._records.items():
        if request_id in (INITIAL_PAUSE,stop_id) or record['command']!='pause':
            raise RuntimeError('GUI command does not belong to this cold Pause trial')
        if record['outcome']=='unknown':raise RuntimeError('GUI command outcome is unknown')
        if record['task'].done() and record['outcome']=='known':
            record['task'].result()
            value=snapshot.status(request_id)
            if value['outcome']=='applied' and value['owner_acknowledged'] is True:
                observed.append({key:value[key] for key in ('request_id','command','sequence','outcome','owner_acknowledged')})
    return observed


class ValidationChecks:
    def activate_verified_runtime(self,identity):
        gateway,controller=self.host.gateway,self.host.controller
        if (gateway.scheduler.capacity is not controller or gateway.capacity is not controller
                or controller.identity!=identity or gateway._runtime_loop is not asyncio.get_running_loop()
                or controller() or gateway.scheduler.active is not None or gateway.scheduler.uncertain
                or gateway.scheduler.closing or len(self.runtime_bindings)>=255):
            raise RuntimeError('Verified runtime binding context refused')
        previous=gateway._runtime_context
        gateway.activate_runtime(identity)
        current=gateway._runtime_context
        self.runtime_bindings.append({'at_monotonic':time.monotonic(),'owner_id':identity['owner_id'],
            'generation':current.generation,'previous_generation':previous.generation if previous else None,
            'gateway_startup_completed':True,'admission_closed':True,'controller_identity_verified':True})

    def verify_runtime_bindings(self):
        gateway,controller=self.host.gateway,self.host.controller
        if (gateway.runtime_timing is not True or gateway.scheduler.capacity is not controller
                or gateway.capacity is not controller or gateway._runtime_error is not None):
            raise RuntimeError('Runtime timing integration unavailable')
        starts=sum(row.get('restore_requested') is True for row in controller.events)
        if len(self.runtime_bindings)!=starts:
            raise RuntimeError('Runtime generations do not cover exact successful owner transitions')
        generation=0;last_owner=None
        for row in self.runtime_bindings:
            expected=generation if row['owner_id']==last_owner else generation+1
            if (row['generation']!=expected or row['previous_generation']!=(generation or None)
                    or not all(row[key] is True for key in
                        ('gateway_startup_completed','admission_closed','controller_identity_verified'))):
                raise RuntimeError('Runtime generation identity sequence refused')
            generation,last_owner=expected,row['owner_id']
        context=gateway._runtime_context
        if (context is None)!=(generation==0) or context is not None and context.generation!=generation:
            raise RuntimeError('Final runtime generation differs from verified owner ledger')
        if self.args.case=='cancel' and generation:
            raise RuntimeError('Cancelled bootstrap unexpectedly activated runtime')
        if self.result.get('task_case_checks_passed') and self.args.case=='complete' and not generation:
            raise RuntimeError('Completed case lacks verified runtime activation')
        history=deepcopy(list(gateway.history))
        if len(history)>=gateway.history.maxlen:
            raise RuntimeError('Runtime request history full; completeness not established')
        for row in history:
            actual,predicted=row['execution_runtime_generation'],row['prediction_runtime_generation']
            if (type(actual) is not int or not 1<=actual<=generation
                    or predicted is not None and (type(predicted) is not int or not 1<=predicted<=actual)
                    or row['prediction_matches_execution_runtime'] is not (actual==predicted)):
                raise RuntimeError('Request runtime generation labels refused')
        if not self.args.fixture and len(history)!=self.result.get('provider_calls'):
            raise RuntimeError('Native provider calls lack complete runtime request evidence')
        return {'enabled':True,'generation':generation or None,'verified_owner_bindings':deepcopy(self.runtime_bindings),
                'request_history':history,'request_path':'fixture_provider' if self.args.fixture else 'actual_gateway',
                'cold_start_had_no_context':self.cold_timing_verified,'performance_claimed':False}

    def safe_report(self,*,pid=None):
        cp=self.checkpoint();self.assert_original(cp)
        if (cp.state['status']!='pending' or cp.state['phase']!='ready'
                or cp.operation is not None or cp.requires_reconciliation):
            raise RuntimeError('Task is not at the verified native safe boundary')
        marker=read(self.work/'pause.json')
        if (marker['boundary']!='safe_after_write' or (pid is not None and marker['pid']!=pid)
                or marker['history_sha256']!=rec.digest(cp.state['native_history'])):
            raise RuntimeError('Native safe-point receipt differs from checkpoint')
        rec.verify_tool_rows(cp.state['native_history'],cp.state['tools'])
        rec.verify_artifacts(cp.state,self.work/'work')
        if read(self.work/'work/report.json')!=REPORT:raise RuntimeError('Original report acceptance failed')
        effect_bytes=(self.work/'effect-receipts.jsonl').read_bytes()
        effects=[json.loads(row) for row in effect_bytes.splitlines() if row.strip()]
        report_hash=sha(self.work/'work/report.json')
        if len(effects)!=1 or effects[0]['name']!='write_file' or effects[0]['artifact_sha256']!=report_hash:
            raise RuntimeError('Expected exactly one independently verified dispatched write')
        wires=read(self.work/'wire-observations.json')
        if any(not row.get('finished_at') for row in wires):raise RuntimeError('Provider outcome still uncertain')
        return cp,report_hash,effect_bytes,wires


class ColdUIQualification(DesktopComposition):
    def __init__(self,args,*,qualification_hold_after_report=False):
        self.args=args
        self.args.fixture=False
        super().__init__(args.profile,args.run,
                         qualification_hold_after_report=qualification_hold_after_report)
        self.result.update(qualification_case_passed=False, case_checks_and_cleanup_passed=False,
            asyncio_teardown_completed=False, case='cold-gui-installed-worker-stop',fixture=False,
            task_completed=False,live_M2_milestone_claimed=False,provider_calls=None,
            dispatched_file_effects=None)

    async def prepare(self):
        await super().prepare()
        ready=read(self.root/'ready.private.json')
        ready.update(case=self.result['case'],gui_title=TITLE,source=self.result['source'],
                     no_resume_requested=True,
                     instructions='Use ordinary Pause, observe its acknowledgement, then Stop. Do not Resume.')
        rec.save(self.root/'ready.private.json',ready)
        self.result['real_window_bound']=True
        self.result['runtime_class_binding_verified']=True
        self.result['gui_diagnostic']={'pid':self.gui.process.pid,'title':TITLE}

    async def interact(self):
        self.gui_pause_seen=[]
        while not self.transport.lifecycle()['stop_requested']:
            self.remaining()
            no_work(self.checkpoint(),self.original,self.deadline,self.host,self.work)
            observed=gui_controls(self.transport,self.box,self.stop_id)
            if observed:self.gui_pause_seen=observed
            if self.worker.poll() is not None:raise RuntimeError('Worker exited before manual Stop')
            if self.gui.process.poll() is not None:raise RuntimeError('GUI exited without explicit manual Stop')
            status={'phase':'ready_for_manual_pause_and_stop','gui_pid':self.gui.process.pid,'gui_title':TITLE,
                'worker_pid':self.worker.pid,'gui_pause_acknowledged':bool(self.gui_pause_seen),
                'no_resume':True,'native_launch_intent':None,'provider_calls':0,
                'runtime':self.runtime.status(),'transport':self.transport.lifecycle()}
            rec.save(self.root/'status.private.json',status)
            await asyncio.sleep(.1)
        self.result['manual_stop_observed']=True
        gui_controls(self.transport,self.box,self.stop_id)
        if not self.gui_pause_seen:raise RuntimeError('Manual Stop lacks an independently observed GUI Pause ACK')
        self.result['gui_pause_observed_before_stop']=True
        self.result['gui_pause_acknowledgements']=deepcopy(self.gui_pause_seen)
        await asyncio.shield(self.transport._stop_task)
        if not self.transport.lifecycle()['stop_confirmed']:raise RuntimeError('Manual Stop is not confirmed')
        self.result['lifecycle']=await self.facade.cooperative_stop()
        if self.result['lifecycle']!={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}:
            raise RuntimeError('Cooperative Stop lacks exact verified closure')

    def validate_terminal(self):
        cp=self.checkpoint();no_work(cp,self.original,self.deadline,self.host,self.work)
        if cp.owner_epoch is not None:raise RuntimeError('Worker did not release actual task ownership')
        if self.worker.poll()!=STOP_EXIT:raise RuntimeError('Installed worker did not exit via cooperative Stop')
        if self.stop_binding._verify_exit(STOP_EXIT)!='service_stopped':
            raise RuntimeError('Final worker receipt no longer matches its durable checkpoint')
        observed=gui_controls(self.transport,self.box,self.stop_id)
        snapshot=self.box.snapshot()
        expected={INITIAL_PAUSE,self.stop_id,*[row['request_id'] for row in observed]}
        if (not observed or set(row['request_id'] for row in snapshot.requests)!=expected
                or any(snapshot.status(row['request_id'])['outcome']!='applied' or
                       snapshot.status(row['request_id'])['owner_acknowledged'] is not True
                       for row in snapshot.requests)):
            raise RuntimeError('Complete cold-control request/ACK ledger differs')
        worker=read(self.work/f'result-{self.worker.pid}.json')
        if (worker.get('provider_calls')!=0 or worker.get('service_stopped') is not True
                or worker.get('passed') is not False or worker.get('completed') is not False):
            raise RuntimeError('Worker Stop result contains unverified work/completion')
        if self.result.get('joined_obligation_errors'):raise RuntimeError('Retained obligation failed')
        if (self.result.get('retained_obligations_joined') is not True
                or self.result.get('gui_cleanup',{}).get('closed') is not True
                or self.result.get('gui_cleanup',{}).get('faults')!=[]):
            raise RuntimeError('Final child/pipe obligations are not cleanly joined')
        if not self.result.get('listener_cleanup',{}).get('clean_close') or not self.result.get('transport_cleanup',{}).get('closed'):
            raise RuntimeError('Control transport/listener did not close cleanly')
        if self.job.active_process_ids()!={os.getpid()}:raise RuntimeError('Actual containing job still has children')
        scheduler=self.host.gateway.scheduler
        if not scheduler.closing or self.host.controller.fault or not self.host.closed:
            raise RuntimeError('Terminal host/scheduler closure differs')
        cleanup=self.result['cleanup']
        if cleanup.get('closed') is not True or any(cleanup.get(k) is not None for k in ('primary_error','cleanup_error','controller_fault')):
            raise RuntimeError('Native cold cleanup has a fault')
        events=complete_ledger(self.host.controller.events,self.initial_events)
        if any(row.get('restore_requested') is True for row in events):raise RuntimeError('Unexpected native restoration')
        self.result.update(provider_calls=0,dispatched_file_effects=0,native_launch_intent=None,
            handoff_events=events,full_handoff_ledger=True,task_status='pending',demand_state='paused',
            owner_released=True,worker_exit_code=STOP_EXIT,task_completed=False,no_resume=True,
            actual_job_members_after_cleanup=[os.getpid()],native_cold_cleanup=deepcopy(cleanup),
            worker_stop_receipt=deepcopy(worker['service_stop']))
        self.result['controls']=[snapshot.status(row['request_id']) for row in snapshot.requests]
        rec.save(self.root/'terminal-checkpoint.private.json',asdict(cp))
        if verify_closure()!=self.result['source']:raise RuntimeError('Runtime source changed during trial')

    def validate_cleanup(self):
        super().validate_cleanup()
        self.validate_terminal()

    async def run(self):
        if self.root.is_relative_to(HERE):
            raise ValueError('Fresh evidence must be outside qualification source')
        self.result['source']=verify_closure()
        result=await super().run()
        result['case_checks_and_cleanup_passed']=result['clean_stop']
        return result


class FullUIQualification(ColdUIQualification):
    safe_report=ValidationChecks.safe_report
    activate_verified_runtime=ValidationChecks.activate_verified_runtime
    verify_runtime_bindings=ValidationChecks.verify_runtime_bindings

    def __init__(self,args):
        super().__init__(args,qualification_hold_after_report=True)
        self.args.case='complete'
        self.result['case']='gui-iq3s-installed-worker-recovery'
        self.runtime_bindings=[];self.cold_timing_verified=False
        self.worker_records=[];self.gui_resumes=[];self.restart_wait=None
        self.current_phase='preparing'

    async def ready(self,child,path):
        # Existing readiness and its worker receipt retain their exact contract.
        await DesktopComposition.ready(self,child,path)
        if getattr(self,'progress',None) is not None:
            started=time.monotonic()
            snapshot=self.host.snapshot()
            checkpoint=self.checkpoint()
            row={'started_monotonic':started,'finished_monotonic':time.monotonic(),
                'worker_pid':child.pid,'worker_live':child.poll() is None,
                'owner_epoch':checkpoint.owner_epoch,'task_revision':checkpoint.revision,
                'intent_revision':self.gate._revision,
                'gui_binding':None if self.gate._binding is None else asdict(self.gate._binding),
                'admission_observed':snapshot['controller']['admission_allowed'],
                'host_snapshot':snapshot}
            observations=self.result.setdefault('cooperative_readiness_observations',[])
            observations.append(row)
            rec.save(self.root/f'cooperative-readiness-{len(observations)}.private.json',row)

    def launch(self,command,label):
        if label=='worker':
            command=list(command)
            self.first_ready=self.work/'controller-ready-1.json'
            command[command.index('--controller-ready')+1]=str(self.first_ready)
            gateway=self.host.gateway
            if (self.host.adapter.launch_intent is not None or gateway._runtime_context is not None
                    or self.registry.observe(self.identity.registration_id).eligible
                    or gateway._runtime_loop is not asyncio.get_running_loop()):
                raise RuntimeError('Cold host already has runtime work before initial paused owner')
            self.host.controller.on_verified_owner=self.activate_verified_runtime
            self.cold_timing_verified=True
        return super().launch(command,label)

    async def prepare(self):
        await super().prepare()
        self.worker_records.append({'worker':self.worker,'binding':self.stop_binding,
            'capability':self.worker_cap,'stop_id':self.stop_id})
        self.phase('ready_for_first_gui_resume')
        value=read(self.root/'ready.private.json')
        value['instructions']='Resume through the real window. Wait for replacement readiness, Resume again, then Stop after task completion.'
        rec.save(self.root/'ready.private.json',value)

    def phase(self,name,**fields):
        self.current_phase=name
        value={'phase':name,'gui_pid':None if self.gui is None else self.gui.process.pid,
            'gui_title':TITLE,'worker_pid':None if self.worker is None else self.worker.pid,
            'task_completed':self.result['task_completed'],**fields}
        if self.runtime is not None:value['runtime']=self.runtime.status()
        if self.transport is not None:value['transport']=self.transport.lifecycle()
        rec.save(self.root/'status.private.json',value)
        self.event('qualification_phase',phase=name)

    def require_continuing(self):
        self.remaining()
        if self.transport is not None and self.transport.lifecycle()['stop_requested']:
            raise RuntimeError('Manual Stop interrupted full-task qualification')
        if self.facade is not None and self.facade._fenced:
            raise RuntimeError('Admission is fenced; full-task qualification cannot continue')
        if self.gui is not None and self.gui.process is not None and self.gui.process.poll() is not None:
            raise RuntimeError('GUI exited before the required manual Stop')

    async def until(self,predicate,child=None,timeout=240):
        def guarded():
            if self.deadline is not None:self.require_continuing()
            return predicate()
        return await DesktopComposition.until(self,guarded,child,timeout)

    def gui_resume(self,after_sequence,owner_epoch):
        snapshot=self.box.snapshot()
        if not snapshot.requests:return None
        latest=snapshot.requests[-1]
        request_id=latest['request_id']
        record=self.transport._records.get(request_id)
        if record is None or record['command']!='resume' or record['outcome']!='known' or not record['task'].done():
            return None
        record['task'].result()
        ack=snapshot.status(request_id)
        if ack['sequence']<=after_sequence or ack['outcome']!='applied' or ack['owner_acknowledged'] is not True:
            return None
        if (snapshot.target.owner_epoch!=owner_epoch or snapshot.demand is None
                or snapshot.demand['state']!='waiting' or snapshot.target.operation is not None
                or snapshot.target.requires_reconciliation):
            raise RuntimeError('GUI Resume is not the current safe waiting owner')
        self.assert_original(snapshot.target)
        if not self.facade.session_is_live(self.gui.binding.session_id):
            raise RuntimeError('GUI Resume lacks the retained authenticated session')
        return {key:ack[key] for key in ('request_id','command','sequence','outcome','owner_acknowledged')}

    async def await_gui_resume(self,after_sequence,child,owner_epoch):
        ack=await self.until(lambda:self.gui_resume(after_sequence,owner_epoch),child,timeout=self.remaining())
        if ack['request_id'] in {row['request_id'] for row in self.gui_resumes}:
            raise RuntimeError('A prior GUI command cannot resume a replacement')
        self.gui_resumes.append(ack);self.event('gui_resume_acknowledged',**ack)
        return ack

    def create_replacement_binding(self):
        """Synchronous callback; facade owns the replacement guard around it."""
        self.stop_id='service-stop-'+uuid.uuid4().hex
        self.worker_cap=object()
        ready=self.work/'controller-ready-2.json'
        if ready.exists():raise RuntimeError('Replacement readiness must be fresh')
        command=[self.plan['base_python'],'-I','-B','-m','adaptive_inference.desktop.hermes.run_recovery',
            'worker','--run',str(self.work),'--controller-ready',str(ready),
            '--gateway-instance',self.host.gateway.instance,'--deadline-monotonic',str(self.deadline),
            '--stop-request-id',self.stop_id,'--qualification-hold-after-report']
        before=len(self.handles)
        # Retain the exact Popen even when its post-launch diagnostic fails.
        try:
            child=self.launch(command,'worker-2')
        finally:
            if len(self.handles)==before+1:
                self.worker=self.handles[-1]
                self.stop_binding=None
                self.worker_records.append({'worker':self.worker,'binding':None,
                    'capability':self.worker_cap,'stop_id':self.stop_id})
        self.bind_worker_stop()
        self.worker_records[-1]['binding']=self.stop_binding
        handle=self.launch_api.handle(child)
        identity=self.launch_api.identity(handle)
        if (identity[0]!=child.pid or self.launch_api.in_job(handle,self.job._HANDLE) is not True
                or child.poll() is not None):
            raise RuntimeError('Replacement is not retained and live in the containing job')
        self.result['replacement_retained_identity']={'pid':identity[0],
            'creation_time_100ns':identity[1],'containing_job_verified':True}
        self.second_ready=ready
        return self.stop_binding,self.worker_cap

    async def restart_at_checkpoint(self,first,before):
        self.require_continuing()
        if first is not self.worker or first not in self.handles:
            raise RuntimeError('Restart injection requires the exact first retained worker')
        # Deliberate test injection at a verified checkpoint, not product Stop.
        if first.poll() is not None:raise RuntimeError('First owner exited before restart injection')
        first.kill()
        self.restart_wait=asyncio.create_task(asyncio.to_thread(first.wait,10))
        code=await asyncio.shield(self.restart_wait)
        self.event('controlled_restart_injection',pid=first.pid,exit_code=code,
            safe_checkpoint_revision=before.revision,product_stop=False)
        self.result['injected_restart']={'pid':first.pid,'exit_code':code,
            'safe_checkpoint_revision':before.revision,'joined':True,'product_stop':False}
        self.require_continuing()
        self.facade.replace_worker(self.stop_binding,self.create_replacement_binding)

    async def interact(self):
        first=self.worker;owner=self.checkpoint().owner_epoch
        await self.await_gui_resume(self.status(INITIAL_PAUSE)['sequence'],first,owner)
        self.phase('first_owner_waiting_for_resources')
        await self.ready(first,self.first_ready)
        self.phase('first_owner_running_original_task')
        await self.until(lambda:(self.work/'pause.json').exists(),first,timeout=self.remaining())
        self.safe_report(pid=first.pid)
        self.submit(REPORT_PAUSE,'pause');await self.ack(REPORT_PAUSE,first)
        before,report_hash,effects,wires=self.safe_report(pid=first.pid)
        rec.save(self.root/'paused-checkpoint.private.json',asdict(before))
        rec.save(self.root/'paused-wire.private.json',wires)
        self.phase('verified_report_paused_before_restart',report_sha256=report_hash,
            completed_effects=1,provider_calls=len(wires))
        await asyncio.sleep(1)
        self.require_continuing()
        after,after_hash,after_effects,after_wires=self.safe_report(pid=first.pid)
        scheduler=self.host.gateway.scheduler
        if (after!=before or after_hash!=report_hash or after_effects!=effects or after_wires!=wires
                or scheduler.active is not None or scheduler.pending or scheduler.uncertain):
            raise RuntimeError('New or uncertain work appeared after pause acknowledgement')
        self.before,self.report_hash,self.effects,self.wires=before,report_hash,effects,wires
        await self.restart_at_checkpoint(first,before)
        second=self.worker
        await self.until(lambda:self.checkpoint().owner_epoch not in (None,before.owner_epoch),second)
        claimed=self.checkpoint();self.assert_original(claimed)
        if (claimed.state[NAMESPACE]['state']!='paused' or claimed.operation is not None
                or claimed.requires_reconciliation or claimed.state['attempts']!=before.state['attempts']
                or claimed.state['native_history']!=before.state['native_history']):
            raise RuntimeError('Replacement lost paused safe progress')
        rec.save(self.root/'replacement-checkpoint.private.json',asdict(claimed))
        self.phase('ready_for_replacement_gui_resume',original_task_deadline=self.deadline)
        await self.await_gui_resume(self.status(REPORT_PAUSE)['sequence'],second,claimed.owner_epoch)
        self.phase('replacement_waiting_for_resources')
        await self.ready(second,self.second_ready)
        self.phase('replacement_finishing_original_task')
        await self.until(lambda:second.poll() is not None,timeout=self.remaining())
        if await self.join_child(second)!=0:raise RuntimeError('Replacement Hermes failed original task')
        self.verify_completed_task()
        self.result['task_case_checks_passed']=True
        self.phase('task_completed_ready_for_manual_stop',report_sha256=report_hash,completed_effects=1)
        while not self.transport.lifecycle()['stop_requested']:
            self.remaining()
            if self.gui.process.poll() is not None:raise RuntimeError('GUI exited without manual Stop')
            await asyncio.sleep(.1)
        self.result['manual_stop_observed']=True
        await asyncio.shield(self.transport._stop_task)
        if not self.transport.lifecycle()['stop_confirmed']:raise RuntimeError('Manual Stop is not confirmed')
        self.result['lifecycle']=await self.facade.cooperative_stop()
        if self.result['lifecycle']!={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}:
            raise RuntimeError('Manual Stop lacks exact verified closure')

    def verify_completed_task(self):
        # Exact final assertions reused from the accepted v3 qualification.
        before,report_hash,effects,wires=self.before,self.report_hash,self.effects,self.wires
        final=read(self.work/f'result-{self.worker.pid}.json');cp=self.checkpoint();self.assert_original(cp)
        if (any(final.get(key) is not True for key in ('passed','completed','resumed'))
                or final.get('fixture') is not self.args.fixture or final.get('model')!=MODEL
                or final.get('quality')!=QUALITY or final.get('context')!=CONTEXT
                or final.get('sdk_revision')!=self.plan['sdk_revision'] or final.get('report')!=REPORT
                or final.get('artifacts')!={'report.json':report_hash}
                or final.get('original_prompt_sha256')!=rec.digest(self.original.prompt)):
            raise RuntimeError('Original M1 report/SDK/quality/context acceptance failed')
        if (cp.state['status']!='accepted' or cp.state['phase']!='accepted' or cp.operation is not None
                or cp.requires_reconciliation or cp.state['native_history'][:len(before.state['native_history'])]!=before.state['native_history']
                or cp.state['requests']-before.state['requests']!=final['provider_calls']
                or (self.work/'effect-receipts.jsonl').read_bytes()!=effects
                or sha(self.work/'work/report.json')!=report_hash):
            raise RuntimeError('Task progress or single-write proof changed during replacement')
        final_wires=read(self.work/'wire-observations.json')
        if (final_wires[:len(wires)]!=wires or len(final_wires)-len(wires)!=final['provider_calls']
                or any(row.get('model')!=MODEL or row.get('quality')!=QUALITY or row.get('class')!='normal'
                       or not row.get('finished_at') for row in final_wires)):
            raise RuntimeError('Exact wire quality or lineage was not retained')
        if self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Accepted task remains eligible for new demand')
        self.result.update(task_completed=True,report=REPORT,report_sha256=report_hash,
            dispatched_file_effects=1,effect_receipts_sha256=hashlib.sha256(effects).hexdigest(),
            provider_calls=len(final_wires),retained_prompt_sha256=rec.digest(cp.prompt),
            native_history_sha256=rec.digest(cp.state['native_history']),
            task_status=cp.state['status'],demand_state=cp.state[NAMESPACE]['state'])

    def obligations(self):
        return super().obligations()+[self.restart_wait]+[
            row['binding']._work for row in self.worker_records if row['binding'] is not None]

    async def dispose(self,failed):
        # A failed replacement callback retains its exact child before raising.
        # A standalone binding can still ask it to stop, while facade fault
        # prevents ordinary native closure from relying on the old worker.
        if self.worker is not None and self.stop_binding is None:self.bind_worker_stop()
        if (self.facade is not None and self.stop_binding is not None
                and self.facade.worker_stop is not self.stop_binding):
            self.fence()
            if self.transport is not None:
                self.transport._request_stop()
                # Drain accepted DB mutations first. The faulted facade cannot
                # close native resources on its former worker's receipt.
                await asyncio.shield(self.transport._stop_task)
            self.stop_binding.request_stop(self.worker_cap)
        await super().dispose(failed)

    def validate_terminal(self):
        self.verify_completed_task()
        cp=self.checkpoint()
        if cp.owner_epoch is not None or self.worker.poll()!=0:
            raise RuntimeError('Completed replacement has not exited and released ownership')
        if self.stop_binding._verify_exit(0)!='task_completed':
            raise RuntimeError('Final Stop does not verify completed-task outcome')
        replacements=self.facade.worker_replacements
        if (len(self.worker_records)!=2 or len(replacements)!=1 or not replacements[0]['committed']
                or replacements[0]['previous_binding'] is not self.worker_records[0]['binding']
                or replacements[0]['binding'] is not self.stop_binding
                or len({row['stop_id'] for row in self.worker_records})!=2):
            raise RuntimeError('Exact retained replacement/Stop binding lineage differs')
        snapshot=self.box.snapshot()
        expected={INITIAL_PAUSE,REPORT_PAUSE,*[row['request_id'] for row in self.gui_resumes]}
        if (len(self.gui_resumes)!=2 or len(self.transport._records)!=2
                or set(self.transport._records)!={row['request_id'] for row in self.gui_resumes}
                or {row['request_id'] for row in snapshot.requests}!=expected
                or any(snapshot.status(row['request_id'])['outcome']!='applied'
                    or snapshot.status(row['request_id'])['owner_acknowledged'] is not True
                    for row in snapshot.requests)):
            raise RuntimeError('Full actual GUI and qualification control ledger differs')
        if (self.result.get('joined_obligation_errors') or not self.result.get('retained_obligations_joined')
                or not self.facade._gui_safe() or not self.facade._worker_safe()
                or self.facade.worker_receipt['outcome']!='task_completed'
                or not self.result.get('listener_cleanup',{}).get('clean_close')
                or not self.result.get('transport_cleanup',{}).get('closed')):
            raise RuntimeError('Final control and child obligations are not safely joined')
        if self.job.active_process_ids()!={os.getpid()}:raise RuntimeError('Containing job still has children')
        cleanup=self.result['cleanup']
        if (not self.host.closed or not self.host.gateway.scheduler.closing
                or cleanup.get('closed') is not True
                or any(cleanup.get(k) is not None for k in ('primary_error','cleanup_error','controller_fault'))):
            raise RuntimeError('Native cleanup has a fault')
        events=complete_ledger(self.host.controller.events,self.initial_events)
        self.result['runtime_binding']=self.verify_runtime_bindings()
        self.result.update(full_handoff_ledger=True,handoff_events=events,owner_released=True,
            worker_exit_code=0,actual_job_members_after_cleanup=[os.getpid()],
            worker_stop_outcome='task_completed',gui_resume_acknowledgements=deepcopy(self.gui_resumes),
            retained_worker_lifetimes=[{'pid':row['worker'].pid,'exit_code':row['worker'].poll(),
                'stop_request_id':row['stop_id']} for row in self.worker_records],
            replacement_binding_committed=True,
            controls=[snapshot.status(row['request_id']) for row in snapshot.requests])
        rec.save(self.root/'terminal-checkpoint.private.json',asdict(cp))
        if verify_closure()!=self.result['source']:raise RuntimeError('Runtime source changed during trial')


def execute(args):
    # Original hard qualification bound includes event-loop/interpreter teardown.
    threading.Thread(target=hard_deadline,args=(1800,),daemon=True).start()
    cold_case=args.case=='cold'
    case=ColdUIQualification if cold_case else FullUIQualification
    result=asyncio.run(case(args).run())
    result['asyncio_teardown_completed']=True
    result['qualification_case_passed']=bool(result['case_checks_and_cleanup_passed']
        and (cold_case or result['task_completed']))
    rec.save(args.run/'result.private.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=('cold','full'),required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    result=execute(parser.parse_args())
    print(json.dumps({k:result.get(k) for k in ('case','qualification_case_passed','task_completed')}))
    return 0 if result['qualification_case_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
