"""Exact alias source preservation; no installed or model qualification."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import task_file_alias_lineage as lineage
from continuation_diagnostics_lineage import predecessor as diagnostic_predecessor
from paused_expiry_lineage import fingerprint


class TaskFileAliasLineageTests(unittest.TestCase):
    def test_two_changed_files_project_exact_previous_sixty_module_runtime(self):
        rows = lineage.record()
        self.assertEqual(rows['schema'], 'adaptive.task-file-alias.source-lineage.v1')
        self.assertEqual(rows['baseline_revision'], 'febfce7afacb6f3d11cf09d774c1b9b0163b7c30')
        self.assertEqual(rows['baseline_runtime_count'], 60)
        self.assertEqual(set(rows['modules']), {'task_spec.py', 'desktop/hermes/recovery.py'})
        self.assertEqual(len(rows['unchanged_runtime']), 58)
        self.assertEqual(rows['new_modules'], {})
        self.assertEqual(len(rows['historical_json']), 33)
        self.assertEqual(set(rows['preserved_tests']), {
            'tests/task_handover_lineage.py', 'tests/test_task_handover_lineage.py',
            'tests/test_task_spec.py', 'tests/test_continuation_host.py'})
        lineage.preserved_records()
        old = json.loads((lineage.ROOT / 'provenance/task-handover/source-lineage.json').read_bytes())
        expected = {name: row['successor_sha256'] for name, row in old['modules'].items()}
        expected.update({name: row['sha256'] for group in ('unchanged_runtime', 'new_modules')
                         for name, row in old[group].items()})
        view = lineage.runtime_view()
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in view.items()}, expected)
        for relative, row in rows['modules'].items():
            with self.subTest(relative=relative):
                data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
                self.assertEqual(lineage.predecessor(relative, data), view[relative])
                self.assertEqual(lineage.predecessor(relative, view[relative]), view[relative])
                tree = ast.parse(data); original = fingerprint(tree)
                self.assertEqual(fingerprint(lineage.restore_file_aliases(tree, relative)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), original)

    def test_changed_files_refuse_byte_only_and_inside_outside_ast_edits(self):
        for relative in lineage.record()['modules']:
            data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-handover source'):
                    lineage.predecessor(relative, data + b'\n# unreviewed\n')
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_file_aliases(ast.parse(data + b'\nunreviewed = True\n'), relative)
                tree = ast.parse(data)
                function = next(node for node in ast.walk(tree)
                                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
                function.body.insert(0, ast.Return(value=ast.Constant(value=None)))
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_file_aliases(tree, relative)

    def test_wrong_predecessor_paths_and_pins_are_refused(self):
        rows = lineage.record(); relative = next(iter(rows['modules']))
        data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
        for field in ('predecessor_sha256', 'predecessor_ast_sha256', 'predecessor_source'):
            changed = deepcopy(rows); changed['modules'][relative][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(lineage, 'record', return_value=changed):
                with self.assertRaisesRegex(AssertionError, 'task-file-alias predecessor'):
                    lineage.predecessor(relative, data)

    def test_complete_runtime_refuses_extra_missing_and_changed_source_groups(self):
        rows = lineage.record()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = list((lineage.ROOT / 'src/adaptive_inference').rglob('*.py'))
            sources += [lineage.ROOT / row['predecessor_source'] for row in rows['modules'].values()]
            sources.append(lineage.ROOT / lineage.ARCHIVE_RELATIVE / 'source-lineage.json')
            sources += lineage.observation_inputs()
            for source in sources:
                target = root / source.relative_to(lineage.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
            lineage.runtime_view(root)
            extra = root / 'src/adaptive_inference/unreviewed.py'; extra.write_text('pass\n')
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):lineage.runtime_view(root)
            extra.unlink()
            for group in ('modules', 'unchanged_runtime'):
                relative = next(iter(rows[group])); target = root / 'src/adaptive_inference' / relative
                before = target.read_bytes(); target.write_bytes(before + b'\n# unreviewed\n')
                with self.subTest(group=group), self.assertRaisesRegex(AssertionError, 'runtime source'):
                    lineage.runtime_view(root)
                target.write_bytes(before)
            target.unlink()
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):lineage.runtime_view(root)

    def test_historical_json_and_preserved_test_edits_are_refused(self):
        rows = lineage.record()
        for group, message in (('historical_json', 'historical task-file-alias input'),
                               ('preserved_tests', 'retained task-file-alias test bytes')):
            changed = deepcopy(rows); relative = next(iter(rows[group]))
            if group == 'historical_json':changed[group][relative] = '0' * 64
            else:changed[group][relative]['sha256'] = '0' * 64
            with self.subTest(group=group), mock.patch.object(lineage, 'record', return_value=changed):
                with self.assertRaisesRegex(AssertionError, message):lineage.preserved_records()

    def test_overlapping_runtime_groups_are_refused(self):
        rows = lineage.record(); relative, value = next(iter(rows['unchanged_runtime'].items()))
        rows['new_modules'][relative] = value
        with mock.patch.object(lineage, 'record', return_value=rows):
            with self.assertRaisesRegex(AssertionError, 'Overlapping'):lineage.runtime_view()

    def test_separate_ci_fixture_only_adds_fence_and_pinned_regression(self):
        rows = lineage.record()['test_only_deltas']
        self.assertEqual(set(rows), {'tests/test_continuation_host.py'})
        relative, row = next(iter(rows.items()))
        old = (lineage.ROOT / row['predecessor_source']).read_bytes()
        current = (lineage.ROOT / relative).read_bytes()
        current = diagnostic_predecessor(current)
        self.assertEqual(hashlib.sha256(old).hexdigest(), row['predecessor_sha256'])
        self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
        tree = ast.parse(current)
        added = row['added_test']
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == added['class'])
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == added['method'])
        self.assertEqual(fingerprint(method), added['ast_sha256'])
        cls.body.remove(method)
        host = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HostTests')
        cleanup = next(n for n in host.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'asyncTearDown')
        self.assertEqual(fingerprint(cleanup.body.pop(0)),
                         fingerprint(ast.parse('self.c.runtime.fence_admission()').body[0]))
        self.assertEqual(fingerprint(tree), row['predecessor_ast_sha256'])
        self.assertEqual(fingerprint(tree), fingerprint(ast.parse(old)))


if __name__ == '__main__':
    unittest.main()
