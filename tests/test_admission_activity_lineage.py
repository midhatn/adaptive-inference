"""Preserve historical source assertions while testing the current wait bridge."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest import mock

import admission_activity_lineage as activity
import task_file_alias_lineage as aliases
from paused_expiry_lineage import fingerprint, mapping


class AdmissionActivityLineageTests(unittest.TestCase):
    def test_exact_runtime_closure_has_one_changed_module(self):
        rows = activity.record()
        self.assertEqual(rows['schema'], 'adaptive.admission-activity.source-lineage.v1')
        runtime = activity.ROOT / 'src/adaptive_inference'
        changed = 'desktop/hermes/pause_activity.py'
        actual = {p.relative_to(runtime).as_posix(): p for p in runtime.rglob('*.py')}
        self.assertEqual(set(actual), set(rows['unchanged_runtime']) | {changed})
        self.assertEqual(len(actual), 60)
        for relative, expected in rows['unchanged_runtime'].items():
            self.assertEqual(hashlib.sha256(actual[relative].read_bytes()).hexdigest(), expected)
        for relative, row in rows['files'].items():
            data = (activity.ROOT / relative).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
            before = (activity.ROOT / row['predecessor_source']).read_bytes()
            self.assertEqual(activity.predecessor(relative, data), before)
            tree = ast.parse(data); original = fingerprint(tree)
            self.assertEqual(fingerprint(activity.restore(tree, relative)), row['predecessor_ast_sha256'])
            self.assertEqual(fingerprint(tree), original)
        self.assertEqual(len(aliases.runtime_view()), 60)

    def test_only_the_declared_activity_method_and_imports_change(self):
        relative = 'src/adaptive_inference/desktop/hermes/pause_activity.py'
        row, before = activity.retained(relative)
        old = ast.parse(before)
        current = ast.parse((activity.ROOT / relative).read_bytes())
        old_class, new_class = mapping(old)['class:PauseActivity'], mapping(current)['class:PauseActivity']
        method = mapping(new_class)['function:_check']
        new_class.body[new_class.body.index(method)] = deepcopy(mapping(old_class)['function:_check'])
        current.body.remove(mapping(current)['from:0:adaptive_inference.demand'])
        imports = mapping(current)['from:0:adaptive_inference.desktop.hermes.recovery']
        current.body[current.body.index(imports)] = deepcopy(mapping(old)['from:0:adaptive_inference.desktop.hermes.recovery'])
        self.assertIsInstance(current.body[0], ast.Expr)
        current.body[0] = deepcopy(old.body[0])
        self.assertEqual(fingerprint(current), fingerprint(old))

    def test_reader_changes_restore_every_previous_assertion_byte_exact(self):
        rows = activity.record()
        self.assertEqual(set(rows['support_edits']), {
            'tests/task_file_alias_lineage.py', 'tests/test_safe_wait_lineage.py'})
        for relative, rules in rows['support_edits'].items():
            current = (activity.ROOT / relative).read_bytes()
            for rule in reversed(rules['replacements']):
                old, new = rule['old'].encode(), rule['new'].encode()
                self.assertEqual(current.count(new), rule['count'])
                current = current.replace(new, old)
            self.assertEqual(current, (activity.ROOT / rows['files'][relative]['predecessor_source']).read_bytes())
        for relative, expected in rows['historical_manifests'].items():
            self.assertEqual(hashlib.sha256((activity.ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_unreviewed_wait_source_reaches_and_fails_original_closure_check(self):
        target = activity.ROOT / 'src/adaptive_inference/desktop/hermes/pause_activity.py'
        before = target.read_bytes(); original_read = Path.read_bytes
        mutations = (before + b'\n# unreviewed\n',
                     before.replace(b'WAIT_ACTIVITY_SECONDS = 15.0', b'WAIT_ACTIVITY_SECONDS = 14.0'),
                     before.replace(b'    def _check(self, owned, pause_observation):\n',
                                    b'    def _check(self, owned, pause_observation):\n        return\n'))
        for changed in mutations:
            self.assertNotEqual(before, changed)
            def read(path):
                return changed if path == target else original_read(path)
            with self.subTest(changed=hashlib.sha256(changed).hexdigest()), mock.patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(AssertionError, 'runtime source'):
                    aliases.runtime_view()

    def test_retained_identity_and_path_tampering_are_refused(self):
        rows = activity.record()
        for relative in rows['files']:
            data = (activity.ROOT / relative).read_bytes()
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
                changed = deepcopy(rows); changed['files'][relative][field] = '0' * 64
                with self.subTest(relative=relative, field=field), mock.patch.object(activity, 'record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'admission-activity predecessor'):
                        activity.predecessor(relative, data)


if __name__ == '__main__':
    unittest.main()
