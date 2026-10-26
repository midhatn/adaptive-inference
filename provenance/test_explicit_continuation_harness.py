# SPDX-License-Identifier: Apache-2.0
"""Run the public qualification's portable fixtures once in an isolated import scope."""
from pathlib import Path
import subprocess
import sys
import unittest


class PublicContinuationHarnessTests(unittest.TestCase):
    def test_portable_harness_checks(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-B','-m','unittest','discover',
            '-s','examples/validation/explicit_continuation','-p','test_*.py','-v'],
            cwd=root,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
