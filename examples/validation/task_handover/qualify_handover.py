# SPDX-License-Identifier: Apache-2.0
"""Ordinary installed two-task composition; root alone performs real UI actions."""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import OUTER_SECONDS,load,read,save,sha
from checks import check_task,check_handover
from selected_source import selected_source_matches
from evidence import task_disk,preservation
from safe_wait import sealed_disk,selected_disk,check_safe_wait
from adaptive_inference.desktop.composition import DesktopComposition,hard_deadline,complete_ledger
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.execution_clock import execution_now,CLOCK_ID


class HandoverQualification(DesktopComposition):
    def __init__(self,bound):
        self.bound=bound;inputs=bound['inputs']
        super().__init__(inputs['profile'],bound['case'],task_spec=inputs['inventory_spec'],
                         task_inputs=inputs['inventory_input'].parent)
        self.product_interaction=None;self.a_before=None;self.accepted=[];self.initial_identity=None
        self.previous=None;self.selected_record=None;self.selected_readiness=None;self.selection_status=None
        self.launch_records=[]
        self.result.update(case='gui-iq3s-safe-wait-continue-two-tasks',qualification_case_passed=False,fixture=False)

    def launch(self,command,label):
        child=super().launch(command,label)
        from adaptive_inference.desktop.gui_launch import WindowsLaunchAPI
        api=WindowsLaunchAPI();identity=api.identity(api.handle(child))
        self.launch_records.append({'child':child,'label':label,
            'identity':{'pid':identity[0],'creation_time_100ns':identity[1]}})
        return child

    def phase(self,name,**fields):
        rec.save(self.root/'phase.private.json',{'phase':name,'qpc':execution_now(),
            'deadline_clock':CLOCK_ID,**fields})

    async def prepare(self):
        await super().prepare()
        self.initial_identity={'pid':os.getpid(),'host_epoch':self.host_epoch,
                               'gateway_instance':self.host.gateway.instance}
        self.result['harness']={'manifest_sha256':self.bound['manifest_sha256'],
            'bindings_sha256':self.bound['bindings_sha256'],'outer_deadline_s':OUTER_SECONDS}
        self.logical_original=asdict(self.original);self.logical_run=self.work
        self.logical_gui=asdict(self.gui.binding);self.initial_plan_sha256=sha(self.work/'plan.json')
        self.phase('inventory_paused_ready_for_resume',gui_binding=self.logical_gui)

    async def observe_until(self,predicate):
        while not predicate():
            if self.product_interaction.done():
                self.product_interaction.result()
                raise RuntimeError('Ordinary interaction ended before required UI boundary')
            if self.host.controller.fault:raise RuntimeError('Controller fault during qualification')
            if self.handover.stopping:raise RuntimeError('Stop preceded required two-task observations')
            await asyncio.sleep(.05)

    def task(self,episode,*,current=False):
        # Before B selection, episode A still retains the first worker. Capture
        # the actual selected composition view without relabeling that snapshot.
        view=({key:getattr(self,key) for key in ('worker','stop_binding','work','identity','original','transport','gui')}
              if current else episode)
        child=view['worker'];joined=self.waits.get(child)
        if joined is None or not joined.done() or joined.result()!=child.poll():
            raise RuntimeError('Actual retained worker was not joined')
        if view['stop_binding']._verify_exit(child.poll())!='task_completed':raise RuntimeError('Task worker did not complete')
        selected=self.selected_record if view['work']==self.logical_run else None
        grant=None if selected is None else selected['grant']
        row=task_disk(view['work'],view['identity'].task_id,child.pid,asdict(view['original']),grant=grant)
        records=view['transport']._records
        resumes=[key for key,value in records.items() if value['command']=='resume'
            and value['outcome']=='known' and value['task'].done() and not value['task'].cancelled()
            and value['task'].exception() is None]
        identity=(selected['retained_child_identity'] if selected is not None else
                  next(record['retained_child_identity'] for record in self.handover.records.values() if record['episode'] is episode))
        if identity['pid']!=child.pid:raise RuntimeError('Retained worker identity changed')
        row.update(gui_binding=asdict(view['gui'].binding),gui_resume_ids=resumes,
            lifetime={'pid':child.pid,'exit_code':child.poll(),'joined':True,
                      'creation_time_100ns':identity['creation_time_100ns'],
                      'containing_job_verified':identity['containing_job_verified']})
        return row

    def capture_expired(self,status):
        child=self.worker;joined=self.waits.get(child)
        if (child.poll()!=6 or joined is None or not joined.done() or joined.result()!=6
                or self.stop_binding._verify_exit(6)!='admission_wait_budget_expired'
                or self.result.get('task_completed') is not False):
            raise RuntimeError('Actual safe wait expiry and retained join required')
        sealed=sealed_disk(self.work,self.logical_original,child.pid)
        raw=(self.work/'wire-observations.json').read_bytes()
        effects=self.work/'effect-receipts.jsonl';effect_raw=effects.read_bytes() if effects.exists() else b''
        records=self.transport._records
        resumes=[key for key,value in records.items() if value['command']=='resume' and value['outcome']=='known'
            and value['task'].done() and not value['task'].cancelled() and value['task'].exception() is None]
        self.previous={'sealed':sealed,'child':child,'identity':deepcopy(self.result['retained_worker_identity']),
            'wire':read(self.work/'wire-observations.json'),'wire_file_sha256':rec.digest(raw),
            'effects':[__import__('json').loads(line) for line in effect_raw.splitlines() if line.strip()],
            'gui_resume_ids':resumes,'qpc':execution_now(),'gui_binding':asdict(self.gui.binding),
            'status':deepcopy(status)}
        save(self.root/'wait-expired.private.json',{k:v for k,v in self.previous.items() if k!='child'})
        (self.root/'wait-sealed-wire.raw.private.json').write_bytes(raw)
        self.phase('admission_wait_expired_ready_for_continue',gui_binding=self.logical_gui)

    async def launch_continuation(self,record,coordinator,intent_valid):
        if self.previous is None or len(self.continuation.records)!=1 or len(self.facade.selected_transitions)!=1:
            raise RuntimeError('Exactly one Continue must follow observed safe expiry')
        self.selected_record=record;self.selected_authority=record['authority']
        self.selection_status=deepcopy(self.runtime.status())
        save(self.root/'selected-status.private.json',self.selection_status)
        save(self.root/'selected-initial.private.json',asdict(record['original']))
        await DesktopComposition.launch_continuation(self,record,coordinator,intent_valid)

    async def ready_continuation(self,record,intent_valid):
        started=execution_now()
        await DesktopComposition.ready_continuation(self,record,intent_valid)
        if not intent_valid() or self.runtime._stopping:return
        self.selected_readiness={'started_qpc':started,'finished_qpc':execution_now(),'deadline_clock':CLOCK_ID,
            'value':read(record['diagnostics']/'controller-ready.json'),
            'boot':read(record['diagnostics']/f"bootstrap-{record['child'].pid}.json"),
            'host_snapshot':self.host.snapshot(),'gui_binding':asdict(self.gui.binding),
            'readiness_deadline_monotonic':record['readiness_deadline_monotonic']}
        save(self.root/'selected-readiness.private.json',self.selected_readiness)

    def recovery_evidence(self,a):
        record=self.selected_record;previous=self.previous
        if record is None or previous is None or self.selected_readiness is None:raise RuntimeError('Missing recovery branch')
        oldchild=previous['child'];joined=self.waits.get(oldchild);identity=previous['identity']
        oldlife={'pid':oldchild.pid,'exit_code':oldchild.poll(),'joined':joined is not None and joined.done() and joined.result()==oldchild.poll(),
            'creation_time_100ns':identity['creation_time_100ns'],'containing_job_verified':identity['containing_job_verified']}
        disk=selected_disk(self.logical_run,self.logical_original,record['grant'],self.host_epoch,record['child'].pid)
        e={**disk,'sealed_before':previous['sealed'],
            'sealed_after':sealed_disk(self.logical_run,self.logical_original,oldchild.pid),
            'grant':deepcopy(record['grant']),'wire_before':previous['wire'],'wire_after':a['wire'],
            'wire_before_file_sha256':previous['wire_file_sha256'],
            'effects_before':previous['effects'],'effects_after':a['effects'],'native_history_after':a['native_history'],
            'gui_resume_ids':previous['gui_resume_ids'],'gui_binding':self.logical_gui,
            'transition':{key:deepcopy(record[key]) for key in ('request','phase','release','committed','started',
                'launch_attempted','authorization_resolved','retained_child_identity','pause_id','resume_id','stop_id')},
            'successor_controls':a['controls'],'selection_status':self.selection_status,'readiness':self.selected_readiness,
            'gateway_instance':self.host.gateway.instance,'lifetimes':[oldlife,a['lifetime']]}
        if sha(self.logical_run/'plan.json')!=self.initial_plan_sha256:raise RuntimeError('Original logical plan changed')
        check_safe_wait(e)
        return e

    async def interact(self):
        self.product_interaction=asyncio.create_task(DesktopComposition.interact(self))
        await self.observe_until(lambda:self.worker_exit_verified and self.result.get('execution_expired') is True)
        if self.result.get('worker_outcome')!='admission_wait_budget_expired':raise RuntimeError('Required wait expiry did not occur')
        await self.observe_until(lambda:self.host.controller.state=='parked')
        await self.runtime.refresh()
        await asyncio.to_thread(self.capture_expired,deepcopy(self.runtime.status()))
        await self.observe_until(lambda:self.selected_readiness is not None and not self.runtime._transitioning)
        await self.observe_until(lambda:self.worker_exit_verified and self.result.get('task_completed') is True)
        a=await asyncio.to_thread(self.task,self.handover.episodes[0],current=True)
        check_task(a,semantic='oracle_matched',grant=self.selected_record['grant'])
        recovery=await asyncio.to_thread(self.recovery_evidence,a)
        save(self.root/'safe-wait-accepted.private.json',recovery)
        save(self.root/'inventory-accepted-time.private.json',{'deadline_clock':CLOCK_ID,'qpc':execution_now(),
            'execution_id':a['checkpoint']['task_id'],'revision':a['checkpoint']['revision']})
        self.a_before=preservation(a);self.accepted.append(a)
        save(self.root/'inventory-accepted.private.json',a)
        self.phase('inventory_accepted_ready_for_new_task',task_id=a['checkpoint']['task_id'])
        await self.observe_until(lambda:len(self.handover.records)==1
            and next(iter(self.handover.records.values()))['phase']=='opened')
        record=next(iter(self.handover.records.values()))
        if len(self.handover.episodes)!=2:raise RuntimeError('Expected exactly two episodes')
        source=record['reservation']['payload']['source'];inputs=self.bound['inputs']
        expected={'task_spec_path':str(inputs['welcome_spec']),
            'task_spec_sha256':sha(inputs['welcome_spec']),'task_inputs':str(inputs['welcome_input'].parent)}
        if not selected_source_matches(source,expected):raise RuntimeError('The real chooser selected different task inputs')
        save(self.root/'welcome-paused-ready.private.json',{'paused':record['paused'],'ready':record['ready'],
            'qpc':execution_now(),'deadline_clock':CLOCK_ID,'source':source,
            'host_identity':{'pid':os.getpid(),'host_epoch':self.host_epoch,'gateway_instance':self.host.gateway.instance}})
        self.phase('welcome_paused_ready_for_resume',gui_binding=asdict(self.gui.binding))
        await self.observe_until(lambda:self.worker_exit_verified and self.result.get('task_completed') is True)
        b=await asyncio.to_thread(self.task,self.handover.episodes[1]);check_task(b,semantic='not_checked')
        self.accepted.append(b);save(self.root/'welcome-accepted.private.json',b)
        self.phase('welcome_accepted_ready_for_stop',task_id=b['checkpoint']['task_id'])
        await asyncio.shield(self.product_interaction)
        self.result['manual_stop_observed']=True

    def validate_cleanup(self):
        super().validate_cleanup()
        if len(self.accepted)!=2 or len(self.handover.records)!=1 or len(self.handover.episodes)!=2:
            raise RuntimeError('Incomplete two-task evidence')
        if self.product_interaction is None or not self.product_interaction.done():
            raise RuntimeError('Ordinary interaction remains retained')
        self.product_interaction.result()
        records=list(self.handover.records.values());record=records[0]
        rows=[self.task(episode) for episode in self.handover.episodes]
        selected={key:deepcopy(record[key]) for key in ('request','reservation','resolved','phase','prepared',
            'started','launch_attempted','rebound','release','paused','ready','retained_child_identity')}
        current={'pid':os.getpid(),'host_epoch':self.host_epoch,'gateway_instance':self.host.gateway.instance}
        children=[]
        if [x['child'] for x in self.launch_records]!=self.handles:raise RuntimeError('Unrecorded retained child')
        for launch in self.launch_records:
            child=launch['child'];joined=self.waits.get(child)
            children.append({'pid':child.pid,'exit_code':child.poll(),'label':launch['label'],
                'creation_time_100ns':launch['identity']['creation_time_100ns'],
                'joined':joined is not None and joined.done() and joined.result()==child.poll()})
        evidence={'safe_wait':self.recovery_evidence(rows[0]),'logical_original':self.logical_original,'tasks':rows,'a_before':self.a_before,'a_after':preservation(rows[0]),
            'inventory_input':self.bound['inputs']['inventory_input'].read_text(encoding='utf-8'),
            'selection_revision':self.handover.selection_revision,'transition':selected,
            'selected_source':selected['reservation']['payload']['source'],
            'host_identity_before':self.initial_identity,'host_identity_after':current,'host_epoch':self.host_epoch,
            'gateway_instance':self.host.gateway.instance,'episodes':deepcopy(self.result['task_episodes']),
            'retained_children':children,'admission':self.handover.authority.status(),
            'admission_checkpoint':asdict(self.handover.authority.store.load(self.handover.authority.task_id)),
            'admission_task_id':self.handover.authority.task_id}
        checks=check_handover(evidence)
        events=complete_ledger(self.host.controller.events,self.initial_events)
        save(self.root/'handover-evidence.private.json',evidence)
        self.result.update(qualification_case_passed=True,handover_checks=checks,
            actual_job_members_after_cleanup=sorted(self.job.active_process_ids()),
            handoff_events=events,gateway_history=deepcopy(list(self.host.gateway.history)),
            provider_calls=sum(len(row['wire']) for row in rows),dispatched_file_effects=2,
            tasks_semantic_validation=['oracle_matched','not_checked'])

    async def dispose(self,failed):
        await super().dispose(failed)
        if self.product_interaction is not None:
            results=await asyncio.gather(asyncio.shield(self.product_interaction),return_exceptions=True)
            if any(isinstance(x,BaseException) for x in results):
                self.result['qualification_observer_failure']=True


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bindings',type=Path,required=True)
    args=parser.parse_args();bound=load(args.bindings,installed=True)
    if os.name!='nt':raise ValueError('Windows installed qualification required')
    threading.Thread(target=hard_deadline,args=(OUTER_SECONDS,),daemon=True).start()
    result=asyncio.run(HandoverQualification(bound).run())
    result['asyncio_teardown_completed']=True
    rec.save(bound['case']/'result.private.json',result)
    return 0 if result.get('clean_stop') is True and result.get('qualification_case_passed') is True else 1


if __name__=='__main__':raise SystemExit(main())
