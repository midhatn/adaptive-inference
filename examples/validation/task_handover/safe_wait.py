# SPDX-License-Identifier: Apache-2.0
"""Strict additional evidence for one wait-expiry -> explicit Continue branch.

Derived from the retained Continue checker. Physical joins remain controller
evidence; storage/history projections below are read-only, never release proofs.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import sqlite3

from bindings import read, sha
from checks import MODEL, QUALITY, CONTEXT, SDK, NS
from adaptive_inference.desktop.hermes.recovery import digest
from evidence import checkpoint, history, native_history

SEAL='adaptive_inference.execution_outcome.v1'
ACKS='adaptive_inference.control_acks.v1'
AUTH='adaptive_inference.continuation_authority.v1'
LINK='adaptive_inference.execution_authorization.v1'
CLOCK='windows-qpc-seconds-v1'
WAIT='adaptive.admission-wait-budget-expiry.v1'


def sealed_disk(run, original, pid):
    """Reread actual predecessor and its mailbox in one read-only SQL view."""
    from adaptive_inference.task_store import TaskStore
    from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, safe_state
    from adaptive_inference.control_mailbox import ACKS as actual_acks
    run=Path(run)
    with closing(sqlite3.connect((run/'task.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        cp=TaskStore._read(db,original['task_id'])
        authority=object.__new__(ContinuationAuthority);authority.store=TaskStore
        marker=safe_state(cp,sealed=True)
        prefix=authority._wait_prefix(db,cp)
        mailbox=TaskStore._read(db,cp.state[actual_acks]['mailbox_task_id'])
        if marker['schema']!=WAIT or cp.owner_epoch is not None:
            raise ValueError('Exact released admission-wait predecessor required')
        rows=[list(row) for row in db.execute('SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',(cp.task_id,))]
    if cp.prompt!=original['prompt'] or cp.metadata!=original['metadata'] or cp.max_attempts!=original['max_attempts']:
        raise ValueError('Original logical task changed')
    if (len(rows)!=cp.revision+1 or [r[0] for r in rows]!=list(range(cp.revision+1))
            or json.loads(rows[-1][2])['state']!=cp.state
            or digest(json.loads(rows[-2][2])['state'])!=marker['pre_seal_state_sha256']):
        raise ValueError('Actual predecessor seal history changed')
    return {'checkpoint':asdict(cp),'history':rows,'mailbox':asdict(mailbox),'prefix':prefix,
        'worker':read(run/f'result-{pid}.json'),'worker_result_sha256':sha(run/f'result-{pid}.json')}


def selected_disk(run, original, grant, host_epoch, pid):
    """Reuse production inherited-grant validators without provisioning records."""
    from adaptive_inference.task_store import TaskStore
    from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority, wire_rows
    from adaptive_inference.desktop.hermes.continuation_worker import scope_for
    run=Path(run);raw=(run/'plan.json').read_bytes();plan=read(run/'plan.json')
    authority=object.__new__(ContinuationAuthority)
    authority.store=TaskStore;authority.logical_task_id=original['task_id'];authority.host_generation=host_epoch
    authority.scope=scope_for(run,plan,raw)
    authority.declaration={AUTH:{'logical_task_id':original['task_id'],'host_generation':host_epoch,
        'scope':authority.scope,'prompt':original['prompt'],'max_attempts':original['max_attempts'],'metadata':original['metadata']}}
    authority.task_id='continue.'+digest(original['task_id'])
    authority.prompt='Record explicit continuation grants for '+original['task_id']+'.'
    with closing(sqlite3.connect((run/'task.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        cp=TaskStore._read(db,grant['payload']['successor_id'])
        acp=TaskStore._read(db,authority.task_id);selection=authority._authority(acp)
        if acp.owner_epoch is not None or selection['grants']!=[grant]:raise ValueError('Authority not released/exactly selected')
        authority._payload(grant['payload'])
        wire=wire_rows((run/'wire-observations.json').read_bytes(),cp,authority.scope)
        authority._inherited_grant(db,cp,grant,wire)
        records=[dict(revision=r[0],event=r[1],payload=json.loads(r[2])) for r in db.execute(
            'SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',(authority.task_id,))]
        first=json.loads(db.execute('SELECT payload FROM history WHERE task_id=? AND revision=0',(cp.task_id,)).fetchone()[0])
    diagnostics=run/'executions'/cp.task_id
    if read(diagnostics/'grant.json')!=grant:raise ValueError('Selected diagnostic grant differs')
    initial={**{k:first[k] for k in ('prompt','max_attempts','metadata','state')},'task_id':cp.task_id,
             'revision':0,'owner_epoch':None,'operation':None,'requires_reconciliation':False}
    return {'selected':asdict(cp),'selected_initial':initial,'authority':asdict(acp),
            'authority_history':records,'authority_task_id':authority.task_id,
            'worker':read(diagnostics/f'result-{pid}.json'),
            'worker_result_sha256':sha(diagnostics/f'result-{pid}.json')}


def check_safe_wait(e):
    checked=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checked.append(name)
    old=e['sealed_before']['checkpoint'];after=e['sealed_after'];g=e['grant'];p=g['payload']
    new=e['selected'];initial=e['selected_initial'];w=e['worker'];marker=old['state'][SEAL]
    pair={'execution_id':p['successor_id'],'execution_generation':g['execution_generation']}
    check('immutable_wait_predecessor',e['sealed_before']==after)
    rows=after['history'];before=json.loads(rows[-2][2])['state'];unsealed=deepcopy(old['state']);unsealed.pop(SEAL)
    check('real_wait_seal',marker['schema']==WAIT and old['owner_epoch'] is None and old['operation'] is None
        and old['requires_reconciliation'] is False and old['state']['status']=='pending'
        and old['state']['phase']=='waiting_admission' and type(old['state']['pending_request']) is dict
        and old['revision']==marker['pre_seal_revision']+1 and rows[-2][0]==marker['pre_seal_revision']
        and before==unsealed and digest(before)==marker['pre_seal_state_sha256']
        and marker['pending_request_sha256']==digest(old['state']['pending_request'])
        and marker['native_history_sha256']==digest(old['state']['native_history'])
        and marker['deadline_clock']==CLOCK and marker['deadline_monotonic']==old['state']['deadline_monotonic']
        and marker['deadline_monotonic']<=marker['sealed_at_monotonic']
        and any(row['name']=='read_file' for row in old['state']['tools']))
    prefix=after['prefix'];requests=prefix['requests'];receipts=prefix['receipts']
    check('actual_sealed_control_prefix',marker['control_prefix_sha256']==digest({'requests':requests,'receipts':receipts})
        and marker['request_count']==len(requests) and marker['ack_count']==len(receipts)
        and prefix['pending_request_sha256']==marker['pending_request_sha256']
        and prefix['native_history_sha256']==marker['native_history_sha256']
        and [x['command'] for x in receipts]==['pause','resume']
        and all(x['outcome']=='applied' for x in receipts)
        and all(x['command']=='pause' for x in requests[len(receipts):])
        and e['gui_resume_ids']==[receipts[1]['request_id']])
    check('explicit_request_supersession',g['pending_request_disposition']=={
        'schema':'adaptive.pending-request-supersession.v1','mode':'rebuild_from_saved_conversation',
        'request_sha256':marker['pending_request_sha256']})
    check('one_exact_wait_grant',g['execution_generation']==1 and type(g['execution_generation']) is int
        and p['logical_task_id']==p['predecessor_id']==old['task_id'] and p['successor_id']!=old['task_id']
        and p['predecessor_revision']==old['revision'] and p['predecessor_seal_sha256']==digest(marker)
        and g['payload_sha256']==digest(p) and p['budget_s']==900 and g['deadline_clock']==CLOCK
        and type(g['authorized_at']) in (int,float) and type(g['deadline_monotonic']) in (int,float)
        and math.isfinite(g['authorized_at']) and math.isfinite(g['deadline_monotonic'])
        and g['deadline_monotonic']>g['authorized_at']
        and g['deadline_monotonic']==g['authorized_at']+900 and marker['sealed_at_monotonic']<=g['authorized_at']
        and g['predecessor_state_sha256']==digest(old['state']) and g['predecessor_history_sha256']==digest(rows)
        and g['release_proven_by_store'] is False)
    inherited=deepcopy(unsealed);inherited.pop(ACKS,None)
    inherited.update(phase='ready',pending_request=None,deadline_monotonic=g['deadline_monotonic'])
    inherited[NS]={**p['demand_identity'],'state':'paused','updated_at_utc':p['demand_identity']['arrived_at_utc'],
        'reason':'Explicit continuation selected; awaiting retained launch and fresh Resume'}
    metadata=deepcopy(old['metadata']);metadata[NS]=p['demand_identity']
    metadata[LINK]={'logical_task_id':old['task_id'],**pair,'command_id':p['command_id'],'payload_sha256':g['payload_sha256']}
    check('exact_selected_initial_projection',initial['state']==inherited and initial['metadata']==metadata
        and initial['revision']==0 and digest(inherited)==g['successor_initial_state_sha256']
        and digest(metadata)==g['successor_metadata_sha256'] and new['metadata']==metadata
        and new['prompt']==initial['prompt']==old['prompt'] and new['max_attempts']==initial['max_attempts']==old['max_attempts']==8
        and new['task_id']==initial['task_id']==p['successor_id'])
    before_wire=e['wire_before'];wire=e['wire_after'];n=len(before_wire)
    check('cumulative_wire_and_execution_calls',0<n<len(wire)<=8 and wire[:n]==before_wire
        and old['state']['requests']==n and new['state']['requests']==len(wire)
        and w['provider_calls']==len(wire)-n and after['worker']['provider_calls']==n
        and g['wire_prefix_count']==n and g['wire_prefix_sha256']==digest(before_wire)
        and g['wire_row_sha256']==[digest(row) for row in before_wire]
        and g['wire_body_sha256']==[row['body_sha256'] for row in before_wire]
        and g['wire_file_sha256']==e['wire_before_file_sha256'])
    check('cumulative_history_effects_and_limits',new['state']['session_id']==old['state']['session_id']
        and all(new['state'].get(k,[])[:len(old['state'].get(k,[]))]==old['state'].get(k,[])
                for k in ('messages','native_history','tools','feedback','admission_deferrals','validation_rejections'))
        and all(new['state'][k]>=old['state'][k] for k in ('attempts','requests','admission_attempts'))
        and new['state']['attempts']<=8 and new['state']['admission_attempts']<=32
        and e['effects_before']==[row for row in old['state']['tools'] if row['name']=='write_file' and row.get('reused') is False]
        and e['effects_after'][:len(e['effects_before'])]==e['effects_before']
        and e['native_history_after'][:len(old['state']['native_history'])]==old['state']['native_history'])
    oldw=after['worker'];proof=oldw['admission_wait_expiry']
    from adaptive_inference.desktop.hermes.service_stop import WAIT_RECEIPT_BINDINGS
    proofkeys={'schema','task_id','registration_id','pid','owner_epoch','revision','state_sha256','task_completed'}|set(WAIT_RECEIPT_BINDINGS)
    check('strict_old_worker_safe_outcome',oldw.get('passed') is False and oldw.get('completed') is False
        and oldw.get('controlled') is True and oldw.get('control_state')=='waiting_admission'
        and oldw.get('control_reason')=='admission_wait_budget_expired'
        and set(proof)==proofkeys and proof['schema']=='adaptive.cooperative-admission-wait-expiry.v1' and proof['task_completed'] is False
        and proof['task_id']==old['task_id'] and proof['pid']==e['lifetimes'][0]['pid']
        and proof['registration_id']==old['metadata'][NS]['registration_id']
        and proof['revision']==old['revision'] and proof['state_sha256']==digest(old['state'])
        and proof['owner_epoch']==marker['owner_epoch']==oldw['owner_epoch']
        and all(proof[k]==marker[k] for k in WAIT_RECEIPT_BINDINGS)
        and not any(k in oldw for k in ('error','error_type','error_chain_types','error_chain_private',
            'traceback_private','cleanup_error','cleanup_errors','expiry_finalization_failed','selected_execution')))
    check('selected_completed_exact_quality',new['state']['status']=='accepted' and new['state']['phase']=='accepted'
        and new['owner_epoch'] is None and new['operation'] is None and not new['requires_reconciliation']
        and SEAL not in new['state'] and new['state']['deadline_monotonic']==g['deadline_monotonic']
        and all(w.get(k) is True for k in ('passed','completed','resumed','continuation_cleanup_verified'))
        and w['selected_execution']=={**pair,'logical_task_id':old['task_id']}
        and all(x['model']==MODEL and x['quality']==QUALITY and x['context']==CONTEXT and x['sdk_revision']==SDK
                and x['fixture'] is False for x in (oldw,w))
        and w['original_prompt_sha256']==digest(old['prompt']))
    t=e['transition'];request=t['request'];release=t['release']
    check('genuine_one_click_continue',request['request_id']==p['command_id'] and request['execution_id']==old['task_id']
        and request['execution_generation']==0 and request['expected_task_revision']==old['revision']
        and request['session_id']==e['gui_binding']['session_id'] and p['host_generation']==e['gui_binding']['host_epoch']
        and all(t.get(k) is True for k in ('committed','started','launch_attempted','authorization_resolved')))
    check('old_exact_release_before_continue',release['worker_joined'] is True and release['exit_code']==6
        and release['outcome']=='admission_wait_budget_expired' and release['execution_id']==old['task_id']
        and digest(release)==p['release_evidence_sha256'] and release['native']['owner_lock_idle'] is True
        and release['native']['backend_port_free'] is True and release['native']['startup_barrier_held'] is True
        and all(release['native']['release'][k] is True for k in ('released','cleanup_confirmed','port_free')))
    controls=e['successor_controls'];suffix=g['payload_sha256'][:24]
    check('one_fresh_pause_and_derived_resume',len(controls)==2
        and [r['request_id'] for r in controls]==['continue-pause-'+suffix,'continue-resume-'+suffix]
        and [r['command'] for r in controls]==['pause','resume']
        and all(r['owner_acknowledged'] is True and r['outcome']=='applied' for r in controls))
    status=e['selection_status'];ready=e['readiness']
    check('exact_selected_status_and_ready',{k:status[k] for k in pair}==pair and status['task_revision']==0
        and status['task_status']=='pending' and status['demand']=='paused'
        and status['continuation']['request_id']==p['command_id'] and status['continuation']['phase'] in ('selected','preparing')
        and ready['value']['selected_execution']==pair and ready['value']['ready'] is True
        and ready['value']['model']==MODEL and ready['value']['quality']==QUALITY
        and ready['value']['gateway_instance']==e['gateway_instance'] and ready['deadline_clock']==CLOCK
        and ready['started_qpc']<=ready['finished_qpc']<ready['readiness_deadline_monotonic']<=g['deadline_monotonic']
        and ready['finished_qpc']-ready['started_qpc']<=240 and ready['gui_binding']==e['gui_binding']
        and ready['boot']['task_id']==p['successor_id'] and ready['boot']['deadline_clock']==CLOCK
        and ready['boot']['deadline_monotonic']==g['deadline_monotonic']
        and ready['boot']['registration_id']==p['demand_identity']['registration_id'])
    a=e['authority'];selection=a['state'][AUTH]
    check('one_released_authority_grant',selection['grants']==[g] and selection['selected_execution']==p['successor_id']
        and selection['execution_generation']==1 and a['owner_epoch'] is None and a['operation'] is None
        and not a['requires_reconciliation'])
    starts=[r for r in e['authority_history'] if r['event']=='operation_started' and r['payload']['operation'].get('details')=={
        'schema':'adaptive.selected-worker-lifetime.v1',**pair,'payload_sha256':g['payload_sha256']}]
    check('one_selected_lifetime',len(starts)==1)
    operation=starts[0]['payload']['operation']
    ends=[r for r in e['authority_history'] if r['event']=='operation_completed' and r['payload']['event_data']['operation']==operation]
    check('one_completed_lifetime',len(ends)==1 and ends[0]['revision']>starts[0]['revision'])
    final=ends[0]['payload']['event_data']['result']
    check('exact_selected_result_binding',operation['kind']=='effect' and final['execution_id']==p['successor_id']
        and final['returncode']==0 and final['result_sha256']==e['worker_result_sha256']
        and final['physical_child_exit_proven'] is False and final['cleanup']['resources_closed'] is True
        and final['cleanup']['state_sha256']==digest(new['state'])
        and final['cleanup']['native_history_sha256']==digest(new['state']['native_history']))
    lives=e['lifetimes']
    check('two_exact_retained_worker_joins',len(lives)==2 and [r['exit_code'] for r in lives]==[6,0]
        and all(r['joined'] is True and r['containing_job_verified'] is True and r['creation_time_100ns']>0 for r in lives)
        and (lives[0]['pid'],lives[0]['creation_time_100ns'])!=(lives[1]['pid'],lives[1]['creation_time_100ns'])
        and lives[0]['pid']==release['worker_pid'] and lives[1]['pid']==t['retained_child_identity']['pid']
        and lives[1]['creation_time_100ns']==t['retained_child_identity']['creation_time_100ns'])
    return checked
