"""Actual serialized request audit with an injected reply; no SDK/network/model."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.hermes import report_contract as wire
from adaptive_inference.task_spec import TaskSpec
from test_compiler_task_spec import compiler_data
from task_spec_support import spec_data


class CompilerWireBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        (self.run/'phase.txt').write_text('parent', encoding='utf-8')
        self.spec = TaskSpec(compiler_data())
        self.sent = []
        # Boundary imports httpx for real response construction/network errors.
        # These non-fixture audit cases use neither: the owned transport is an
        # injected reply, and the exact serialized request still traverses send.
        self.httpx = mock.patch.dict(sys.modules, {'httpx': SimpleNamespace()})
        self.httpx.start(); self.addCleanup(self.httpx.stop)

    def boundary(self, **kwargs):
        result = wire.Boundary(self.run, False, **kwargs)
        result.original = self.transport
        return result

    def request(self, names=('read_file', 'write_file', 'build_and_test'), **overrides):
        body = {'model': wire.MODEL, **deepcopy(wire.QUALITY),
                'messages': [{'role': 'user', 'content': self.spec.prompt}],
                'tools': [{'type': 'function', 'function': {'name': name,
                           'parameters': {'type': 'object', 'properties': {}}}} for name in names]}
        body.update(overrides)
        return SimpleNamespace(method='POST', url=wire.BASE+'/chat/completions', headers={},
                               content=json.dumps(body, sort_keys=True).encode('utf-8'))

    def transport(self, client, request, **kwargs):
        self.sent.append(request.content)
        payload = {'model': wire.MODEL,
                   'choices': [{'message': {'role': 'assistant', 'content': 'Done.'}, 'finish_reason': 'stop'}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}}
        return SimpleNamespace(status_code=200, content=json.dumps(payload).encode(),
            headers={'X-Adaptive-Class': 'normal', 'X-Adaptive-Request-Id': 'injected-reply'},
            read=lambda: None, json=lambda: deepcopy(payload))

    def test_declared_compiler_request_reaches_existing_transport_and_audit(self):
        boundary = self.boundary(task_spec=self.spec)
        request = self.request()
        response = boundary.send(None, request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sent, [request.content])
        rows = json.loads((self.run/'wire-observations.json').read_text())
        self.assertEqual(rows, boundary.rows)
        self.assertEqual(rows[0]['tool_names'], ['build_and_test', 'read_file', 'write_file'])
        self.assertEqual(rows[0]['body_sha256'], wire.digest(request.content))
        self.assertEqual(rows[0]['gateway_request_id'], 'injected-reply')

    def test_default_and_file_task_keep_the_original_file_scope(self):
        for kwargs in ({}, {'task_spec': TaskSpec(spec_data())}):
            with self.subTest(explicit_file_task=bool(kwargs)):
                boundary = self.boundary(**kwargs)
                with self.assertRaises(wire.Refused): boundary.send(None, self.request())
                self.assertEqual(boundary.rows, [])
                for names in (('read_file', 'write_file'), ('read_file', 'write_file', 'patch', 'search_files')):
                    boundary.send(None, self.request(names))
                self.assertEqual(len(boundary.rows), 2)

    def test_compiler_scope_rejects_missing_extra_and_duplicate_tools_before_transport(self):
        boundary = self.boundary(task_spec=self.spec)
        for names in (('read_file', 'write_file'), ('read_file', 'write_file', 'build_and_test', 'terminal'),
                      ('read_file', 'write_file', 'build_and_test', 'build_and_test')):
            with self.subTest(names=names), self.assertRaises(wire.Refused):
                boundary.send(None, self.request(names))
        self.assertEqual(self.sent, [])
        self.assertEqual(boundary.rows, [])

    def test_only_exact_immutable_task_spec_can_select_compiler_scope(self):
        for value in (self.spec.data, SimpleNamespace(compiler=self.spec.compiler), True):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.boundary(task_spec=value)
        original = compiler_data()
        spec = TaskSpec(original)
        boundary = self.boundary(task_spec=spec)
        original['compiler'] = None
        self.assertEqual(boundary.send(None, self.request()).status_code, 200)

    def test_compiler_opt_in_preserves_quality_and_route_checks(self):
        boundary = self.boundary(task_spec=self.spec)
        with self.assertRaises(wire.Refused): boundary.send(None, self.request(max_tokens=100))
        request = self.request(); request.url = wire.BASE+'/other'
        with self.assertRaises(wire.Refused): boundary.send(None, request)
        self.assertEqual(self.sent, [])
        self.assertEqual(boundary.rows, [])

    def test_compiler_opt_in_preserves_duplicate_request_refusal(self):
        boundary = self.boundary(task_spec=self.spec)
        request = self.request(); boundary.send(None, request)
        with self.assertRaises(wire.Refused): boundary.send(None, request)
        self.assertEqual(self.sent, [request.content])
        self.assertEqual(len(boundary.rows), 1)


if __name__ == '__main__': unittest.main()
