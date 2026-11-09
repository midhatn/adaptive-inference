"""Task acceptance checks; normalized receipts below are fixtures, not video evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from adaptive_inference.task_spec import (
    TaskSpec, BUDGET, VIDEO_SCHEMA, VIDEO_RECIPE, VIDEO_MEDIA, canonical, digest,
)
from task_spec_support import spec_data


def video_data():
    value = spec_data(inputs={}, outputs=[], prompt='Create a checked calibration video.')
    value.update(schema=VIDEO_SCHEMA, video={'recipe_id': VIDEO_RECIPE, 'max_runs': 2})
    return value


def receipt(spec, *, operation='operation-1', call='call-1', status='passed'):
    value = {'operation_id': operation, 'tool_call_id': call, 'spec_sha256': spec.sha256,
             'recipe_id': VIDEO_RECIPE, 'status': status, 'owned_processes_exited': True}
    if status == 'passed':
        value.update(artifact_sha256=digest(b'fixture clip'), probe_sha256=digest(b'fixture probe'),
                     media=dict(VIDEO_MEDIA))
    return value


class VideoTaskSpecTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.spec = TaskSpec(video_data())

    def test_explicit_immutable_contract_preserves_original_budget_and_prompt(self):
        data = video_data()
        data['prompt'] = '  Original objective.\n'
        spec = TaskSpec(data)
        identity = spec.sha256
        data['video']['max_runs'] = 1
        spec.video['recipe_id'] = 'changed'
        self.assertEqual(spec.sha256, identity)
        self.assertEqual(spec.data['budget'], BUDGET)
        self.assertEqual(spec.prompt, '  Original objective.\n')
        self.assertEqual(TaskSpec.from_metadata(spec.metadata()), spec)
        self.assertEqual(TaskSpec.from_bytes(canonical(spec.data)), spec)
        self.assertIsNone(spec.compiler)

    def test_fixed_recipe_cannot_grant_shell_paths_or_other_recipes(self):
        for extra in ({'recipe_id': 'other'}, {'max_runs': 3}, {'max_runs': True},
                      {'command': 'ffmpeg'}, {'output': 'custom.mp4'}):
            data = video_data(); data['video'].update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                TaskSpec(data)
        for args in ({}, {'recipe_id': 'other'}, {'recipe_id': VIDEO_RECIPE, 'output': 'x'},
                     {'recipe_id': VIDEO_RECIPE, 'encoder': 'libx264'}):
            self.assertFalse(self.spec.validate_video_args(args).accepted)
        self.assertTrue(self.spec.validate_video_args({'recipe_id': VIDEO_RECIPE}).accepted)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_model_claim_cannot_replace_successful_joined_clip_receipt(self):
        for records in (None, [], [receipt(self.spec, status='failed')]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.spec.completion(self.work, [], 'The video is ready.', video_receipts=records)
        failed = receipt(self.spec, status='failed')
        passed = receipt(self.spec, operation='operation-2', call='call-2')
        result = self.spec.completion(self.work, [], 'The clip was checked.', video_receipts=[failed, passed])
        self.assertTrue(result['video']['qualified'])
        self.assertEqual(result['video']['attempts'], 2)
        self.assertEqual(result['video']['successful']['artifact_sha256'], passed['artifact_sha256'])
        self.assertFalse(self.spec.validate_video_args({'recipe_id': VIDEO_RECIPE}, completed_runs=2).accepted)

    def test_completion_requires_original_identity_exact_media_and_unique_effects(self):
        good = receipt(self.spec)
        for key, value in (('owned_processes_exited', False), ('status', 'unknown'),
                           ('spec_sha256', '0' * 64), ('artifact_sha256', 'bad'),
                           ('probe_sha256', 'bad'), ('media', {**VIDEO_MEDIA, 'frames': 89}),
                           ('media', {**VIDEO_MEDIA, 'width': 1280.0})):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.spec.video_completion([{**good, key: value}])
        with self.assertRaises(ValueError): self.spec.video_completion([good, deepcopy(good)])

    def test_old_tasks_cannot_gain_video_authority_and_v3_cannot_mix_tool_contracts(self):
        old = TaskSpec(spec_data(inputs={}, outputs=[]))
        self.assertIsNone(old.video)
        self.assertFalse(old.validate_video_args({'recipe_id': VIDEO_RECIPE}).accepted)
        with self.assertRaises(ValueError):
            old.completion(self.work, [], 'done', video_receipts=[])
        data = video_data(); data['compiler'] = {}
        with self.assertRaises(ValueError): TaskSpec(data)
        data = video_data(); data['budget']['execution_seconds'] = 901
        with self.assertRaises(ValueError): TaskSpec(data)

    def test_public_example_requires_checked_video_under_original_limits(self):
        path = Path(__file__).resolve().parents[1] / 'examples/tasks/video-testclip/task.json'
        spec = TaskSpec.from_bytes(path.read_bytes())
        self.assertEqual(spec.video, {'recipe_id': VIDEO_RECIPE, 'max_runs': 2})
        self.assertEqual(spec.data['budget'], BUDGET)
        with self.assertRaises(ValueError): spec.completion(self.work, [], 'done', video_receipts=[])


if __name__ == '__main__':
    unittest.main()
