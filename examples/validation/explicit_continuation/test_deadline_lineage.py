# SPDX-License-Identifier: Apache-2.0
"""Keep the prospective expression change separate from historical evidence."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ARCHIVE=ROOT/'provenance/explicit-continuation/deadline-arithmetic'

# Reuse the existing exact SHA+AST source view; retained code is never executed.
sys.path.insert(0,str(ROOT/'tests'))
try:
    from continuation_timeout_lineage import reboot_budget_predecessor
finally:
    sys.path.pop(0)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def producer_sha(relative,data):
    return hashlib.sha256(reboot_budget_predecessor(relative,data,ROOT)).hexdigest()


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
        producer=(ROOT/lineage['producer_path']).read_bytes()
        self.assertEqual(producer_sha(lineage['producer_path'],producer),lineage['producer_sha256'])
        # Even an unchanged AST with different bytes must not receive this view.
        self.assertEqual(producer.count(b'state.pop(BUDGET, None)'),1)
        for changed in (producer+b'\n# unreviewed producer\n',
                        producer.replace(b'state.pop(BUDGET, None)',b'state.get(BUDGET, None)',1)):
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()):
                self.assertEqual(reboot_budget_predecessor(lineage['producer_path'],changed,ROOT),changed)
                with self.assertRaises(AssertionError):
                    self.assertEqual(producer_sha(lineage['producer_path'],changed),lineage['producer_sha256'])

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
