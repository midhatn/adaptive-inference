"""Freeze the unchanged ownership, task, demand, mailbox and feedback contracts."""
import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def parsed(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def dumped(node):
    return ast.dump(node, include_attributes=False)


class PreservationTests(unittest.TestCase):
    def test_original_task_store_identity_and_unmodified_ownership_contracts(self):
        prior = ROOT / "predecessor/src/adaptive_inference/task_store.py"
        current = ROOT / "src/adaptive_inference/task_store.py"
        self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(),
                         "39f4efaa0983fea5202ac1027f12c7638787e7da874e26b678a9a3812b1afacc")
        old, new = parsed(prior), parsed(current)
        old_nodes = {node.name: node for node in old.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        new_nodes = {node.name: node for node in new.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        for name, node in old_nodes.items():
            if name != "TaskStore":
                self.assertEqual(dumped(node), dumped(new_nodes[name]), name)
        old_methods = {node.name: node for node in old_nodes["TaskStore"].body if isinstance(node, ast.FunctionDef)}
        new_methods = {node.name: node for node in new_nodes["TaskStore"].body if isinstance(node, ast.FunctionDef)}
        for name, node in old_methods.items():
            if name not in ("__init__", "_verify_existing", "_connection"):
                self.assertEqual(dumped(node), dumped(new_methods[name]), name)
        old_constants = {node.targets[0].id: node for node in old.body
                         if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        new_constants = {node.targets[0].id: node for node in new.body
                         if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        for name, node in old_constants.items():
            self.assertEqual(dumped(node), dumped(new_constants[name]), name)

    def test_original_connection_body_is_only_moved_under_gate(self):
        old = parsed(ROOT / "predecessor/src/adaptive_inference/task_store.py")
        new = parsed(ROOT / "src/adaptive_inference/task_store.py")
        old_class = next(node for node in old.body if isinstance(node, ast.ClassDef) and node.name == "TaskStore")
        new_class = next(node for node in new.body if isinstance(node, ast.ClassDef) and node.name == "TaskStore")
        before = next(node for node in old_class.body if isinstance(node, ast.FunctionDef) and node.name == "_connection")
        after = next(node for node in new_class.body if isinstance(node, ast.FunctionDef) and node.name == "_connection_locked")
        after.name = "_connection"
        for node in ast.walk(after):
            if isinstance(node, ast.Attribute) and node.attr == "_verify_existing_locked":
                node.attr = "_verify_existing"
        self.assertEqual(dumped(before), dumped(after))

    def test_consumers_and_all_previous_tests_are_byte_exact(self):
        for relative in (
            "src/adaptive_inference/__init__.py", "src/adaptive_inference/demand.py",
            "src/adaptive_inference/feedback.py", "src/adaptive_inference/control_mailbox.py",
            "tests/test_task_store.py", "tests/test_demand.py",
            "tests/test_persistent_feedback.py", "tests/test_control_mailbox.py",
        ):
            self.assertEqual((ROOT / relative).read_bytes(), (ROOT / "predecessor" / relative).read_bytes(), relative)


if __name__ == "__main__":
    unittest.main()
