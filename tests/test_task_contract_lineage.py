"""Exact current source plus historical projection; not installed qualification."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import task_contract_lineage as lineage
from paused_expiry_lineage import fingerprint


class TaskContractLineageTests(unittest.TestCase):
    def test_complete_current_closure_and_exact_preserved_baseline(self):
        rows = lineage.record()
        self.assertEqual(rows['schema'], 'adaptive.task-contract.source-lineage.v1')
        self.assertEqual(rows['baseline_revision'], '5d2264dfeafe6483dd9d839097811f687fab654c')
        self.assertEqual(rows['baseline_runtime_count'], 57)
        self.assertEqual(set(rows['new_modules']), {'task_spec.py', 'desktop/task_admission.py'})
        view = lineage.runtime_view()
        self.assertEqual(len(view), 57)
        for relative, row in rows['modules'].items():
            with self.subTest(relative=relative):
                self.assertEqual(hashlib.sha256(view[relative]).hexdigest(), row['predecessor_sha256'])
                data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
                self.assertEqual(lineage.predecessor(relative, data), view[relative])
                self.assertEqual(lineage.predecessor(relative, view[relative]), view[relative])
                tree = ast.parse(data); original = fingerprint(tree)
                self.assertEqual(fingerprint(lineage.restore_task_contract(tree, relative)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), original)

    def test_all_changed_sources_reject_unreviewed_bytes_and_ast(self):
        for relative in lineage.record()['modules']:
            data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-contract source'):
                    lineage.predecessor(relative, data + b'\n# unreviewed byte edit\n')
                with self.assertRaisesRegex(AssertionError, 'complete task-contract AST'):
                    lineage.restore_task_contract(ast.parse(data + b'\nunreviewed = True\n'), relative)

    def test_mutation_inside_a_function_is_not_hidden(self):
        for relative in lineage.record()['modules']:
            tree = ast.parse((lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes())
            function = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            function.body.insert(0, ast.Return(value=ast.Constant(value=None)))
            with self.subTest(relative=relative), self.assertRaisesRegex(AssertionError, 'complete task-contract AST'):
                lineage.restore_task_contract(tree, relative)

    def test_changed_predecessor_pin_or_path_is_refused(self):
        rows = lineage.record(); relative = next(iter(rows['modules']))
        data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
        for field in ('predecessor_sha256', 'predecessor_ast_sha256', 'predecessor_source'):
            altered = deepcopy(rows); altered['modules'][relative][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(lineage, 'record', return_value=altered):
                with self.assertRaisesRegex(AssertionError, 'task-contract predecessor'):
                    lineage.predecessor(relative, data)

    def test_closure_refuses_extra_missing_new_and_unchanged_source_edits(self):
        rows = lineage.record()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (lineage.ROOT / 'src/adaptive_inference').rglob('*.py'):
                target = root / path.relative_to(lineage.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
            for row in rows['modules'].values():
                target = root / row['predecessor_source']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((lineage.ROOT / row['predecessor_source']).read_bytes())
            with mock.patch.object(lineage, 'ROOT', root), mock.patch.object(lineage, 'record', return_value=rows):
                lineage.runtime_view()
                extra = root / 'src/adaptive_inference/unreviewed.py'; extra.write_text('pass\n')
                with self.assertRaisesRegex(AssertionError, 'runtime closure'):
                    lineage.runtime_view()
                extra.unlink()
                for group in ('new_modules', 'unchanged_runtime'):
                    relative = next(iter(rows[group])); path = root / 'src/adaptive_inference' / relative
                    before = path.read_bytes(); path.write_bytes(before + b'\n# unreviewed\n')
                    with self.subTest(group=group), self.assertRaisesRegex(AssertionError, 'runtime source'):
                        lineage.runtime_view()
                    path.write_bytes(before)
                missing = root / 'src/adaptive_inference/task_spec.py'; missing.unlink()
                with self.assertRaisesRegex(AssertionError, 'runtime closure'):
                    lineage.runtime_view()


if __name__ == '__main__':
    unittest.main()
