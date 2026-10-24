"""Local Adaptive Engine owner. No benchmark imports, model probes or call limit."""
from __future__ import annotations
import argparse
import hashlib
import http.client
import json
import math
import msvcrt
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'runtime/Strata'
PYTHON=Path(json.loads((ROOT/'PROVENANCE.json').read_text(encoding='utf-8'))['dependencies']['strata_python'])
# The detached owner uses the actual interpreter, avoiding a venv redirector
# outside its job. Its packages are the existing, recorded environment's.
SITE=PYTHON.parent.parent/'Lib/site-packages'
if str(SITE) not in sys.path: sys.path.append(str(SITE))
sys.path.insert(0,str(SOURCE))
from strata_control import private_files
import psutil
import owned_job
from ownership import Identities, ProcessHandle
from memory_monitor import MemoryMonitor
from serve import launch_identity
from serve.memory_policy import MemoryPolicy, GIB


def digest(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def exception_diagnostic(exc):
    """Private failure evidence, retaining the original traceback and WinAPI code."""
    out={'type':type(exc).__name__,'message':str(exc),
         'traceback':''.join(traceback.format_exception(exc))}
    for name in ('winerror','errno','operation','pid','access_mask'):
        value=getattr(exc,name,None)
        if value is not None: out[name]=value
    return out


def plan_startup_cache(cfg, reading, now):
    """Apply the existing unloaded-model policy before eager native startup.

    This changes only the RAM cache, never model bytes, context or sampling.
    The chosen startup budget is this run's ceiling; later native ACKs report
    actual allocations, which may be smaller. A fresh run may choose more RAM.
    """
    args=cfg['args']
    index=args.index('--resident-budget-gib')+1
    cap=float(args[index]); reserve=int(args[args.index('--vram-reserve-mib')+1])
    policy=MemoryPolicy(cfg['memory_policy'],resident_cap_gib=cap,vram_reserve_mib=reserve)
    plan=policy.plan_for_load(reading,now)
    if plan is None or now-reading['sampled_at']>2:
        raise RuntimeError('Startup cache planning requires fresh complete memory telemetry')
    available=min(reading['ram_total']-reading['ram_used'],reading['ram_commit_available'])/GIB
    headroom=max(policy.headroom,reading['ram_total']/GIB*(1-policy.ram_target))
    allowance=available-headroom-policy.overhead
    # plan_for_load deliberately clamps low budgets to one GiB. It does not
    # prove that even one GiB fits; admission must reject that case first.
    if allowance<1: raise RuntimeError('Startup lacks space for overhead, headroom and a 1 GiB resident cache')
    # Do not let the policy's nearest-decimal rounding exceed the raw room.
    chosen=math.floor(min(plan['resident_budget_gib'],allowance,cap)*32)/32
    if chosen<1: raise RuntimeError('Startup resident cache is below the supported policy minimum')
    args[index]=format(chosen,'.8g')
    return {'reading':dict(reading),'configured_cap_gib':cap,'available_ram_commit_gib':available,
            'overhead_gib':policy.overhead,'required_headroom_gib':headroom,
            'raw_allowance_gib':allowance,'resident_budget_gib':chosen,
            'policy_plan':plan,'rounding':'down to 32 MiB',
            'scope':'startup proposal and per-run cap; native allocation remains authoritative'}


def save(path,value):
    path=Path(path); temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    # A Windows reader can briefly deny replacement. Keep the old complete
    # snapshot visible and bound the retry; never fall back to a partial write.
    deadline=time.monotonic()+1
    try:
        while True:
            try: os.replace(temp,path); return
            except PermissionError:
                if time.monotonic()>=deadline: raise
                time.sleep(.01)
    finally:
        if temp.exists(): temp.unlink()


def private_directory(path):
    path=Path(path)
    if path.is_symlink() or path.exists() and path.lstat().st_file_attributes & 0x400:
        raise RuntimeError('Refusing a reparse point for owned state')
    private_files.private_mkdir(path,parents=True,exist_ok=True)
    private_files.restrict_to_current_user(path,directory=True)
    if not private_files.is_unshared(path): raise RuntimeError('Owned state is not private')


def lock(path):
    stream=Path(path).open('a+b')
    try:
        if os.fstat(stream.fileno()).st_size==0: stream.write(b'0'); stream.flush()
        stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
    except BaseException: stream.close(); raise
    return stream


def unlock(stream):
    stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1); stream.close()


def verify():
    manifest=read(ROOT/'MANIFEST.json'); provenance=read(ROOT/'PROVENANCE.json')
    for relative,sha in manifest['files'].items():
        path=ROOT/relative
        if not path.resolve().is_relative_to(ROOT) or not path.is_file() or digest(path)!=sha:
            raise RuntimeError('Package file changed: '+relative)
    for path,sha in provenance['dependencies_sha256'].items():
        if digest(path)!=sha: raise RuntimeError('External runtime changed: '+path)
    for name,identity in provenance['asset_metadata'].items():
        stat=Path(name).stat()
        if {'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}!=identity:
            raise RuntimeError('Model asset metadata changed: '+name)
    cfg=read(ROOT/'config/server-template.json'); args=cfg['args']
    if (cfg['port']!=18098 or cfg['cwd']!=str(SOURCE) or cfg['exe']!=str(ROOT/'runtime/native/strata.exe')
        or args[args.index('--max-context')+1]!='65536' or '--mtp' in args
        or cfg['reasoning_budget_tokens']!=8192 or cfg['reasoning_effort']!='high'
        or cfg['sampling']['experimental_speed_projection'] is not False or cfg['vision']['gpu'] is not False):
        raise RuntimeError('Qualified configuration changed')
    return {'manifest_sha256':digest(ROOT/'MANIFEST.json'),'provenance_sha256':digest(ROOT/'PROVENANCE.json'),
            'files':len(manifest['files']),'model_assets':len(provenance['asset_metadata']),
            'model_asset_content_hashed':False,'native_sha256':provenance['native_sha256']}


def active_run():
    pointer=read(ROOT/'state/active.json'); run=Path(pointer['run']).resolve(strict=True)
    if not run.is_relative_to((ROOT/'runs').resolve()) or run.is_symlink():
        raise RuntimeError('Active run is outside this project')
    state=read(run/'owner.json')
    if state['owner_id']!=pointer['owner_id']: raise RuntimeError('Owner identity does not match active run')
    return run,state


def rpc(run,owner_id,method):
    control=read(run/'control.json')
    if control['owner_id']!=owner_id: raise RuntimeError('Control owner identity changed')
    with socket.create_connection(('127.0.0.1',control['port']),timeout=3) as sock:
        sock.sendall((json.dumps({'owner_id':owner_id,'token':control['token'],'method':method})+'\n').encode())
        data=sock.makefile('rb').readline(65537)
        if not data or len(data)>65536: raise RuntimeError('Invalid owner response')
        value=json.loads(data)
        if value.get('owner_id')!=owner_id: raise RuntimeError('Owner response identity mismatch')
        return value


def status():
    try: run,state=active_run()
    except FileNotFoundError: return {'state':'stopped','running':False,'project':str(ROOT)}
    if state['state'] in ('stopped','failed'): return state
    try:
        handle=ProcessHandle(state['owner']['pid'],state['owner'])
        try:
            if handle.exited(): return {**state,'state':'owner_exited','running':False}
            return rpc(run,state['owner_id'],'status')
        finally: handle.close()
    except (OSError,RuntimeError,ValueError):
        return {**state,'state':'unreachable','running':None,'note':'No stale PID is signalled by status'}


def get_api(port,path):
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
    try:
        conn.request('GET',path); reply=conn.getresponse(); raw=reply.read(2**20+1)
        if reply.status!=200 or len(raw)>2**20: raise RuntimeError('Engine status unavailable')
        return json.loads(raw)
    finally: conn.close()


def owned_server_command(run,env,*,port=18098,backend='strata'):
    """Use the server's existing config/argv MAC contract; no key is written to disk."""
    args=['--engine',backend,'--config',str(run/'server.json'),'--host','127.0.0.1','--port',str(port),
          '--fit-max-tokens','--owner-fd','0','--shutdown-timeout','30',
          '--ready-file',str(run/'server-ready.json')]
    key=secrets.token_bytes(32)
    expected=launch_identity.attestation(key,(run/'server.json').read_bytes(),args)
    env['STRATA_OWNER_ATTEST_KEY']=key.hex()
    return [str(PYTHON),'-B','-m','serve.server',*args],expected


def verify_launch_attestation(telemetry,expected):
    actual=telemetry.get('instance',{}).get('launch_attestation')
    if not isinstance(actual,str) or not secrets.compare_digest(actual,expected):
        raise RuntimeError('Live configuration/arguments do not match owned launch attestation')


class Owner:
    def __init__(self,run,request):
        self.run,self.request=run,request; self.owner_id=request['owner_id']
        self.stop_requested=threading.Event(); self.control_done=threading.Event(); self.lock=threading.RLock()
        self.finished=threading.Event()
        self.child=None; self.memory=None; self.identities=None; self.listener=None
        self.started=time.monotonic(); self.stop_reason='requested'; self.urgent=False
        self.state={'owner_id':self.owner_id,'run':str(run),'project':str(ROOT),'state':'starting',
                    'running':True,'api_url':'http://127.0.0.1:18098/v1','port':18098,
                    'max_runtime_seconds':request['max_runtime_seconds'],'started_at':time.time()}

    def publish(self):
        with self.lock:
            self.state['updated_at']=time.time()
            save(self.run/'owner.json',self.state)

    def snapshot(self):
        with self.lock:
            processes=self.identities.snapshot() if self.identities else None
            if processes: processes['completed_tail']=processes['completed_tail'][-16:]
            return {**self.state,'memory':self.memory.snapshot() if self.memory else None,
                    'processes':processes}

    def request_stop(self,reason,urgent=False):
        with self.lock:
            self.stop_reason=reason; self.urgent=self.urgent or urgent; self.stop_requested.set()

    def start_control(self):
        self.listener=socket.socket(); self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        self.listener.bind(('127.0.0.1',0)); self.listener.listen(8); self.listener.settimeout(.2)
        token=secrets.token_hex(32)
        save(self.run/'control.json',{'owner_id':self.owner_id,'port':self.listener.getsockname()[1],'token':token})
        def loop():
            while not self.control_done.is_set():
                try: conn,_=self.listener.accept()
                except socket.timeout: continue
                except OSError: return
                with conn:
                    conn.settimeout(2)
                    try:
                        raw=conn.makefile('rb').readline(4097)
                        if len(raw)>4096: continue
                        msg=json.loads(raw)
                        if msg.get('owner_id')!=self.owner_id or not secrets.compare_digest(str(msg.get('token','')),token): continue
                        if msg.get('method')=='stop': self.request_stop('requested')
                        elif msg.get('method')!='status': continue
                        conn.sendall((json.dumps(self.snapshot(),allow_nan=False)+'\n').encode())
                    except (OSError,ValueError): pass
        threading.Thread(target=loop,name='owner-control',daemon=True).start()

    def launch(self):
        provenance=read(ROOT/'PROVENANCE.json')
        self.memory=MemoryMonitor(provenance['dependencies']['nvml'],
                                  provenance['dependencies_sha256'][provenance['dependencies']['nvml']])
        self.memory.start()
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1); sock.bind(('127.0.0.1',18098))
        cfg=json.loads(json.dumps(read(ROOT/'config/server-template.json')).replace('@RUN@',self.run.as_posix()))
        self.state['startup_cache_plan']=plan_startup_cache(cfg,self.memory.startup_reading(),time.time())
        self.publish()
        for leaf in ('tmp','cuda','hf','xdg'): (self.run/'state/cache'/leaf).mkdir(parents=True,exist_ok=True)
        (self.run/'state/appdata').mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'runtime/expert-profile.seed.bin',self.run/'state/expert-profile.bin')
        save(self.run/'server.json',cfg)
        env={k:v for k,v in os.environ.items() if not k.upper().startswith(
            ('STRATA_','HERMES_','OPENAI_','ANTHROPIC_','OPENROUTER_','GGML_'))}
        lease=secrets.token_hex(32); save(self.run/'resource-lease.json',{'token':lease,'owner_id':self.owner_id})
        env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',STRATA_NO_ACQUIRE='1',
                   STRATA_RESOURCE_LEASE_TOKEN=lease,STRATA_RUNTIME_DIR=str(self.run/'state/runtime'),
                   LOCALAPPDATA=str(self.run/'state/appdata'))
        for key in ('TEMP','TMP','TMPDIR','CUDA_CACHE_PATH','HF_HOME','XDG_CACHE_HOME'): env[key]=cfg['env'][key]
        command,expected=owned_server_command(self.run,env)
        self.state['expected_launch_attestation']=expected
        with (self.run/'server.log').open('xb') as log:
            self.child=subprocess.Popen(command,cwd=SOURCE,env=env,stdin=subprocess.PIPE,
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        self.state['effective_config_sha256']=digest(self.run/'server.json')
        self.publish()

    def check_ready(self):
        try:
            ready=read(self.run/'server-ready.json')
            owned={r['pid']:r for r in self.identities.snapshot()['active']}
            if ready['pid'] not in owned: return False
            listeners={c.pid for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and
                       c.laddr.port==18098 and c.laddr.ip=='127.0.0.1'}
            if listeners!={ready['pid']}: raise RuntimeError('HTTP listener does not belong to this exact server')
            telemetry=get_api(18098,'/v1/telemetry'); live=get_api(18098,'/v1/status')
            if telemetry['instance']['id']!=ready['instance_id']: raise RuntimeError('Ready/live instance mismatch')
            verify_launch_attestation(telemetry,self.state['expected_launch_attestation'])
            if not live.get('loaded'): return False
            if live['context']['native']!=65536 or not live['inference_scheduling']['enabled']:
                raise RuntimeError('Live context or scheduler does not match')
            self.state.update(state='ready',server=owned[ready['pid']],instance_id=ready['instance_id'],
                              model=live['model'],ready_at=time.time()); self.publish(); return True
        except (FileNotFoundError,OSError,ValueError): return False

    def finish(self):
        errors=[]
        def attempt(stage,operation,default=None):
            try: return operation()
            except BaseException as exc:
                errors.append({'stage':stage,**exception_diagnostic(exc)})
                return default

        self.state.update(state='stopping',stop_reason=self.stop_reason)
        attempt('publish_stopping',self.publish)
        if self.child and self.child.stdin:
            attempt('close_server_stdin',self.child.stdin.close)
        deadline=time.monotonic()+(0 if self.urgent else 40)
        def drain():
            while self.child and self.child.poll() is None and time.monotonic()<deadline:
                self.identities.collect(); time.sleep(.1)
        attempt('drain_owned_server',drain)
        cleanup=attempt('cleanup_owned_processes',self.identities.cleanup,False) if self.identities else True
        if self.child:
            attempt('wait_owned_server',lambda:self.child.wait(timeout=2))
        # None records unavailable evidence. Never fabricate an empty process
        # list or confirmed exits after collection/snapshot failure.
        processes=attempt('snapshot_owned_processes',self.identities.snapshot) if self.identities else None
        memory=attempt('close_memory_monitor',self.memory.close) if self.memory else None
        if memory and memory.get('error'): self.state['error']=self.state.get('error') or memory['error']
        if self.identities: attempt('close_retained_handles',self.identities.close)
        self.control_done.set()
        if self.listener: attempt('close_control_listener',self.listener.close)

        def finalize():
            if errors:
                self.state['cleanup_error']=errors[0]['message']
                self.state['cleanup_errors']=list(errors)
            confirmed=bool(cleanup) and not errors
            self.state.update(state='stopped' if confirmed and not self.state.get('error') else 'failed',
                running=False if confirmed else None,cleanup_confirmed=confirmed,processes=processes,memory=memory,
                process_snapshot_available=processes is not None,
                server_exit_code=self.child.returncode if self.child else None,stopped_at=time.time())
        finalize()
        attempt('publish_terminal',self.publish)
        finalize()
        before=len(errors)
        attempt('save_terminal_result',lambda:save(self.run/'result.json',self.state))
        if len(errors)!=before:
            finalize()
            attempt('publish_result_write_failure',self.publish)
            finalize()
            print(json.dumps({'owner_id':self.owner_id,'state':'failed','cleanup_errors':errors}),file=sys.stderr)
        self.finished.set()
        return 0 if self.state['state']=='stopped' else 1

    def run_owner(self):
        lease=lock(ROOT/'state/owner.lock')
        try:
            # The owner joins before ANY child. Its sole, noninherited handle
            # also covers abrupt exits and the native engine's nested jobs.
            owned_job.contain_current_process(); self.identities=Identities(owned_job)
            mine=ProcessHandle(os.getpid()); self.state['owner']=dict(mine.record); mine.close()
            self.publish()
            save(ROOT/'state/active.json',{'run':str(self.run),'owner_id':self.owner_id})
            self.start_control()
            def watchdog():
                stopping_at=None
                while not self.finished.wait(.1):
                    elapsed=time.monotonic()-self.started
                    limit=self.request['max_runtime_seconds']
                    if limit is not None and elapsed>=limit and not self.stop_requested.is_set():
                        self.request_stop('maximum_runtime')
                    if self.state['state']=='starting' and elapsed>=300 and not self.stop_requested.is_set():
                        self.request_stop('startup_deadline',urgent=True)
                    if self.stop_requested.is_set():
                        stopping_at=stopping_at or time.monotonic()
                        if time.monotonic()-stopping_at>=60:
                            # Last-resort process exit closes this job's sole
                            # handle even if a driver or shutdown call is stuck.
                            os._exit(124)
            threading.Thread(target=watchdog,name='owner-deadline',daemon=True).start()
            try:
                self.state['verification']=verify(); self.publish()
                if self.stop_requested.is_set(): return self.finish()
                self.launch()
                while not self.stop_requested.is_set():
                    self.identities.collect(); self.memory.check()
                    if self.child.poll() is not None: raise RuntimeError('Owned server exited')
                    elapsed=time.monotonic()-self.started
                    limit=self.request['max_runtime_seconds']
                    if limit is not None and elapsed>=limit: self.request_stop('maximum_runtime'); break
                    if self.state['state']=='starting':
                        if not self.check_ready() and elapsed>=300: raise RuntimeError('Startup deadline exceeded')
                    time.sleep(.1)
            except BaseException as exc:
                self.state['error']=str(exc)
                self.state['error_diagnostic']=exception_diagnostic(exc)
                traceback.print_exception(exc,file=sys.stderr)
                self.request_stop(type(exc).__name__,urgent=True)
            return self.finish()
        finally: unlock(lease)


def start(wait,max_runtime):
    private_directory(ROOT/'state'); private_directory(ROOT/'runs')
    launch_lock=lock(ROOT/'state/start.lock')
    try:
        try: own_lock=lock(ROOT/'state/owner.lock')
        except OSError: return status()
        else: unlock(own_lock)
        verified=verify(); owner_id=uuid.uuid4().hex
        run=ROOT/'runs'/time.strftime('%Y%m%d-%H%M%S')
        run=run.with_name(run.name+'-'+owner_id[:8]); private_directory(run)
        request={'owner_id':owner_id,'max_runtime_seconds':max_runtime,'verification':verified}
        save(run/'request.json',request)
        # Use the real interpreter: the long-lived owner must not sit behind a
        # separate virtual-environment launcher that a stop could mistake for it.
        interpreter=read(ROOT/'PROVENANCE.json')['dependencies']['owner_python']
        with (run/'owner.log').open('xb') as log:
            proc=subprocess.Popen([interpreter,'-B',str(ROOT/'engine.py'),'_host',str(run),owner_id],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS,close_fds=True)
        deadline=time.monotonic()+wait
        while time.monotonic()<deadline:
            if (run/'owner.json').exists():
                value=status()
                if value.get('owner_id')==owner_id and value['state'] in ('ready','stopped','failed'): return value
            if proc.poll() is not None:
                return read(run/'owner.json') if (run/'owner.json').exists() else {
                    'state':'failed','error':'Owner exited before publication','run':str(run),'exit_code':proc.returncode}
            time.sleep(.2)
        value=status()
        return value if value.get('owner_id')==owner_id else {
            'state':'starting','running':True,'owner_id':owner_id,'run':str(run),
            'api_url':'http://127.0.0.1:18098/v1','note':'New owner has not published readiness yet'}
    finally: unlock(launch_lock)


def stop(wait):
    try: run,state=active_run()
    except FileNotFoundError: return {'state':'stopped','running':False}
    if state['state'] in ('stopped','failed'): return state
    handle=ProcessHandle(state['owner']['pid'],state['owner'])
    try:
        # Creation time + retained handle + exact owner invocation. Never kill a
        # PID from a stale ready file or an unrelated process with the same name.
        command=psutil.Process(state['owner']['pid']).cmdline()
        if str(ROOT/'engine.py') not in command or '_host' not in command or str(run) not in command:
            raise RuntimeError('Refusing a process that is not this project owner')
        try: rpc(run,state['owner_id'],'stop')
        except (OSError,ValueError,RuntimeError): pass
        until=time.monotonic()+wait
        while time.monotonic()<until:
            if handle.exited():
                value=read(run/'owner.json')
                return value if value['state'] in ('stopped','failed') else {
                    **value,'state':'owner_exited','running':False,'cleanup_confirmed':False}
            time.sleep(.1)
        handle.terminate()  # Exact retained owner; Windows closes its owned job.
        end=time.monotonic()+5
        while not handle.exited() and time.monotonic()<end: time.sleep(.05)
        return {**state,'state':'owner_terminated','running':not handle.exited(),'emergency_stop':True,
                'cleanup_confirmed':False,'note':'Owned job closed; final per-process receipt unavailable'}
    finally: handle.close()


def main():
    parser=argparse.ArgumentParser(description='Start, inspect or stop this Adaptive Engine only.')
    parser.add_argument('action',choices=('start','status','stop','verify','_host'))
    parser.add_argument('internal',nargs='*'); parser.add_argument('--json',action='store_true')
    parser.add_argument('--wait',type=float)
    parser.add_argument('--max-runtime-seconds',type=float)
    args=parser.parse_args()
    try:
        if args.action=='_host':
            run=Path(args.internal[0]).resolve(strict=True); request=read(run/'request.json')
            if not run.is_relative_to((ROOT/'runs').resolve()) or request['owner_id']!=args.internal[1]:
                raise RuntimeError('Invalid owner request')
            return Owner(run,request).run_owner()
        if args.internal: raise ValueError('Unexpected positional arguments')
        if args.max_runtime_seconds is not None and not 60<=args.max_runtime_seconds<=604800:
            raise ValueError('Optional runtime limit must be between 60 seconds and 7 days')
        wait=args.wait if args.wait is not None else (300 if args.action=='start' else 75)
        if not 1<=wait<=600: raise ValueError('Wait must be between 1 and 600 seconds')
        value=(start(wait,args.max_runtime_seconds) if args.action=='start' else stop(wait) if args.action=='stop'
               else status() if args.action=='status' else {'verified':True,**verify()})
        print(json.dumps(value,indent=2,allow_nan=False))
        return 1 if value.get('state') in ('failed','unreachable','owner_terminated','owner_exited') else 0
    except Exception as exc:
        print(json.dumps({'state':'failed','error':str(exc)})); return 1


if __name__=='__main__': raise SystemExit(main())
