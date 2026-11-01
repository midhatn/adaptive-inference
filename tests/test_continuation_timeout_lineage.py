"""Keep timeout diagnostics separate from all previous behavior/source claims."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import continuation_timeout_lineage as lineage
import continuation_diagnostics_lineage as diagnostics
from paused_expiry_lineage import fingerprint


class TimeoutLineageTests(unittest.TestCase):
    def test_exact_four_file_delta_reverses_every_original_assertion(self):
        rows = lineage.record()
        self.assertEqual(rows['runtime_changes'], [])
        self.assertEqual(set(rows['files']), lineage.INPUTS)
        replacements = json.loads((lineage.ROOT/lineage.ARCHIVE/'replacements.json').read_bytes())
        self.assertEqual(set(replacements), lineage.INPUTS)
        for relative, row in rows['files'].items():
            data = lineage.preparation_predecessor(relative, (lineage.ROOT/relative).read_bytes())
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['successor_sha256'])
            self.assertEqual(fingerprint(ast.parse(data)), row['successor_ast_sha256'])
            before = (lineage.ROOT/row['predecessor_source']).read_bytes()
            self.assertEqual(lineage.predecessor(relative, data), before)
            self.assertEqual(lineage.predecessor(relative, before), before)
            for rule in reversed(replacements[relative]):
                new, old = rule['new'].encode(), rule['old'].encode()
                self.assertEqual(data.count(new), rule['count'])
                data = data.replace(new, old)
            self.assertEqual(data, before)

    def test_all_runtime_modules_and_historical_manifests_stay_exact(self):
        rows = lineage.record()
        runtime = lineage.ROOT/'src/adaptive_inference'
        actual = {name: hashlib.sha256(data).hexdigest()
                  for name, data in lineage.preparation_runtime_view().items()}
        self.assertEqual(len(actual), 60)
        self.assertEqual(actual, rows['unchanged_runtime'])
        for relative, expected in rows['historical_manifests'].items():
            self.assertEqual(hashlib.sha256((lineage.ROOT/relative).read_bytes()).hexdigest(), expected)

    def test_unknown_changes_are_not_projected_and_old_validator_refuses(self):
        relative = diagnostics.FIXTURE; current = (lineage.ROOT/relative).read_bytes()
        for data in (current+b'\n# unknown\n',
                     current.replace(b'continuation_timeout_s = 30', b'continuation_timeout_s = 31', 1)):
            self.assertNotEqual(data, current)
            self.assertEqual(lineage.predecessor(relative, data), data)
            with self.assertRaisesRegex(AssertionError, 'complete CI diagnostic fixture'):
                diagnostics.predecessor(data)
        # A legacy scratch root may omit the outer archive, but cannot thereby
        # project unknown/new source as historical accepted bytes.
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(lineage.predecessor(relative, current, Path(directory)), current)

    def test_predecessor_path_hash_and_ast_tampering_are_refused(self):
        rows = lineage.record()
        for relative in rows['files']:
            data = (lineage.ROOT/relative).read_bytes()
            for field in ('predecessor_source', 'predecessor_sha256', 'predecessor_ast_sha256'):
                changed = deepcopy(rows); changed['files'][relative][field] = '0'*64
                with self.subTest(relative=relative, field=field), mock.patch.object(
                        lineage, 'record', return_value=changed):
                    with self.assertRaisesRegex(AssertionError, 'timeout diagnostic predecessor'):
                        lineage.predecessor(relative, data)


if __name__ == '__main__':
    unittest.main()
