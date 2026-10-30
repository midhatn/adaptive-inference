"""Historical expectations stay exact while two declared current helpers evolve."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import historical_native_sources as lineage


class HistoricalNativeSourcesTests(unittest.TestCase):
    def test_only_declared_files_are_projected_and_both_versions_are_bound(self):
        for relative, (current, previous) in lineage.PINS.items():
            self.assertEqual(hashlib.sha256((lineage.HERE / relative).read_bytes()).hexdigest(), current)
            selected = lineage.historical_native_source(relative)
            self.assertEqual(selected, lineage.ARCHIVE / Path(relative).name)
            self.assertEqual(hashlib.sha256(selected.read_bytes()).hexdigest(), previous)
        other = 'native/owner_source/engine.py'
        self.assertEqual(lineage.historical_native_source(other), lineage.HERE / other)

    def test_modified_current_or_preserved_bytes_are_refused(self):
        for change in ('current', 'previous'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                relative = 'native/owner_source/ownership.py'
                current = root / 'current' / relative
                previous = root / 'previous/ownership.py'
                current.parent.mkdir(parents=True)
                previous.parent.mkdir()
                current.write_bytes((lineage.HERE / relative).read_bytes())
                previous.write_bytes((lineage.ARCHIVE / 'ownership.py').read_bytes())
                target = current if change == 'current' else previous
                target.write_bytes(target.read_bytes() + b'\n# unexpected change\n')
                with mock.patch.object(lineage, 'HERE', root / 'current'), \
                     mock.patch.object(lineage, 'ARCHIVE', root / 'previous'):
                    with self.assertRaisesRegex(ValueError, 'identity changed'):
                        lineage.historical_native_source(relative)

    def test_complete_original_readers_restore_with_only_explicit_path_changes(self):
        archive = lineage.ARCHIVE / 'test-readers'
        pins = json.loads((archive / 'manifest.json').read_text())['sha256']
        transformations = {
            'test_arithmetic_feedback.py': (
                'historical_native_source(row[\'path\']).read_bytes()',
                '(HERE/row[\'path\']).read_bytes()'),
            'test_shutdown_receipts.py': (
                'historical_native_source(row[\'path\']).read_bytes()',
                '(HERE/row[\'path\']).read_bytes()'),
        }
        for name, (after, before) in transformations.items():
            with self.subTest(name=name):
                original = (archive / name).read_bytes()
                self.assertEqual(hashlib.sha256(original).hexdigest(), pins[name])
                current = (lineage.HERE / name).read_bytes()
                added_import = b'from historical_native_sources import historical_native_source\n'
                self.assertEqual(current.count(added_import), 1)
                self.assertEqual(current.count(after.encode()), 1)
                restored = current.replace(added_import, b'').replace(after.encode(), before.encode())
                self.assertEqual(restored, original)


if __name__ == '__main__':
    unittest.main()
