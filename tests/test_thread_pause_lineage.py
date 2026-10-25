import ast
import hashlib
import unittest

from thread_pause_lineage import ROOT, record, predecessor, restore_thread
from ast_preservation import preservation_dump


class ThreadPauseLineageTests(unittest.TestCase):
    def test_exact_five_module_delta_preserves_all_failed_predecessors(self):
        rows=record();self.assertEqual(len(rows['modules']),5)
        self.assertEqual(len(rows['unchanged_runtime']),49)
        for relative,pin in rows['unchanged_runtime'].items():
            self.assertEqual(hashlib.sha256((ROOT/'src/adaptive_inference'/relative).read_bytes()).hexdigest(),pin)
        for relative in rows['modules']:
            current=(ROOT/'src/adaptive_inference'/relative).read_bytes()
            old=predecessor(relative,current)
            self.assertEqual(preservation_dump(restore_thread(ast.parse(current),relative)),preservation_dump(ast.parse(old)))

    def test_scope_interruption_and_cleanup_mutations_cannot_be_hidden(self):
        for relative,old,new in (
            ('desktop/hermes/pause_activity.py','self.thread_interrupted() is not False','False'),
            ('desktop/hermes/pause_activity.py','not self.lock.acquire(blocking=False)','False'),
            ('desktop/hermes/recovery.py','self._control_thread = previous','self._control_thread = threading.current_thread()'),
            ('desktop/hermes/service_stop.py','activity.cleanup_scope(agent, verify=True)','activity.cleanup_scope(agent, verify=False)')):
            source=(ROOT/'src/adaptive_inference'/relative).read_text();self.assertIn(old,source)
            with self.subTest(relative=relative,old=old),self.assertRaises(AssertionError):
                restore_thread(ast.parse(source.replace(old,new,1)),relative)
