"""Pinned expiry deltas preserve all prior source assertions and reject drift."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

from ast_preservation import preservation_dump
from paused_expiry_lineage import ROOT, ARCHIVE, retained, restore_expiry
from execution_clock_lineage import predecessor


class ExpiryLineageTests(unittest.TestCase):
    def test_all_ten_exact_successors_restore_their_complete_predecessors(self):
        record=json.loads((ARCHIVE/'source-lineage.json').read_text())
        self.assertEqual(len(record['modules']),10)
        self.assertEqual(len(record['unchanged_runtime']),42)
        for relative,expected in record['unchanged_runtime'].items():
            data=(ROOT/'src/adaptive_inference'/relative).read_bytes()
            self.assertEqual(hashlib.sha256(predecessor(relative,data)).hexdigest(),expected)
        for relative,row in record['modules'].items():
            with self.subTest(relative=relative):
                data=(ROOT/'src/adaptive_inference'/relative).read_bytes()
                self.assertEqual(hashlib.sha256(predecessor(relative,data)).hexdigest(),row['successor_sha256'])
                _,before=retained(relative)
                self.assertEqual(preservation_dump(restore_expiry(ast.parse(data),relative)),preservation_dump(before))

    def test_mutations_within_declared_seams_cannot_be_hidden_by_restoration(self):
        mutations=(('control_mailbox.py',"'execution_budget_expired'","'other_expiry'"),
            ('desktop/hermes/run_recovery.py',"2 if result.get('cleanup_errors')","5 if result.get('cleanup_errors')"),
            ('desktop/control_client.py','Not recorded;','Not sent;'),
            ('desktop/hermes/service_stop.py','timeout=5.0','timeout=50.0'))
        for relative,old,new in mutations:
            text=(ROOT/'src/adaptive_inference'/relative).read_text(encoding='utf-8')
            self.assertIn(old,text)
            with self.subTest(relative=relative),self.assertRaises(AssertionError):
                restore_expiry(ast.parse(text.replace(old,new,1)),relative)

    def test_outside_seam_changes_remain_visible_in_complete_ast_comparison(self):
        for relative,old,new in (
            ('desktop/control_client.py','queue.Queue(maxsize=3)','queue.Queue(maxsize=4)'),
            ('desktop/hermes/run_recovery.py',"'max_requests': 8","'max_requests': 9"),
            ('desktop/composition.py','qualification_timeout_s != 1800','qualification_timeout_s != 1801')):
            text=(ROOT/'src/adaptive_inference'/relative).read_text(encoding='utf-8');self.assertIn(old,text)
            _,before=retained(relative)
            try:changed=restore_expiry(ast.parse(text.replace(old,new,1)),relative)
            except AssertionError:
                # This statement now belongs to a strictly pinned clock/Pause
                # successor seam, so rejection is stronger than a later diff.
                continue
            self.assertNotEqual(preservation_dump(changed),preservation_dump(before))


if __name__=='__main__':unittest.main()
