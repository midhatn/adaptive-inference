# SPDX-License-Identifier: Apache-2.0
"""Pure terminal predicates reused from the preserved expiry03 scaffold."""
from pathlib import Path

CLOCK_ID='windows-qpc-seconds-v1'


def bound_file(static,name):
    matches=[value for path,value in static['input_sha256'].items() if Path(path).name==name]
    if len(matches)!=1:raise ValueError('Static file binding is missing or ambiguous')
    return matches[0]


def parent(h,row,static):
    for key,value in (('exit_code',0),('timed_out',False),('emergency_termination_attempted',False),
        ('retained_case_handle_exited',True),('parent_source_unchanged',True),
        ('supervision_error',None),('supervision_errors',[]),('task_deadline_s',900),
        ('outer_deadline_s',1800),('qualification_manifest',static['qualification_manifest_sha256'])):
        h.exact(row.get(key),value,'parent_or_original_bound_changed')
    expected=h.digest(static['parent_source_sha256'])
    h.exact(row['parent_source_sha256_before'],expected,'parent_source_changed')
    h.exact(row['parent_source_sha256_after'],expected,'parent_source_changed')
    elapsed=h.number(row['elapsed_s']);h.need(900<=elapsed<1800,'expiry_parent_elapsed_outside_bounds')
    return {'exit_code':0,'retained_handle_exited':True,'emergency_termination':False,
        'elapsed_s':elapsed,'source_sha256':expected}


def get_observations(h,rows,*,expiry_at,stop_at,gateway_instance):
    """Count only complete fetch intervals contained in the tagged QPC window.

    Caller must bind the complete trace and the two terminally audited same-clock
    timestamps. Old reader_monotonic remains local diagnostic data and cannot
    substitute for either endpoint. No frame/GET latency is claimed.
    """
    start,end=h.number(expiry_at),h.number(stop_at)
    h.need(start<end,'expiry_stop_order_changed')
    h.need(type(rows) is list and len(rows)<=1200,'observer_trace_unbounded')
    selected=[];errors=0
    for row in rows:
        h.exact(row.get('deadline_clock'),CLOCK_ID,'observer_deadline_clock_changed')
        before=h.number(row.get('reader_before_deadline_clock'))
        after=h.number(row.get('reader_after_deadline_clock'))
        h.need(before<=after,'observer_interval_reversed')
        if not start<=before<=after<end:continue
        if 'observation_error' in row:
            errors+=1;continue
        status=row['gateway_status']
        h.exact(status.get('service'),'adaptive-inference','unexpected_service')
        h.exact(status.get('instance'),gateway_instance,'gateway_instance_changed')
        h.exact(status['resources'].get('admission_allowed'),False,'expired_admission_reopened')
        for key,value in (('active',False),('pending',0),('closing',False),('backend_completion_uncertain',False)):
            h.exact(status['scheduler'].get(key),value,'expired_service_not_idle_open')
        selected.append((before,after))
    h.need(bool(selected),'no_successful_get_after_expiry_before_stop')
    h.need(selected==sorted(selected) and len(set(selected))==len(selected),'observer_clock_order_changed')
    return {'successful_post_expiry_gets':len(selected),'request_errors_in_selected_window':errors,
        'cleanup_proven_by_observer':False,'latency_claimed':False,'deadline_clock':CLOCK_ID,
        'scope':'Observed successful same-instance status requests after verified expiry and before manual Stop'}


def timing(h,result,readiness,observation,ui):
    """Bind audited real UI brackets and explicit same-clock scenario times.

    Uses root's explicit actual-click/QPC receipt contract. This scaffold cannot
    write public acceptance or supply missing observations.
    """
    for row in (result,observation,ui,*readiness):
        h.exact(row.get('deadline_clock'),CLOCK_ID,'timing_clock_changed')
    h.exact(len(readiness),1,'readiness_count_changed')
    deadline=h.number(result['original_task_deadline'])
    ready=h.number(readiness[0]['finished_deadline_clock'])
    verified=h.number(result['verified_expiry_observed_deadline_clock'])
    observed=h.number(observation['at_deadline_clock'])
    h.exact(ui['first_resume_clicks'],1,'resume_click_count_changed')
    h.exact(ui['manual_pause_clicks'],1,'pause_click_count_changed')
    h.exact(ui['stop_clicks'],1,'stop_click_count_changed')
    h.exact(ui['retry_clicks'],0,'unexpected_retry_click')
    resume=[h.number(ui[k]) for k in ('resume_qpc_before','resume_qpc_after')]
    pause=[h.number(ui[k]) for k in ('pause_qpc_before','pause_qpc_after')]
    stop=[h.number(ui[k]) for k in ('stop_qpc_before','stop_qpc_after')]
    h.need(resume[0]<=resume[1]<=ready<=pause[0]<=pause[1]<deadline<=verified<=observed<stop[0]<=stop[1],
           'real_ui_expiry_order_changed')
    park=result['expiry_parked_observation']
    h.exact(park.get('deadline_clock'),CLOCK_ID,'park_clock_changed')
    h.need(verified<=h.number(park['at_deadline_clock'])<=observed,'park_not_between_expiry_and_observation')
    gui=ui['post_expiry_gui'];h.exact(gui.get('deadline_clock'),CLOCK_ID,'gui_observation_clock_changed')
    for key in ('same_window','stop_available','task_pending'):h.true(gui.get(key),'gui_expiry_state_unconfirmed')
    h.exact(h.integer(gui['hwnd'],1),h.integer(ui['window_id'],1),'gui_window_changed')
    waiting=gui['waiting_text']
    h.need(type(waiting) is str and 'budget' in waiting.lower() and 'saved' in waiting.lower(),
           'saved_budget_text_not_observed')
    h.need(observed<=h.number(gui['qpc_before'])<=h.number(gui['qpc_after'])<stop[0],
           'gui_observation_not_between_expiry_and_stop')
    return {'deadline_clock':CLOCK_ID,'single_resume_pause_stop':True,
            'pause_before_original_deadline':True,'same_service_observed_before_manual_stop':True}


def audit_bindings(h,prior,audit,required,inputs,selections):
    checks=prior.checks(h,audit,required)
    for label,path in selections.items():
        h.exact(audit['input_sha256'][str(Path(path).resolve(strict=True))],inputs.hashes[label],
            'terminal_audit_input_changed')
    return checks


