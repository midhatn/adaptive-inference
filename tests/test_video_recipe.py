"""Fixed-video component checks; fake tools only, no GPU or process execution."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from adaptive_inference.config import Config
from adaptive_inference.handoff import ForegroundPolicy, HandoffController, ToolRequirements
from adaptive_inference.scheduler import Scheduler
from adaptive_inference.desktop.video_recipe import (
    Executable, RecipeCleanupError, RecipeInterrupted, VideoRecipe, run_recipe,
)
from test_handoff import Adapter, sample


class ScriptedOwner:
    def __init__(self, recipe, controller, *, codes=(), probe=None, decode=b'', bad_cleanup=False,
                 interrupt=False):
        self.recipe, self.controller, self.codes = recipe, controller, iter(codes)
        self.probe = probe if probe is not None else {'streams': [
            {'codec_name': 'h264', 'width': 1280, 'height': 720, 'nb_read_frames': '90'}]}
        self.decode, self.bad_cleanup, self.interrupt = decode, bad_cleanup, interrupt
        self.records = []
        self.terminated = self.closed = False
        self.clock = time.perf_counter
        self.started = asyncio.Event()

    def check(self, deadline, interruption):
        if interruption.is_set():
            raise RecipeInterrupted('injected foreground interruption')
        if self.clock() >= deadline:
            raise TimeoutError('original deadline')

    async def run(self, command, *, cwd, log, deadline, interruption):
        assert self.controller.tool is not None and self.controller.tool.granted
        assert self.controller() is False and self.controller.state == 'parked'
        assert cwd == self.recipe.run
        self.started.set()
        code = next(self.codes, 0)
        self.records.append({'argv': command, 'deadline': deadline, 'exit_code': code, 'joined': True})
        stage = log.stem
        if stage == 'encode':
            log.write_bytes(b'simulated encoder log')
            if code == 0:
                (self.recipe.run / self.recipe.artifact).write_bytes(b'component-only fake video')
        elif stage == 'probe':
            log.write_bytes(json.dumps(self.probe).encode() if isinstance(self.probe, dict) else self.probe)
        else:
            log.write_bytes(self.decode)
        if self.interrupt:
            interruption.set()
        return code

    async def close(self):
        # The grant must remain owned until cleanup has confirmed every exit.
        assert self.controller.tool is not None
        if self.bad_cleanup:
            raise RuntimeError('injected unconfirmed descendant')
        self.closed = True
        return {'total': len(self.records), 'active': 0, 'limit_terminated': 0}


class VideoRecipeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        pins = []
        for name in ('ffmpeg.exe', 'ffprobe.exe'):
            path = root / name
            path.write_bytes(b'inert pin only: ' + name.encode())
            pins.append(Executable(path, hashlib.sha256(path.read_bytes()).hexdigest()))
        self.recipe = VideoRecipe(*pins, root / 'run', ())
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
        def factory(memory, environment, *, clock):
            self.assertEqual(memory, self.recipe.job_memory_mib)
            self.assertEqual(environment, dict(self.recipe.environment))
            owner.clock = clock
            return owner
        return owner, factory

    async def test_fixed_clip_uses_one_grant_and_preserves_commands_and_deadline(self):
        owner, factory = self.owner()
        original = time.perf_counter() + 900
        with patch.object(self.controller, 'acquire_tool', AsyncMock(wraps=self.controller.acquire_tool)) as acquire:
            result = await run_recipe(self.controller, self.recipe, task_deadline=original, _owner_factory=factory)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['schema'], 'video-recipe.v1')
        self.assertEqual(result['recipe_id'], 'nvenc-testclip.v1')
        self.assertEqual(result['task_deadline'], original)
        self.assertEqual(result['deadline'], result['started'] + 90)
        self.assertEqual(acquire.await_count, 1)
        self.assertEqual(acquire.call_args.args, (ToolRequirements(8, 12, 6000),))
        self.assertTrue(all(row['deadline'] == result['deadline'] for row in owner.records))
        video = str(self.recipe.run / 'handoff-video.mp4')
        expected = [
            [str(self.recipe.ffmpeg.path), '-hide_banner', '-nostdin', '-n', '-f', 'lavfi', '-i',
             'testsrc2=size=1280x720:rate=30', '-t', '3', '-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p', '-an', video],
            [str(self.recipe.ffprobe.path), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_name,width,height,nb_read_frames', '-of', 'json', video],
            [str(self.recipe.ffmpeg.path), '-hide_banner', '-nostdin', '-v', 'error', '-i', video, '-f', 'null', '-'],
        ]
        self.assertEqual([row['argv'] for row in result['stages']], expected)
        self.assertEqual([row['stage'] for row in result['stages']], ['encode', 'probe', 'decode'])
        self.assertEqual(result['artifact_sha256'], hashlib.sha256(b'component-only fake video').hexdigest())
        self.assertEqual(result['probe']['nb_read_frames'], '90')
        self.assertTrue(result['owned_processes_exited'] and owner.closed)
        self.assertIsNone(self.controller.tool)
        self.assertEqual(result['job_accounting']['active'], 0)
        self.assertEqual(self.adapter.calls[0][0], 'stop')
        self.assertEqual(json.loads((self.recipe.run / 'receipt.json').read_text()), result)

    async def test_changed_pin_and_consumed_output_refuse_before_grant(self):
        self.recipe.ffprobe.path.write_bytes(b'changed executable')
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() + 30)
        self.assertIsNone(self.controller.tool)
        self.assertFalse(self.recipe.run.exists())
        self.recipe.run.mkdir()
        with self.assertRaisesRegex(ValueError, 'output already exists'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() + 30)

    async def test_nonzero_stages_stop_without_fallback_or_retry(self):
        for codes, stage, count in [((7,), 'encode', 1), ((0, 8), 'probe', 2), ((0, 0, 9), 'decode', 3)]:
            with self.subTest(stage=stage):
                self.recipe = replace(self.recipe, run=self.recipe.run.parent / stage)
                owner, factory = self.owner(codes=codes)
                result = await run_recipe(self.controller, self.recipe,
                    task_deadline=time.perf_counter() + 30, _owner_factory=factory)
                self.assertFalse(result['passed'])
                self.assertEqual(result['failure_stage'], stage)
                self.assertEqual(len(owner.records), count)
                self.assertTrue(owner.closed and result['owned_processes_exited'])
                self.assertIsNone(self.controller.tool)

    async def test_successful_exits_require_exact_probe_and_error_free_decode(self):
        wrong = {'streams': [{'codec_name': 'h264', 'width': 1280, 'height': 720, 'nb_read_frames': '89'}]}
        for index, kwargs in enumerate(({'probe': wrong}, {'probe': b'not JSON'}, {'decode': b'decode error'})):
            with self.subTest(kwargs=kwargs):
                self.recipe = replace(self.recipe, run=self.recipe.run.parent / ('bad-output-' + str(index)))
                owner, factory = self.owner(**kwargs)
                result = await run_recipe(self.controller, self.recipe,
                    task_deadline=time.perf_counter() + 30, _owner_factory=factory)
                self.assertFalse(result['passed'])
                self.assertTrue(all(row['exit_code'] == 0 for row in result['stages']))
                self.assertIn('error', result)
                self.assertTrue(owner.closed)
                self.assertIsNone(self.controller.tool)

    async def test_waiting_for_grant_does_not_restart_the_ninety_second_budget(self):
        owner, factory = self.owner()
        now = [time.perf_counter()]
        start = now[0]
        acquire = self.controller.acquire_tool
        async def delayed_grant(*args, **kwargs):
            grant = await acquire(*args, **kwargs)
            now[0] += 91
            return grant
        with patch.object(self.controller, 'acquire_tool', delayed_grant):
            result = await run_recipe(self.controller, self.recipe, task_deadline=start + 900,
                clock=lambda: now[0], _owner_factory=factory)
        self.assertEqual(result['deadline'], start + 90)
        self.assertEqual(result['status'], 'timed_out')
        self.assertEqual(owner.records, [])
        self.assertTrue(owner.closed)
        self.assertIsNone(self.controller.tool)

    async def test_short_original_deadline_is_retained_and_expired_task_refused(self):
        with self.assertRaisesRegex(ValueError, 'original execution deadline'):
            await run_recipe(self.controller, self.recipe, task_deadline=time.perf_counter() - 1)
        self.assertFalse(self.recipe.run.exists())
        self.assertIsNone(self.controller.tool)
        original = time.perf_counter() + 20
        owner, factory = self.owner()
        result = await run_recipe(self.controller, self.recipe, task_deadline=original, _owner_factory=factory)
        self.assertTrue(result['passed'])
        self.assertEqual(result['deadline'], original)

    async def test_foreground_interruption_joins_before_releasing_and_stops_next_stage(self):
        owner, factory = self.owner(interrupt=True)
        result = await run_recipe(self.controller, self.recipe,
            task_deadline=time.perf_counter() + 30, _owner_factory=factory)
        self.assertEqual(result['status'], 'interrupted')
        self.assertFalse(result['passed'])
        self.assertEqual(len(owner.records), 1)
        self.assertTrue(owner.closed and result['owned_processes_exited'])
        self.assertIsNone(self.controller.tool)

    async def test_cancellation_joins_and_saves_receipt_before_propagating(self):
        owner, factory = self.owner()
        async def held(*args, **kwargs):
            owner.started.set()
            await asyncio.Event().wait()
        owner.run = held
        work = asyncio.create_task(run_recipe(self.controller, self.recipe,
            task_deadline=time.perf_counter() + 30, _owner_factory=factory))
        await asyncio.wait_for(owner.started.wait(), 5)
        work.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await work
        result = json.loads((self.recipe.run / 'receipt.json').read_text())
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['passed'])
        self.assertTrue(owner.closed and result['owned_processes_exited'])
        self.assertIsNone(self.controller.tool)

    async def test_unconfirmed_cleanup_keeps_grant_and_owner_for_host_recovery(self):
        owner, factory = self.owner(bad_cleanup=True)
        with self.assertRaises(RecipeCleanupError) as caught:
            await run_recipe(self.controller, self.recipe,
                task_deadline=time.perf_counter() + 30, _owner_factory=factory)
        self.assertIs(caught.exception.owner, owner)
        self.assertEqual(caught.exception.receipt['status'], 'cleanup_unconfirmed')
        self.assertFalse(caught.exception.receipt['passed'])
        self.assertFalse(caught.exception.receipt['owned_processes_exited'])
        self.assertEqual(self.controller.fault, 'tool_exit_unconfirmed')
        self.assertIsNotNone(self.controller.tool)
        self.assertFalse(self.controller())
