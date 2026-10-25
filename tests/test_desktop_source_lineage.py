"""Declared installed promotion keeps the accepted runtime mechanisms intact."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from paused_expiry_lineage import restore_expiry, ARCHIVE as EXPIRY_ARCHIVE
from execution_clock_lineage import restore_clock

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'provenance/installed-desktop'
DESKTOP=ROOT/'src/adaptive_inference/desktop'
QUALIFIED={name:'adaptive_inference.desktop.'+name for name in (
    'control_transport','mailbox_runtime','ui_intent','ui_progress','persistent_host',
    'cold_start','load_feasibility','windows_host_base','native_owner_adapter')}
QUALIFIED.update({name:'adaptive_inference.desktop.hermes.'+name for name in (
    'service_stop','admission','recovery','control_bridge','report_validator')})


class Imports(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        node.module=QUALIFIED.get(node.module,node.module)
        return node
    def visit_Import(self,node):
        if len(node.names)==1 and node.names[0].name in ('admission','recovery'):
            return ast.ImportFrom(module='adaptive_inference.desktop.hermes',names=node.names,level=0)
        return node


def tree(path):
    value=ast.parse(path.read_text(encoding='utf-8'))
    package=ROOT/'src/adaptive_inference'
    if path.is_relative_to(package):
        relative=path.relative_to(package).as_posix()
        if relative in json.loads((EXPIRY_ARCHIVE/'source-lineage.json').read_text())['modules']:
            value=restore_expiry(value,relative)
        else:value=restore_clock(value,relative)
    return value
def dump(node):return ast.dump(node,include_attributes=False)
def definition(value,name):
    return next(n for n in ast.walk(value) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name)


class SourceLineageTests(unittest.TestCase):
    def test_all_retained_inputs_match_declared_hashes(self):
        manifest=json.loads((ARCHIVE/'source-lineage.json').read_text())
        for row in manifest['source_mappings']+manifest['test_and_planner_support']+manifest['composition_fragments']:
            with self.subTest(path=row['retained_source']):
                expected=row.get('retained_sha256',row.get('sha256',row.get('source_sha256')))
                self.assertEqual(hashlib.sha256((ROOT/row['retained_source']).read_bytes()).hexdigest(),expected)

    def test_non_gui_runtime_changes_only_qualified_imports(self):
        manifest=json.loads((ARCHIVE/'source-lineage.json').read_text())
        excluded={'hermes/run_recovery.py','native/windows_host_base.py',
            'examples/validation/hermes_tool_task/run_task.py',
            'control_client.py','gui_session.py','startup_pipe.py','window_marker.py',
            'run_gui.py','gui_launch.py','retained_ui.py'}
        for row in manifest['source_mappings']:
            if row['source'] in excluded:continue
            with self.subTest(source=row['source']):
                expected=Imports().visit(tree(ROOT/row['retained_source']))
                self.assertEqual(dump(expected),dump(tree(ROOT/row['destination'])))

    def test_report_helper_preserves_wire_quality_and_arithmetic_contract(self):
        before=tree(ARCHIVE/'sources/examples/validation/hermes_tool_task/run_task.py')
        after=tree(DESKTOP/'hermes/report_contract.py')
        for name in ('digest','save','git','config','Refused','Boundary','snapshot'):
            with self.subTest(name=name):self.assertEqual(dump(definition(before,name)),dump(definition(after,name)))

    def test_worker_only_adds_import_origin_checks_to_accepted_execution(self):
        before=Imports().visit(definition(tree(ARCHIVE/'sources/hermes/run_recovery.py'),'worker'))
        after=definition(tree(DESKTOP/'hermes/run_recovery.py'),'worker')
        class RemoveOriginChecks(ast.NodeTransformer):
            def visit_ImportFrom(self,node):
                if node.module=='adaptive_inference.desktop.installation' and [a.name for a in node.names]==['verify_sdk_imports']:
                    return None
                return node
            def visit_Expr(self,node):
                if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='verify_sdk_imports':
                    return None
                return self.generic_visit(node)
        self.assertEqual(dump(before),dump(RemoveOriginChecks().visit(after)))

    def test_native_host_changes_only_installed_job_and_reader_imports(self):
        before=Imports().visit(tree(ARCHIVE/'sources/native/windows_host_base.py'))
        after=tree(DESKTOP/'windows_host_base.py')
        for value in (before,after):
            cls=definition(value,'DesktopHost')
            cls.body=[n for n in cls.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) or n.name not in ('_prepare_job','_start_activity')]
        self.assertEqual(dump(before),dump(after))

    def test_retained_cleanup_and_readiness_methods_are_unchanged(self):
        after=tree(DESKTOP/'composition.py')
        groups={
            'run_cold_ui_class.py':('bind_worker_stop','join_child','fence','paused_ack','bind_gui',
                'obligations','control_io_released','join_gui_resources','dispose_control_io','dispose'),
            'qualification_helpers_class.py':('event','until','remaining','status','submit','ack','checkpoint','assert_original','ready')}
        for file,names in groups.items():
            before=tree(ARCHIVE/'sources'/file)
            for name in names:
                with self.subTest(name=name):self.assertEqual(dump(definition(before,name)),dump(definition(after,name)))


if __name__=='__main__':unittest.main()
