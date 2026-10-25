"""Selected desktop control inputs remain inspectable without private packets."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent / 'desktop-control-core'


class DesktopControlSourceTests(unittest.TestCase):
    def test_retained_components_fixtures_and_consumer_match_lineage(self):
        lineage = json.loads((ROOT / 'source-lineage.json').read_text(encoding='utf-8'))
        for name, expected in lineage['preserved'].items():
            with self.subTest(source=name):
                path = ROOT / name
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                self.assertTrue(path.resolve().is_relative_to(ROOT.resolve()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
