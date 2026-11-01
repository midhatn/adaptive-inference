"""Ordinary authoring sources stay separate from the historical runtime view."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest import mock

import continuation_timeout_lineage as lineage
import task_file_alias_lineage as aliases
from paused_expiry_lineage import fingerprint


class TaskPreparationLineageTests(unittest.TestCase):
    def test_exact_addition_cli_and_version_project_to_existing_sixty_module_record(self):
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
            'src/adaptive_inference/__init__.py',
            'tests/continuation_timeout_lineage.py', 'tests/task_file_alias_lineage.py',
            'tests/test_admission_activity_lineage.py', 'tests/test_continuation_timeout_lineage.py',
            'tests/test_safe_wait_lineage.py', 'tests/test_pause_observation_lineage.py',
            'tests/test_continuation_host.py'})
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                current = (lineage.ROOT / relative).read_bytes()
                current = lineage.reopen_predecessor(relative, current)
                self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
                before = lineage.preparation_predecessor(relative, current)
                self.assertEqual(hashlib.sha256(before).hexdigest(), row['predecessor_sha256'])
                self.assertEqual(fingerprint(ast.parse(before)), row['predecessor_ast_sha256'])
                unknown = current + b'\n# unreviewed\n'
                self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)

    def test_changed_authoring_bytes_fail_and_unknown_modules_reach_original_check(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        original_read = Path.read_bytes
        for name in ('cli.py', 'task_prepare.py', '__init__.py'):
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

    def test_version_ast_projection_preserves_exact_original_assignment(self):
        relative = 'src/adaptive_inference/__init__.py'
        current = (lineage.ROOT / relative).read_bytes()
        row = lineage.preparation_record()['files'][relative]
        self.assertEqual(row['replacements'], [{
            'old': '__version__ = "0.3.0"', 'new': '__version__ = "0.4.0a1"', 'count': 1}])
        before = lineage.preparation_predecessor(relative, current)
        self.assertEqual(hashlib.sha256(before).hexdigest(),
                         lineage.record()['unchanged_runtime']['__init__.py'])
        self.assertEqual(fingerprint(lineage.restore_preparation(ast.parse(current), '__init__.py')),
                         fingerprint(ast.parse(before)))
        unknown = current.replace(b'"0.4.0a1"', b'"0.4.0a2"')
        self.assertNotEqual(current, unknown)
        self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)
        self.assertEqual(fingerprint(lineage.restore_preparation(ast.parse(unknown), '__init__.py')),
                         fingerprint(ast.parse(unknown)))


class InstalledReopenLineageTests(unittest.TestCase):
    def test_declared_sources_recover_exact_base_without_changing_preparation_record(self):
        rows = lineage.reopen_record()
        self.assertEqual(rows['schema'], 'adaptive.installed-reopen.source-lineage.v1')
        self.assertEqual(set(rows['files']), {
            'src/adaptive_inference/desktop/composition.py',
            'src/adaptive_inference/desktop/hermes/run_recovery.py',
            'tests/continuation_timeout_lineage.py', 'tests/test_task_preparation_lineage.py',
            'tests/test_safe_wait_lineage.py'})
        self.assertEqual(rows['addition']['source'], 'src/adaptive_inference/desktop/saved_tasks.py')
        original_record = lineage.ROOT / lineage.PREPARATION / 'source-lineage.json'
        self.assertEqual(hashlib.sha256(original_record.read_bytes()).hexdigest(),
                         rows['preserved_preparation_record_sha256'])
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                data = (lineage.ROOT / relative).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
                self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                self.assertEqual(lineage.reopen_predecessor(relative, data), before)
                self.assertEqual(lineage.reopen_predecessor(relative, before), before)
                self.assertEqual(lineage.reopen_predecessor(relative, data + b'\n# unreviewed\n'),
                                 data + b'\n# unreviewed\n')
        runtime = lineage.ROOT / 'src/adaptive_inference'
        current = {p.relative_to(runtime).as_posix(): p.read_bytes() for p in runtime.rglob('*.py')}
        self.assertEqual(len(current), 62)
        self.assertEqual(len(lineage.reopen_runtime_view(current)), 61)
        self.assertEqual({name: hashlib.sha256(data).hexdigest()
                          for name, data in lineage.preparation_runtime_view().items()},
                         lineage.record()['unchanged_runtime'])

    def test_added_and_changed_runtime_bytes_cannot_hide_from_original_checks(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        original_read = Path.read_bytes
        for name in (*lineage.REOPEN_RUNTIME, lineage.REOPEN_ADDITION):
            target = runtime / name
            def read(path):
                data = original_read(path)
                return data + b'\n# unreviewed\n' if path == target else data
            with self.subTest(name=name), mock.patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(AssertionError, 'runtime source'):
                    aliases.runtime_view()

    def test_ast_projection_is_exact_and_does_not_accept_unknown_syntax(self):
        for name in lineage.REOPEN_RUNTIME:
            relative = 'src/adaptive_inference/' + name
            data = (lineage.ROOT / relative).read_bytes()
            row = lineage.reopen_record()['files'][relative]
            tree = ast.parse(data)
            original = fingerprint(tree)
            with self.subTest(name=name):
                self.assertEqual(fingerprint(lineage.restore_reopen(tree, name)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), original)
                unknown = ast.parse(data + b'\nunreviewed = True\n')
                self.assertEqual(fingerprint(lineage.restore_reopen(unknown, name)), fingerprint(unknown))
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    aliases.restore_file_aliases(unknown, name)

    def test_retained_source_path_and_identity_changes_are_refused(self):
        original = lineage.reopen_record()
        for relative in original['files']:
            current = (lineage.ROOT / relative).read_bytes()
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
                changed = deepcopy(original)
                changed['files'][relative][field] = '0' * 64
                with self.subTest(relative=relative, field=field), mock.patch.object(
                        lineage, 'reopen_record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'installed-reopen predecessor'):
                        lineage.reopen_predecessor(relative, current)


if __name__ == '__main__':
    unittest.main()
