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
    if name in ('run_gui', 'gui_launch'):
        from task_handover_lineage import restore_task_handover
        tree = restore_task_handover(tree, 'desktop/' + name + '.py')
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

    def test_run_gui_handover_projection_refuses_unreviewed_function_and_module_edits(self):
        from adaptive_inference.desktop import run_gui
        source = Path(run_gui.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        main.body.insert(0, ast.Return(value=ast.Constant(value=None)))
        for changed in (source + '\nunreviewed = True\n', ast.unparse(tree)):
            with self.subTest(changed=changed[-50:]), self.assertRaisesRegex(
                    AssertionError, 'Changed complete task-handover AST'):
                normalized_source(changed, 'run_gui')

    def test_gui_launch_only_adds_two_exact_task_chooser_source_dependencies(self):
        from adaptive_inference.desktop import gui_launch
        import task_handover_lineage as lineage
        relative = 'desktop/gui_launch.py'
        before = ast.parse(lineage.retained(relative, lineage.record()['modules'][relative]))
        after = ast.parse(Path(gui_launch.__file__).read_text(encoding='utf-8'))
        declarations = []
        for tree in (before, after):
            matches = [node for node in tree.body if isinstance(node, ast.Assign)
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'CHILD_SOURCES']
            self.assertEqual(len(matches), 1)
            call = matches[0].value
            self.assertIsInstance(call, ast.Call)
            self.assertIsInstance(call.func, ast.Name); self.assertEqual(call.func.id, 'frozenset')
            self.assertEqual(len(call.args), 1); self.assertEqual(call.keywords, [])
            names = ast.literal_eval(call.args[0])
            self.assertIs(type(names), tuple); self.assertEqual(len(names), len(set(names)))
            declarations.append((matches[0], set(names)))
        self.assertEqual(declarations[1][1], declarations[0][1] | {'task_spec.py', 'feedback.py'})
        self.assertEqual(declarations[1][1] - declarations[0][1], {'task_spec.py', 'feedback.py'})
        declarations[1][0].value = declarations[0][0].value
        self.assertEqual(preservation_dump(after), preservation_dump(before))

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

    def test_exact_nine_source_installed_closure_passes(self):
        self.assertEqual(len(CHILD_SOURCES), 9)
        self.assertIn('__init__.py', CHILD_SOURCES)
        self.assertIn('desktop/__init__.py', CHILD_SOURCES)
        self.assertIn('task_spec.py', CHILD_SOURCES)
        self.assertIn('feedback.py', CHILD_SOURCES)
        self.spec.verify()

    def test_missing_either_package_initializer_is_rejected(self):
        for missing in ('__init__.py', 'desktop/__init__.py'):
            with self.subTest(missing=missing), self.assertRaises(StartupError):
                replace(self.spec, source_pins=tuple(row for row in self.spec.source_pins if row[0] != missing)).verify()

    def test_missing_either_task_chooser_import_pin_is_rejected(self):
        for missing in ('task_spec.py', 'feedback.py'):
            with self.subTest(missing=missing), self.assertRaises(StartupError):
                replace(self.spec, source_pins=tuple(row for row in self.spec.source_pins if row[0] != missing)).verify()

    def test_missing_task_chooser_import_file_with_retained_pin_is_rejected(self):
        for missing in ('task_spec.py', 'feedback.py'):
            path = self.root / missing
            original = path.read_bytes()
            try:
                path.unlink()
                with self.subTest(missing=missing), self.assertRaises(FileNotFoundError):
                    self.spec.verify()
            finally:
                path.write_bytes(original)

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

    def test_matching_lazy_task_import_origins_are_accepted_without_resource_acquisition(self):
        importlib.import_module('adaptive_inference.task_spec')
        self.gui._verify_installed_imports(chooser=True)

    def test_missing_or_changed_lazy_task_import_origins_are_refused(self):
        importlib.import_module('adaptive_inference.task_spec')
        for name in ('adaptive_inference', 'adaptive_inference.desktop',
                     'adaptive_inference.task_spec', 'adaptive_inference.feedback'):
            for replacement in (None, SimpleNamespace(__file__=__file__)):
                with self.subTest(name=name, replacement=replacement), mock.patch.dict(
                        self.gui.sys.modules, {name: replacement}), self.assertRaises(RuntimeError):
                    self.gui._verify_installed_imports(chooser=True)

    def test_chooser_refuses_different_task_import_before_dialog_or_file_read(self):
        spec = importlib.import_module('adaptive_inference.task_spec')
        wrong = SimpleNamespace(__file__=__file__, TaskSpec=spec.TaskSpec,
                                MAX_SPEC_BYTES=spec.MAX_SPEC_BYTES, _file=mock.Mock())
        dialogs = mock.Mock()
        with mock.patch.dict(self.gui.sys.modules, {'adaptive_inference.task_spec': wrong}):
            with self.assertRaisesRegex(RuntimeError, 'GUI package import identity changed'):
                self.gui.choose_task(object(), dialogs=dialogs)
        dialogs.askopenfilename.assert_not_called()
        dialogs.askdirectory.assert_not_called()
        wrong._file.assert_not_called()

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
