"""Compiler contract checks only; receipts are fixtures, not native build evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from adaptive_inference.task_spec import (TaskSpec, BUDGET, COMPILER_RECIPE,
                                          COMPILER_SCHEMA, canonical, digest)
from task_spec_support import spec_data


def compiler_data(*, expected_stdout='23 units', max_runs=2):
    value = spec_data(inputs={}, outputs=[], prompt='Compile and test C++ that prints the requested result.')
    value.update(schema=COMPILER_SCHEMA, compiler={
        'recipe_id': COMPILER_RECIPE, 'expected_stdout': expected_stdout,
        'max_source_chars': 16384, 'max_runs': max_runs})
    return value


def receipt(spec, *, operation='operation-1', call='call-1', source='int main() {}', status='passed'):
    value = {'operation_id': operation, 'tool_call_id': call, 'spec_sha256': spec.sha256,
             'recipe_id': COMPILER_RECIPE, 'source_sha256': digest(source.encode('utf-8')),
             'status': status, 'owned_processes_exited': True}
    if status == 'passed':
        value.update(stdout_sha256=digest(spec.compiler['expected_stdout'].encode('utf-8')),
                     artifact_sha256=digest(b'fixture artifact'), test_report_sha256=digest(b'fixture tests'))
    return value


class CompilerTaskSpecTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.spec = TaskSpec(compiler_data())

    def test_explicit_compiler_contract_preserves_prompt_budget_and_immutable_identity(self):
        raw = compiler_data(expected_stdout='نتيجة\r\n')
        raw['prompt'] = '  Keep this original objective.\n'
        spec = TaskSpec(raw)
        original = spec.sha256
        raw['compiler']['max_runs'] = 8
        spec.compiler['expected_stdout'] = 'changed'
        self.assertEqual(spec.sha256, original)
        self.assertEqual(spec.prompt, '  Keep this original objective.\n')
        self.assertEqual(spec.data['budget'], BUDGET)
        self.assertEqual(spec.compiler['expected_stdout'], 'نتيجة\r\n')
        self.assertEqual(TaskSpec.from_metadata(spec.metadata()), spec)
        self.assertEqual(TaskSpec.from_bytes(canonical(spec.data)), spec)

    def test_only_supported_bounded_contract_and_original_budget_are_accepted(self):
        for key, value in (('recipe_id', 'shell'), ('max_source_chars', 16385),
                           ('max_runs', 9), ('max_runs', True), ('max_source_chars', 0),
                           ('expected_stdout', 'é' * 2049), ('command', 'cmake')):
            raw = compiler_data()
            raw['compiler'][key] = value
            with self.subTest(key=key, value=repr(value)[:40]), self.assertRaises(ValueError):
                TaskSpec(raw)
        raw = compiler_data(); raw['budget']['execution_seconds'] = 901
        with self.assertRaises(ValueError): TaskSpec(raw)
        raw = compiler_data(); del raw['compiler']
        with self.assertRaises(ValueError): TaskSpec(raw)
        self.assertEqual(TaskSpec(compiler_data(expected_stdout='é' * 2048)).compiler['max_runs'], 2)

    def test_source_corrections_are_new_bounded_proposals_without_file_authority(self):
        first = {'recipe_id': COMPILER_RECIPE, 'source': 'int main() { invalid; }'}
        corrected = {'recipe_id': COMPILER_RECIPE, 'source': 'int main() { return 0; }'}
        self.assertTrue(self.spec.validate_compiler_args(first).accepted)
        self.assertTrue(self.spec.validate_compiler_args(corrected, completed_runs=1).accepted)
        self.assertFalse(self.spec.validate_compiler_args(corrected, completed_runs=2).accepted)
        for args in ({**corrected, 'path': 'main.cpp'}, {**corrected, 'command': 'cmake'},
                     {**corrected, 'recipe_id': 'other'}, {**corrected, 'source': 'x' * 16385},
                     {**corrected, 'source': ' '}, {**corrected, 'source': '\x00'},
                     {**corrected, 'source': '\ud800'}):
            with self.subTest(args=repr(args)[:90]):
                self.assertFalse(self.spec.validate_compiler_args(args).accepted)
        with self.assertRaises(ValueError): self.spec.validate_compiler_args(corrected, completed_runs=True)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_failed_then_corrected_attempt_requires_success_and_retains_attempt_count(self):
        failed = receipt(self.spec, source='int main() { invalid; }', status='failed')
        passed = receipt(self.spec, operation='operation-2', call='call-2', source='int main() { return 0; }')
        original = deepcopy([failed, passed])
        self.assertFalse(self.spec.compiler_completion([failed])['qualified'])
        with self.assertRaises(ValueError):
            self.spec.completion(self.work, [], 'Claimed success.', compiler_receipts=[failed])
        result = self.spec.completion(self.work, [], 'Compiler tests passed.', compiler_receipts=[failed, passed])
        self.assertTrue(result['compiler']['qualified'])
        self.assertEqual(result['compiler']['attempts'], 2)
        self.assertEqual(result['compiler']['successful']['operation_id'], 'operation-2')
        self.assertEqual(result['compiler']['successful']['source_sha256'], passed['source_sha256'])
        self.assertEqual([failed, passed], original)
        with self.assertRaises(ValueError): self.spec.completion(self.work, [], 'Claimed success.')
        with self.assertRaises(ValueError): self.spec.completion(self.work, [], 'Claimed success.', compiler_receipts=[])

    def test_exact_stdout_bytes_contract_identity_cleanup_and_unique_attempts_are_required(self):
        spec = TaskSpec(compiler_data(expected_stdout='23\r\n'))
        good = receipt(spec)
        for key, value in (('stdout_sha256', digest(b'23\n')), ('spec_sha256', self.spec.sha256),
                           ('recipe_id', 'other'), ('owned_processes_exited', False),
                           ('owned_processes_exited', 1), ('status', 'unknown'),
                           ('source_sha256', 'bad'), ('artifact_sha256', 'bad'), ('command', 'run')):
            bad = {**good, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): spec.compiler_completion([bad])
        for duplicate in ({**good, 'tool_call_id': 'call-2'}, {**good, 'operation_id': 'operation-2'}):
            with self.assertRaises(ValueError): spec.compiler_completion([good, duplicate])
        extra = receipt(spec, operation='operation-3', call='call-3', status='failed')
        second = receipt(spec, operation='operation-2', call='call-2', status='failed')
        with self.assertRaises(ValueError): spec.compiler_completion([good, second, extra])

    def test_known_finalized_failures_do_not_become_success_or_restore_allowance(self):
        statuses = ('failed', 'interrupted', 'timed_out', 'cancelled', 'cancelled_before_dispatch',
                    'binding_refused', 'preparation_failed')
        spec = TaskSpec(compiler_data(max_runs=8))
        records = [receipt(spec, operation=f'op-{i}', call=f'call-{i}', status=status)
                   for i, status in enumerate(statuses)]
        result = spec.compiler_completion(records)
        self.assertEqual(result, {'qualified': False, 'recipe_id': COMPILER_RECIPE,
                                  'attempts': 7, 'successful': None})
        records.append(receipt(spec, operation='op-final', call='call-final'))
        self.assertTrue(spec.compiler_completion(records)['qualified'])
        self.assertFalse(spec.validate_compiler_args({'recipe_id': COMPILER_RECIPE, 'source': 'new'},
                                                     completed_runs=8).accepted)

    def test_compiler_success_does_not_replace_required_file_receipt_or_oracle(self):
        raw = spec_data(inputs={}, outputs=[('report.json', 'json')], expected={'report.json': {'done': True}})
        raw.update(schema=COMPILER_SCHEMA, compiler=compiler_data()['compiler'])
        spec = TaskSpec(raw)
        compiled = [receipt(spec)]
        with self.assertRaises(ValueError): spec.completion(self.work, [], 'done', compiler_receipts=compiled)
        output = self.work / 'report.json'; output.write_bytes(b'{"done":true}')
        tool = {'name': 'write_file', 'args': {'path': 'report.json'}, 'artifact_sha256': digest(output.read_bytes())}
        self.assertEqual(spec.completion(self.work, [tool], 'done', compiler_receipts=compiled)
                         ['semantic_validation'], 'oracle_matched')
        output.write_bytes(b'{"done":false}')
        with self.assertRaises(ValueError): spec.completion(self.work, [tool], 'done', compiler_receipts=compiled)

    def test_v1_retains_its_exact_schema_result_and_has_no_compiler_permission(self):
        raw = spec_data(inputs={}, outputs=[], prompt='Explain this concept.')
        encoded = canonical(raw)
        spec = TaskSpec(raw)
        self.assertEqual(spec.sha256, digest(encoded))
        self.assertIsNone(spec.compiler)
        self.assertEqual(spec.completion(self.work, [], 'An explanation.'),
                         {'artifacts': {}, 'semantic_validation': 'not_checked', 'validated_artifacts': []})
        self.assertFalse(spec.validate_compiler_args({'recipe_id': COMPILER_RECIPE, 'source': 'code'}).accepted)
        with self.assertRaises(ValueError): spec.compiler_completion([])
        raw['compiler'] = compiler_data()['compiler']
        with self.assertRaises(ValueError): TaskSpec(raw)
