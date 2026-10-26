# SPDX-License-Identifier: Apache-2.0
"""One discovery wrapper runs all 21 unchanged historical PR20 checks."""
import importlib.util
from pathlib import Path
import unittest


class HistoricalPausedExpiryTests(unittest.TestCase):
    def test_unchanged_historical_exporter_checks(self):
        repository = Path(__file__).resolve().parents[1]
        path = repository / 'provenance/paused-budget-expiry/historical-view/run_historical.py'
        spec = importlib.util.spec_from_file_location('paused_expiry_historical_runner', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run(repository)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
