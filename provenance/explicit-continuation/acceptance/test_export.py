# SPDX-License-Identifier: Apache-2.0
"""Portable synthetic projection/refusal checks; these never accept a live run."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class ContinuationExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = load(HERE/'export.py', 'continuation_public_export')
        cls.prior, cls.h, cls.checks = cls.export.helpers(REPOSITORY)
        # The retained fixture imports constants from the exact reviewed module.
        previous = sys.modules.get('continuation_export_checks')
        sys.modules['continuation_export_checks'] = cls.checks
        try:
            cls.fixture = staticmethod(load(HERE/'synthetic.py', 'continuation_synthetic').fixture)
        finally:
            if previous is None:
                sys.modules.pop('continuation_export_checks', None)
            else:
                sys.modules['continuation_export_checks'] = previous

    def example(self):
        e = self.fixture()
        e['gui_binding']['hwnd'] = 42
        e['readiness']['gui_binding']['hwnd'] = 42
        ui = dict(first_resume_clicks=1, manual_pause_clicks=1, continue_clicks=1,
                  stop_clicks=1, retry_clicks=0, window_id=42, stop_qpc_before=1105.0,
                  post_expiry_gui={'same_window': True},
                  post_continue_gui={'same_window': True, 'task_accepted': True})
        return e, ui

    def test_synthetic_projection_preserves_only_bounded_outcome(self):
        e, ui = self.example()
        value = self.export.project(self.h, self.checks, e, ui)
        self.assertEqual(value['execution_generations'], [0, 1])
        self.assertEqual(value['provider_requests'], dict(before_continue=1, after_continue=2, new_requests=1, cumulative_limit=8))
        self.assertEqual(value['physical_writes'], 1)
        self.assertAlmostEqual(value['relative_seconds_after_expiry_seal']['grant_committed'], 1.9)
        self.h.privacy_check(self.h.encoded(value))

    def test_private_extras_are_not_serialized(self):
        e, ui = self.example()
        private = r'C:\Users\private-person\secret-transcript.txt'
        for value in (e, ui):
            value.update(prompt=private, pid=918273, hwnd=671234, messages=[private], extra={'absolute_clock': 123456789})
        raw = self.h.encoded(self.export.project(self.h, self.checks, e, ui))
        self.h.privacy_check(raw)
        for value in (private.encode(), b'private-person', b'918273', b'671234', b'123456789', b'absolute_clock'):
            self.assertNotIn(value, raw)

    def test_core_counter_effect_readiness_and_lifetime_refusals(self):
        for mutate in (
            lambda e: e['selected']['state'].update(requests=0),
            lambda e: e['effects'].append(deepcopy(e['effects'][0])),
            lambda e: e['readiness']['value']['selected_execution'].update(execution_generation=0),
            lambda e: e.update(worker_result_sha256='f'*64),
        ):
            with self.subTest(mutate=mutate):
                e, ui = self.example(); mutate(e)
                with self.assertRaises((AssertionError, self.h.Refused)):
                    self.export.project(self.h, self.checks, e, ui)

    def test_click_bool_and_absolute_order_refused(self):
        e, ui = self.example()
        ui['continue_clicks'] = True
        with self.assertRaises(self.h.Refused):
            self.export.project(self.h, self.checks, e, ui)
        ui['continue_clicks'] = 1; ui['stop_qpc_before'] = 1000.0
        with self.assertRaises(self.h.Refused):
            self.export.project(self.h, self.checks, e, ui)

    def test_role_substitution_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root/'first.json', root/'second.json'
            first.write_bytes(b'{"passed":true}'); second.write_bytes(b'{"passed":false}')
            binding = {'private_input_sha256': {'audit': self.h.hash_bytes(first.read_bytes())}}
            selection = {'scope': self.export.SCOPE, 'inputs': {'audit': str(second)}}
            with self.assertRaises(self.h.Refused):
                self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)
            selection['inputs'] = {'evidence': str(first)}
            with self.assertRaises(self.h.Refused):
                self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_exact_hash_does_not_allow_duplicate_or_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'invalid.json'
            for raw in (b'{"passed":true,"passed":false}', b'{"value":NaN}'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    binding = {'private_input_sha256': {'audit': self.h.hash_bytes(raw)}}
                    selection = {'scope': self.export.SCOPE, 'inputs': {'audit': str(path)}}
                    with self.assertRaises(self.h.Refused):
                        self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_checks_private_identity_normalization(self):
        result = self.export.normalized_checks(self.h, {'passed': True,
            'checks': {'native_owner_private-456': True, 'real_input_equality': True}})
        self.assertEqual(result, {'native_owner_check_1': True, 'real_input_equality': True})
        self.assertNotIn('private', json.dumps(result))
        with self.assertRaises(self.h.Refused):
            self.export.normalized_checks(self.h, {'passed': True, 'checks': {'real_input_equality': 1}})

    def test_binding_and_missing_input_refuse_without_disclosure(self):
        binding = self.h.parse((HERE/'bindings.json').read_bytes())
        self.export.enabled_binding(self.h, binding)
        self.assertEqual(binding['terminal_audit_sha256'],
            'f0ba3661c4f19ddf9cfdac703f64f77bcfa7703442d0f52abe8c30573472fb3b')
        disabled = {**binding, 'enabled': False}
        with self.assertRaisesRegex(self.h.Refused, 'acceptance_not_bound'):
            self.export.enabled_binding(self.h, disabled)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root/'output'
            stream = io.StringIO()
            with redirect_stdout(stream):
                rc = self.export.main(['--repository', str(REPOSITORY), '--selection',
                    str(root/'private-person-secret.json'), '--output', str(output)])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(stream.getvalue())['reason'], 'FileNotFoundError')
            self.assertFalse(output.exists())
            self.assertNotIn('private-person', stream.getvalue())

    def test_output_must_be_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stream = io.StringIO()
            with redirect_stdout(stream):
                rc = self.export.main(['--repository', str(REPOSITORY), '--selection',
                    str(root/'missing.json'), '--output', str(root)])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(stream.getvalue())['reason'], 'output_not_fresh')


if __name__ == '__main__':
    unittest.main()
