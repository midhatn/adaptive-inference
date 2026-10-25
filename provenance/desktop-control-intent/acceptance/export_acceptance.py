# SPDX-License-Identifier: Apache-2.0
"""Select exact audited successor cold/full evidence into a NEW directory.

Only terminal receipts are read. Reuses the historical strict reader, type/hash,
privacy helpers and unchanged checks/progress selectors without changing any
historical globals or calling its old build/cold/full/parent/wheel gates.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

PREVIOUS_EXPORTER='provenance/installed-desktop/export_acceptance.py'
PREVIOUS_EXPORTER_SHA='7eeec842d1aac88b3d0f9039b54c1f8aa7dfa76d81beecbd72c98467225e4b89'
PREVIOUS_RESULT='provenance/installed-desktop/acceptance/result.json'
PREVIOUS_RESULT_SHA='092f9467c209760fd17b98cc18b9066b1095a83947372e4c62d8ff0e45a5283a'
WHEEL='17fd683bb43e60d91851e1e6efce315cfa04627e50d2b8816e45afbac5c69fbb'
CLIENT='2cb2fb52bbf8bc420d6030b1753c0494552b6e73c60aa9b32d9ed415103711d5'
BEFORE_CLIENT='5c614b6f4b568bb6837fc9360913750c574c1ec7343ef283579c79f0744f46c9'
QUALIFICATION='fccd2564acce46e26d3f83c2f9e78f0b99c051b563622d6440d871de6e58aa9d'
QUALIFIER='f84c7894699d70b3f902df2dd7691e0f2242fab80c7e9767ef9eb98bca628a98'
PROFILE='849f392cde67e0a20dddadd375aa084e659625a00d41f86bd06947067356b931'
SOURCE_REVIEW='85293f406ba7a11a99cf1ade78a140a5598694173d89d55b98495d54baff9554'
PACKAGE_REVIEW='a2f1b5cc628b664e9081bc1b1518c38c0a990b910a171b302f7a4ea9a5acf702'
ACTUAL_GATE='ada79fb08b9467020244112cd318bf97766c1f815c660f06d4dbb0714bfdca48'
COLD_AUDIT='a301cbc2d430da9ce3913da66453fa5ebce13f508bbfca3f7f6705db566e7eb8'
FULL_AUDIT='2f302309e658142eff38382376fe4630097bc4cf0984c92ae603970bbd0383cc'
FULL_ADDITIONAL_CHECKS=frozenset(('single_stop_and_two_single_resume_clicks',
    'physical_overlap_and_performance_not_claimed','actual_deployment_gate_bound','prior_missed_stop_case_preserved'))


def helpers(repository):
    path=Path(repository).resolve(strict=True)/PREVIOUS_EXPORTER
    if hashlib.sha256(path.read_bytes()).hexdigest()!=PREVIOUS_EXPORTER_SHA:
        raise ValueError('Historical selector changed')
    spec=importlib.util.spec_from_file_location('preserved_installed_selector',path)
    prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    return prior,prior.helper(repository)


def pinned(h,inputs,label,path,expected):
    value=inputs.read(label,path)
    h.exact(inputs.hashes[label],expected,'input_pin_changed')
    return value


def source_identity(h,current,previous):
    h.exact(current.get('version'),'0.3.0','package_version_changed')
    files,old=current['files'],previous['installed_package']['files']
    h.need(type(files) is dict and len(files)==52 and set(files)==set(old),'package_module_set_changed')
    h.exact(files['desktop/control_client.py'],CLIENT,'successor_client_changed')
    h.exact(old['desktop/control_client.py'],BEFORE_CLIENT,'predecessor_client_changed')
    for name in files:
        h.digest(files[name])
        if name!='desktop/control_client.py':h.exact(files[name],old[name],'unrelated_runtime_changed')
    return {'client_sha256':CLIENT,'predecessor_client_sha256':BEFORE_CLIENT,
            'other_runtime_modules_byte_identical':51,'runtime_modules':52}


def parent(h,row):
    for key,value in (('exit_code',0),('timed_out',False),('emergency_termination_attempted',False),
        ('retained_case_handle_exited',True),('parent_source_unchanged',True),
        ('supervision_error',None),('supervision_errors',[]),('task_deadline_s',900),
        ('outer_deadline_s',1800),('qualification_manifest',QUALIFICATION)):
        h.exact(row.get(key),value,'parent_not_clean_or_binding_changed')
    before=h.digest(row.get('parent_source_sha256_before'))
    h.exact(row.get('parent_source_sha256_after'),before,'parent_source_changed')
    elapsed=h.number(row.get('elapsed_s'));h.need(elapsed<1800,'outer_bound_exceeded')
    return {'exit_code':0,'retained_handle_exited':True,'emergency_termination':False,
            'elapsed_s':elapsed,'source_sha256':before}


def clean_case(h,prior,result,supervisor,identity):
    h.quality(result)
    for key in ('clean_stop','qualification_case_passed','case_checks_and_cleanup_passed',
        'asyncio_teardown_completed','manual_stop_observed','owner_released',
        'retained_obligations_joined','full_handoff_ledger'):
        h.true(result.get(key),'case_or_cleanup_failed')
    for key,value in (('fixture',False),('live_M2_milestone_claimed',False),
        ('foreground_policy_id',prior.POLICY),('lifecycle',{'worker_joined':True,
            'host_closed':True,'uncertain':False,'fault':None}),
        ('source',{'manifest_sha256':QUALIFICATION,'files':5,'installed_package':identity})):
        h.exact(result.get(key),value,'case_scope_or_source_changed')
    for key in ('primary_error','cleanup_error','cooperative_diagnostic_error'):
        h.exact(result.get(key),None,'case_error')
    h.need(not result.get('joined_obligation_errors'),'join_error')
    gui=result['gui_cleanup']
    for key in ('closed','session_revoked','pipe_threads_joined','pipe_handles_closed',
        'process_handle_closed','verifier_handle_closed','child_exit_observed'):
        h.true(gui.get(key),'gui_cleanup_incomplete')
    for key,value in (('child_exit_code',0),('pending_pipe_operations',0),('faults',[])):
        h.exact(gui.get(key),value,'gui_cleanup_fault')
    listener=result['listener_cleanup'];h.true(listener.get('clean_close'),'listener_not_closed')
    for key in ('owned_connection_pending','setup_pending','handler_pending'):
        h.exact(listener.get(key),False,'listener_pending')
    h.exact(listener.get('faults'),[],'listener_fault')
    transport=result['transport_cleanup']
    for key in ('closed','stop_requested','stop_confirmed'):h.true(transport.get(key),'transport_unconfirmed')
    for key in ('pending_mutations','unknown_mutations','handlers','pending_connections','stream_close_failures'):
        h.exact(transport.get(key),0,'transport_pending_or_uncertain')
    h.exact(transport.get('faults'),[],'transport_fault')
    native=result['cleanup'];h.true(native.get('closed'),'native_not_closed')
    for key in ('primary_error','cleanup_error','controller_fault'):h.exact(native.get(key),None,'native_fault')
    return {'supervisor':parent(h,supervisor),'clean_stop':True,'retained_cleanup_confirmed':True,
            'control_progress':prior.progress(h,result['cooperative_foreground_final'])}


def cold(h,prior,result,supervisor,audit,ui,identity):
    value=clean_case(h,prior,result,supervisor,identity)
    required=prior.COLD_CHECKS|{'ui_single_click_controls','physical_status_overlap_not_claimed','actual_deployment_gate_bound'}
    value['independent_checks']=prior.checks(h,audit,required)
    for key,expected in (('case','cold-gui-installed-worker-stop'),('task_completed',False),
        ('provider_calls',0),('dispatched_file_effects',0),('native_launch_intent',None),
        ('no_resume',True),('worker_exit_code',4),('task_status','pending'),('demand_state','paused')):
        h.exact(result.get(key),expected,'cold_work_or_task_outcome_changed')
    h.true(result.get('gui_pause_observed_before_stop'),'gui_pause_ack_missing')
    controls=result.get('controls');h.need(type(controls) is list and len(controls)==3,'cold_control_count_changed')
    for sequence,row in enumerate(controls,1):
        for key,expected in (('sequence',sequence),('command','pause'),('outcome','applied'),('owner_acknowledged',True)):
            h.exact(row.get(key),expected,'cold_control_changed')
    for key,expected in (('case','installed-ui-cold-02'),('pause_clicks',1),('stop_clicks',1),
        ('resume_clicks',0),('retry_clicks',0),('minimize_or_restore_tested',False),
        ('local_unsent_wait_state_seen',False),('engine_recording_and_owner_acknowledgement_are_separate',True),
        ('observer_termination_proves_cleanup',False)):
        h.exact(ui.get(key),expected,'cold_ui_observation_changed')
    h.exact(value['control_progress']['totals']['successful_pairs'],0,'cold_admission_claim')
    value.update(task_completed=False,task_state='pending_paused',provider_calls=0,file_effects=0,
        native_launches=0,acknowledged_pause_commands=3,
        ui_observation={'pause_clicks':1,'stop_clicks':1,'resume_clicks':0,'retry_clicks':0,
            'local_unsent_wait_state_observed':False,'physical_status_overlap_established':False,
            'minimize_restore_tested':False},
        scope='One observed Pause click and one Stop click; model-free. Pending-status ordering is fixture evidence only.')
    return value


def full(h,prior,result,supervisor,audit,ui,identity):
    value=clean_case(h,prior,result,supervisor,identity)
    audit_checks=dict(audit['checks']);owners=audit['native_owners']
    h.exact(len(owners),2,'native_owner_count_changed')
    for generation,(owner,retained) in enumerate(zip(owners,(8,7)),1):
        audit_checks['native_owner_generation_'+str(generation)]=audit_checks.pop('native_owner_'+owner['owner_id'])
        h.exact(owner.get('retained_total'),retained,'actual_native_retention_changed')
        h.exact(owner.get('server_exit_code'),0,'native_server_failed')
    required=(prior.FULL_CHECKS-{'missed_first_stop_click_preserved'})|FULL_ADDITIONAL_CHECKS
    value['independent_checks']=prior.checks(h,dict(audit,checks=audit_checks),required)
    h.exact(audit.get('validation_rejection_count'),0,'real_correction_scope_changed')
    for key,expected in (('case','gui-iq3s-installed-worker-recovery'),('task_completed',True),
        ('provider_calls',3),('dispatched_file_effects',1),('worker_exit_code',0),
        ('worker_stop_outcome','task_completed'),('task_status','accepted'),
        ('task_case_checks_passed',True),('replacement_binding_committed',True)):
        h.exact(result.get(key),expected,'full_task_outcome_changed')
    h.exact(result.get('report'),h.REPORT,'original_report_oracle_changed')
    rows=result['controls'];h.exact(len(rows),4,'full_control_count_changed')
    for sequence,(row,command) in enumerate(zip(rows,('pause','resume','pause','resume')),1):
        for key,expected in (('sequence',sequence),('command',command),('outcome','applied'),('owner_acknowledged',True)):
            h.exact(row.get(key),expected,'full_control_or_ack_changed')
    acks=result['gui_resume_acknowledgements'];h.exact(len(acks),2,'gui_resume_count_changed')
    for ack,row in zip(acks,(rows[1],rows[3])):
        for key in ('sequence','request_id','command','outcome','owner_acknowledged'):
            h.exact(ack.get(key),row[key],'gui_resume_ack_binding_changed')
    restart=result['injected_restart'];lifetimes=result['retained_worker_lifetimes']
    for key,expected in (('exit_code',1),('joined',True),('product_stop',False)):
        h.exact(restart.get(key),expected,'retained_restart_changed')
    h.exact([row.get('exit_code') for row in lifetimes],[1,0],'worker_lifetimes_changed')
    h.need(lifetimes[0]['pid']==restart['pid'] and lifetimes[0]['pid']!=lifetimes[1]['pid'],'worker_identity_changed')
    binding=result['runtime_binding']
    for key,expected in (('enabled',True),('generation',2),('cold_start_had_no_context',True),('performance_claimed',False)):
        h.exact(binding.get(key),expected,'runtime_binding_changed')
    h.exact([row['generation'] for row in binding['verified_owner_bindings']],[1,2],'native_generations_changed')
    observations=result['cooperative_readiness_observations'];h.exact(len(observations),2,'readiness_count_changed')
    for index,row in enumerate(observations):
        h.true(row.get('admission_observed'),'readiness_admission_missing')
        h.true(row.get('worker_live'),'ready_worker_not_live')
        h.exact(row.get('worker_pid'),lifetimes[index]['pid'],'ready_worker_mismatch')
        snapshot=row['host_snapshot'];controller=snapshot['controller'];activity=snapshot['activity']
        for key,expected in (('handoff_state','ready'),('admission_allowed',True),('foreground_reason','cooperative_clear'),('fault',None)):
            h.exact(controller.get(key),expected,'ready_controller_changed')
        h.exact(activity.get('errors'),[],'activity_error')
        h.true(activity['foreground'].get('valid'),'foreground_invalid')
        for key in ('hwnd','pid','creation_time_100ns'):
            h.exact(activity['foreground'].get(key),result['retained_gui_binding'][key],'owned_foreground_changed')
        guard=snapshot['cooperative_foreground']
        h.exact(guard.get('consecutive'),2,'readiness_progress_pair_missing')
        h.exact(guard['completed']['intent_revision'],row['intent_revision'],'readiness_intent_generation_changed')
        prior.progress(h,guard)
    for key,expected in (('case','installed-ui-full-02'),('first_resume_clicks',1),
        ('replacement_resume_clicks',1),('stop_clicks',1),('manual_pause_clicks',0),('retry_clicks',0),
        ('same_window_retained_across_worker_replacement',True),('local_unsent_wait_state_seen',False),
        ('physical_click_status_overlap_established',False),('observer_termination_proves_cleanup',False),
        ('performance_improvement_claimed',False)):
        h.exact(ui.get(key),expected,'full_ui_observation_changed')
    value.update(task_completed=True,task_state='accepted',provider_calls=3,file_effects=1,
        report=h.REPORT,report_sha256=h.digest(result['report_sha256']),
        effect_receipts_sha256=h.digest(result['effect_receipts_sha256']),
        native_history_sha256=h.digest(result['native_history_sha256']),
        retained_native_children_per_generation=[8,7],all_retained_native_children_exited=True,
        worker_restart={'original_exit_code':1,'replacement_exit_code':0,'original_joined_before_replacement':True,
            'safe_checkpoint_revision':h.integer(restart['safe_checkpoint_revision']),'product_stop_injected':False},
        acknowledged_gui_resumes=2,observed_owned_foreground_readiness_generations=2,
        real_model_validation_rejections=0,real_model_correction_observed=False,
        ui_observation={'first_resume_clicks':1,'replacement_resume_clicks':1,'stop_clicks':1,
            'same_window_retained':True,'local_unsent_wait_state_observed':False,
            'physical_status_overlap_established':False},performance_improvement_claimed=False,
        scope='One bounded IQ3_S report/restart task and observed single clicks; pending-status ordering remains fixture evidence.')
    return value


def observer(h,row,samples,valid):
    for key,expected in (('samples',samples),('valid_responses',valid),
        ('consecutive_connection_errors',3),('end_reason','three_connection_errors_after_response'),
        ('source_unchanged',True),('active_case_file_contents_read',False),('task_completion_claimed',False)):
        h.exact(row.get(key),expected,'observer_scope_changed')
    return {'samples':samples,'valid_responses':valid,'terminal_request_errors':3,
            'classification':'inconclusive','cleanup_proven_by_observer':False}


def build(h,prior,repository,selection,inputs):
    h.exact(selection.get('scope'),'retained-intent-cold-full-02','selection_scope_changed')
    h.exact(h.hash_bytes(inputs.raw('wheel',selection['wheel'])),WHEEL,'wheel_changed')
    h.exact(h.hash_bytes(inputs.raw('qualification_manifest',selection['qualification_manifest'])),QUALIFICATION,'qualification_source_changed')
    h.exact(h.hash_bytes(inputs.raw('qualifier',selection['qualifier'])),QUALIFIER,'qualifier_changed')
    previous=pinned(h,inputs,'predecessor',Path(repository)/PREVIOUS_RESULT,PREVIOUS_RESULT_SHA)
    audit=pinned(h,inputs,'cold_audit',selection['cold_audit'],COLD_AUDIT)
    supervisor=inputs.read('cold_parent',selection['cold_parent']);parent(h,supervisor)
    result=inputs.read('cold_result',selection['cold_result'])
    ui=inputs.read('cold_ui',selection['cold_ui'])
    for label in ('cold_result','cold_ui'):
        h.exact(audit['evidence_sha256'][str(Path(selection[label]).resolve(strict=True))],inputs.hashes[label],'cold_audit_binding_changed')
    h.exact(audit['supervisor'],supervisor,'cold_parent_binding_changed')
    h.exact(audit['ui_observations'],ui,'cold_ui_binding_changed')
    identity=result['source']['installed_package']
    source=source_identity(h,identity,previous)
    review=pinned(h,inputs,'source_review',selection['source_review'],SOURCE_REVIEW)
    h.true(review.get('passed'),'source_review_failed');h.exact(review['client_sha256'],CLIENT,'reviewed_client_changed')
    h.need(type(review['checks']) is dict and len(review['checks'])==20 and all(v is True for v in review['checks'].values()),'source_check_failed')
    package=pinned(h,inputs,'package_review',selection['package_review'],PACKAGE_REVIEW)
    for key,value in (('passed',True),('wheel_sha256',WHEEL),('runtime_modules',52),
        ('all_RECORD_hashes_sizes_verified',True),('source_matches_reviewed_candidate',True)):
        h.exact(package.get(key),value,'package_review_changed')
    gate=pinned(h,inputs,'actual_gate',selection['actual_gate'],ACTUAL_GATE)
    for key,value in (('passed',True),('wheel_sha256',WHEEL),('profile_sha256',PROFILE),
        ('host_checks',252),('worker_checks',305),('runtime_modules_current_on_both_interpreters',52),
        ('native_files',4847),('native_dependencies',8),('model_asset_metadata',14),
        ('full_model_content_hashed',False),('capacity_monitor_joined',True),('all_receipts_unchanged',True)):
        h.exact(gate.get(key),value,'actual_deployment_gate_changed')
    for label,count in (('host',252),('worker',305)):
        report=inputs.read(label,selection[label])
        h.exact(gate['input_sha256'][str(Path(selection[label]).resolve(strict=True))],inputs.hashes[label],'actual_install_binding_changed')
        h.true(report.get('passed'),'actual_install_not_passed')
        h.exact(report['package_identity'],identity,'installed_identity_changed')
        h.need(type(report['checks']) is dict and len(report['checks'])==count and all(v is True for v in report['checks'].values()),'actual_install_check_failed')
    full_supervisor=inputs.read('full_parent',selection['full_parent']);parent(h,full_supervisor)
    full_audit=pinned(h,inputs,'full_audit',selection['full_audit'],FULL_AUDIT)
    full_result=inputs.read('full_result',selection['full_result'])
    full_ui=inputs.read('full_ui',selection['full_ui'])
    for label in ('full_result','full_ui'):
        h.exact(full_audit['input_sha256'][str(Path(selection[label]).resolve(strict=True))],inputs.hashes[label],'full_audit_binding_changed')
    h.exact(full_audit['supervisor'],full_supervisor,'full_parent_binding_changed')
    h.exact(full_audit['ui_observations'],full_ui,'full_ui_binding_changed')
    cold_selected=cold(h,prior,result,supervisor,audit,ui,identity)
    cold_selected['observer']=observer(h,audit['observer'],49,46)
    full_selected=full(h,prior,full_result,full_supervisor,full_audit,full_ui,identity)
    full_selected['observer']=observer(h,full_audit['observer'],418,415)
    value={'schema':'adaptive.desktop-control-intent-evidence.v1',
        'status':'bounded-installed-cold-and-full-accepted','wheel_sha256':WHEEL,'source_binding':source,
        'installed_package':identity,
        'qualification_manifest_sha256':QUALIFICATION,'qualifier_sha256':QUALIFIER,
        'profile_sha256':PROFILE,'model':h.MODEL,'quality':h.QUALITY,
        'software':{'independent_python311':review['tests311'],'independent_python312':review['tests312'],
            'scope':'Targeted software fixtures, separate from installed real GUI cases'},
        'actual_installation':{'host_checks':252,'worker_checks':305,'runtime_modules':52},
        'qualification_bounds':{'task_deadline_s':900,'provider_request_limit':8,
            'readiness_deadline_s':240,'outer_deadline_s':1800},
        'cold':cold_selected,'full':full_selected,
        'private_input_sha256':dict(inputs.hashes),'prior_helper_sha256':prior.HELPER_SHA,
        'previous_selector_sha256':PREVIOUS_EXPORTER_SHA}
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv);prior,h=helpers(args.repository)
    try:
        h.need(not args.output.exists() and args.output.parent.is_dir(),'output_not_fresh')
        inputs=h.Inputs(args.selection.parent);selection=inputs.read('selection',args.selection)
        value=build(h,prior,args.repository,selection,inputs)
        value['selection_exporter_sha256']=h.hash_bytes(Path(__file__).read_bytes())
        data=h.encoded(value);h.privacy_check(data)
        manifest={'schema':'adaptive.public-evidence-files.v1','source_selection':'explicit nested allowlists',
            'files':{'result.json':h.hash_bytes(data)},'sanitizer_sha256':value['selection_exporter_sha256'],
            'reused_helper_sha256':prior.HELPER_SHA,'previous_selector_sha256':PREVIOUS_EXPORTER_SHA}
        manifest_data=h.encoded(manifest);h.privacy_check(manifest_data);inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name,blob in (('result.json',data),('manifest.json',manifest_data)):
            with (args.output/name).open('xb') as stream:stream.write(blob)
        print(json.dumps({'prepared':True,'published':False,'files':manifest['files']}))
        return 0
    except (h.Refused,KeyError,IndexError,TypeError,ValueError,OSError) as error:
        print(json.dumps({'prepared':False,'reason':str(error) if isinstance(error,h.Refused) else type(error).__name__}))
        return 2


if __name__=='__main__':raise SystemExit(main())
