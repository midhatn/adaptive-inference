"""Ordinary authoring sources stay separate from the historical runtime view."""
import ast
import hashlib
from pathlib import Path
import unittest
from unittest import mock

import continuation_timeout_lineage as lineage
import task_file_alias_lineage as aliases
from paused_expiry_lineage import fingerprint


class TaskPreparationLineageTests(unittest.TestCase):
    def test_exact_addition_and_cli_project_to_existing_sixty_module_record(self):
        rows = lineage.preparation_record()
        self.assertEqual(rows['schema'], 'adaptive.task-preparation.source-lineage.v1')
        record_path = lineage.ROOT / lineage.ARCHIVE / 'source-lineage.json'
        self.assertEqual(rows['baseline_runtime_record'], record_path.relative_to(lineage.ROOT).as_posix())
        self.assertEqual(hashlib.sha256(record_path.read_bytes()).hexdigest(), rows['baseline_runtime_record_sha256'])
        current = lineage.preparation_runtime_view()
        self.assertEqual(len(current), 60)
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in current.items()},
                         lineage.record()['unchanged_runtime'])
        self.assertEqual(len(aliases.runtime_view()), 60)

    def test_reader_changes_reverse_exactly_and_unknown_bytes_are_not_projected(self):
        rows = lineage.preparation_record()
        self.assertEqual(set(rows['files']), {'src/adaptive_inference/cli.py',
            'tests/continuation_timeout_lineage.py', 'tests/task_file_alias_lineage.py',
            'tests/test_admission_activity_lineage.py', 'tests/test_continuation_timeout_lineage.py',
            'tests/test_safe_wait_lineage.py', 'tests/test_pause_observation_lineage.py'})
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                current = (lineage.ROOT / relative).read_bytes()
                self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
                before = lineage.preparation_predecessor(relative, current)
                self.assertEqual(hashlib.sha256(before).hexdigest(), row['predecessor_sha256'])
                self.assertEqual(fingerprint(ast.parse(before)), row['predecessor_ast_sha256'])
                unknown = current + b'\n# unreviewed\n'
                self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)

    def test_changed_authoring_bytes_fail_and_unknown_modules_reach_original_check(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        original_read = Path.read_bytes
        for name in ('cli.py', 'task_prepare.py'):
            target = runtime / name
            def read(path):
                raw = original_read(path)
                return raw + b'\n# unreviewed\n' if path == target else raw
            with self.subTest(name=name), mock.patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(AssertionError, 'runtime source'):
                    aliases.runtime_view()
        original_view = lineage.preparation_runtime_view
        def extra(root=None):
            return {**original_view(root), 'unreviewed.py': b'pass\n'}
        with mock.patch.object(lineage, 'preparation_runtime_view', extra):
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):
                aliases.runtime_view()


if __name__ == '__main__':
    unittest.main()
