# SPDX-License-Identifier: Apache-2.0
"""Public-path adaptation equivalence and refusal; no installed runtime needed."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def source_function(source,name):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(source,node)


# Reused verbatim from tests/ast_preservation.py (Apache-2.0).
# Python 3.12 adds an empty type_params field to unchanged definitions:
# https://docs.python.org/3.12/library/ast.html#ast.FunctionDef
def preservation_dump(tree):
    tree = deepcopy(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and hasattr(node, 'type_params'):
            parameters = node.type_params
            if type(parameters) is not list or parameters:
                raise ValueError('New or invalid type parameters are outside the preserved Python 3.11 source')
            del node.type_params
    return ast.dump(tree, include_attributes=False)

class PublicHarnessSourceTests(unittest.TestCase):
    def test_exact_workflow_and_current_source_closure(self):
        lineage=read(HERE/'source-lineage.json')
        for name in lineage['exact_workflow_files']:
            self.assertEqual(sha(HERE/name),lineage['private_predecessor_files'][name],name)
        manifest=read(HERE/'source-manifest.json')
        for name,pin in manifest['files'].items():self.assertEqual(sha(HERE/name),pin,name)
        root=HERE.parents[2]/'provenance/explicit-continuation/qualification-predecessor'
        self.assertEqual(len(lineage['qualification_predecessor']),7)
        for name,pin in lineage['qualification_predecessor'].items():self.assertEqual(sha(root/name),pin,name)

    def test_only_baseline_resolution_changed(self):
        lineage=read(HERE/'source-lineage.json')
        previous=(HERE/'predecessor-bindings.py').read_bytes().decode('utf-8')
        current=(HERE/'bindings.py').read_bytes().decode('utf-8')
        restored=current.replace(source_function(current,'baseline'),source_function(previous,'baseline'))
        self.assertEqual(restored,previous)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),lineage['private_predecessor_files']['bindings.py'])

    def test_fixture_has_only_declared_path_substitution(self):
        lineage=read(HERE/'source-lineage.json');delta=lineage['fixture_path_substitution']
        source=(HERE/'test_checks.py').read_bytes()
        self.assertEqual(source.count(delta['after'].encode()),1)
        restored=source.replace(delta['after'].encode(),delta['before'].encode())
        self.assertEqual(hashlib.sha256(restored).hexdigest(),lineage['private_predecessor_files']['test_checks.py'])

    def test_qpc_functions_are_exact_original_asts(self):
        lineage=read(HERE/'source-lineage.json')
        functions={n.name:n for n in ast.parse((HERE/'qpc_helpers.py').read_text()).body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(set(functions),{'finite_time','qpc_bracket'})
        for name,node in functions.items():
            self.assertEqual(hashlib.sha256(preservation_dump(node).encode()).hexdigest(),lineage['qpc_function_ast_sha256'][name])

    def test_preservation_rejects_new_or_invalid_parameters(self):
        for source in ('def f():\n pass\n', 'async def f():\n pass\n', 'class C:\n pass\n'):
            for value in (None, (), '', False, [ast.Name(id='T',ctx=ast.Load())]):
                tree=ast.parse(source)
                tree.body[0].type_params=value
                with self.subTest(source=source,value=value), self.assertRaisesRegex(ValueError,'type parameters'):
                    preservation_dump(tree)
        if hasattr(ast,'TypeVar'):
            for source in ('def f[T]():\n pass\n','async def f[T]():\n pass\n','class C[T]:\n pass\n'):
                with self.subTest(source=source), self.assertRaisesRegex(ValueError,'type parameters'):
                    preservation_dump(ast.parse(source))

    def test_preservation_retains_changes_without_mutation(self):
        source=(HERE/'qpc_helpers.py').read_text()
        tree=ast.parse(source)
        before=ast.dump(tree,include_attributes=True)
        preserved=preservation_dump(tree)
        self.assertEqual(ast.dump(tree,include_attributes=True),before)
        self.assertNotEqual(preserved,preservation_dump(ast.parse(source.replace('value>0','value>=0'))))
        self.assertNotEqual(preservation_dump(ast.parse("value = 'type_params=[]'")),
                            preservation_dump(ast.parse("value = ''")))

    def test_qpc_real_boundary_predicates_and_unknown_helper(self):
        import bindings
        qpc=bindings.baseline('audit_expiry.py')
        row={'deadline_clock':'windows-qpc-seconds-v1','before':10.,'after':11.}
        self.assertTrue(qpc.qpc_bracket(row,'before','after'))
        for changed in ({'deadline_clock':'local-monotonic'},{'before':True},{'before':float('nan')},
                        {'after':float('inf')},{'after':9.}):
            self.assertFalse(qpc.qpc_bracket({**row,**changed},'before','after'))
        with self.assertRaisesRegex(ValueError,'Unknown retained helper'):bindings.baseline('unreviewed.py')

    def test_modified_qpc_or_public_predecessor_refused_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'examples/validation/explicit_continuation';local.mkdir(parents=True)
            for name in ('bindings.py','source-lineage.json','qpc_helpers.py'):
                (local/name).write_bytes((HERE/name).read_bytes())
            spec=importlib.util.spec_from_file_location('modified_public_bindings',local/'bindings.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            (local/'qpc_helpers.py').write_bytes((local/'qpc_helpers.py').read_bytes()+b'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'Retained QPC helper changed'):module.baseline('audit_expiry.py')
            relative='provenance/explicit-continuation/qualification-predecessor'
            shutil.copytree(HERE.parents[2]/relative,root/relative)
            target=root/relative/'qualify.py';target.write_bytes(target.read_bytes()+b'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'Public qualification predecessor changed'):
                module.baseline('installed_desktop/qualify.py')


if __name__=='__main__':unittest.main()
