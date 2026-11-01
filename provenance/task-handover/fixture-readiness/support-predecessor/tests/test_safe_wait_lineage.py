"""Exact new source closure and unchanged historical assertions; no model run."""
import ast
from copy import deepcopy
import hashlib
import unittest
from unittest import mock

import task_file_alias_lineage as lineage
from paused_expiry_lineage import fingerprint


class SafeWaitLineageTests(unittest.TestCase):
    def test_complete_current_runtime_and_declared_predecessors(self):
        rows = lineage.safe_wait_record()
        self.assertEqual(rows['schema'], 'adaptive.safe-admission-wait.source-lineage.v1')
        actual = {p.relative_to(lineage.ROOT / 'src/adaptive_inference').as_posix(): p
                  for p in (lineage.ROOT / 'src/adaptive_inference').rglob('*.py')}
        self.assertEqual(set(actual), set(rows['runtime']))
        self.assertEqual(len(actual), 60)
        for relative, path in actual.items():
            data = path.read_bytes(); pin = rows['runtime'][relative]
            self.assertEqual(hashlib.sha256(data).hexdigest(), pin['sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), pin['ast_sha256'])
        for relative, row in rows['files'].items():
            current = (lineage.ROOT / relative).read_bytes()
            before = (lineage.ROOT / row['predecessor_source']).read_bytes()
            self.assertEqual(lineage.safe_wait_predecessor(relative, current), before)
            self.assertEqual(lineage.safe_wait_predecessor(relative, before), before)
            original = ast.parse(current); original_pin = fingerprint(original)
            self.assertEqual(fingerprint(lineage.restore_safe_wait(original, relative)), fingerprint(ast.parse(before)))
            self.assertEqual(fingerprint(original), original_pin)

    def test_unreviewed_successor_bytes_and_inside_outside_ast_refuse(self):
        for relative in lineage.safe_wait_record()['files']:
            data = (lineage.ROOT / relative).read_bytes()
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-handover source'):
                    lineage.safe_wait_predecessor(relative, data+b'\n# unreviewed\n')
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_safe_wait(ast.parse(data+b'\nunreviewed=True\n'), relative)
                tree = ast.parse(data)
                function = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
                if function is None:
                    assignment = next(n for n in tree.body if isinstance(n, ast.Assign))
                    assignment.value = ast.Constant(value='unreviewed value')
                else:
                    function.body.insert(0, ast.Return(value=ast.Constant(value=None)))
                with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                    lineage.restore_safe_wait(tree, relative)

    def test_predecessor_paths_bytes_and_ast_pins_refuse(self):
        for relative in lineage.safe_wait_record()['files']:
            data = (lineage.ROOT / relative).read_bytes()
            for field in ('predecessor_source','predecessor_sha256','predecessor_ast_sha256'):
                rows = lineage.safe_wait_record(); rows['files'][relative][field] = '0'*64
                with self.subTest(relative=relative, field=field), mock.patch.object(lineage, 'safe_wait_record', return_value=rows):
                    with self.assertRaisesRegex(AssertionError, 'safe-wait predecessor'):
                        lineage.safe_wait_predecessor(relative, data)

    def test_all_historical_manifests_remain_exact(self):
        for relative, expected in lineage.safe_wait_record()['historical_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_already_reconstructed_historical_views_remain_exact_and_bounded(self):
        for relative, variants in lineage.safe_wait_record()['historical_views'].items():
            for row in variants:
                data = (lineage.ROOT/row['source']).read_bytes()
                self.assertEqual(lineage.safe_wait_predecessor(relative, data), data)
                self.assertEqual(fingerprint(lineage.restore_safe_wait(ast.parse(data), relative)), row['ast_sha256'])
                changed = lineage.safe_wait_record()
                found = next(r for r in changed['historical_views'][relative] if r['source'] == row['source'])
                found['source'] = 'provenance/../unreviewed/'+relative
                with mock.patch.object(lineage, 'safe_wait_record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'historical source path'):
                        lineage.safe_wait_predecessor(relative, data)

    def test_support_edits_restore_original_assertions_byte_exact(self):
        rows = lineage.safe_wait_record()
        for relative, rules in rows['support_edits'].items():
            data = (lineage.ROOT / relative).read_bytes()
            row = rows['files'][relative]
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
            if rules.get('appended_marker'):
                marker = rules['appended_marker'].encode()
                self.assertEqual(data.count(marker), 1)
                offset = data.index(marker)
                self.assertEqual(hashlib.sha256(data[offset:]).hexdigest(), rules['appended_sha256'])
                data = data[:offset]
            for replacement in reversed(rules['replacements']):
                old, new, count = replacement['old'].encode(), replacement['new'].encode(), replacement['count']
                self.assertEqual(data.count(new), count)
                data = data.replace(new, old)
            self.assertEqual(data, (lineage.ROOT / row['predecessor_source']).read_bytes())


if __name__ == '__main__':
    unittest.main()
