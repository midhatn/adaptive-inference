# SPDX-License-Identifier: Apache-2.0
"""Installed bounded Hermes task consumer; never controls a model service."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
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
from datetime import datetime, timezone
import uuid
import traceback
from adaptive_inference.execution_clock import CLOCK_ID, execution_now, verify_execution_clock

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


def prepared_contract(plan):
    """Resolve a new explicit specification, or the unchanged legacy report plan."""
    from adaptive_inference.task_spec import TaskSpec
    if 'task_spec' not in plan and 'task_spec_sha256' not in plan:
        if plan.get('task_id') != 'orders-report':
            raise ValueError('An explicit task specification is required')
        return None
    if 'task_spec' not in plan or 'task_spec_sha256' not in plan:
        raise ValueError('Incomplete prepared task specification')
    spec = TaskSpec(plan['task_spec'])
    if spec.sha256 != plan['task_spec_sha256']:
        raise ValueError('Prepared task specification changed')
    return spec


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setup(plan):
    from adaptive_inference.desktop.installation import package_identity, verify_sdk, verify_interpreter
    package_identity(plan['package_identity'])
    verify_interpreter(plan['base_python'], plan['python_sha256'], current=True)
    verify_sdk(plan['sdk'])
    site.addsitedir(plan['site_packages'])
    package_identity(plan['package_identity'])
    from adaptive_inference.desktop.hermes import recovery, report_contract as base
    base.configure_inputs(plan['sdk'], plan['python'], plan['gateway'], MODEL)
    return recovery, base


def prepare(args):
    from adaptive_inference.desktop.installation import package_identity, sha, verify_interpreter, verify_sdk
    from adaptive_inference.desktop.profile import WindowsProfile

    verify_execution_clock()
    run = args.run.resolve()
    if sha(args.profile) != args.profile_sha256:
        raise RuntimeError('Deployment profile changed before preparation')
    profile = WindowsProfile.load(args.profile)
    from adaptive_inference.task_spec import TaskSpec
    explicit = [getattr(args, key, None) for key in
                ('task_spec', 'task_spec_sha256', 'task_inputs', 'task_id', 'session_id')]
    if any(value is not None for value in explicit) and not all(explicit):
        raise ValueError('A new task requires its specification, input directory and fresh task/session identities')
    task_spec = None if not any(explicit) else TaskSpec.read(args.task_spec, args.task_spec_sha256)
    reserved_identity = None
    identity_path = getattr(args, 'demand_identity', None)
    identity_sha = getattr(args, 'demand_identity_sha256', None)
    if identity_path is not None or identity_sha is not None:
        from adaptive_inference.task_spec import strict_json
        from adaptive_inference.demand import DemandIdentity
        if task_spec is None or not identity_path or not identity_sha:
            raise ValueError('Reserved demand identity requires its file/hash and an explicit task specification')
        with Path(identity_path).open('rb') as stream:
            identity_raw = stream.read(4097)
        if len(identity_raw) > 4096 or hashlib.sha256(identity_raw).hexdigest() != identity_sha:
            raise ValueError('Reserved demand identity input changed')
        reserved_identity = strict_json(identity_raw)
        if type(reserved_identity) is not dict or set(reserved_identity) != {'registration_id', 'task_id', 'owner_id', 'arrived_at_utc'}:
            raise ValueError('Exact reserved demand identity fields required')
        DemandIdentity(**reserved_identity)
        if reserved_identity['task_id'] != args.task_id:
            raise ValueError('Reserved demand belongs to another task')
    if task_spec is not None:
        from adaptive_inference.task_store import _task_id
        _task_id(args.task_id); _task_id(args.session_id)
        if args.fixture or getattr(args, 'validate_report_before_write', False):
            raise ValueError('Legacy report fixture options cannot replace an explicit task contract')
        task_spec.verify_inputs(args.task_inputs)
    expected = json.loads(args.package_identity.read_text(encoding='utf-8'))
    installed = package_identity(expected)
    python = verify_interpreter(profile.worker_python, profile.worker_python_sha256, current=True)
    sdk = verify_sdk(profile.hermes_source)
    site_packages = profile.hermes_site_packages.resolve(strict=True)
    if not site_packages.is_dir():
        raise ValueError('Explicit installed Hermes dependency directory required')
    plan = {'sdk': str(sdk), 'sdk_revision': SDK_REV, 'python': str(python),
            'python_sha256': profile.worker_python_sha256, 'package_identity': installed,
            'base_python': str(python), 'site_packages': str(site_packages),
            'gateway': f'http://127.0.0.1:{profile.gateway.port}/v1', 'model': MODEL, 'quality': QUALITY, 'fixture': args.fixture,
            'task_id': 'orders-report', 'session_id': 'adaptive-restart-' + run.name, 'max_requests': 8,
            'fixture_scenario':args.fixture_scenario}
    if args.control_case not in ('complete','cancel'):
        raise ValueError('Explicit qualification control case is required')
    plan['control_case']=args.control_case
    if task_spec is not None:
        plan.update(task_id=args.task_id, session_id=args.session_id,
                    task_spec=task_spec.data, task_spec_sha256=task_spec.sha256)
    plan['demand_identity']={'registration_id':'qualification-'+uuid.uuid4().hex,
        'task_id':plan['task_id'],'owner_id':'qualified-hermes',
        'arrived_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
    if reserved_identity is not None: plan['demand_identity'] = reserved_identity
    if args.fixture_scenario!='normal' and not args.fixture:
        raise ValueError('Synthetic admission scenario requires fixture mode')
    rec, base = setup(plan)
    validator_identity=None
    if task_spec is not None:
        validator_identity = task_spec.validator_identity()
        plan['pre_effect_validator'] = validator_identity
    elif getattr(args,'validate_report_before_write',False):
        from adaptive_inference.desktop.hermes.report_validator import identity as report_identity
        validator_identity=report_identity(base.REPORT)
        plan['pre_effect_validator']=validator_identity
    if base.git('rev-parse', 'HEAD') != SDK_REV or base.git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Installed SDK identity changed')
    run.mkdir(parents=True, exist_ok=False)
    work = run / 'work'; work.mkdir()
    if task_spec is None:
        (work / 'orders.csv').write_text(base.CSV, encoding='utf-8', newline='\n')
    else:
        task_spec.stage_inputs(args.task_inputs, work)
    (run / 'phase.txt').write_text('parent', encoding='utf-8')
    home = run / 'home'; home.mkdir()
    plugin = home / 'plugins/recovery-checkpoint'; plugin.mkdir(parents=True)
    (plugin / '__init__.py').write_text('from adaptive_inference.desktop.hermes.recovery import register\n', encoding='utf-8')
    (plugin / 'plugin.yaml').write_text("name: recovery-checkpoint\nversion: '0.1.0'\ndescription: Explicit owned restart checkpoint.\n", encoding='utf-8')
    plan['deadline_clock'] = CLOCK_ID
    config = base.config(work)
    config['plugins'] = {'enabled': ['recovery-checkpoint']}
    rec.save(home / 'config.yaml', config)
    from adaptive_inference.task_store import TaskStore
    from adaptive_inference.demand import DemandIdentity
    from adaptive_inference.desktop.hermes.control_bridge import prepare_task
    metadata={'sdk_revision':SDK_REV,'model':MODEL,'quality':QUALITY,'deadline_clock':CLOCK_ID}
    if task_spec is not None: metadata.update(task_spec.metadata())
    if validator_identity is not None:metadata['pre_effect_validator']=validator_identity
    prepare_task(TaskStore(run/'task.sqlite3'),DemandIdentity(**plan['demand_identity']),
        PROMPT if task_spec is None else task_spec.prompt,
        plan['session_id'],metadata=metadata,max_attempts=8)
    # Installed source files are verified by shared wheel-relative pins;
    # mutable task inputs retain the original explicit file pins.
    inputs = ['orders.csv'] if task_spec is None else [row['name'] for row in task_spec.data['inputs']]
    pins = [home / 'config.yaml', plugin / '__init__.py', plugin / 'plugin.yaml', *(work / name for name in inputs)]
    plan['pins'] = {str(p): rec.digest(p.read_bytes()) for p in pins}
    rec.save(run / 'plan.json', plan)
    print(json.dumps({'prepared': True, 'model_started': False, 'fixture': args.fixture}))


def qualification_report_resumed(mailbox, owned):
    """Observe the exact report Pause followed by the latest applied Resume.

    Qualification-only caller; this is not an admission reservation. Reuse the
    existing owner check and coherent, validated mailbox snapshot. A later
    command still belongs to the existing cooperative operation safe points.
    """
    from adaptive_inference.control_mailbox import ControlBlocked

    current = mailbox._owned_snapshot(owned)
    snapshot = mailbox.snapshot()
    target = snapshot.target
    if target != current or target != owned.checkpoint:
        raise ControlBlocked('Report hold checkpoint differs from its retained owner')
    if (target.owner_epoch is None or target.state['status'] != 'pending'
            or target.operation is not None or target.requires_reconciliation
            or target.state.get('phase') != 'ready'
            or target.state.get('pending_request') is not None
            or snapshot.demand is None or snapshot.demand['state'] != 'waiting'):
        return False
    pause = next((row for row in snapshot.requests
                  if row['request_id'] == 'pause-after-safe'), None)
    if pause is None or pause['command'] != 'pause':
        return False
    latest = snapshot.requests[-1]
    if latest['command'] != 'resume' or latest['sequence'] <= pause['sequence']:
        return False
    # status() derives acknowledgement only from the validated ordered prefix;
    # a recorded request alone, including a later Pause/Cancel, cannot release.
    return all(snapshot.status(row['request_id'])['outcome'] == 'applied'
               and snapshot.status(row['request_id'])['owner_acknowledged'] is True
               for row in (pause, latest))


def worker(args):
    grant_path = getattr(args, 'continuation_grant', None)
    if grant_path is None:
        return _worker(args)
    if args.mode != 'worker' or getattr(args, 'host_generation', None) is None:
        raise ValueError('Selected execution requires worker mode and exact host generation')
    from adaptive_inference.desktop.hermes.continuation_worker import read_json, selected_worker
    grant = read_json(grant_path)
    with selected_worker(args.run, grant, host_generation=args.host_generation,
                         deadline=args.deadline_monotonic, clock=execution_now) as selected:
        code = _worker(args, selected=selected)
        selected.finish(code)
        return code


def _worker(args, *, selected=None):
    run = args.run.resolve(strict=True)
    plan = json.loads((run / 'plan.json').read_text(encoding='utf-8'))
    task_spec = prepared_contract(plan)
    if (plan.get('sdk_revision') != SDK_REV or plan.get('model') != MODEL
            or plan.get('quality') != QUALITY or type(plan.get('fixture')) is not bool
            or plan.get('max_requests') != 8):
        raise ValueError('Prepared source/quality/request contract differs')
    # Verify with stdlib before importing the pinned adapter/helper or loading
    # dependency .pth files. A rejected changed consumer must never execute.
    for path, expected in plan['pins'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Pinned integration input changed before import')
    # Reject a sealed execution before SDK import or a new target claim.
    from adaptive_inference.task_store import TaskStore, ReconciliationRequired
    from adaptive_inference.control_mailbox import execution_outcome
    store = TaskStore(run / 'task.sqlite3')
    startup_checkpoint = store.load(plan['task_id']) if selected is None else selected.owned.checkpoint
    if execution_outcome(startup_checkpoint.state) is not None:
        raise ReconciliationRequired('This execution budget is sealed')
    if selected is not None:
        plan = selected.exact_plan()
    diagnostics = run if selected is None else selected.diagnostics
    verify_execution_clock()
    if (plan.get('deadline_clock') != CLOCK_ID
            or startup_checkpoint.metadata.get('deadline_clock') != CLOCK_ID
            or startup_checkpoint.state.get('deadline_clock') != CLOCK_ID):
        raise ReconciliationRequired('Installed task has no recognized original execution clock')
    for key in list(os.environ):
        if key.startswith(('HERMES_', 'OPENAI_', 'ANTHROPIC_', 'STRATA_')) or key in ('PYTHONPATH', 'PYTHONHOME'):
            os.environ.pop(key, None)
    os.environ.update(HERMES_HOME=str(run / 'home'), HERMES_BUNDLED_PLUGINS=str(run / 'empty-bundled'),
                      PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
    rec, base = setup(plan)
    from adaptive_inference.desktop.hermes import admission
    if base.git('rev-parse', 'HEAD') != SDK_REV or base.git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Installed SDK changed')
    sys.path.insert(0, plan['sdk'])
    import httpx
    from adaptive_inference.task_store import TaskStore, ReconciliationRequired
    from adaptive_inference.demand import DemandIdentity,DemandRegistry,Registration,NAMESPACE
    from adaptive_inference.control_mailbox import Mailbox,ACKS
    from adaptive_inference.desktop.hermes.control_bridge import Controls
    from adaptive_inference.desktop.hermes.service_stop import (
        StopAtPause, ProductStop, STOP_EXIT, PAUSED_EXPIRY_EXIT, finalize_paused_expiry)
    from hermes_state import SessionDB
    from adaptive_inference.desktop.installation import verify_sdk_imports
    verify_sdk_imports(plan['sdk'])
    result = {'passed': False, 'fixture': plan['fixture'], 'sdk_revision': SDK_REV,
              'model': MODEL, 'quality': QUALITY, 'mode': args.mode}
    if selected is not None:
        result['selected_execution'] = {'logical_task_id': selected.original['task_id'],
            'execution_id': selected.execution_id, 'execution_generation': selected.execution_generation}
    db = agent = provider = None
    controller = None
    pending_expiry = None
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
            if scenario=='report-feedback' and tools:
                response=super().fake_response(req,'parent',1)
                payload=response.json();call=payload['choices'][0]['message']['tool_calls'][0]
                rejected=any('proposal_validation_failed' in str(row.get('content','')) for row in tools)
                if rejected:
                    call['id']+='-corrected'
                else:
                    arguments=json.loads(call['function']['arguments'])
                    draft=json.loads(arguments['content']);draft.update(units=19,total_cents=4800)
                    arguments['content']=json.dumps(draft);call['function']['arguments']=json.dumps(arguments)
                return httpx.Response(200,request=req,headers=response.headers,json=payload)
            return super().fake_response(req, 'parent', 1 if tools else 0)

    boundary = Boundary(run, plan['fixture'])
    if selected is not None or (run / 'wire-observations.json').exists():
        boundary.rows = (selected.load_wire() if selected is not None else
                         json.loads((run / 'wire-observations.json').read_text()))
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
    @contextmanager
    def paused_expiry_boundary(owned):
        nonlocal agent, db, provider, pending_expiry
        try:
            yield
        except rec.ControlStop as exc:
            if (exc.control_state != 'paused' or exc.reason != 'control_wait_deadline'
                    or controller is None):
                raise
            proof = finalize_paused_expiry(controller, agent=agent, db=db,
                provider=provider, session_db_factory=SessionDB)
            # The exact objects were successfully closed while owned. Outer
            # finally must not close them again after sealing the checkpoint.
            agent = db = provider = None
            pending_expiry = proof  # Provisional until claim exit and final restoration.
            if selected is not None:
                from adaptive_inference.desktop.hermes.continuation_worker import effect_receipts
                selected.note_cleanup({'resources_closed': True, 'state_sha256': proof['state_sha256'],
                    'native_history_sha256': proof['native_history_sha256'],
                    'effect_receipts_sha256': effect_receipts(selected.owned, run)})
        finally:
            if controller is not None and controller.controls.wait_activity is not None:
                controller.controls.wait_activity.revoke()
    try:
        cp = startup_checkpoint
        identity=DemandIdentity(**plan['demand_identity'])
        validator_identity=plan.get('pre_effect_validator')
        pre_effect_validator=None
        expected_metadata={'sdk_revision':SDK_REV,'model':MODEL,'quality':QUALITY,NAMESPACE:identity.metadata(),
                           'deadline_clock':CLOCK_ID}
        if task_spec is not None:
            expected_metadata.update(task_spec.metadata())
            if validator_identity != task_spec.validator_identity():
                raise ReconciliationRequired('Prepared task validator identity changed')
            expected_metadata['pre_effect_validator'] = validator_identity
            pre_effect_validator = task_spec.validate_write
        elif validator_identity is not None:
            from adaptive_inference.desktop.hermes.report_validator import identity as report_identity,validator as report_validator
            if validator_identity!=report_identity(base.REPORT):
                raise ReconciliationRequired('Prepared report validator source or oracle changed')
            expected_metadata['pre_effect_validator']=validator_identity
            pre_effect_validator=report_validator(base.REPORT)
        if selected is not None:
            from adaptive_inference.desktop.hermes.continuation import LINK
            expected_metadata[LINK] = selected.owned.checkpoint.metadata[LINK]
        original_prompt = PROMPT if task_spec is None else task_spec.prompt
        if (cp.prompt != original_prompt or cp.max_attempts != 8 or cp.metadata != expected_metadata):
            raise ReconciliationRequired('Original task identity differs from the prepared contract')
        claim = store.claim(plan['task_id'], expected_revision=cp.revision) if selected is None else nullcontext(selected.owned)
        with claim as owned, paused_expiry_boundary(owned):
            result['owner_epoch']=owned.checkpoint.owner_epoch
            if args.mode=='worker':
                deadline=args.deadline_monotonic
                if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                        or not 0 < deadline-execution_now() <= 900):
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
                history = (rec.resumable(owned, db, run / 'work') if selected is None else selected.verify_native(db))
                if owned.checkpoint.state['status'] == 'accepted':
                    result.update(passed=True, terminal_noop=True, provider_calls=0)
                else:
                    registry=DemandRegistry((Registration(store,identity),))
                    mailbox=Mailbox(registry,identity.registration_id,requester_capability=object())
                    controls=Controls(mailbox,deadline=deadline,
                        deadline_clock=CLOCK_ID,
                        utc_now=lambda:datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
                    controller=rec.Recovery(owned,db,run/'work',run,controls=controls,
                        pre_effect_validator=pre_effect_validator,validator_identity=validator_identity)
                    from adaptive_inference.desktop.hermes.pause_activity import PauseActivity
                    def sdk_thread_interrupted():
                        from tools.interrupt import is_interrupted
                        return is_interrupted()
                    controls.wait_activity = PauseActivity(controller,thread_interrupted=sdk_thread_interrupted)
                    if args.stop_request_id is not None:
                        controls.safe_boundary=StopAtPause(controller,args.stop_request_id)
                    # Publish durable demand before waiting for the parent host.
                    # This may intentionally block in prequeued pause or exit cancelled.
                    controller.bootstrap_controls()
                    demand=registry.observe(identity.registration_id)
                    rec.save(diagnostics/f'bootstrap-{os.getpid()}.json',{'pid':os.getpid(),
                        'task_id':identity.task_id,'registration_id':identity.registration_id,
                        'revision':owned.checkpoint.revision,'owner_epoch':owned.checkpoint.owner_epoch,
                        'deadline_monotonic':deadline,'deadline_clock':CLOCK_ID,
                        'demand':{'state':demand.state,'eligible':demand.eligible}})
                    # Root/controller owns readiness. Never construct an agent while parked;
                    # metadata discovery uses GET and is not an admitted model generation.
                    if not args.controller_ready or not args.gateway_instance:
                        raise ValueError('Explicit owned gateway instance and readiness receipt required')
                    if selected is not None:
                        selected.ready_path(args.controller_ready)
                    while not args.controller_ready.exists():
                        controller.control_safe_point()
                        if execution_now()>=deadline:raise rec.RecoveryStop('Bootstrap readiness deadline')
                        time.sleep(.05)
                    controller.control_safe_point()
                    ready = (json.loads(args.controller_ready.read_text(encoding='utf-8')) if selected is None
                             else selected.read_ready(args.controller_ready))
                    if (ready.get('ready') is not True or ready.get('model') != MODEL
                            or ready.get('quality') != QUALITY or ready.get('gateway') != plan['gateway']
                            or ready.get('gateway_instance')!=args.gateway_instance
                            or not 0 <= time.time() - ready.get('observed_at', 0) <= 30):
                        raise ValueError('Controller readiness receipt is stale or differs')
                    instance=ready.get('gateway_instance')
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
                            boundary=boundary,deadline=deadline,clock=execution_now)
                    boundary.provider=provider
                    controller.provider=provider
                    original_barrier=controller.barrier
                    def controlled_safe_hold(label):
                        if label!='safe_after_write':return original_barrier(label)
                        def resumed():
                            if args.qualification_hold_after_report:
                                return qualification_report_resumed(mailbox, owned)
                            return any(r['request_id']=='resume-after-safe' and r['outcome']=='applied'
                                for r in owned.checkpoint.state.get(ACKS,{}).get('receipts',[]))
                        if resumed():return
                        rec.resumable(owned,db,run/'work')
                        rec.save(diagnostics/'pause.json',{'boundary':label,'pid':os.getpid(),
                            'revision':owned.checkpoint.revision,
                            'history_sha256':rec.digest(owned.checkpoint.state['native_history'])})
                        while not resumed():
                            controller.control_safe_point()
                            if execution_now()>=deadline:raise rec.RecoveryStop('Controlled safe-point hold deadline')
                            time.sleep(.05)
                    if task_spec is None and (args.stop_request_id is None or args.qualification_hold_after_report):
                        controller.barrier=controlled_safe_hold
                    rec.ACTIVE = controller
                    from run_agent import AIAgent
                    verify_sdk_imports(plan['sdk'])
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
                    task_identity = {} if task_spec is None else {'task_id': cp.metadata.get(
                        'adaptive_inference.execution_authorization.v1', {}).get('logical_task_id', cp.task_id)}
                    outcome = agent.run_conversation(CONTINUE if history else original_prompt,
                                                     conversation_history=history or None, **task_identity)
                    if task_spec is None:
                        report = json.loads((run / 'work/report.json').read_text(encoding='utf-8'))
                        if report != base.REPORT:
                            raise rec.RecoveryStop('Original artifact acceptance failed')
                        completion = {'artifacts': {'report.json': rec.digest((run / 'work/report.json').read_bytes())},
                                      'report': report}
                    else:
                        completion = task_spec.completion(run / 'work', owned.checkpoint.state['tools'],
                                                          outcome.get('final_response', ''))
                        completion['task_spec_sha256'] = task_spec.sha256
                    controls.wait_activity.finish_turn(outcome)
                    controller.finish(outcome)
                    result.update(passed=True, provider_calls=len(boundary.rows) - before,
                        resumed=bool(history), original_prompt_sha256=rec.digest(original_prompt),
                        transcript_rows=len(owned.checkpoint.state['native_history']),
                        transcript_sha256=rec.digest(owned.checkpoint.state['native_history']),
                        **completion, completed=outcome.get('completed'),
                        admission_attempts=owned.checkpoint.state.get('admission_attempts',0),
                        admission_deferrals=len(owned.checkpoint.state.get('admission_deferrals',[])),
                        fixture_admission_clock_s=clock.now if clock else None)
    except BaseException as exc:
        pending_expiry = None
        result.update(error_type=type(exc).__name__, error=str(exc), provider_calls=len(boundary.rows)-starting_requests)
        chain=[];details=[];seen=set();cause=exc
        while cause is not None and id(cause) not in seen and len(chain)<8:
            seen.add(id(cause));chain.append(type(cause).__name__)
            detail={'type':type(cause).__name__,'message':str(cause)}
            for key in ('sqlite_errorcode','sqlite_errorname','winerror','errno'):
                value=getattr(cause,key,None)
                if type(value) in (int,str):detail[key]=value
            details.append(detail)
            cause=getattr(cause,'original',None) or cause.__cause__ or cause.__context__
        result['error_chain_types']=chain
        result['error_chain_private']=details
        result['traceback_private']=''.join(traceback.format_exception(exc))
        if isinstance(exc,rec.ControlStop):
            result.update(controlled=True,control_state=exc.control_state,control_reason=exc.reason,
                          completed=False)
        if isinstance(exc,ProductStop):
            result.update(service_stopped=True,service_stop=exc.receipt)
    finally:
        cleanup_errors = []
        activity = None if controller is None else controller.controls.wait_activity
        try:
            # Revoke late callbacks on every exit, including SDK abandonment.
            # A busy logical owner is a cleanup failure, never concurrent close.
            with activity.cleanup_scope(agent,verify=False) if activity is not None else nullcontext():
                if selected is not None and db is not None and controller is not None:
                    from adaptive_inference.desktop.hermes.service_stop import close_safe_resources
                    selected.verify_native(db)
                    proof = close_safe_resources(controller, agent=agent, db=db, provider=provider,
                                                 session_db_factory=SessionDB)
                    from adaptive_inference.desktop.hermes.continuation_worker import effect_receipts
                    effect_receipt_sha = effect_receipts(selected.owned, run)
                    selected.note_cleanup({**proof, 'effect_receipts_sha256': effect_receipt_sha})
                    agent = db = provider = None
                else:
                    for name, resource in (('agent', agent), ('database', db), ('provider', provider)):
                        if resource is not None:
                            try:
                                resource.close()
                            except BaseException as cleanup_error:
                                cleanup_errors.append({'resource': name,
                                    'type': type(cleanup_error).__name__, 'message': str(cleanup_error)})
        except BaseException as cleanup_error:
            cleanup_errors.append({'resource':'recovery_serialization',
                'type':type(cleanup_error).__name__,'message':str(cleanup_error)})
        httpx.Client.send = original_send
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_ex
        socket.socketpair, socket.getaddrinfo = original_pair, original_dns
        if cleanup_errors:
            pending_expiry = None
            result.update(passed=False, completed=False, cleanup_errors=cleanup_errors)
            result.pop('service_stopped', None)
        if pending_expiry is not None:
            result.update(passed=False, controlled=True, completed=False,
                control_state='paused', control_reason='paused_budget_expired',
                paused_expiry=pending_expiry, provider_calls=len(boundary.rows)-starting_requests)
        if selected is not None:
            result['continuation_cleanup_verified'] = selected.cleanup_proof is not None and not cleanup_errors
        rec.save(diagnostics / f'result-{os.getpid()}.json', result)
    return (2 if result.get('cleanup_errors') else 0 if result['passed'] else STOP_EXIT if result.get('service_stopped') is True
            else PAUSED_EXPIRY_EXIT if result.get('paused_expiry') is not None
            else 3 if result.get('control_state')=='cancelled' else 2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['prepare', 'worker', 'reconcile'])
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--profile', type=Path)
    p.add_argument('--profile-sha256')
    p.add_argument('--package-identity', type=Path)
    p.add_argument('--task-spec', type=Path)
    p.add_argument('--task-spec-sha256')
    p.add_argument('--task-inputs', type=Path)
    p.add_argument('--task-id')
    p.add_argument('--session-id')
    p.add_argument('--demand-identity', type=Path)
    p.add_argument('--demand-identity-sha256')
    p.add_argument('--fixture', action='store_true')
    p.add_argument('--pause', choices=['safe_after_write', 'uncertain_after_write'])
    p.add_argument('--controller-ready', type=Path)
    p.add_argument('--receipt', type=Path)
    p.add_argument('--operation-id')
    p.add_argument('--deadline-monotonic',type=float)
    p.add_argument('--gateway-instance')
    p.add_argument('--stop-request-id')
    p.add_argument('--qualification-hold-after-report',action='store_true')
    p.add_argument('--continuation-grant', type=Path)
    p.add_argument('--host-generation')
    p.add_argument('--validate-report-before-write',action='store_true')
    p.add_argument('--control-case',choices=['complete','cancel'])
    p.add_argument('--fixture-scenario',choices=['normal','wait-race','unknown-failure','report-feedback'],default='normal')
    a = p.parse_args()
    if a.mode == 'prepare':
        if not all((a.profile, a.profile_sha256, a.package_identity)):
            p.error('prepare requires explicit profile, its SHA-256 and installed package identity')
        prepare(a)
        return 0
    return worker(a)


if __name__ == '__main__':
    raise SystemExit(main())
