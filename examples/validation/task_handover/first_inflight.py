# SPDX-License-Identifier: Apache-2.0
"""Additional pure terminal predicates; never replace the retained recovery audit.

Native-to-pending projection is source-backed semantic lineage, not reconstruction
of raw assistant JSON. Hermes MIT source pins are recorded in source-pins.json.
"""
from copy import deepcopy
from datetime import datetime
import base64,hashlib,json,math,re
CLOCK='windows-qpc-seconds-v1'
SEAL='adaptive_inference.execution_outcome.v1'
def digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def require(condition,name):
    if condition is not True:raise ValueError(name)
def time_value(v):return type(v) in (int,float) and math.isfinite(v) and v>0
def bracket(row,before,after):
    require(row.get('deadline_clock')==CLOCK and time_value(row.get(before)) and time_value(row.get(after)) and row[before]<=row[after],'invalid_qpc_bracket')
def wall_bracket(row):
    a=datetime.fromisoformat(row['utc_before']);b=datetime.fromisoformat(row['utc_after'])
    require(a.tzinfo is not None and b.tzinfo is not None and a<=b,'invalid_wall_bracket')
def integer(v):return type(v) is int and v>=0
def hex64(v):return type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None

def check_capture(capture,ui,expected):
    require(capture.get('schema')=='private.case09.pre-resume-ui-binding.v1','capture_schema')
    bracket(capture,'capture_qpc_before','capture_qpc_after')
    observed=capture['observation'];bracket(observed,'qpc_before','qpc_after');wall_bracket(observed)
    raw=base64.b64decode(capture['phase_raw_base64'],validate=True)
    require(digest(raw)==capture['phase_sha256'],'capture_raw_hash')
    phase=json.loads(raw)
    require(set(phase)=={'phase','qpc','deadline_clock','gui_binding'} and phase['phase']=='inventory_paused_ready_for_resume' and phase['deadline_clock']==CLOCK,'capture_phase')
    require(phase['gui_binding']==expected==ui['window_a'],'capture_exact_host_binding')
    require(all(type(expected.get(k)) is int and expected[k]>0 and observed[k]==expected[k] and type(observed[k]) is int for k in ('hwnd','pid')),'capture_observed_window')
    require(type(observed.get('title')) is str and bool(observed['title']) and type(observed.get('note')) is str and bool(observed['note']),'capture_actual_observation')
    require(time_value(phase['qpc']) and phase['qpc']<=capture['capture_qpc_before']<=capture['capture_qpc_after']<ui['resume_a_qpc_before'] and observed['qpc_after']<=capture['capture_qpc_after'] and observed['qpc_after']<ui['resume_a_qpc_before'],'capture_before_resume')
    return phase

def check_onset(trace,ui,activity,capture,instance,binding,seal_qpc):
    check_capture(capture,ui,binding)
    require(activity.get('schema')=='private.case09.real-foreground.v1' and activity.get('deadline_clock')==CLOCK,'activity_schema')
    doc=activity['document'];actions=activity['actions'];prepared=activity['prepared_observation']
    require(all(type(doc.get(k)) is int and doc[k]>0 for k in ('pid','hwnd')) and doc['hwnd']!=binding['hwnd'],'different_real_document_window')
    require(all(type(doc.get(k)) is str and bool(doc[k]) for k in ('title','path')),'document_identity')
    bracket(prepared,'qpc_before','qpc_after');wall_bracket(prepared)
    require(type(prepared.get('note')) is str and bool(prepared['note']) and prepared['qpc_after']<ui['resume_a_qpc_before'],'document_prepared_before_resume')
    require(type(actions) is list and len(actions)>0,'actual_foreground_actions')
    for a in actions:
        bracket(a,'qpc_before','qpc_after');wall_bracket(a)
        require(all(a.get(k)==doc[k] and type(a[k]) is int for k in ('pid','hwnd')),'activity_window_changed')
        require(all(type(a.get(k)) is str and bool(a[k]) for k in ('observed_before','action','observed_after')),'missing_action_and_refresh')
    require(all(a['qpc_after']<b['qpc_before'] for a,b in zip(actions,actions[1:])),'actual_action_log_order')
    first=actions[0];require(ui['resume_a_qpc_after']<first['qpc_before']<seal_qpc,'foreground_after_resume')
    # Retain and validate the full actual log. An action straddling or following
    # the seal cannot prove input before it; only the completed prefix can.
    preseal=[a for a in actions if a['qpc_after']<=seal_qpc]
    require(bool(preseal) and actions[:len(preseal)]==preseal and all(b['qpc_after']-a['qpc_before']<60 for a,b in zip(preseal,preseal[1:])) and seal_qpc-preseal[-1]['qpc_before']<60,'real_activity_hold_gap')
    good=[];last_end=0
    for index,row in enumerate(trace):
        bracket(row,'reader_before_deadline_clock','reader_after_deadline_clock')
        lo,hi=row['reader_before_deadline_clock'],row['reader_after_deadline_clock']
        require(last_end<=lo,'trace_clock_order');last_end=hi
        if 'gateway_status' not in row or 'observation_error' in row:
            require(not (ui['resume_a_qpc_after']<=lo<seal_qpc),'ambiguous_active_interval');continue
        status=row['gateway_status'];s=status['scheduler'];r=status['resources']
        require(status.get('service')=='adaptive-inference' and status.get('instance')==instance,'gateway_identity')
        require(type(s.get('active')) is bool and all(integer(s.get(k)) for k in ('completed','pending')) and type(r.get('admission_allowed')) is bool and 'fault' in r and type(r.get('foreground_reason')) is str and type(r.get('handoff_state')) is str,'strict_status_types')
        if ui['resume_a_qpc_after']<=lo<seal_qpc:
            require(s.get('backend_completion_uncertain') is False and s.get('closing') is False and r.get('fault') is None,'uncertain_or_faulted_interval')
        good.append((index,row))
    def active0(row):
        s=row['gateway_status']['scheduler'];return s['active'] is True and s['completed']==0 and s['pending']==0 and s.get('backend_completion_uncertain') is False and s.get('closing') is False
    before=[(i,r) for i,r in good if ui['resume_a_qpc_after']<=r['reader_before_deadline_clock'] and r['reader_after_deadline_clock']<first['qpc_before'] and active0(r)]
    after=[(i,r) for i,r in good if first['qpc_after']<r['reader_before_deadline_clock']<seal_qpc and active0(r)]
    require(bool(before) and bool(after),'missed_first_inflight_overlap')
    resource_before=before[-1][1]['gateway_status']['resources']
    require(resource_before['admission_allowed'] is True and resource_before['handoff_state']=='ready' and resource_before['fault'] is None,'pre_action_admission_must_be_open')
    drain=[(i,r) for i,r in after if r['gateway_status']['resources'].get('admission_allowed') is False and r['gateway_status']['resources'].get('foreground_reason')=='foreground_activity' and r['gateway_status']['resources'].get('handoff_state')=='draining']
    require(bool(drain),'missing_foreground_draining_overlap')
    require(all(active0(row) and row['gateway_status']['resources']['fault'] is None for i,row in good if before[-1][0]<=i<=drain[0][0]),'intervening_completion_or_replacement')
    start=drain[0][1]['reader_after_deadline_clock'];park=[];completed_seen=False
    for i,row in good:
        lo=row['reader_before_deadline_clock']
        if not start<=lo<seal_qpc:continue
        s=row['gateway_status']['scheduler'];r=row['gateway_status']['resources']
        require(s['pending']==0 and s['completed'] in (0,1) and r['admission_allowed'] is False and r.get('foreground_reason')=='foreground_activity','hold_not_preserved')
        if s['completed']==1:
            require(s['active'] is False,'second_dispatch_during_hold');completed_seen=True
            if r.get('handoff_state')=='parked':park.append((i,row))
        else:require(not completed_seen and s['active'] is True,'first_request_disappeared_or_counter_regressed')
    require(bool(park),'missing_drained_parked_observation')
    return {'before_index':before[-1][0],'after_index':after[0][0],'draining_index':drain[0][0],'parked_index':park[0][0],'full_action_count':len(actions),'preseal_action_count':len(preseal),'claim':'same first admitted cycle by single-owner counter invariant; not GPU execution or preemption'}

def check_lineage(recovery,logical,result,input_name,input_bytes):
    old=recovery['sealed_after'];cp=old['checkpoint'];state=cp['state'];wire=recovery['wire_before'];history=state['native_history'];tools=state['tools']
    require(logical['state']['native_history']==[] and logical['state']['tools']==[] and type(logical['state']['requests']) is int and logical['state']['requests']==0 and logical['state']['messages']==[{'role':'user','content':logical['prompt']}],'original_empty_native_setup')
    require(cp['task_id']==logical['task_id'] and cp['prompt']==logical['prompt'] and state['session_id']==logical['state']['session_id'],'same_original_task_session')
    require(result.get('fixture') is False and old['worker'].get('fixture') is False,'real_original_worker')
    require(type(state['requests']) is int and state['requests']==1 and type(old['worker']['provider_calls']) is int and old['worker']['provider_calls']==1 and len(wire)==1,'exact_one_original_wire')
    w=wire[0];require(w.get('finish_reason')=='tool_calls' and all(hex64(w.get(k)) for k in ('body_sha256','messages_sha256','tools_sha256','response_sha256','assistant_sha256')),'first_wire_complete_hashes')
    require(type(w.get('gateway_request_id')) is str and bool(w['gateway_request_id']) and time_value(w.get('started_at')) and time_value(w.get('finished_at')) and w['started_at']<=w['finished_at'],'first_wire_identity')
    gh=result['gateway_history'];require(len(gh)>0 and gh[0]['request_id']==w['gateway_request_id'] and type(gh[0]['status']) is int and gh[0]['status']==200 and gh[0].get('backend_completion_uncertain') is False,'first_gateway_wire_lineage')
    require(len(history)==3 and [x.get('role') for x in history]==['user','assistant','tool'] and history[0]['content']==logical['prompt'],'unique_first_native_assistant')
    assistant,toolrow=history[1:];calls=assistant.get('tool_calls')
    require(type(calls) is list and len(calls)==1 and assistant.get('finish_reason')=='tool_calls','unique_native_read_intent')
    call=calls[0];callid=call.get('id');args={'path':input_name}
    require(type(callid) is str and bool(callid) and call.get('type')=='function' and call['function'].get('name')=='read_file' and json.loads(call['function']['arguments'])==args,'exact_read_call')
    require(len(tools)==1 and tools[0].get('name')=='read_file' and tools[0].get('args')==args and tools[0].get('tool_call_id')==callid and tools[0].get('session_id')==state['session_id'] and tools[0].get('reused') is False,'one_real_read_receipt')
    t=tools[0];parsed=json.loads(t['result']);expected='\n'.join(str(n)+'|'+line for n,line in enumerate(input_bytes.decode('utf-8').splitlines(),1))
    require(parsed.get('content')==expected and type(parsed.get('file_size')) is int and parsed['file_size']==len(input_bytes) and type(parsed.get('total_lines')) is int and parsed['total_lines']==len(input_bytes.decode('utf-8').splitlines()) and all(parsed.get(k) is False for k in ('truncated','is_binary','is_image','not_found')) and not parsed.get('error'),'complete_actual_input_read')
    require(toolrow.get('content')==t['result'] and toolrow.get('tool_call_id')==callid and toolrow.get('tool_name')=='read_file','exact_native_result')
    starts=[];ends=[]
    for rev,event,payload in old['history']:
        p=json.loads(payload)
        if event=='operation_started':starts.append((rev,p['operation'],p['state']))
        elif event=='operation_completed':ends.append((rev,p['event_data']))
    require(len(starts)==len(ends)==2 and [x[1]['kind'] for x in starts]==['generation','validation'],'one_generation_one_read_operation')
    gen,readop=starts;gendone,readdone=ends
    require(gen[0]<gendone[0]<readop[0]<readdone[0] and gendone[1]['operation']==gen[1] and gendone[1]['result']=={'provider_returned':True} and readdone[1]['operation']==readop[1] and readdone[1]['result']==t,'exact_completed_operation_order')
    initial=gen[2]['pending_request']
    require(gen[1]['details']['pure_provider_request'] is True and gen[1]['details']['request_sha256']==digest(initial) and digest(initial['messages'])==w['messages_sha256'] and digest(initial['tools'])==w['tools_sha256'],'initial_request_to_wire_projection')
    require(type(gen[2]['requests']) is int and gen[2]['requests']==0 and gen[2]['tools']==[] and [x.get('role') for x in gen[2]['native_history']]==['user'] and gen[2]['native_history'][0]['content']==logical['prompt'],'no_prior_native_generation')
    require(readop[1]['id']==t['operation_id'] and readop[1]['details']=={k:t[k] for k in ('name','tool_call_id','args','fingerprint','session_id')},'read_operation_receipt_identity')
    pending=state['pending_request'];messages=pending['messages']
    require(len(messages)==4 and [x.get('role') for x in messages]==['system','user','assistant','tool'] and messages[:2]==initial['messages'],'pending_preserves_original_request_context')
    # Pinned Hermes turn_context copies reasoning and removes persistence-only
    # metadata; reasoning_params strips exactly call_id/response_item_id here.
    # This is the native->saved-request semantic projection, never raw response.
    require(set(assistant)<= {'role','content','reasoning','reasoning_content','finish_reason','tool_calls','timestamp','_db_persisted','_row_id','message_uid','_tool_call_uids'},'unsupported_native_assistant_carrier')
    require(set(call)<= {'id','type','function','call_id','response_item_id'} and call.get('call_id',callid)==callid,'unsupported_native_call_carrier')
    projected={k:deepcopy(assistant[k]) for k in ('role','content','tool_calls','reasoning','reasoning_content') if k in assistant}
    projected['tool_calls']=[{k:deepcopy(v) for k,v in call.items() if k not in ('call_id','response_item_id')}]
    require(messages[2]==projected and messages[3]=={k:toolrow[k] for k in ('role','content','tool_call_id')},'pending_exact_native_read_projection')
    require({k:v for k,v in pending.items() if k!='messages'}=={k:v for k,v in initial.items() if k!='messages'} and digest(pending)!=digest(initial) and state[SEAL]['pending_request_sha256']==digest(pending),'undispatched_successor_preserves_options')
    require(recovery['effects_before']==[] and sum(x.get('name')=='read_file' for x in recovery['selected']['state']['tools'])==1,'no_preexpiry_write_or_replayed_read')
    return {'wire_request_id':w['gateway_request_id'],'wire_response_sha256':w['response_sha256'],'wire_assistant_sha256':w['assistant_sha256'],'native_history_sha256':digest(history),'pending_request_sha256':digest(pending),'read_operation_id':t['operation_id'],'claim':'source-backed causal lineage and exact native-to-pending projection; opaque raw response hashes, not raw/native byte equivalence'}
