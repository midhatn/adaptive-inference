# SPDX-License-Identifier: Apache-2.0
"""One explicit pre-Resume capture of the existing host phase; no polling/control."""
import argparse,base64,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE / '.'))
sys.path.insert(0,str(HERE))
from bindings import load,read,save,sha
from first_inflight import digest,require,bracket,wall_bracket

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bindings',type=Path,required=True)
    p.add_argument('--observation',type=Path,required=True,help='Actual prior UI observation using pre-resume template; never inferred from phase')
    args=p.parse_args();bound=load(args.bindings,installed=True);case=bound['case']
    require(case==Path(read(bound['path'].with_name('bindings.disabled.private.json'))['case']),'fresh_case09_only')
    require(not (case/'result.private.json').exists(),'terminal_case_refused')
    output=case/'pre-resume-binding.private.json'
    require(not output.exists(),'capture_once_only')
    from adaptive_inference.execution_clock import verify_execution_clock,execution_now
    clock=verify_execution_clock()
    observation=read(args.observation);bracket(observation,'qpc_before','qpc_after');wall_bracket(observation)
    require(all(type(observation.get(k)) is int and observation[k]>0 for k in ('pid','hwnd')),'observed_identity_required')
    require(all(type(observation.get(k)) is str and bool(observation[k]) for k in ('title','note')),'actual_ui_observation_required')
    before=execution_now();raw=(case/'phase.private.json').read_bytes();after=execution_now()
    phase=json.loads(raw)
    require(set(phase)=={'phase','qpc','deadline_clock','gui_binding'} and phase['phase']=='inventory_paused_ready_for_resume' and phase['deadline_clock']==clock,'paused_phase_required')
    require(all(type(phase['gui_binding'][k]) is int and phase['gui_binding'][k]==observation[k] for k in ('pid','hwnd')),'actual_window_must_match_host')
    require(observation['qpc_after']<=before and phase['qpc']<=before,'observation_must_precede_capture')
    value={'schema':'private.case09.pre-resume-ui-binding.v1','deadline_clock':clock,'capture_qpc_before':before,'capture_qpc_after':after,
        'bindings_sha256':bound['bindings_sha256'],'observation':observation,'observation_path':str(args.observation.resolve()),'observation_sha256':sha(args.observation),
        'phase_raw_base64':base64.b64encode(raw).decode('ascii'),'phase_sha256':digest(raw),'scope':'One explicit raw host phase read before actual Resume; UI identity separately observed. No control or task-store read.'}
    save(output,value)
    print(json.dumps({'saved':str(output),'sha256':sha(output),'window_a':phase['gui_binding']}))
if __name__=='__main__':main()
