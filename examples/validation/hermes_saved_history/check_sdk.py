# SPDX-License-Identifier: Apache-2.0
"""Pinned SDK saved-history rebuild component; no full agent/model/OS join claim."""
from contextlib import ExitStack
from copy import deepcopy
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

parser=argparse.ArgumentParser()
parser.add_argument('--profile',type=Path,required=True)
parser.add_argument('--source-root',type=Path,required=True)
parser.add_argument('--source-manifest',type=Path,default=Path(__file__).resolve().parent/'source-manifest.json')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parent
SOURCE=args.source_root.resolve(strict=True)
OUT=args.output.resolve();OUT.mkdir(parents=False,exist_ok=False)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
manifest=json.loads(args.source_manifest.read_text())
source_pins=manifest['files']
if manifest.get('schema')!='adaptive.validation.hermes-saved-history.sources.v1':
    raise RuntimeError('Unknown source manifest')
expected_runtime={p for p in source_pins if p.startswith('src/adaptive_inference/')}
actual_runtime={p.relative_to(SOURCE).as_posix() for p in (SOURCE/'src/adaptive_inference').rglob('*.py')}
if actual_runtime!=expected_runtime or len(expected_runtime)!=60:
    raise RuntimeError('Runtime source closure differs')
for relative,expected in source_pins.items():
    path=(SOURCE/relative).resolve(strict=True)
    if Path(relative).is_absolute() or not path.is_relative_to(SOURCE) or sha(path)!=expected:
        raise RuntimeError('Source/support identity changed: '+relative)
sys.path[:0]=[str(SOURCE/'src'),str(SOURCE/'tests')]
from adaptive_inference.desktop.profile import WindowsProfile
from adaptive_inference.desktop.installation import verify_sdk,verify_sdk_imports,verify_interpreter
from adaptive_inference.desktop.hermes import recovery as rec,run_recovery,report_contract,admission
from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES,SDK_REV
from adaptive_inference.task_store import TaskStore
from test_desktop_report_feedback import NativeDB
profile=WindowsProfile.load(args.profile)
verify_interpreter(profile.worker_python,profile.worker_python_sha256,current=True)
SDK=profile.hermes_source.resolve(strict=True)
verify_sdk(SDK)
if manifest['sdk_revision']!=SDK_REV:
    raise RuntimeError('SDK revision contract differs')
for relative,expected in manifest['sdk_files'].items():
    path=(SDK/relative).resolve(strict=True)
    if Path(relative).is_absolute() or not path.is_relative_to(SDK) or sha(path)!=expected:
        raise RuntimeError('SDK fixture/support identity changed: '+relative)
for key in list(os.environ):
    if key.startswith(('HERMES_','OPENAI_','ANTHROPIC_','STRATA_')) or key in ('PYTHONPATH','PYTHONHOME'):
        os.environ.pop(key,None)
os.environ.update(HERMES_HOME=str(OUT/'hermes-home'),HERMES_BUNDLED_PLUGINS=str(OUT/'empty-bundled'),
    LITELLM_LOCAL_MODEL_COST_MAP='True',PYTHONDONTWRITEBYTECODE='1')
(OUT/'hermes-home').mkdir()
rec.save(OUT/'hermes-home/config.yaml',report_contract.config(OUT/'work'))
sys.path[:0]=[str(SDK),str(profile.hermes_site_packages)]
sources=[Path(__file__),ROOT/'README.md',args.profile,args.source_manifest,
    *(SOURCE/p for p in source_pins),
    *(SDK/p for p in SDK_FILES),
    *(SDK/p for p in ('agent/turn_context.py','agent/turn_facade.py','agent/conversation_loop.py',
        'agent/turn_api_call.py','agent/transports/chat_completions.py','hermes_cli/middleware.py',
        'tests/agent/test_turn_context.py','LICENSE'))]
def pins():return {str(p.resolve()):sha(p) for p in sources}
before=pins()
def forbidden(*a,**kw):raise AssertionError('No network/process execution is permitted in this SDK component fixture')
def no_process(*a,**kw):raise OSError('Offline fixture refuses all child launches, including optional SDK git metadata')

with ExitStack() as isolation:
    isolation.enter_context(mock.patch.object(socket.socket,'connect',side_effect=forbidden))
    isolation.enter_context(mock.patch.object(socket.socket,'connect_ex',side_effect=forbidden))
    isolation.enter_context(mock.patch.object(subprocess,'Popen',side_effect=no_process))
    from agent import turn_context
    from agent.transports import get_transport
    import agent.transports.chat_completions as transport_module
    from hermes_cli import middleware,plugins
    fixture_spec=importlib.util.spec_from_file_location('pinned_turn_context_fixture',SDK/'tests/agent/test_turn_context.py')
    fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)
    verify_sdk_imports(SDK)
    for module in (turn_context,transport_module,middleware):
        if Path(module.__file__).resolve()!=SDK/Path(module.__name__.replace('.','/')).with_suffix('.py'):
            raise RuntimeError('SDK import origin differs')
    if Path(rec.__file__).resolve()!=SOURCE/'src/adaptive_inference/desktop/hermes/recovery.py':
        raise RuntimeError('Source Recovery origin differs')

    class RebuildTests(unittest.TestCase):
        def setUp(self):
            self.run=OUT/self._testMethodName;self.run.mkdir();self.work=self.run/'work';self.work.mkdir()
            self.session='saved-'+rec.digest(self._testMethodName)[:20]
            (self.work/'orders.csv').write_text(report_contract.CSV,encoding='utf-8')
            self.db=NativeDB(self.run/'native.sqlite3');self.addCleanup(self.db.close)
            self.db.append({'role':'user','content':run_recovery.PROMPT})
            self.store=TaskStore(self.run/'task.sqlite3')
            state=rec.initial_state(run_recovery.PROMPT,self.session)
            state['native_history']=rec.native_history(self.db,self.session)
            cp=self.store.create('logical-task',run_recovery.PROMPT,max_attempts=8,state=state,
                metadata={'model':run_recovery.MODEL,'quality':run_recovery.QUALITY})
            self.claim=self.store.claim(cp.task_id,expected_revision=cp.revision)
            self.owned=self.claim.__enter__();self.addCleanup(self.claim.__exit__,None,None,None)
            self.controller=rec.Recovery(self.owned,self.db,self.work,self.run,
                controls=SimpleNamespace(poll=lambda owned:None))
            arguments={'path':'orders.csv'}
            self.db.append({'role':'assistant','content':None,'tool_calls':[{'id':'original-read',
                'type':'function','function':{'name':'read_file','arguments':json.dumps(arguments)}}]})
            result=self.controller.tool('read_file',arguments,
                lambda value:json.dumps({'content':(self.work/value['path']).read_text(encoding='utf-8')}),
                session_id=self.session,tool_call_id='original-read')
            self.assertNotIn('error',json.loads(result))
            self.db.append({'role':'tool','tool_call_id':'original-read','content':result})
            self.controller.control_safe_point()
            state=deepcopy(self.owned.checkpoint.state)
            # Declared historical completed request seed, not a fabricated actual provider run.
            state.update(requests=1,attempts=1,admission_attempts=1)
            self.owned.save_checkpoint(state,expected_revision=self.owned.checkpoint.revision)
            self.history=deepcopy(state['native_history']);self.history_sha=rec.digest(self.history)
            self.transport=get_transport('chat_completions')
            self.tools=[{'type':'function','function':{'name':name,'description':'bounded fixture file tool',
                'parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}
                for name in ('read_file','write_file')]
            self.old_pending=self.build(self.history)
            rec.save(self.run/'predecessor-pending.private.json',self.old_pending)
            self.old_raw=(self.run/'predecessor-pending.private.json').read_bytes()
            self.dispatched=[]

        def build(self,messages):
            return self.transport.build_kwargs(model=run_recovery.MODEL,messages=deepcopy(messages),
                tools=deepcopy(self.tools),base_url='http://127.0.0.1:18100/v1',timeout=1800,
                max_tokens=10923,max_tokens_param_fn=lambda count:{'max_tokens':count},
                reasoning_config={'enabled':True,'effort':'high'},provider_name='custom:adaptive',
                request_overrides={'extra_body':deepcopy(run_recovery.QUALITY)})

        def reconstructed(self):
            agent=fixture._FakeAgent()
            agent.session_id=self.session;agent.model=run_recovery.MODEL
            agent.provider=agent.requested_provider='custom:adaptive'
            agent.base_url='http://127.0.0.1:18100/v1'
            agent.max_tokens=10923;agent._skip_mcp_refresh=True
            def persist(messages,history):
                self.assertEqual(history,self.history)
                self.assertEqual(messages[:len(history)],history)
                for row in messages[len(history):]:self.db.append(deepcopy(row))
            agent._persist_session=persist
            with mock.patch('agent.auxiliary_client.set_runtime_main',lambda *a,**kw:None):
                context=fixture._build(agent,user_message=run_recovery.CONTINUE,
                    conversation_history=deepcopy(self.history),task_id='logical-task')
            self.assertEqual(context.messages[:len(self.history)],self.history)
            self.assertEqual(len(context.messages),len(self.history)+1)
            self.assertEqual(context.messages[-1]['role'],'user')
            self.assertEqual(context.messages[-1]['content'],run_recovery.CONTINUE)
            self.assertEqual(rec.digest(self.history),self.history_sha)
            self.assertEqual(rec.native_history(self.db,self.session),context.messages)
            return self.build(context.messages)

        def dispatch(self,request):
            outer=self
            class Provider(admission.Provider):
                def __init__(self):
                    self.model=run_recovery.MODEL;self.instance='a'*32;self.deadline=900
                    self.clock=lambda:1.;self.sleep=lambda duration:None
                    self.current_attempt=self.body_sha256=None
                    self.status_reader=lambda:{'service':'adaptive-inference','instance':self.instance,
                        'scheduler':{'active':False,'pending':0,'closing':False,'backend_completion_uncertain':False},
                        'resources':{'admission_allowed':True}}
                    def capture(**value):
                        outer.dispatched.append(deepcopy(value))
                        return 'scripted transport response to NEW request; no model'
                    self.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
            self.controller.provider=Provider()
            manager=SimpleNamespace(_middleware={'llm_execution':[self.controller.llm]},
                _report_hook_failure=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Middleware must not fail open')))
            with mock.patch.object(plugins,'_delivery_manager',return_value=manager):
                return middleware.run_llm_execution_middleware(request,forbidden,
                    original_request=deepcopy(request),session_id=self.session,task_id='logical-task')

        def test_actual_sdk_rebuild_preserves_history_and_dispatches_new_request(self):
            request=self.reconstructed()
            self.assertNotEqual(rec.digest(request),rec.digest(self.old_pending))
            self.assertEqual(request['model'],run_recovery.MODEL)
            self.assertEqual(request['extra_body'],run_recovery.QUALITY)
            self.assertEqual(request['max_tokens'],10923)
            self.assertEqual([t['function']['name'] for t in request['tools']],['read_file','write_file'])
            self.assertEqual(self.dispatch(request),'scripted transport response to NEW request; no model')
            self.assertEqual(len(self.dispatched),1)
            sent=deepcopy(self.dispatched[0]);sent.pop('extra_headers')
            self.assertEqual(sent,request)
            state=self.owned.checkpoint.state
            self.assertEqual((state['requests'],state['attempts'],state['admission_attempts']),(2,2,2))
            self.assertEqual(state['phase'],'awaiting_native_flush')
            self.assertIsNone(state['pending_request']);self.assertIsNone(self.owned.checkpoint.operation)
            self.assertEqual(len(state['tools']),1)
            self.assertEqual(state['native_history'][:len(self.history)],self.history)
            self.assertEqual((self.run/'predecessor-pending.private.json').read_bytes(),self.old_raw)
            self.assertFalse((self.work/'report.json').exists())
            self.assertFalse((self.run/'effect-receipts.jsonl').exists())
            rec.save(self.run/'projection.private.json',{'old_pending_sha256':rec.digest(self.old_pending),
                'new_request_sha256':rec.digest(request),'history_prefix_sha256':self.history_sha,
                'new_user_turns':1,'captured_fixture_dispatches':1,'requests_before':1,'requests_after':2,
                'task_completed':False,'full_agent_loop':False})

        def test_changed_native_prefix_refuses_before_scripted_transport(self):
            request=self.reconstructed()
            self.db.connection.execute('DELETE FROM messages WHERE n=(SELECT MIN(n) FROM messages)')
            self.db.connection.commit()
            with self.assertRaises(rec.RecoveryStop):self.dispatch(request)
            self.assertEqual(self.dispatched,[])
            self.assertEqual(self.owned.checkpoint.state['requests'],1)
            self.assertEqual((self.run/'predecessor-pending.private.json').read_bytes(),self.old_raw)

    started=time.monotonic()
    with (OUT/'tests.private.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RebuildTests))
    verify_sdk_imports(SDK)
    verify_sdk(SDK)
after=pins()
receipt={'schema':'adaptive.validation.hermes-saved-history.v1','passed':result.wasSuccessful() and before==after,
    'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
    'elapsed_s':time.monotonic()-started,'source_before':before,'source_after':after,'source_unchanged':before==after,
    'executable':sys.executable,'executable_sha256':sha(sys.executable),'python':sys.version,
    'mode':'source','source_manifest_sha256':sha(args.source_manifest),
    'runtime_source_sha256':{k.removeprefix('src/adaptive_inference/'):v for k,v in source_pins.items()
                             if k.startswith('src/adaptive_inference/')},
    'sdk_revision':SDK_REV,'sdk_pins':dict(SDK_FILES),
    'scope':'Actual pinned SDK turn prologue/transport builder/LLM middleware and source Recovery/Provider.execute with real SQLite; fake SDK agent projection and scripted terminal transport. No AIAgent/full-turn lease/model/native/GUI/installed/OS join acceptance.'}
rec.save(OUT/'tests.private.json',receipt)
print(json.dumps({k:receipt[k] for k in ('passed','tests','failures','errors','skips','source_unchanged')}))
raise SystemExit(0 if receipt['passed'] else 1)
