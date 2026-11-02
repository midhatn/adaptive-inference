"""Saved-video and later-task checks using existing real SQLite fixtures."""
import json
from pathlib import Path
import unittest
from unittest import mock

from adaptive_inference.desktop import saved_tasks as saved
from adaptive_inference.task_store import TaskStore
from adaptive_inference.task_spec import TaskSpec
from test_desktop_saved_tasks import BOOT, PACKAGE
from test_video_task_spec import video_data
import test_video_dispatch as dispatch_fixture
import test_task_handover as handover_fixture


class SavedVideoTests(unittest.TestCase):
    def test_saved_video_is_reverified_without_execution_or_mutation(self):
        fixture = dispatch_fixture.VideoRecoveryTests()
        self.addCleanup(fixture.doCleanups)
        create = TaskStore.create

        def contextual_create(store, *args, metadata=None, **kwargs):
            context = saved.bind_context(saved.new_context('a' * 64, PACKAGE, BOOT), store.path.parent)
            return create(store, *args, metadata={**metadata, saved.CONTEXT: context}, **kwargs)

        with mock.patch.object(TaskStore, 'create', contextual_create):
            fixture.setUp()
        f = fixture.fixture
        call, args = fixture.intent()
        result = fixture.dispatch(call, args); f.flush(call, result)
        f.db.append({'role': 'assistant', 'content': 'The checked clip is ready.'})
        f.controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                             'final_response': 'The checked clip is ready.'})
        context = f.owned.checkpoint.metadata[saved.CONTEXT]
        f.release()
        (f.run / 'plan.json').write_text(json.dumps({'task_id': 'task', 'session_id': 'session',
            saved.CONTEXT: context, 'task_spec': f.spec.data, 'pins': {}}), encoding='utf-8')
        before = {p.relative_to(f.run).as_posix(): p.read_bytes() for p in f.run.rglob('*') if p.is_file()}
        with mock.patch.object(TaskStore, 'claim', side_effect=AssertionError('Saved view must not execute')):
            selected = saved.read_saved(f.run)
        self.assertTrue(selected['completed'])
        self.assertEqual(selected['checkpoint'].state['output'], 'The checked clip is ready.')
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(before, {p.relative_to(f.run).as_posix(): p.read_bytes()
                                  for p in f.run.rglob('*') if p.is_file()})
        (f.recipes[0].run / f.recipes[0].artifact).write_bytes(b'changed video')
        with self.assertRaises(ValueError):
            saved.read_saved(f.run)
        self.assertEqual(len(f.calls), 1)


class LaterVideoTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = f = handover_fixture.HandoverTests()
        await f.asyncSetUp()
        for function, args, kwargs in f._cleanups:
            self.addCleanup(function, *args, **kwargs)
        f._cleanups.clear()
        self.addAsyncCleanup(f.asyncTearDown)
        f.new_spec = TaskSpec(video_data())
        f.spec_path.write_text(json.dumps(f.new_spec.data), encoding='utf-8')

    async def test_missing_video_deployment_refuses_before_reservation_or_launch(self):
        f = self.fixture
        with self.assertRaisesRegex(ValueError, 'Video task requires explicit video deployment settings'):
            await f.reserve()
        self.assertEqual(len(f.c.handles), 1)
        self.assertIsNone(f.coordinator.records['new-one']['payload'])

    async def test_configured_video_task_is_reserved_with_original_spec(self):
        f = self.fixture
        f.c.profile.video = object()  # Availability only; this gate does not run tools.
        grant = await f.reserve()
        self.assertEqual(grant['phase'], 'reserved')
        payload = f.coordinator.records['new-one']['payload']
        self.assertEqual(payload['source']['task_spec_sha256'], f.request()['task_spec_sha256'])
        self.assertFalse(Path(payload['run']).exists())
        self.assertEqual(len(f.c.handles), 1)


if __name__ == '__main__': unittest.main()
