"""STAGED terminal-only expiry audit. Never run while the case is active.

Reuses full02's pure readers, SQLite projection, effect oracle and ownership
predicates. Actual wheel/deployment bindings and observed identifiers are inputs;
no future result, model-call count or native child count is prefilled.
"""
import argparse, csv, hashlib, json, math, sqlite3, zipfile
from pathlib import Path

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def lines(p): return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]
NS='adaptive_inference.demand.v1'
KEY='adaptive_inference.execution_outcome.v1'
CLOCK_ID='windows-qpc-seconds-v1'

def finite_time(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0

def qpc_bracket(row,before,after):
    return (row.get('deadline_clock')==CLOCK_ID and finite_time(row.get(before))
            and finite_time(row.get(after)) and row[before]<=row[after])

QUALITY={'max_tokens':10923,'reasoning_effort':'high','reasoning_budget_tokens':8192,
         'experimental_speed_projection':False,'strata_tune':{'pcie_frac':.37}}
CONTEXT={'context_length':65536,'threshold':.8,'threshold_tokens':46421,'reserved_output':10923,'max_tokens':10923}

def audit(binding, output):
    b=read(binding)
    assert b['status']=='ready_for_terminal_only_audit'
    case=Path(b['case']); base=case.parent; work=case/'hermes-task'
    # Root must have consumed the retained parent's terminal result before calling.
    sup=read(base/(case.name+'.supervisor.private.json'))
    assert sup['exit_code']==0 and sup['retained_case_handle_exited'] is True
    assert not sup['timed_out'] and not sup['emergency_termination_attempted']
    assert sup['supervision_error'] is None and sup['supervision_errors']==[]
    assert all(sha(p)==h for p,h in b['input_sha256'].items())
    output.mkdir(exist_ok=False)
    receipt={'scope':'Installed IQ3_S safe paused original-budget expiry; pending task, no renewal/reboot/performance/whole-M2 claim','checks':{}}
    def check(name,value):
        receipt['checks'][name]=bool(value)
        if not value: raise AssertionError(name)
    try:
        result=read(case/'result.private.json');original=read(case/'original-checkpoint.private.json')
        term=read(case/'terminal-checkpoint.private.json');paused=read(case/'paused-checkpoint.private.json')
        plan=read(work/'plan.json');events=lines(case/'events.private.jsonl')
        lifetimes=result['retained_worker_lifetimes']
        check('single_retained_worker_no_replacement',len(lifetimes)==1 and lifetimes[0]['exit_code']==5
              and not result.get('injected_restart') and not result.get('replacement_binding_committed'))
        pid=lifetimes[0]['pid'];worker=read(work/f'result-{pid}.json');boot=read(work/f'bootstrap-{pid}.json')
        releases=[x['release'] for x in result['handoff_events'] if 'release' in x]
        sources=[p for p in case.rglob('*') if p.is_file()]
        sources += [base/(case.name+s) for s in ('.supervisor.private.json','.api-trace.private.jsonl','.api-trace.private.receipt.json')]
        sources += [Path(p) for p in b['input_sha256']]+[Path(binding)]
        sources += [p for r in releases for p in Path(r['identity']['run']).glob('*') if p.is_file()]
        before={str(p):sha(p) for p in sources}
        with sqlite3.connect((work/'task.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
            c.row_factory=sqlite3.Row
            tasks=[dict(x) for x in c.execute('SELECT * FROM tasks')]
            history=[dict(x) for x in c.execute('SELECT * FROM history')]
            integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
        task=next(x for x in tasks if x['task_id']=='orders-report')
        state=json.loads(task['state']);meta=json.loads(task['metadata']);marker=state[KEY]
        check('task_database_integrity',integrity=='ok')
        check('actual_database_matches_terminal_checkpoint',state==term['state'] and meta==term['metadata']
              and all(task[k]==term[k] for k in ('task_id','prompt','max_attempts','revision','owner_epoch'))
              and task['inflight'] is None and not task['reconciliation']
              and term['operation'] is None and not term['requires_reconciliation'])
        check('pending_paused_all_owners_released',state['status']=='pending' and state['phase']=='ready'
              and state[NS]['state']=='paused' and len(tasks)==2
              and all(x['owner_epoch'] is None and x['inflight'] is None and not x['reconciliation'] for x in tasks))
        check('original_prompt_quality_metadata_budget_preserved',
              all(term[k]==paused[k]==original[k] for k in ('task_id','prompt','metadata','max_attempts'))
              and state['messages'][0]==original['state']['messages'][0]
              and state['deadline_monotonic']==paused['state']['deadline_monotonic']==result['deadline_monotonic']
              and task['max_attempts']==plan['max_requests']==8 and sup['task_deadline_s']==900 and sup['outer_deadline_s']==1800
              and plan['quality']==result['quality']==worker['quality']==QUALITY
              and plan['model']==result['model']==worker['model']=='qwen3.8-flash-next-iq3_s-adaptive-media-beta'
              and result['fixture'] is False and worker['fixture'] is False)
        for cp in (paused,term):
            h=next(json.loads(x['payload']) for x in history if x['task_id']==task['task_id'] and x['revision']==cp['revision'])
            check('checkpoint_actual_history_'+str(cp['revision']),h['state']==cp['state'])
        check('one_original_deadline_in_all_task_history',all(
            json.loads(h['payload'])['state'].get('deadline_monotonic',state['deadline_monotonic'])==state['deadline_monotonic']
            for h in history if h['task_id']==task['task_id']))
        without=dict(state);without.pop(KEY)
        check('full_saved_state_unchanged_except_seal',without==paused['state']
              and task['revision']==paused['revision']+1 and marker['pre_seal_revision']==paused['revision']
              and marker['pre_seal_state_sha256']==digest(paused['state']) and marker['owner_epoch']==paused['owner_epoch'])
        mailbox=next(x for x in tasks if x['task_id']!='orders-report')
        requests=json.loads(mailbox['state'])['adaptive_inference.control_requests.v1']
        acks=state['adaptive_inference.control_acks.v1']['receipts']
        resumes=result['gui_resume_acknowledgements'];pauses=result['gui_pause_acknowledgements']
        check('exact_initial_pause_genuine_resume_genuine_pause_prefix',len(resumes)==len(pauses)==1
              and len(requests)==len(acks)==len(result['controls'])==3
              and [x['command'] for x in requests]==['pause','resume','pause']
              and [x['request_id'] for x in requests]==['initial-pause-before-bootstrap',resumes[0]['request_id'],pauses[0]['request_id']]
              and all({k:a[k] for k in ('sequence','request_id','command')}==r and a['outcome']=='applied' for r,a in zip(requests,acks))
              and all({k:v for k,v in r.items() if k!='owner_acknowledged'}==a and r['owner_acknowledged'] is True for r,a in zip(result['controls'],acks)))
        proof=worker['paused_expiry'];expiry=read(case/'expiry-observation.private.json')
        check('one_explicit_shared_execution_clock',all(row.get('deadline_clock')==CLOCK_ID for row in
              (state,meta,plan,original['state'],original['metadata'],paused['state'],paused['metadata'],result,marker,proof,expiry,boot))
              and boot['deadline_monotonic']==state['deadline_monotonic']==result['original_task_deadline'])
        check('strict_marker_and_predeadline_pause',marker['schema']=='adaptive.paused-budget-expiry.v2'
              and set(marker)=={'schema','deadline_clock','deadline_monotonic','pause_observed_at_monotonic','sealed_at_monotonic',
                  'owner_epoch','pre_seal_revision','pre_seal_state_sha256','pause_request_id','pause_sequence','control_prefix_sha256'}
              and all(type(marker[k]) in (float,int) and math.isfinite(marker[k]) and marker[k]>0 for k in
                  ('deadline_monotonic','pause_observed_at_monotonic','sealed_at_monotonic'))
              and marker['pause_observed_at_monotonic']<marker['deadline_monotonic']<=marker['sealed_at_monotonic']
              and marker['deadline_monotonic']==state['deadline_monotonic']
              and marker['pause_request_id']==pauses[0]['request_id'] and marker['pause_sequence']==pauses[0]['sequence']
              and marker['control_prefix_sha256']==digest({'requests':requests,'receipts':acks}))
        check('expiry_receipt_binds_final_released_state_and_worker',
              proof['schema']=='adaptive.cooperative-paused-expiry.v2' and proof['pid']==pid
              and set(proof)=={'schema','deadline_clock','task_id','registration_id','pid','owner_epoch','revision',
                  'state_sha256','native_history_sha256','deadline_monotonic','pause_observed_at_monotonic','sealed_at_monotonic',
                  'pause_request_id','pause_sequence','control_prefix_sha256','task_completed'}
              and proof['revision']==task['revision'] and proof['owner_epoch']==marker['owner_epoch']==worker['owner_epoch']
              and proof['task_id']==task['task_id'] and proof['registration_id']==plan['demand_identity']['registration_id']
              and proof['state_sha256']==digest(state) and proof['native_history_sha256']==digest(state['native_history'])
              and proof['task_completed'] is False and all(proof[k]==marker[k] for k in
                  ('deadline_monotonic','pause_observed_at_monotonic','sealed_at_monotonic','pause_request_id','pause_sequence','control_prefix_sha256'))
              and result['paused_expiry_receipt']==expiry['expiry_receipt']==proof
              and worker['passed'] is False and worker['completed'] is False and worker['controlled'] is True
              and worker['control_state']=='paused' and worker['control_reason']=='paused_budget_expired'
              and not any(k in worker for k in ('error','error_type','error_chain_types','error_chain_private','traceback_private','cleanup_error','cleanup_errors','expiry_finalization_failed')))
        rows=list(csv.DictReader((work/'work/orders.csv').read_text().splitlines()))
        oracle={'rows':len(rows),'units':sum(int(x['quantity']) for x in rows),'total_cents':sum(int(x['quantity'])*int(x['unit_cents']) for x in rows),'by_item':{}}
        for x in rows:oracle['by_item'][x['item']]=oracle['by_item'].get(x['item'],0)+int(x['quantity'])*int(x['unit_cents'])
        check('original_csv_and_report_oracle',oracle=={'rows':4,'units':17,'total_cents':4350,'by_item':{'folder':1100,'notebook':2250,'pen':1000}}==read(work/'work/report.json')==result['report'])
        effects=lines(work/'effect-receipts.jsonl');writes=[x for x in state['tools'] if x['name']=='write_file']
        check('one_unchanged_actual_report_effect',len(effects)==len(writes)==1 and effects[0]==writes[0]
              and effects[0]['reused'] is False and effects[0]['artifact_sha256']==sha(work/'work/report.json')==result['report_sha256']
              and sha(work/'effect-receipts.jsonl')==result['effect_receipts_sha256'])
        check('all_tool_results_exactly_once',all(len([m for m in state['native_history'] if m.get('role')=='tool' and m.get('tool_call_id')==t['tool_call_id'] and m['content']==t['result']])==1 for t in state['tools']))
        wire=read(work/'wire-observations.json');runtime=result['runtime_binding']
        check('no_provider_calls_after_pause_and_original_quality',wire==read(case/'paused-wire.private.json')
              and 0<len(wire)<=8 and result['provider_calls']==state['requests']==worker['provider_calls']==len(wire)
              and all(x['method']=='POST' and x['url']=='http://127.0.0.1:18100/v1/chat/completions'
                  and x['finished_at']>=x['started_at'] and x['model']==plan['model'] and x['quality']==QUALITY for x in wire))
        config=read(work/'home/config.yaml')
        check('original_context_unchanged',worker['context']==CONTEXT and config['model']['context_length']==65536 and config['compression']['threshold']==.8)
        # Exact independent native-message projection retained from full02.
        with sqlite3.connect((work/'home/state.db').as_uri()+'?mode=ro',uri=True) as c:
            c.row_factory=sqlite3.Row
            native_rows=[dict(x) for x in c.execute('SELECT * FROM messages ORDER BY id')]
            sessions=[dict(x) for x in c.execute('SELECT * FROM sessions')]
            native_integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
        check('native_database_integrity',native_integrity=='ok' and len(sessions)==1 and sessions[0]['id']==state['session_id'] and not sessions[0].get('parent_session_id'))
        decoded=[]
        for row in native_rows:
            m={'role':row['role'],'content':row['content'],'_db_persisted':True,'_row_id':row['id'],'message_uid':row['message_uid'],'timestamp':row['timestamp']}
            for column,key in (('tool_call_uids','_tool_call_uids'),('tool_call_uid','_tool_call_uid'),('tool_calls','tool_calls')):
                if row[column]:m[key]=json.loads(row[column]) if column!='tool_call_uid' else row[column]
            for key in ('tool_call_id','tool_name','effect_disposition','finish_reason','reasoning'):
                if row[key]:m[key]=row[key]
            if row['role']=='assistant' and row['reasoning_content'] is not None:m['reasoning_content']=row['reasoning_content']
            decoded.append(m)
        check('final_native_rows_equal_saved_history_after_cleanup',all(x['session_id']==state['session_id'] and x['active']==1 and x['compacted']==0 for x in native_rows)
              and decoded==state['native_history']==paused['state']['native_history']
              and digest(decoded)==result['native_history_sha256']==proof['native_history_sha256'])
        from adaptive_inference.desktop.hermes.recovery import verify_validation_rows
        verify_validation_rows(decoded,state,meta.get('pre_effect_validator'))
        check('native_validation_feedback_preserved',state.get('validation_rejections',[])==paused['state'].get('validation_rejections',[])
              and meta.get('pre_effect_validator')==plan.get('pre_effect_validator'))
        readiness=result['cooperative_readiness_observations'];check('one_actual_readiness_receipt',len(readiness)==1 and readiness[0]==read(case/'cooperative-readiness-1.private.json'))
        obs=readiness[0];hs=obs['host_snapshot'];progress=hs['cooperative_foreground'];current=progress['completed'];activity=hs['activity']
        completed=[x for x in progress['events'] if x['event']=='completed' and x['intent_revision']==obs['intent_revision']]
        check('current_readiness_identity_and_positive_pairs',obs['worker_pid']==pid and obs['owner_epoch']==paused['owner_epoch']
              and obs['worker_live'] and obs['admission_observed'] and obs['gui_binding']==result['retained_gui_binding']
              and all(activity['foreground'][k]==obs['gui_binding'][k] for k in ('pid','hwnd','creation_time_100ns'))
              and hs['controller']['handoff_state']=='ready' and hs['controller']['admission_allowed'] and hs['controller']['foreground_reason']=='cooperative_clear'
              and progress['consecutive']==2 and progress['reason']=='progress_healthy' and current['intent_revision']==obs['intent_revision']
              and len(completed)>=2 and completed[-1]['sequence']==current['sequence'] and completed[-2]['sequence']+1==current['sequence'])
        begin=next(x['at_monotonic'] for x in events if x['kind']=='demand_before_readiness' and x['pid']==pid)
        check('unchanged_readiness_freshness_capacity_and240bound',0<=obs['finished_monotonic']-begin<=240 and obs['deadline_clock']==CLOCK_ID and finite_time(obs['finished_deadline_clock']) and obs['finished_deadline_clock']<state['deadline_monotonic']
              and current['elapsed_s']<=.5 and obs['finished_monotonic']-current['closed']<=2.5 and obs['finished_monotonic']-activity['monotonic_s']<=1
              and activity['host']['cpu_busy_fraction']<=.8 and activity['host']['ram_available_gib']>=4 and activity['host']['commit_available_gib']>=4)
        check('every_actual_request_has_verified_runtime_generation',len(runtime['request_history'])==len(wire)
              and [x['request_id'] for x in runtime['request_history']]==[x['gateway_request_id'] for x in wire]
              and all(x['status']==200 and not x['backend_completion_uncertain'] and x['prediction_matches_execution_runtime'] for x in runtime['request_history']))
        native_proofs=[]
        check('complete_native_owner_restore_release_ledger',result['full_handoff_ledger'] and len(releases)>=1
              and len(releases)==sum(x.get('restore_requested') is True for x in result['handoff_events'])==len(runtime['verified_owner_bindings']))
        for release in releases:
            n=read(Path(release['identity']['run'])/'result.json');count=n['processes']['retained_total']
            check('native_owner_'+n['owner_id'],type(count) is int and count>0 and n['owner_id']==release['owner_id']
                  and n['owner']==release['identity']['owner'] and n['state']=='stopped' and not n['running']
                  and n['stop_reason']=='requested' and n['cleanup_confirmed'] and n['server_exit_code']==0
                  and n['processes']['active']==[] and n['processes']['confirmed_exits']==count
                  and all(x['exited'] for x in n['processes']['completed_tail']) and release['released'] and release['cleanup_confirmed'] and release['port_free']
                  and release['confirmed_process_exits']==release['retained_processes']==count and all(x['exited'] for x in release['retained_at_stop']))
            native_proofs.append({'owner_id':n['owner_id'],'owner_pid':n['owner']['pid'],'run':n['run'],'retained_total':count,'server_exit_code':0})
        parked=result['expiry_parked_observation'];ui=read(case/'ui-observations.private.json')
        check('verified_expiry_then_parked_open_service_before_stop',result['deadline_clock']==parked['deadline_clock']==expiry['deadline_clock']==CLOCK_ID
              and all(finite_time(x) for x in (result['verified_expiry_observed_deadline_clock'],parked['at_deadline_clock'],expiry['at_deadline_clock']))
              and marker['sealed_at_monotonic']<=result['verified_expiry_observed_deadline_clock']<=parked['at_deadline_clock']<=expiry['at_deadline_clock']
              and parked['handoff_state']=='parked' and parked['admission_allowed'] is False and parked['host_closed'] is False and parked['scheduler_closing'] is False
              and parked['release'] in releases and result['expiry_service_observation_seconds']>=10
              and expiry['worker_pid']==pid and expiry['worker_exit_code']==5 and expiry['runtime']['waiting_reason']=='budget_expired')
        # Explicit future UI-receipt contract, populated from root's actual observations.
        gui_seen=ui['post_expiry_gui']
        check('separate_same_window_expiry_display_and_manual_stop',ui['window_id']==result['retained_gui_binding']['hwnd']==gui_seen['hwnd']
              and ui['first_resume_clicks']==ui['manual_pause_clicks']==ui['stop_clicks']==1 and ui['retry_clicks']==0
              and gui_seen['same_window'] is True and gui_seen['stop_available'] is True and gui_seen['task_pending'] is True
              and 'budget' in gui_seen['waiting_text'].lower() and 'saved' in gui_seen['waiting_text'].lower()
              and qpc_bracket(gui_seen,'qpc_before','qpc_after') and qpc_bracket(ui,'stop_qpc_before','stop_qpc_after')
              and expiry['at_deadline_clock']<=gui_seen['qpc_before']<=gui_seen['qpc_after']
                  <ui['stop_qpc_before']<=ui['stop_qpc_after']
              and all(isinstance(gui_seen[k],str) and gui_seen[k] for k in ('utc_before','utc_after'))
              and all(isinstance(ui[k],str) and ui[k] for k in ('stop_utc_before','stop_utc_after')))
        trace=lines(base/(case.name+'.api-trace.private.jsonl'));observer=read(base/(case.name+'.api-trace.private.receipt.json'))
        good=[x for x in trace if 'gateway_status' in x]
        # QPC brackets conservatively surround complete GET and UI operations.
        # Local reader_monotonic values are never used for shared-deadline ordering.
        check('all_observer_shared_clock_brackets_valid',observer['deadline_clock']==CLOCK_ID
              and all(qpc_bracket(x,'reader_before_deadline_clock','reader_after_deadline_clock') for x in trace))
        post=[x for x in good if 'observation_error' not in x and
              expiry['at_deadline_clock']<=x['reader_before_deadline_clock']<=x['reader_after_deadline_clock']<ui['stop_qpc_before']]
        check('post_expiry_same_instance_get_service_response',len(trace)==observer['samples'] and len(good)==observer['valid_responses']
              and {x['gateway_status']['instance'] for x in good}=={observer['gateway_instance']}
              and post and any(x['gateway_status']['resources']['handoff_state']=='parked'
                  and x['gateway_status']['resources']['admission_allowed'] is False and x['gateway_status']['scheduler']['closing'] is False for x in post)
              and observer['task_completion_claimed'] is False and observer['active_case_file_contents_read'] is False)
        hc=read(case/'host/result.json');hs=read(case/'host/status.json')
        check('host_native_cleanup_views',hc==result['cleanup'] and hc['closed'] and hc['normal_release_confirmed'] and hc['owned_children_exited']
              and all(hc[k] is None for k in ('primary_error','controller_fault','cleanup_error')))
        check('paused_effective_demand_and_admission_closed',hs['controller']['demand']['classification']=='absent' and not hs['controller']['admission_allowed']
              and any(x['state']=='paused' and x['reason']=='demand_paused' for x in hs['controller']['demand']['intents']))
        g=result['gui_cleanup'];t=result['transport_cleanup'];l=result['listener_cleanup']
        check('gui_exact_owned_cleanup',g['child_exit_code']==0 and g['pending_pipe_operations']==0 and g['faults']==[]
              and all(g[k] for k in ('closed','child_exit_observed','session_revoked','authentication_revoked','pipe_threads_joined','pipe_handles_closed','verifier_handle_closed','process_handle_closed')))
        check('listener_transport_fully_closed',l['accepted_connections']>0 and l['clean_close'] and l['resources_closed'] and l['listener_closed']
              and not any(l[k] for k in ('accepting','owned_connection_pending','setup_pending','handler_pending')) and l['faults']==[]
              and t['closed'] and t['stop_requested'] and t['stop_confirmed'] and all(t[k]==0 for k in ('pending_mutations','unknown_mutations','handlers','pending_connections','stream_close_failures')) and t['faults']==[])
        diag=result['cooperative_foreground_final']
        check('postcleanup_progress_snapshot_without_error',diag['reason']=='listener_closed' and diag['pending_sequence'] is None
              and all(v==0 for k,v in diag['invalidations'].items() if any(word in k for word in ('failed','timeout','unconfirmed','cancelled'))))
        check('full_and_public_handoff_views_consistent',len(result['cleanup']['events'])==len(result['handoff_events'])
              and all({k:v for k,v in a.items() if k!='release'}=={k:v for k,v in b.items() if k!='release'}
                  and ('release' not in b or all(a['release'][k]==v for k,v in b['release'].items()))
                  for a,b in zip(result['handoff_events'],result['cleanup']['events'])))
        exits=result['all_retained_process_exits']
        check('exact_worker_and_preparation_joined_job_empty',len(exits)==2 and sum(x['pid']==pid and x['exit_code']==5 for x in exits)==1
              and all(x['exit_code']==0 for x in exits if x['pid']!=pid) and result['actual_job_members_after_cleanup']==[sup['pid']]
              and result['retained_obligations_joined'] and not result.get('joined_obligation_errors'))
        check('normal_stop_and_pending_expiry_scope',result['manual_stop_observed'] and result['worker_stop_outcome']=='paused_budget_expired'
              and result['owner_released'] and result['worker_exit_code']==5 and result['task_completed'] is False
              and result['execution_expired'] is True and all(result[k] is True for k in
                  ('clean_stop','qualification_case_passed','case_checks_and_cleanup_passed','asyncio_teardown_completed','expiry_case_checks_passed'))
              and result['live_M2_milestone_claimed'] is False and result['lifecycle']=={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None})
        hostid=read(b['host_audit']);workerid=read(b['worker_audit']);pins=result['source']['installed_package']
        check('same_actual_installed_package_in_both_interpreters',hostid['passed'] and workerid['passed']
              and pins==hostid['package_identity']==workerid['package_identity']==plan['package_identity']==read(case/'installed-package.private.json')
              and len(pins['files'])==54 and all(sha(Path(r['package_root'])/p)==h for r in (hostid,workerid) for p,h in pins['files'].items()))
        with zipfile.ZipFile(b['wheel']) as z:
            payload={p.removeprefix('adaptive_inference/'):hashlib.sha256(z.read(p)).hexdigest() for p in z.namelist() if p.startswith('adaptive_inference/') and p.endswith('.py')}
        check('reviewed_wheel_payload_exact',sha(b['wheel'])==b['wheel_sha256'] and payload==pins['files'])
        qual=Path(b['qualifier']);manifest=read(qual/'source-manifest.json')
        check('qualifier_and_parent_sources_exact',sha(qual/'source-manifest.json')==result['source']['manifest_sha256']==sup['qualification_manifest']
              and all(sha(qual/p)==v['sha256'] for p,v in manifest['files'].items())
              and sha(b['parent'])==sup['parent_source_sha256_before']==sup['parent_source_sha256_after']
              and sha(b['observer_source'])==observer['source_sha256'])
        gate=read(b['deployment_gate'])
        check('actual_deployment_gate_bound',gate['passed'] and gate['wheel_sha256']==b['wheel_sha256']
              and all(sha(p)==h for p,h in gate['input_sha256'].items()))
        from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES
        clock_probe=read(b['installed_clock_probe'])
        check('actual_installed_shared_clock_probe_bound',clock_probe['passed'] is True
              and sha(b['installed_clock_probe'])==b['input_sha256'][b['installed_clock_probe']])
        check('sdk_and_prepared_input_pins',len(SDK_FILES)==20 and all(sha(Path(plan['sdk'])/p)==h for p,h in SDK_FILES.items()) and all(sha(p)==h for p,h in plan['pins'].items()))
        check('all_terminal_inputs_unchanged',all(sha(p)==h for p,h in before.items()))
        receipt.update(passed=True,input_sha256=before,task_revision=task['revision'],task_state_sha256=digest(state),native_history_sha256=digest(decoded),
            report_sha256=result['report_sha256'],effect_sha256=result['effect_receipts_sha256'],validation_rejection_count=len(state.get('validation_rejections',[])),
            provider_calls=len(wire),readiness=readiness,native_owners=native_proofs,controls=result['controls'],supervisor=sup,observer=observer,ui_observations=ui,
            paused_expiry=proof,expiry_observation=expiry,parked_observation=parked,post_expiry_get_responses=len(post),observer_termination_proves_cleanup=False,
            actual_deployment_gate_sha256=sha(b['deployment_gate']),deadline_clock=CLOCK_ID,
            shared_clock_probe_sha256=sha(b['installed_clock_probe']),
            clock_observation_scope='Same-machine QPC brackets; local monotonic fields are elapsed/freshness diagnostics only')
    except BaseException as exc:
        receipt.update(passed=False,error=type(exc).__name__+': '+str(exc));raise
    finally:
        (output/'audit.private.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':receipt.get('passed'),'checks':len(receipt['checks']),'error':receipt.get('error')}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bindings',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--terminal-confirmed',action='store_true',required=True)
    args=parser.parse_args()
    audit(args.bindings,args.output.resolve())
