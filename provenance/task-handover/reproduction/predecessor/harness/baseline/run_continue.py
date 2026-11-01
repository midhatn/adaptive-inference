# SPDX-License-Identifier: Apache-2.0
"""Retained parent adapted from the accepted expiry parent; never an acceptance shortcut."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import HERE,OUTER_SECONDS,load,save,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings',required=True,type=Path)
    args=parser.parse_args();bound=load(args.bindings)
    if os.name!='nt':raise ValueError('Windows installed qualification required')
    case=bound['case'];receipt=Path(str(case)+'.supervisor.private.json');log=Path(str(case)+'.console.private.log')
    if any(p.exists() for p in (case,receipt,log)):raise RuntimeError('Fresh case/log/receipt required')
    command=[bound['profile']['host_python']['path'],'-I','-B',str(HERE/'qualify_continue.py'),
             '--bindings',str(bound['path'])]
    source=Path(__file__).resolve();source_before=sha(source);started=time.monotonic()
    failure=None;errors=[];code=None;exit_observed=False;timed_out=False;emergency=False
    with log.open('xb') as stream:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,cwd=case.parent)
        try:
            print(json.dumps({'retained_actual_runner_pid':child.pid,'run':str(case),'started':True}),flush=True)
        except BaseException as error:
            failure=error;errors.append({'stage':'startup_diagnostic','error':type(error).__name__+': '+str(error)})
        try:
            code=child.wait(timeout=OUTER_SECONDS);exit_observed=True
        except BaseException as error:
            timed_out=isinstance(error,subprocess.TimeoutExpired)
            errors.append({'stage':'initial_wait','error':type(error).__name__+': '+str(error)})
            if failure is None:failure=error
            emergency=True
            try:child.kill()
            except BaseException as error:errors.append({'stage':'emergency_kill','error':type(error).__name__+': '+str(error)})
            try:code=child.wait(timeout=10);exit_observed=True
            except BaseException as error:errors.append({'stage':'final_wait','error':type(error).__name__+': '+str(error)})
    source_after=sha(source)
    value={'pid':child.pid,'actual_executable':command[0],'exit_code':code,
        'retained_case_handle_exited':exit_observed,'timed_out':timed_out,'elapsed_s':time.monotonic()-started,
        'task_deadline_s':900,'successor_budget_s':900,'outer_deadline_s':OUTER_SECONDS,
        'harness_manifest':bound['manifest_sha256'],'bindings_sha256':bound['bindings_sha256'],
        'parent_source_sha256_before':source_before,'parent_source_sha256_after':source_after,
        'parent_source_unchanged':source_before==source_after,
        'supervision_error':None if failure is None else type(failure).__name__+': '+str(failure),
        'supervision_errors':errors,'emergency_termination_attempted':emergency,
        'emergency_termination_is_qualification_failure':True}
    save(receipt,value)
    if failure is not None:raise failure
    return 0 if code==0 and exit_observed and not emergency and source_before==source_after else 1


if __name__=='__main__':raise SystemExit(main())
