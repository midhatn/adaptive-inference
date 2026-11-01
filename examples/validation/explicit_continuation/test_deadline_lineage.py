# SPDX-License-Identifier: Apache-2.0
"""Keep the prospective expression change separate from historical evidence."""
import hashlib
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ARCHIVE=ROOT/'provenance/explicit-continuation/deadline-arithmetic'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())


class DeadlineSourceTests(unittest.TestCase):
    def test_preserved_source_and_exact_expression_change(self):
        lineage=read(ARCHIVE/'source-lineage.json')
        self.assertEqual(sha(ARCHIVE/'predecessor-files.json'),lineage['predecessor_manifest_sha256'])
        pins=read(ARCHIVE/'predecessor-files.json')
        for name,pin in pins.items():
            self.assertEqual(sha(ARCHIVE/'predecessor'/name),pin,name)
        for name in ('test_checks.py','test_source.py'):
            self.assertEqual(sha(HERE/name),pins[name],name)
        self.assertEqual(sha(ROOT/'provenance/explicit-continuation/acceptance/checks.py'),pins['checks.py'])
        delta=lineage['expression_change'];current=(HERE/'checks.py').read_bytes()
        self.assertEqual(current.count(delta['after'].encode()),1)
        restored=current.replace(delta['after'].encode(),delta['before'].encode())
        self.assertEqual(restored,(ARCHIVE/'predecessor/checks.py').read_bytes())
        self.assertEqual(sha(ROOT/lineage['producer_path']),lineage['producer_sha256'])

    def test_old_workflow_bindings_remain_and_new_manifest_is_complete(self):
        previous=read(ARCHIVE/'predecessor/source-lineage.json')
        current=read(HERE/'source-lineage.json');correction=current.pop('deadline_arithmetic_correction')
        self.assertEqual(correction['sha256'],sha(ROOT/correction['path']))
        self.assertEqual(current.pop('scope'),read(ARCHIVE/'source-lineage.json')['current_scope'])
        previous.pop('scope');previous['exact_workflow_files'].remove('checks.py')
        self.assertEqual(current,previous)
        old=read(ARCHIVE/'predecessor/source-manifest.json')['files']
        for name,pin in old.items():
            target=ARCHIVE/'predecessor'/name if name in ('checks.py','README.md','source-lineage.json') else HERE/name
            self.assertEqual(sha(target),pin,name)
        manifest=read(HERE/'source-manifest.json')['files']
        self.assertEqual(set(manifest),set(old)|{'test_deadline_arithmetic.py','test_deadline_lineage.py'})


if __name__=='__main__':unittest.main()
