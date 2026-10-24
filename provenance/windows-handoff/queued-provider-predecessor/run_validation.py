"""Bounded real IQ3_S desktop and installed-agent qualification.

Operator paths are arguments. All raw results stay in the fresh private run.
This harness intentionally never changes a model or quality control.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'native'))
from native_owner_adapter import NativeOwnerAdapter
from adaptive_inference.config import Config
from adaptive_inference.gateway import create_app, GATEWAY
from adaptive_inference.handoff import ToolRequirements
from aiohttp import web, ClientSession, ClientTimeout

MODEL = 'qwen3.8-flash-next-iq3_s-adaptive-media-beta'
QUALITY = {'max_tokens':10923, 'reasoning_effort':'high', 'reasoning_budget_tokens':8192,
           'experimental_speed_projection':False, 'strata_tune':{'pcie_frac':.37}}
EXPECTED = {'rows':4, 'units':17, 'total_cents':4350,
            'by_item':{'apple':1200, 'banana':750, 'orange':2400}}
PROMPT = ('Calculate this CSV: item,quantity,unit_cents\napple,3,200\nbanana,5,150\n'
          'apple,3,200\norange,6,400\n'
          'Reply only a JSON object with rows, units, total_cents, and by_item mapping items to cents. '
          'Use integers and no markdown.')

def save(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def event(run, kind, **fields):
    row = {'at':time.monotonic(), 'kind':kind, **fields}
    with (run/'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row)+'\n')
    print(json.dumps(row), flush=True)

async def wait_process(process, timeout, interruption=None):
    deadline = time.monotonic()+timeout
    while process.poll() is None:
        if time.monotonic() >= deadline or interruption is not None and interruption.is_set():
            process.kill()
            await asyncio.to_thread(process.wait, 10)
            raise RuntimeError('Owned subprocess interrupted or timed out')
        await asyncio.sleep(.05)
    return process.returncode

async def generations(run, gateway):
    receipts=[]
    async with ClientSession(timeout=ClientTimeout(total=600, sock_read=600),trust_env=False) as client:
        for index in range(2):
            body={'model':MODEL, 'messages':[{'role':'user','content':PROMPT}], **QUALITY}
            began=time.monotonic()
            event(run,'inference_requested',index=index)
            async with client.post('http://127.0.0.1:18100/v1/chat/completions',json=body,
                                   headers={'X-Adaptive-Class':'background'}) as response:
                data=await response.json()
                save(run/f'response-{index}.private.json',data)
                if response.status != 200 or data.get('model') != MODEL:
                    raise RuntimeError('Qualified inference response failed')
                gateway_class=response.headers.get('X-Adaptive-Class')
                if gateway_class != 'background': raise RuntimeError('Background request class changed')
            choice=data['choices'][0]
            content=choice['message']['content'].strip()
            if content.startswith('```'):
                content=content.split('\n',1)[1].rsplit('```',1)[0].strip()
            answer=json.loads(content)
            if answer != EXPECTED or choice['finish_reason'] != 'stop':
                raise RuntimeError('Arithmetic artifact failed independent acceptance')
            row={'index':index,'requested_at':began,'completed_at':time.monotonic(),
                 'answer':answer,'finish_reason':choice['finish_reason'],
                 'usage':data.get('usage'),'quality':QUALITY,'model':MODEL,
                 'request_class':'background','gateway_class':gateway_class,
                 'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}
            receipts.append(row); save(run/'inference-receipts.json',receipts)
            event(run,'inference_accepted',index=index)
    return receipts

async def protected_video(args, host):
    run=args.run
    binary_pins={str(path.resolve(strict=True)):digest(path) for path in (args.ffmpeg,args.ffprobe)}
    identities=[]
    def launch(command, output, stderr=subprocess.STDOUT):
        executable=Path(command[0]).resolve(strict=True)
        if digest(executable)!=binary_pins[str(executable)]:
            raise RuntimeError('Explicit tool executable changed before launch')
        child=subprocess.Popen(command,stdout=output,stderr=stderr,stdin=subprocess.DEVNULL)
        identities.append({'pid':child.pid,'executable_sha256':binary_pins[str(executable)],
                           'started_at':time.monotonic(),'executable_name':executable.name})
        return child
    event(run,'tool_requested')
    grant=await host.controller.acquire_tool(ToolRequirements(ram_gib=8,commit_gib=12,vram_mib=6000),timeout_s=240)
    event(run,'tool_granted',capacity=grant.capacity)
    children=[]
    try:
        video=run/'handoff-video.mp4'
        command=[str(args.ffmpeg),'-hide_banner','-nostdin','-n','-f','lavfi','-i',
                 'testsrc2=size=1280x720:rate=30','-t','3','-c:v','h264_nvenc',
                 '-pix_fmt','yuv420p','-an',str(video)]
        with (run/'video-encode.log').open('wb') as output:
            child=launch(command,output)
            children.append(child)
            if await wait_process(child,60,grant.interruption) != 0:
                raise RuntimeError('NVENC encode failed')
        with (run/'video-probe.json').open('wb') as output:
            child=launch([str(args.ffprobe),'-v','error','-count_frames','-select_streams','v:0',
                '-show_entries','stream=codec_name,width,height,nb_read_frames','-of','json',str(video)],
                output,stderr=subprocess.DEVNULL)
            children.append(child)
            if await wait_process(child,20,grant.interruption) != 0: raise RuntimeError('Video probe failed')
        probe=json.loads((run/'video-probe.json').read_text())['streams'][0]
        if probe != {'codec_name':'h264','width':1280,'height':720,'nb_read_frames':'90'}:
            raise RuntimeError('Video content contract failed')
        with (run/'video-decode.log').open('wb') as output:
            child=launch([str(args.ffmpeg),'-hide_banner','-nostdin','-v','error',
                '-i',str(video),'-f','null','-'],output)
            children.append(child)
            if await wait_process(child,30,grant.interruption) != 0: raise RuntimeError('Video decode failed')
        receipt={'passed':True,'capacity':grant.capacity,'probe':probe,'video_sha256':digest(video),
                 'ffmpeg_sha256':digest(args.ffmpeg),'ffprobe_sha256':digest(args.ffprobe),
                 'owned_processes':[{**identity,'exit_code':child.returncode}
                                    for identity,child in zip(identities,children)],
                 'owned_process_exit_codes':[p.returncode for p in children]}
        save(run/'video-receipt.json',receipt)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill(); await asyncio.to_thread(child.wait,10)
        host.controller.complete_tool(grant,owned_processes_exited=all(p.poll() is not None for p in children))
    await host.wait_ready(timeout_s=240)
    event(run,'inference_restored_after_video')
    return receipt

async def recovery(args,host):
    from adaptive_inference.task_store import TaskStore
    run=args.hermes_run
    plan=json.loads((run/'plan.json').read_text())
    if (plan.get('fixture') is not False or plan.get('model') != MODEL
            or plan.get('quality') != QUALITY or plan.get('gateway') != 'http://127.0.0.1:18100/v1'
            or plan.get('sdk_revision') != '14e1e43a23761b369641208e204365cd6cb9399d'
            or plan.get('task_id') != 'orders-report' or plan.get('max_requests') != 8):
        raise RuntimeError('Recovery plan is not the exact real IQ3_S contract')
    if (any((run/name).exists() for name in ('pause.json','effect-receipts.jsonl','wire-observations.json'))
            or list(run.glob('result-*.json')) or (run/'work/report.json').exists()):
        raise RuntimeError('Recovery acceptance requires a fresh unconsumed prepared task')
    for path,expected in plan['pins'].items():
        if digest(Path(path)) != expected: raise RuntimeError('Prepared recovery input changed')
    store=TaskStore(run/'task.sqlite3')
    original=store.load(plan['task_id'])
    if (original.state['phase'] != 'ready' or original.state['status'] != 'pending'
            or original.operation is not None or original.state['requests'] != 0
            or original.state['native_history'] or original.state['session_id'] != plan['session_id']):
        raise RuntimeError('Recovery task is not at its original safe boundary')
    expected_report={'rows':4,'units':17,'total_cents':4350,
                     'by_item':{'folder':1100,'notebook':2250,'pen':1000}}
    expected_context={'context_length':65536,'threshold':.8,'threshold_tokens':46421,
                      'reserved_output':10923,'max_tokens':10923}
    def object_hash(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    deadline=time.monotonic()+900
    def remaining():
        left=deadline-time.monotonic()
        if left <= 0: raise TimeoutError('Whole recovery acceptance exceeded900seconds')
        return left
    receipts=[]
    for phase,pause in [('before_restart',True),('after_restart',False)]:
        await host.wait_ready(timeout_s=min(240,remaining()))
        remaining()
        ready={'ready':True,'model':plan['model'],'quality':plan['quality'],
               'gateway':plan['gateway'],'observed_at':time.time()}
        save(run/'controller-ready.json',ready)
        command=[plan['base_python'],'-I','-B',str(HERE/'hermes/run_recovery.py'),'worker',
                 '--run',str(run),'--controller-ready',str(run/'controller-ready.json')]
        if pause: command+=['--pause','safe_after_write']
        event(args.run,'hermes_phase',phase=phase)
        with (run/(phase+'.log')).open('wb') as output:
            child=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            try:
                if pause:
                    while not (run/'pause.json').exists():
                        if child.poll() is not None or time.monotonic()>=deadline:
                            raise RuntimeError('Hermes did not reach durable safe boundary')
                        await asyncio.sleep(.1)
                    boundary=json.loads((run/'pause.json').read_text())
                    if boundary.get('pid') != child.pid or boundary.get('boundary') != 'safe_after_write':
                        raise RuntimeError('Pause identity or boundary mismatch')
                    before=store.load(plan['task_id'])
                    if (before.revision != boundary.get('revision') or before.operation is not None
                            or before.requires_reconciliation or before.state['phase'] != 'ready'
                            or object_hash(before.state['native_history']) != boundary.get('history_sha256')
                            or before.prompt != original.prompt or before.metadata != original.metadata):
                        raise RuntimeError('Pause is not the exact durable original-task checkpoint')
                    if json.loads((run/'work/report.json').read_text()) != expected_report:
                        raise RuntimeError('Original report failed acceptance before restart')
                    before_hash=digest(run/'work/report.json')
                    before_receipts=(run/'effect-receipts.jsonl').read_bytes()
                    effects=[json.loads(row) for row in before_receipts.splitlines() if row.strip()]
                    if (len(effects) != 1 or effects[0].get('name') != 'write_file'
                            or effects[0].get('artifact_sha256') != before_hash):
                        raise RuntimeError('Expected exactly one verified dispatched file effect')
                    before_wire=json.loads((run/'wire-observations.json').read_text())
                    child.kill(); await asyncio.to_thread(child.wait,10)
                    receipts.append({'phase':phase,'pid':child.pid,'exit_code':child.returncode,
                                     'safe_boundary':True,'boundary_revision':before.revision,
                                     'native_history_sha256':boundary['history_sha256'],
                                     'provider_calls':len(before_wire),'report_sha256':before_hash})
                    event(args.run,'hermes_process_restart',safe_boundary=True)
                else:
                    code=await wait_process(child,remaining())
                    receipts.append({'phase':phase,'pid':child.pid,'exit_code':code})
                    if code != 0: raise RuntimeError('Resumed Hermes process failed')
            finally:
                if child.poll() is None:
                    child.kill(); await asyncio.to_thread(child.wait,10)
        if not pause:
            if digest(run/'work/report.json')!=before_hash or (run/'effect-receipts.jsonl').read_bytes()!=before_receipts:
                raise RuntimeError('Completed tool was replayed or changed across restart')
            final=json.loads((run/f'result-{child.pid}.json').read_text())
            if (any(final.get(k) is not True for k in ('passed','completed','resumed'))
                    or final.get('fixture') is not False or final.get('model') != MODEL
                    or final.get('quality') != QUALITY or final.get('context') != expected_context
                    or final.get('sdk_revision') != plan['sdk_revision']
                    or final.get('report') != expected_report or final.get('artifacts') != {'report.json':before_hash}
                    or final.get('original_prompt_sha256') != object_hash(original.prompt)
                    or type(final.get('provider_calls')) is not int or final['provider_calls'] < 1):
                raise RuntimeError('Resumed process did not produce the required semantic receipt')
            after=store.load(plan['task_id'])
            if (after.state['status'] != 'accepted' or after.state['phase'] != 'accepted'
                    or after.operation is not None or after.prompt != original.prompt
                    or after.metadata != original.metadata or after.state['messages'][0] != original.state['messages'][0]
                    or after.state['native_history'][:len(before.state['native_history'])] != before.state['native_history']
                    or after.state['requests']-before.state['requests'] != final['provider_calls']):
                raise RuntimeError('Original task/native progress did not survive restart exactly')
            wires=json.loads((run/'wire-observations.json').read_text())
            if (wires[:len(before_wire)] != before_wire or len(wires)-len(before_wire) != final['provider_calls']
                    or any(row.get('model') != MODEL or row.get('quality') != QUALITY
                           or row.get('class') != 'normal' or not row.get('finished_at') for row in wires)):
                raise RuntimeError('Restart wire evidence changed quality or lost request lineage')
            selected={k:final[k] for k in ('passed','fixture','sdk_revision','model','quality','context',
                'provider_calls','resumed','original_prompt_sha256','transcript_rows','transcript_sha256',
                'artifacts','report','completed')}
            wire_quality=[{k:row.get(k) for k in ('model','quality','class','body_sha256','messages_sha256',
                'tools_sha256','tool_names','finish_reason','usage','gateway_request_id')} for row in wires]
    save(args.run/'recovery-processes.json',{'passed':True,'processes':receipts,
         'report_sha256':before_hash,'effect_receipts_unchanged':True,'dispatched_file_effects':1,
         'effect_receipts_sha256':hashlib.sha256(before_receipts).hexdigest(),
         'original_prompt_sha256':object_hash(original.prompt),'resume':selected,'wire_quality':wire_quality,
         'source_sha256':{name:digest(HERE/'hermes'/name) for name in
             ('recovery.py','run_recovery.py','test_recovery.py','source-lock.json')}})
    event(args.run,'hermes_restart_accepted')

async def main(args):
    args.run.mkdir(parents=False,exist_ok=False)
    done=threading.Event()
    def watchdog():
        if not done.wait(1800):
            save(args.run/'watchdog.json',{'passed':False,'reason':'outer_1800s_deadline'})
            os._exit(124) # inherited kill-on-close job owns every child
    threading.Thread(target=watchdog,daemon=True).start()
    config=Config(backend_kind='strata',backend_url='http://127.0.0.1:18098/v1',
                  default_class='normal',queue_timeout_s=600,upstream_timeout_s=600,
                  upstream_read_timeout_s=600,backend_revision='qualified-IQ3_S-native-744205e4')
    owner=json.loads(args.owner_config.read_text())
    host=adapter=runner=None
    window=None; requests=None; initial=None
    result={'case':args.case,'passed':False,'model':MODEL,'quality':QUALITY,
            'harness_sha256':digest(Path(__file__)),
            'gateway_default_class':'normal','standalone_generation_class':'background'}
    try:
        if args.case=='controlled':
            from windows_host import DesktopHost
            host=DesktopHost(owner,config,args.run/'host',max_runtime_seconds=1800)
            await host.start(timeout_s=240)
            adapter=host.adapter; gateway=host.gateway
        else:
            import importlib.util
            spec=importlib.util.spec_from_file_location('_validation_job',HERE/'native/owner_source/owned_job.py')
            job=importlib.util.module_from_spec(spec); spec.loader.exec_module(job); job.contain_current_process()
            adapter=NativeOwnerAdapter(**owner)
            initial=await adapter.status()
            if initial.get('running') is not False: raise RuntimeError('No live owner adoption')
            initial=await adapter.start()
            app=create_app(config); gateway=app[GATEWAY]
            runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,config.host,config.port).start()
        initial=await adapter.status()
        save(args.run/'initial-owner.private.json',initial)
        save(args.run/'initial-capacity.json',await adapter.fresh_capacity())
        event(args.run,'backend_ready',owner_id=initial['owner_id'])
        requests=asyncio.create_task(generations(args.run,gateway))
        deadline=time.monotonic()+30
        while gateway.scheduler.active is None:
            if requests.done(): await requests
            if time.monotonic()>deadline: raise RuntimeError('First generation did not enter active inference')
            await asyncio.sleep(.01)
        event(args.run,'foreground_starting')
        with (args.run/'foreground.log').open('wb') as output:
            window=subprocess.Popen([sys._base_executable,str(HERE/'foreground/foreground_window.py'),
                    '--output',str(args.run/'foreground'),'--seconds','45','--fps','60'],
                    stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            ready_deadline=time.monotonic()+10
            while True:
                if window.poll() is not None or time.monotonic()>=ready_deadline:
                    raise RuntimeError('Owned foreground process did not become ready')
                try:
                    foreground_ready=json.loads((args.run/'foreground/ready.json').read_text())
                    break
                except (OSError,json.JSONDecodeError):
                    pass  # the foreground writer may still be finishing ready.json
                await asyncio.sleep(.05)
            if foreground_ready.get('pid') != window.pid:
                raise RuntimeError('Foreground ready PID does not match retained actual process')
            window_code=await wait_process(window,70)
        result['foreground']=json.loads((args.run/'foreground/result.json').read_text())
        result['inference']=await requests
        if window_code != 0: raise RuntimeError('Foreground measurement did not qualify')
        event(args.run,'foreground_completed',p95_ms=result['foreground']['paint_interval_p95_ms'])
        if host:
            await host.wait_ready(timeout_s=240)
            result['handoff_events']=list(host.controller.events)
            if not any('release' in row for row in result['handoff_events']):
                raise RuntimeError('Foreground demand did not cause a verified release')
            if host.controller.identity['owner_id']==initial['owner_id']:
                raise RuntimeError('Foreground recovery did not restore a distinct owner')
            result['video']=await protected_video(args,host)
            if args.hermes_run: await recovery(args,host)
        result['passed']=True
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        try:
            if window is not None and window.poll() is None:
                window.kill(); await asyncio.to_thread(window.wait,10)
            if requests is not None and not requests.done():
                try: await asyncio.wait_for(asyncio.shield(requests),600)
                except BaseException: pass
            if host:
                result['handoff_events']=list(host.controller.events)
                result['cleanup']=await host.close(timeout_s=180)
            elif adapter:
                if runner:
                    await gateway.scheduler.close()
                    deadline=time.monotonic()+180
                    while gateway.scheduler.active is not None and time.monotonic()<deadline: await asyncio.sleep(.1)
                    if gateway.scheduler.active is not None or gateway.scheduler.uncertain:
                        raise RuntimeError('Uncontrolled shutdown completion uncertain')
                state=await adapter.status()
                if state.get('running'):
                    result['cleanup']=await adapter.stop(state)
                await adapter.close(release_parked=True)
                if runner: await runner.cleanup()
        except BaseException as cleanup:
            result['passed']=False; result['cleanup_error']=str(cleanup)
            raise
        finally:
            save(args.run/'result.private.json',result)
            done.set()
            event(args.run,'run_finished',passed=result['passed'])

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--case',choices=['uncontrolled','controlled'],required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--owner-config',type=Path,required=True)
    p.add_argument('--hermes-run',type=Path)
    p.add_argument('--ffmpeg',type=Path)
    p.add_argument('--ffprobe',type=Path)
    args=p.parse_args()
    if args.case=='controlled' and not all((args.ffmpeg,args.ffprobe)): p.error('Controlled case needs explicit existing FFmpeg and FFprobe')
    if args.hermes_run and args.case!='controlled': p.error('Hermes recovery requires the controlled host')
    if args.hermes_run and not (args.hermes_run/'plan.json').is_file(): p.error('Hermes recovery needs an existing prepared plan')
    asyncio.run(main(args))
