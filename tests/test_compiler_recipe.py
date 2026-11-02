"""Component and inert-process checks; these never invoke CMake or a model."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from adaptive_inference.config import Config
from adaptive_inference.handoff import ForegroundPolicy, HandoffController, ToolRequirements
from adaptive_inference.scheduler import Scheduler
from adaptive_inference.desktop.compiler_recipe import (
    CompilerRecipe, Executable, RecipeCleanupError, RecipeInterrupted, _ProcessOwner, _Job, run_recipe,
)
from test_handoff import Adapter, sample


class ScriptedOwner:
    """Test double for recipe commands, separate from actual inert subtree checks."""
    def __init__(self, recipe, controller, codes=(), *, bad_report=False, bad_cleanup=False):
        self.recipe, self.controller, self.codes = recipe, controller, iter(codes)
        self.bad_report, self.bad_cleanup = bad_report, bad_cleanup
        self.records = []
        self.terminated = self.closed = False
        self.started = asyncio.Event()

    def check(self, deadline, interruption):
        if interruption.is_set():
            raise RecipeInterrupted('injected foreground interruption')
        if time.perf_counter() >= deadline:
            raise TimeoutError('original deadline')

    async def run(self, command, *, cwd, log, deadline, interruption):
        assert self.controller.tool is not None
        assert self.controller() is False
        assert self.controller.state == 'parked'
        self.started.set()
        code = next(self.codes, 0)
        self.records.append({'argv': command, 'deadline': deadline, 'exit_code': code, 'joined': True})
        log.write_text('inert command result\n', encoding='utf-8')
        if len(self.records) == 3 and code == 0:
            self.recipe.build.mkdir(exist_ok=True)
            (self.recipe.build / self.recipe.artifact).write_bytes(b'component-only fake artifact')
            body = '<failure message="wrong result"/>' if self.bad_report else ''
            (self.recipe.run / 'tests.xml').write_text(
                '<testsuite><testcase name="answer">' + body + '</testcase></testsuite>', encoding='utf-8')
        return code

    async def close(self):
        if self.bad_cleanup:
            raise RuntimeError('injected unconfirmed descendant')
        self.closed = True
        return {'total': len(self.records), 'active': 0, 'limit_terminated': 0}


class RecipeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        source = root / 'source'
        source.mkdir()
        (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.21)\n', encoding='utf-8')
        pin = Executable(Path(sys.executable).resolve(), hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest())
        self.recipe = CompilerRecipe(pin, pin, pin, pin, source,
            (('CMakeLists.txt', hashlib.sha256((source / 'CMakeLists.txt').read_bytes()).hexdigest()),),
            root / 'run', 'answer.exe', ('answer',), 2, ToolRequirements(1, 1, 0), 256, 20,
            tuple((key, value) for key, value in os.environ.items() if key.upper() in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')))
        self.adapter = Adapter()
        self.controller = HandoffController(self.adapter,
            ForegroundPolicy(recovery_s=0, engage_samples=1), clock=time.perf_counter)
        self.scheduler = Scheduler(Config(), self.controller)
        self.controller.bind_scheduler(self.scheduler)
        await self.controller.initialize()
        self.running = True
        self.pump = asyncio.create_task(self.pump_controller())
        self.addAsyncCleanup(self.stop_pump)

    async def pump_controller(self):
        while self.running:
            self.controller.observe(sample(time.perf_counter()))
            await self.controller.step()
            await asyncio.sleep(.01)

    async def stop_pump(self):
        self.running = False
        await self.pump
        await self.scheduler.close()

    def owner(self, **kwargs):
        owner = ScriptedOwner(self.recipe, self.controller, **kwargs)
        return owner, lambda *args, **kw: owner

    async def test_fixed_recipe_hands_off_and_returns_exact_artifact_and_tests(self):
        owner, factory = self.owner()
        original = time.perf_counter() + 25
        result = await run_recipe(self.controller, self.recipe, task_deadline=original, _owner_factory=factory)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['task_deadline'], original)
        self.assertLessEqual(result['deadline'], original)
        self.assertEqual(result['tests_passed'], ['answer'])
        self.assertTrue(owner.closed)
        self.assertIsNone(self.controller.tool)
        self.assertEqual([r['stage'] for r in result['stages']], ['configure', 'build', 'test'])
        configure = result['stages'][0]['argv']
        for flag in ('-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POLICY_DEFAULT_CMP0141=NEW',
                     '-DCMAKE_MSVC_DEBUG_INFORMATION_FORMAT=Embedded',
                     '-DCMAKE_TRY_COMPILE_CONFIGURATION=Release'):
            self.assertEqual(configure.count(flag), 1)
        self.assertTrue(all(row['deadline'] == result['deadline'] for row in owner.records))
        self.assertIn('--no-tests=error', result['stages'][2]['argv'])
        self.assertIn('--parallel', result['stages'][1]['argv'])
        self.assertEqual(json.loads((self.recipe.run / 'receipt.json').read_text(encoding='utf-8')), result)
        self.assertEqual(self.adapter.calls[0][0], 'stop')

    async def test_declared_llvm_linker_is_fixed_and_changed_bytes_refuse_before_grant(self):
        self.assertIsNone(self.recipe.linker)
        self.assertNotIn('-DCMAKE_LINKER_TYPE=LLD', self.recipe.commands()[0][1])
        tools = self.recipe.source.parent / 'LLVM tools with spaces'
        tools.mkdir()
        for name in ('clang-cl.exe', 'lld-link.exe'):
            (tools / name).write_bytes(b'inert pinned tool; never executed')
        compiler = Executable(tools / 'clang-cl.exe', hashlib.sha256((tools / 'clang-cl.exe').read_bytes()).hexdigest())
        linker = Executable(tools / 'lld-link.exe', hashlib.sha256((tools / 'lld-link.exe').read_bytes()).hexdigest())
        self.recipe = replace(self.recipe, compiler=compiler, linker=linker)
        self.recipe.verify(fresh=True)
        command = self.recipe.commands()[0][1]
        for flag in ('-DCMAKE_LINKER_TYPE=LLD', '-DCMAKE_LINKER:FILEPATH=' + linker.path.as_posix(),
                     '-DCMAKE_LINKER_LLD:FILEPATH=' + linker.path.as_posix(),
                     '-DCMAKE_CXX_COMPILER=' + compiler.path.as_posix(),
                     '-DCMAKE_MAKE_PROGRAM=' + self.recipe.ninja.path.as_posix()):
            self.assertEqual(command.count(flag), 1)
            self.assertNotIn('\\', flag)
        linker.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() + 10)
        self.assertIsNone(self.controller.tool)
        self.assertFalse(self.recipe.run.exists())

    async def test_changed_source_or_consumed_destination_refuses_before_grant(self):
        (self.recipe.source / 'CMakeLists.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() + 10)
        self.assertIsNone(self.controller.tool)
        self.assertFalse(self.recipe.run.exists())
        self.recipe.run.mkdir()
        with self.assertRaisesRegex(ValueError, 'output already exists'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() + 10)

    async def test_nonzero_build_and_test_stop_without_retry_and_release_only_after_close(self):
        for codes, stage, count in [((0, 7), 'build', 2), ((0, 0, 8), 'test', 3)]:
            with self.subTest(stage=stage):
                self.recipe = replace(self.recipe, run=self.recipe.run.parent / stage)
                owner, factory = self.owner(codes=codes)
                result = await run_recipe(self.controller, self.recipe,
                    task_deadline=time.perf_counter() + 15, _owner_factory=factory)
                self.assertFalse(result['passed'])
                self.assertEqual(result['failure_stage'], stage)
                self.assertEqual(len(owner.records), count)
                self.assertTrue(owner.closed)
                self.assertTrue(result['owned_processes_exited'])
                self.assertIsNone(self.controller.tool)

    async def test_zero_exit_does_not_override_failed_test_report(self):
        owner, factory = self.owner(bad_report=True)
        result = await run_recipe(self.controller, self.recipe,
            task_deadline=time.perf_counter() + 15, _owner_factory=factory)
        self.assertFalse(result['passed'])
        self.assertIn('exact declared tests', result['error']['message'])
        self.assertTrue(owner.closed)

    async def test_unknown_descendant_exit_latches_existing_controller_and_retains_owner(self):
        owner, factory = self.owner(bad_cleanup=True)
        with self.assertRaises(RecipeCleanupError) as caught:
            await run_recipe(self.controller, self.recipe,
                task_deadline=time.perf_counter() + 15, _owner_factory=factory)
        self.assertIs(caught.exception.owner, owner)
        self.assertFalse(caught.exception.receipt['owned_processes_exited'])
        self.assertFalse(caught.exception.receipt['passed'])
        self.assertEqual(self.controller.fault, 'tool_exit_unconfirmed')
        self.assertIsNotNone(self.controller.tool)
        self.assertFalse(self.controller())

    async def test_cancellation_joins_before_propagating_and_saves_failure(self):
        owner, factory = self.owner()
        async def held(*args, **kwargs):
            owner.started.set()
            await asyncio.Event().wait()
        owner.run = held
        work = asyncio.create_task(run_recipe(self.controller, self.recipe,
            task_deadline=time.perf_counter() + 15, _owner_factory=factory))
        await asyncio.wait_for(owner.started.wait(), 5)
        work.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await work
        self.assertTrue(owner.closed)
        result = json.loads((self.recipe.run / 'receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['passed'])
        self.assertTrue(result['owned_processes_exited'])
        self.assertIsNone(self.controller.tool)

    async def test_expired_original_task_cannot_get_a_fresh_recipe_budget(self):
        with self.assertRaisesRegex(ValueError, 'original execution deadline'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() - .01)
        self.assertIsNone(self.controller.tool)
        self.assertFalse(self.recipe.run.exists())


@unittest.skipUnless(os.name == 'nt' and sys.version_info[:3] == (3, 11, 9),
                     'Actual job ownership uses the supported full Windows CPython 3.11.9')
class InertSubtreeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = dict(os.environ)
        self.owner = _ProcessOwner(256, env)
        self.addAsyncCleanup(self.owner.close)
        self.interruption = asyncio.Event()

    def python(self, code):
        return [sys.executable, '-I', '-B', '-c', code]

    async def run_child(self, command):
        return await self.owner.run(command, cwd=self.root, log=self.root / 'child.log',
            deadline=time.perf_counter() + 15, interruption=self.interruption)

    async def test_normal_parent_waits_for_later_grandchild_exit(self):
        marker = self.root / 'grandchild-done'
        grandchild = "import pathlib,time;time.sleep(.1);pathlib.Path(%r).write_text('done')" % str(marker)
        code = 'import subprocess,sys;subprocess.Popen([sys.executable,"-I","-B","-c",%r])' % grandchild
        self.assertEqual(await self.run_child(self.python(code)), 0)
        self.assertEqual(marker.read_text(), 'done')
        accounting = await self.owner.close()
        self.assertGreaterEqual(accounting['total'], 3)
        self.assertEqual(accounting['active'], 0)
        self.assertTrue(all(row['joined'] for row in self.owner.records))
        self.assertFalse(self.owner.terminated)

    async def test_interruption_terminates_only_owned_subtree_and_confirms_empty(self):
        marker = self.root / 'grandchild-ready'
        grandchild = "import pathlib,time;pathlib.Path(%r).write_text('ready');time.sleep(60)" % str(marker)
        code = 'import subprocess,sys;subprocess.Popen([sys.executable,"-I","-B","-c",%r]).wait()' % grandchild
        work = asyncio.create_task(self.run_child(self.python(code)))
        try:
            async with asyncio.timeout(5):
                while not marker.exists():
                    await asyncio.sleep(.02)
            self.interruption.set()
            with self.assertRaises(RecipeInterrupted):
                await work
        finally:
            if not work.done():
                work.cancel()
                try:
                    await work
                except asyncio.CancelledError:
                    pass
            accounting = await self.owner.close()
        self.assertEqual(accounting['active'], 0)
        self.assertGreaterEqual(accounting['total'], 3)
        self.assertTrue(self.owner.terminated)
        self.assertTrue(all(row['joined'] for row in self.owner.records))

    async def test_assignment_failure_never_delivers_command_and_joins_gated_child(self):
        marker = self.root / 'must-not-exist'
        command = self.python("import pathlib;pathlib.Path(%r).write_text('bad')" % str(marker))
        with patch.object(_Job, 'assign', side_effect=RuntimeError('injected assignment failure')):
            with self.assertRaisesRegex(RuntimeError, 'assignment failure'):
                await self.run_child(command)
        accounting = await self.owner.close()
        self.assertFalse(marker.exists())
        self.assertEqual(accounting['active'], 0)
        self.assertEqual(len(self.owner.records), 1)
        record = self.owner.records[0]
        self.assertFalse(record['command_delivered'])
        self.assertFalse(record['assigned'])
        self.assertTrue(record['joined'])

    async def test_actual_nonzero_child_is_returned_without_retry(self):
        self.assertEqual(await self.run_child(self.python('raise SystemExit(7)')), 7)
        await self.owner.close()
        self.assertEqual(len(self.owner.records), 1)
        self.assertEqual(self.owner.records[0]['exit_code'], 7)
        self.assertTrue(self.owner.records[0]['joined'])
        self.assertFalse(self.owner.terminated)


if __name__ == '__main__':
    unittest.main()
