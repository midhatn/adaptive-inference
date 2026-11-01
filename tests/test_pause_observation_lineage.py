"""Current pause-observation source identity; no retained historical execution."""
import ast
from copy import deepcopy
import hashlib
import unittest
from unittest import mock

import task_file_alias_lineage as lineage
from continuation_diagnostics_lineage import readiness_support_predecessor
from paused_expiry_lineage import fingerprint


def old_source(relative):
    data = lineage.admission_activity.timeout_lineage.preparation_predecessor(relative, (lineage.ROOT / relative).read_bytes())
    data = readiness_support_predecessor(relative, data)
    return lineage.safe_wait_predecessor(relative, data)


def method(tree, key):
    class_name, name = key.split('.')
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return cls, next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


class PauseObservationLineageTests(unittest.TestCase):
    def test_two_current_files_reuse_exact_existing_reviewed_sources(self):
        rows = lineage.observation_record()
        self.assertEqual(rows['schema'], 'adaptive.pause-observation.source-lineage.v1')
        self.assertEqual(set(rows['modules']), {'control_mailbox.py', 'desktop/hermes/control_bridge.py'})
        for relative, row in rows['modules'].items():
            with self.subTest(relative=relative):
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                current = old_source('src/adaptive_inference/' + relative)
                self.assertEqual(row['predecessor_source'], lineage.OBSERVATION_BASE + relative)
                self.assertEqual(lineage.observation_predecessor(relative, current), before)
                self.assertEqual(lineage.observation_predecessor(relative, before), before)
                original_tree = ast.parse(current); original_pin = fingerprint(original_tree)
                self.assertEqual(fingerprint(lineage.restore_observation(original_tree, relative)), fingerprint(ast.parse(before)))
                self.assertEqual(fingerprint(original_tree), original_pin)

    def test_three_declared_methods_are_the_only_ast_changes_and_seal_is_unchanged(self):
        names = set()
        for relative, row in lineage.observation_record()['modules'].items():
            before = ast.parse((lineage.ROOT / row['predecessor_source']).read_bytes())
            current = ast.parse(old_source('src/adaptive_inference/' + relative))
            for key, pins in row['changed_methods'].items():
                cls, current_method = method(current, key); _, old_method = method(before, key)
                names.add(key)
                self.assertEqual(fingerprint(current_method), pins['successor_ast_sha256'])
                self.assertEqual(fingerprint(old_method), pins['predecessor_ast_sha256'])
                cls.body[cls.body.index(current_method)] = deepcopy(old_method)
            self.assertEqual(fingerprint(current), fingerprint(before))
            if relative == 'control_mailbox.py':
                self.assertEqual(fingerprint(method(current, 'Mailbox.seal_paused_execution')[1]),
                                 fingerprint(method(before, 'Mailbox.seal_paused_execution')[1]))
        self.assertEqual(names, {'Mailbox._paused_execution', 'Mailbox.paused_execution_observation', 'Controls.poll'})

    def test_unreviewed_bytes_and_ast_are_refused(self):
        for relative in lineage.observation_record()['modules']:
            data = old_source('src/adaptive_inference/' + relative)
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-handover source'):
                    lineage.observation_predecessor(relative, data + b'\n# unreviewed\n')
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_observation(ast.parse(data + b'\nunreviewed=True\n'), relative)
                tree = ast.parse(data)
                _, changed = method(tree, next(iter(lineage.observation_record()['modules'][relative]['changed_methods'])))
                changed.body.insert(0, ast.Return(value=ast.Constant(value=None)))
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_observation(tree, relative)

    def test_changed_predecessor_identity_and_path_are_refused(self):
        for relative in lineage.observation_record()['modules']:
            current = old_source('src/adaptive_inference/' + relative)
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
                rows = lineage.observation_record(); rows['modules'][relative][field] = '0' * 64
                with self.subTest(relative=relative, field=field), mock.patch.object(lineage, 'observation_record', return_value=rows):
                    with self.assertRaisesRegex(AssertionError, 'pause-observation predecessor'):
                        lineage.observation_predecessor(relative, current)

    def test_original_helper_and_test_assertions_restore_byte_exact(self):
        for relative, row in lineage.observation_record()['support'].items():
            with self.subTest(relative=relative):
                current = old_source(relative)
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                self.assertEqual(hashlib.sha256(current).hexdigest(), row['successor_sha256'])
                self.assertEqual(hashlib.sha256(before).hexdigest(), row['predecessor_sha256'])
                if 'appended_marker' in row:
                    marker = row['appended_marker'].encode()
                    self.assertEqual(current.count(marker), 1)
                    offset = current.index(marker)
                    self.assertEqual(hashlib.sha256(current[offset:]).hexdigest(), row['appended_sha256'])
                    current = current[:offset]
                for addition in row['insertions']:
                    # Anchor at the line boundary: a four-space statement is
                    # otherwise also a substring of its eight-space sibling.
                    addition = b'\n' + addition.encode()
                    self.assertEqual(current.count(addition), 1)
                    current = current.replace(addition, b'\n', 1)
                self.assertEqual(current, before)

    def test_prior_runtime_and_diagnostic_manifests_remain_exact(self):
        rows = lineage.observation_record()
        for relative, pin in rows['historical_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), pin)
        self.assertEqual(rows['historical_manifests']['provenance/task-handover/task-file-aliases/source-lineage.json'],
                         'c99b9386c8426ff792bd078e643e110630a5cad7ae3c3cec7ba269556e1c07ba')
        expected = lineage.record()
        all_names = set().union(*(set(expected[key]) for key in ('modules', 'unchanged_runtime', 'new_modules')))
        self.assertEqual(len(all_names), 60)
        self.assertEqual(set(lineage.admission_activity.timeout_lineage.preparation_runtime_view()), all_names)
        for relative in all_names - set(rows['modules']):
            row = expected['modules'].get(relative)
            pin = row['successor_sha256'] if row else {**expected['unchanged_runtime'], **expected['new_modules']}[relative]['sha256']
            self.assertEqual(hashlib.sha256(old_source('src/adaptive_inference/' + relative)).hexdigest(), pin)


if __name__ == '__main__':
    unittest.main()
