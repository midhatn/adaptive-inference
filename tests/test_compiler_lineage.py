"""Historical inputs stay exact while the compiler is tested independently."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import compiler_lineage as lineage
from paused_expiry_lineage import fingerprint


class CompilerLineageTests(unittest.TestCase):
    def current_runtime(self):
        runtime = lineage.ROOT / 'src/adaptive_inference'
        return {path.relative_to(runtime).as_posix(): path.read_bytes()
                for path in runtime.rglob('*.py')}

    def test_exact_predecessors_and_original_task_validator_source_are_retained(self):
        rows = lineage.record()
        self.assertEqual(rows['predecessor_revision'], '84ef4d21bf948c8266c76910a22648c27f1113d8')
        self.assertEqual(len(rows['files']), 16)
        for relative, row in rows['files'].items():
            with self.subTest(relative=relative):
                data = (lineage.ROOT / relative).read_bytes()
                before = lineage.retained(relative, row, lineage.ROOT)
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
                self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
                self.assertEqual(lineage.predecessor(relative, data), before)
                self.assertEqual(lineage.predecessor(relative, before), before)
        spec = rows['files']['src/adaptive_inference/task_spec.py']
        self.assertEqual(spec['predecessor_sha256'],
                         'e5c85a4f07b256c799a654fb1c5631dd71a177ed6ac3218f9453b8e56ccba425')
        self.assertNotEqual(spec['successor_sha256'], spec['predecessor_sha256'])
        for relative, pin in rows['preserved_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT / relative).read_bytes()).hexdigest(), pin)

    def test_unknown_byte_and_semantic_edits_are_not_projected(self):
        for relative in lineage.record()['files']:
            data = (lineage.ROOT / relative).read_bytes()
            for extra in (b'\n# unreviewed source\n', b'\nunreviewed = True\n'):
                with self.subTest(relative=relative, extra=extra):
                    changed = data + extra
                    self.assertEqual(lineage.predecessor(relative, changed), changed)

    def test_runtime_closure_requires_all_additions_and_preserves_all_old_pins(self):
        rows = lineage.record()
        current = self.current_runtime(); original = dict(current)
        self.assertEqual(len(rows['baseline_runtime']), 63)
        self.assertEqual(len(rows['additions']), 10)
        result = lineage.runtime_view(current)
        self.assertEqual(current, original)
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in result.items()},
                         rows['baseline_runtime'])
        self.assertEqual(lineage.runtime_view(result), result)
        for name in current:
            changed = dict(current); changed[name] += b'\n# unreviewed\n'
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'runtime source'):
                lineage.runtime_view(changed)
        for name in (*rows['additions'], 'task_spec.py'):
            changed = dict(current); del changed[name]
            with self.subTest(missing=name), self.assertRaisesRegex(AssertionError, 'runtime closure'):
                lineage.runtime_view(changed)
        with self.assertRaisesRegex(AssertionError, 'runtime closure'):
            lineage.runtime_view({**current, 'unreviewed.py': b'pass\n'})

    def test_ast_projection_requires_exact_current_file_even_for_comment_only_change(self):
        relative = 'task_spec.py'; source = 'src/adaptive_inference/' + relative
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
            with self.assertRaisesRegex(AssertionError, 'complete reboot-budget source'):
                lineage.restore(tree, relative)

    def test_predecessor_and_successor_identity_tampering_is_refused(self):
        rows = lineage.record(); relative = 'src/adaptive_inference/task_spec.py'
        data = (lineage.ROOT / relative).read_bytes()
        for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256',
                      'successor_ast_sha256'):
            changed = deepcopy(rows); changed['files'][relative][field] = '0' * 64
            with self.subTest(field=field), mock.patch.object(lineage, 'record', return_value=changed):
                with self.assertRaisesRegex(AssertionError, 'compiler'):
                    lineage.predecessor(relative, data)

    def test_legacy_disposable_roots_do_not_receive_an_unbound_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = b'pass\n'; tree = ast.parse(data)
            self.assertEqual(lineage.inputs(root), [])
            self.assertEqual(lineage.predecessor('src/adaptive_inference/task_spec.py', data, root), data)
            self.assertEqual(lineage.runtime_view({'unknown.py': data}, root), {'unknown.py': data})
            self.assertIs(lineage.restore(tree, 'task_spec.py', root), tree)


if __name__ == '__main__':
    unittest.main()
