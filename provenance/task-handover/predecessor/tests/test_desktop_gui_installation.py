"""Installed source closure and source-preservation checks; no child or GUI."""
import ast
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from ast_preservation import preservation_dump
from desktop_gui_support.intent_lineage import restore_predecessor

from adaptive_inference.desktop.gui_launch import CHILD_SOURCES, LaunchSpec
from adaptive_inference.desktop.startup_pipe import StartupError


def normalized_source(text, name):
    tree = ast.parse(text)
    if name == 'control_client':tree = restore_predecessor(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('adaptive_inference.desktop.'):
            node.module = node.module.removeprefix('adaptive_inference.desktop.')
    if name == 'control_client':
        controller = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ClientController')
        for method in controller.body:
            if isinstance(method, ast.FunctionDef) and method.name == 'render':
                method.body = [ast.Pass()]
        view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'TkView')
        view.body = [method for method in view.body if not (
            isinstance(method, ast.FunctionDef) and method.name == '_minimize')]
        for method in view.body:
            if isinstance(method, ast.FunctionDef) and method.name == 'render':
                class Footer(ast.NodeTransformer):
                    def visit_Attribute(self, node):
                        if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr == '_normal_footer':
                            return ast.Constant('Closing this window leaves the task and engine running.')
                        return self.generic_visit(node)
                Footer().visit(method)
            if isinstance(method, ast.FunctionDef) and method.name in ('__init__', 'attach'):
                method.body = [ast.Pass()]
                for index in reversed(range(len(method.args.kwonlyargs))):
                    if method.args.kwonlyargs[index].arg == 'minimize_on_close':
                        del method.args.kwonlyargs[index]
                        del method.args.kw_defaults[index]
    if name == 'run_gui':
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.ImportFrom) and node.module == 'pathlib') and not (
            isinstance(node, ast.FunctionDef) and node.name == '_verify_installed_imports')]
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        main.body = [node for node in main.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and ast.unparse(node.value.func) in ('sys.path.insert', '_verify_installed_imports'))]
        for node in ast.walk(main):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'TkView':
                node.keywords = [keyword for keyword in node.keywords if keyword.arg != 'minimize_on_close']
    if name == 'gui_launch':
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CHILD_SOURCES' for t in node.targets):
                node.value = ast.Constant(None)
            if isinstance(node, ast.ClassDef) and node.name == 'LaunchSpec':
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name == 'verify':
                        method.body = [ast.Pass()]
    return preservation_dump(tree)


class SourcePreservationTests(unittest.TestCase):
    def test_all_seven_modules_preserve_accepted_behavior_outside_declared_install_seams(self):
        lineage = json.loads((Path(__file__).parent / 'desktop_gui_support/source-lineage.json').read_text())
        for name, row in lineage['modules'].items():
            module = importlib.import_module('adaptive_inference.desktop.' + name)
            normalized = normalized_source(Path(module.__file__).read_text(encoding='utf-8'), name)
            self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), row['normalized_ast_sha256'], name)

    def test_exact_canonical_class_identities(self):
        from adaptive_inference.desktop import control_client, gui_launch, gui_session, retained_ui, startup_pipe, ui_intent
        self.assertIs(gui_launch.Bootstrap, control_client.Bootstrap)
        self.assertIs(startup_pipe.Bootstrap, control_client.Bootstrap)
        self.assertIs(gui_session.ClientController, control_client.ClientController)
        self.assertIs(gui_session.ChildHandshake, startup_pipe.ChildHandshake)
        self.assertIs(gui_launch.UIBinding, ui_intent.UIBinding)
        self.assertIs(retained_ui.UIBinding, ui_intent.UIBinding)

    def test_unsupported_runtime_is_rejected_before_windows_api_acquisition(self):
        from adaptive_inference.desktop import gui_launch
        with mock.patch.object(gui_launch.sys, 'version_info', (3, 12, 0)), mock.patch.object(
                gui_launch, 'VerifierAPI') as acquire:
            with self.assertRaises(StartupError):
                gui_launch.WindowsLaunchAPI()
            acquire.assert_not_called()


class InstalledClosureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='installed-gui-sources-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / 'adaptive_inference'
        (self.root / 'desktop').mkdir(parents=True)
        executable = self.root / 'python-fixture.exe'
        executable.write_bytes(b'never executed')
        for name in CHILD_SOURCES:
            (self.root / name).write_bytes(b'# fixture never executed\n')
        self.spec = LaunchSpec(executable, hashlib.sha256(executable.read_bytes()).hexdigest(),
            self.root / 'desktop/run_gui.py', tuple((name, hashlib.sha256((self.root / name).read_bytes()).hexdigest())
                                                   for name in sorted(CHILD_SOURCES)))

    def test_exact_seven_source_installed_closure_passes(self):
        self.assertEqual(len(CHILD_SOURCES), 7)
        self.assertIn('__init__.py', CHILD_SOURCES)
        self.assertIn('desktop/__init__.py', CHILD_SOURCES)
        self.spec.verify()

    def test_missing_either_package_initializer_is_rejected(self):
        for missing in ('__init__.py', 'desktop/__init__.py'):
            with self.subTest(missing=missing), self.assertRaises(StartupError):
                replace(self.spec, source_pins=tuple(row for row in self.spec.source_pins if row[0] != missing)).verify()

    def test_changed_each_source_or_initializer_is_rejected(self):
        for name in CHILD_SOURCES:
            path = self.root / name
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'# changed\n')
                with self.subTest(name=name), self.assertRaises(StartupError):
                    self.spec.verify()
            finally:
                path.write_bytes(original)

    def test_duplicates_extras_and_noncanonical_names_are_rejected(self):
        for row in (self.spec.source_pins[0], ('../outside.py', '0' * 64),
                    ('desktop/../__init__.py', '0' * 64), ('desktop\\run_gui.py', '0' * 64),
                    ('desktop/unknown.py', '0' * 64), (self.root.as_posix() + '/__init__.py', '0' * 64)):
            with self.subTest(row=row), self.assertRaises(StartupError):
                replace(self.spec, source_pins=self.spec.source_pins + (row,)).verify()

    def test_wrong_entrypoint_and_interpreter_are_rejected(self):
        for entrypoint in (self.root / 'run_gui.py', self.root / 'desktop/control_client.py'):
            with self.subTest(entrypoint=entrypoint), self.assertRaises(StartupError):
                replace(self.spec, entrypoint=entrypoint).verify()
        with self.assertRaises(StartupError):
            replace(self.spec, interpreter_sha256='0' * 64).verify()


class ChildImportIdentityTests(unittest.TestCase):
    def setUp(self):
        self.modules = ('adaptive_inference', 'adaptive_inference.desktop',
                        *('adaptive_inference.desktop.' + name for name in
                          ('control_client', 'startup_pipe', 'window_marker', 'gui_session')))
        for name in self.modules:
            importlib.import_module(name)
        from adaptive_inference.desktop import run_gui
        self.gui = run_gui

    def test_matching_installed_origins_are_accepted_without_resource_acquisition(self):
        self.gui._verify_installed_imports()

    def test_each_changed_or_missing_child_package_origin_is_refused(self):
        for name in self.modules:
            for replacement in (None, SimpleNamespace(__file__=__file__)):
                with self.subTest(name=name, replacement=replacement), mock.patch.dict(
                        self.gui.sys.modules, {name: replacement}), self.assertRaises(RuntimeError):
                    self.gui._verify_installed_imports()

    def test_main_rejects_import_mismatch_before_owning_any_startup_pipe(self):
        with mock.patch.object(self.gui, '_verify_installed_imports',
                               side_effect=RuntimeError('different installation')), mock.patch.object(
                                   self.gui, 'owned_startup_streams') as acquire:
            with self.assertRaisesRegex(RuntimeError, 'different installation'):
                self.gui.main()
            acquire.assert_not_called()


if __name__ == '__main__':
    unittest.main()
