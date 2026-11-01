# SPDX-License-Identifier: Apache-2.0
"""Run the fresh-workflow source checks in the existing isolated discovery style."""
from pathlib import Path
import subprocess
import sys
import unittest


class PublicTaskHandoverTests(unittest.TestCase):
    def test_public_workflow_source_and_local_bindings(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-B','-m','unittest','discover',
            '-s','examples/validation/task_handover','-p','test_*.py','-v'],
            cwd=root,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
