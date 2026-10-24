# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
import httpx

spec = importlib.util.spec_from_file_location("bounded_task", Path(__file__).with_name("run_task.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "phase.txt").write_text("parent", encoding="utf-8")
        self.boundary = m.Boundary(self.root, True)
        self.body = {"model": m.MODEL, "messages": [{"role": "user", "content": "fixture"}],
                     "tools": [{"type": "function", "function": {"name": n}} for n in ("read_file", "write_file")], **m.QUALITY}
    def tearDown(self): self.tmp.cleanup()
    def request(self, body=None, headers=None, url=None):
        return httpx.Request("POST", url or m.BASE + "/chat/completions", json=body or self.body, headers=headers)
    def test_full_quality_and_tools(self):
        self.assertEqual(self.boundary.send(None, self.request()).status_code, 200)
        self.assertEqual(self.boundary.rows[0]["quality"], m.QUALITY)
        self.assertNotIn("assistant", self.boundary.rows[0])
        self.assertIn("assistant_sha256", self.boundary.rows[0])
    def test_portable_paths_and_url_admission(self):
        before = m.SDK, m.PYTHON, m.PLUGIN_SOURCE, m.BASE, m.MODEL
        try:
            m.configure_inputs(self.root, sys.executable, self.root, "http://127.0.0.1:18222/v1", m.MODEL)
            self.assertEqual(m.BASE, "http://127.0.0.1:18222/v1")
            for url in ("http://127.0.0.1:0/v1", "http://127.0.0.1:65536/v1",
                        "http://127.0.0.1:18100/v1?key=x", "http://localhost:18100/v1",
                        "http://127.0.0.1:18100/\nv1", "http://127.0.0.1:18100\\/v1"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    m.configure_inputs(self.root, sys.executable, self.root, url, m.MODEL)
            with self.assertRaises(ValueError):
                m.configure_inputs(self.root, sys.executable, self.root, m.BASE, "different-model")
        finally:
            m.SDK, m.PYTHON, m.PLUGIN_SOURCE, m.BASE, m.MODEL = before
    def test_changed_prepared_quality_refused(self):
        m.save(self.root / "plan.json", {"quality": {"max_tokens": 1024}})
        with self.assertRaises(ValueError): m.load_plan(self.root)
    def test_tool_hook_fails_closed_on_malformed_path_and_phase(self):
        spec = importlib.util.spec_from_file_location("audit", Path(__file__).with_name("audit_plugin.py"))
        audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
        hooks = {}
        class Context:
            def register_hook(self, name, fn): hooks[name] = fn
        with patch.dict("os.environ", {"ADAPTIVE_TASK_RUN": str(self.root)}):
            audit.register(Context())
        for args in (["not", "a", "mapping"], {"path": "bad\x00path"}, {"path": "../secret"}):
            self.assertEqual(hooks["pre_tool_call"](tool_name="read_file", args=args)["action"], "block")
        (self.root / "phase.txt").write_text("unexpected", encoding="utf-8")
        self.assertEqual(hooks["pre_tool_call"](tool_name="read_file", args={"path": "orders.csv"})["action"], "block")
    def test_each_quality_change_refuses_before_dispatch(self):
        for field in m.QUALITY:
            body = dict(self.body); body.pop(field)
            with self.subTest(field=field), self.assertRaises(m.Refused): self.boundary.send(None, self.request(body))
        self.assertEqual(self.boundary.rows, [])
    def test_child_requires_plugin_header(self):
        (self.root / "phase.txt").write_text("child", encoding="utf-8")
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request())
        self.boundary.send(None, self.request(headers={"X-Adaptive-Class": "background"}))
    def test_foreground_and_manual_metadata_not_demoted(self):
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request(headers={"X-Adaptive-Class": "background"}))
        for key in ("strata_scheduling", "adaptive_scheduling"):
            with self.assertRaises(m.Refused): self.boundary.send(None, self.request({**self.body, key: {"class": "normal"}}))
    def test_duplicate_post_has_no_second_dispatch(self):
        self.boundary.send(None, self.request())
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request())
        self.assertEqual(len(self.boundary.rows), 1)
    def test_wrong_url_and_tools_refused(self):
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request(url="https://example.invalid/v1/chat/completions"))
        body = {**self.body, "tools": self.body["tools"] + [{"function": {"name": "terminal"}}]}
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request(body))
    def test_no_reduced_output_budget(self):
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request({**self.body, "max_tokens": 1024}))
    def test_request_count_bound(self):
        self.boundary.steps["parent"] = 8
        with self.assertRaises(m.Refused): self.boundary.send(None, self.request())
    def test_gateway_history_requires_identity_and_exact_ids(self):
        data = {"service": "adaptive-inference", "instance": "instance", "backend": "strata",
                "scheduler": {"active": False, "pending": 0, "completed": 0}, "history": []}
        response = httpx.Response(200, json=data, request=httpx.Request("GET", m.BASE))
        with patch.object(httpx.Client, "get", return_value=response):
            self.assertEqual(m.gateway_metrics(self.root, "before", None, []), "instance")
            with self.assertRaises(m.Refused): m.gateway_metrics(self.root, "restart", "different", [])
            with self.assertRaises(m.Refused): m.gateway_metrics(self.root, "missing", "instance", [{"class": "normal"}])


if __name__ == "__main__": unittest.main()
