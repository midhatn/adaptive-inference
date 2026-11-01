# SPDX-License-Identifier: Apache-2.0
"""Lossless operator recording: one B capture, then one final Python assembly.

No UI/control/HTTP/process action. Full bindings never pass through JS Number.
The immutable pre-Resume/pre-Continue observations remain the evidence source.
"""
from copy import deepcopy
from pathlib import Path
import argparse,base64,json,math,os,sys
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(HERE / '.'));sys.path.insert(0,str(HERE))
from bindings import load,read,save,sha,unique
from first_inflight import CLOCK,SEAL,digest,require,bracket,wall_bracket,time_value,check_capture
PROTECTED=frozenset(('window_a','window_b','expired_window','selected_source'))
MAX_JSON=16*1024*1024  # Terminal safe-wait receipts include the full durable history.

def strict_bytes(raw):
    require(type(raw) is bytes and len(raw)<=MAX_JSON,'bounded_json_required')
    def bad(_):raise ValueError('nonfinite_json')
    def finite_float(text):
        value=float(text)
        require(math.isfinite(value),'nonfinite_json')
        return value
    return json.loads(raw,object_pairs_hook=unique,parse_constant=bad,parse_float=finite_float)

def full_binding(value):
    require(type(value) is dict and set(value)=={'host_epoch','session_id','task_id','hwnd','pid','creation_time_100ns'},'exact_binding_schema')
    require(all(type(value[k]) is str and bool(value[k]) for k in ('host_epoch','session_id','task_id')),'binding_string_identity')
    require(all(type(value[k]) is int and 0<value[k]<2**53 for k in ('hwnd','pid')),'binding_safe_ui_identity')
    require(type(value['creation_time_100ns']) is int and 0<value['creation_time_100ns']<2**64,'binding_exact_integer_creation_time')
    return deepcopy(value)

def observed_window(observation,binding):
    bracket(observation,'qpc_before','qpc_after');wall_bracket(observation)
    require(all(type(observation.get(k)) is int and observation[k]==binding[k] for k in ('hwnd','pid')),'separate_observed_window_mismatch')
    require(all(type(observation.get(k)) is str and bool(observation[k]) for k in ('title','note')),'actual_observation_note_required')

def phase_from_capture(capture,name,schema):
    require(capture.get('schema')==schema,'capture_schema')
    bracket(capture,'capture_qpc_before','capture_qpc_after')
    raw=base64.b64decode(capture['phase_raw_base64'],validate=True)
    require(digest(raw)==capture['phase_sha256'],'raw_capture_hash')
    phase=strict_bytes(raw)
    require(type(phase) is dict and set(phase)=={'phase','qpc','deadline_clock','gui_binding'} and phase['phase']==name and phase['deadline_clock']==CLOCK and time_value(phase['qpc']) and phase['qpc']<=capture['capture_qpc_before'],'exact_phase_capture')
    binding=full_binding(phase['gui_binding']);observed_window(capture['observation'],binding)
    require(capture['observation']['qpc_after']<=capture['capture_qpc_before'],'observation_before_capture')
    return binding

def make_b_capture(raw,observation,before,after,binding_sha,welcome_sha):
    value={'schema':'private.case10.pre-resume-b-ui-binding.v1','deadline_clock':CLOCK,'capture_qpc_before':before,'capture_qpc_after':after,'bindings_sha256':binding_sha,'observation':deepcopy(observation),'phase_raw_base64':base64.b64encode(raw).decode('ascii'),'phase_sha256':digest(raw),'welcome_ready_sha256':welcome_sha}
    phase_from_capture(value,'welcome_paused_ready_for_resume',value['schema'])
    return value

def merge_ui(draft,a,*,binding_sha,b=None,welcome=None,welcome_sha=None,expired=None,wait_expired=None):
    """Only insert protected fields; every actual action field stays identical."""
    template=read(HERE/'ui.template.private.json')
    require(type(draft) is dict and set(draft)==set(template) and draft.get('deadline_clock')==CLOCK,'exact_action_draft_schema')
    original=deepcopy(draft);merged=deepcopy(draft)
    require(a.get('bindings_sha256')==binding_sha,'same_enabled_binding')
    ga=phase_from_capture(a,'inventory_paused_ready_for_resume','private.case09.pre-resume-ui-binding.v1')
    def insert(key,value):
        # Refuse corruption rather than silently repairing an already-filled field.
        require(merged[key] is None or type(merged[key]) is type(value) and digest(merged[key])==digest(value),'conflicting_protected_prefill_'+key)
        merged[key]=deepcopy(value)
    insert('window_a',ga);check_capture(a,merged,ga)
    if b is not None:
        require(b.get('bindings_sha256')==binding_sha and b.get('welcome_ready_sha256')==welcome_sha,'same_B_binding_and_immutable_source')
        gb=phase_from_capture(b,'welcome_paused_ready_for_resume','private.case10.pre-resume-b-ui-binding.v1')
        require(b['capture_qpc_after']<merged['resume_b_qpc_before'] and ga['host_epoch']==gb['host_epoch'],'B_captured_before_resume')
        require(type(welcome) is dict and welcome['deadline_clock']==CLOCK and time_value(welcome['qpc']) and merged['new_task_qpc_before']<welcome['qpc']<=b['capture_qpc_before'] and welcome['host_identity']['host_epoch']==gb['host_epoch'],'immutable_welcome_source_time_and_host')
        require(type(welcome.get('source')) is dict and bool(welcome['source']),'actual_selected_source')
        insert('window_b',gb);insert('selected_source',welcome['source'])
    else:
        require(welcome is None and welcome_sha is None and type(merged['new_task_clicks']) is int and type(merged['resume_b_clicks']) is int and merged['new_task_clicks']==merged['resume_b_clicks']==0 and merged['window_b'] is None and merged['selected_source'] is None,'missing_actual_B_capture')
    if expired is not None:
        observed_window(expired,ga)
        require(wait_expired is not None and wait_expired['gui_binding']==ga,'expired_exact_prior_A_binding')
        marker=wait_expired['sealed']['checkpoint']['state'][SEAL]
        require(marker['deadline_clock']==CLOCK and time_value(marker['sealed_at_monotonic']) and marker['sealed_at_monotonic']<expired['qpc_before']<=expired['qpc_after']<merged['continue_qpc_before'],'expired_observed_after_seal_before_continue')
        require((merged['expired_gui_qpc_before'],merged['expired_gui_qpc_after'])==(expired['qpc_before'],expired['qpc_after']),'expired_actual_observation_brackets')
        insert('expired_window',ga)
    else:
        require(wait_expired is None and type(merged['continue_clicks']) is int and merged['continue_clicks']==0 and merged['expired_window'] is None and merged['expired_gui_qpc_before'] is None and merged['expired_gui_qpc_after'] is None,'missing_expired_observation')
    before={k:v for k,v in original.items() if k not in PROTECTED};after={k:v for k,v in merged.items() if k not in PROTECTED}
    require(before==after and digest(before)==digest(after),'nonbinding_actions_changed')
    return merged

def publish(output,draft_raw,value,inputs):
    """Exclusive raw backup and stage; Windows rename never replaces a winner."""
    require(os.name=='nt','windows_no_overwrite_publish_required')
    output=Path(output);backup=output.with_name('ui-actions.before-recording.private.json');stage=output.with_name('ui-observations.staged.private.json');receipt_path=output.with_name('ui-recording.private.json')
    require(all(not p.exists() for p in (output,backup,stage,receipt_path)),'recording_outputs_must_be_fresh')
    require(all(sha(Path(p))==pin for p,pin in inputs.items()),'recording_inputs_changed')
    with backup.open('xb') as f:f.write(draft_raw)
    require(backup.read_bytes()==draft_raw,'raw_action_backup_mismatch')
    save(stage,value)
    require(read(stage)==value,'lossless_stage_readback')
    require(all(sha(Path(p))==pin for p,pin in inputs.items()),'recording_inputs_changed_before_publish')
    os.rename(stage,output)  # Windows refuses an existing destination; never os.replace.
    require(read(output)==value,'lossless_final_readback')
    require(all(sha(Path(p))==pin for p,pin in inputs.items()),'recording_inputs_changed_after_publish')
    receipt={'schema':'private.case10.lossless-ui-recording.v1','passed':True,'inputs':inputs,'output_sha256':sha(output),'raw_draft_backup_sha256':sha(backup),'nonbinding_sha256':digest({k:v for k,v in value.items() if k not in PROTECTED}),'protected_fields':sorted(PROTECTED),'scope':'Exact Python transfer of already-observed immutable bindings; no retrospective UI observation, no qualification claim.'}
    save(receipt_path,receipt);return receipt

def checked_bound(path):
    bound=load(path,installed=False)
    require(bound['case']==Path(read(bound['path'].with_name('bindings.disabled.private.json'))['case']) and bound['value']=={**read(bound['path'].with_name('bindings.disabled.private.json')),'enabled':True},'exact_enabled_case10_only')
    return bound

def capture_b(bound):
    case=bound['case'];output=case/'welcome-pre-resume-binding.private.json'
    require(not output.exists() and not (case/'result.private.json').exists(),'one_pre_resume_B_capture_only')
    from adaptive_inference.execution_clock import verify_execution_clock,execution_now
    require(verify_execution_clock()==CLOCK,'same_QPC_clock')
    obs_path=case/'welcome-pre-resume-ui.private.json';welcome_path=case/'welcome-paused-ready.private.json'
    obs_raw=obs_path.read_bytes();observation=strict_bytes(obs_raw)
    before=execution_now();raw=(case/'phase.private.json').read_bytes();after=execution_now()
    welcome_raw=welcome_path.read_bytes();strict_bytes(welcome_raw)
    value=make_b_capture(raw,observation,before,after,bound['bindings_sha256'],digest(welcome_raw))
    value.update(observation_path=str(obs_path),observation_sha256=digest(obs_raw),scope='One explicit B phase read and immutable welcome receipt binding before actual Resume B; no UI action or task-store read.')
    require(obs_path.read_bytes()==obs_raw and welcome_path.read_bytes()==welcome_raw,'capture_inputs_changed')
    save(output,value);return {'saved':str(output),'sha256':sha(output),'kind':'B capture; no full binding in stdout'}

def record(bound,*,with_b,with_expired,parent_joined,observer_joined):
    require(parent_joined is True and observer_joined is True,'join_actual_parent_and_observer_before_final_assembly')
    case=bound['case'];require((case/'result.private.json').is_file(),'terminal_case_required')
    inputs={}
    def data(path):
        path=Path(path);raw=path.read_bytes();require(len(raw)<=MAX_JSON,'bounded_recording_input');inputs[str(path)]=digest(raw);return strict_bytes(raw)
    draft_path=case/'ui-actions.private.json';draft=data(draft_path);draft_raw=draft_path.read_bytes();require(digest(draft_raw)==inputs[str(draft_path)],'draft_changed')
    a=data(case/'pre-resume-binding.private.json')
    def capture_observation(capture,expected):
        require(Path(capture['observation_path']).resolve()==expected.resolve(),'explicit_capture_observation_path')
        observed=data(expected);require(observed==capture['observation'] and inputs[str(expected)]==capture['observation_sha256'],'retained_observation_changed')
    capture_observation(a,case/'pre-resume-ui.private.json')
    b=welcome=welcome_sha=None
    if with_b:
        b=data(case/'welcome-pre-resume-binding.private.json');capture_observation(b,case/'welcome-pre-resume-ui.private.json')
        welcome=data(case/'welcome-paused-ready.private.json');welcome_sha=inputs[str(case/'welcome-paused-ready.private.json')]
    expired=wait=None
    if with_expired:
        expired=data(case/'expired-ui.private.json');wait=data(case/'wait-expired.private.json')
    value=merge_ui(draft,a,binding_sha=bound['bindings_sha256'],b=b,welcome=welcome,welcome_sha=welcome_sha,expired=expired,wait_expired=wait)
    receipt=publish(case/'ui-observations.private.json',draft_raw,value,inputs)
    return {'saved':str(case/'ui-observations.private.json'),'sha256':receipt['output_sha256'],'receipt_sha256':sha(case/'ui-recording.private.json'),'full_bindings_passed_through_javascript':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['capture-b','record']);p.add_argument('--bindings',type=Path,required=True)
    p.add_argument('--with-b',action='store_true');p.add_argument('--with-expired',action='store_true');p.add_argument('--parent-joined',action='store_true');p.add_argument('--observer-joined',action='store_true');a=p.parse_args()
    bound=checked_bound(a.bindings)
    if a.mode=='capture-b':
        require(not (a.with_b or a.with_expired or a.parent_joined or a.observer_joined),'capture_mode_flags');result=capture_b(bound)
    else:result=record(bound,with_b=a.with_b,with_expired=a.with_expired,parent_joined=a.parent_joined,observer_joined=a.observer_joined)
    print(json.dumps(result,allow_nan=False))
if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'failed':True,'error_type':type(error).__name__,'reason':str(error)[:240]}));raise SystemExit(1)
