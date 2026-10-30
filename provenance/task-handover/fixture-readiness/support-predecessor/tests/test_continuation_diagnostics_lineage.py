"""Source preservation only; does not execute the retained child fixture."""
import ast
import hashlib
import unittest
from unittest import mock

import continuation_diagnostics_lineage as diagnostics
from paused_expiry_lineage import fingerprint


def cleanup(tree):
    host = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HostTests')
    return host, next(n for n in host.body if isinstance(n, ast.FunctionDef) and n.name == 'cleanup_retained')


class ContinuationDiagnosticLineageTests(unittest.TestCase):
    def test_fixture_projects_to_exact_d1_before_original_assertions(self):
        row = diagnostics.record()['files'][diagnostics.FIXTURE]
        current = (diagnostics.ROOT / diagnostics.FIXTURE).read_bytes()
        before = diagnostics.retained(diagnostics.FIXTURE)
        self.assertEqual(row['predecessor_sha256'], 'd1dae632a71d74e3dcb200b6050acf86e4a38be3907ed403af857cb9e3f8ce99')
        self.assertEqual(diagnostics.predecessor(current), before)
        self.assertEqual(diagnostics.predecessor(before), before)

    def test_only_pinned_opt_in_diagnostic_statements_changed(self):
        row = diagnostics.record()['files'][diagnostics.FIXTURE]
        old = ast.parse(diagnostics.retained(diagnostics.FIXTURE))
        current = ast.parse((diagnostics.ROOT / diagnostics.FIXTURE).read_bytes())
        host, method = cleanup(current); _, old_method = cleanup(old)
        self.assertEqual(fingerprint(method), row['changed_method']['successor_ast_sha256'])
        self.assertEqual(fingerprint(old_method), row['changed_method']['predecessor_ast_sha256'])
        opt_in = next(n for n in method.body if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Name) and n.test.id == 'destination')
        loop = next(n for n in opt_in.body if isinstance(n, ast.For))
        added = loop.body[-3:-1]
        self.assertEqual([type(n) for n in added], [ast.Assign, ast.Try])
        self.assertEqual(fingerprint(ast.Module(body=added, type_ignores=[])),
                         row['changed_method']['inserted_statements_ast_sha256'])
        del loop.body[-3:-1]
        self.assertEqual(fingerprint(method), fingerprint(old_method))
        self.assertEqual(fingerprint(current), fingerprint(old))

    def test_byte_and_ast_mutations_cannot_be_projected(self):
        current = (diagnostics.ROOT / diagnostics.FIXTURE).read_bytes()
        for changed in (current + b'\n# unreviewed\n', current + b'\nunreviewed = True\n',
                        current.replace(b'cleanup_retained(self)', b'cleanup_unreviewed(self)', 1)):
            with self.subTest(changed=hashlib.sha256(changed).hexdigest()):
                with self.assertRaisesRegex(AssertionError, 'complete CI diagnostic fixture'):
                    diagnostics.predecessor(changed)

    def test_wrong_predecessor_identity_and_path_are_refused(self):
        current = (diagnostics.ROOT / diagnostics.FIXTURE).read_bytes()
        for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
            rows = diagnostics.record(); rows['files'][diagnostics.FIXTURE][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(diagnostics, 'record', return_value=rows):
                with self.assertRaisesRegex(AssertionError, 'CI diagnostic predecessor'):
                    diagnostics.predecessor(current)

    def test_old_lineage_assertions_are_byte_exact_after_two_explicit_insertions(self):
        relative = 'tests/test_task_file_alias_lineage.py'
        current = (diagnostics.ROOT / relative).read_bytes()
        fixture_input = b'            sources += lineage.observation_inputs()\n'
        self.assertEqual(current.count(fixture_input), 1)
        current = current.replace(fixture_input, b'', 1)
        row = diagnostics.record()['files'][relative]
        self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
        first = b'from continuation_diagnostics_lineage import predecessor as diagnostic_predecessor\n'
        second = b'        current = diagnostic_predecessor(current)\n'
        self.assertEqual(current.count(first), 1); self.assertEqual(current.count(second), 1)
        self.assertEqual(current.replace(first, b'', 1).replace(second, b'', 1), diagnostics.retained(relative))

    def test_alias_manifest_remains_exact_and_runtime_is_not_in_this_delta(self):
        rows = diagnostics.record()
        self.assertEqual(rows['schema'], 'adaptive.continuation-ci-diagnostics.source-lineage.v1')
        self.assertEqual(set(rows['files']), {diagnostics.FIXTURE, 'tests/test_task_file_alias_lineage.py'})
        self.assertEqual(rows['runtime_changes'], [])
        historical = diagnostics.ROOT / 'provenance/task-handover/task-file-aliases/source-lineage.json'
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(),
                         'c99b9386c8426ff792bd078e643e110630a5cad7ae3c3cec7ba269556e1c07ba')


if __name__ == '__main__':
    unittest.main()
