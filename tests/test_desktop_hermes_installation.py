"""Installed worker setup uses canonical identities before external SDK inputs."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from adaptive_inference.desktop import installation
from adaptive_inference.desktop.hermes import run_recovery, report_contract, recovery


class WorkerSetupTests(unittest.TestCase):
    def setUp(self):
        root=Path(tempfile.gettempdir()).resolve()
        self.plan={'package_identity':{'version':'fixture','files':{}},
            'base_python':str(root/'python.exe'),'python':str(root/'python.exe'),
            'python_sha256':'a'*64,'sdk':str(root/'sdk'),
            'site_packages':str(root/'dependencies'),'gateway':'http://127.0.0.1:18100/v1'}

    def test_verify_package_and_sdk_before_dependency_setup_then_recheck_package(self):
        calls=[]
        with mock.patch.object(installation,'package_identity',side_effect=lambda *a:calls.append('package')), \
                mock.patch.object(installation,'verify_interpreter',side_effect=lambda *a,**k:calls.append('interpreter')), \
                mock.patch.object(installation,'verify_sdk',side_effect=lambda *a:calls.append('sdk')), \
                mock.patch.object(run_recovery.site,'addsitedir',side_effect=lambda *a:calls.append('dependencies')), \
                mock.patch.object(report_contract,'configure_inputs') as configure:
            rec,base=run_recovery.setup(self.plan)
        self.assertEqual(calls,['package','interpreter','sdk','dependencies','package'])
        self.assertIs(rec,recovery);self.assertIs(base,report_contract)
        configure.assert_called_once_with(self.plan['sdk'],self.plan['python'],self.plan['gateway'],run_recovery.MODEL)

    def test_changed_installed_package_or_sdk_cannot_load_dependency_hooks(self):
        for failing in ('package_identity','verify_interpreter','verify_sdk'):
            with self.subTest(failing=failing), ExitStack() as stack:
                for name in ('package_identity','verify_interpreter','verify_sdk'):
                    stack.enter_context(mock.patch.object(installation,name,
                        side_effect=RuntimeError('changed input') if name==failing else None))
                dependencies=stack.enter_context(mock.patch.object(run_recovery.site,'addsitedir'))
                configure=stack.enter_context(mock.patch.object(report_contract,'configure_inputs'))
                with self.assertRaises(RuntimeError):run_recovery.setup(self.plan)
                dependencies.assert_not_called();configure.assert_not_called()

    def test_dependency_hook_cannot_switch_package_before_helper_import(self):
        with mock.patch.object(installation,'package_identity',side_effect=[None,RuntimeError('changed origin')]), \
                mock.patch.object(installation,'verify_interpreter'),mock.patch.object(installation,'verify_sdk'), \
                mock.patch.object(run_recovery.site,'addsitedir'),mock.patch.object(report_contract,'configure_inputs') as configure:
            with self.assertRaises(RuntimeError):run_recovery.setup(self.plan)
        configure.assert_not_called()


if __name__=='__main__':unittest.main()
