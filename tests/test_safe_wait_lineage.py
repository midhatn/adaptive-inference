"""Exact new source closure and unchanged historical assertions; no model run."""
import ast
from copy import deepcopy
import hashlib
import unittest
from unittest import mock

import task_file_alias_lineage as lineage
from admission_activity_lineage import predecessor as activity_predecessor
from continuation_diagnostics_lineage import readiness_support_predecessor
from paused_expiry_lineage import fingerprint


def current_source(relative):
    data = lineage.continuation_observation_predecessor(relative, (lineage.ROOT / relative).read_bytes())
    return readiness_support_predecessor(relative, data)


class SafeWaitLineageTests(unittest.TestCase):
    def test_complete_current_runtime_and_declared_predecessors(self):
        rows = lineage.safe_wait_record()
        self.assertEqual(rows['schema'], 'adaptive.safe-admission-wait.source-lineage.v1')
        actual = {p.relative_to(lineage.ROOT / 'src/adaptive_inference').as_posix(): p
                  for p in (lineage.ROOT / 'src/adaptive_inference').rglob('*.py')}
        self.assertEqual(set(actual), set(rows['runtime']))
        self.assertEqual(len(actual), 60)
        for relative, path in actual.items():
            data = lineage.continuation_observation_predecessor('src/adaptive_inference/' + relative, path.read_bytes())
            pin = rows['runtime'][relative]
            self.assertEqual(hashlib.sha256(data).hexdigest(), pin['sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), pin['ast_sha256'])
        for relative, row in rows['files'].items():
            current = current_source(relative)
            before = (lineage.ROOT / row['predecessor_source']).read_bytes()
            self.assertEqual(lineage.safe_wait_predecessor(relative, current), before)
            self.assertEqual(lineage.safe_wait_predecessor(relative, before), before)
            original = ast.parse(current); original_pin = fingerprint(original)
            self.assertEqual(fingerprint(lineage.restore_safe_wait(original, relative)), fingerprint(ast.parse(before)))
            self.assertEqual(fingerprint(original), original_pin)

    def test_unreviewed_successor_bytes_and_inside_outside_ast_refuse(self):
        for relative in lineage.safe_wait_record()['files']:
            data = current_source(relative)
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
            data = current_source(relative)
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
            data = current_source(relative)
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

# Current ACK-read successor source checks; historical assertions above are unchanged.
class ContinuationObservationLineageTests(unittest.TestCase):
    def test_exact_two_runtime_delta_and_whole_source_projection(self):
        rows = lineage.continuation_observation_record()
        self.assertEqual(rows['schema'], 'adaptive.continuation-observation.source-lineage.v1')
        self.assertEqual(set(rows['runtime_changes']), {
            'src/adaptive_inference/desktop/composition.py',
            'src/adaptive_inference/desktop/mailbox_runtime.py'})
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                data = activity_predecessor(relative, (lineage.ROOT / relative).read_bytes())
                before = (lineage.ROOT / row['predecessor_source']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
                self.assertEqual(lineage.continuation_observation_predecessor(relative, data), before)
                self.assertEqual(lineage.continuation_observation_predecessor(relative, before), before)
                tree = ast.parse(data); initial = fingerprint(tree)
                self.assertEqual(fingerprint(lineage.restore_continuation_observation(tree, relative)),
                                 row['predecessor_ast_sha256'])
                self.assertEqual(fingerprint(tree), initial)

    def test_byte_and_inside_outside_ast_changes_refuse(self):
        for relative in lineage.continuation_observation_record()['files']:
            data = activity_predecessor(relative, (lineage.ROOT / relative).read_bytes())
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete task-handover source'):
                    lineage.continuation_observation_predecessor(relative, data+b'\n# unreviewed\n')
                for tree in (ast.parse(data+b'\nunreviewed=True\n'), ast.parse(data)):
                    if not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='unreviewed'
                                                               for t in n.targets) for n in tree.body):
                        method = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
                        method.body.insert(0, ast.Return(value=ast.Constant(value=None)))
                    with self.assertRaisesRegex(AssertionError, 'complete task-handover AST'):
                        lineage.restore_continuation_observation(tree, relative)

    def test_predecessor_path_bytes_and_ast_refuse(self):
        for relative in lineage.continuation_observation_record()['files']:
            data = activity_predecessor(relative, (lineage.ROOT / relative).read_bytes())
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
                rows = lineage.continuation_observation_record(); rows['files'][relative][field] = '0'*64
                with self.subTest(relative=relative, field=field), mock.patch.object(
                        lineage, 'continuation_observation_record', return_value=rows):
                    with self.assertRaisesRegex(AssertionError, 'continuation-observation predecessor'):
                        lineage.continuation_observation_predecessor(relative, data)

    def test_original_support_assertions_restore_byte_exact(self):
        rows = lineage.continuation_observation_record()
        self.assertEqual(set(rows['support_edits']), {'tests/task_file_alias_lineage.py',
            'tests/test_safe_wait_lineage.py', 'tests/test_continuation_readiness.py'})
        for relative, rules in rows['support_edits'].items():
            current = activity_predecessor(relative, (lineage.ROOT / relative).read_bytes())
            if rules.get('appended_marker'):
                marker = rules['appended_marker'].encode()
                self.assertEqual(current.count(marker), 1)
                offset = current.index(marker)
                self.assertEqual(hashlib.sha256(current[offset:]).hexdigest(), rules['appended_sha256'])
                current = current[:offset]
            for rule in reversed(rules['replacements']):
                old, new = rule['old'].encode(), rule['new'].encode()
                self.assertEqual(current.count(new), rule['count'])
                current = current.replace(new, old)
            row = rows['files'][relative]
            self.assertEqual(current, (lineage.ROOT / row['predecessor_source']).read_bytes())

    def test_previous_manifests_and_only_declared_runtime_seams_preserved(self):
        from paused_expiry_lineage import mapping
        rows = lineage.continuation_observation_record()
        for relative, pin in rows['historical_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), pin)
        for relative, changes in rows['runtime_changes'].items():
            row = rows['files'][relative]
            old = ast.parse((lineage.ROOT / row['predecessor_source']).read_bytes())
            current = ast.parse((lineage.ROOT / relative).read_bytes())
            for change in changes:
                parent, old_parent = current, old
                for part in change['path'][:-1]:
                    parent, old_parent = mapping(parent)[part], mapping(old_parent)[part]
                node = mapping(parent)[change['path'][-1]]
                prior = mapping(old_parent).get(change['path'][-1])
                self.assertEqual(fingerprint(node), change['successor_ast_sha256'])
                self.assertEqual(fingerprint(prior) if prior is not None else None, change['predecessor_ast_sha256'])
                index = parent.body.index(node)
                if prior is None:
                    del parent.body[index]
                else:
                    parent.body[index] = deepcopy(prior)
            self.assertEqual(fingerprint(current), fingerprint(old))
