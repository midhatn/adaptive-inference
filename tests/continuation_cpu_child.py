"""Bounded CPU child fixture: real SQLite/claims, no SDK/model/network/native UI.

Only the test harness invokes this file. It uses the existing expiry fixture to
make the original seal, then the reviewed selected-worker context and native
SQLite projection for a resumed report or cooperative Stop. No LLM is simulated
as producing new work: complete mode verifies the already-written report.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent/'src'),str(HERE)]
from adaptive_inference.desktop.hermes import recovery as rec,run_recovery as worker,service_stop
from adaptive_inference.desktop.hermes.continuation_worker import selected_worker,read_json,effect_receipts
from adaptive_inference.desktop.hermes.control_bridge import Controls
from adaptive_inference.control_mailbox import Mailbox
from adaptive_inference.demand import DemandIdentity,DemandRegistry,Registration
from adaptive_inference.execution_clock import execution_now,CLOCK_ID
from adaptive_inference.task_store import TaskStore
import test_desktop_expiry_worker as original_fixture
from test_desktop_paused_expiry import ClosingDB


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--original',action='store_true')
    parser.add_argument('--continuation-grant',type=Path)
    parser.add_argument('--host-generation')
    parser.add_argument('--controller-ready',type=Path)
    parser.add_argument('--gateway-instance')
    parser.add_argument('--deadline-monotonic',type=float)
    parser.add_argument('--stop-request-id')
    parser.add_argument('--behavior',choices=['complete','hold'],default='complete')
    parser.add_argument('--pause-delay',type=float,default=0)
    args=parser.parse_args()
    timer=threading.Timer(15,lambda:os._exit(124));timer.daemon=True;timer.start()
    if args.original:
        # A fixture-only readiness handshake separates import startup from the
        # existing 15-second work guard. Atomic replacement avoids partial JSON.
        ready=args.run/'original-fixture-ready.json'
        pending=ready.with_suffix('.tmp')
        pending.write_text(json.dumps({'pid':os.getpid(),'work_guard_s':15}),encoding='utf-8')
        pending.replace(ready)
        f=original_fixture.WorkerExpiryTests()
        f.run=args.run;f.now=9.;f.opened=[]
        f.args=SimpleNamespace(run=args.run,mode='worker',deadline_monotonic=10.,
            stop_request_id=None,controller_ready=None,gateway_instance=None,qualification_hold_after_report=False)
        return f.invoke()
    grant=read_json(args.continuation_grant)
    with selected_worker(args.run,grant,host_generation=args.host_generation,
                         deadline=args.deadline_monotonic) as selected:
        plan=selected.exact_plan();store=selected.authority.store
        identity=DemandIdentity(**plan['demand_identity'])
        box=Mailbox(DemandRegistry((Registration(store,identity),)),identity.registration_id,
                    requester_capability=object())
        db=ClosingDB(args.run/'home/state.db')
        controls=Controls(box,deadline=args.deadline_monotonic,deadline_clock=CLOCK_ID,
            utc_now=lambda:'2026-10-25T23:00:00Z')
        controller=rec.Recovery(selected.owned,db,args.run/'work',args.run,controls=controls)
        controls.safe_boundary=service_stop.StopAtPause(controller,args.stop_request_id)
        result={'passed':False,'completed':False,'model':worker.MODEL,'quality':worker.QUALITY,
                'owner_epoch':selected.owned.checkpoint.owner_epoch,
                'selected_execution':{'logical_task_id':selected.original['task_id'],
                    'execution_id':selected.execution_id,'execution_generation':selected.execution_generation}}
        try:
            selected.verify_native(db)
            if args.pause_delay:time.sleep(args.pause_delay)
            controller.bootstrap_controls()
            rec.save(selected.diagnostics/f'bootstrap-{os.getpid()}.json',{
                'pid':os.getpid(),'task_id':identity.task_id,'registration_id':identity.registration_id,
                'revision':selected.owned.checkpoint.revision,'owner_epoch':selected.owned.checkpoint.owner_epoch,
                'deadline_monotonic':args.deadline_monotonic,'deadline_clock':CLOCK_ID})
            while not args.controller_ready.exists():
                controller.control_safe_point();time.sleep(.01)
            selected.read_ready(args.controller_ready)
            if args.behavior=='hold':
                while True:controller.control_safe_point();time.sleep(.01)
            controller.finish({'completed':True,'final_response':'CPU fixture verified existing report; no new model work'})
            result.update(passed=True,completed=True,provider_calls=0)
            code=0
        except service_stop.ProductStop as exc:
            result.update(service_stopped=True,service_stop=exc.receipt,controlled=True,
                          control_state='stopped',control_reason=exc.reason,provider_calls=0)
            code=service_stop.STOP_EXIT
        proof=service_stop.close_safe_resources(controller,agent=None,db=db,provider=None,session_db_factory=ClosingDB)
        selected.note_cleanup({**proof,'effect_receipts_sha256':effect_receipts(selected.owned,args.run)})
        result['continuation_cleanup_verified']=True
        rec.save(selected.result_path,result)
        selected.finish(code)
        return code


if __name__=='__main__':raise SystemExit(main())
