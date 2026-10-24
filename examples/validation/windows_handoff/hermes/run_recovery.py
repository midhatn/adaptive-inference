# SPDX-License-Identifier: Apache-2.0
"""Bounded installed-Hermes restart fixture/runner; never controls a model service."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import site
import socket
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
SDK_REV = '14e1e43a23761b369641208e204365cd6cb9399d'
MODEL = 'qwen3.8-flash-next-iq3_s-adaptive-media-beta'
QUALITY = {'max_tokens': 10923, 'reasoning_effort': 'high', 'reasoning_budget_tokens': 8192,
           'experimental_speed_projection': False, 'strata_tune': {'pcie_frac': .37}}
PROMPT = ('Read orders.csv with read_file. Compute quantity times unit_cents for each data row, '
          'aggregate by item, and write report.json using write_file. The JSON must have exactly '
          'rows (data row count), units (sum of quantities), total_cents, and by_item (item-to-cents map). '
          'Use integers. Use only read_file and write_file, do not use shell or other tools. '
          'Finish only after the write succeeds. Reply briefly describing the created artifact.')
CONTINUE = ('Continue the original saved task from this exact conversation. Preserve completed tool results '
            'and do not repeat completed writes. Finish the original objective and report its outcome.')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setup(plan):
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(Path(plan['canonical']) / 'src'))
    site.addsitedir(plan['site_packages'])
    import recovery
    base = load_module('bounded_task', Path(plan['canonical']) / 'examples/validation/hermes_tool_task/run_task.py')
    base.configure_inputs(plan['sdk'], plan['python'], Path(plan['canonical']) / 'plugins/hermes', plan['gateway'], MODEL)
    return recovery, base


def prepare(args):
    run = args.run.resolve()
    sdk, canonical, python = [p.resolve(strict=True) for p in (args.hermes_source, args.canonical, args.python)]
    base_python = subprocess.check_output([str(python), '-I', '-c', 'import sys;print(sys._base_executable)'], text=True).strip()
    plan = {'sdk': str(sdk), 'sdk_revision': SDK_REV, 'canonical': str(canonical), 'python': str(python),
            'base_python': base_python, 'site_packages': str(python.parent.parent / 'Lib/site-packages'),
            'gateway': args.gateway_url, 'model': MODEL, 'quality': QUALITY, 'fixture': args.fixture,
            'task_id': 'orders-report', 'session_id': 'adaptive-restart-' + run.name, 'max_requests': 8,
            'fixture_scenario':args.fixture_scenario}
    if args.fixture_scenario!='normal' and not args.fixture:
        raise ValueError('Synthetic admission scenario requires fixture mode')
    rec, base = setup(plan)
    if base.git('rev-parse', 'HEAD') != SDK_REV or base.git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Installed SDK identity changed')
    run.mkdir(parents=True, exist_ok=False)
    work = run / 'work'; work.mkdir()
    (work / 'orders.csv').write_text(base.CSV, encoding='utf-8', newline='\n')
    (run / 'phase.txt').write_text('parent', encoding='utf-8')
    home = run / 'home'; home.mkdir()
    plugin = home / 'plugins/recovery-checkpoint'; plugin.mkdir(parents=True)
    (plugin / '__init__.py').write_text('from recovery import register\n', encoding='utf-8')
    (plugin / 'plugin.yaml').write_text("name: recovery-checkpoint\nversion: '0.1.0'\ndescription: Explicit owned restart checkpoint.\n", encoding='utf-8')
    config = base.config(work)
    config['plugins'] = {'enabled': ['recovery-checkpoint']}
    rec.save(home / 'config.yaml', config)
    from adaptive_inference.task_store import TaskStore
    TaskStore(run / 'task.sqlite3').create(plan['task_id'], PROMPT, max_attempts=8,
        metadata={'sdk_revision': SDK_REV, 'model': MODEL, 'quality': QUALITY},
        state=rec.initial_state(PROMPT, plan['session_id']))
    pins = [HERE / 'admission.py', HERE / 'recovery.py', HERE / 'run_recovery.py', canonical / 'src/adaptive_inference/task_store.py',
            canonical / 'examples/validation/hermes_tool_task/run_task.py', home / 'config.yaml',
            plugin / '__init__.py', plugin / 'plugin.yaml', work / 'orders.csv']
    plan['pins'] = {str(p): rec.digest(p.read_bytes()) for p in pins}
    rec.save(run / 'plan.json', plan)
    print(json.dumps({'prepared': True, 'model_started': False, 'fixture': args.fixture}))


def worker(args):
    run = args.run.resolve(strict=True)
    plan = json.loads((run / 'plan.json').read_text(encoding='utf-8'))
    if (plan.get('sdk_revision') != SDK_REV or plan.get('model') != MODEL
            or plan.get('quality') != QUALITY or type(plan.get('fixture')) is not bool
            or plan.get('max_requests') != 8 or plan.get('task_id') != 'orders-report'):
        raise ValueError('Prepared source/quality/request contract differs')
    # Verify with stdlib before importing the pinned adapter/helper or loading
    # dependency .pth files. A rejected changed consumer must never execute.
    for path, expected in plan['pins'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Pinned integration input changed before import')
    for key in list(os.environ):
        if key.startswith(('HERMES_', 'OPENAI_', 'ANTHROPIC_', 'STRATA_')) or key in ('PYTHONPATH', 'PYTHONHOME'):
            os.environ.pop(key, None)
    os.environ.update(HERMES_HOME=str(run / 'home'), HERMES_BUNDLED_PLUGINS=str(run / 'empty-bundled'),
                      PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
    rec, base = setup(plan)
    import admission
    if base.git('rev-parse', 'HEAD') != SDK_REV or base.git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Installed SDK changed')
    sys.path.insert(0, plan['sdk'])
    import httpx
    from adaptive_inference.task_store import TaskStore, ReconciliationRequired
    from hermes_state import SessionDB
    result = {'passed': False, 'fixture': plan['fixture'], 'sdk_revision': SDK_REV,
              'model': MODEL, 'quality': QUALITY, 'mode': args.mode}
    store = TaskStore(run / 'task.sqlite3')
    db = agent = provider = None
    original_send = httpx.Client.send
    original_connect, original_ex = socket.socket.connect, socket.socket.connect_ex
    original_pair, original_dns = socket.socketpair, socket.getaddrinfo
    pair_state = threading.local()

    class Boundary(base.Boundary):
        provider = None
        fixture_posts = 0
        def send(self,client,req,**kw):
            try:
                return super().send(client,req,**kw)
            except admission.Deferred as exc:
                # The base audit has recorded the prepared call. A complete
                # no-dispatch proof moves it to the separate admission ledger.
                row=self.rows.pop()
                if row['body_sha256']!=exc.proof['body_sha256']:
                    raise rec.RecoveryStop('Deferred request audit mismatch')
                self.steps[row['phase']]-=1;self.seen.remove(row['body_sha256'])
                base.save(self.run/'wire-observations.json',self.rows)
                path=self.run/'admission-attempts.json'
                old=json.loads(path.read_text()) if path.exists() else []
                old.append({'proof':exc.proof,'started_at':row['started_at'],'finished_at':time.time()})
                base.save(path,old)
                raise

        def transport(self,client,req,**kw):
            if self.provider is not None:self.provider.inspect_request(req)
            response=original_send(client,req,**kw)
            if self.provider is not None and req.method=='POST':self.provider.inspect_response(req,response)
            return response

        def fake_response(self, req, phase, step):
            self.provider.inspect_request(req)
            self.fixture_posts+=1
            scenario=plan.get('fixture_scenario','normal')
            if scenario=='unknown-failure' and len(self.rows)==2:
                raise httpx.ReadTimeout('Synthetic unknown transport outcome',request=req)
            if scenario=='wait-race' and self.fixture_posts==1:
                proof={'dispatched':False,'gateway_instance':self.provider.instance,
                       'attempt_id':self.provider.current_attempt,'body_sha256':admission.sha(req.content)}
                response=httpx.Response(503,request=req,headers={
                    'X-Adaptive-Dispatch':'not-dispatched','X-Adaptive-Gateway-Instance':proof['gateway_instance'],
                    'X-Adaptive-Attempt-Id':proof['attempt_id'],'X-Adaptive-Body-SHA256':proof['body_sha256']},
                    json={'error':{'type':'adaptive_inference_error','code':'admission_deferred'},'admission':proof})
                self.provider.inspect_response(req,response)
            body = json.loads(req.content)
            tools = [row for row in body['messages'] if row.get('role') == 'tool']
            if any('verified' in str(row.get('content', '')) and 'true' in str(row.get('content', '')).lower() for row in tools):
                return super().fake_response(req, 'parent', 2)
            return super().fake_response(req, 'parent', 1 if tools else 0)

    boundary = Boundary(run, plan['fixture'])
    if (run / 'wire-observations.json').exists():
        boundary.rows = json.loads((run / 'wire-observations.json').read_text())
        boundary.steps['parent'] = len(boundary.rows)
        boundary.seen = {r['body_sha256'] for r in boundary.rows}
    boundary.original = boundary.transport
    starting_requests = len(boundary.rows)
    httpx.Client.send = lambda client, req, **kw: boundary.send(client, req, **kw)
    def connect(sock, address, ex=False):
        internal = getattr(pair_state, 'active', False) and address[0] in ('127.0.0.1', '::1')
        if not internal and (plan['fixture'] or address[:2] != ('127.0.0.1', base.urlsplit(plan['gateway']).port)):
            raise OSError('Only the declared gateway is allowed; fixture has no network')
        return (original_ex if ex else original_connect)(sock, address)
    def pair(*a, **k):
        pair_state.active = True
        try: return original_pair(*a, **k)
        finally: pair_state.active = False
    def dns(host, *a, **k):
        if host not in (None, 'localhost', '127.0.0.1', '::1'):
            raise OSError('External DNS disabled')
        return original_dns(host, *a, **k)
    socket.socket.connect = lambda s, a: connect(s, a)
    socket.socket.connect_ex = lambda s, a: connect(s, a, True)
    socket.socketpair, socket.getaddrinfo = pair, dns
    try:
        cp = store.load(plan['task_id'])
        if (cp.prompt != PROMPT or cp.max_attempts != 8 or cp.metadata != {
                'sdk_revision': SDK_REV, 'model': MODEL, 'quality': QUALITY}):
            raise ReconciliationRequired('Original task identity differs from the prepared contract')
        with store.claim(plan['task_id'], expected_revision=cp.revision) as owned:
            if not plan['fixture']:
                deadline=args.deadline_monotonic
                if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                        or not 0 < deadline-time.monotonic() <= 900):
                    raise ValueError('Explicit remaining whole-task deadline required')
                previous=owned.checkpoint.state.get('deadline_monotonic')
                if previous is not None and previous!=deadline:
                    raise ReconciliationRequired('Whole task deadline cannot reset across restart')
                if previous is None:
                    state=rec.copy.deepcopy(owned.checkpoint.state);state['deadline_monotonic']=deadline
                    owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
            db = SessionDB(run / 'home/state.db')
            if args.mode == 'reconcile':
                if not args.receipt:
                    raise ValueError('Explicit --receipt file required')
                receipt = json.loads(args.receipt.read_text(encoding='utf-8'))
                rec.reconcile_write(owned, db, run / 'work', receipt,
                                    expected_operation_id=args.operation_id)
                result.update(passed=True, reconciled=True, provider_calls=0)
            else:
                history = rec.resumable(owned, db, run / 'work')
                if owned.checkpoint.state['status'] == 'accepted':
                    result.update(passed=True, terminal_noop=True, provider_calls=0)
                else:
                    # Root/controller owns readiness. Never construct an agent while parked;
                    # metadata discovery uses GET and is not an admitted model generation.
                    if not plan['fixture']:
                        if not args.controller_ready:
                            raise ValueError('Explicit fresh controller readiness receipt required')
                        ready = json.loads(args.controller_ready.read_text(encoding='utf-8'))
                        if (ready.get('ready') is not True or ready.get('model') != MODEL
                                or ready.get('quality') != QUALITY or ready.get('gateway') != plan['gateway']
                                or not 0 <= time.time() - ready.get('observed_at', 0) <= 30):
                            raise ValueError('Controller readiness receipt is stale or differs')
                        instance=ready.get('gateway_instance')
                    else:
                        instance='f'*32
                    clock=None
                    if plan['fixture']:
                        clock=type('FixtureClock',(),{'now':0.0})()
                        def tick(seconds):clock.now+=seconds
                        def status():
                            allowed=plan.get('fixture_scenario')!='wait-race' or clock.now>=181
                            return {'service':'adaptive-inference','instance':instance,
                                'scheduler':{'active':False,'pending':0,'closing':False,'backend_completion_uncertain':False},
                                'resources':{'admission_allowed':allowed}}
                        provider=admission.Provider(base_url=plan['gateway'],model=MODEL,instance=instance,
                            boundary=boundary,deadline=900,status=status,clock=lambda:clock.now,sleep=tick)
                    else:
                        provider=admission.Provider(base_url=plan['gateway'],model=MODEL,instance=instance,
                            boundary=boundary,deadline=deadline)
                    boundary.provider=provider
                    controller = rec.Recovery(owned, db, run / 'work', run, pause=args.pause)
                    controller.provider=provider
                    rec.ACTIVE = controller
                    from run_agent import AIAgent
                    agent = AIAgent(base_url=plan['gateway'], api_key='local-no-key', provider='custom:adaptive',
                        model=MODEL, api_mode='chat_completions', max_iterations=8, enabled_toolsets=['file'],
                        quiet_mode=True, platform='cli', skip_context_files=True, skip_memory=True,
                        skip_background_review=True, max_tokens=10923, reasoning_config={'enabled': True, 'effort': 'high'},
                        request_overrides={'extra_body': QUALITY}, cwd=str(run / 'work'),
                        session_id=plan['session_id'], session_db=db)
                    controller.agent = agent
                    if plan['fixture']:
                        def private_transport_forbidden(*_args,**_kwargs):
                            raise AssertionError('Private Hermes watchdog/transport was invoked')
                        agent._interruptible_api_call=private_transport_forbidden
                        result['private_transport_sentinel_installed']=True
                    result['context'] = base.snapshot(agent)
                    from hermes_cli.plugins import get_plugin_manager
                    plugin = get_plugin_manager()._plugins['recovery-checkpoint']
                    if not plugin.enabled or plugin.error:
                        raise rec.RecoveryStop('Recovery middleware did not register')
                    before = len(boundary.rows)
                    outcome = agent.run_conversation(CONTINUE if history else PROMPT,
                                                     conversation_history=history or None)
                    report = json.loads((run / 'work/report.json').read_text(encoding='utf-8'))
                    if report != base.REPORT:
                        raise rec.RecoveryStop('Original artifact acceptance failed')
                    controller.finish(outcome)
                    result.update(passed=True, provider_calls=len(boundary.rows) - before,
                        resumed=bool(history), original_prompt_sha256=rec.digest(PROMPT),
                        transcript_rows=len(owned.checkpoint.state['native_history']),
                        transcript_sha256=rec.digest(owned.checkpoint.state['native_history']),
                        artifacts={'report.json': rec.digest((run / 'work/report.json').read_bytes())},
                        report=report, completed=outcome.get('completed'),
                        admission_attempts=owned.checkpoint.state.get('admission_attempts',0),
                        admission_deferrals=len(owned.checkpoint.state.get('admission_deferrals',[])),
                        fixture_admission_clock_s=clock.now if clock else None)
    except BaseException as exc:
        result.update(error_type=type(exc).__name__, error=str(exc), provider_calls=len(boundary.rows)-starting_requests)
        chain=[];seen=set();cause=exc
        while cause is not None and id(cause) not in seen and len(chain)<8:
            seen.add(id(cause));chain.append(type(cause).__name__)
            cause=getattr(cause,'original',None) or cause.__cause__ or cause.__context__
        result['error_chain_types']=chain
    finally:
        if agent is not None:
            agent.close()
        if db is not None:
            db.close()
        if provider is not None:
            provider.close()
        httpx.Client.send = original_send
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_ex
        socket.socketpair, socket.getaddrinfo = original_pair, original_dns
        rec.save(run / f'result-{os.getpid()}.json', result)
    return 0 if result['passed'] else 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['prepare', 'worker', 'reconcile'])
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--hermes-source', type=Path)
    p.add_argument('--canonical', type=Path)
    p.add_argument('--python', type=Path)
    p.add_argument('--gateway-url', default='http://127.0.0.1:18100/v1')
    p.add_argument('--fixture', action='store_true')
    p.add_argument('--pause', choices=['safe_after_write', 'uncertain_after_write'])
    p.add_argument('--controller-ready', type=Path)
    p.add_argument('--receipt', type=Path)
    p.add_argument('--operation-id')
    p.add_argument('--deadline-monotonic',type=float)
    p.add_argument('--fixture-scenario',choices=['normal','wait-race','unknown-failure'],default='normal')
    a = p.parse_args()
    if a.mode == 'prepare':
        if not all((a.hermes_source, a.canonical, a.python)):
            p.error('prepare requires explicit source, canonical repository and existing SDK interpreter')
        prepare(a)
        return 0
    return worker(a)


if __name__ == '__main__':
    raise SystemExit(main())
