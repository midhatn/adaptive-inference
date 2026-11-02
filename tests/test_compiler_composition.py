"""Compiler launch/Stop integration with inert tools and retained lifecycle fakes."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from adaptive_inference.desktop.composition import DesktopComposition
from adaptive_inference.desktop.desktop_controls import DesktopControlLifecycle
from adaptive_inference.desktop.control_transport import PreparedTask
from adaptive_inference.desktop.profile import WindowsProfile
from adaptive_inference.desktop.compiler_profile import verify_settings
from adaptive_inference.desktop.task_handover import HostTaskHandover
from adaptive_inference.task_spec import TaskSpec
from test_compiler_task_spec import compiler_data
from test_desktop_installation import profile_value
from test_desktop_lifecycle import Host, Worker, GUI


class CompilerLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.c = object.__new__(DesktopComposition)
        self.c.compiler_host = object(); self.c.compiler_bindings = {}
        self.c.host_epoch = 'host-1'; self.c.host = SimpleNamespace(gateway=SimpleNamespace(instance='gateway-1'))
        self.spec = TaskSpec(compiler_data())
        self.plan = {'task_spec': self.spec.data, 'task_spec_sha256': self.spec.sha256}

    def test_launch_binding_contains_original_identity_without_secret_on_argv(self):
        args = self.c.compiler_launch_args(self.root, self.plan, execution_id='task', task_id='task',
                                           deadline=900., diagnostics=self.root)
        path = Path(args[1]); raw = path.read_bytes(); data = json.loads(raw)
        self.assertEqual(args[3], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(data['capability'], args)
        self.assertEqual(data['task_deadline'], 900.)
        self.assertEqual(data['execution_id'], 'task')
        with self.assertRaises(RuntimeError):
            self.c.compiler_launch_args(self.root, self.plan, execution_id='task', task_id='task',
                                        deadline=1800., diagnostics=self.root)
        self.assertEqual(path.read_bytes(), raw)

    def test_file_only_launch_has_no_compiler_binding(self):
        self.assertEqual(self.c.compiler_launch_args(self.root, {'task_id': 'orders-report'},
            execution_id='task', task_id='task', deadline=900., diagnostics=self.root), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_profile_pins_tools_and_keeps_fixed_resource_limits(self):
        value = profile_value(self.root)
        compiler = {'schema': 'adaptive.compiler-settings.v1', 'environment': {'PATH': str(self.root)}}
        for key, name in [('cmake','cmake.exe'), ('ctest','ctest.exe'), ('compiler','clang-cl.exe'),
                          ('ninja','ninja.exe'), ('linker','lld-link.exe')]:
            path = self.root/name; path.write_bytes(b'inert-'+key.encode())
            compiler[key] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        self.assertIsNone(WindowsProfile.from_dict(value).compiler)
        configured = WindowsProfile.from_dict({**value, 'compiler': compiler}).compiler
        verify_settings(configured)
        self.assertEqual((configured.parallel_jobs, configured.job_memory_mib, configured.max_seconds), (2,2048,90))
        configured.compiler.path.write_bytes(b'changed')
        with self.assertRaises(ValueError): verify_settings(configured)


class CompilerStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_handover_failure_cleanup_joins_compiler_before_native_close(self):
        release, entered = asyncio.Event(), asyncio.Event()
        operation = asyncio.create_task(release.wait())
        events = []
        class Compiler:
            def interrupt(self): events.append('interrupt')
            async def close(self, **_): entered.set()
            def obligations(self):
                return ({'close_task': None, 'operations': ({'task': operation, 'runner': None},)},)
            def lifecycle(self): return {'bridge': {'closed': operation.done()}}
        class Native:
            async def close(self, **_):
                assert operation.done(); events.append('native_closed'); return {'closed': True}
        composition = SimpleNamespace(compiler_host=Compiler(), handles=[], host=Native(), result={})
        owner = HostTaskHandover(composition); owner.fence = lambda: None
        cleanup = asyncio.create_task(owner.failure_cleanup())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertNotIn('native_closed', events)
            self.assertFalse(cleanup.done())
            release.set(); await asyncio.wait_for(asyncio.shield(cleanup), 2)
            self.assertIn('native_closed', events)
            self.assertTrue(all(task.done() for task in owner._failure_drains))
        finally:
            release.set(); await asyncio.wait_for(asyncio.shield(cleanup), 2)
            await operation

    async def test_stop_interrupts_and_joins_compiler_before_worker_stop(self):
        worker, gui = Worker(), GUI()
        host = Host(worker, gui)
        entered, released = asyncio.Event(), asyncio.Event()
        events = []
        class Compiler:
            def interrupt(self): events.append('compiler_interrupt')
            async def close(self, *, timeout):
                entered.set(); await released.wait(); events.append('compiler_joined')
                return {'bridge': {'closed': True, 'unknown': 0}}
        host.compiler_operations = Compiler()
        original = worker.request_stop
        def stop(cap): events.append('worker_stop'); original(cap)
        worker.request_stop = stop
        facade = DesktopControlLifecycle(host, PreparedTask('host','task','objective'),
            worker_stop=worker, worker_capability=object(), gui=gui)
        work = asyncio.create_task(facade.cooperative_stop())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertEqual(worker.requests, 0)
            self.assertEqual(events, ['compiler_interrupt'])
            released.set(); worker.release.set(); gui.release.set()
            result = await asyncio.wait_for(asyncio.shield(work), 2)
            self.assertLess(events.index('compiler_joined'), events.index('worker_stop'))
            self.assertTrue(result['worker_joined']); self.assertTrue(result['host_closed'])
            self.assertFalse(result['uncertain'])
        finally:
            released.set(); worker.release.set(); gui.release.set()
            await asyncio.wait_for(asyncio.shield(work), 2)


if __name__ == '__main__': unittest.main()
