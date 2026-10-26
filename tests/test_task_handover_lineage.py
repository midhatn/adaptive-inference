"""Source preservation only; current handover behavior has separate tests."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import task_handover_lineage as lineage
from paused_expiry_lineage import fingerprint


class TaskHandoverLineageTests(unittest.TestCase):
    def test_complete_current_runtime_projects_exact_c3_runtime(self):
        rows = lineage.record()
        self.assertEqual(rows['schema'], 'adaptive.task-handover.source-lineage.v1')
        self.assertEqual(rows['baseline_revision'], 'c3f8726712bdd845abab8a9cdf111282d1a5f858')
        self.assertEqual(rows['baseline_runtime_count'], 59)
        lineage.preserved_records()
        self.assertEqual(len(rows['historical_json']), 32)
        prior = json.loads((lineage.ROOT / 'provenance/task-contract/source-lineage.json').read_text())
        expected = {name: row['successor_sha256'] for name, row in prior['modules'].items()}
        expected.update({name: row['sha256'] for key in ('new_modules', 'unchanged_runtime')
                         for name, row in prior[key].items()})
        view = lineage.runtime_view()
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in view.items()}, expected)
        for relative, row in rows['modules'].items():
            with self.subTest(relative=relative):
                data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
                self.assertEqual(lineage.predecessor(relative, data), view[relative])
                self.assertEqual(lineage.predecessor(relative, view[relative]), view[relative])
                tree = ast.parse(data); original = fingerprint(tree)
                self.assertEqual(fingerprint(lineage.restore_task_handover(tree, relative)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), original)

    def test_each_changed_file_rejects_byte_and_inside_outside_ast_edits(self):
        for relative in lineage.record()['modules']:
            data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-handover source'):
                    lineage.predecessor(relative, data + b'\n# unreviewed\n')
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_task_handover(ast.parse(data + b'\nunreviewed = True\n'), relative)
                tree = ast.parse(data)
                function = next(node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
                function.body.insert(0, ast.Return(value=ast.Constant(value=None)))
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_task_handover(tree, relative)

    def test_changed_predecessor_pins_or_paths_are_refused(self):
        rows = lineage.record(); relative = next(iter(rows['modules']))
        data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
        for field in ('predecessor_sha256', 'predecessor_ast_sha256', 'predecessor_source'):
            altered = deepcopy(rows); altered['modules'][relative][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(lineage, 'record', return_value=altered):
                with self.assertRaisesRegex(AssertionError, 'task-handover predecessor'):
                    lineage.predecessor(relative, data)

    def test_whole_closure_rejects_extra_missing_and_each_source_group_edit(self):
        rows = lineage.record()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = list((lineage.ROOT / 'src/adaptive_inference').rglob('*.py'))
            sources += [lineage.ROOT / row['predecessor_source'] for row in rows['modules'].values()]
            sources.append(lineage.ROOT / lineage.ARCHIVE_RELATIVE / 'source-lineage.json')
            # The alias projection needs only its manifest and two exact predecessors.
            import task_file_alias_lineage as aliases
            sources.append(lineage.ROOT / aliases.ARCHIVE_RELATIVE / 'source-lineage.json')
            sources += [lineage.ROOT / row['predecessor_source']
                        for row in aliases.record().get('modules', {}).values()]
            for path in sources:
                target = root / path.relative_to(lineage.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
            lineage.runtime_view(root)
            extra = root / 'src/adaptive_inference/unreviewed.py'; extra.write_text('pass\n')
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):lineage.runtime_view(root)
            extra.unlink()
            for group in ('modules', 'new_modules', 'unchanged_runtime'):
                relative = next(iter(rows[group])); path = root / 'src/adaptive_inference' / relative
                before = path.read_bytes(); path.write_bytes(before + b'\n# unreviewed\n')
                with self.subTest(group=group), self.assertRaisesRegex(AssertionError, 'runtime source'):
                    lineage.runtime_view(root)
                path.write_bytes(before)
            path.unlink()
            with self.assertRaisesRegex(AssertionError, 'runtime closure'):lineage.runtime_view(root)

    def test_original_json_and_preserved_test_edits_are_refused(self):
        rows = lineage.record()
        for group, error in (('historical_json', 'historical task-handover input'),
                             ('preserved_tests', 'retained task-handover test bytes')):
            altered = deepcopy(rows); relative = next(iter(rows[group]))
            if group == 'historical_json':altered[group][relative] = '0' * 64
            else:altered[group][relative]['sha256'] = '0' * 64
            with self.subTest(group=group), mock.patch.object(lineage, 'record', return_value=altered):
                with self.assertRaisesRegex(AssertionError, error):lineage.preserved_records()

    def test_overlapping_runtime_groups_are_refused(self):
        rows = lineage.record(); relative, value = next(iter(rows['unchanged_runtime'].items()))
        rows['new_modules'][relative] = value
        with mock.patch.object(lineage, 'record', return_value=rows):
            with self.assertRaisesRegex(AssertionError, 'Overlapping'):lineage.runtime_view()


if __name__ == '__main__':
    unittest.main()
