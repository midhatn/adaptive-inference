# SPDX-License-Identifier: Apache-2.0
"""Terminal input identity using the existing reviewed TaskSpec capability.

Caller must first pass the original audit and bind its input_sha256 and the two
inventory descriptors. No argument rewriting, SDK import, database or CLI.
"""
from pathlib import Path
import adaptive_inference.task_spec as contract

TASK_SPEC_SHA256='e5c85a4f07b256c799a654fb1c5631dd71a177ed6ac3218f9453b8e56ccba425'
MAX_CONTEXT_BYTES=1024*1024

def require(condition,reason):
    if condition is not True:raise ValueError(reason)

def validate_input_path(case,logical,recovery,plan,config,spec_raw,source_raw,*,audited_pins,spec_path,source_path):
    """Return (unaltered native path, proof); old check_lineage remains mandatory."""
    require(type(audited_pins) is dict and bool(audited_pins),'original_audited_pins_required')
    case=Path(case);run=case/'hermes-task';work=run/'work'
    require(case.is_absolute() and all(p.resolve(strict=True)==p for p in (case,run,work)),'exact_independently_bound_case_run_work')
    require(contract.digest(Path(contract.__file__).read_bytes())==TASK_SPEC_SHA256,'reviewed_TaskSpec_source_required')
    observed={}
    def pinned(path,maximum=MAX_CONTEXT_BYTES):
        path=Path(path)
        require(path.is_absolute() and path.resolve(strict=True)==path,'exact_pinned_context_path')
        expected=audited_pins.get(str(path))
        require(type(expected) is str and len(expected)==64,'missing_original_audit_pin')
        with path.open('rb') as stream:raw=stream.read(maximum+1)
        require(len(raw)<=maximum and contract.digest(raw)==expected,'original_audited_input_changed')
        observed[str(path)]=maximum
        return raw
    def same_json(path,value):
        raw=pinned(path)
        require(contract.canonical(contract.strict_json(raw))==contract.canonical(value),'supplied_context_not_original_audited_bytes')
        return raw
    spec_path=Path(spec_path);source_path=Path(source_path)
    require(type(spec_raw) is bytes and pinned(spec_path,contract.MAX_SPEC_BYTES)==spec_raw,'raw_bound_TaskSpec_mismatch')
    require(type(source_raw) is bytes and pinned(source_path,contract.MAX_INPUT_BYTES)==source_raw,'raw_bound_source_mismatch')
    spec=contract.TaskSpec.from_bytes(spec_raw);data=spec.data
    require(len(data['inputs'])==1 and data['inputs'][0]['name']=='inventory.csv','single_bound_inventory_input_required')
    declared=data['inputs'][0];expected=work/declared['name']
    require(source_path.name==declared['name'] and len(source_raw)==declared['bytes'] and contract.digest(source_raw)==declared['sha256'],'declared_source_bytes_mismatch')
    plan_path=run/'plan.json';config_path=run/'home/config.yaml'
    same_json(case/'original-checkpoint.private.json',logical)
    same_json(plan_path,plan);config_raw=same_json(config_path,config)
    require(plan.get('task_spec')==data and plan.get('task_spec_sha256')==spec.sha256,'canonical_plan_TaskSpec_mismatch')
    require(plan.get('fixture') is False and plan.get('task_id')==logical['task_id'] and plan.get('session_id')==logical['state']['session_id'],'original_real_task_session_mismatch')
    require(plan['package_identity']['files'].get('task_spec.py')==TASK_SPEC_SHA256 and plan.get('pre_effect_validator')==spec.validator_identity(),'plan_validator_source_mismatch')
    for cp in (logical,recovery['sealed_after']['checkpoint']):
        stored=contract.TaskSpec.from_metadata(cp['metadata'])
        require(stored is not None and stored.sha256==spec.sha256 and stored.data==data and cp['prompt']==spec.prompt,'original_checkpoint_TaskSpec_or_prompt_mismatch')
        require(cp['task_id']==logical['task_id'] and cp['state']['session_id']==logical['state']['session_id'],'checkpoint_original_task_session_mismatch')
    require(type(config.get('terminal')) is dict and config['terminal']=={'backend':'local','cwd':str(work)},'exact_local_work_cwd_required')
    plan_pins=plan.get('pins')
    require(type(plan_pins) is dict and plan_pins.get(str(config_path))==contract.digest(config_raw)==audited_pins.get(str(config_path)),'explicit_config_pin_required')
    require(plan_pins.get(str(expected))==declared['sha256']==audited_pins.get(str(expected)),'explicit_work_input_pin_required')
    require(pinned(expected,declared['bytes'])==source_raw,'staged_input_bytes_mismatch')
    spec.verify_inputs(work)
    history=recovery['sealed_after']['checkpoint']['state']['native_history']
    require(type(history) is list and all(type(row) is dict and type(row.get('tool_calls',[])) is list for row in history),'native_history_shape')
    calls=[call for row in history for call in row.get('tool_calls',[])]
    require(len(calls)==1 and type(calls[0]) is dict and type(calls[0].get('function')) is dict and calls[0]['function'].get('name')=='read_file','unique_native_read_call_required')
    argument_text=calls[0]['function'].get('arguments')
    require(type(argument_text) is str,'strict_native_argument_json_required')
    args=contract.strict_json(argument_text)
    require(type(args) is dict and set(args)=={'path'} and type(args['path']) is str,'exact_path_only_argument_required')
    raw_path=args['path']
    require(spec.file_path(work,raw_path,write=False)==expected,'native_read_not_exact_bound_input')
    spec.verify_inputs(work)
    for path,maximum in tuple(observed.items()):pinned(path,maximum)
    return raw_path,{'bound_work':str(work),'declared_input':declared['name'],'resolved_input':str(expected),
        'raw_argument_sha256':contract.digest(argument_text.encode('utf-8')),'raw_spec_sha256':contract.digest(spec_raw),
        'canonical_spec_sha256':spec.sha256,'input_sha256':declared['sha256'],'TaskSpec_source_sha256':TASK_SPEC_SHA256,
        'raw_path_preserved':True,'scope':'Exact declared staged input only; unchanged check_lineage must still verify native/operation/result/pending equality.'}
