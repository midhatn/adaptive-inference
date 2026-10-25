"""CPU-only host composition: fixture listener/job/reader/native driver, real task DB."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent/'desktop_native_support'
import ast, asyncio, copy, importlib.util, math, os, tempfile, threading, time, unittest
from types import SimpleNamespace
from unittest import mock
from adaptive_inference.config import Config
from adaptive_inference.demand import DemandIdentity,DemandRegistry,Registration,NAMESPACE
from adaptive_inference.task_store import TaskStore
from adaptive_inference.handoff import ForegroundPolicy,ToolRequirements
from adaptive_inference.desktop.cold_start import ColdStartAdapter
from adaptive_inference.desktop.native_owner_adapter import CapacityMonitor,OwnerStartupError
from adaptive_inference.desktop.persistent_host import PersistentDesktopHost
from test_desktop_native_owner import Driver,live

spec=importlib.util.spec_from_file_location('fixture_policy',HERE/'planner_source/sealed_memory_policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
def definitions(file,names,namespace):
    tree=ast.parse((HERE/'planner_source'/file).read_text())
    selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in selected}==set(names)
    exec(compile(ast.Module(body=selected,type_ignores=[]),file,'exec'),namespace)
    return namespace
planner=definitions('owner_engine.py',('plan_startup_cache',),
    {'MemoryPolicy':policy.MemoryPolicy,'GIB':policy.GIB,'math':math})['plan_startup_cache']
validators=definitions('memory_reader.py',('GuardError','checked_sample','checked_host_sample'),
    {'math':math,'time':time})

class Job:
    def __init__(self):self.contained=False;self.children=set()
    def contain_current_process(self):self.contained=True
    def active_process_ids(self):return {os.getpid(),*self.children}
class Reader:
    busy=False
    def sample(self):
        return {'monotonic_s':time.monotonic(),'session_input_idle_s':0 if self.busy else 100,
          'foreground':{'pid':44,'creation_time_100ns':55,'valid':True,'cpu_cores_used':0},
          'host':{'ram_available_gib':40,'commit_available_gib':60},'errors':[]}
class Runner:
    def __init__(self,app,**kw):self.app=app;self.open=False;self.cleaned=False
    async def setup(self):self.open=True
    async def cleanup(self):self.cleaned=True
class Site:
    def __init__(self,runner,host,port):self.runner=runner;self.open=False
    async def start(self):self.open=True
    async def stop(self):self.open=False
class RichDriver(Driver):
    def __init__(self):
        super().__init__();self.state={'state':'stopped','running':False}
        self.ram=30;self.commit=40;self.gpu=6*2**30;self.runtime_seen='unset'
        self.start_entered=threading.Event();self.start_release=None;self.invalid_profile=False
    def owner_idle(self):return True
    def start_owner(self,runtime):
        self.runtime_seen=runtime;self.start_entered.set()
        if self.start_release is not None and not self.start_release.wait(4):
            raise RuntimeError('Fixture start deadline')
        self.reuse_owner=self.starts%2==1
        return super().start_owner(runtime)
    def capacity(self):
        return {'sampled_at':time.monotonic(),'complete':True,
          'available_ram_gib':self.ram,'available_commit_gib':self.commit,
          'available_vram_mib':self.gpu/2**20,
          'raw_host':{'sampled_at':time.time(),'total_ram_gib':64,
                      'available_ram_gib':self.ram,'available_commit_gib':self.commit},
          'raw_gpu':{'total_bytes':8*2**30,'used_bytes':8*2**30-self.gpu,'free_bytes':self.gpu}}
    def load_plan_context(self):
        return {'config':{'args':['--resident-budget-gib','32','--vram-reserve-mib','448'],
             'memory_policy':{'enabled':not self.invalid_profile,'mode':'live',
                              'min_ram_headroom_gib':4,'overhead_ram_gib':14}},
          'plan_startup_cache':planner,'checked_host_sample':validators['checked_host_sample'],
          'checked_gpu_sample':validators['checked_sample']}

async def until(predicate,limit=3):
    deadline=time.monotonic()+limit
    while not predicate():
        if time.monotonic()>deadline:raise AssertionError('Fixture deadline')
        await asyncio.sleep(.01)

class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.store=TaskStore(self.root/'tasks.sqlite3')
        self.identity=DemandIdentity('r','t','worker','2026-10-24T12:00:00Z')
        cp=self.store.create('t','Keep original task',max_attempts=3,metadata={NAMESPACE:self.identity.metadata()})
        self.claim=self.store.claim('t',expected_revision=cp.revision);self.owned=self.claim.__enter__()
        self.registry=DemandRegistry((Registration(self.store,self.identity),))
        self.job,self.reader,self.driver=Job(),Reader(),RichDriver()
        self.adapter=ColdStartAdapter(_driver=self.driver,job=self.job,max_runtime_seconds=None)
        self.host=PersistentDesktopHost({},Config(port=18199,backend_kind='strata',
            backend_url='http://127.0.0.1:18098/v1'),self.root/'run',
            ForegroundPolicy(input_hold_s=1,recovery_s=0,engage_samples=1),
            demand=self.registry,restore_requirements=ToolRequirements(4,4,448),
            adapter=self.adapter,reader=self.reader,job=self.job,idle_grace_s=.1,
            _runner_factory=Runner,_site_factory=Site)
    async def asyncTearDown(self):
        self.job.children.clear()
        if self.driver.start_release is not None:self.driver.start_release.set()
        if self.host.started_at is not None and not self.host.closed:
            try:await self.host.close(timeout_s=2)
            except Exception:pass # Negative fixtures retain truthful unresolved receipts.
        self.host.activity_stop.set();self.host.watchdog_done.set()
        if self.host.activity_thread:await asyncio.to_thread(self.host.activity_thread.join,2)
        self.claim.__exit__(None,None,None);self.temp.cleanup()
    def demand(self,state):
        return self.registry.transition('r',self.owned,state,
            expected_revision=self.owned.checkpoint.revision,updated_at_utc='2026-10-24T12:01:00Z')
    async def test_persistent_cold_listener_without_demand_never_starts_native(self):
        cp=self.owned.checkpoint;history=self.store.history('t')
        result=await self.host.start()
        self.assertTrue(result['service_started']);self.assertFalse(result['model_ready'])
        await asyncio.sleep(.25)
        self.assertEqual(self.driver.starts,0);self.assertEqual(self.host.controller.state,'parked')
        self.assertIsNone(self.host.snapshot()['service_lifetime_seconds'])
        self.assertEqual(self.store.load('t'),cp);self.assertEqual(self.store.history('t'),history)
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'never_launched');self.assertIsNone(result['release'])
        self.assertFalse(result['normal_release_confirmed']);self.assertFalse(self.driver.locked)
    async def test_setup_timeout_is_bounded_but_retains_blocked_verification_and_cleanup(self):
        entered=threading.Event();release=threading.Event();original=self.driver.verify
        def blocked():
            entered.set()
            if not release.wait(4):raise RuntimeError('Fixture setup bound')
            return original()
        self.driver.verify=blocked
        started=time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(self.host.start(timeout_s=1),1.6)
            self.assertLess(time.monotonic()-started,1.5)
            self.assertTrue(entered.is_set());self.assertTrue(self.driver.locked)
            self.assertFalse(self.host.setup_task.done());self.assertFalse(self.host.closed)
            self.assertTrue(self.host.gateway.scheduler.closing)
            self.assertEqual(self.driver.starts,0);self.assertIsNone(self.host.site)
        finally:release.set()
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'never_launched')
        self.assertEqual(result['primary_error']['type'],'TimeoutError')
        self.assertIsNone(self.host.site);self.assertEqual(self.driver.starts,0)
    async def test_clean_lifecycle_close_retains_controller_fault_and_no_qualification_claim(self):
        self.demand('waiting');await self.host.start();await until(self.host.controller)
        self.host.controller._fail('fixture_controller_fault')
        result=await self.host.close(timeout_s=3)
        self.assertTrue(result['closed']);self.assertTrue(result['normal_release_confirmed'])
        self.assertEqual(result['controller_fault'],'fixture_controller_fault')
        self.assertFalse(result['qualification_claimed'])
    async def test_completed_setup_timeout_is_joined_failure_not_permanent_cleanup_block(self):
        original=self.driver.verify;calls=[]
        def timed_out_once():
            calls.append(1)
            if len(calls)==1:raise TimeoutError('fixture verification timed out')
            return original()
        self.driver.verify=timed_out_once
        with self.assertRaisesRegex(TimeoutError,'fixture verification'):
            await self.host.start(timeout_s=2)
        self.assertTrue(self.host.setup_task.done())
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'never_launched')
        self.assertEqual(result['primary_error']['type'],'TimeoutError')
        self.assertIn('fixture verification',result['primary_error']['message'])
        self.assertEqual(result['controller_fault'],'initial_owner_unverified')
        self.assertFalse(result['qualification_claimed']);self.assertFalse(self.driver.locked)
        self.assertEqual((self.driver.starts,self.driver.stops),(0,0))
    async def test_demand_wakes_without_http_ticket_and_idle_releases(self):
        self.demand('waiting');await self.host.start();await until(self.host.controller)
        self.assertIsNone(self.driver.runtime_seen);self.assertEqual(self.driver.starts,1)
        self.assertFalse(self.host.gateway.scheduler.pending)
        self.assertEqual(self.host.controller.load_preview['state'],'candidate')
        self.demand('fulfilled');await until(lambda:self.host.controller.state=='parked')
        self.assertEqual(self.driver.stops,1)
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'released_owner');self.assertTrue(result['normal_release_confirmed'])
    async def test_capacity_wait_is_read_only_and_recovers_same_task(self):
        self.driver.commit=18;self.demand('waiting');before=self.owned.checkpoint
        await self.host.start();await asyncio.sleep(.35)
        self.assertEqual(self.driver.starts,0)
        self.assertEqual(self.host.controller.load_preview['state'],'waiting_capacity')
        self.assertEqual(self.store.load('t'),before)
        self.driver.commit=40;await until(self.host.controller)
        self.assertEqual(self.driver.starts,1);self.assertEqual(self.store.load('t'),before)
    async def test_profile_floor_blocks_candidate_with_only_250_mib_gpu(self):
        self.driver.gpu=250*2**20;self.demand('waiting')
        await self.host.start();await asyncio.sleep(.35)
        self.assertEqual(self.driver.starts,0)
        self.assertEqual(self.host.controller.load_preview['reason'],'profile_floors_or_context_unavailable')
    async def test_unknown_and_invalid_profile_hold_without_fault_or_attempt(self):
        self.driver.invalid_profile=True;self.demand('waiting')
        await self.host.start();await asyncio.sleep(.35)
        self.assertEqual(self.driver.starts,0);self.assertIsNone(self.host.controller.fault)
        self.assertEqual(self.host.controller.load_preview['state'],'unknown')
    async def test_foreground_busy_blocks_restoration_then_recovers(self):
        self.reader.busy=True;self.demand('waiting');await self.host.start()
        await asyncio.sleep(.3);self.assertEqual(self.driver.starts,0)
        self.reader.busy=False;await until(self.host.controller)
        self.assertEqual(self.driver.starts,1)
    async def test_observer_refreshes_independently_during_start_and_cancel_prevents_admission(self):
        calls=[];original=self.registry.observations
        def observe():calls.append(time.monotonic());return original()
        self.registry.observations=observe
        self.driver.start_release=threading.Event();self.demand('waiting')
        await self.host.start();await until(self.driver.start_entered.is_set)
        count=len(calls);self.demand('cancelled');await asyncio.sleep(.25)
        self.assertGreater(len(calls),count)
        self.driver.start_release.set()
        await until(lambda:self.driver.stops==1)
        self.assertFalse(self.host.controller());self.assertEqual(self.driver.starts,1)
    async def test_close_during_deferred_start_joins_then_stops_exact_new_owner(self):
        self.driver.start_release=threading.Event();self.demand('waiting')
        await self.host.start();await until(self.driver.start_entered.is_set)
        closing=asyncio.create_task(self.host.close(timeout_s=3))
        await asyncio.sleep(.1);self.assertFalse(closing.done())
        self.driver.start_release.set();result=await closing
        self.assertTrue(result['closed']);self.assertEqual(self.driver.stops,1)
        self.assertEqual(result['release']['owner_id'],self.adapter.launch_intent['owner_id'])
    async def test_cancelled_close_is_retained_and_retrievable(self):
        self.demand('waiting');await self.host.start();await until(self.host.controller)
        ticket=await self.host.gateway.scheduler.acquire('normal',None)
        closing=asyncio.create_task(self.host.close(timeout_s=3))
        await until(lambda:self.host.gateway.scheduler.closing);closing.cancel()
        await asyncio.sleep(.05);self.assertFalse(closing.done())
        await self.host.gateway.scheduler.release(ticket)
        with self.assertRaises(asyncio.CancelledError):await closing
        self.assertTrue((await self.host.close(timeout_s=3))['closed'])
        self.assertEqual(self.driver.stops,1)
    async def test_stalled_demand_read_stays_unknown_and_shutdown_retains_it(self):
        started=threading.Event();release=threading.Event();original=self.registry.observations
        def blocked():
            started.set()
            if not release.wait(4):raise RuntimeError('Fixture read bound')
            return original()
        self.registry.observations=blocked;self.demand('waiting')
        await self.host.start()
        try:
            await until(started.is_set)
            await asyncio.sleep(.2)
            self.assertEqual(self.host.controller._demand_state(),'unknown')
            self.assertEqual(self.driver.starts,0)
            with self.assertRaisesRegex(RuntimeError,'Demand observation still owns'):
                await self.host.close(timeout_s=1)
            self.assertFalse(self.host.closed)
            self.assertFalse(self.host.demand_task.done())
            self.assertTrue(self.driver.locked)
        finally:release.set()
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'never_launched')
    async def test_uncertain_scheduler_refuses_normal_release(self):
        self.demand('waiting');await self.host.start();await until(self.host.controller)
        ticket=await self.host.gateway.scheduler.acquire('normal',None)
        await self.host.gateway.scheduler.release(ticket,uncertain=True)
        with self.assertRaisesRegex(RuntimeError,'Scheduler completion'):
            await self.host.close(timeout_s=2)
        self.assertFalse(self.host.closed);self.assertEqual(self.driver.stops,0)
        self.assertIsNone(self.host.close_result)
    async def test_typed_failed_start_uses_exact_failure_receipt_not_active_status(self):
        failure=OwnerStartupError('fixture launch failed',owner_id='attempt',run=self.root/'missing',
            process=SimpleNamespace(pid=222,poll=lambda:1))
        def fail(runtime):self.driver.starts+=1;raise failure
        self.driver.start_owner=fail;self.demand('waiting');await self.host.start()
        await until(lambda:self.host.drive_task.done())
        self.driver.status=lambda:(_ for _ in ()).throw(AssertionError('Never adopt after failed start'))
        result=await self.host.close(timeout_s=3)
        self.assertEqual(result['outcome'],'failed_start_cleanup')
        self.assertFalse(result['normal_release_confirmed'])
        self.assertEqual(result['primary_error']['type'],'OwnerStartupError')
        self.assertIsNone(result['release'])
    async def test_untyped_failed_start_preserves_primary_and_cleanup_errors(self):
        def fail(runtime):self.driver.starts+=1;raise RuntimeError('original launch uncertainty')
        self.driver.start_owner=fail;self.demand('waiting');await self.host.start()
        await until(lambda:self.host.drive_task.done())
        with self.assertRaisesRegex(RuntimeError,'Deferred startup remains unresolved'):
            await self.host.close(timeout_s=3)
        self.assertFalse(self.host.closed);self.assertTrue(self.driver.locked)
        self.assertIn('original launch uncertainty',self.host.primary_error['message'])
        self.assertIn('Deferred startup',self.host.cleanup_error['message'])
    async def test_external_worker_blocks_close_and_retry_rechecks_job(self):
        self.demand('waiting');await self.host.start();await until(self.host.controller)
        self.job.children.add(99999)
        with self.assertRaisesRegex(RuntimeError,'external worker'):
            await self.host.close(timeout_s=2)
        self.assertEqual(self.driver.stops,0);self.assertFalse(self.host.closed)
        self.job.children.clear();self.assertTrue((await self.host.close(timeout_s=3))['closed'])
    async def test_tool_capacity_does_not_run_model_cache_preview(self):
        await self.host.start();await until(lambda:self.host.controller.policy.allowed)
        self.host.controller.load_context=None
        requirements=ToolRequirements(1,1,100)
        self.assertTrue(self.host.controller._capacity_fits(self.driver.capacity(),requirements))

class PairedMonitorTests(unittest.TestCase):
    def test_same_reader_supplies_raw_and_projected_fields_and_closes_once(self):
        counts={'factory':0,'read':0,'close':0}
        def factory():
            counts['factory']+=1
            def read():
                counts['read']+=1
                return {'host':{'sampled_at':time.time(),'total_ram_gib':64,
                    'available_ram_gib':30,'available_commit_gib':40},
                    'gpu':{'total_bytes':8*2**30,'used_bytes':2*2**30,'free_bytes':6*2**30}}
            def close():counts['close']+=1
            return read,close
        monitor=CapacityMonitor(factory)
        try:
            monitor.start();row=monitor.snapshot()
            self.assertEqual(row['available_vram_mib'],row['raw_gpu']['free_bytes']/2**20)
            row['raw_host']['available_ram_gib']=0
            self.assertEqual(monitor.snapshot()['raw_host']['available_ram_gib'],30)
        finally:monitor.close()
        self.assertEqual(counts['factory'],1);self.assertEqual(counts['close'],1)
    def test_invalid_raw_projection_stops_observer(self):
        monitor=CapacityMonitor(lambda:(lambda:{'host':{},'gpu':{}},lambda:None))
        with self.assertRaises(Exception):monitor.start()
        with self.assertRaises(Exception):monitor.close()

if __name__=='__main__':unittest.main(verbosity=2)

