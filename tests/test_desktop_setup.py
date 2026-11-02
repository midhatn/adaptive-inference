"""Ordinary launcher preparation without model, worker or real GUI execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from adaptive_inference.desktop import installation
from adaptive_inference.desktop.profile import WindowsProfile


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('desktop_example_' + name,
                                                ROOT / 'examples/desktop' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load('setup')
launcher = load('launch')


class DesktopSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.worker = self.root / 'worker.exe'
        self.worker.write_bytes(b'explicit worker interpreter')
        self.sdk = self.root / 'sdk'; self.sdk.mkdir()
        self.dependencies = self.root / 'dependencies'; self.dependencies.mkdir()
        self.owner = self.root / 'owner'; self.owner.mkdir()
        (self.owner / 'MANIFEST.json').write_text('{}', encoding='utf-8')
        (self.owner / 'PROVENANCE.json').write_text('{}', encoding='utf-8')
        self.owner_value = {'package': str(self.owner),
            'manifest_sha256': installation.sha(self.owner / 'MANIFEST.json'),
            'provenance_sha256': installation.sha(self.owner / 'PROVENANCE.json')}
        self.options = {'worker_python': self.worker, 'hermes_source': self.sdk,
                        'hermes_site_packages': self.dependencies, 'native_owner': self.owner}
        for patch in (mock.patch.object(setup, 'host_installation', return_value=Path(sys.executable).resolve()),
                      mock.patch.object(setup, 'verify_sdk', return_value=self.sdk),
                      mock.patch.object(setup, 'owner_identity', return_value=self.owner_value)):
            patch.start(); self.addCleanup(patch.stop)

    def prepare(self, name='desktop'):
        return setup.create_setup(self.root / name, **self.options)

    def test_generated_profile_uses_selected_files_and_existing_contract(self):
        result = self.prepare()
        profile = WindowsProfile.load(result['profile'])
        self.assertEqual(profile.worker_python, self.worker)
        self.assertEqual(profile.worker_python_sha256, installation.sha(self.worker))
        self.assertEqual(profile.owner, self.owner_value)
        self.assertEqual(profile.hermes_source, self.sdk)
        self.assertEqual(profile.hermes_site_packages, self.dependencies)
        self.assertEqual(profile.gateway.port, 18100)
        self.assertEqual(profile.gateway.backend_url, 'http://127.0.0.1:18098/v1')
        self.assertIsNone(profile.compiler)
        self.assertNotIn('compiler', json.loads(Path(result['profile']).read_bytes()))
        folder = Path(result['profile']).parent
        self.assertEqual((folder / 'launch.py').read_bytes(),
                         (ROOT / 'examples/desktop/launch.py').read_bytes())
        self.assertEqual(list(Path(result['runs']).iterdir()), [])
        self.assertFalse(result['inference_tested'])
        with self.assertRaisesRegex(ValueError, 'new setup folder'):
            self.prepare()

    def compiler_settings(self):
        value = {'schema': 'adaptive.compiler-settings.v1',
                 'environment': {'PATH': str(self.root), 'INCLUDE': 'headers', 'LIB': 'libraries'}}
        for name, filename in (('cmake', 'cmake.exe'), ('ctest', 'ctest.exe'),
                               ('compiler', 'clang-cl.exe'), ('ninja', 'ninja.exe'),
                               ('linker', 'lld-link.exe')):
            path = self.root / filename
            path.write_bytes(('inert selected tool: ' + name).encode())
            value[name] = {'path': str(path), 'sha256': installation.sha(path)}
        settings = self.root / 'compiler-settings.json'
        settings.write_text(json.dumps(value), encoding='utf-8')
        return settings, value

    def test_compiler_cli_verifies_selected_tools_without_launching_them(self):
        settings, expected = self.compiler_settings()
        destination = self.root / 'compiler desktop'
        argv = ['--destination', str(destination), '--compiler-settings', str(settings)]
        for name, path in self.options.items():
            argv.extend(['--' + name.replace('_', '-'), str(path)])
        with mock.patch('builtins.print'), mock.patch.object(subprocess, 'Popen') as launch:
            self.assertEqual(setup.main(argv), 0)
            launch.assert_not_called()
        profile_path = destination / 'deployment.json'
        self.assertEqual(json.loads(profile_path.read_bytes())['compiler'], expected)
        profile = WindowsProfile.load(profile_path)
        self.assertEqual(profile.compiler.compiler.path, Path(expected['compiler']['path']))
        self.assertEqual(profile.compiler.environment, tuple(sorted(expected['environment'].items())))
        self.assertEqual(profile.compiler.parallel_jobs, 2)
        self.assertEqual(profile.compiler.job_memory_mib, 2048)
        self.assertEqual(profile.compiler.max_seconds, 90)
        self.assertEqual(list((destination / 'runs').iterdir()), [])

    def test_invalid_or_changed_compiler_settings_leave_no_setup(self):
        settings, value = self.compiler_settings()
        destination = self.root / 'refused compiler'
        value['schema'] = 'unsupported'
        settings.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unsupported compiler settings'):
            setup.create_setup(destination, **self.options, compiler_settings=settings)
        self.assertFalse(destination.exists())
        value['schema'] = 'adaptive.compiler-settings.v1'
        settings.write_text(json.dumps(value), encoding='utf-8')
        Path(value['compiler']['path']).write_bytes(b'changed after selection')
        with self.assertRaisesRegex(ValueError, 'executable changed'):
            setup.create_setup(destination, **self.options, compiler_settings=settings)
        self.assertFalse(destination.exists())

    def test_compiler_example_has_original_budget_and_requires_real_result(self):
        from adaptive_inference.task_spec import BUDGET, TaskSpec
        spec = TaskSpec.from_bytes((ROOT / 'examples/tasks/compiler-stdout/task.json').read_bytes())
        self.assertEqual(spec.data['budget'], BUDGET)
        self.assertEqual(spec.data['inputs'], [])
        self.assertEqual(spec.data['outputs'], [])
        self.assertEqual(spec.compiler['expected_stdout'], '23 units')
        self.assertEqual(spec.compiler['max_runs'], 2)
        with self.assertRaisesRegex(ValueError, 'validated successful compiler receipt'):
            spec.completion(self.root, [], 'It worked.', compiler_receipts=[])

    def test_failed_existing_contract_validation_leaves_no_output(self):
        destination = self.root / 'invalid'
        with self.assertRaises(ValueError):
            setup.create_setup(destination, **self.options, gateway_port=18098)
        self.assertFalse(destination.exists())
        with mock.patch.object(setup, 'owner_identity', side_effect=RuntimeError('owner changed')):
            with self.assertRaisesRegex(RuntimeError, 'owner changed'):
                setup.create_setup(destination, **self.options)
        self.assertFalse(destination.exists())

    def test_cancel_starts_nothing_and_success_forwards_to_existing_executor(self):
        result = self.prepare()
        executor = mock.Mock(return_value={'clean_stop': True})
        selected = {'task_spec_path': str(self.root / 'task.json'),
                    'task_inputs': str(self.root / 'inputs')}
        with mock.patch.object(installation, 'verify_interpreter'), \
                mock.patch.object(installation, 'package_identity'):
            self.assertIsNone(launcher.launch(result['profile'], result['runs'],
                                             picker=lambda: None, executor=executor))
            executor.assert_not_called()
            first = launcher.launch(result['profile'], result['runs'],
                                    picker=lambda: selected, executor=executor)
            second = launcher.launch(result['profile'], result['runs'],
                                     picker=lambda: selected, executor=executor)
        self.assertEqual(first, {'clean_stop': True})
        self.assertEqual(second, first)
        calls = executor.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].args[1], calls[1].args[1])
        for call in calls:
            self.assertEqual(call.args[0], Path(result['profile']))
            self.assertEqual(call.args[1].parent, Path(result['runs']))
            self.assertFalse(call.args[1].exists())
            self.assertEqual(call.kwargs, {'task_spec': selected['task_spec_path'],
                                          'task_inputs': selected['task_inputs'], 'enable_reopen': True})

    def test_picker_is_destroyed_before_return_and_on_failure(self):
        import adaptive_inference.desktop.run_gui as gui
        root = mock.Mock()
        tkinter = mock.Mock(Tk=mock.Mock(return_value=root))
        buttons = {}
        def button(parent, *, text, command):
            self.assertIs(parent, root)
            buttons[text] = command
            return mock.Mock()
        tkinter.Button.side_effect = button
        selected = {'task_spec_path': 'task.json', 'task_inputs': 'inputs'}
        with mock.patch.dict(sys.modules, {'tkinter': tkinter}), \
                mock.patch.object(gui, 'choose_task', return_value=selected) as choose:
            def click():
                choose.assert_not_called()
                buttons['New task']()
            root.mainloop.side_effect = click
            self.assertEqual(launcher.select_task(), selected)
            choose.assert_called_once_with(root)
            root.quit.assert_called_once_with()
            root.destroy.assert_called_once_with()
            root.withdraw.assert_not_called()
        root.reset_mock()
        with mock.patch.dict(sys.modules, {'tkinter': tkinter}), \
                mock.patch.object(gui, 'choose_task', return_value=None) as choose:
            def cancel():
                buttons['New task']()
                root.quit.assert_not_called()
                buttons['Cancel']()
            root.mainloop.side_effect = cancel
            self.assertIsNone(launcher.select_task())
            choose.assert_called_once_with(root)
            root.quit.assert_called_once_with()
            root.destroy.assert_called_once_with()
        root.reset_mock()
        with mock.patch.dict(sys.modules, {'tkinter': tkinter}), \
                mock.patch.object(gui, 'choose_task', side_effect=ValueError('invalid task')):
            root.mainloop.side_effect = lambda: buttons['New task']()
            with self.assertRaisesRegex(ValueError, 'invalid task'):
                launcher.select_task()
            root.quit.assert_called_once_with()
            root.destroy.assert_called_once_with()

    def test_saved_selection_forwards_without_new_task_and_shows_completed_result(self):
        import adaptive_inference.desktop.installation as installation
        result = self.prepare('saved-task-launch')
        saved_result = {'objective': 'Original prompt', 'output': 'Saved answer', 'artifacts': []}
        executor = mock.Mock(return_value={'clean_stop': True, 'saved_result': saved_result})
        viewer = mock.Mock()
        selected = {'saved_task': str(self.root / 'canonical-task')}
        with mock.patch.object(installation, 'verify_interpreter'), \
                mock.patch.object(installation, 'package_identity'):
            outcome = launcher.launch(result['profile'], result['runs'], picker=lambda: selected,
                                      executor=executor, result_viewer=viewer)
        self.assertTrue(outcome['clean_stop'])
        self.assertEqual(executor.call_args.kwargs, {**selected, 'enable_reopen': True})
        viewer.assert_called_once_with(saved_result)
        self.assertFalse(executor.call_args.args[1].exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows command processor')
    def test_actual_generated_command_runs_isolated_stub_from_spaced_folder(self):
        result = self.prepare('desktop with spaces & ! %')
        folder = Path(result['profile']).parent
        receipt = folder / 'stub.json'
        (folder / 'launch.py').write_text(
            'import json, pathlib, sys\n'
            "pathlib.Path(__file__).with_name('stub.json').write_text(json.dumps({"
            "'executable': sys.executable, 'isolated': sys.flags.isolated, "
            "'no_bytecode': sys.dont_write_bytecode}), encoding='utf-8')\n",
            encoding='utf-8')
        command_processor = os.environ.get('COMSPEC', 'cmd.exe')
        command = '"' + command_processor + '" /d /s /c ""' + result['launcher'] + '""'
        completed = subprocess.run(command,
            cwd=self.root, capture_output=True, timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(completed.returncode, 0, (completed.stdout, completed.stderr))
        observed = json.loads(receipt.read_text(encoding='utf-8'))
        self.assertEqual(Path(observed['executable']).resolve(), Path(sys.executable).resolve())
        self.assertEqual(observed['isolated'], 1)
        self.assertTrue(observed['no_bytecode'])


if __name__ == '__main__':
    unittest.main()
