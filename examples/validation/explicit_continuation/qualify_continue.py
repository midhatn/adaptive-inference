# SPDX-License-Identifier: Apache-2.0
"""Fresh installed Continue qualification. Root alone runs real window actions."""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

# -I excludes even the script directory. Only this reviewed harness is added;
# adaptive_inference must resolve from the reviewed installation, never src.
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import HERE, OUTER_SECONDS, baseline, load, read, save, sha
from checks import check_continuation, digest, REPORT, MODEL, QUALITY, CONTEXT, NS as NAMESPACE

old = baseline('installed_desktop/qualify.py')
rec = old.rec
from adaptive_inference.desktop.composition import DesktopComposition, hard_deadline, complete_ledger
from adaptive_inference.execution_clock import execution_now, CLOCK_ID


def raw_history(path, task_id):
    with sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True) as db:
        return [list(row) for row in db.execute(
            'SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',(task_id,))]


class ContinueQualification(old.PausedExpiryQualification):
    def __init__(self,args,bound):
        super().__init__(args)
        self.bound=bound
        self.expiry_ready=False
        self.expiry_task=None
        self.previous=None
        self.selection_status=None
        self.selected_readiness=None
        self.result.update(case='gui-iq3s-installed-explicit-continue',continuation_case_checks_passed=False)

    async def prepare(self):
        await super().prepare()
        self.result['initial_plan_sha256']=sha(self.work/'plan.json')
        self.result['harness']={'manifest_sha256':self.bound['manifest_sha256'],
            'bindings_sha256':self.bound['bindings_sha256'],'outer_deadline_s':OUTER_SECONDS}
        value=read(self.root/'ready.private.json')
        value['instructions']='Resume once; after the saved-report signal Pause once; wait for genuine expiry and saved-work state; click Continue saved task once; after accepted completion click Stop engine once. No second Resume.'
        old.rec.save(self.root/'ready.private.json',value)

    def phase(self,name,**fields):
        if name=='expired_progress_saved_ready_for_manual_stop':
            if self.previous is not None:raise RuntimeError('Duplicate expiry readiness')
            cp=self.checkpoint()
            self.previous={'checkpoint':asdict(cp),'history':raw_history(self.work/'task.sqlite3',cp.task_id),
                'worker':self.worker,'binding':self.stop_binding,'mailbox':self.box,
                'identity':deepcopy(self.result['retained_worker_identity']),
                'deadline':self.deadline,'original':asdict(self.original)}
            save(self.root/'sealed-predecessor.private.json',self.previous['checkpoint'])
            save(self.root/'sealed-history.private.json',self.previous['history'])
            save(self.root/'paused-effects.private.json',{'sha256':digest(self.effects)})
            (self.root/'sealed-wire.raw.private.json').write_bytes((self.work/'wire-observations.json').read_bytes())
            name='expired_progress_saved_ready_for_continue'
            self.expiry_ready=True
        super().phase(name,**fields)

    async def launch_continuation(self,record,coordinator,intent_valid):
        if not self.expiry_ready or self.previous is None:raise RuntimeError('Continue preceded verified expiry')
        if (len(self.continuation.records)!=1 or len(self.facade.selected_transitions)!=1
                or self.facade.selected_transitions[0] is not record):
            raise RuntimeError('Expected exactly one actual Continue transition')
        self.selection_status=deepcopy(self.runtime.status())
        save(self.root/'selected-status.private.json',self.selection_status)
        save(self.root/'selected-initial.private.json',asdict(record['original']))
        await DesktopComposition.launch_continuation(self,record,coordinator,intent_valid)

    async def ready_continuation(self,record,intent_valid):
        started=execution_now()
        await DesktopComposition.ready_continuation(self,record,intent_valid)
        if not intent_valid() or self.runtime._stopping:return
        value=read(record['diagnostics']/'controller-ready.json')
        self.selected_readiness={'started_qpc':started,'finished_qpc':execution_now(),
            'deadline_clock':CLOCK_ID,'value':value,
            'boot':read(record['diagnostics']/f"bootstrap-{record['child'].pid}.json"),
            'host_snapshot':self.host.snapshot(),'gui_binding':asdict(self.gui.binding),
            'readiness_deadline_monotonic':record['readiness_deadline_monotonic']}
        save(self.root/'selected-readiness.private.json',self.selected_readiness)

    def verify_expired_progress(self):
        from adaptive_inference.control_mailbox import EXECUTION_OUTCOME,execution_outcome,control_prefix_digest
        from adaptive_inference.desktop.hermes.service_stop import PAUSED_EXPIRY_EXIT
        cp=self.checkpoint();self.assert_original(cp)
        marker=execution_outcome(cp.state)
        joined=self.waits.get(self.worker)
        if (self.result.get('execution_expired') is not True
                or self.result.get('worker_outcome')!='paused_budget_expired'
                or self.result.get('task_completed') is not False
                or self.worker.poll()!=PAUSED_EXPIRY_EXIT or joined is None or not joined.done()
                or joined.result()!=PAUSED_EXPIRY_EXIT
                or self.stop_binding._verify_exit(PAUSED_EXPIRY_EXIT)!='paused_budget_expired'):
            raise RuntimeError('Expiry lacks the production retained join and verified outcome')
        if (marker is None or cp.owner_epoch is not None or cp.operation is not None
                or cp.requires_reconciliation or cp.state['status']!='pending'
                or cp.state[NAMESPACE]['state']!='paused'):
            raise RuntimeError('Expired execution did not preserve an unowned pending paused task')
        state=deepcopy(cp.state);del state[EXECUTION_OUTCOME]
        pause=self.gui_pauses[0]
        snapshot=self.box.snapshot()
        prefix={'requests':list(snapshot.requests),'receipts':list(snapshot.receipts)}
        if (state!=self.before.state or cp.revision!=self.before.revision+1
                or marker['pre_seal_revision']!=self.before.revision
                or marker['owner_epoch']!=self.before.owner_epoch
                or marker['deadline_monotonic']!=self.deadline
                or self.plan.get('deadline_clock')!=CLOCK_ID
                or cp.metadata.get('deadline_clock')!=CLOCK_ID or state.get('deadline_clock')!=CLOCK_ID
                or marker.get('deadline_clock')!=CLOCK_ID
                or not marker['pause_observed_at_monotonic']<self.deadline<=marker['sealed_at_monotonic']<=execution_now()
                or marker['pause_request_id']!=pause['request_id'] or marker['pause_sequence']!=pause['sequence']
                or marker['pre_seal_state_sha256']!=rec.digest(self.before.state)
                or prefix!=self.paused_prefix
                or marker['control_prefix_sha256']!=control_prefix_digest(snapshot.requests,snapshot.receipts)):
            raise RuntimeError('Expiry changed the saved task or genuine Pause prefix')
        rec.verify_tool_rows(cp.state['native_history'],cp.state['tools'])
        rec.verify_artifacts(cp.state,self.work/'work')
        wires=read(self.work/'wire-observations.json')
        final=read(self.work/f'result-{self.worker.pid}.json')
        if ((self.work/'effect-receipts.jsonl').read_bytes()!=self.effects
                or read(self.work/'work/report.json')!=REPORT or sha(self.work/'work/report.json')!=self.report_hash
                or wires!=self.wires or not 0<len(wires)<=8 or cp.state['requests']!=len(wires)
                or any(row.get('model')!=MODEL or row.get('quality')!=QUALITY or row.get('class')!='normal'
                       or not row.get('finished_at') for row in wires)
                or final.get('model')!=MODEL or final.get('quality')!=QUALITY
                or final.get('fixture') is not False or final.get('sdk_revision')!=self.plan['sdk_revision']
                or final.get('passed') is not False or final.get('completed') is not False
                or final.get('controlled') is not True or final.get('control_state')!='paused'
                or final.get('control_reason')!='paused_budget_expired' or final.get('provider_calls')!=len(wires)
                or final.get('context')!=CONTEXT):
            raise RuntimeError('Expiry lost the original report, quality, accounting or single-write evidence')
        if self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Expired paused execution still requests model admission')
        return cp,final

    async def interact(self):
        self.product_interaction=asyncio.create_task(DesktopComposition.interact(self))
        # The byte-exact expiry observer keeps waiting for Stop after it has
        # captured the seal. It never mutates the selected execution or waits on
        # a worker independently of the retained production interaction.
        self.expiry_task=asyncio.create_task(old.PausedExpiryQualification.observe_expiry_scenario(self))
        await self.observe_until(lambda:self.expiry_ready)
        await self.observe_until(lambda:self.continuation.current is not None)
        record=self.continuation.current
        await self.observe_until(lambda:not self.runtime._transitioning and self.selected_readiness is not None)
        if record['phase']!='running':raise RuntimeError('Continue did not reach derived Resume')
        self.phase('continued_worker_running_original_task')
        await self.observe_until(lambda:self.worker_exit_verified and self.result.get('task_completed') is True)
        cp=self.checkpoint();worker=read(record['diagnostics']/f'result-{self.worker.pid}.json')
        if (cp.state['status']!='accepted' or not all(worker.get(k) is True for k in ('passed','completed','resumed'))
                or worker.get('report')!=REPORT or self.stop_binding._verify_exit(self.worker.poll())!='task_completed'):
            raise RuntimeError('Original task completion not verified')
        save(self.root/'accepted-before-stop.private.json',asdict(cp))
        self.phase('continued_task_accepted_ready_for_manual_stop')
        while not self.transport.lifecycle()['stop_requested']:
            self.require_product_live()
            await asyncio.sleep(.1)
        await asyncio.shield(self.expiry_task)
        await asyncio.shield(self.product_interaction)

    def obligations(self):
        return super().obligations()+[self.expiry_task]

    def validate_terminal(self):
        if self.previous is None or self.selected_readiness is None:raise RuntimeError('Incomplete Continue observations')
        record=self.continuation.current
        if (len(self.continuation.records)!=1 or len(self.facade.selected_transitions)!=1
                or self.facade.selected_transitions[0] is not record
                or self.product_interaction is None or not self.product_interaction.done()
                or self.expiry_task is None or not self.expiry_task.done()):
            raise RuntimeError('Continuation task/record obligations are incomplete')
        self.product_interaction.result();self.expiry_task.result()
        old_worker=self.previous['worker'];worker=self.worker
        def lifetime(child):
            joined=self.waits.get(child)
            identity=self.previous['identity'] if child is old_worker else record['retained_child_identity']
            return {'pid':child.pid,'creation_time_100ns':identity['creation_time_100ns'],'exit_code':child.poll(),
                'joined':joined is not None and joined.done() and joined.result()==child.poll()}
        selected=self.checkpoint();path=record['diagnostics']/f'result-{worker.pid}.json'
        snapshot=record['mailbox'].snapshot()
        evidence={'sealed_before':self.previous['checkpoint'],
            'sealed_after':asdict(self.store.load(self.previous['checkpoint']['task_id'])),
            'paused':asdict(self.before),'history_before':self.previous['history'],
            'history_after':raw_history(self.work/'task.sqlite3',self.previous['checkpoint']['task_id']),
            'grant':deepcopy(record['grant']),'selected':asdict(selected),'selected_initial':asdict(record['original']),
            'authority':asdict(self.store.load(record['authority'].task_id)),
            'authority_history':list(self.store.history(record['authority'].task_id)),
            'authority_task_id':record['authority'].task_id,'worker':read(path),'worker_result_sha256':sha(path),
            'wire_before':self.wires,'wire_after':read(self.work/'wire-observations.json'),
            'effects_before_sha256':digest(self.effects),'effects_after_sha256':sha(self.work/'effect-receipts.jsonl'),
            'effects':[json.loads(row) for row in (self.work/'effect-receipts.jsonl').read_text().splitlines() if row.strip()],
            'report':read(self.work/'work/report.json'),'report_sha256':sha(self.work/'work/report.json'),
            'transition':{key:deepcopy(record[key]) for key in ('request','phase','release','committed','started',
                'launch_attempted','authorization_resolved','retained_child_identity','pause_id','resume_id','stop_id')},
            'successor_controls':[snapshot.status(row['request_id']) for row in snapshot.requests],
            'selection_status':self.selection_status,'readiness':self.selected_readiness,
            'gui_binding':asdict(self.gui.binding),'gateway_instance':self.host.gateway.instance,
            'lifetimes':[lifetime(old_worker),lifetime(worker)],'manual_stop_observed':self.result.get('manual_stop_observed'),
            'stop_confirmed':self.transport.lifecycle()['stop_confirmed'],'lifecycle':self.result.get('lifecycle'),
            'retained_obligations_joined':self.result.get('retained_obligations_joined'),
            'joined_obligation_errors':self.result.get('joined_obligation_errors',[])}
        checks=check_continuation(evidence)
        if sha(self.work/'plan.json')!=self.result['initial_plan_sha256']:raise RuntimeError('Logical plan changed')
        if asdict(self.gui.binding)!=self.result['retained_gui_binding']:raise RuntimeError('GUI binding changed')
        # The predecessor binding verified release before Continue. Its native
        # history is now intentionally a prefix, so do not rerun an old exact-tip
        # verifier against the successor's extended session.
        old.rec.verify_tool_rows(selected.state['native_history'],selected.state['tools'])
        old.rec.verify_artifacts(selected.state,self.work/'work')
        save(self.root/'continuation-evidence.private.json',evidence)
        save(self.root/'terminal-checkpoint.private.json',asdict(selected))
        self.result.update(continuation_case_checks_passed=True,continuation_checks=checks,task_completed=True,
            report=evidence['report'],report_sha256=evidence['report_sha256'],
            provider_calls=len(evidence['wire_after']),dispatched_file_effects=1,
            effect_receipts_sha256=evidence['effects_after_sha256'],
            retained_worker_lifetimes=evidence['lifetimes'],worker_stop_outcome='task_completed',
            gui_resume_acknowledgements=deepcopy(self.gui_resumes),gui_pause_acknowledgements=deepcopy(self.gui_pauses),
            full_handoff_ledger=True,handoff_events=complete_ledger(self.host.controller.events,self.initial_events),
            actual_job_members_after_cleanup=[os.getpid()])
        self.result['runtime_binding']=self.verify_runtime_bindings()
        if load(self.bound['path'],installed=True)['bindings_sha256']!=self.bound['bindings_sha256']:
            raise RuntimeError('Bound installation/source inputs changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings',required=True,type=Path)
    args=parser.parse_args();bound=load(args.bindings,installed=True)
    if bound['case'].exists():raise RuntimeError('Fresh qualification case required')
    args.profile=bound['inputs']['profile'];args.run=bound['case'];args.case='continue'
    threading.Thread(target=hard_deadline,args=(OUTER_SECONDS,),daemon=True).start()
    result=asyncio.run(ContinueQualification(args,bound).run())
    result['asyncio_teardown_completed']=True
    result['qualification_case_passed']=bool(result['case_checks_and_cleanup_passed']
        and result.get('continuation_case_checks_passed') and result.get('task_completed'))
    old.rec.save(args.run/'result.private.json',result)
    print(json.dumps({key:result.get(key) for key in ('case','qualification_case_passed','task_completed')}))
    return 0 if result['qualification_case_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
