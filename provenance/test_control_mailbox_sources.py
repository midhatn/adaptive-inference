"""Retained control and coherent-snapshot sources remain inspectable offline."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent / 'control-mailbox'


class ControlMailboxSourceTests(unittest.TestCase):
    def test_preserved_sources_match_both_promotion_records(self):
        for name in ('source-lineage.json', 'snapshot-lineage.json'):
            lineage = json.loads((HERE / name).read_text(encoding='utf-8'))
            for source, expected in lineage['preserved'].items():
                with self.subTest(manifest=name, source=source):
                    path = HERE / source
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertTrue(path.resolve().is_relative_to(HERE.resolve()))
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
