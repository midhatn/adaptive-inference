import ast
import hashlib
import unittest
from execution_clock_lineage import ROOT, record, predecessor, restore_clock
from ast_preservation import preservation_dump
from thread_pause_lineage import predecessor as thread_predecessor


class ClockLineageTests(unittest.TestCase):
    def test_complete_source_delta_is_explicit_and_failed_predecessors_are_unchanged(self):
        rows=record();self.assertEqual(len(rows['modules']),7)
        self.assertEqual(len(rows['unchanged_runtime']),45);self.assertEqual(len(rows['new_modules']),2)
        for relative,pin in {**rows['unchanged_runtime'],**rows['new_modules']}.items():
            current=(ROOT/'src/adaptive_inference'/relative).read_bytes()
            self.assertEqual(hashlib.sha256(thread_predecessor(relative,current)).hexdigest(),pin)
        for relative in rows['modules']:
            current=(ROOT/'src/adaptive_inference'/relative).read_bytes()
            old=predecessor(relative,current)
            self.assertEqual(preservation_dump(restore_clock(ast.parse(current),relative)),preservation_dump(ast.parse(old)))

    def test_original_deadline_and_sdk_guard_mutations_are_detected(self):
        for relative,old,new in (
                ('desktop/composition.py','execution_now()+900','execution_now()+901'),
                ('desktop/hermes/service_stop.py',"now < marker['sealed_at_monotonic']","False"),
                ('desktop/hermes/run_recovery.py','controls.wait_activity.finish_turn(outcome)','pass')):
            source=(ROOT/'src/adaptive_inference'/relative).read_text();self.assertIn(old,source)
            with self.subTest(relative=relative),self.assertRaises(AssertionError):
                restore_clock(ast.parse(source.replace(old,new,1)),relative)
