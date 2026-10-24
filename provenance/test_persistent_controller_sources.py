"""Retained reviewed controller/timing inputs remain inspectable offline."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent / 'persistent-desktop'


class PersistentSourceTests(unittest.TestCase):
    def test_archived_controller_and_timing_sources_match_lineage(self):
        for root in (HERE, HERE / 'reviewed-timing'):
            lineage = json.loads((root / 'source-lineage.json').read_text(encoding='utf-8'))
            for name, expected in lineage['preserved'].items():
                with self.subTest(source=name):
                    path = root / name
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
