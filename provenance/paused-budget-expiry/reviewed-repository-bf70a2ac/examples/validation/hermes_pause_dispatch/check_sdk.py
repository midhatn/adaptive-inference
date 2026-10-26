# SPDX-License-Identifier: Apache-2.0
"""Actual pinned sequential runner/pool/context with production Recovery.tool.

Only the innermost SDK middleware hook is replaced, matching upstream's own
sequential-dispatch fixtures. It forwards to the actual Recovery/Controls guard.
No AIAgent construction, provider, socket, model, visible GUI or native launch.
"""
from pathlib import Path
import argparse,hashlib,importlib,json,os,sqlite3,sys,threading,time,unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--profile',type=Path,required=True)
parser.add_argument('--mode',choices=('source','installed'),required=True)
parser.add_argument('--installed-identity',type=Path)
options=parser.parse_args()
if (options.mode=='installed')!=(options.installed_identity is not None):
    parser.error('Installed mode requires --installed-identity; source mode does not accept it')
out=options.output;out.mkdir(exist_ok=False)
os.environ.update(HERMES_HOME=str(out/'home'),LITELLM_LOCAL_MODEL_COST_MAP='True',PYTHONDONTWRITEBYTECODE='1')
sys.path.insert(0,str(REPO/'tests'))
if options.mode=='source':sys.path.insert(0,str(REPO/'src'))
from adaptive_inference.desktop.profile import WindowsProfile
from adaptive_inference.desktop.installation import package_identity,verify_sdk,verify_sdk_imports,verify_interpreter
profile=WindowsProfile.load(options.profile)
verify_interpreter(profile.worker_python,profile.worker_python_sha256,current=True)
SDK=profile.hermes_source.resolve(strict=True)
references_path=REPO/'provenance/paused-budget-expiry/thread-successor/sdk-references.json'
references=json.loads(references_path.read_text(encoding='utf-8'))
verify_sdk(SDK)
for relative,expected in references['files'].items():
    if hashlib.sha256((SDK/relative).read_bytes()).hexdigest()!=expected:
        raise RuntimeError('Changed SDK dispatch reference: '+relative)
sys.path[:0]=[str(SDK),str(profile.hermes_site_packages)]
from adaptive_inference.desktop.hermes import pause_activity,control_bridge,service_stop,run_recovery,sdk_pins
if options.installed_identity is not None:
    identity=package_identity(json.loads(options.installed_identity.read_text()))
else:identity=None
from agent import tool_executor as te
from tools import daemon_pool,thread_context,interrupt
from adaptive_inference.desktop.hermes import recovery as rec
import test_desktop_pause_activity as fixture
runtime_root=Path(rec.__file__).resolve().parents[2]
if options.installed_identity is None:
    assert runtime_root==(REPO/'src/adaptive_inference').resolve()
else:
    assert runtime_root==(Path(sys.base_prefix)/'Lib/site-packages/adaptive_inference').resolve()
    assert str((REPO/'src').resolve()) not in sys.path
for module in (rec,pause_activity,control_bridge,service_stop,run_recovery,sdk_pins):
    assert Path(module.__file__).resolve()==runtime_root/'desktop/hermes'/Path(module.__file__).name
for module in (te,daemon_pool,thread_context,interrupt):
    assert Path(module.__file__).resolve()==SDK/Path(module.__name__.replace('.','/')).with_suffix('.py')
verify_sdk_imports(SDK)

class SDKDispatchSuccessor(unittest.TestCase):
    setUp=fixture.PauseActivityTests.setUp
    advance=fixture.PauseActivityTests.advance
    release=fixture.PauseActivityTests.release
    guard=fixture.PauseActivityTests.guard
    finalize=fixture.PauseActivityTests.finalize

    def configured(self):
        # Same durable projection fixture, explicitly opened for serialized
        # cross-thread access. No production SessionDB implementation is mocked.
        self.db.connection.close()
        self.db.connection=sqlite3.connect(self.db.db_path,check_same_thread=False)
        self.addCleanup(self.db.connection.close)
        self.controls.deadline=1000.
        guard=self.guard();guard.thread_interrupted=interrupt.is_interrupted;agent=self.agent
        self.controller._control_thread=None  # Require the real Recovery scope.
        agent._tool_worker_threads=set();agent._tool_worker_threads_lock=threading.Lock()
        self.box.submit(self.cap,'resume','resume');self.box.consume(self.owned,updated_at_utc=fixture.NOW)
        from adaptive_inference.desktop.hermes.report_contract import CSV,REPORT
        (self.work/'orders.csv').write_text(CSV,encoding='utf-8')
        self.report=REPORT;self.effects=[];self.seen=[];self.pools=[];self.futures=[]
        self.caller=threading.current_thread();self.dispatch_entered=None
        return guard

    def intent(self,name,args,call):
        self.db.append({'role':'assistant','content':None,'tool_calls':[{'id':call,'type':'function',
            'function':{'name':name,'arguments':json.dumps(args)}}]})

    def effect(self,args):
        self.effects.append(dict(args));path=self.work/args['path']
        if 'content' in args:
            path.write_text(args['content'],encoding='utf-8');return json.dumps({'verified':True})
        return json.dumps({'content':path.read_text(encoding='utf-8')})

    def middleware(self,agent_arg,**kw):
        self.assertIs(agent_arg,self.agent)
        self.seen.append({'different_thread':threading.current_thread() is not self.caller,
                         'registered_worker':threading.current_thread().ident in self.agent._tool_worker_threads})
        value=self.controller.tool(kw['function_name'],kw['function_args'],self.effect,
            session_id='native',tool_call_id=kw['tool_call_id'])
        return te._ManagedToolResult(result=value,args=kw['function_args'],middleware_trace=[],blocked=False,dispatched=True)

    def run_sdk(self,name,args,call,timeout=10.):
        original=daemon_pool.DaemonThreadPoolExecutor
        def retain(**kw):
            executor=original(**kw);self.pools.append(executor);submit=executor.submit
            def keep(*args,**kwargs):
                future=submit(*args,**kwargs);self.futures.append(future)
                # Reuse upstream's deterministic submit gate. The SDK computes
                # its deadline only after submit returns; this barrier reaches
                # our exact blocked safe point, including middleware preamble.
                if self.dispatch_entered is not None:
                    self.assertTrue(self.dispatch_entered.wait(5),'callback did not reach safe point')
                return future
            executor.submit=keep;return executor
        with mock.patch.object(te,'_run_agent_tool_execution_middleware',side_effect=self.middleware), \
             mock.patch.object(te,'_resolve_sequential_tool_timeout',return_value=timeout), \
             mock.patch.object(daemon_pool,'DaemonThreadPoolExecutor',side_effect=retain), \
             mock.patch.object(te,'_emit_terminal_post_tool_call'):
            return te._run_sequential_tool_execution_middleware(self.agent,function_name=name,function_args=args,
                effective_task_id='fixture',tool_call_id=call,execute=self.effect)

    def join_exact(self):
        for future in self.futures:
            try:future.result(timeout=5.)
            except rec.RecoveryStop:pass
        for pool in self.pools:
            for thread in pool._threads:
                thread.join(5.);self.assertFalse(thread.is_alive())
        self.assertFalse(self.agent._tool_worker_threads)
        self.assertIsNone(self.controller._control_thread)

    def test_real_sequential_sdk_handoff_reads_then_writes_exactly_once(self):
        guard=self.configured()
        for name,args,call in (('read_file',{'path':'orders.csv'},'read-1'),
            ('write_file',{'path':'report.json','content':json.dumps(self.report)},'write-1')):
            self.intent(name,args,call)
            managed=self.run_sdk(name,args,call)
            self.assertIsNone(self.controller._control_thread)
            self.db.append({'role':'tool','tool_call_id':call,'content':managed.result})
            self.controller.control_safe_point()
        self.join_exact()
        self.assertEqual(self.seen,[{'different_thread':True,'registered_worker':True}]*2)
        self.assertEqual(len(self.effects),2);self.assertEqual(guard.stamps,0)
        self.assertEqual(json.loads((self.work/'report.json').read_text()),self.report)
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()),1)
        self.assertEqual(len(self.owned.checkpoint.state['tools']),2)
        rec.verify_tool_rows(rec.native_history(self.db,'native'),self.owned.checkpoint.state['tools'])

    def blocked_timeout(self,*,try_cleanup):
        guard=self.configured();entered=threading.Event();release=threading.Event();signals=[]
        self.dispatch_entered=entered
        def blocked(*_):
            entered.set()
            if not release.wait(5):raise TimeoutError('fixture release missing')
            signals.append(interrupt.is_interrupted());return 2000
        self.db.session_turn_lease_expires_at.side_effect=blocked
        self.box.submit(self.cap,'pause','pause')
        args={'path':'orders.csv'};self.intent('read_file',args,'read-1')
        try:
            managed=self.run_sdk('read_file',args,'read-1',timeout=.2)
            self.assertTrue(entered.is_set());self.assertIsInstance(managed.result,te._ToolTimeoutResult)
            self.assertFalse(self.futures[0].done());self.assertFalse(self.agent._interrupt_requested)
            self.assertFalse(self.agent._turn_user_intervened)
            self.assertEqual(guard.stamps,0);self.assertEqual(self.effects,[])
            if try_cleanup:
                with self.assertRaisesRegex(rec.RecoveryStop,'still owns recovery'):self.finalize()
                with self.assertRaisesRegex(rec.RecoveryStop,'still owns recovery'):
                    with guard.cleanup_scope(self.agent,verify=False):self.agent.close()
                self.agent.close.assert_not_called();self.assertEqual(self.db.close_calls,0)
                from adaptive_inference.control_mailbox import EXECUTION_OUTCOME
                self.assertNotIn(EXECUTION_OUTCOME,self.owned.checkpoint.state)
        finally:
            release.set();self.join_exact()
        self.assertEqual(signals,[True]);self.assertEqual(guard.stamps,0)
        self.assertEqual(self.effects,[]);self.assertEqual(self.owned.checkpoint.state['tools'],[])
        with self.assertRaises(rec.RecoveryStop):guard.check_final(self.agent)
        self.assertIsNotNone(guard.fault)

    def test_actual_sdk_timeout_thread_signal_blocks_callback_without_agent_abort(self):
        self.blocked_timeout(try_cleanup=False)

    def test_actual_abandoned_callback_cannot_overlap_cleanup_or_seal(self):
        self.blocked_timeout(try_cleanup=True)

sources=[Path(__file__).resolve(),HERE/'README.md',options.profile.resolve(strict=True),references_path,
    *(SDK/n for n in references['files']),*runtime_root.rglob('*.py'),
    *(REPO/'tests'/n for n in ('test_desktop_pause_activity.py','test_desktop_paused_expiry.py','test_desktop_report_feedback.py'))]
def pins():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
before=pins();started=time.monotonic()
with (out/'tests.log').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SDKDispatchSuccessor))
after=pins();verify_sdk(SDK);verify_sdk_imports(SDK)
if options.installed_identity is not None:package_identity(identity)
receipt={'passed':result.wasSuccessful() and before==after,'tests':result.testsRun,
    'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
    'elapsed_s':time.monotonic()-started,'source_before':before,'source_after':after,'source_unchanged':before==after,
    'installed_mode':options.installed_identity is not None,'package_identity':identity,
    'python':sys.version,'executable':sys.executable,
    'scope':'Actual pinned SDK sequential runner, daemon pool, propagated context and registered worker; corrected production Recovery.tool reads/writes through legitimate handoff and refuses actual timed-out callbacks. Reduced native SQLite projection fixture; no full conversation/model/live service claim.'}
path=out/'tests.private.json';path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_before','source_after')}))
print(hashlib.sha256(path.read_bytes()).hexdigest());sys.exit(not receipt['passed'])
