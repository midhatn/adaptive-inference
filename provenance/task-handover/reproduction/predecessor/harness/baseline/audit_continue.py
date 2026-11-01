# SPDX-License-Identifier: Apache-2.0
"""Terminal-only audit. Explicit inputs and root joins are required; no discovery."""
import argparse
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import HERE,OUTER_SECONDS,baseline,load,read,save,sha
from checks import ACKS,AUTH,CLOCK,CONTEXT,MODEL,NS,QUALITY,REPORT,SEAL,check_continuation,digest,require


def checkpoint(row):
    return {**{k:row[k] for k in ('task_id','prompt','max_attempts','revision','owner_epoch')},
        'state':json.loads(row['state']),'metadata':json.loads(row['metadata']),
        'operation':None if row['inflight'] is None else json.loads(row['inflight']),
        'requires_reconciliation':bool(row['reconciliation'])}


def audit(bindings,output,*,parent_joined=False,observer_joined=False):
    require(parent_joined and observer_joined,'Root must join both retained processes first')
    bound=load(bindings,installed=True);case=bound['case'];work=case/'hermes-task'
    output=Path(output)
    if not output.is_absolute() or output.is_relative_to(case) or output.exists():raise ValueError('Fresh external audit output required')
    output.mkdir(exist_ok=False)
    receipt={'schema':'private.continuation.installed-audit.v1','passed':False,'checks':{},
        'scope':'One installed same-window explicit Continue on original IQ3_S task; no reboot/general M2/performance claim.'}
    observed={}
    def track(path):
        path=Path(path).resolve(strict=True)
        value=sha(path)
        if str(path) in observed:require(observed[str(path)]==value,'Input changed during terminal audit')
        observed[str(path)]=value;return path
    def data(path):return read(track(path))
    def rows(path):return [json.loads(x) for x in track(path).read_text().splitlines() if x.strip()]
    def check(name,condition):
        receipt['checks'][name]=bool(condition);require(bool(condition),name)
    try:
        parent=data(Path(str(case)+'.supervisor.private.json'))
        check('normal_retained_parent_exit',parent['exit_code']==0 and parent['retained_case_handle_exited'] is True
            and not parent['timed_out'] and not parent['emergency_termination_attempted']
            and parent['supervision_error'] is None and parent['supervision_errors']==[]
            and parent['task_deadline_s']==parent['successor_budget_s']==900 and parent['outer_deadline_s']==OUTER_SECONDS)
        result=data(case/'result.private.json');e=data(case/'continuation-evidence.private.json');recorded=deepcopy(e)
        plan=data(work/'plan.json');initial=data(case/'original-checkpoint.private.json')
        check('accepted_real_case',result['fixture'] is False and result['task_completed'] is True
            and result['case']=='gui-iq3s-installed-explicit-continue'
            and all(result[k] is True for k in ('clean_stop','qualification_case_passed','case_checks_and_cleanup_passed',
                'asyncio_teardown_completed','continuation_case_checks_passed')))
        e['sealed_before']=data(case/'sealed-predecessor.private.json');e['history_before']=data(case/'sealed-history.private.json')
        e['paused']=data(case/'paused-checkpoint.private.json')
        grant=e['grant'];successor=grant['payload']['successor_id']
        check('explicit_successor_identifier',type(successor) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',successor) is not None)
        diagnostics=work/'executions'/successor
        check('execution_scoped_diagnostics',diagnostics.resolve(strict=True)==diagnostics and diagnostics.is_relative_to(work/'executions'))
        check('actual_grant_file',data(diagnostics/'grant.json')==grant)
        dbpath=track(work/'task.sqlite3')
        with sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            tasks={x['task_id']:dict(x) for x in db.execute('SELECT * FROM tasks')}
            histories={key:[list(row) for row in db.execute('SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision',(key,))] for key in tasks}
            check('task_database_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
        e['sealed_after']=checkpoint(tasks[e['sealed_before']['task_id']]);e['history_after']=histories[e['sealed_before']['task_id']]
        e['selected']=checkpoint(tasks[successor]);e['authority']=checkpoint(tasks[e['authority_task_id']])
        e['authority_history']=[{'revision':r,'event':event,'payload':json.loads(payload)} for r,event,payload in histories[e['authority_task_id']]]
        e['selected_initial']=data(case/'selected-initial.private.json')
        creation=histories[successor][0];created=json.loads(creation[2])
        check('actual_successor_creation',creation[0]==e['selected_initial']['revision']==0
            and created['state']==e['selected_initial']['state'] and created['metadata']==e['selected_initial']['metadata'])
        check('all_task_owners_released',all(x['owner_epoch'] is None and x['inflight'] is None and not x['reconciliation'] for x in tasks.values()))
        request_namespace='adaptive_inference.control_requests.v1'
        oldacks=e['sealed_after']['state'][ACKS]
        newacks=e['selected']['state'][ACKS]
        oldrequests=json.loads(tasks[oldacks['mailbox_task_id']]['state'])[request_namespace]
        newrequests=json.loads(tasks[newacks['mailbox_task_id']]['state'])[request_namespace]
        check('exact_five_scoped_task_records',set(tasks)=={e['sealed_before']['task_id'],successor,e['authority_task_id'],
            oldacks['mailbox_task_id'],newacks['mailbox_task_id']})
        check('actual_old_pause_control_prefix',len(oldrequests)==len(oldacks['receipts'])==3
            and [x['command'] for x in oldrequests]==['pause','resume','pause']
            and digest({'requests':oldrequests,'receipts':oldacks['receipts']})==e['sealed_after']['state'][SEAL]['control_prefix_sha256']
            and all({k:a[k] for k in ('sequence','request_id','command')}==r and a['outcome']=='applied'
                for r,a in zip(oldrequests,oldacks['receipts'])))
        check('actual_selected_control_receipts',len(newrequests)==len(newacks['receipts'])==2
            and all({k:a[k] for k in ('sequence','request_id','command')}==r and a['outcome']=='applied'
                for r,a in zip(newrequests,newacks['receipts'])))
        e['successor_controls']=[{**row,'owner_acknowledged':True} for row in newacks['receipts']]
        e['wire_before']=data(case/'paused-wire.private.json');e['wire_after']=data(work/'wire-observations.json')
        check('exact_wire_bytes_at_authorization',data(case/'sealed-wire.raw.private.json')==e['wire_before']
            and sha(case/'sealed-wire.raw.private.json')==grant['wire_file_sha256'])
        e['effects_before_sha256']=data(case/'paused-effects.private.json')['sha256']
        e['effects_after_sha256']=sha(track(work/'effect-receipts.jsonl'));e['effects']=rows(work/'effect-receipts.jsonl')
        e['report']=data(work/'work/report.json');e['report_sha256']=sha(work/'work/report.json')
        oldpid,newpid=[x['pid'] for x in e['lifetimes']]
        workerpath=track(diagnostics/f'result-{newpid}.json');e['worker']=data(workerpath);e['worker_result_sha256']=sha(workerpath)
        e['selection_status']=data(case/'selected-status.private.json');e['readiness']=data(case/'selected-readiness.private.json')
        check('actual_selected_readiness_files',e['readiness']['value']==data(diagnostics/'controller-ready.json')
            and e['readiness']['boot']==data(diagnostics/f'bootstrap-{newpid}.json'))
        check('recorded_matches_actual_terminal_inputs',e==recorded)
        for name in check_continuation(e):check(name,True)
        check('terminal_checkpoint_matches_database',data(case/'terminal-checkpoint.private.json')==e['selected']
            and data(case/'accepted-before-stop.private.json')==e['selected'])
        oldworker=data(work/f'result-{oldpid}.json');marker=e['sealed_before']['state'][SEAL]
        proof=oldworker['paused_expiry'];expiry=data(case/'expiry-observation.private.json')
        check('retained_expiry_receipt',proof==expiry['expiry_receipt'] and proof['pid']==oldpid
            and proof['task_completed'] is False and proof['state_sha256']==digest(e['sealed_before']['state'])
            and proof['native_history_sha256']==digest(e['sealed_before']['state']['native_history'])
            and proof['revision']==e['sealed_before']['revision'] and proof['task_id']==initial['task_id']
            and all(proof[k]==marker[k] for k in ('deadline_clock','deadline_monotonic','pause_request_id','pause_sequence',
                'pause_observed_at_monotonic','sealed_at_monotonic','control_prefix_sha256'))
            and oldworker['passed'] is False and oldworker['completed'] is False and not oldworker.get('cleanup_errors'))
        csvrows=list(csv.DictReader(track(work/'work/orders.csv').read_text().splitlines()))
        oracle={'rows':len(csvrows),'units':sum(int(x['quantity']) for x in csvrows),
            'total_cents':sum(int(x['quantity'])*int(x['unit_cents']) for x in csvrows),'by_item':{}}
        for x in csvrows:oracle['by_item'][x['item']]=oracle['by_item'].get(x['item'],0)+int(x['quantity'])*int(x['unit_cents'])
        check('original_csv_oracle',oracle==REPORT==e['report']==result['report'])
        check('original_plan_quality_scope',sha(work/'plan.json')==result['initial_plan_sha256'] and plan['max_requests']==8
            and plan['model']==MODEL and plan['quality']==QUALITY and plan['fixture'] is False
            and plan['sdk_revision']==e['worker']['sdk_revision']==oldworker['sdk_revision']=='14e1e43a23761b369641208e204365cd6cb9399d'
            and e['selected']['prompt']==initial['prompt'] and all(sha(track(p))==h for p,h in plan['pins'].items()))
        config=data(work/'home/config.yaml')
        check('original_context_config',config['model']['context_length']==65536 and config['compression']['threshold']==.8)
        state=e['selected']['state'];meta=e['selected']['metadata'];native=track(work/'home/state.db')
        with sqlite3.connect(native.as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            native_rows=[dict(x) for x in db.execute('SELECT * FROM messages ORDER BY id')]
            sessions=[dict(x) for x in db.execute('SELECT * FROM sessions')]
            check('native_database_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                and len(sessions)==1 and sessions[0]['id']==state['session_id'] and not sessions[0].get('parent_session_id'))
        # Exact projection reused from the retained expiry/full02 auditor.
        decoded=[]
        for row in native_rows:
            message={'role':row['role'],'content':row['content'],'_db_persisted':True,'_row_id':row['id'],
                'message_uid':row['message_uid'],'timestamp':row['timestamp']}
            for column,key in (('tool_call_uids','_tool_call_uids'),('tool_call_uid','_tool_call_uid'),('tool_calls','tool_calls')):
                if row[column]:message[key]=json.loads(row[column]) if column!='tool_call_uid' else row[column]
            for key in ('tool_call_id','tool_name','effect_disposition','finish_reason','reasoning'):
                if row[key]:message[key]=row[key]
            if row['role']=='assistant' and row['reasoning_content'] is not None:message['reasoning_content']=row['reasoning_content']
            decoded.append(message)
        check('actual_native_history_equals_successor',decoded==state['native_history']
            and all(x['session_id']==state['session_id'] and x['active']==1 and x['compacted']==0 for x in native_rows))
        from adaptive_inference.desktop.hermes.recovery import verify_validation_rows
        verify_validation_rows(decoded,state,meta.get('pre_effect_validator'));check('native_validation_feedback',True)
        runtime=result['runtime_binding'];wire=e['wire_after']
        check('actual_runtime_request_lineage',[x['request_id'] for x in runtime['request_history']]==[x['gateway_request_id'] for x in wire]
            and all(x['status']==200 and not x['backend_completion_uncertain'] and x['prediction_matches_execution_runtime'] for x in runtime['request_history']))
        check('reported_cumulative_result',result['provider_calls']==len(wire) and result['dispatched_file_effects']==1
            and result['effect_receipts_sha256']==e['effects_after_sha256'] and result['report_sha256']==e['report_sha256'])
        releases=[x['release'] for x in result['handoff_events'] if 'release' in x]
        check('complete_restore_release_ledger',result['full_handoff_ledger'] is True and len(releases)>=2
            and len(releases)==sum(x.get('restore_requested') is True for x in result['handoff_events'])==len(runtime['verified_owner_bindings']))
        for release in releases:
            native_result=data(Path(release['identity']['run'])/'result.json');count=native_result['processes']['retained_total']
            check('native_owner_'+native_result['owner_id'],type(count) is int and count>0 and native_result['owner_id']==release['owner_id']
                and native_result['owner']==release['identity']['owner'] and native_result['state']=='stopped' and not native_result['running']
                and native_result['stop_reason']=='requested' and native_result['cleanup_confirmed'] and native_result['server_exit_code']==0
                and native_result['processes']['active']==[] and native_result['processes']['confirmed_exits']==count
                and all(x['exited'] for x in native_result['processes']['completed_tail'])
                and all(release[k] is True for k in ('released','cleanup_confirmed','port_free'))
                and release['confirmed_process_exits']==release['retained_processes']==count
                and all(x['exited'] for x in release['retained_at_stop']))
        check_ui_and_observer(case,e,result,expiry,data,rows,check)
        cleanup=data(case/'host/result.json')
        check('host_native_cleanup',cleanup==result['cleanup'] and all(cleanup[k] is True for k in ('closed','normal_release_confirmed','owned_children_exited'))
            and all(cleanup[k] is None for k in ('primary_error','controller_fault','cleanup_error')))
        gui=result['gui_cleanup'];listener=result['listener_cleanup'];transport=result['transport_cleanup']
        check('actual_gui_cleanup',gui['child_exit_code']==0 and gui['pending_pipe_operations']==0 and gui['faults']==[]
            and all(gui[k] for k in ('closed','child_exit_observed','session_revoked','authentication_revoked','pipe_threads_joined','pipe_handles_closed','verifier_handle_closed','process_handle_closed')))
        check('listener_transport_closed',listener['accepted_connections']>0 and listener['clean_close'] and listener['resources_closed'] and listener['listener_closed']
            and not any(listener[k] for k in ('accepting','owned_connection_pending','setup_pending','handler_pending')) and listener['faults']==[]
            and transport['closed'] and transport['stop_requested'] and transport['stop_confirmed']
            and all(transport[k]==0 for k in ('pending_mutations','unknown_mutations','handlers','pending_connections','stream_close_failures')) and transport['faults']==[])
        exits=result['all_retained_process_exits']
        check('all_three_children_joined_job_empty',len(exits)==3
            and sum(x['pid']==oldpid and x['exit_code']==5 for x in exits)==1
            and sum(x['pid']==newpid and x['exit_code']==0 for x in exits)==1
            and sorted(x['exit_code'] for x in exits)==[0,0,5]
            and result['actual_job_members_after_cleanup']==[parent['pid']])
        check('full_cleanup_ledger_consistent',len(result['cleanup']['events'])==len(result['handoff_events'])
            and all({k:v for k,v in a.items() if k!='release'}=={k:v for k,v in b.items() if k!='release'}
                and ('release' not in b or all(a['release'][k]==v for k,v in b['release'].items()))
                for a,b in zip(result['handoff_events'],result['cleanup']['events'])))
        check_package(bound,result,plan,parent,data,track,check)
        check('all_terminal_inputs_unchanged',all(sha(p)==h for p,h in observed.items()))
        receipt.update(passed=True,input_sha256=observed,bindings_sha256=bound['bindings_sha256'],
            provider_calls=len(wire),physical_writes=1,execution_budgets=[900,900],outer_deadline_s=OUTER_SECONDS)
    except BaseException as error:
        receipt['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        save(output/'audit.private.json',receipt)
    return receipt


def check_ui_and_observer(case,e,result,expiry,data,rows,check):
    old=baseline('audit_expiry.py');ui=data(case/'ui-observations.private.json');g=e['grant']
    check('one_real_click_each_same_window',ui['first_resume_clicks']==ui['manual_pause_clicks']==ui['continue_clicks']==ui['stop_clicks']==1
        and ui['retry_clicks']==0 and ui['window_id']==e['gui_binding']['hwnd']==result['retained_gui_binding']['hwnd'])
    for action in ('resume','pause','continue','stop'):
        check(action+'_actual_clock_bracket',old.qpc_bracket(ui,action+'_qpc_before',action+'_qpc_after')
            and all(type(ui.get(action+'_utc_'+side)) is str and ui[action+'_utc_'+side] for side in ('before','after')))
    seen=ui['post_expiry_gui'];after=ui['post_continue_gui']
    check('saved_then_selected_same_window',seen['same_window'] is True and seen['stop_available'] is True and seen['task_pending'] is True
        and 'budget' in seen['waiting_text'].lower() and 'saved' in seen['waiting_text'].lower()
        and seen['hwnd']==after['hwnd']==ui['window_id'] and old.qpc_bracket(seen,'qpc_before','qpc_after')
        and old.qpc_bracket(after,'qpc_before','qpc_after') and after['same_window'] is True and after['stop_available'] is True
        and after['task_text']=='Task completed.' and after['task_accepted'] is True
        and expiry['at_deadline_clock']<=seen['qpc_before']<=seen['qpc_after']<ui['continue_qpc_before']
        and ui['continue_qpc_before']<=g['authorized_at']<ui['stop_qpc_before']
        and ui['continue_qpc_after']<=after['qpc_before']<=after['qpc_after']<ui['stop_qpc_before'])
    marker=e['sealed_before']['state'][SEAL]
    check('genuine_pause_before_deadline',ui['resume_qpc_after']<ui['pause_qpc_before']
        and ui['pause_qpc_after']<marker['deadline_monotonic']<=marker['sealed_at_monotonic']
        and marker['sealed_at_monotonic']<=expiry['at_deadline_clock'] and result['expiry_service_observation_seconds']>=10)
    trace=rows(Path(str(case)+'.api-trace.private.jsonl'));observer=data(Path(str(case)+'.api-trace.private.receipt.json'))
    good=[x for x in trace if 'gateway_status' in x and 'observation_error' not in x]
    check('observer_actual_source_and_clock',observer['source_unchanged'] is True and observer['source_sha256']==sha(HERE/'observe_continue.py')
        and observer['deadline_clock']==CLOCK and observer['task_completion_claimed'] is False and observer['active_case_file_contents_read'] is False
        and all(old.qpc_bracket(x,'reader_before_deadline_clock','reader_after_deadline_clock') for x in trace)
        and len(trace)==observer['samples'] and sum('gateway_status' in x for x in trace)==observer['valid_responses'])
    intervals=[(expiry['at_deadline_clock'],ui['continue_qpc_before']),(ui['continue_qpc_after'],ui['stop_qpc_before'])]
    check('observed_same_service_before_and_after_continue',{x['gateway_status']['instance'] for x in good}=={e['gateway_instance']}
        and all(any(lo<=x['reader_before_deadline_clock']<=x['reader_after_deadline_clock']<hi for x in good) for lo,hi in intervals))
    # Connection refusal, timeout, or observer exit status never proves cleanup.


def check_package(bound,result,plan,parent,data,track,check):
    identity=bound['identity'];host=data(bound['inputs']['host_install']);worker=data(bound['inputs']['worker_install'])
    check('actual_installed_payload_both_interpreters',host['passed'] is True and worker['passed'] is True
        and identity==host['package_identity']==worker['package_identity']==plan['package_identity']==result['source']['installed_package']
        and all(sha(track(Path(row['package_root'])/name))==h for row in (host,worker) for name,h in identity['files'].items()))
    with zipfile.ZipFile(bound['inputs']['wheel']) as archive:
        payload={p.removeprefix('adaptive_inference/'):hashlib.sha256(archive.read(p)).hexdigest()
            for p in archive.namelist() if p.startswith('adaptive_inference/') and p.endswith('.py')}
    check('wheel_payload_exact',payload==identity['files'])
    check('harness_sources_bound',parent['harness_manifest']==result['harness']['manifest_sha256']==bound['manifest_sha256']
        and parent['bindings_sha256']==result['harness']['bindings_sha256']==bound['bindings_sha256']
        and parent['parent_source_unchanged'] is True
        and parent['parent_source_sha256_before']==parent['parent_source_sha256_after']==sha(HERE/'run_continue.py'))
    gate=data(bound['inputs']['deployment_gate']);sdk=data(bound['inputs']['installed_sdk']);clock=data(bound['inputs']['clock_probe'])
    check('deployment_sdk_clock_bound',gate['passed'] is True and all(sha(track(p))==h for p,h in gate['input_sha256'].items())
        and sdk['passed'] is True and sdk['installed_mode'] is True and sdk['package_identity']==identity
        and clock['passed'] is True and clock['mode']=='installed' and clock['deadline_clock']==CLOCK
        and clock['profile_sha256']==bound['value']['inputs']['profile']['sha256'])
    from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES
    check('exact_twenty_sdk_sources',len(SDK_FILES)==20 and all(sha(track(Path(plan['sdk'])/name))==h for name,h in SDK_FILES.items()))
    check('bound_inputs_still_exact',load(bound['path'],installed=True)['bindings_sha256']==bound['bindings_sha256'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--parent-joined',action='store_true');parser.add_argument('--observer-joined',action='store_true')
    args=parser.parse_args()
    audit(args.bindings,args.output,parent_joined=args.parent_joined,observer_joined=args.observer_joined)
    return 0


if __name__=='__main__':raise SystemExit(main())
