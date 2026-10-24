"""Offline integrity of retained storage and accepted M1 source inputs."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


class TaskStoreSourceTests(unittest.TestCase):
    def check_files(self, root, entries):
        for name, entry in entries.items():
            with self.subTest(source=name):
                path = root / name
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                data = path.read_bytes()
                self.assertEqual(len(data), entry['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])

    def test_reviewed_component_and_predecessors_match_retained_manifest(self):
        root = HERE / 'task-store-verification'
        lineage = json.loads((root / 'source-lineage.json').read_text(encoding='utf-8'))
        self.check_files(root, lineage['files'])
        prototype = root / 'reviewed-prototype'
        manifest = prototype / 'source-manifest.json'
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),
                         lineage['prototype_manifest_sha256'])
        self.check_files(prototype, json.loads(manifest.read_text(encoding='utf-8'))['files'])
        self.assertEqual(hashlib.sha256((prototype / 'src/adaptive_inference/task_store.py').read_bytes()).hexdigest(),
                         lineage['runtime_sha256'])

    def test_accepted_m1_runtime_is_retained_with_exact_identity(self):
        root = HERE / 'persistent-desktop'
        manifest = json.loads((root / 'm1-source-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['source_commit'], '124b8ef2430a67e69e0e177f014a6fdc393c16a2')
        self.assertEqual(len(manifest['files']), 18)
        self.check_files(root, manifest['files'])


if __name__ == '__main__':
    unittest.main()
