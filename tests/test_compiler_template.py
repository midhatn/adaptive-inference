"""Fixed template preparation and retained artifact checks, without execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from adaptive_inference.desktop.compiler_recipe import Executable
from adaptive_inference.desktop.compiler_template import (
    CompilerSettings, prepare_cpp_recipe, verify_cpp_artifacts)
from adaptive_inference.task_spec import TaskSpec, BUDGET


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CompilerTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.spec = TaskSpec({'schema': 'adaptive.task-spec.v2', 'prompt': 'Compile and check the answer.',
            'inputs': [], 'outputs': [], 'budget': deepcopy(BUDGET), 'validation': {'validator': None},
            'compiler': {'recipe_id': 'cpp17-stdout.v1', 'expected_stdout': 'units=17',
                         'max_source_chars': 4096, 'max_runs': 3}})
        pins = []
        for name in ('cmake.exe', 'ctest.exe', 'clang-cl.exe', 'ninja.exe', 'lld-link.exe'):
            path = self.root / name
            path.write_bytes(b'inert fixture ' + name.encode())
            pins.append(Executable(path, sha(path.read_bytes())))
        self.settings = CompilerSettings(*pins, environment=())
        self.args = {'recipe_id': 'cpp17-stdout.v1', 'source': 'int main() { return 0; }'}
        self.operation = 'a' * 32

    def prepare(self, operation=None, args=None):
        return prepare_cpp_recipe(self.settings, spec=self.spec, args=args or self.args,
            operation_id=operation or self.operation, root=self.root)

    def completed(self):
        recipe = self.prepare()
        recipe.build.mkdir(parents=True)
        (recipe.build / 'program.exe').write_bytes(b'inert executable artifact')
        (recipe.build / 'program.stdout').write_bytes(b'units=17')
        (recipe.build / 'program.exit').write_bytes(b'0')
        (recipe.run / 'tests.xml').write_bytes(b'<testsuite/>')
        (recipe.run / 'receipt.json').write_bytes(b'{"fixture":true}')
        result = {'operation_id': self.operation, 'recipe_id': 'cpp17-stdout.v1',
            'status': 'passed', 'owned_processes_exited': True,
            'artifact_sha256': sha((recipe.build / 'program.exe').read_bytes()),
            'test_report_sha256': sha((recipe.run / 'tests.xml').read_bytes()),
            'receipt_sha256': sha((recipe.run / 'receipt.json').read_bytes())}
        return recipe, result

    def verify(self, result):
        return verify_cpp_artifacts(self.root, spec=self.spec, args=self.args,
            operation_id=self.operation, result=result)

    def test_corrected_source_is_new_snapshot_without_rewriting_previous_operation(self):
        first = self.prepare()
        corrected = {**self.args, 'source': 'int main() { return 1; }'}
        second = self.prepare('b' * 32, corrected)
        self.assertEqual((first.source / 'program.cpp').read_text(), self.args['source'])
        self.assertEqual((second.source / 'program.cpp').read_text(), corrected['source'])
        self.assertNotEqual(first.source_files, second.source_files)
        with self.assertRaises(FileExistsError):
            self.prepare(args=corrected)
        self.assertEqual(self.spec.data['budget'], BUDGET)

    def test_model_cannot_supply_build_configuration_or_expected_output(self):
        for field in ('command', 'CMakeLists.txt', 'expected_stdout', 'path'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare(args={**self.args, field: 'arbitrary'})
        self.assertFalse((self.root / self.operation).exists())

    def test_retained_success_requires_exact_stdout_exit_and_artifact(self):
        recipe, result = self.completed()
        self.assertEqual(self.verify(result)['stdout_sha256'], sha(b'units=17'))
        for name, bad in (('program.stdout', b'units=19'), ('program.exit', b'1\n'),
                          ('program.exe', b'changed executable')):
            path = recipe.build / name
            original = path.read_bytes()
            path.write_bytes(bad)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify(result)
            path.write_bytes(original)

    def test_changed_source_or_receipt_and_unknown_cleanup_cannot_requalify(self):
        recipe, result = self.completed()
        for bad in ({**result, 'status': 'outcome_unknown'},
                    {**result, 'owned_processes_exited': False}):
            with self.assertRaises(ValueError):
                self.verify(bad)
        receipt = recipe.run / 'receipt.json'
        receipt.write_text(json.dumps({'changed': True}))
        with self.assertRaises(ValueError):
            self.verify(result)
        (recipe.source / 'program.cpp').write_text('different source')
        with self.assertRaises(ValueError):
            self.verify(result)
