# SPDX-License-Identifier: Apache-2.0
"""Terminal-only replay of actual task files, retained cleanup and installed inputs."""
import argparse
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import HERE,OUTER_SECONDS,load,read,save,sha
from checks import check_handover
from selected_source import selected_source_matches
from evidence import task_disk,preservation,checkpoint
from safe_wait import sealed_disk,selected_disk,SEAL,ACKS
from qpc import qpc_bracket


def audit(binding,output,*,parent_joined=False,observer_joined=False):
    if parent_joined is not True or observer_joined is not True:
        raise ValueError('Root must join both retained parent and observer first')
    bound=load(binding,installed=True);case=bound['case'];output=Path(output)
    if not output.is_absolute() or output.exists() or output.is_relative_to(case):
        raise ValueError('Fresh terminal-only audit output required')
    output.mkdir(exist_ok=False)
    receipt={'schema':'private.safe-wait-handover.installed-audit.v1','passed':False,'checks':{},
        'scope':'One installed IQ3_S safe admission-wait expiry, explicit Continue, inventory -> welcome handover in one retained host. Inventory oracle checked; welcome format-only. No reboot/performance claim.'}
    observed={}
    def track(path):
        path=Path(path).resolve(strict=True);pin=sha(path)
        if str(path) in observed and observed[str(path)]!=pin:raise ValueError('Terminal input changed')
        observed[str(path)]=pin;return path
    def data(path):return read(track(path))
    def rows(path):return [json.loads(x) for x in track(path).read_text().splitlines() if x.strip()]
    def check(name,value):
        receipt['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    try:
        result=data(case/'result.private.json');parent=data(Path(str(case)+'.supervisor.private.json'))
        check('normal_parent',parent['exit_code']==0 and parent['retained_case_handle_exited'] is True
            and parent['timed_out'] is False and parent['emergency_termination_attempted'] is False
            and parent['supervision_error'] is None and parent['supervision_errors']==[]
            and parent['task_deadline_s']==parent['second_task_budget_s']==900 and parent['outer_deadline_s']==OUTER_SECONDS)
        check('ordinary_host_accepted',result['case']=='gui-iq3s-safe-wait-continue-two-tasks'
            and all(result.get(k) is True for k in ('clean_stop','task_completed','qualification_case_passed','asyncio_teardown_completed','manual_stop_observed','retained_obligations_joined'))
            and not any(result.get(k) for k in ('primary_error','cleanup_error','qualification_observer_failure','joined_obligation_errors')))
        e=data(case/'handover-evidence.private.json');recorded=deepcopy(e)
        recovery=e['safe_wait'];grant=recovery['grant'];logical=e['logical_original']
        oldpid=recovery['lifetimes'][0]['pid'];selectedpid=recovery['lifetimes'][1]['pid']
        run=case/'hermes-task';diagnostics=run/'executions'/grant['payload']['successor_id']
        for path in (run/'task.sqlite3',run/f'result-{oldpid}.json',diagnostics/'grant.json',
                diagnostics/f'result-{selectedpid}.json',diagnostics/f'bootstrap-{selectedpid}.json',
                diagnostics/'controller-ready.json'):
            track(path)
        expired=data(case/'wait-expired.private.json')
        check('actual_expired_capture',recovery['sealed_before']==expired['sealed']
            and recovery['wire_before']==expired['wire'] and recovery['effects_before']==expired['effects']
            and recovery['gui_resume_ids']==expired['gui_resume_ids'] and recovery['gui_binding']==expired['gui_binding']
            and expired['status']['waiting_reason']=='budget_expired'
            and expired['status']['continuation']=={'phase':'available','request_id':None}
            and expired['qpc']>=expired['sealed']['checkpoint']['state'][SEAL]['sealed_at_monotonic'])
        wire_raw=track(case/'wait-sealed-wire.raw.private.json')
        check('actual_saved_wire',read(wire_raw)==recovery['wire_before']
            and sha(wire_raw)==recovery['wire_before_file_sha256']==expired['wire_file_sha256'])
        recovery['sealed_after']=sealed_disk(run,logical,oldpid)
        actual=selected_disk(run,logical,grant,e['host_epoch'],selectedpid)
        for key,value in actual.items():recovery[key]=value
        check('actual_selected_status_initial',data(case/'selected-status.private.json')==recovery['selection_status']
            and data(case/'selected-initial.private.json')==recovery['selected_initial'])
        ready=data(case/'selected-readiness.private.json')
        check('actual_selected_readiness',ready==recovery['readiness']
            and data(diagnostics/'controller-ready.json')==ready['value']
            and data(diagnostics/f'bootstrap-{selectedpid}.json')==ready['boot'])
        check('accepted_recovery_preserved',data(case/'safe-wait-accepted.private.json')==recovery)
        for index,row in enumerate(e['tasks']):
            run=Path(row['run']).resolve(strict=True)
            expected=case/'hermes-task' if index==0 else case/'tasks'/row['checkpoint']['task_id']
            check('task_'+str(index)+'_exact_private_namespace',run==expected and run.is_relative_to(case))
            for name in ('task.sqlite3','home/state.db','home/config.yaml','plan.json','wire-observations.json','effect-receipts.jsonl'):
                track(run/name)
            local=run/'executions'/grant['payload']['successor_id'] if index==0 else run
            track(local/f"result-{row['lifetime']['pid']}.json")
            disk=task_disk(run,row['checkpoint']['task_id'],row['lifetime']['pid'],row['original'],grant=grant if index==0 else None)
            for name in (*disk['input_sha256'],disk['artifact_name']):track(run/'work'/name)
            check('task_'+str(index)+'_actual_disk_projection',all(row[key]==value for key,value in disk.items()))
            specrole='inventory_spec' if index==0 else 'welcome_spec'
            inputrole='inventory_input' if index==0 else 'welcome_input'
            from adaptive_inference.task_spec import TaskSpec
            spec=TaskSpec.from_bytes(track(bound['inputs'][specrole]).read_bytes())
            check('task_'+str(index)+'_exact_input_contract',spec==TaskSpec.from_metadata(row['checkpoint']['metadata'])
                and row['checkpoint']['prompt']==spec.prompt
                and disk['input_sha256']=={bound['inputs'][inputrole].name:sha(track(bound['inputs'][inputrole]))})
            for path,pin in row['plan']['pins'].items():check('pinned_'+str(index)+'_'+Path(path).name,sha(track(path))==pin)
            check('task_'+str(index)+'_installed_identity',row['plan']['package_identity']==bound['identity'])
            with closing(sqlite3.connect((run/'task.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                actual=list(db.execute('SELECT task_id,owner_epoch,inflight,reconciliation FROM tasks'))
            expected_ids=({logical['task_id'],recovery['sealed_after']['mailbox']['task_id'],recovery['authority_task_id'],
                grant['payload']['successor_id'],row['checkpoint']['state'][ACKS]['mailbox_task_id']} if index==0 else
                {row['checkpoint']['task_id'],row['checkpoint']['state'][ACKS]['mailbox_task_id']})
            check('task_'+str(index)+'_exact_released_records',{x[0] for x in actual}==expected_ids
                and all(x[1] is None and x[2] is None and not x[3] for x in actual))
        e['a_before']=preservation(data(case/'inventory-accepted.private.json'))
        e['a_after']=preservation(e['tasks'][0])
        check('B_accepted_snapshot_unchanged',preservation(data(case/'welcome-accepted.private.json'))==preservation(e['tasks'][1]))
        e['admission_checkpoint']=checkpoint(track(case/'admission.sqlite3'),e['admission_task_id'])
        acp=e['admission_checkpoint'];state=acp['state']['adaptive_inference.task_admission.v1']
        e['admission']={'selection_revision':state['selection_revision'],'selected':state['selected'],
            'admissions':state['admissions'],'operation':acp['operation'],
            'requires_reconciliation':acp['requires_reconciliation'],
            'host_stopped':bool(state['admissions'] and state['admissions'][-1]['phase']=='stopped'),
            'stop_fenced':bool(acp['operation'] or acp['requires_reconciliation'] or
                state['admissions'] and state['admissions'][-1]['phase'] not in ('released','abandoned','stopped'))}
        check('actual_admission_grant',len(e['admission']['admissions'])==1
            and e['admission']['admissions'][0]['reservation']==e['transition']['reservation']
            and acp['metadata']['adaptive_inference.task_admission.v1']=={
                'host_generation':e['host_epoch'],'tasks_root':str(case/'tasks'),
                'initial':{'task_id':logical['task_id'],'run':str(case/'hermes-task')}}
            and e['transition']['reservation']['payload']['host_generation']==e['host_epoch'])
        expected_source={'task_spec_path':str(bound['inputs']['welcome_spec']),
            'task_spec_sha256':sha(track(bound['inputs']['welcome_spec'])),
            'task_inputs':str(bound['inputs']['welcome_input'].parent)}
        check('actual_selected_source_input_binding',selected_source_matches(e['selected_source'],expected_source))
        ready=data(case/'welcome-paused-ready.private.json')
        check('actual_B_paused_readiness',ready['paused']==e['transition']['paused'] and ready['ready']==e['transition']['ready']
            and ready['source']==e['selected_source'] and ready['host_identity']==e['host_identity_before'])
        check('actual_A_original',data(case/'original-checkpoint.private.json')==logical)
        check('recorded_matches_actual_disk',e==recorded)
        for name in check_handover(e):check(name,True)
        check_ui_observer(bound,e,result,data,rows,check)
        cleanup=data(case/'host/result.json')
        check('actual_native_host_cleanup',cleanup==result['cleanup'] and all(cleanup[k] is True for k in ('closed','normal_release_confirmed','owned_children_exited'))
            and all(cleanup[k] is None for k in ('primary_error','controller_fault','cleanup_error')))
        events=result['handoff_events'];releases=[x['release'] for x in events if 'release' in x]
        check('complete_native_release_count',len(releases)>=2 and len(releases)==sum(x.get('restore_requested') is True for x in events))
        for index,release in enumerate(releases):
            native=data(Path(release['identity']['run'])/'result.json');count=native['processes']['retained_total']
            check('native_owner_'+str(index),type(count) is int and count>0 and native['owner_id']==release['owner_id']
                and native['state']=='stopped' and not native['running'] and native['stop_reason']=='requested'
                and native['cleanup_confirmed'] is True and native['server_exit_code']==0
                and native['processes']['active']==[] and native['processes']['confirmed_exits']==count
                and all(x['exited'] for x in native['processes']['completed_tail'])
                and all(release[k] is True for k in ('released','cleanup_confirmed','port_free'))
                and release['confirmed_process_exits']==release['retained_processes']==count
                and all(x['exited'] for x in release['retained_at_stop']))
        wires=[w for task in e['tasks'] for w in task['wire']];history=result['gateway_history']
        check('actual_gateway_request_lineage',[x['request_id'] for x in history]==[x['gateway_request_id'] for x in wires]
            and all(x['status']==200 and not x['backend_completion_uncertain'] and x['prediction_matches_execution_runtime'] for x in history))
        check('real_two_task_totals',result['provider_calls']==len(wires)<=16 and result['dispatched_file_effects']==2
            and result['tasks_semantic_validation']==['oracle_matched','not_checked'])
        check('containing_job_empty',result['actual_job_members_after_cleanup']==[parent['pid']]
            and result['all_retained_process_exits']==[{k:x[k] for k in ('pid','exit_code')} for x in e['retained_children']]
            and [x['exit_code'] for x in result['all_retained_process_exits']]==[0,6,0,0,0])
        check_package(bound,result,parent,data,track,check)
        check('all_inputs_unchanged',all(sha(path)==pin for path,pin in observed.items()))
        receipt.update(passed=True,input_sha256=observed,bindings_sha256=bound['bindings_sha256'],
            provider_calls=len(wires),physical_writes=2,execution_budgets=[900,900,900],outer_deadline_s=OUTER_SECONDS,
            tasks_semantic_validation=['oracle_matched','not_checked'])
    except BaseException as error:
        receipt['error']=type(error).__name__+': '+str(error);raise
    finally:save(output/'audit.private.json',receipt)
    return receipt


def check_ui_observer(bound,e,result,data,rows,check):
    case=bound['case'];ui=data(case/'ui-observations.private.json')
    check('genuine_real_actions',all(ui[k]==1 for k in ('resume_a_clicks','continue_clicks','new_task_clicks','resume_b_clicks','stop_clicks'))
        and all(ui[k]==0 for k in ('retry_clicks','pause_clicks')))
    for action in ('resume_a','continue','new_task','resume_b','stop'):
        check(action+'_clock_bracket',qpc_bracket(ui,action+'_qpc_before',action+'_qpc_after'))
        before=datetime.fromisoformat(ui[action+'_utc_before']);after=datetime.fromisoformat(ui[action+'_utc_after'])
        check(action+'_wall_bracket',before.tzinfo is not None and after.tzinfo is not None and before<=after)
    for action,task in zip(('resume_a','resume_b'),e['tasks']):
        before=datetime.fromisoformat(ui[action+'_utc_before']).timestamp()
        control=e['safe_wait']['sealed_after']['prefix']['receipts'][1] if action=='resume_a' else task['controls'][1]
        ack=datetime.fromisoformat(control['acknowledged_at_utc']).timestamp()
        check(action+'_before_actual_provider',before<=ack<=task['wire'][0]['started_at'])
    check('actual_action_order',ui['resume_a_qpc_after']<ui['continue_qpc_before']<=ui['continue_qpc_after']<ui['new_task_qpc_before']
        <=ui['new_task_qpc_after']<ui['resume_b_qpc_before']<=ui['resume_b_qpc_after']<ui['stop_qpc_before'])
    check('actual_window_bindings',ui['window_a']==e['tasks'][0]['gui_binding'] and ui['window_b']==e['tasks'][1]['gui_binding']
        and ui['selected_source']==e['selected_source'])
    ready=data(case/'welcome-paused-ready.private.json')
    check('B_observed_paused_before_genuine_resume',ui['new_task_qpc_before']<ready['qpc']<ui['resume_b_qpc_before'])
    recovery=e['safe_wait'];grant=recovery['grant'];n=grant['wire_prefix_count']
    accepted=data(case/'inventory-accepted-time.private.json')
    check('accepted_A_observed_before_new_task',accepted['deadline_clock']=='windows-qpc-seconds-v1'
        and accepted['execution_id']==e['tasks'][0]['checkpoint']['task_id']
        and accepted['revision']==e['tasks'][0]['checkpoint']['revision']
        and recovery['readiness']['finished_qpc']<=accepted['qpc']<ui['new_task_qpc_before'])
    check('grant_follows_genuine_continue',ui['continue_qpc_before']<=grant['authorized_at']<=recovery['readiness']['started_qpc'])
    ack=datetime.fromisoformat(recovery['successor_controls'][1]['acknowledged_at_utc']).timestamp()
    check('Continue_before_derived_resume_and_new_provider',datetime.fromisoformat(ui['continue_utc_before']).timestamp()<=ack
        <=recovery['wire_after'][n]['started_at'] and recovery['readiness']['value']['observed_at']<=recovery['wire_after'][n]['started_at'])
    check('expired_window_observed_before_continue',qpc_bracket(ui,'expired_gui_qpc_before','expired_gui_qpc_after')
        and recovery['sealed_after']['checkpoint']['state'][SEAL]['sealed_at_monotonic']<=ui['expired_gui_qpc_before']
        <=ui['expired_gui_qpc_after']<ui['continue_qpc_before'] and ui['expired_window']==recovery['gui_binding'])
    trace=rows(Path(str(case)+'.api-trace.private.jsonl'))
    observer=data(Path(str(case)+'.api-trace.private.receipt.json'))
    good=[x for x in trace if 'gateway_status' in x and 'observation_error' not in x]
    check('bounded_observer_identity',observer['source_unchanged'] is True and observer['source_sha256']==sha(HERE/'observe_handover.py')
        and observer['task_completion_claimed'] is False and observer['active_case_file_contents_read'] is False
        and len(trace)==observer['samples'] and len(good)==observer['valid_responses']
        and all(qpc_bracket(x,'reader_before_deadline_clock','reader_after_deadline_clock') for x in trace))
    check('same_gateway_before_and_after_handover',{x['gateway_status']['instance'] for x in good}=={e['gateway_instance']}
        and all(any(lo<=x['reader_before_deadline_clock']<=x['reader_after_deadline_clock']<hi for x in good)
            for lo,hi in ((ui['resume_a_qpc_after'],ui['continue_qpc_before']),
                          (ui['expired_gui_qpc_after'],ui['continue_qpc_before']),
                          (ui['continue_qpc_after'],ui['new_task_qpc_before']),
                          (ui['resume_b_qpc_after'],ui['stop_qpc_before']))))
    # Preserve observer end_reason/exit verbatim. Disconnection never proves cleanup.


def check_package(bound,result,parent,data,track,check):
    identity=bound['identity'];host=data(bound['inputs']['host_install']);worker=data(bound['inputs']['worker_install'])
    check('both_actual_installed_packages',host['passed'] is True and worker['passed'] is True
        and identity==host['package_identity']==worker['package_identity']
        and all(sha(track(Path(row['package_root'])/name))==pin for row in (host,worker) for name,pin in identity['files'].items()))
    with zipfile.ZipFile(track(bound['inputs']['wheel'])) as archive:
        actual={name.removeprefix('adaptive_inference/'):hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist() if name.startswith('adaptive_inference/') and name.endswith('.py')}
    check('actual_wheel_runtime',actual==identity['files'])
    check('exact_harness',parent['harness_manifest']==result['harness']['manifest_sha256']==bound['manifest_sha256']
        and parent['bindings_sha256']==result['harness']['bindings_sha256']==bound['bindings_sha256']
        and parent['parent_source_unchanged'] is True and parent['parent_source_sha256_before']==parent['parent_source_sha256_after']==sha(HERE/'run_handover.py'))
    gate=data(bound['inputs']['deployment_gate']);sdk=data(bound['inputs']['installed_sdk']);clock=data(bound['inputs']['clock_probe'])
    check('deployment_source_sdk_clock',gate['passed'] is True and all(sha(track(path))==pin for path,pin in gate['input_sha256'].items())
        and sdk['passed'] is True and sdk['installed_mode'] is True and sdk['package_identity']==identity
        and clock['passed'] is True and clock['mode']=='installed' and clock['deadline_clock']=='windows-qpc-seconds-v1'
        and clock['profile_sha256']==bound['value']['inputs']['profile']['sha256'])
    for path in bound['inputs'].values():track(path)
    check('bound_inputs_still_exact',load(bound['path'],installed=True)['bindings_sha256']==bound['bindings_sha256'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bindings',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--parent-joined',action='store_true')
    p.add_argument('--observer-joined',action='store_true');a=p.parse_args()
    audit(a.bindings,a.output,parent_joined=a.parent_joined,observer_joined=a.observer_joined)


if __name__=='__main__':main()
