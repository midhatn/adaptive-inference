# SPDX-License-Identifier: Apache-2.0
"""Focused public-location checks; no installed runtime, model, GUI or live case."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
ARCHIVE=HERE.parents[2]/'provenance/task-handover/reproduction'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


class PublicHandoverTests(unittest.TestCase):
    def test_exact_sources_and_complete_manifest(self):
        lineage=read(HERE/'source-lineage.json')
        for group in ('exact_harness_files','exact_foreground_files'):
            for name,pin in lineage[group].items():self.assertEqual(sha(HERE/name),pin,name)
        for name,pin in lineage['files'].items():self.assertEqual(sha(HERE/name),pin,name)
        manifest=read(HERE/'source-manifest.json')
        self.assertIs(manifest['enabled'],False)
        files={p.name for p in HERE.iterdir() if p.is_file() and p.name!='source-manifest.json'}
        self.assertEqual(set(manifest['files']),files)
        for name,pin in manifest['files'].items():self.assertEqual(sha(HERE/name),pin,name)

    def test_only_declared_location_changes(self):
        lineage=read(HERE/'source-lineage.json')
        self.assertEqual(set(lineage['transformations']),{'capture_binding.py','cue_status.py','expiry_ready.py','record_ui.py','audit_first_inflight.py'})
        for name,row in lineage['transformations'].items():
            current=(HERE/name).read_bytes();ast.parse(current)
            for change in reversed(row['changes']):
                self.assertEqual(current.count(change['after'].encode()),change['count'])
                current=current.replace(change['after'].encode(),change['before'].encode())
            self.assertEqual(current,(ARCHIVE/row['predecessor']).read_bytes(),name)

    def test_existing_complete_foreground_fixture_uses_exact_predicate(self):
        previous=list(sys.path)
        try:fixture=module(ARCHIVE/'fixtures/test_first_inflight.py','retained_foreground_fixture')
        finally:sys.path[:]=previous
        evidence=fixture.onset_fixture();before=deepcopy(evidence)
        import first_inflight
        self.assertTrue(first_inflight.check_onset(*evidence))
        self.assertEqual(evidence,before)

    def synthetic_binding(self,root):
        """Explicitly synthetic file descriptors for the existing pure loader."""
        import bindings
        local=root/'local';local.mkdir();case=root/'a-new-case'
        identity={'version':'synthetic','files':{str(i)+'.py':'0'*64 for i in range(60)}}
        executable=local/'synthetic-interpreter';executable.write_text('never executed')
        descriptor=lambda path:{'path':str(path.resolve()),'sha256':sha(path)}
        values={name:{'synthetic':True} for name in bindings.INPUTS}
        values['profile']={'host_python':descriptor(executable),'worker_python':descriptor(executable)}
        values['installed_identity']=identity
        for name in ('host_install','worker_install','installed_sdk'):
            values[name]={'passed':True,'package_identity':identity,'installed_mode':True,'synthetic':True}
        values['clock_probe']={'passed':True,'synthetic':True}
        inputs={}
        for name,value in values.items():
            path=local/(name+'.json');path.write_text(json.dumps(value));inputs[name]=descriptor(path)
        gate=Path(inputs['deployment_gate']['path'])
        gate.write_text(json.dumps({'passed':True,'wheel_sha256':inputs['wheel']['sha256'],'synthetic':True}))
        inputs['deployment_gate']=descriptor(gate)
        declaration={'schema':'private.task-handover.installed-inputs.v1','enabled':False,
            'case':str(case),'harness_manifest':descriptor(HERE/'source-manifest.json'),'inputs':inputs}
        disabled=local/'bindings.disabled.private.json';disabled.write_text(json.dumps(declaration))
        enabled=local/'bindings.enabled.private.json';enabled.write_text(json.dumps({**declaration,'enabled':True}))
        return bindings,disabled,enabled,declaration

    def test_local_declaration_and_fresh_case_work_outside_source(self):
        import record_ui,expiry_ready
        with tempfile.TemporaryDirectory() as directory:
            bindings,disabled,enabled,declaration=self.synthetic_binding(Path(directory))
            bound=bindings.load(enabled,installed=False)
            self.assertEqual(record_ui.checked_bound(enabled)['case'],Path(declaration['case']))
            with patch.object(expiry_ready,'load',return_value=bound):
                self.assertEqual(expiry_ready.checked(enabled),bound)
            with self.assertRaisesRegex(ValueError,'disabled or incomplete'):bindings.load(disabled)
            self.assertFalse(bound['case'].exists())

    def test_changed_local_declaration_is_refused(self):
        import record_ui,expiry_ready
        with tempfile.TemporaryDirectory() as directory:
            bindings,disabled,enabled,declaration=self.synthetic_binding(Path(directory))
            bound=bindings.load(enabled,installed=False)
            declaration['case']=str(Path(directory)/'different-case');disabled.write_text(json.dumps(declaration))
            with self.assertRaisesRegex(ValueError,'exact_enabled_case10'):record_ui.checked_bound(enabled)
            with patch.object(expiry_ready,'load',return_value=bound),self.assertRaisesRegex(ValueError,'exact_enabled_case11'):
                expiry_ready.checked(enabled)

    def test_relocated_source_closure_and_changed_file_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(strict=True);copy=root/'copied-example';shutil.copytree(HERE,copy,ignore=shutil.ignore_patterns('__pycache__'))
            bindings,disabled,enabled,declaration=self.synthetic_binding(root)
            declaration['harness_manifest']={'path':str(copy/'source-manifest.json'),'sha256':sha(copy/'source-manifest.json')}
            enabled.write_text(json.dumps({**declaration,'enabled':True}))
            relocated=module(copy/'bindings.py','relocated_handover_bindings')
            self.assertEqual(relocated.load(enabled)['case'],Path(declaration['case']))
            (copy/'first_inflight.py').write_bytes((copy/'first_inflight.py').read_bytes()+b'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'Harness source differs'):relocated.load(enabled)

    def test_supplement_still_requires_actual_join_attestation(self):
        import audit_first_inflight
        with self.assertRaisesRegex(ValueError,'actual_retained_parent_and_observer_joins_required'):
            audit_first_inflight.audit(Path('missing'),Path('missing'))


if __name__=='__main__':unittest.main()
