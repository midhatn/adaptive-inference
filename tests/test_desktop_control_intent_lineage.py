"""Exact pre-fix source, declared successor, and outside-seam mutation checks."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from adaptive_inference.desktop import control_client as cc
from ast_preservation import preservation_dump
from desktop_gui_support.intent_lineage import (
    ADDED, BEFORE_SHA256, EDITED, ROOT, controller, predecessor_tree, restore_predecessor,
)


class IntentLineageTests(unittest.TestCase):
    def setUp(self):
        self.before=predecessor_tree()
        self.after=ast.parse(Path(cc.__file__).read_text(encoding='utf-8'))
        self.prior={n.name:n for n in controller(self.before).body if isinstance(n,ast.FunctionDef)}
        self.current={n.name:n for n in controller(self.after).body if isinstance(n,ast.FunctionDef)}

    def test_pinned_successor_and_exact_declared_method_set(self):
        record=json.loads((ROOT/'provenance/desktop-control-intent/source-lineage.json').read_text())
        self.assertEqual(record['predecessor_sha256'],BEFORE_SHA256)
        self.assertEqual(record['successor_sha256'],hashlib.sha256(Path(cc.__file__).read_bytes()).hexdigest())
        self.assertEqual(record['edited_methods'],list(EDITED));self.assertEqual(record['added_methods'],list(ADDED))
        self.assertEqual(set(self.current)-set(self.prior),set(ADDED))
        self.assertEqual(set(self.prior)-set(self.current),set())
        self.assertEqual({name for name in self.prior if preservation_dump(self.prior[name])!=preservation_dump(self.current[name])},set(EDITED))

    def test_everything_outside_the_declared_seam_matches_exact_predecessor(self):
        self.assertEqual(preservation_dump(restore_predecessor(self.after)),preservation_dump(self.before))

    def test_close_tick_and_initializer_keep_their_original_ownership_statements(self):
        init=deepcopy(self.current['__init__'])
        added=ast.parse('self._local_intent=None\nself._local_feedback=None').body
        self.assertEqual([preservation_dump(n) for n in init.body[-2:]],[preservation_dump(n) for n in added])
        init.body=init.body[:-2]
        self.assertEqual(preservation_dump(init),preservation_dump(self.prior['__init__']))
        tick=deepcopy(self.current['tick'])
        self.assertEqual(preservation_dump(tick.body[2]),preservation_dump(ast.parse('self._drain_intent()').body[0]))
        del tick.body[2]
        self.assertEqual(preservation_dump(tick),preservation_dump(self.prior['tick']))
        close=deepcopy(self.current['close'])
        self.assertIsInstance(close.body[2],ast.If)
        self.assertEqual(preservation_dump(close.body[2].test),preservation_dump(ast.parse('self._local_intent is not None',mode='eval').body))
        del close.body[2]
        self.assertEqual(preservation_dump(close),preservation_dump(self.prior['close']))

    def test_poll_and_render_only_add_local_intent_gate_and_feedback(self):
        poll=deepcopy(self.current['poll_status'])
        condition=poll.body[1].test
        self.assertIsInstance(condition,ast.BoolOp);self.assertIsInstance(condition.op,ast.Or)
        self.assertEqual(preservation_dump(condition.values[-1]),preservation_dump(ast.parse('self._local_intent is not None',mode='eval').body))
        condition.values.pop()
        self.assertEqual(preservation_dump(poll),preservation_dump(self.prior['poll_status']))
        class Projection(ast.NodeTransformer):
            count=0
            def visit_BoolOp(self,node):
                if preservation_dump(node)==preservation_dump(ast.parse('self._local_feedback or self.action_text',mode='eval').body):
                    self.count+=1
                    return ast.parse('self.action_text',mode='eval').body
                return self.generic_visit(node)
        transform=Projection();render=transform.visit(deepcopy(self.current['render']))
        self.assertEqual(transform.count,1)
        self.assertEqual(preservation_dump(render),preservation_dump(self.prior['render']))

    def test_unrelated_transport_timer_and_owner_edits_remain_detectable(self):
        text=Path(cc.__file__).read_text(encoding='utf-8')
        for old,new in (
            ('queue.Queue(maxsize=3)','queue.Queue(maxsize=4)'),
            ('self.root.after(100,self._tick)','self.root.after(101,self._tick)'),
            ("self.worker.start()","self.worker.close()"),
            ("self.stop_recorded=True","self.stop_recorded=False")):
            self.assertIn(old,text)
            changed=ast.parse(text.replace(old,new,1))
            self.assertNotEqual(preservation_dump(restore_predecessor(changed)),preservation_dump(self.before),old)

    def test_signature_change_is_refused_and_historical_lineage_still_matches(self):
        changed=deepcopy(self.after)
        method=next(n for n in controller(changed).body if isinstance(n,ast.FunctionDef) and n.name=='tick')
        method.args.args.append(ast.arg(arg='unexpected'))
        with self.assertRaisesRegex(AssertionError,'signature'):restore_predecessor(changed)
        from test_desktop_gui_installation import normalized_source
        record=json.loads((ROOT/'tests/desktop_gui_support/source-lineage.json').read_text())
        before=(ROOT/'provenance/desktop-control-intent/control_client.before.py').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(normalized_source(before,'control_client').encode()).hexdigest(),
            record['modules']['control_client']['normalized_ast_sha256'])


if __name__=='__main__':unittest.main()
