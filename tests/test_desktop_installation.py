"""Installation/configuration boundary fixtures; no installed SDK or native IO."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop import installation
from adaptive_inference.desktop.profile import WindowsProfile, SCHEMA, COOPERATIVE_POLICY


def profile_value(root):
    return {'schema': SCHEMA,
        'host_python': {'path': str(root/'host-python.exe'), 'sha256': 'a'*64},
        'worker_python': {'path': str(root/'worker-python.exe'), 'sha256': 'b'*64},
        'hermes': {'source': str(root/'hermes'), 'site_packages': str(root/'dependencies')},
        'native_owner': {'package': str(root/'native-owner'),
                         'manifest_sha256': 'c'*64, 'provenance_sha256': 'd'*64},
        'gateway': {'backend': {'kind': 'strata', 'base_url': 'http://127.0.0.1:18098/v1'}},
        'foreground_policy': COOPERATIVE_POLICY}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.gettempdir()).resolve()
        self.value = profile_value(self.root)

    def test_explicit_gateway_and_single_host_gui_interpreter(self):
        result = WindowsProfile.from_dict(self.value)
        self.assertEqual(result.gateway.port,18100)
        self.assertEqual(result.host_python,self.root/'host-python.exe')
        self.assertFalse(hasattr(result,'gui_python'))

    def test_no_implicit_policy_or_unknown_fields(self):
        for change in ({'foreground_policy':'automatic'}, {'gui_python':{}}, {'schema':'v2'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                WindowsProfile.from_dict({**self.value,**change})

    def test_refuses_unpinned_or_relative_deployment_inputs(self):
        for change in ({'path':'python.exe'}, {'sha256':'A'*64}, {'sha256':'latest'}):
            value=deepcopy(self.value);value['host_python'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                WindowsProfile.from_dict(value)

    def test_refuses_arbitrary_backend_or_credentials(self):
        for gateway in ({'backend':{'kind':'llamacpp'}},
                {'backend':{'kind':'strata','base_url':'http://localhost:18098/v1'}},
                {'backend':self.value['gateway']['backend'],'listen':{'port':18098}},
                {'backend':self.value['gateway']['backend'],'listen':{'api_key_env':'OTHER_KEY'}}):
            with self.subTest(gateway=gateway), self.assertRaises(ValueError):
                WindowsProfile.from_dict({**self.value,'gateway':gateway})


class Item:
    def __init__(self,name,path):
        self.name=name
        self.hash=SimpleNamespace(mode='sha256',value=base64.urlsafe_b64encode(
            hashlib.sha256(path.read_bytes()).digest()).rstrip(b'=').decode())
    def as_posix(self):return self.name


class InstallationTests(unittest.TestCase):
    def setUp(self):
        import adaptive_inference
        self.root=Path(adaptive_inference.__file__).resolve().parent
        self.rows=[Item('adaptive_inference/'+p.relative_to(self.root).as_posix(),p)
                   for p in self.root.rglob('*.py')]
        self.dist=SimpleNamespace(version='fixture',files=self.rows,read_text=lambda name:None,
            locate_file=lambda value:self.root.parent/(value.name if type(value) is Item else value))
        self.context=mock.patch.object(installation.metadata,'distribution',return_value=self.dist)
        self.context.start();self.addCleanup(self.context.stop)

    def test_record_verified_relative_identity_can_cross_installation_roots(self):
        value=installation.package_identity()
        self.assertIn('desktop/composition.py',value['files'])
        self.assertEqual(installation.package_identity(deepcopy(value)),value)
        self.assertTrue(all(not Path(name).is_absolute() for name in value['files']))

    def test_changed_record_or_expected_content_refused(self):
        value=installation.package_identity()
        value['files']['desktop/composition.py']='0'*64
        with self.assertRaises(RuntimeError):installation.package_identity(value)
        self.rows[0].hash.value='invalid'
        with self.assertRaises(RuntimeError):installation.package_identity()

    def test_editable_missing_or_duplicate_sources_refused(self):
        self.dist.read_text=lambda name:json.dumps({'dir_info':{'editable':True}})
        with self.assertRaises(RuntimeError):installation.package_identity()
        self.dist.read_text=lambda name:None
        self.dist.files=[]
        with self.assertRaises(RuntimeError):installation.package_identity()
        self.dist.files=self.rows+[self.rows[0]]
        with self.assertRaises(RuntimeError):installation.package_identity()

    def test_preloaded_alternate_canonical_module_refused(self):
        with mock.patch.dict(sys.modules,{'adaptive_inference.foreign':SimpleNamespace(__file__=__file__)}):
            with self.assertRaises(RuntimeError):installation.package_identity()
        with mock.patch.dict(sys.modules,{'adaptive_inference.desktop.shadow':SimpleNamespace(
                __file__=str(self.root/'desktop/installation.py'))}):
            with self.assertRaises(RuntimeError):installation.package_identity()

    def test_hash_equal_redirector_is_not_current_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'python.exe';path.write_bytes(b'fixture')
            expected=installation.sha(path)
            self.assertEqual(installation.verify_interpreter(path,expected),path)
            with mock.patch.object(installation,'sys',SimpleNamespace(executable=str(path),
                    _base_executable=str(path.parent/'base.exe'),prefix='venv',base_prefix='base')):
                with self.assertRaises(RuntimeError):installation.verify_interpreter(path,expected,current=True)


if __name__=='__main__':unittest.main()
