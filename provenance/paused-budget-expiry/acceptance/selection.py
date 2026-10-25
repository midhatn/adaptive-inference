# SPDX-License-Identifier: Apache-2.0
"""Pure scoped predicates reused from the preserved expiry03 selection scaffold.

Only export.py binds these predicates to accepted terminal evidence. They do not
run an agent, create a result or modify historical acceptance helpers.
"""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

SELECTOR='provenance/desktop-control-intent/acceptance/export_acceptance.py'
SELECTOR_SHA='b2a319ad8d1880a1fa61224bea895e50734976f098a140962c2da91fa60c9ca1'
OUTCOME='adaptive_inference.execution_outcome.v1'
ACKS='adaptive_inference.control_acks.v1'
CLOCK_ID='windows-qpc-seconds-v1'
FAILED_AUDIT_SHA='eab60eea7a14df1faddb904782143b8e4d07a619fc8dae057e5611d03fc6d3f8'
FAILED_THREAD_AUDIT_SHA='6f8f1d41288517d00e1e8059d31f969efffadfa3afbdefd17d516c4a02b86f6e'


def helpers(repository):
    path=Path(repository)/SELECTOR
    if hashlib.sha256(path.read_bytes()).hexdigest()!=SELECTOR_SHA:
        raise ValueError('Retained-command selector changed')
    spec=importlib.util.spec_from_file_location('expiry_preserved_selector',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    prior,h=module.helpers(repository)
    return module,prior,h


def source_identity(h,identity,lineage,base):
    files=identity['files'];changes=lineage['modules'];same=lineage['unchanged_runtime']
    new=lineage['new_modules']
    h.need(type(files) is dict and len(files)==54 and set(files)==set(changes)|set(same)|set(new),
           'source_module_set_changed')
    h.need(len(changes)==7 and len(same)==45 and not set(changes)&set(same),'source_lineage_changed')
    h.exact(sorted(new),['desktop/hermes/pause_activity.py','execution_clock.py'],'new_modules_changed')
    h.need(not set(new)&(set(changes)|set(same)),'new_module_collides')
    previous=dict(base['unchanged_runtime'])
    previous.update({name:row['successor_sha256'] for name,row in base['modules'].items()})
    h.need(len(base['modules'])==10 and len(base['unchanged_runtime'])==42
           and set(previous)==set(changes)|set(same),'failed_predecessor_lineage_changed')
    for name,row in changes.items():
        h.exact(h.digest(row['predecessor_sha256']),h.digest(previous[name]),'predecessor_source_changed')
    for name,value in same.items():
        h.exact(h.digest(value),h.digest(previous[name]),'unchanged_predecessor_changed')
    for name,value in files.items():
        expected=changes[name]['successor_sha256'] if name in changes else same.get(name,new.get(name))
        h.exact(h.digest(value),h.digest(expected),'runtime_source_changed')
    return {'runtime_modules':54,'changed_existing_runtime_modules':7,
            'unchanged_existing_runtime_modules':45,'new_runtime_modules':2}


def thread_source_identity(h,identity,thread,lineage,base):
    """Add the exact thread repair to the unchanged clock/expiry lineage chain."""
    changes=thread['modules'];same=thread['unchanged_runtime'];files=identity['files']
    h.exact(thread.get('schema'),'adaptive.paused-budget-expiry.thread-successor.v1','thread_lineage_schema_changed')
    h.exact(thread.get('failed_predecessor_wheel_sha256'),
        '9ab7743de1f1f9696c19152bdde82c0d7b4da9d0880a42ac91d93348716f5eb6','thread_predecessor_wheel_changed')
    h.exact(thread.get('failed_predecessor_source_manifest_sha256'),
        '60bbb67b7e3d665922f84b33c33f90f9268d960211b2d6c0228404d417d392df','thread_predecessor_freeze_changed')
    h.need(type(files) is dict and len(files)==54 and set(files)==set(changes)|set(same),
           'thread_runtime_module_set_changed')
    h.need(len(changes)==5 and len(same)==49 and not set(changes)&set(same),'thread_delta_changed')
    h.exact(sorted(changes),['desktop/hermes/'+name for name in
        ('pause_activity.py','recovery.py','run_recovery.py','sdk_pins.py','service_stop.py')],
        'thread_changed_module_names_changed')
    previous=dict(same)
    previous.update({name:row['predecessor_sha256'] for name,row in changes.items()})
    earlier=source_identity(h,{'files':previous},lineage,base)
    for name,value in files.items():
        expected=changes[name]['successor_sha256'] if name in changes else same[name]
        h.exact(h.digest(value),h.digest(expected),'thread_runtime_source_changed')
    return {'runtime_modules':54,'changed_existing_runtime_modules':5,
            'unchanged_existing_runtime_modules':49,'new_runtime_modules':0,
            'clock_predecessor':earlier}


def cleanup(h,result):
    for key in ('clean_stop','qualification_case_passed','case_checks_and_cleanup_passed',
        'asyncio_teardown_completed','manual_stop_observed','owner_released',
        'retained_obligations_joined','full_handoff_ledger','expiry_case_checks_passed'):
        h.true(result.get(key),'cleanup_or_case_not_passed')
    h.exact(result.get('lifecycle'),{'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None},
            'lifecycle_not_verified')
    for key in ('primary_error','cleanup_error','cooperative_diagnostic_error'):
        h.exact(result.get(key),None,'case_fault')
    h.need(not result.get('joined_obligation_errors'),'unjoined_obligation')
    gui=result['gui_cleanup']
    for key in ('closed','session_revoked','pipe_threads_joined','pipe_handles_closed',
        'process_handle_closed','verifier_handle_closed','child_exit_observed'):
        h.true(gui.get(key),'gui_cleanup_failed')
    for key,value in (('child_exit_code',0),('pending_pipe_operations',0),('faults',[])):
        h.exact(gui.get(key),value,'gui_cleanup_failed')
    listener=result['listener_cleanup'];h.true(listener.get('clean_close'),'listener_not_closed')
    for key in ('owned_connection_pending','setup_pending','handler_pending'):
        h.exact(listener.get(key),False,'listener_pending')
    h.exact(listener.get('faults'),[],'listener_fault')
    transport=result['transport_cleanup']
    for key in ('closed','stop_requested','stop_confirmed'):h.true(transport.get(key),'transport_not_closed')
    for key in ('pending_mutations','unknown_mutations','handlers','pending_connections','stream_close_failures'):
        h.exact(transport.get(key),0,'transport_not_clean')
    h.exact(transport.get('faults'),[],'transport_fault')
    h.true(result['cleanup'].get('closed'),'native_not_closed')
    for key in ('primary_error','cleanup_error','controller_fault'):
        h.exact(result['cleanup'].get(key),None,'native_fault')
    return {'worker_joined':True,'gui_closed':True,'native_closed':True,
            'listener_closed':True,'transport_closed':True,'uncertainty':False}


def expiry_state(h,result,worker,paused,terminal,observation):
    """Cross-check selected terminal files; independent SQLite audit still required."""
    h.quality(result);h.quality(worker)
    for key,value in (('case','gui-iq3s-installed-paused-budget-expiry'),('fixture',False),
        ('live_M2_milestone_claimed',False),('execution_expired',True),('task_completed',False),
        ('worker_exit_code',5),('worker_outcome','paused_budget_expired'),
        ('worker_stop_outcome','paused_budget_expired'),('task_status','pending'),
        ('demand_state','paused'),('dispatched_file_effects',1),('report',h.REPORT)):
        h.exact(result.get(key),value,'expiry_result_changed')
    count=h.integer(result['provider_calls'],1);h.need(count<=8,'request_budget_exceeded')
    h.exact(worker.get('provider_calls'),count,'worker_request_count_changed')
    for key,value in (('passed',False),('completed',False),('controlled',True),
        ('control_state','paused'),('control_reason','paused_budget_expired'),('fixture',False)):
        h.exact(worker.get(key),value,'worker_expiry_changed')
    for key in ('error','error_type','error_chain_types','error_chain_private','traceback_private',
                'cleanup_error','cleanup_errors','expiry_finalization_failed'):
        h.need(key not in worker,'worker_cleanup_failed')
    lives=result['retained_worker_lifetimes'];h.exact(len(lives),1,'worker_replaced')
    h.exact(lives[0].get('exit_code'),5,'worker_exit_changed')
    h.need(not result.get('replacement_binding_committed') and not result.get('injected_restart'),
           'unexpected_restart')
    for key,value in (('owner_epoch',None),('operation',None),('requires_reconciliation',False)):
        h.exact(terminal.get(key),value,'terminal_owner_not_released')
    final=deepcopy(terminal['state']);marker=final.pop(OUTCOME)
    h.exact(final,paused['state'],'preserved_state_changed')
    h.exact(final.get('status'),'pending','task_completed')
    h.exact(final.get('requests'),count,'durable_request_count_changed')
    rejected=final.get('validation_rejections',[])
    h.need(type(rejected) is list and len(rejected)<=count,'validation_rejection_count_invalid')
    h.exact(marker.get('schema'),'adaptive.paused-budget-expiry.v2','seal_schema_changed')
    for row in (result,final,paused['metadata'],terminal['metadata'],marker,observation):
        h.exact(row.get('deadline_clock'),CLOCK_ID,'deadline_clock_missing_or_changed')
    h.exact(paused['metadata'],terminal['metadata'],'task_metadata_changed')
    h.exact(marker['pre_seal_revision'],h.integer(paused['revision']),'pre_seal_revision_changed')
    h.exact(h.integer(terminal['revision']),paused['revision']+1,'extra_terminal_revision')
    h.exact(marker['owner_epoch'],paused['owner_epoch'],'owner_epoch_changed')
    h.exact(marker['pre_seal_state_sha256'],h.object_hash(paused['state']),'pre_state_hash_changed')
    deadline=h.number(marker['deadline_monotonic']);observed=h.number(marker['pause_observed_at_monotonic'])
    sealed=h.number(marker['sealed_at_monotonic'])
    h.need(0<observed<deadline<=sealed,'pause_not_observed_before_deadline')
    h.exact(final['deadline_monotonic'],deadline,'original_deadline_changed')
    h.exact(result['original_task_deadline'],deadline,'result_deadline_changed')
    rows=result['controls'];h.exact(len(rows),3,'control_prefix_changed')
    requests=[]
    for sequence,(row,command) in enumerate(zip(rows,('pause','resume','pause')),1):
        for key,value in (('sequence',sequence),('command',command),('outcome','applied'),('owner_acknowledged',True)):
            h.exact(row.get(key),value,'control_ack_changed')
        requests.append({k:row[k] for k in ('request_id','sequence','command')})
    h.exact(marker['control_prefix_sha256'],h.object_hash({'requests':requests,'receipts':final[ACKS]['receipts']}),
            'control_prefix_hash_changed')
    h.exact(marker['pause_request_id'],rows[-1]['request_id'],'wrong_pause_identity')
    h.exact(marker['pause_sequence'],3,'wrong_pause_sequence')
    for key,index in (('gui_resume_acknowledgements',1),('gui_pause_acknowledgements',2)):
        h.exact(len(result[key]),1,'gui_control_count_changed')
        h.exact(result[key][0],{k:rows[index][k] for k in
            ('request_id','command','sequence','outcome','owner_acknowledged')},'gui_ack_changed')
    proof=worker['paused_expiry']
    h.exact(result['paused_expiry_receipt'],proof,'result_worker_proof_changed')
    h.exact(observation['expiry_receipt'],proof,'observation_worker_proof_changed')
    h.exact(proof['schema'],'adaptive.cooperative-paused-expiry.v2','proof_schema_changed')
    h.exact(proof.get('deadline_clock'),CLOCK_ID,'receipt_deadline_clock_changed')
    for key in ('deadline_monotonic','pause_observed_at_monotonic','sealed_at_monotonic','owner_epoch',
                'pause_request_id','pause_sequence','control_prefix_sha256'):
        h.exact(proof[key],marker[key],'receipt_marker_changed')
    h.exact(h.integer(proof['pid'],1),lives[0]['pid'],'worker_identity_changed')
    h.exact(h.integer(proof['revision']),terminal['revision'],'proof_revision_changed')
    h.exact(proof['state_sha256'],h.object_hash(terminal['state']),'final_state_hash_changed')
    h.exact(proof['native_history_sha256'],h.object_hash(final['native_history']),'native_hash_changed')
    h.exact(proof['task_completed'],False,'proof_claims_completion')
    h.exact(observation['gui_binding'],result['retained_gui_binding'],'gui_replaced')
    verified=h.number(result['verified_expiry_observed_deadline_clock'])
    h.need(sealed<=verified<=h.number(observation['at_deadline_clock']),'observation_precedes_seal')
    for key,value in (('waiting_reason','budget_expired'),('task_status','pending'),('demand','paused')):
        h.exact(observation['runtime'].get(key),value,'expiry_presentation_changed')
    duration=h.number(result['expiry_service_observation_seconds']);h.need(duration>=10,'open_service_observation_short')
    return {'task_completed':False,'task_state':'pending_paused_sealed','worker_exit_code':5,
        'retained_worker_count':1,'provider_calls':count,'validation_rejections':len(rejected),
        'file_effects':1,'report':h.REPORT,
        'report_sha256':h.digest(result['report_sha256']),
        'effect_receipts_sha256':h.digest(result['effect_receipts_sha256']),
        'native_history_sha256':h.digest(proof['native_history_sha256']),
        'sealed_state_sha256':h.digest(proof['state_sha256']),
        'control_prefix_sha256':h.digest(marker['control_prefix_sha256']),
        'predeadline_pause_observed':True,'same_gui_after_expiry':True,
        'open_service_observation_s':duration,'budget_renewed':False,'deadline_clock':CLOCK_ID}


def request_generations(h,result):
    binding=result['runtime_binding'];count=result['provider_calls']
    h.exact(binding.get('enabled'),True,'runtime_binding_missing')
    h.exact(binding.get('request_path'),'actual_gateway','not_actual_gateway')
    h.exact(binding.get('performance_claimed'),False,'performance_claimed')
    generations=h.integer(binding['generation'],1)
    history=binding['request_history'];h.exact(len(history),count,'request_correlation_incomplete')
    for row in history:
        actual=h.integer(row['execution_runtime_generation'],1)
        h.need(actual<=generations,'unknown_native_generation')
    return {'native_generations':generations,'correlated_requests':count,'performance_claimed':False}


def native_releases(h,result,owners):
    """Use actual complete release ledger and independently audited child counts."""
    h.need(type(owners) is list and bool(owners),'native_owner_evidence_missing')
    by_owner={}
    for event in result['handoff_events']:
        if 'release' not in event:continue
        proof=event['release'];owner=proof['owner_id']
        if owner in by_owner:h.exact(proof,by_owner[owner],'conflicting_owner_release')
        for key in ('released','cleanup_confirmed','port_free'):h.true(proof.get(key),'native_release_failed')
        count=h.integer(proof['retained_processes'],1)
        h.exact(h.integer(proof['confirmed_process_exits']),count,'native_child_still_unconfirmed')
        by_owner[owner]=proof
    ids=[row['owner_id'] for row in owners]
    h.need(len(set(ids))==len(ids) and set(ids)==set(by_owner),'native_owner_ledger_incomplete')
    counts=[]
    for row in owners:
        h.exact(row['server_exit_code'],0,'native_server_failed')
        count=h.integer(row['retained_total'],1)
        h.exact(count,by_owner[row['owner_id']]['retained_processes'],'actual_native_count_changed')
        counts.append(count)
    park=result['expiry_parked_observation']
    h.exact(park.get('deadline_clock'),CLOCK_ID,'park_clock_changed')
    h.number(park['at_deadline_clock'])
    for key,value in (('handoff_state','parked'),('admission_allowed',False),
                      ('host_closed',False),('scheduler_closing',False)):
        h.exact(park.get(key),value,'parked_service_not_open')
    proof=park['release'];h.need(proof['owner_id'] in by_owner,'park_owner_unknown')
    h.exact(proof,by_owner[proof['owner_id']],'park_release_changed')
    return {'retained_native_children_per_owner':counts,'native_owner_count':len(counts),
        'all_retained_native_children_exited':True,'normal_park_observed_before_stop':True}


def failed_trial(h,audit,source_sha256):
    """Select the preserved independent failure, never reclassify its old proof."""
    h.exact(h.digest(source_sha256),FAILED_AUDIT_SHA,'failed_audit_binding_changed')
    h.true(audit.get('audit_completed'),'failure_audit_incomplete')
    h.exact(audit.get('case_accepted'),False,'failed_case_relabelled')
    predicates=audit['predicates']
    rejecting=[row['predicate'] for row in predicates
               if row['rejected_at_host_interval_endpoints']!=[False,False]]
    h.exact(rejecting,["now < marker['sealed_at_monotonic']"],'failure_diagnosis_changed')
    clock=audit['clock']
    host=[h.number(value) for value in clock['host_observed_interval']]
    h.need(len(host)==2 and host[0]<=host[1]<h.number(clock['worker_sealed']),
           'failed_clock_evidence_changed')
    h.exact(audit['provider_calls'],2,'failed_request_count_changed')
    h.exact(audit['effects'],1,'failed_effect_count_changed')
    h.exact(audit['validation_rejections'],0,'failed_rejection_count_changed')
    h.exact(audit['supervisor']['exit_code'],1,'failed_parent_relabelled')
    return {'case_accepted':False,'independent_audit_sha256':FAILED_AUDIT_SHA,
            'cause':'Different host and worker monotonic clock domains rejected the seal as future-dated',
            'saved_deadline_equal':True,'provider_calls':2,'file_effects':1,
            'post_expiry_availability_claimed':False,'manual_stop_claimed':False,
            'watchdog_observation':'Separate SDK idle-watchdog warnings; no general lease or billing claim'}


def failed_thread_trial(h,audit,source_sha256):
    """Select the distinct failed tool-thread trial without clock-failure inference."""
    h.exact(h.digest(source_sha256),FAILED_THREAD_AUDIT_SHA,'failed_thread_audit_binding_changed')
    h.true(audit.get('audit_completed'),'thread_failure_audit_incomplete')
    h.true(audit.get('diagnosis_checks_passed'),'thread_failure_diagnosis_incomplete')
    h.exact(audit.get('case_accepted'),False,'failed_thread_case_relabelled')
    h.exact(audit.get('worker_failure'),'Paused SDK check belongs to its exact owner thread',
            'thread_failure_cause_changed')
    h.exact(audit.get('host_refusal'),'Pending native tool continuation cannot confirm product Stop',
            'thread_failure_cleanup_changed')
    for key,value in (('provider_calls',1),('effect_count',0),('native_message_rows',2),('native_pending_tool_calls',1)):
        h.exact(audit.get(key),value,'thread_failure_scope_changed')
    for key in ('pending_waiting_state_preserved_not_sealed','no_tool_receipt_or_report_write',
        'unfinished_read_file_call_truthfully_preserved','listener_closed_but_product_stop_unconfirmed'):
        h.true(audit['checks'].get(key),'thread_failure_evidence_changed')
    h.exact(audit['supervisor']['exit_code'],1,'failed_thread_parent_relabelled')
    ui=audit['ui_observations']
    for key,value in (('first_resume_clicks',1),('manual_pause_clicks',0),('stop_clicks',0),('retry_clicks',0),
                      ('post_expiry_gui',None)):
        h.exact(ui.get(key),value,'failed_thread_ui_scope_changed')
    return {'case_accepted':False,'independent_audit_sha256':FAILED_THREAD_AUDIT_SHA,
        'cause':'Constructor-thread guard refused the SDK sequential worker before tool dispatch',
        'provider_calls':1,'file_effects':0,'native_pending_tool_calls':1,
        'pending_task_preserved':True,'expiry_accepted':False,'manual_stop_claimed':False}


