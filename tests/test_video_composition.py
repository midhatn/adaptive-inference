"""Selected video launch authority with inert bindings; no native execution."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from adaptive_inference.desktop.composition import DesktopComposition
from adaptive_inference.task_spec import TaskSpec
from test_video_task_spec import video_data


class VideoLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.c = object.__new__(DesktopComposition)
        self.c.compiler_host = SimpleNamespace(lifecycle=lambda: {'bound': True}); self.c.compiler_bindings = {}; self.c.compiler_kind = 'video'
        self.c.host_epoch = 'host-1'; self.c.host = SimpleNamespace(gateway=SimpleNamespace(instance='gateway-1'))
        spec = TaskSpec(video_data())
        self.plan = {'task_spec': spec.data, 'task_spec_sha256': spec.sha256}

    def test_video_binding_is_private_and_cannot_renew_original_deadline(self):
        args = self.c.compiler_launch_args(self.root, self.plan, execution_id='task', task_id='task',
                                          deadline=900., diagnostics=self.root)
        path = Path(args[1]); raw = path.read_bytes(); binding = json.loads(raw)
        self.assertEqual(binding['schema'], 'adaptive.video-worker-binding.v1')
        self.assertEqual(binding['task_deadline'], 900.)
        self.assertEqual(args[3], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(binding['capability'], args)
        with self.assertRaises(RuntimeError):
            self.c.compiler_launch_args(self.root, self.plan, execution_id='task', task_id='task',
                                        deadline=1800., diagnostics=self.root)
        self.assertEqual(path.read_bytes(), raw)

    def test_video_task_cannot_select_compiler_deployment(self):
        self.c.compiler_kind = 'compiler'
        with self.assertRaisesRegex(RuntimeError, 'configured useful-tool deployment'):
            self.c.compiler_launch_args(self.root, self.plan, execution_id='task', task_id='task',
                                        deadline=900., diagnostics=self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_file_only_task_does_not_get_video_binding(self):
        self.assertEqual(self.c.compiler_launch_args(self.root, {'task_id': 'orders-report'},
            execution_id='task', task_id='task', deadline=900., diagnostics=self.root), [])
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__': unittest.main()
