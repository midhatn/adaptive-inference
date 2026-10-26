# SPDX-License-Identifier: Apache-2.0
"""Pure new Continue predicates; installed proof also requires terminal readers."""
from copy import deepcopy
import hashlib
import json
import math

NS='adaptive_inference.demand.v1'
SEAL='adaptive_inference.execution_outcome.v1'
ACKS='adaptive_inference.control_acks.v1'
AUTH='adaptive_inference.continuation_authority.v1'
LINK='adaptive_inference.execution_authorization.v1'
CLOCK='windows-qpc-seconds-v1'
MODEL='qwen3.8-flash-next-iq3_s-adaptive-media-beta'
QUALITY={'max_tokens':10923,'reasoning_effort':'high','reasoning_budget_tokens':8192,
         'experimental_speed_projection':False,'strata_tune':{'pcie_frac':.37}}
CONTEXT={'context_length':65536,'threshold':.8,'threshold_tokens':46421,'reserved_output':10923,'max_tokens':10923}
REPORT={'rows':4,'units':17,'total_cents':4350,'by_item':{'folder':1100,'notebook':2250,'pen':1000}}


def digest(value):
    raw=value if isinstance(value,bytes) else json.dumps(value,sort_keys=True,ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def require(value,message):
    if value is not True: raise AssertionError(message)


def check_continuation(e):
    """No synthetic value may replace the reader's actual DB/file/handle inputs."""
    checked=[]
    def check(name,condition):
        require(bool(condition),name);checked.append(name)
    old=e['sealed_before'];now=e['sealed_after'];paused=e['paused']
    g=e['grant'];p=g['payload'];new=e['selected'];initial=e['selected_initial'];w=e['worker']
    pair={'execution_id':p['successor_id'],'execution_generation':g['execution_generation']}
    check('immutable_predecessor',old==now and e['history_before']==e['history_after'])
    marker=old['state'][SEAL];unsealed=deepcopy(old['state']);del unsealed[SEAL]
    check('real_predecessor_seal',unsealed==paused['state'] and old['revision']==paused['revision']+1
          and marker['pre_seal_revision']==paused['revision']
          and marker['pre_seal_state_sha256']==digest(paused['state'])
          and marker['deadline_clock']==CLOCK and marker['deadline_monotonic']==old['state']['deadline_monotonic']
          and marker['pause_observed_at_monotonic']<marker['deadline_monotonic']<=marker['sealed_at_monotonic'])
    check('one_exact_grant',type(g['execution_generation']) is int and g['execution_generation']==1
          and p['logical_task_id']==old['task_id'] and p['predecessor_id']==old['task_id']
          and p['predecessor_revision']==old['revision'] and p['predecessor_seal_sha256']==digest(marker)
          and p['successor_id']!=old['task_id'] and g['payload_sha256']==digest(p)
          and p['budget_s']==900 and g['deadline_monotonic']-g['authorized_at']==900
          and marker['sealed_at_monotonic']<=g['authorized_at'] and g['deadline_clock']==CLOCK
          and g['predecessor_state_sha256']==digest(old['state'])
          and g['predecessor_history_sha256']==digest(e['history_before'])
          and g['release_proven_by_store'] is False)
    a=e['authority'];selection=a['state'][AUTH]
    check('authority_selected_once',selection['grants']==[g] and selection['execution_generation']==1
          and selection['selected_execution']==p['successor_id']
          and a['owner_epoch'] is None and a['operation'] is None and not a['requires_reconciliation'])
    inherited=deepcopy(old['state']);inherited.pop(SEAL);inherited.pop(ACKS,None)
    inherited['deadline_monotonic']=g['deadline_monotonic'];inherited[NS]=initial['state'][NS]
    check('inherited_creation_exact',initial['state']==inherited
          and digest(initial['state'])==g['successor_initial_state_sha256']
          and digest(initial['metadata'])==g['successor_metadata_sha256']
          and initial['state'][NS]['state']=='paused' and initial['state']['requests']==old['state']['requests']
          and new['task_id']==initial['task_id']==p['successor_id']
          and new['prompt']==initial['prompt']==old['prompt']
          and new['max_attempts']==initial['max_attempts']==old['max_attempts']==8)
    metadata=deepcopy(old['metadata']);metadata[NS]=p['demand_identity']
    metadata[LINK]={'logical_task_id':old['task_id'],**pair,'command_id':p['command_id'],'payload_sha256':g['payload_sha256']}
    check('inherited_metadata_exact',new['metadata']==initial['metadata']==metadata)
    check('task_accepted',new['state']['status']=='accepted' and new['state']['phase']=='accepted'
          and new['owner_epoch'] is None and new['operation'] is None and not new['requires_reconciliation']
          and SEAL not in new['state'] and new['state']['deadline_monotonic']==g['deadline_monotonic']
          and all(w.get(k) is True for k in ('passed','completed','resumed','continuation_cleanup_verified'))
          and w['selected_execution']=={**pair,'logical_task_id':old['task_id']} and w['fixture'] is False
          and not w.get('cleanup_errors') and w['original_prompt_sha256']==digest(old['prompt']))
    before=e['wire_before'];after=e['wire_after'];n=len(before)
    check('cumulative_wire_no_reset',0<n<len(after)<=8 and after[:n]==before
          and old['state']['requests']==n and new['state']['requests']==len(after)
          and w['provider_calls']==len(after)-n and g['wire_prefix_count']==n
          and g['wire_prefix_sha256']==digest(before) and g['wire_row_sha256']==[digest(x) for x in before]
          and g['wire_body_sha256']==[x['body_sha256'] for x in before])
    check('quality_and_completed_requests',w['model']==MODEL and w['quality']==QUALITY and w['context']==CONTEXT
          and all(x['model']==MODEL and x['quality']==QUALITY and x['class']=='normal'
                  and x['method']=='POST' and x['url']=='http://127.0.0.1:18100/v1/chat/completions'
                  and type(x['finished_at']) in (int,float) and math.isfinite(x['finished_at'])
                  and x['finished_at']>=x['started_at'] for x in after))
    check('counters_and_feedback_preserved',all(new['state'][k]>=old['state'][k] for k in ('attempts','admission_attempts'))
          and new['state']['attempts']<=8 and new['state']['admission_attempts']<=32
          and new['state'].get('validation_rejections',[])[:len(old['state'].get('validation_rejections',[]))]==old['state'].get('validation_rejections',[])
          and new['state']['native_history'][:len(old['state']['native_history'])]==old['state']['native_history']
          and new['state']['session_id']==old['state']['session_id'])
    physical=[x for x in new['state']['tools'] if x['name']=='write_file' and x.get('reused') is False]
    check('one_unchanged_physical_effect',len(e['effects'])==len(physical)==1 and e['effects']==physical
          and e['effects_before_sha256']==e['effects_after_sha256']
          and e['effects'][0]['artifact_sha256']==e['report_sha256']==w['artifacts']['report.json']
          and e['report']==w['report']==REPORT)
    check('tool_history_exact_once',all(sum(m.get('role')=='tool' and m.get('tool_call_id')==t['tool_call_id']
          and m.get('content')==t['result'] for m in new['state']['native_history'])==1 for t in new['state']['tools']))
    transition=e['transition'];request=transition['request']
    check('authenticated_one_click_selection',request['request_id']==p['command_id']
          and request['execution_id']==old['task_id'] and request['execution_generation']==0
          and request['expected_task_revision']==old['revision']
          and request['session_id']==e['gui_binding']['session_id']
          and p['host_generation']==e['gui_binding']['host_epoch']
          and all(transition.get(k) is True for k in ('committed','started','launch_attempted','authorization_resolved')))
    check('predecessor_release_bound',transition['release']['worker_joined'] is True
          and transition['release']['exit_code']==5 and transition['release']['outcome']=='paused_budget_expired'
          and transition['release']['execution_id']==old['task_id']
          and digest(transition['release'])==p['release_evidence_sha256'])
    controls=e['successor_controls'];suffix=g['payload_sha256'][:24]
    check('fresh_pause_then_derived_resume',len(controls)==2
          and [x['request_id'] for x in controls]==['continue-pause-'+suffix,'continue-resume-'+suffix]
          and [x['command'] for x in controls]==['pause','resume']
          and all(x['outcome']=='applied' and x['owner_acknowledged'] is True for x in controls)
          and controls[0]['sequence']<controls[1]['sequence'])
    status=e['selection_status']
    check('actual_selected_status',{k:status[k] for k in pair}==pair
          and status['task_revision']==initial['revision'] and status['task_status']=='pending'
          and status['demand']=='paused' and status['continuation']['request_id']==p['command_id']
          and status['continuation']['phase'] in ('selected','preparing'))
    ready=e['readiness']
    check('selected_readiness_exact',ready['value']['selected_execution']==pair and ready['value']['ready'] is True
          and ready['value']['model']==MODEL and ready['value']['quality']==QUALITY
          and ready['value']['gateway_instance']==e['gateway_instance']
          and ready['deadline_clock']==CLOCK and ready['started_qpc']<=ready['finished_qpc']<g['deadline_monotonic']
          and ready['finished_qpc']-ready['started_qpc']<=240
          and ready['finished_qpc']<ready['readiness_deadline_monotonic']<=g['deadline_monotonic']
          and ready['gui_binding']==e['gui_binding']
          and ready['boot']['task_id']==p['successor_id'] and ready['boot']['deadline_monotonic']==g['deadline_monotonic']
          and ready['boot']['deadline_clock']==CLOCK and ready['boot']['registration_id']==p['demand_identity']['registration_id'])
    starts=[x for x in e['authority_history'] if x['event']=='operation_started' and
            x['payload']['operation'].get('details')=={'schema':'adaptive.selected-worker-lifetime.v1',
            **pair,'payload_sha256':g['payload_sha256']}]
    check('one_selected_worker_lifetime',len(starts)==1)
    operation=starts[0]['payload']['operation']
    ends=[x for x in e['authority_history'] if x['event']=='operation_completed'
          and x['payload']['event_data']['operation']==operation]
    check('one_lifetime_completion',len(ends)==1 and ends[0]['revision']>starts[0]['revision'])
    proof=ends[0]['payload']['event_data']['result']
    check('completed_authority_binds_result',operation['kind']=='effect' and proof['execution_id']==p['successor_id']
          and proof['returncode']==0 and proof['result_sha256']==e['worker_result_sha256']
          and proof['physical_child_exit_proven'] is False and proof['cleanup']['resources_closed'] is True
          and proof['cleanup']['state_sha256']==digest(new['state'])
          and proof['cleanup']['native_history_sha256']==digest(new['state']['native_history']))
    life=e['lifetimes']
    check('two_actual_retained_joins',len(life)==2
          and (life[0]['pid'],life[0]['creation_time_100ns'])!=(life[1]['pid'],life[1]['creation_time_100ns'])
          and all(type(x['creation_time_100ns']) is int and x['creation_time_100ns']>0 for x in life)
          and [x['exit_code'] for x in life]==[5,0] and all(x['joined'] is True for x in life)
          and life[0]['pid']==transition['release']['worker_pid']
          and life[1]['pid']==transition['retained_child_identity']['pid']
          and life[1]['creation_time_100ns']==transition['retained_child_identity']['creation_time_100ns']
          and transition['retained_child_identity']['containing_job_verified'] is True)
    check('normal_final_stop',e['manual_stop_observed'] is True and e['stop_confirmed'] is True
          and e['lifecycle']=={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}
          and e['retained_obligations_joined'] is True and not e['joined_obligation_errors'])
    return checked
