# SPDX-License-Identifier: Apache-2.0
"""Portable synthetic export checks; no private case inputs or live acceptance."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parent.parent
HERE = REPOSITORY/'provenance/task-handover/acceptance'


class TaskHandoverAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('case17_export_tests', HERE/'export.py')
        cls.export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.export)
        cls.foundation, _, cls.h = cls.export.helpers(REPOSITORY)

    def example(self):
        # Synthetic minimal projection input, not qualification evidence.
        task = {'artifact': {'total_units': 23}, 'artifact_sha256': 'a'*64,
                'wire': [{}, {}, {}], 'effects': [{}]}
        evidence = {'tasks': [task, deepcopy(task)], 'safe_wait': {
            'sealed_before': {'checkpoint': {'state': {
                'adaptive_inference.execution_outcome.v1': {'sealed_at_monotonic': 1750.0}}}},
            'grant': {'authorized_at': 1755.0}}}
        ui = {key+'_clicks': 0 if key in ('pause', 'retry') else 1
              for key in ('resume_a', 'continue', 'new_task', 'resume_b', 'stop', 'pause', 'retry')}
        ui.update(new_task_qpc_before=1800.0, stop_qpc_before=1900.0,
            rejected_input_attempts=[{'action': 'set_value task picker File name',
                'error': 'Cannot set a value for an element that is not settable'}])
        activity = {'actions': [{'qpc_before': 1050.0+i*30, 'qpc_after': 1051.0+i*30}
                               for i in range(24)] + [{'qpc_before': 1760.0, 'qpc_after': 1761.0}]}
        return evidence, ui, activity

    def test_projection_preserves_misses_and_failed_input_without_postseal_credit(self):
        value = self.export.project(self.h, *self.example(), {})
        self.assertEqual(value['provider_calls'], 6)
        self.assertEqual(value['physical_writes'], 2)
        self.assertEqual(value['welcome']['acceptance'], 'format-only')
        self.assertEqual(value['foreground']['target_misses'], 23)
        self.assertEqual(value['foreground']['postseal_actions_excluded'], 1)
        self.assertEqual(value['foreground']['preseal_tail_s'], 10)
        self.assertEqual(value['unsuccessful_input']['count'], 1)
        self.assertEqual(value['relative_seconds_after_expiry_seal']['continue_committed'], 5)
        self.h.privacy_check(self.h.encoded(value))

    def test_private_extras_and_absolute_clocks_are_not_projected(self):
        e, ui, activity = self.example()
        private = r'C:\Users\private-person\secret-transcript.txt'
        for row in (e, ui, activity):
            row.update(prompt=private, pid=918273, hwnd=671234, messages=[private],
                       native_history=[private], absolute_clock=123456789)
        raw = self.h.encoded(self.export.project(self.h, e, ui, activity, {}))
        self.h.privacy_check(raw)
        for marker in (private.encode(), b'private-person', b'918273', b'671234', b'123456789', b'absolute_clock'):
            self.assertNotIn(marker, raw)

    def test_changed_counters_controls_or_lost_failure_are_refused(self):
        mutations = (
            lambda e, u, a: e['tasks'][0]['wire'].append({}),
            lambda e, u, a: e['tasks'][1]['effects'].append({}),
            lambda e, u, a: u.update(continue_clicks=True),
            lambda e, u, a: u.update(rejected_input_attempts=[]),
            lambda e, u, a: a['actions'][1].update(qpc_after=1110.0),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                values = self.example(); mutate(*values)
                with self.assertRaises(self.h.Refused):
                    self.export.project(self.h, *values, {})

    def test_fixed_role_substitution_and_missing_role_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); one, two = root/'one.json', root/'two.json'
            one.write_bytes(b'{"passed":true}'); two.write_bytes(b'{"passed":false}')
            binding = {'private_input_sha256': {'primary_audit': self.h.hash_bytes(one.read_bytes())}}
            selection = {'scope': self.export.SCOPE, 'inputs': {'primary_audit': str(two)}}
            with self.assertRaises(self.h.Refused):
                self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)
            selection['inputs'] = {'foreground_audit': str(one)}
            with self.assertRaises(self.h.Refused):
                self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_duplicate_or_nonfinite_json_is_refused_even_when_hash_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'invalid.json'
            for raw in (b'{"passed":true,"passed":false}', b'{"clock":NaN}'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    binding = {'private_input_sha256': {'primary_audit': self.h.hash_bytes(raw)}}
                    selection = {'scope': self.export.SCOPE, 'inputs': {'primary_audit': str(path)}}
                    with self.assertRaises(self.h.Refused):
                        self.export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_actual_selection_is_fixed_to_both_audits_and_complete_role_set(self):
        inputs = self.h.Inputs(HERE)
        binding = self.export.support(self.h, inputs, 'bindings.json')
        self.assertEqual(set(binding['private_input_sha256']), self.export.ROLES)
        self.assertEqual(binding['private_input_sha256']['primary_audit'],
            '6a0e6f14360a4aed403ab1efdbb946daf6c0f151162aad24bf4e3141aa81b4d0')
        self.assertEqual(binding['private_input_sha256']['foreground_audit'],
            '8fa5059cb817e5ebd8228ead738bc36e8e388b2abba53d0f3dc75ba7b7431cc5')
        self.assertEqual(len(binding['terminal_checks']), 99)

    def test_definitions_exclude_module_imports_and_side_effects(self):
        namespace = {}
        raw = b'import unavailable_runtime\nraise RuntimeError("not allowed")\nVALUE=4\ndef pure(x): return x+VALUE\n'
        self.export.definitions(self.h, raw, ['pure'], namespace)
        self.assertEqual(namespace['pure'](3), 7)
        self.assertNotIn('unavailable_runtime', namespace)

    def test_fresh_output_and_missing_private_input_refuse_without_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for output, reason in ((root, 'output_not_fresh'), (root/'new', 'FileNotFoundError')):
                stream = io.StringIO()
                with redirect_stdout(stream):
                    rc = self.export.main(['--repository', str(REPOSITORY), '--selection',
                        str(root/'private-person-secret.json'), '--output', str(output)])
                self.assertEqual(rc, 2)
                self.assertEqual(json.loads(stream.getvalue())['reason'], reason)
                self.assertNotIn('private-person', stream.getvalue())
                if output != root: self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
