# SPDX-License-Identifier: Apache-2.0
"""Synthetic predicate fixture only; never accepted live evidence.

Exact fixture function retained from the reviewed qualification tests.
"""
from copy import deepcopy
import json
# The test loader provides the exact adjacent checks module.
from continuation_export_checks import *

def fixture():
    effect={'name':'write_file','reused':False,'artifact_sha256':'a'*64,'tool_call_id':'tool1','result':'saved'}
    state={'status':'pending','phase':'ready','deadline_clock':CLOCK,'deadline_monotonic':1000.0,
        NS:{'state':'paused'},ACKS:{'receipts':[]},'requests':1,'attempts':1,'admission_attempts':1,
        'session_id':'same-session','native_history':[{'role':'tool','tool_call_id':'tool1','content':'saved'}],
        'tools':[effect]}
    paused={'task_id':'orders-report','prompt':'Original synthetic objective','max_attempts':8,'metadata':{'deadline_clock':CLOCK},
        'revision':1,'state':state,'operation':None,'requires_reconciliation':False,'owner_epoch':'old-owner'}
    marker={'deadline_clock':CLOCK,'deadline_monotonic':1000.0,'pause_observed_at_monotonic':500.0,
        'sealed_at_monotonic':1000.1,'pre_seal_revision':1,'pre_seal_state_sha256':digest(state)}
    old=deepcopy(paused);old['state'][SEAL]=marker;old.update(revision=2,owner_epoch=None)
    history=[[i,'event',json.dumps({'state':s})] for i,s in enumerate(({},state,old['state']))]
    wire={'model':MODEL,'quality':QUALITY,'class':'normal','method':'POST',
        'url':'http://127.0.0.1:18100/v1/chat/completions','started_at':10.0,'finished_at':11.0,'body_sha256':'b'*64}
    release={'worker_joined':True,'worker_pid':11,'exit_code':5,'outcome':'paused_budget_expired','execution_id':'orders-report'}
    payload={'logical_task_id':'orders-report','predecessor_id':'orders-report','predecessor_revision':2,
        'predecessor_seal_sha256':digest(marker),'successor_id':'orders-report.next','budget_s':900,
        'command_id':'continue1','host_generation':'same-host','release_evidence_sha256':digest(release),
        'demand_identity':{'registration_id':'new','task_id':'orders-report.next','owner_id':'owner','arrived_at_utc':'2026-10-26T00:00:00Z'}}
    pair={'execution_id':payload['successor_id'],'execution_generation':1}
    g={'payload':payload,'payload_sha256':digest(payload),'execution_generation':1,'authorized_at':1002.0,
        'deadline_monotonic':1902.0,'deadline_clock':CLOCK,'predecessor_state_sha256':digest(old['state']),
        'predecessor_history_sha256':digest(history),'release_proven_by_store':False,'wire_prefix_count':1,
        'wire_prefix_sha256':digest([wire]),'wire_row_sha256':[digest(wire)],'wire_body_sha256':[wire['body_sha256']]}
    newstate=deepcopy(state);newstate.pop(ACKS);newstate['deadline_monotonic']=1902.0
    newmeta={**old['metadata'],NS:payload['demand_identity'],LINK:{'logical_task_id':'orders-report',**pair,
        'command_id':'continue1','payload_sha256':g['payload_sha256']}}
    initial={**deepcopy(old),'task_id':payload['successor_id'],'revision':0,'state':newstate,'metadata':newmeta}
    g['successor_initial_state_sha256']=digest(newstate);g['successor_metadata_sha256']=digest(newmeta)
    selected=deepcopy(initial);selected['state'].update(status='accepted',phase='accepted',requests=2,attempts=2,admission_attempts=2)
    selected['state']['native_history'].append({'role':'assistant','content':'Done'})
    worker={'passed':True,'completed':True,'resumed':True,'continuation_cleanup_verified':True,
        'selected_execution':{**pair,'logical_task_id':'orders-report'},'fixture':False,
        'original_prompt_sha256':digest(old['prompt']),'provider_calls':1,'model':MODEL,'quality':QUALITY,
        'context':CONTEXT,'report':REPORT,'artifacts':{'report.json':'a'*64}}
    authority={'state':{AUTH:{'grants':[g],'execution_generation':1,'selected_execution':payload['successor_id']}},
        'owner_epoch':None,'operation':None,'requires_reconciliation':False}
    operation={'kind':'effect','details':{'schema':'adaptive.selected-worker-lifetime.v1',**pair,'payload_sha256':g['payload_sha256']}}
    proof={'execution_id':payload['successor_id'],'returncode':0,'result_sha256':'c'*64,'physical_child_exit_proven':False,
        'cleanup':{'resources_closed':True,'state_sha256':digest(selected['state']),'native_history_sha256':digest(selected['state']['native_history'])}}
    ah=[{'revision':2,'event':'operation_started','payload':{'operation':operation}},
        {'revision':3,'event':'operation_completed','payload':{'event_data':{'operation':operation,'result':proof}}}]
    suffix=g['payload_sha256'][:24]
    controls=[{'request_id':'continue-'+action+'-'+suffix,'command':action,'sequence':i,
        'outcome':'applied','owner_acknowledged':True} for i,action in enumerate(('pause','resume'),1)]
    transition={'request':{'request_id':'continue1','execution_id':'orders-report','execution_generation':0,
        'expected_task_revision':2,'session_id':'same-ui'},'committed':True,'started':True,'launch_attempted':True,'authorization_resolved':True,
        'release':release,'retained_child_identity':{'pid':12,'creation_time_100ns':200,'containing_job_verified':True}}
    return {'sealed_before':old,'sealed_after':deepcopy(old),'paused':paused,'history_before':history,'history_after':deepcopy(history),
        'grant':g,'selected':selected,'selected_initial':initial,'worker':worker,'authority':authority,'authority_history':ah,
        'wire_before':[wire],'wire_after':[wire,{**wire,'body_sha256':'d'*64,'started_at':1100.0,'finished_at':1101.0}],
        'effects':[effect],'effects_before_sha256':'e'*64,'effects_after_sha256':'e'*64,'report':REPORT,'report_sha256':'a'*64,
        'transition':transition,'gui_binding':{'session_id':'same-ui','host_epoch':'same-host'},'successor_controls':controls,
        'selection_status':{**pair,'task_revision':0,'task_status':'pending','demand':'paused','continuation':{'request_id':'continue1','phase':'preparing'}},
        'readiness':{'value':{'selected_execution':pair,'ready':True,'model':MODEL,'quality':QUALITY,'gateway_instance':'gateway1'},
            'deadline_clock':CLOCK,'started_qpc':1003.0,'finished_qpc':1004.0,
            'readiness_deadline_monotonic':1243.0,'gui_binding':{'session_id':'same-ui','host_epoch':'same-host'},
            'boot':{'task_id':payload['successor_id'],'deadline_monotonic':1902.0,'deadline_clock':CLOCK,'registration_id':'new'}},'gateway_instance':'gateway1',
        'worker_result_sha256':'c'*64,'lifetimes':[{'pid':11,'creation_time_100ns':100,'exit_code':5,'joined':True},{'pid':12,'creation_time_100ns':200,'exit_code':0,'joined':True}],
        'manual_stop_observed':True,'stop_confirmed':True,'lifecycle':{'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None},
        'retained_obligations_joined':True,'joined_obligation_errors':[]}
