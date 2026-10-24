"""Preserve the precise fixture inputs named by published integration receipts."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IntegrationReceiptTests(unittest.TestCase):
    def test_exported_fixture_bytes_match_their_recorded_validation(self):
        for integration in ('openai-admission', 'openhands'):
            directory = ROOT / 'integrations' / integration
            receipt = json.loads((directory / 'evidence.json').read_text(encoding='utf-8'))
            for name, recorded in receipt['files'].items():
                with self.subTest(integration=integration, file=name):
                    content = (directory / name).read_bytes()
                    self.assertEqual(len(content), recorded['bytes'])
                    self.assertEqual(hashlib.sha256(content).hexdigest(), recorded['sha256'])


if __name__ == '__main__':
    unittest.main()
