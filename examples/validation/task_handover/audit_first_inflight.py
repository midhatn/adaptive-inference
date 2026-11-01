# SPDX-License-Identifier: Apache-2.0
"""Terminal-only additive audit, after the unchanged recovery auditor passes."""
import argparse,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(HERE / '.'))
sys.path.insert(0,str(HERE))
from bindings import load,read,save,sha
from first_inflight import require,check_onset,check_lineage,SEAL

def audit(bindings,output,*,parent_joined=False,observer_joined=False):
    require(parent_joined is True and observer_joined is True,'actual_retained_parent_and_observer_joins_required')
    bound=load(bindings,installed=True);case=bound['case'];output=Path(output)
    require(case==Path(read(bound['path'].with_name('bindings.disabled.private.json'))['case']),'case09_only')
    require(output==Path(str(case)+'-first-inflight-audit-01') and not output.exists(),'fresh_supplemental_audit_output')
    require(read(bindings)=={**read(bound['path'].with_name('bindings.disabled.private.json')),'enabled':True},'only_explicit_activation_delta')
    output.mkdir();receipt={'schema':'private.case09.first-inflight-audit.v1','passed':False,'qualification_claimed':False,
        'scope':'Additive first-admitted-cycle foreground overlap and saved-read causal lineage, only after original recovery audit passes. No preemption, reboot or performance claim; inventory oracle, welcome format-only.'}
    observed={}
    def track(path):
        path=Path(path).resolve(strict=True);pin=sha(path)
        require(str(path) not in observed or observed[str(path)]==pin,'terminal_input_changed')
        observed[str(path)]=pin;return path
    def data(path):return read(track(path))
    try:
        freeze=data(HERE/'source-manifest.json')
        require(freeze['enabled'] is False and all(sha(track(HERE/n))==pin for n,pin in freeze['files'].items()),'frozen_supplemental_sources')
        pins=data(HERE/'source-lineage.json')
        require(all(sha(track(HERE/path))==pin for path,pin in pins['files'].items()),'exact_reviewed_source_lineage')
        prior=data(Path(str(case)+'-audit-01')/'audit.private.json')
        require(prior.get('schema')=='private.safe-wait-handover.installed-audit.v1' and prior.get('passed') is True and type(prior.get('checks')) is dict and bool(prior['checks']) and all(v is True for v in prior['checks'].values()),'original_recovery_audit_must_pass')
        require(prior['bindings_sha256']==bound['bindings_sha256'],'original_audit_same_binding')
        require(all(sha(track(path))==pin for path,pin in prior['input_sha256'].items()),'original_audited_inputs_unchanged')
        required=['handover-evidence.private.json','result.private.json','original-checkpoint.private.json','wait-expired.private.json','wait-sealed-wire.raw.private.json','ui-observations.private.json']
        require(all(str(case/n) in prior['input_sha256'] for n in required) and str(Path(str(case)+'.api-trace.private.jsonl')) in prior['input_sha256'],'required_original_audit_inputs')
        e=data(case/'handover-evidence.private.json');result=data(case/'result.private.json');ui=data(case/'ui-observations.private.json')
        from safe_wait import check_safe_wait
        receipt['retained_safe_wait_checks']=check_safe_wait(e['safe_wait'])
        capture=data(case/'pre-resume-binding.private.json');activity=data(case/'foreground-observations.private.json')
        require(capture['bindings_sha256']==bound['bindings_sha256'] and sha(track(capture['observation_path']))==capture['observation_sha256'] and data(capture['observation_path'])==capture['observation'],'actual_pre_resume_observation_unchanged')
        from expiry_ready import validate_expiry
        context=data(case/'pre-resume-expiry-context.private.json');ready=data(case/'expiry-ready.private.json')
        require(all(sha(track(path))==pin for path,pin in context['inputs'].items()),'pre_resume_startup_context_unchanged')
        expiry=data(case/'wait-expired.private.json');raw_wire=track(case/'wait-sealed-wire.raw.private.json').read_bytes()
        readiness=validate_expiry(expiry,raw_wire,context,ui['resume_a_qpc_before'],ui['resume_a_qpc_after'])
        require(ready['schema']=='private.case11.expiry-observation-ready.v1' and ready['passed'] is True and ready['deadline_clock']==context['deadline_clock']=='windows-qpc-seconds-v1' and ready['bindings_sha256']==context['bindings_sha256']==bound['bindings_sha256'],'reviewed_expiry_readiness_identity')
        require(ready['context_sha256']==sha(case/'pre-resume-expiry-context.private.json') and ready['receipt_sha256']==sha(case/'wait-expired.private.json') and ready['wire_sha256']==sha(case/'wait-sealed-wire.raw.private.json') and all(ready[k]==v for k,v in readiness.items()),'actual_immutable_expiry_readiness')
        from first_inflight import bracket
        bracket(ready,'qpc_before','qpc_after')
        require(ready['resume_qpc_before']==ui['resume_a_qpc_before'] and ready['resume_qpc_after']==ui['resume_a_qpc_after'] and expiry['qpc']<=ready['qpc_after']<ui['expired_gui_qpc_before'],'readiness_before_actual_expired_GUI')
        trace=[json.loads(line) for line in track(Path(str(case)+'.api-trace.private.jsonl')).read_text().splitlines() if line.strip()]
        receipt['onset']=check_onset(trace,ui,activity,capture,e['gateway_instance'],e['safe_wait']['gui_binding'],e['safe_wait']['sealed_after']['checkpoint']['state'][SEAL]['sealed_at_monotonic'])
        from path_lineage import validate_input_path
        spec_path=track(bound['inputs']['inventory_spec']);source_path=track(bound['inputs']['inventory_input'])
        raw_path,receipt['input_identity']=validate_input_path(case,e['logical_original'],e['safe_wait'],data(case/'hermes-task/plan.json'),data(case/'hermes-task/home/config.yaml'),spec_path.read_bytes(),source_path.read_bytes(),audited_pins=prior['input_sha256'],spec_path=spec_path,source_path=source_path)
        receipt['lineage']=check_lineage(e['safe_wait'],e['logical_original'],result,raw_path,source_path.read_bytes())
        require(all(sha(path)==pin for path,pin in observed.items()),'all_terminal_inputs_unchanged')
        receipt.update(passed=True,qualification_claimed=True,input_sha256=observed,bindings_sha256=bound['bindings_sha256'],original_audit_sha256=sha(Path(str(case)+'-audit-01')/'audit.private.json'))
    except BaseException as error:
        receipt['error']=type(error).__name__+': '+str(error);raise
    finally:save(output/'audit.private.json',receipt)
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--parent-joined',action='store_true');p.add_argument('--observer-joined',action='store_true');a=p.parse_args()
    print(json.dumps(audit(a.bindings,a.output,parent_joined=a.parent_joined,observer_joined=a.observer_joined)))
