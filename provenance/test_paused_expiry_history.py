# SPDX-License-Identifier: Apache-2.0
"""Keep historical evidence independent of later source and runner failures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
SUPPORT = REPOSITORY / 'provenance/paused-budget-expiry/historical-view'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HistoricalIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adaptive-history-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repository = self.root / 'source'
        self.builder = load(SUPPORT / 'historical_view.py', 'history_builder_under_test')
        plan = self.builder.load_plan(REPOSITORY)
        names = {row['source'] for row in plan['entries']}
        names.update(('provenance/reconstruct.py',
                      'provenance/paused-budget-expiry/acceptance/reviewed-source.json'))
        for name in names:
            target = self.repository / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / name, target)
        self.plan = self.builder.load_plan(self.repository)

    def test_complete_view_does_not_read_changed_current_runtime(self):
        current = self.repository / 'src/adaptive_inference/execution_clock.py'
        current.parent.mkdir(parents=True)
        current.write_bytes(b'# a future runtime is deliberately different\n')
        view = self.root / 'view'
        result = self.builder.build_view(self.repository, view)
        self.assertEqual((result['files'], result['bytes']), (123, 1594016))
        self.assertNotEqual(current.read_bytes(), (view / current.relative_to(self.repository)).read_bytes())
        self.assertEqual(set(result['source_sha256']), {row['path'] for row in self.plan['entries']})

    def test_missing_snapshot_never_falls_back_to_identical_current_file(self):
        row = next(row for row in self.plan['entries'] if row['path'].endswith('/execution_clock.py'))
        current = self.repository / row['path']
        current.parent.mkdir(parents=True)
        shutil.copyfile(self.repository / row['source'], current)
        (self.repository / row['source']).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.builder.build_view(self.repository, self.root / 'view')
        self.assertFalse((self.root / 'view').exists())

    def test_changed_snapshot_is_refused(self):
        path = self.repository / self.plan['entries'][0]['source']
        path.write_bytes(path.read_bytes() + b'\nchanged\n')
        with self.assertRaises(ValueError):
            self.builder.build_view(self.repository, self.root / 'view')

    def test_mapping_must_cover_every_frozen_input_even_with_updated_map_hash(self):
        local = self.root / 'builder'
        local.mkdir()
        shutil.copyfile(SUPPORT / 'historical_view.py', local / 'historical_view.py')
        mapping = json.loads((SUPPORT / 'source-map.json').read_bytes())
        mapping['mappings'].pop(next(iter(mapping['mappings'])))
        raw = json.dumps(mapping).encode()
        (local / 'source-map.json').write_bytes(raw)
        other = load(local / 'historical_view.py', 'incomplete_map_under_test')
        with patch.object(other, 'MAP_SHA', hashlib.sha256(raw).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'complete frozen closure'):
                other.build_view(self.repository, self.root / 'view')

    def test_replacement_directory_is_not_deleted(self):
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            with self.builder.historical_view(self.repository, self.root) as view:
                original = view.parent
                retained = self.root / 'retained-original'
                # Both absolute paths are this test's owned direct children.
                self.assertEqual(original.parent, self.root)
                self.assertFalse(retained.exists())
                before = original.stat()
                original.rename(retained)
                original.mkdir()
                after = original.stat()
                self.assertNotEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
                sentinel = original / 'keep.txt'
                sentinel.write_bytes(b'keep this replacement')
        self.assertEqual(sentinel.read_bytes(), b'keep this replacement')
        self.assertTrue((retained / 'repository').is_dir())


class HistoricalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adaptive-history-runner-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runner = load(SUPPORT / 'run_historical.py', 'historical_runner_under_test')
        self.observed_view = None

    def child(self, command, **options):
        self.observed_view = Path(options['env']['ADAPTIVE_EVIDENCE_REPOSITORY'])
        self.assertTrue(self.observed_view.is_dir())
        self.assertEqual(options['env']['PYTHONDONTWRITEBYTECODE'], '1')
        self.assertEqual(command[1], '-B')
        return subprocess.CompletedProcess(command, 17, '', 'retained failure output')

    def test_view_lives_until_child_exit_and_failure_output_survives(self):
        with patch.object(self.runner.subprocess, 'run', side_effect=self.child):
            result = self.runner.run(REPOSITORY, temp_parent=self.root)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stderr, 'retained failure output')
        self.assertFalse(self.observed_view.exists())

    def test_default_system_temporary_alias_is_resolved_before_strict_builder(self):
        nested = self.root / 'system-temp-alias'
        nested.mkdir()
        alias = str(nested / '..')
        with patch.object(self.runner.tempfile, 'gettempdir', return_value=alias):
            with patch.object(self.runner.subprocess, 'run', side_effect=self.child):
                result = self.runner.run(REPOSITORY)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.observed_view.parent.parent, self.root)
        self.assertFalse(self.observed_view.exists())

    def test_child_timeout_is_propagated_after_context_cleanup(self):
        def timeout(command, **options):
            self.child(command, **options)
            raise subprocess.TimeoutExpired(command, options['timeout'])
        with patch.object(self.runner.subprocess, 'run', side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.runner.run(REPOSITORY, temp_parent=self.root)
        self.assertFalse(self.observed_view.exists())

    def test_export_must_reproduce_exact_published_bytes(self):
        selection, output = self.root / 'selection.json', self.root / 'output'
        selection.write_bytes(b'{}')
        def changed_result(command, **options):
            self.observed_view = Path(command[command.index('--repository') + 1])
            self.assertTrue(self.observed_view.is_dir())
            output.mkdir()
            (output / 'result.json').write_bytes(b'changed')
            (output / 'manifest.json').write_bytes(b'changed')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(self.runner.subprocess, 'run', side_effect=changed_result):
            with self.assertRaisesRegex(ValueError, 'evidence differs'):
                self.runner.run(REPOSITORY, temp_parent=self.root, selection=selection, output=output)
        self.assertFalse(self.observed_view.exists())
        self.assertEqual((output / 'result.json').read_bytes(), b'changed')


if __name__ == '__main__':
    unittest.main()
