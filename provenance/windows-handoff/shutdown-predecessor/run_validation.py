"""Bounded real IQ3_S desktop and installed-agent qualification.

Operator paths are arguments. All raw results stay in the fresh private run.
This harness intentionally never changes a model or quality control.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import importlib.util
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
from adaptive_inference.feedback import run_with_feedback, Verdict
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

def runtime_sources():
    return {f'src/adaptive_inference/{name}.py':digest(Path(importlib.util.find_spec(
            'adaptive_inference.'+name).origin))
            for name in ('gateway','scheduler','handoff','task_store','config','costs','feedback')}

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

async def launch_agent_foreground(run):
    """A second actual foreground interval interrupts the installed agent itself."""
    with (run/'hermes-foreground.log').open('wb') as output:
        child=subprocess.Popen([sys._base_executable,str(HERE/'foreground/foreground_window.py'),
                '--output',str(run/'hermes-foreground'),'--seconds','45','--fps','60'],
                stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    try:
        until=time.monotonic()+10
        while time.monotonic()<until and child.poll() is None:
            try:
                ready=json.loads((run/'hermes-foreground/ready.json').read_text())
            except (OSError,json.JSONDecodeError):
                await asyncio.sleep(.05)
                continue
            if ready.get('pid')!=child.pid:
                raise RuntimeError('Agent foreground identity differs from retained process')
            return child
        raise RuntimeError('Agent foreground process did not become ready')
    except BaseException:
        if child.poll() is None:
            child.kill(); await asyncio.to_thread(child.wait,10)
        raise

async def generations(run, gateway):
    """Two logical tasks; only completed answer rejection permits correction.

    Use the canonical feedback loop unchanged. Transport, routing and envelope
    failures escape generate, so an unknown outcome never becomes a retry.
    All attempts remain private evidence, including rejected outputs.
    """
    receipts=[]; attempts=[]
    tasks=[{'index':index,'status':'not_started','accepted':False,'attempts':0} for index in range(2)]
    def persist():
        save(run/'inference-attempts.private.json',attempts)
        save(run/'inference-tasks.private.json',{'logical_task_count':2,
             'maximum_attempts_per_task':3,'maximum_requests':6,
             'request_count':len(attempts),'tasks':tasks})
        save(run/'inference-receipts.json',receipts)
    def distinct_object(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    persist()
    async with ClientSession(timeout=ClientTimeout(total=600, sock_read=600),trust_env=False) as client:
        for index in range(2):
            task=tasks[index]; task['status']='running'; task_attempts=[]
            async def generate(messages):
                attempt=len(task_attempts)+1
                body={'model':MODEL,'messages':messages,**QUALITY}
                stem=f'task-{index}-attempt-{attempt}'
                row={'index':index,'attempt':attempt,'request_index':len(attempts),
                     'requested_at':time.monotonic(),'status':'request_prepared','verdict':None,
                     'model':MODEL,'quality':QUALITY,'request_class':'background',
                     'request_file':stem+'-request.private.json',
                     'response_file':stem+'-response.private.bin',
                     'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()}
                save(run/row['request_file'],body)
                task_attempts.append(row); attempts.append(row); task['attempts']=attempt
                persist(); event(run,'inference_requested',index=index,attempt=attempt,request_index=row['request_index'])
                try:
                    async with client.post('http://127.0.0.1:18100/v1/chat/completions',json=body,
                                           headers={'X-Adaptive-Class':'background'}) as response:
                        row.update(http_status=response.status,gateway_class=response.headers.get('X-Adaptive-Class'))
                        raw=await response.read()
                        (run/row['response_file']).write_bytes(raw)
                        row.update(response_sha256=hashlib.sha256(raw).hexdigest(),
                                   completed_at=time.monotonic(),status='response_received')
                        persist()
                        if response.status != 200: raise RuntimeError('Qualified inference HTTP response failed')
                        data=json.loads(raw,object_pairs_hook=distinct_object)
                        save(run/(stem+'-response.private.json'),data)
                        if type(data) is not dict or data.get('model') != MODEL:
                            raise RuntimeError('Qualified inference model changed')
                        if row['gateway_class'] != 'background':
                            raise RuntimeError('Background request class changed')
                        choices=data.get('choices')
                        if type(choices) is not list or len(choices)!=1 or type(choices[0]) is not dict:
                            raise RuntimeError('Unknown inference response envelope')
                        choice=choices[0]; message=choice.get('message')
                        if (type(message) is not dict or type(message.get('content')) is not str
                                or choice.get('finish_reason') not in ('stop','length','content_filter','tool_calls')):
                            raise RuntimeError('Unknown inference completion outcome')
                        row.update(finish_reason=choice['finish_reason'],usage=data.get('usage'))
                        return message['content']
                except BaseException as exc:
                    row.update(status='fatal_error',error=type(exc).__name__+': '+str(exc),retryable=False)
                    persist()
                    raise
            def validate(content):
                row=task_attempts[-1]; answer=None
                try:
                    answer=json.loads(content,object_pairs_hook=distinct_object)
                    if (type(answer) is not dict or set(answer)!=set(EXPECTED)
                            or any(type(answer[key]) is not int for key in ('rows','units','total_cents'))
                            or type(answer['by_item']) is not dict
                            or set(answer['by_item'])!=set(EXPECTED['by_item'])
                            or any(type(value) is not int for value in answer['by_item'].values())):
                        raise ValueError('Answer schema differs')
                except (ValueError,TypeError,KeyError):
                    feedback=('Return only one JSON object with exactly rows, units, total_cents, and by_item. '
                              'Use JSON integers for every numeric value, one entry for each CSV item, '
                              'no duplicate keys, no markdown and no extra text. Recompute from the original CSV.')
                else:
                    feedback='' if answer==EXPECTED else (
                        'The independent arithmetic check rejected the result. Recount CSV data rows, '
                        'sum quantities, multiply quantity by unit_cents for each row, group all repeated '
                        'item rows, and sum the item totals. Recompute from the original CSV.')
                if row['finish_reason']!='stop':
                    feedback=('The response did not finish with the required stop reason. Return a complete final '
                              'JSON answer under the unchanged response budget. '+feedback).strip()
                verdict=Verdict(not feedback,feedback)
                row.update(status='validated',retryable=not verdict.accepted and row['attempt']<3,
                           verdict={'accepted':verdict.accepted,'feedback':verdict.feedback})
                if verdict.accepted: row['answer']=answer
                persist(); event(run,'inference_verdict',index=index,attempt=row['attempt'],accepted=verdict.accepted)
                return verdict
            try:
                outcome=await run_with_feedback(PROMPT,generate,validate,max_attempts=3)
                task.update(accepted=outcome.accepted,status='accepted' if outcome.accepted else 'exhausted')
                persist()
                if not outcome.accepted:
                    raise RuntimeError('Arithmetic artifact exhausted independent acceptance after three attempts')
                final=task_attempts[-1]
                row={key:final[key] for key in ('answer','finish_reason','usage','quality','model',
                     'request_class','gateway_class','request_sha256')}
                row.update(index=index,requested_at=task_attempts[0]['requested_at'],
                           completed_at=final['completed_at'],attempts=outcome.attempts,
                           request_count=len(task_attempts),max_attempts=3,
                           attempt_request_indices=[item['request_index'] for item in task_attempts])
                receipts.append(row); persist()
                event(run,'inference_accepted',index=index,attempts=outcome.attempts)
            except BaseException as exc:
                if task['status']!='exhausted': task['status']='fatal_error'
                task['error']=type(exc).__name__+': '+str(exc); persist()
                raise
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
    for name in ('admission.py','recovery.py','run_recovery.py'):
        source=args.hermes_adapter.resolve()/name
        if plan['pins'].get(str(source))!=digest(source):
            raise RuntimeError('Executed recovery adapter is not the prepared source')
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
    agent_foreground=None
    wait_samples=[]
    agent_foreground_result=None
    agent_foreground_process=None
    for phase,pause in [('before_restart',True),('after_restart',False)]:
        await host.wait_ready(timeout_s=min(240,remaining()))
        remaining()
        ready={'ready':True,'model':plan['model'],'quality':plan['quality'],
               'gateway_instance':host.gateway.instance,
               'gateway':plan['gateway'],'observed_at':time.time()}
        save(run/'controller-ready.json',ready)
        command=[plan['base_python'],'-I','-B',str(args.hermes_adapter/'run_recovery.py'),'worker',
                 '--run',str(run),'--controller-ready',str(run/'controller-ready.json'),
                 '--deadline-monotonic',str(deadline)]
        if pause: command+=['--pause','safe_after_write']
        event(args.run,'hermes_phase',phase=phase)
        with (run/(phase+'.log')).open('wb') as output:
            child=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
            try:
                if pause:
                    while not (run/'pause.json').exists():
                        if child.poll() is not None or time.monotonic()>=deadline:
                            raise RuntimeError('Hermes did not reach durable safe boundary')
                        if agent_foreground is None and host.gateway.scheduler.active is not None:
                            active=host.gateway.scheduler.active
                            event(args.run,'hermes_foreground_starting')
                            agent_foreground=await launch_agent_foreground(args.run)
                            if host.gateway.scheduler.active is not active or active.request_class!='normal':
                                raise RuntimeError('Foreground window did not become ready during the same agent request')
                            agent_foreground_process={'pid':agent_foreground.pid,
                                'active_sequence_at_ready':active.sequence,
                                'active_class_at_ready':active.request_class,
                                'same_active_ticket_at_ready':True,
                                'observed_at_monotonic':time.monotonic(),
                                'ready_sha256':digest(args.run/'hermes-foreground/ready.json')}
                        observed=store.load(plan['task_id'])
                        if (observed.state['phase']=='waiting_admission'
                                and observed.operation is None and not host.controller()):
                            if observed.prompt!=original.prompt or observed.requires_reconciliation:
                                raise RuntimeError('Waiting lost the original safe task')
                            wait_samples.append({'at':time.monotonic(),
                                'task_revision':observed.revision,
                                'controller_state':host.controller.state,
                                'active':host.gateway.scheduler.active is not None})
                        if agent_foreground is not None and agent_foreground.poll() not in (None,0):
                            raise RuntimeError('Agent foreground observation did not qualify')
                        await asyncio.sleep(.1)
                    if agent_foreground is None:
                        raise RuntimeError('No foreground interruption of installed agent occurred')
                    if await wait_process(agent_foreground,min(70,remaining()))!=0:
                        raise RuntimeError('Agent foreground interval failed')
                    agent_foreground_result=json.loads((args.run/'hermes-foreground/result.json').read_text())
                    agent_foreground_process.update(exit_code=agent_foreground.returncode,
                        result_sha256=digest(args.run/'hermes-foreground/result.json'))
                    if (agent_foreground_result.get('valid_foreground_run') is not True
                            or agent_foreground_result.get('paint_interval_p95_ms',float('inf'))>25
                            or agent_foreground_result.get('stalls_over_50ms_fraction',float('inf'))>.01
                            or len(wait_samples)<10
                            or wait_samples[-1]['at']-wait_samples[0]['at']<1):
                        raise RuntimeError('No independently observed durable resource wait')
                    boundary=json.loads((run/'pause.json').read_text())
                    if boundary.get('pid') != child.pid or boundary.get('boundary') != 'safe_after_write':
                        raise RuntimeError('Pause identity or boundary mismatch')
                    before=store.load(plan['task_id'])
                    if (before.revision != boundary.get('revision') or before.operation is not None
                            or before.requires_reconciliation or before.state['phase'] != 'ready'
                            or object_hash(before.state['native_history']) != boundary.get('history_sha256')
                            or before.prompt != original.prompt or before.metadata != original.metadata
                            or before.state.get('deadline_monotonic')!=deadline):
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
                if agent_foreground is not None and agent_foreground.poll() is None:
                    agent_foreground.kill(); await asyncio.to_thread(agent_foreground.wait,10)
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
                    or after.state['requests']-before.state['requests'] != final['provider_calls']
                    or after.state.get('deadline_monotonic')!=deadline):
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
         'deadline_monotonic':deadline,'gateway_instance':host.gateway.instance,
         'agent_foreground':agent_foreground_result,
         'agent_foreground_process':agent_foreground_process,
         'waiting_observations':wait_samples,
         'report_sha256':before_hash,'effect_receipts_unchanged':True,'dispatched_file_effects':1,
         'effect_receipts_sha256':hashlib.sha256(before_receipts).hexdigest(),
         'original_prompt_sha256':object_hash(original.prompt),'resume':selected,'wire_quality':wire_quality,
         'source_sha256':{name:digest(args.hermes_adapter/name) for name in
             ('admission.py','recovery.py','run_recovery.py','test_recovery.py','source-lock.json')}})
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
            'runtime_source_sha256':runtime_sources(),
            'protocol':'immediate-admission-v1',
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
            result['runtime_source_unchanged']=runtime_sources()==result['runtime_source_sha256']
            if not result['runtime_source_unchanged']:
                result['passed']=False
                result['source_error']='Runtime source changed during qualification'
            save(args.run/'result.private.json',result)
            done.set()
            event(args.run,'run_finished',passed=result['passed'])

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--case',choices=['uncontrolled','controlled'],required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--owner-config',type=Path,required=True)
    p.add_argument('--hermes-run',type=Path)
    p.add_argument('--hermes-adapter',type=Path,default=HERE/'hermes')
    p.add_argument('--ffmpeg',type=Path)
    p.add_argument('--ffprobe',type=Path)
    args=p.parse_args()
    if args.case=='controlled' and not all((args.ffmpeg,args.ffprobe)): p.error('Controlled case needs explicit existing FFmpeg and FFprobe')
    if args.hermes_run and args.case!='controlled': p.error('Hermes recovery requires the controlled host')
    if args.hermes_run and not (args.hermes_run/'plan.json').is_file(): p.error('Hermes recovery needs an existing prepared plan')
    if args.hermes_run and not all((args.hermes_adapter/name).is_file() for name in
            ('admission.py','recovery.py','run_recovery.py','test_recovery.py','source-lock.json')):
        p.error('Hermes recovery requires the complete immediate-admission adapter source')
    asyncio.run(main(args))
