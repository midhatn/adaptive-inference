"""Ordinary authoring sources stay separate from the historical runtime view."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
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
                current = lineage.fixture_stop_predecessor(relative, current)
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
                data = lineage.integration_predecessor(relative, data, 'reopen')
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


class FixtureStopVerificationLineageTests(unittest.TestCase):
    def test_exact_four_file_view_preserves_original_records(self):
        rows = lineage.fixture_stop_record()
        self.assertEqual(rows['schema'], 'adaptive.fixture-stop-verification.source-lineage.v1')
        self.assertEqual(rows['runtime_changes'], [])
        self.assertEqual(set(rows['files']), lineage.FIXTURE_STOP_INPUTS)
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                current = (lineage.ROOT / relative).read_bytes()
                current = lineage.integration_predecessor(relative, current, 'fixture_stop')
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
                self.assertEqual(fingerprint(ast.parse(current)), row['successor_ast_sha256'])
                self.assertEqual(lineage.fixture_stop_predecessor(relative, current), before)
                self.assertEqual(lineage.fixture_stop_predecessor(relative, before), before)
        for relative, expected in rows['preserved_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_unknown_bytes_and_legacy_roots_are_not_projected(self):
        for relative in lineage.FIXTURE_STOP_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            unknown = current + b'\n# unreviewed fixture change\n'
            with self.subTest(relative=relative):
                self.assertEqual(lineage.fixture_stop_predecessor(relative, unknown), unknown)
                self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)
                with tempfile.TemporaryDirectory() as directory:
                    self.assertEqual(lineage.preparation_predecessor(relative, current, Path(directory)), current)

    def test_predecessor_and_successor_ast_tampering_is_refused(self):
        rows = lineage.fixture_stop_record()
        for relative in lineage.FIXTURE_STOP_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256',
                          'successor_ast_sha256'):
                changed = deepcopy(rows); changed['files'][relative][field] = '0' * 64
                with self.subTest(relative=relative, field=field), mock.patch.object(
                        lineage, 'fixture_stop_record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'fixture Stop verification'):
                        lineage.fixture_stop_predecessor(relative, current)


class IntegratedReaderLineageTests(unittest.TestCase):
    def test_both_exact_branch_views_and_original_manifests_are_preserved(self):
        rows = lineage.integration_record()
        self.assertEqual(rows['schema'], 'adaptive.installed-reopen.fixture-stop-integration.v1')
        self.assertEqual(set(rows['files']), lineage.INTEGRATION_INPUTS)
        self.assertEqual(rows['runtime_changes'], [])
        records = {'reopen': lineage.reopen_record(), 'fixture_stop': lineage.fixture_stop_record()}
        for relative, row in rows['files'].items():
            current = (lineage.ROOT / relative).read_bytes()
            current = lineage.handover_predecessor(relative, current)
            self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
            self.assertEqual(fingerprint(ast.parse(current)), row['successor_ast_sha256'])
            for view, original in records.items():
                with self.subTest(relative=relative, view=view):
                    retained = lineage.integration_predecessor(relative, current, view)
                    self.assertEqual(hashlib.sha256(retained).hexdigest(),
                                     original['files'][relative]['successor_sha256'])
                    self.assertEqual(fingerprint(ast.parse(retained)),
                                     original['files'][relative]['successor_ast_sha256'])
                    self.assertEqual(lineage.integration_predecessor(relative, retained, view), retained)
        for relative, expected in rows['preserved_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_unknown_reader_bytes_and_legacy_roots_are_not_projected(self):
        for relative in lineage.INTEGRATION_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            unknown = current + b'\n# unreviewed integrated reader\n'
            for view in ('reopen', 'fixture_stop'):
                with self.subTest(relative=relative, view=view):
                    self.assertEqual(lineage.integration_predecessor(relative, unknown, view), unknown)
                    with tempfile.TemporaryDirectory() as directory:
                        self.assertEqual(lineage.integration_predecessor(
                            relative, current, view, Path(directory)), current)
            self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)

    def test_retained_identity_and_successor_ast_changes_are_refused(self):
        rows = lineage.integration_record()
        for relative in lineage.INTEGRATION_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            for view in ('reopen', 'fixture_stop'):
                for field in ('source', 'sha256', 'ast_sha256', 'successor_ast_sha256'):
                    changed = deepcopy(rows)
                    target = changed['files'][relative]
                    if field != 'successor_ast_sha256':
                        target = target['views'][view]
                    target[field] = '0' * 64
                    with self.subTest(relative=relative, view=view, field=field), mock.patch.object(
                            lineage, 'integration_record', return_value=changed):
                        with self.assertRaisesRegex(AssertionError, 'integrated reader'):
                            lineage.integration_predecessor(relative, current, view)


class HandoverReopenLineageTests(unittest.TestCase):
    def test_exact_four_file_delta_preserves_base_and_original_manifests(self):
        rows = lineage.handover_record()
        self.assertEqual(rows['schema'], 'adaptive.installed-reopen.handover-tasks.v1')
        self.assertEqual(rows['predecessor_revision'], 'c6f20623579021d78cecdd6af8229bbdf2d6ef46')
        self.assertEqual(rows['runtime_changes'], list(lineage.HANDOVER_RUNTIME))
        self.assertEqual(set(rows['files']), lineage.HANDOVER_INPUTS)
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                current = (lineage.ROOT / relative).read_bytes()
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
                self.assertEqual(fingerprint(ast.parse(current)), row['successor_ast_sha256'])
                self.assertEqual(hashlib.sha256(before).hexdigest(), row['predecessor_sha256'])
                self.assertEqual(fingerprint(ast.parse(before)), row['predecessor_ast_sha256'])
                self.assertEqual(lineage.handover_predecessor(relative, current), before)
                self.assertEqual(lineage.handover_predecessor(relative, before), before)
        for relative, expected in rows['preserved_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), expected)
        self.assertTrue(set(lineage.handover_inputs()).issubset(lineage.preparation_inputs()))

    def test_unknown_bytes_and_legacy_roots_reach_existing_checks(self):
        for relative in lineage.HANDOVER_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            unknown = current + b'\n# unreviewed handover reopening\n'
            with self.subTest(relative=relative):
                self.assertEqual(lineage.handover_predecessor(relative, unknown), unknown)
                self.assertEqual(lineage.preparation_predecessor(relative, unknown), unknown)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.assertEqual(lineage.handover_predecessor(relative, current, root), current)
                    self.assertEqual(lineage.preparation_predecessor(relative, current, root), current)
                    self.assertEqual(lineage.handover_inputs(root), [])

    def test_both_runtime_modules_project_before_saved_tasks_is_removed(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        current = {p.relative_to(runtime).as_posix(): p.read_bytes() for p in runtime.rglob('*.py')}
        before = dict(current)
        view = lineage.handover_runtime_view(current)
        self.assertEqual(current, before)
        self.assertEqual(set(view), set(current))
        for name in current:
            expected = (lineage.handover_predecessor('src/adaptive_inference/' + name, current[name])
                        if name in lineage.HANDOVER_RUNTIME else current[name])
            self.assertEqual(view[name], expected)
        self.assertEqual(len(lineage.reopen_runtime_view(current)), 61)
        self.assertEqual({name: hashlib.sha256(data).hexdigest()
                          for name, data in lineage.preparation_runtime_view().items()},
                         lineage.record()['unchanged_runtime'])
        original_read = Path.read_bytes
        for name in lineage.HANDOVER_RUNTIME:
            target = runtime / name
            def read(path):
                data = original_read(path)
                return data + b'\n# unreviewed handover source\n' if path == target else data
            with self.subTest(name=name), mock.patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(AssertionError, 'runtime source'):
                    aliases.runtime_view()
        original_view = lineage.handover_runtime_view
        def extra(current, root=None):
            return {**original_view(current, root), 'unreviewed.py': b'pass\n'}
        with mock.patch.object(lineage, 'handover_runtime_view', extra):
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):
                aliases.runtime_view()

    def test_ast_projection_requires_complete_current_bytes_and_preserves_unknown_syntax(self):
        original_read = Path.read_bytes
        for name in lineage.HANDOVER_RUNTIME:
            relative = 'src/adaptive_inference/' + name
            target = lineage.ROOT / relative
            data = target.read_bytes()
            row = lineage.handover_record()['files'][relative]
            tree = ast.parse(data)
            original = fingerprint(tree)
            with self.subTest(name=name):
                self.assertEqual(fingerprint(lineage.restore_preparation(tree, name)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), original)
                unknown = ast.parse(data + b'\nunreviewed = True\n')
                self.assertEqual(fingerprint(lineage.restore_preparation(unknown, name)), fingerprint(unknown))
                def read(path):
                    raw = original_read(path)
                    return raw + b'\n# same AST, unknown bytes\n' if path == target else raw
                with mock.patch.object(Path, 'read_bytes', read):
                    with self.assertRaisesRegex(AssertionError, 'complete handover-reopen source'):
                        lineage.restore_preparation(tree, name)

    def test_predecessor_and_successor_ast_tampering_is_refused(self):
        rows = lineage.handover_record()
        for relative in lineage.HANDOVER_INPUTS:
            current = (lineage.ROOT / relative).read_bytes()
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256',
                          'successor_ast_sha256'):
                changed = deepcopy(rows)
                changed['files'][relative][field] = '0' * 64
                with self.subTest(relative=relative, field=field), mock.patch.object(
                        lineage, 'handover_record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'handover-reopen'):
                        lineage.handover_predecessor(relative, current)


if __name__ == '__main__':
    unittest.main()
