"""Current-source closure and strict historical projection, without execution."""
import ast
from copy import deepcopy
import hashlib
import json
import unittest
from unittest import mock

import continuation_lineage as lineage
from paused_expiry_lineage import fingerprint
from task_contract_lineage import runtime_view


class ContinuationLineageTests(unittest.TestCase):
    def test_exact_current_runtime_closure_and_predecessor_snapshot(self):
        record = lineage.record()
        self.assertEqual(tuple(len(record[name]) for name in
            ('modules', 'unchanged_runtime', 'new_modules')), (8, 46, 3))
        expected = set(record['modules']) | set(record['unchanged_runtime']) | set(record['new_modules'])
        root = lineage.ROOT / 'src/adaptive_inference'
        historical = runtime_view()  # Validate the complete current closure before projecting it.
        self.assertEqual(set(historical), expected)
        for relative, row in record['modules'].items():
            data = historical[relative]
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
            self.assertEqual(row['predecessor_source'], record['historical_snapshot'] + '/src/adaptive_inference/' + relative)
            prior = lineage.retained(relative, row)
            self.assertEqual(lineage.predecessor(relative, data), prior)
            self.assertEqual(lineage.predecessor(relative, prior), prior)
            self.assertEqual(fingerprint(lineage.restore_continuation(ast.parse(data), relative)), fingerprint(ast.parse(prior)))
            self.assertTrue(row['edits'])
        for relative, digest in record['unchanged_runtime'].items():
            self.assertEqual(hashlib.sha256(historical[relative]).hexdigest(), digest)
        for relative, row in record['new_modules'].items():
            data = historical[relative]
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), row['ast_sha256'])

    def test_every_changed_file_rejects_unpinned_bytes_and_outside_ast_mutation(self):
        for relative in lineage.record()['modules']:
            data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(AssertionError, 'complete (?:task-contract|continuation) source'):
                    lineage.predecessor(relative, data + b'\n# unreviewed whitespace-only change\n')
                with self.assertRaisesRegex(AssertionError, 'complete (?:task-contract|continuation) AST'):
                    lineage.restore_continuation(ast.parse(data + b'\nunreviewed = True\n'), relative)

    def test_changed_guard_inside_declared_seam_is_not_hidden(self):
        for relative in lineage.record()['modules']:
            tree = ast.parse((lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes())
            row = lineage.record()['modules'][relative]
            edit = next(edit for edit in row['edits'] if edit['path'][-1].startswith('function:'))
            node = tree
            for name in edit['path']:
                node = lineage.mapping(node)[name]
            node.body.insert(0, ast.Return(value=ast.Constant(value=None)))
            with self.subTest(relative=relative), self.assertRaisesRegex(AssertionError, 'complete (?:task-contract|continuation) AST'):
                lineage.restore_continuation(tree, relative)

    def test_missing_and_tampered_declared_seams_fail_closed(self):
        record = lineage.record()
        relative = 'desktop/composition.py'
        tree = ast.parse((lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes())
        for mutation in ('drop', 'replace_pin'):
            altered = deepcopy(record)
            if mutation == 'drop':
                altered['modules'][relative]['edits'].pop()
            else:
                altered['modules'][relative]['edits'][0]['successor_ast_sha256'] = '0' * 64
            with self.subTest(mutation=mutation), mock.patch.object(lineage, 'record', return_value=altered), self.assertRaises(AssertionError):
                lineage.restore_continuation(tree, relative)

    def test_wrong_predecessor_pin_cannot_replace_historical_source(self):
        record = lineage.record()
        relative = 'task_store.py'
        record['modules'][relative]['predecessor_sha256'] = '0' * 64
        data = (lineage.ROOT / 'src/adaptive_inference' / relative).read_bytes()
        with mock.patch.object(lineage, 'record', return_value=record), self.assertRaisesRegex(AssertionError, 'predecessor bytes'):
            lineage.predecessor(relative, data)

    def test_qualifier_compatibility_is_one_exact_child_identity_replacement(self):
        helper = lineage.ROOT / 'examples/validation/installed_desktop'
        saved = lineage.ARCHIVE / 'qualification-predecessor'
        previous = json.loads((saved / 'source-manifest.json').read_text(encoding='utf-8'))
        for name, row in previous['files'].items():
            data = (saved / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            self.assertEqual(len(data), row['bytes'])
        current = json.loads((helper / 'source-lineage.json').read_text(encoding='utf-8'))
        historical = json.loads((saved / 'source-lineage.json').read_text(encoding='utf-8'))
        successor = current.pop('compatibility_successor')
        self.assertEqual(current, historical)
        self.assertEqual(hashlib.sha256((saved / 'source-manifest.json').read_bytes()).hexdigest(), successor['historical_source_manifest_sha256'])
        old = (saved / 'qualify.py').read_bytes()
        new = (helper / 'qualify.py').read_bytes()
        change = successor['exact_replacement']
        self.assertEqual(change, {'before': 'self.waits.get(self.worker.pid)', 'after': 'self.waits.get(self.worker)', 'count': 1})
        self.assertEqual(old.count(change['before'].encode()), 1)
        self.assertEqual(old.replace(change['before'].encode(), change['after'].encode()), new)
        self.assertEqual(hashlib.sha256(old).hexdigest(), successor['predecessor_sha256'])
        self.assertEqual(hashlib.sha256(new).hexdigest(), successor['successor_sha256'])
        acceptance = json.loads((lineage.ROOT / 'provenance/paused-budget-expiry/acceptance/bindings.json').read_text())
        self.assertEqual(acceptance['qualifier_sha256'], successor['predecessor_sha256'])


if __name__ == '__main__':
    unittest.main()
