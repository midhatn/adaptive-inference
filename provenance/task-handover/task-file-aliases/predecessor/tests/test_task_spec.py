"""Portable contract, staging and artifact checks; no agent/provider execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from adaptive_inference.task_spec import TaskSpec, NAMESPACE, canonical, digest
from adaptive_inference.desktop.hermes.run_recovery import prepared_contract
from task_spec_support import spec_data


class TaskSpecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'source'; self.source.mkdir()
        self.work = self.root/'work'; self.work.mkdir()
        (self.source/'notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.spec = TaskSpec(spec_data())

    def test_immutable_exact_original_prompt_and_detached_data(self):
        raw = spec_data(prompt='  Keep my original words: مرحبا.\n')
        spec = TaskSpec(raw); original = spec.sha256
        raw['prompt'] = 'changed'; copy = spec.data; copy['inputs'].clear()
        self.assertEqual(spec.prompt, '  Keep my original words: مرحبا.\n')
        self.assertEqual(spec.sha256, original); self.assertEqual(len(spec.data['inputs']), 1)
        self.assertEqual(TaskSpec.from_metadata(spec.metadata()), spec)

    def test_prompt_limit_counts_utf8_bytes(self):
        TaskSpec(spec_data(prompt='é' * 8192))
        with self.assertRaises(ValueError): TaskSpec(spec_data(prompt='é' * 8193))

    def test_serialized_duplicate_nonfinite_and_oversize_refused(self):
        for raw in (b'{"schema":0,"schema":1}', b'{"x":NaN}', b'{"x":1e9999}', b' ' * 65537):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError): TaskSpec.from_bytes(raw)

    def test_exact_supported_budget_no_bool_or_extra_configuration(self):
        for key, value in [('max_requests', 9), ('execution_seconds', 901), ('max_attempts', True), ('model', 'other')]:
            raw = spec_data(); raw['budget'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): TaskSpec(raw)
        raw = spec_data(); raw['model'] = 'not task data'
        with self.assertRaises(ValueError): TaskSpec(raw)

    def test_flat_case_insensitive_disjoint_names(self):
        for name in ('../answer.txt', 'a/b.txt', 'a\\b.txt', '/answer.txt', 'C:answer.txt', 'NUL.txt', 'answer.', 'NOTES.TXT'):
            raw = spec_data(); raw['outputs'][0]['name'] = name
            with self.subTest(name=name), self.assertRaises(ValueError): TaskSpec(raw)

    def test_file_count_input_size_and_output_character_caps(self):
        candidates = []
        raw = spec_data(); raw['inputs'] *= 17; candidates.append(raw)
        raw = spec_data(); raw['inputs'][0]['bytes'] = 262145; candidates.append(raw)
        raw = spec_data(); raw['outputs'][0]['max_chars'] = 4097; candidates.append(raw)
        for raw in candidates:
            with self.assertRaises(ValueError): TaskSpec(raw)

    def test_staging_preserves_bytes_and_refuses_overwrite(self):
        self.spec.stage_inputs(self.source, self.work)
        self.assertEqual((self.work/'notes.txt').read_bytes(), (self.source/'notes.txt').read_bytes())
        with self.assertRaises(FileExistsError): self.spec.stage_inputs(self.source, self.work)

    def test_changed_input_refuses_before_and_after_staging(self):
        self.spec.stage_inputs(self.source, self.work)
        (self.work/'notes.txt').write_text('changed')
        with self.assertRaises(ValueError): self.spec.verify_inputs(self.work)
        (self.source/'notes.txt').write_text('changed')
        with self.assertRaises(ValueError): self.spec.stage_inputs(self.source, self.work)

    def test_declared_file_scope_rejects_absolute_and_other_tasks(self):
        self.spec.stage_inputs(self.source, self.work)
        for name in (str(self.work/'notes.txt'), 'other.txt', '../source/notes.txt', 'notes.txt/child'):
            with self.subTest(name=name), self.assertRaises(ValueError): self.spec.file_path(self.work, name)
        with self.assertRaises(ValueError): self.spec.file_path(self.work, 'notes.txt', write=True)

    def test_hard_link_input_refused(self):
        import os
        os.link(self.source/'notes.txt', self.source/'alias.txt')
        with self.assertRaises(ValueError): self.spec.verify_inputs(self.source)

    def test_metadata_and_plan_digest_tamper_refused(self):
        metadata = self.spec.metadata(); metadata[NAMESPACE]['spec']['prompt'] = 'different'
        with self.assertRaises(ValueError): TaskSpec.from_metadata(metadata)
        plan = {'task_id': 'arbitrary', 'task_spec': self.spec.data, 'task_spec_sha256': self.spec.sha256}
        self.assertEqual(prepared_contract(plan), self.spec)
        plan['task_spec_sha256'] = '0'*64
        with self.assertRaises(ValueError): prepared_contract(plan)
        with self.assertRaises(ValueError): prepared_contract({'task_id': 'arbitrary'})
        self.assertIsNone(prepared_contract({'task_id': 'orders-report'}))

    def test_raw_file_pin_is_distinct_from_canonical_spec_digest(self):
        raw = json.dumps(self.spec.data, indent=2).encode(); path = self.root/'task.json'; path.write_bytes(raw)
        self.assertEqual(TaskSpec.read(path, digest(raw)), self.spec)
        with self.assertRaises(ValueError): TaskSpec.read(path, self.spec.sha256)

    def test_json_oracle_is_generic_and_feedback_does_not_reveal_expected_value(self):
        expected = {'restock': {'paper': 17}}
        spec = TaskSpec(spec_data(outputs=[('result.json', 'json')], expected={'result.json': expected}))
        bad = spec.validate_write('write_file', {'path': 'result.json', 'content': '{"restock":{"paper":3}}'})
        self.assertFalse(bad.accepted); self.assertNotIn('17', bad.feedback); self.assertNotIn('paper', bad.feedback)
        self.assertTrue(spec.validate_write('write_file', {'path': 'result.json', 'content': json.dumps(expected)}).accepted)

    def test_duplicate_nonfinite_and_json_type_mismatch_never_pass_oracle(self):
        spec = TaskSpec(spec_data(outputs=[('result.json', 'json')], expected={'result.json': {'count': 1}}))
        for content in ('{"count":1,"count":1}', '{"count":NaN}', '{"count":true}', '{"count":1.0}', '{"count":1e9999}'):
            with self.subTest(content=content):
                self.assertFalse(spec.validate_write('write_file', {'path':'result.json','content':content}).accepted)

    def test_unknown_validator_and_optional_oracle_output_refused(self):
        raw = spec_data(outputs=[('result.json','json')], expected={'result.json': {}})
        raw['validation']['validator']['id'] = 'import:user.code'
        with self.assertRaises(ValueError): TaskSpec(raw)
        raw['validation']['validator']['id'] = 'json-equals.v1'; raw['outputs'][0]['required'] = False
        with self.assertRaises(ValueError): TaskSpec(raw)

    def test_answer_only_has_no_semantic_correctness_claim(self):
        spec = TaskSpec(spec_data(inputs={}, outputs=[], prompt='Explain this concept.'))
        result = spec.completion(self.work, [], 'An explanation.')
        self.assertEqual(result, {'artifacts':{}, 'semantic_validation':'not_checked','validated_artifacts':[]})
        with self.assertRaises(ValueError): spec.completion(self.work, [], '')

    def test_unreceipted_or_missing_output_cannot_complete(self):
        self.spec.stage_inputs(self.source, self.work)
        with self.assertRaises(ValueError): self.spec.completion(self.work, [], 'done')
        (self.work/'answer.txt').write_text('answer')
        with self.assertRaises(ValueError): self.spec.completion(self.work, [], 'done')

    def test_completion_checks_actual_output_and_receipt_digest(self):
        self.spec.stage_inputs(self.source, self.work); (self.work/'answer.txt').write_bytes(b'answer')
        tool = {'name':'write_file','args':{'path':'answer.txt'},'artifact_sha256':digest(b'answer')}
        result = self.spec.completion(self.work,[tool],'done')
        self.assertEqual(result['semantic_validation'],'not_checked')
        (self.work/'answer.txt').write_text('changed')
        with self.assertRaises(ValueError): self.spec.completion(self.work,[tool],'done')
