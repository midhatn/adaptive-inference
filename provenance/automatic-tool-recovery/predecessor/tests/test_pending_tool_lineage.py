"""Pending tool recovery preserves exact published recipe source identities."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pending_tool_lineage as lineage
import recipe_reconciliation_lineage
from paused_expiry_lineage import fingerprint


class PendingToolLineageTests(unittest.TestCase):
    def current_runtime(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        return {path.relative_to(runtime).as_posix(): path.read_bytes()
                for path in runtime.rglob('*.py')}

    def test_exact_recipe_predecessors_and_evidence_remain_unchanged(self):
        rows = lineage.record()
        self.assertEqual(rows['predecessor_revision'], '93eba3ce4eee9609283f360fb7ca51b6c136e8bb')
        self.assertTrue(rows['files'])
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                data = (lineage.ROOT / relative).read_bytes()
                before = lineage.retained(relative, row, lineage.ROOT)
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
                self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
                self.assertEqual(lineage.predecessor(relative, data), before)
                self.assertEqual(lineage.predecessor(relative, before), before)
        for relative, pin in rows['preserved_records'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), pin)
        self.assertIn('provenance/recipe-reconciliation/source-lineage.json', rows['preserved_records'])
        self.assertIn('provenance/recipe-reconciliation/installed-worker-loss-2026-11-02.json',
                      rows['preserved_records'])

    def test_unknown_complete_bytes_and_semantics_are_not_projected(self):
        for relative in lineage.record()['files']:
            data = (lineage.ROOT / relative).read_bytes()
            for extra in (b'\n# unreviewed reconciliation source\n', b'\nunreviewed = True\n'):
                changed = data + extra
                with self.subTest(relative=relative, extra=extra):
                    self.assertEqual(lineage.predecessor(relative, changed), changed)

    def test_runtime_restores_all_77_recipe_modules_and_composes_idempotently(self):
        rows = lineage.record()
        self.assertEqual(len(rows['baseline_runtime']), 77)
        current = self.current_runtime(); original = dict(current)
        result = lineage.runtime_view(current)
        self.assertEqual(current, original)
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in result.items()},
                         rows['baseline_runtime'])
        self.assertEqual(lineage.runtime_view(result), result)
        prior = recipe_reconciliation_lineage.runtime_view(current)
        self.assertEqual(len(prior), 77)
        self.assertEqual(recipe_reconciliation_lineage.runtime_view(result), prior)
        self.assertEqual(recipe_reconciliation_lineage.runtime_view(prior), prior)
        for name in current:
            changed = dict(current); changed[name] += b'\n# unreviewed\n'
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'runtime source'):
                lineage.runtime_view(changed)
        changed = dict(current); del changed['task_spec.py']
        with self.assertRaisesRegex(AssertionError, 'runtime closure'):
            lineage.runtime_view(changed)
        with self.assertRaisesRegex(AssertionError, 'runtime closure'):
            lineage.runtime_view({**current, 'unreviewed.py': b'pass\n'})

    def test_ast_projection_requires_complete_current_bytes(self):
        relative = 'desktop/hermes/compiler_recovery.py'
        source = 'src/adaptive_inference/' + relative
        target = lineage.ROOT / source; data = target.read_bytes(); tree = ast.parse(data)
        row = lineage.record()['files'][source]
        self.assertEqual(fingerprint(lineage.restore(tree, relative)), row['predecessor_ast_sha256'])
        self.assertEqual(fingerprint(tree), row['successor_ast_sha256'])
        changed = ast.parse(data + b'\nunreviewed = True\n')
        self.assertEqual(fingerprint(lineage.restore(changed, relative)), fingerprint(changed))
        original_read = Path.read_bytes
        def read(path):
            raw = original_read(path)
            return raw + b'\n# same AST\n' if path == target else raw
        with mock.patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(AssertionError, 'pending-tool-recovery source'):
                lineage.restore(tree, relative)

    def test_predecessor_and_successor_identity_tampering_is_refused(self):
        rows = lineage.record(); relative = 'src/adaptive_inference/desktop/hermes/compiler_recovery.py'
        data = (lineage.ROOT / relative).read_bytes()
        for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256',
                      'successor_ast_sha256'):
            changed = deepcopy(rows); changed['files'][relative][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(lineage, 'record', return_value=changed):
                with self.assertRaisesRegex(AssertionError, 'pending-tool-recovery'):
                    lineage.predecessor(relative, data)

    def test_missing_archive_never_authorizes_an_unbound_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = b'pass\n'; tree = ast.parse(data)
            self.assertEqual(lineage.inputs(root), [])
            self.assertEqual(lineage.predecessor('src/adaptive_inference/task_spec.py', data, root), data)
            self.assertEqual(lineage.runtime_view({'unknown.py': data}, root), {'unknown.py': data})
            self.assertIs(lineage.restore(tree, 'task_spec.py', root), tree)


if __name__ == '__main__':
    unittest.main()
