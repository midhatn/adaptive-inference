# SPDX-License-Identifier: Apache-2.0
"""Offline refusal and privacy checks; no private receipts, SDK or model needed."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPOSITORY = Path(os.environ.get('ADAPTIVE_EVIDENCE_REPOSITORY', HERE.parents[2]))
spec = importlib.util.spec_from_file_location('paused_expiry_export_under_test', HERE/'export.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class FinalExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selector = export.load_module('selection.py')
        cls.retained, cls.prior, cls.h = cls.selector.helpers(REPOSITORY)
        cls.bindings = cls.h.parse((HERE/'bindings.json').read_bytes())
        cls.freeze = cls.h.parse((HERE/'reviewed-source.json').read_bytes())
        cls.result = cls.h.parse((HERE/'result.json').read_bytes())

    def selected(self, directory, blobs=None):
        blobs = blobs or {'one': b'{"number":1}', 'two': b'{"number":2}'}
        paths, pins = {}, {}
        for key, data in blobs.items():
            path = directory/(key+'.json')
            path.write_bytes(data)
            paths[key] = str(path)
            pins[key] = self.h.hash_bytes(data)
        return {'scope': 'installed-paused-expiry-03', 'inputs': paths}, {'private_input_sha256': pins}

    def test_explicit_relocated_input_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            rows = export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)
            self.assertEqual(rows, {'one': {'number': 1}, 'two': {'number': 2}})

    def test_extra_input_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            selection['inputs']['unreviewed'] = selection['inputs']['one']
            with self.assertRaisesRegex(self.h.Refused, 'input_label_set_changed'):
                export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_missing_input_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            selection['inputs'].pop('two')
            with self.assertRaisesRegex(self.h.Refused, 'input_label_set_changed'):
                export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_hash_role_swap_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            selection['inputs']['one'], selection['inputs']['two'] = selection['inputs']['two'], selection['inputs']['one']
            with self.assertRaisesRegex(self.h.Refused, 'accepted_input_changed'):
                export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_changed_receipt_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            Path(selection['inputs']['one']).write_bytes(b'{"number":3}')
            with self.assertRaisesRegex(self.h.Refused, 'accepted_input_changed'):
                export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_wrong_scope_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selection, binding = self.selected(root)
            selection['scope'] = 'source-tests-only'
            with self.assertRaisesRegex(self.h.Refused, 'selection_scope_changed'):
                export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def test_ambiguous_json_refused_even_when_hash_matches(self):
        for data in (b'{"passed":true,"passed":false}', b'{"number":NaN}'):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                selection, binding = self.selected(root, {'one': data})
                with self.assertRaises((self.h.Refused, ValueError)):
                    export.selected_inputs(self.h, self.h.Inputs(root), selection, binding)

    def source_copy(self, root):
        for name in self.freeze['files']:
            if name in export.HISTORICAL_SUPPORT:
                continue
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((REPOSITORY/name).read_bytes())

    def test_exact_historical_doc_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source_copy(root)
            path = root/'docs/paused-budget-expiry.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Current documentation can describe the accepted trial.', encoding='utf-8')
            inputs = self.h.Inputs(root)
            export.reviewed_source(self.h, inputs, root, self.bindings)
            self.assertEqual(inputs.hashes['source:docs/paused-budget-expiry.md'],
                             self.freeze['files']['docs/paused-budget-expiry.md'])
            self.assertEqual(len([x for x in inputs.hashes if x.startswith('source:')]), 120)

    def test_other_source_cannot_fallback_to_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source_copy(root)
            (root/'src/adaptive_inference/execution_clock.py').write_text('# altered', encoding='utf-8')
            with self.assertRaisesRegex(self.h.Refused, 'reviewed_source_file_changed'):
                export.reviewed_source(self.h, self.h.Inputs(root), root, self.bindings)

    def test_missing_source_cannot_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.source_copy(root)
            (root/'src/adaptive_inference/execution_clock.py').unlink()
            with self.assertRaises(FileNotFoundError):
                export.reviewed_source(self.h, self.h.Inputs(root), root, self.bindings)

    def test_extra_support_mapping_refused(self):
        altered = deepcopy(self.bindings)
        altered['reviewed_support']['src/adaptive_inference/execution_clock.py'] = 'reviewed-support/clock.py'
        with self.assertRaisesRegex(self.h.Refused, 'support_mapping_changed'):
            export.reviewed_source(self.h, self.h.Inputs(HERE), REPOSITORY, altered)

    def test_source_path_traversal_refused(self):
        with self.assertRaisesRegex(self.h.Refused, 'source_path_invalid'):
            export.contained(self.h, REPOSITORY, '../elsewhere')

    def sdk_receipt(self):
        return {'passed': True, 'tests': 3, 'failures': 0, 'errors': 0, 'skipped': 0,
                'source_unchanged': True, 'installed_mode': True, 'source_before': {'module': 'abc'},
                'source_after': {'module': 'abc'}}

    def test_installed_sdk_receipt_accepted(self):
        export.test_receipt(self.h, self.sdk_receipt(), 3, installed=True)

    def test_source_sdk_cannot_be_relabelled_installed(self):
        row = self.sdk_receipt()
        row['installed_mode'] = False
        with self.assertRaisesRegex(self.h.Refused, 'sdk_execution_mode_changed'):
            export.test_receipt(self.h, row, 3, installed=True)

    def test_sdk_mutated_source_refused(self):
        row = self.sdk_receipt()
        row['source_after']['module'] = 'changed'
        with self.assertRaisesRegex(self.h.Refused, 'test_source_changed'):
            export.test_receipt(self.h, row, 3, installed=True)

    def test_sdk_skipped_or_failed_not_accepted(self):
        for field in ('failures', 'errors', 'skipped'):
            with self.subTest(field=field):
                row = self.sdk_receipt()
                row[field] = 1
                with self.assertRaisesRegex(self.h.Refused, 'test_receipt_not_passed'):
                    export.test_receipt(self.h, row, 3, installed=True)

    def test_unreviewed_wheel_refused(self):
        with self.assertRaisesRegex(self.h.Refused, 'wheel_changed'):
            export.wheel_identity(self.h, b'not the reviewed wheel')

    def test_public_json_privacy_and_no_absolute_clock_readings(self):
        for name in ('result.json', 'manifest.json', 'bindings.json', 'reviewed-source.json'):
            self.h.privacy_check((HERE/name).read_bytes())
        prohibited = {'deadline_monotonic', 'at_deadline_clock', 'execution_now', 'reader_before_deadline_clock',
                      'reader_after_deadline_clock', 'qpc_before', 'qpc_after', 'owner_id', 'window_id',
                      'gateway_instance', 'retained_prompt_sha256', 'started_monotonic', 'finished_monotonic'}
        def scan(value):
            if isinstance(value, dict):
                self.assertFalse(prohibited.intersection(value))
                for nested in value.values():
                    scan(nested)
            elif isinstance(value, list):
                for nested in value:
                    scan(nested)
        scan(self.result)

    def test_scope_and_failed_trials_remain_distinct(self):
        result = self.result
        self.assertFalse(result['accepted_trial']['task_completed'])
        self.assertEqual(result['accepted_trial']['task_state'], 'pending_paused_sealed')
        self.assertEqual(result['accepted_trial']['provider_calls'], 2)
        self.assertEqual(result['accepted_trial']['post_expiry_availability']['successful_post_expiry_gets'], 55)
        self.assertFalse(result['accepted_trial']['observer']['cleanup_proven_by_observer'])
        self.assertTrue(all(value is False for value in result['limitations'].values()))
        self.assertEqual(set(result['failed_trials']), {'expiry01_clock', 'expiry02_tool_thread'})
        self.assertTrue(all(row['case_accepted'] is False for row in result['failed_trials'].values()))
        self.assertNotEqual(result['failed_trials']['expiry01_clock']['independent_audit_sha256'],
                            result['failed_trials']['expiry02_tool_thread']['independent_audit_sha256'])

    def test_manifest_binds_result_and_writer(self):
        manifest = self.h.parse((HERE/'manifest.json').read_bytes())
        self.assertEqual(manifest['files'], {'result.json': self.h.hash_bytes((HERE/'result.json').read_bytes())})
        self.assertEqual(self.result['selection_exporter_sha256'], self.h.hash_bytes((HERE/'export.py').read_bytes()))
        self.assertEqual(manifest['sanitizer_sha256'], self.result['selection_exporter_sha256'])

    def test_fresh_output_required_before_private_input_read(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(export.main(['--repository', str(REPOSITORY), '--selection', str(Path(folder)/'missing.json'),
                                          '--output', folder]), 2)


if __name__ == '__main__':
    unittest.main()
