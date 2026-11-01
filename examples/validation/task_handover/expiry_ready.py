# SPDX-License-Identifier: Apache-2.0
"""One-shot immutable expiry readiness; never a process or control authority."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import argparse,json,re,sys
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(HERE / '.'));sys.path.insert(0,str(HERE))
from bindings import load,read,save,sha
from record_ui import strict_bytes,phase_from_capture,full_binding,MAX_JSON
from first_inflight import require,digest,time_value,CLOCK,SEAL
NS='adaptive_inference.demand.v1'
CONTEXT='private.case11.pre-resume-expiry-context.v1'
CP_KEYS={'task_id','prompt','max_attempts','metadata','revision','state','operation','requires_reconciliation','owner_epoch'}
LIMIT=1024*1024

def bounded(path,maximum=MAX_JSON):
    with Path(path).open('rb') as stream:raw=stream.read(maximum+1)
    require(len(raw)<=maximum,'immutable_file_oversized')
    return raw

def same(a,b):return type(a) is type(b) and digest(a)==digest(b)

def context_values(original,paused,ready,plan,config,capture,binding_sha,spec_raw,source_raw,case):
    """Only independently retained startup facts, before any candidate expiry."""
    from adaptive_inference.task_spec import TaskSpec
    spec=TaskSpec.from_bytes(spec_raw);work=Path(case)/'hermes-task/work'
    require(set(original)==CP_KEYS and type(original['revision']) is int and original['revision']==0 and original['owner_epoch'] is None and original['operation'] is None and original['requires_reconciliation'] is False,'original_startup_checkpoint')
    require(type(paused) is dict and set(paused)=={'ack','checkpoint','worker_pid'} and set(paused['checkpoint'])==CP_KEYS,'paused_startup_schema')
    cp=paused['checkpoint'];meta=original['metadata'];demand=meta[NS]
    require(all(same(cp[k],original[k]) for k in ('task_id','prompt','max_attempts','metadata')) and original['max_attempts']==8,'startup_task_changed')
    require(TaskSpec.from_metadata(meta)==spec and original['prompt']==spec.prompt and meta.get('pre_effect_validator')==spec.validator_identity(),'startup_bound_TaskSpec')
    require(plan['task_spec']==spec.data and plan['task_spec_sha256']==spec.sha256 and plan['task_id']==original['task_id'] and plan['session_id']==original['state']['session_id'] and plan['fixture'] is False,'startup_plan_binding')
    require(all(same(plan[k],meta[k]) for k in ('model','quality','sdk_revision','deadline_clock')),'startup_quality_binding')
    require(meta['deadline_clock']==CLOCK and demand['task_id']==original['task_id'] and {k:v for k,v in demand.items() if k!='schema'}==plan['demand_identity'],'startup_registration_binding')
    require(type(cp['owner_epoch']) is str and re.fullmatch('[0-9a-f]{32}',cp['owner_epoch']) is not None and cp['operation'] is None and cp['requires_reconciliation'] is False,'startup_worker_owner')
    require(cp['state']['session_id']==original['state']['session_id'] and cp['state']['deadline_clock']==CLOCK and time_value(cp['state']['deadline_monotonic']),'startup_native_session_deadline')
    for state in (original['state'],cp['state']):
        require(state['native_history']==[] and state['tools']==[] and type(state['requests']) is int and state['requests']==0 and state['pending_request'] is None,'no_pre_resume_work')
    require(paused['ack']['request_id']=='initial-pause-before-bootstrap' and paused['ack']['command']=='pause' and paused['ack']['outcome']=='applied' and paused['ack']['owner_acknowledged'] is True,'initial_pause_ack')
    require(set(ready)=={'ready','gui_pid','worker_pid','task_id','paused_owner_acknowledged','model_started','instructions'} and ready['ready'] is True and ready['paused_owner_acknowledged'] is True and ready['model_started'] is False,'original_ready_schema')
    require(type(paused['worker_pid']) is int and 0<paused['worker_pid']<2**53 and type(ready['worker_pid']) is int and ready['worker_pid']==paused['worker_pid'] and ready['task_id']==original['task_id'],'independent_original_worker_pid')
    require(capture['bindings_sha256']==binding_sha,'pre_resume_capture_binding')
    gui=phase_from_capture(capture,'inventory_paused_ready_for_resume','private.case09.pre-resume-ui-binding.v1')
    require(gui['task_id']==original['task_id'] and type(ready['gui_pid']) is int and ready['gui_pid']==gui['pid'],'independent_original_GUI')
    require(config.get('terminal')=={'backend':'local','cwd':str(work)},'startup_exact_local_cwd')
    declaration=spec.data['inputs']
    require(len(declaration)==1 and declaration[0]['name']=='inventory.csv' and len(source_raw)==declaration[0]['bytes'] and digest(source_raw)==declaration[0]['sha256'],'startup_bound_input')
    require(plan['pins'].get(str(work/'inventory.csv'))==declaration[0]['sha256'],'startup_explicit_input_pin')
    return {'original':deepcopy(original),'gui_binding':gui,'worker_pid':paused['worker_pid'],'owner_epoch':cp['owner_epoch'],'deadline_monotonic':cp['state']['deadline_monotonic'],'plan':deepcopy(plan),'initial_pause_id':paused['ack']['request_id'],'A_capture_qpc_after':capture['capture_qpc_after'],
            'worker_creation_scope':'Startup binds worker PID/owner/task; exact retained creation identity and actual exit6/join remain the pinned producer proof, not a separate startup FILETIME observation.'}

def validate_expiry(value,raw_wire,context,resume_before,resume_after):
    """Compose existing detached validators plus context/envelope checks only."""
    from adaptive_inference.desktop.hermes.continuation import safe_state,wire_rows
    from adaptive_inference.control_mailbox import control_prefix_digest,WAIT_EXPIRY_SCHEMA
    from adaptive_inference.desktop.hermes.service_stop import WAIT_RECEIPT_BINDINGS
    require(type(value) is dict and set(value)=={'sealed','identity','wire','wire_file_sha256','effects','gui_resume_ids','qpc','gui_binding','status'},'exact_expiry_envelope')
    require(type(context) is dict and context['schema']==CONTEXT and context['deadline_clock']==CLOCK,'independent_context_required')
    require(all(time_value(t) for t in (resume_before,resume_after,context['capture_qpc_before'],context['capture_qpc_after'],value['qpc'])) and context['capture_qpc_before']<=context['capture_qpc_after']<resume_before<=resume_after<value['qpc'],'pre_resume_context_order')
    original=context['original'];sealed=value['sealed'];cp=sealed['checkpoint']
    require(type(sealed) is dict and set(sealed)=={'checkpoint','history','mailbox','prefix','worker','worker_result_sha256'} and set(cp)==CP_KEYS,'sealed_projection_schema')
    require(all(same(cp[k],original[k]) for k in ('task_id','prompt','max_attempts','metadata')) and cp['state']['session_id']==original['state']['session_id'],'expiry_original_task_context')
    require(same(full_binding(value['gui_binding']),context['gui_binding']),'expiry_full_original_GUI')
    identity=value['identity'];require(type(identity) is dict and set(identity)=={'pid','creation_time_100ns','containing_job_verified'} and type(identity['pid']) is int and identity['pid']==context['worker_pid'] and type(identity['creation_time_100ns']) is int and 0<identity['creation_time_100ns']<2**64 and identity['containing_job_verified'] is True,'producer_retained_worker_identity')
    marker=safe_state(SimpleNamespace(**cp),sealed=True)
    require(marker['schema']==WAIT_EXPIRY_SCHEMA and cp['owner_epoch'] is None and type(cp['revision']) is int and cp['revision']==marker['pre_seal_revision']+1 and marker['owner_epoch']==context['owner_epoch'] and marker['deadline_monotonic']==context['deadline_monotonic'] and resume_after<marker['sealed_at_monotonic']<=value['qpc'],'exact_released_wait_seal')
    prefix=sealed['prefix'];requests=prefix['requests'];receipts=prefix['receipts']
    require(control_prefix_digest(requests,receipts)==marker['control_prefix_sha256'] and len(requests)==marker['request_count'] and len(receipts)==marker['ack_count'] and prefix['pending_request_sha256']==marker['pending_request_sha256'] and prefix['native_history_sha256']==marker['native_history_sha256'],'sealed_control_prefix_binding')
    require(len(receipts)==2 and [r['command'] for r in receipts]==['pause','resume'] and all(r['outcome']=='applied' for r in receipts) and receipts[0]['request_id']==context['initial_pause_id'] and value['gui_resume_ids']==[receipts[1]['request_id']] and all(r['command']=='pause' for r in requests[2:]),'original_pause_and_one_resume')
    rows=wire_rows(raw_wire,SimpleNamespace(**cp),{'gateway':context['plan']['gateway']})
    require(digest(raw_wire)==value['wire_file_sha256'] and same(rows,value['wire']) and len(rows)==1 and cp['state']['requests']==1 and len(cp['state']['tools'])==1 and cp['state']['tools'][0]['name']=='read_file' and value['effects']==[],'completed_first_wire_saved_read_only')
    worker=sealed['worker'];proof=worker['admission_wait_expiry']
    require(worker.get('fixture') is False and worker.get('passed') is False and worker.get('completed') is False and worker.get('controlled') is True and worker.get('control_state')=='waiting_admission' and worker.get('control_reason')=='admission_wait_budget_expired' and type(worker.get('provider_calls')) is int and worker['provider_calls']==1 and worker.get('owner_epoch')==context['owner_epoch'],'source_gated_expired_worker_outcome')
    # Expiry emits no completion-only prompt hash. Exact checkpoint prompt and
    # metadata were already bound to the original pre-Resume context above.
    require(all(same(worker[k],context['plan'][k]) for k in ('model','quality','sdk_revision')),'expired_worker_quality')
    keys={'schema','task_id','registration_id','pid','owner_epoch','revision','state_sha256','task_completed'}|set(WAIT_RECEIPT_BINDINGS)
    require(set(proof)==keys and proof['schema']=='adaptive.cooperative-admission-wait-expiry.v1' and proof['task_completed'] is False and proof['pid']==context['worker_pid'] and type(proof['pid']) is int and proof['task_id']==original['task_id'] and proof['registration_id']==original['metadata'][NS]['registration_id'] and proof['owner_epoch']==context['owner_epoch'] and type(proof['revision']) is int and proof['revision']==cp['revision'] and proof['state_sha256']==digest(cp['state']) and all(same(proof[k],marker[k]) for k in WAIT_RECEIPT_BINDINGS),'worker_seal_original_context')
    require(not any(k in worker for k in ('error','error_type','error_chain_types','error_chain_private','traceback_private','cleanup_error','cleanup_errors','expiry_finalization_failed','selected_execution')),'worker_expiry_error')
    status=value['status'];require(type(status) is dict and status.get('task_status')=='pending' and type(status.get('task_revision')) is int and status['task_revision']==cp['revision'] and status.get('execution_id')==original['task_id'] and type(status.get('execution_generation')) is int and status['execution_generation']==0 and status.get('waiting_reason')=='budget_expired' and status.get('continuation')=={'phase':'available','request_id':None},'original_expired_continuation_available')
    return {'seal_qpc':marker['sealed_at_monotonic'],'receipt_qpc':value['qpc'],'wire_count':len(rows),'scope':'Readiness for actual expired GUI observation only. Physical worker identity/exit6/join relies on pinned producer; unchanged terminal audits decide qualification.'}

def checked(path):
    bound=load(path,installed=True)
    require(bound['case']==Path(read(bound['path'].with_name('bindings.disabled.private.json'))['case']) and bound['value']=={**read(bound['path'].with_name('bindings.disabled.private.json')),'enabled':True},'exact_enabled_case11')
    freeze=read(HERE/'source-manifest.json');require(freeze['enabled'] is False and all(sha(HERE/n)==pin for n,pin in freeze['files'].items()),'reviewed_packet_unchanged')
    return bound

def capture_context(bound):
    from adaptive_inference.execution_clock import verify_execution_clock,execution_now
    case=bound['case'];output=case/'pre-resume-expiry-context.private.json'
    require(not output.exists() and not (case/'result.private.json').exists() and not (case/'wait-expired.private.json').exists(),'fresh_pre_resume_context_only')
    require(verify_execution_clock()==CLOCK,'context_QPC_clock');before=execution_now();inputs={}
    def data(path,maximum=MAX_JSON):
        raw=bounded(path,maximum);inputs[str(path)]=digest(raw);return strict_bytes(raw)
    original=data(case/'original-checkpoint.private.json');paused=data(case/'paused-before-gui.private.json');ready=data(case/'ready.private.json')
    plan=data(case/'hermes-task/plan.json');configpath=case/'hermes-task/home/config.yaml';config=data(configpath);capture=data(case/'pre-resume-binding.private.json')
    from checks import MODEL,QUALITY,SDK
    require(plan['package_identity']==bound['identity'] and plan['model']==MODEL and same(plan['quality'],QUALITY) and plan['sdk_revision']==SDK,'bound_installed_model_quality_context')
    listen=bound['profile']['gateway']['listen'];require(plan['gateway']=='http://'+listen['host']+':'+str(listen['port'])+'/v1','bound_gateway_route_context')
    obs=case/'pre-resume-ui.private.json';require(Path(capture['observation_path'])==obs and same(data(obs),capture['observation']) and inputs[str(obs)]==capture['observation_sha256'],'context_actual_A_observation')
    specpath=bound['inputs']['inventory_spec'];sourcepath=bound['inputs']['inventory_input'];specraw=bounded(specpath,65536);sourceraw=bounded(sourcepath,262144)
    inputs[str(specpath)]=digest(specraw);inputs[str(sourcepath)]=digest(sourceraw)
    require(inputs[str(specpath)]==bound['value']['inputs']['inventory_spec']['sha256'] and inputs[str(sourcepath)]==bound['value']['inputs']['inventory_input']['sha256'],'bound_spec_source_bytes')
    require(plan['pins'].get(str(configpath))==inputs[str(configpath)],'context_config_plan_pin')
    staged=case/'hermes-task/work/inventory.csv';stagedraw=bounded(staged,262144);inputs[str(staged)]=digest(stagedraw);require(stagedraw==sourceraw,'context_staged_input')
    value=context_values(original,paused,ready,plan,config,capture,bound['bindings_sha256'],specraw,sourceraw,case)
    require(capture['capture_qpc_after']<=before,'A_capture_before_context')
    value.update(schema=CONTEXT,deadline_clock=CLOCK,capture_qpc_before=before,capture_qpc_after=execution_now(),bindings_sha256=bound['bindings_sha256'],inputs=inputs)
    require(all(sha(p)==pin for p,pin in inputs.items()),'context_inputs_changed');save(output,value)
    return {'status':'context_captured','sha256':sha(output),'scope':'Before Resume A; no complete binding in stdout.'}

def check_once(bound,resume_before,resume_after,context_sha256):
    from adaptive_inference.execution_clock import verify_execution_clock,execution_now
    case=bound['case'];contextpath=case/'pre-resume-expiry-context.private.json';resultpath=case/'expiry-ready.private.json'
    require(not resultpath.exists() and not (case/'result.private.json').exists(),'one_ready_receipt_before_terminal')
    require(type(context_sha256) is str and re.fullmatch('[0-9a-f]{64}',context_sha256) is not None,'explicit_pre_resume_context_hash_required')
    require(verify_execution_clock()==CLOCK,'expiry_QPC_clock');before=execution_now();context_raw=bounded(contextpath);require(digest(context_raw)==context_sha256,'pre_resume_context_hash_changed');context=strict_bytes(context_raw)
    require(context['bindings_sha256']==bound['bindings_sha256'] and all(sha(p)==pin for p,pin in context['inputs'].items()),'retained_startup_context_changed')
    receiptpath=case/'wait-expired.private.json';wirepath=case/'wait-sealed-wire.raw.private.json'
    try:
        raw=bounded(receiptpath);wire_raw=bounded(wirepath,LIMIT);value=strict_bytes(raw);strict_bytes(wire_raw)
    except (FileNotFoundError,json.JSONDecodeError,UnicodeDecodeError):
        return {'status':'not_ready','scope':'Stay with genuine foreground work; no GUI activation or inferred expiry.'}
    proof=validate_expiry(value,wire_raw,context,resume_before,resume_after)
    require(bounded(receiptpath)==raw and bounded(wirepath,LIMIT)==wire_raw and bounded(contextpath)==context_raw,'immutable_expiry_readback_changed')
    require(all(sha(p)==pin for p,pin in context['inputs'].items()),'startup_inputs_changed_during_check')
    value={'schema':'private.case11.expiry-observation-ready.v1','passed':True,'deadline_clock':CLOCK,'qpc_before':before,'qpc_after':execution_now(),'bindings_sha256':bound['bindings_sha256'],'context_sha256':digest(context_raw),'receipt_sha256':digest(raw),'wire_sha256':digest(wire_raw),'resume_qpc_before':resume_before,'resume_qpc_after':resume_after,**proof}
    save(resultpath,value)
    return {'status':'ready','readiness_sha256':sha(resultpath),'receipt_sha256':value['receipt_sha256'],'wire_sha256':value['wire_sha256'],'seal_qpc':proof['seal_qpc'],'scope':proof['scope']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('context','check'));p.add_argument('--bindings',type=Path,required=True);p.add_argument('--resume-before',type=float);p.add_argument('--resume-after',type=float);p.add_argument('--context-sha256');a=p.parse_args()
    bound=checked(a.bindings)
    if a.mode=='context':require(a.resume_before is None and a.resume_after is None and a.context_sha256 is None,'context_has_no_resume');value=capture_context(bound)
    else:value=check_once(bound,a.resume_before,a.resume_after,a.context_sha256)
    output=json.dumps(value,separators=(',',':'),allow_nan=False);require(len(output.encode())+1<=1024,'bounded_expiry_output');print(output)
    return 0 if value['status'] in ('ready','context_captured') else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status':'refused','type':type(error).__name__,'reason':str(error)[:180]},separators=(',',':')));raise SystemExit(1)
