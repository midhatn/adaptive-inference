# SPDX-License-Identifier: Apache-2.0
"""Bounded data checks for the one inventory -> welcome qualification.

Production TaskSpec/worker verification remains authoritative. These checks add
an independently computed inventory oracle and explicit two-task boundaries.
"""
import csv
import hashlib
import io
import json
import math

MODEL = 'qwen3.8-flash-next-iq3_s-adaptive-media-beta'
QUALITY = {'max_tokens':10923,'reasoning_effort':'high','reasoning_budget_tokens':8192,
           'experimental_speed_projection':False,'strata_tune':{'pcie_frac':0.37}}
CONTEXT = {'context_length':65536,'threshold':.8,'threshold_tokens':46421,
           'reserved_output':10923,'max_tokens':10923}
SDK = '14e1e43a23761b369641208e204365cd6cb9399d'
NS = 'adaptive_inference.demand.v1'


def digest(value):
    if not isinstance(value,bytes):
        value=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()


def inventory_oracle(raw):
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
    result=[]
    for row in rows:
        if set(row)!={'item','on_hand','target','pack_size'}:raise ValueError('Inventory schema')
        have,target,pack=(int(row[key]) for key in ('on_hand','target','pack_size'))
        if min(have,target)<0 or pack<=0:raise ValueError('Inventory values')
        need=max(0,target-have);packs=(need+pack-1)//pack
        result.append({'item':row['item'],'packs':packs,'units':packs*pack})
    return {'reorder':result,'total_units':sum(row['units'] for row in result)}


def check_task(row, *, semantic, grant=None):
    cp,worker,plan=row['checkpoint'],row['worker'],row['plan']
    state=cp['state'];wire=row['wire'];effects=row['effects']
    inherited=0 if grant is None else grant['wire_prefix_count']
    if grant is not None and (cp['task_id']!=grant['payload']['successor_id'] or inherited<=0 or inherited>=len(wire)):
        raise ValueError('Selected task wire prefix differs')
    if (state['status']!='accepted' or cp['owner_epoch'] is not None or cp['operation'] is not None
            or cp['requires_reconciliation'] or state['pending_request'] is not None
            or not 0<len(wire)<=8 or len(wire)!=state['requests'] or worker['provider_calls']!=len(wire)-inherited
            or not 0<state['attempts']<=8 or not 0<=state['admission_attempts']<=32):
        raise ValueError('Task completion/counters not verified')
    if (worker.get('passed') is not True or worker.get('completed') is not True
            or worker.get('fixture') is not False or worker.get('cleanup_errors')
            or worker.get('context')!=CONTEXT or worker.get('model')!=MODEL
            or worker.get('quality')!=QUALITY or worker.get('sdk_revision')!=SDK
            or worker.get('semantic_validation')!=semantic):
        raise ValueError('Actual worker/quality/semantic scope differs')
    if (plan['max_requests']!=8 or plan['model']!=MODEL or plan['quality']!=QUALITY
            or plan['fixture'] is not False or plan['sdk_revision']!=SDK
            or cp['prompt']!=row['original']['prompt'] or cp['metadata']!=row['original']['metadata']
            or state['session_id']!=row['original']['state']['session_id']
            or worker['original_prompt_sha256']!=digest(cp['prompt'])):
        raise ValueError('Original prompt/plan/session changed')
    if any(x.get('model')!=MODEL or x.get('quality')!=QUALITY or x.get('class')!='normal'
           or not x.get('finished_at') or not x.get('gateway_request_id') for x in wire):
        raise ValueError('Wire quality or completion differs')
    if (len(effects)!=1 or effects[0]['name']!='write_file'
            or effects[0]['artifact_sha256']!=row['artifact_sha256']
            or worker['artifacts']!={row['artifact_name']:row['artifact_sha256']}
            or row['completion']['artifacts']!=worker['artifacts']
            or row['completion']['semantic_validation']!=semantic):
        raise ValueError('Create-only artifact evidence differs')
    controls=row['controls']
    if (len(controls)!=2 or [x['command'] for x in controls]!=['pause','resume']
            or any(x['owner_acknowledged'] is not True or x['outcome']!='applied' for x in controls)
            or (grant is None and row['gui_resume_ids']!=[controls[1]['request_id']])
            or (grant is not None and [x['request_id'] for x in controls]!=[
                'continue-pause-'+grant['payload_sha256'][:24], 'continue-resume-'+grant['payload_sha256'][:24]])):
        raise ValueError('Exactly one genuine GUI Resume required per task')
    life=row['lifetime']
    if life['exit_code']!=0 or life['joined'] is not True or life['containing_job_verified'] is not True:
        raise ValueError('Actual worker lifetime not joined')
    if row['native_history']!=state['native_history']:
        raise ValueError('Native stored history differs from checkpoint')


def check_handover(e):
    checks={}
    def check(name,condition):
        checks[name]=bool(condition)
        if not condition:raise AssertionError(name)
    a,b=e['tasks']
    recovery=e.get('safe_wait')
    if recovery is not None:
        from safe_wait import check_safe_wait
        for name in check_safe_wait(recovery):check(name,True)
        check('selected_A_exact_recovery_projection',a['checkpoint']==recovery['selected']
            and a['original']==recovery['selected_initial'] and a['worker']==recovery['worker']
            and a['worker_result_sha256']==recovery['worker_result_sha256'] and a['wire']==recovery['wire_after']
            and a['controls']==recovery['successor_controls'] and a['lifetime']==recovery['lifetimes'][1]
            and a['gui_binding']==recovery['gui_binding'])
    check_task(a,semantic='oracle_matched',grant=None if recovery is None else recovery['grant']);check('inventory_task_contract',True)
    check_task(b,semantic='not_checked');check('welcome_format_only_contract',True)
    check('independent_inventory_oracle',a['artifact']==inventory_oracle(e['inventory_input'].encode()))
    check('distinct_task_scopes',a['checkpoint']['task_id']!=b['checkpoint']['task_id']
        and a['checkpoint']['state']['session_id']!=b['checkpoint']['state']['session_id']
        and a['run']!=b['run'] and a['artifact_name']=='replenishment.json' and b['artifact_name']=='welcome.txt')
    check('original_A_preserved',e['a_before']==e['a_after'])
    transition=e['transition'];grant=transition['reservation'];payload=grant['payload']
    check('one_exact_task_selection',e['selection_revision']==1 and transition['phase']=='opened'
        and transition['resolved'] is True and transition['prepared'] is True
        and transition['started'] is True and transition['rebound'] is True
        and grant['selection_revision']==1 and payload['task_id']==b['checkpoint']['task_id']
        and payload['predecessor_execution_id']==a['checkpoint']['task_id']
        and payload['source']==e['selected_source'])
    release=transition['release']
    check('old_worker_and_native_released_before_selection',release['worker_joined'] is True
        and release['worker_pid']==a['lifetime']['pid'] and release['exit_code']==0
        and release['outcome']=='task_completed' and release['native']['owner_lock_idle'] is True
        and release['native']['backend_port_free'] is True and release['native']['startup_barrier_held'] is True
        and all(release['native']['release'].get(k) is True for k in ('released','cleanup_confirmed','port_free')))
    paused=transition['paused'];state=paused['checkpoint']['state']
    check('B_genuine_paused_bootstrap',paused['ack']['owner_acknowledged'] is True and paused['ack']['outcome']=='applied'
        and state[NS]['state']=='paused' and state['requests']==state['attempts']==state['admission_attempts']==0
        and state['tools']==state['native_history']==[] and state['pending_request'] is None
        and transition['ready']['paused_owner_acknowledged'] is True
        and transition['ready']['task_id']==b['checkpoint']['task_id'])
    ga,gb=a['gui_binding'],b['gui_binding']
    check('fresh_window_same_host',ga['host_epoch']==gb['host_epoch']==e['host_epoch']
        and ga['task_id']!=gb['task_id'] and ga['session_id']!=gb['session_id']
        and ga['pid']!=gb['pid'] and e['host_identity_before']==e['host_identity_after'])
    check('all_episodes_cleaned',len(e['episodes'])==2 and all(x['gui_cleanup']['closed']
        and x['gui_cleanup']['child_exit_observed'] and x['gui_cleanup']['child_exit_code']==0
        and x['gui_cleanup']['pending_pipe_operations']==0 and not x['gui_cleanup']['faults']
        and x['listener_cleanup']['clean_close'] and x['listener_cleanup']['resources_closed']
        and not x['listener_cleanup']['faults'] and x['transport_cleanup']['closed']
        and x['transport_cleanup']['stop_confirmed'] and not x['transport_cleanup']['faults']
        and all(x['transport_cleanup'][k]==0 for k in ('pending_mutations','unknown_mutations','handlers','pending_connections','stream_close_failures'))
        for x in e['episodes']))
    if recovery is None:
        check('all_retained_children_joined',len(e['retained_children'])==4
            and all(x['joined'] is True and x['exit_code']==0 for x in e['retained_children']))
    else:
        children=e['retained_children']
        check('all_exact_recovery_children_joined',[x['label'] for x in children]==
            ['prepare','worker','worker-continue-1','prepare-task-1','worker-task-1']
            and [x['exit_code'] for x in children]==[0,6,0,0,0]
            and all(x['joined'] is True and x['creation_time_100ns']>0 for x in children)
            and len({(x['pid'],x['creation_time_100ns']) for x in children})==5
            and children[1]['pid']==recovery['lifetimes'][0]['pid']
            and children[1]['creation_time_100ns']==recovery['lifetimes'][0]['creation_time_100ns']
            and children[2]['pid']==a['lifetime']['pid'] and children[2]['creation_time_100ns']==a['lifetime']['creation_time_100ns']
            and children[4]['pid']==b['lifetime']['pid'] and children[4]['creation_time_100ns']==b['lifetime']['creation_time_100ns'])
    check('admission_stopped_released',e['admission']['host_stopped'] is True and e['admission']['stop_fenced'] is False
        and e['admission_checkpoint']['owner_epoch'] is None and e['admission_checkpoint']['operation'] is None
        and not e['admission_checkpoint']['requires_reconciliation'])
    return checks
