"""Archive identity checks use real ZIP/tar bytes; no package is installed."""
import base64
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('distribution_check', ROOT / 'provenance/check_distribution.py')
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


class DistributionChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in distribution.TOP_LEVEL:
            (self.root / name).write_text('fixture\n', encoding='utf-8')
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "0.3.0"\n', encoding='utf-8')
        for name in ('src/adaptive_inference/__init__.py',
                     'src/adaptive_inference/desktop/installation.py',
                     'third_party/strata/LICENSE', 'third_party/finagle/LICENSE',
                     'third_party/finagle/NOTICE',
                     'examples/validation/latency_drift/LICENSE.river'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# fixture\n')
        self.sdist = self.root / 'source.tar.gz'
        with tarfile.open(self.sdist, 'w:gz') as archive:
            for name, path in distribution.expected_files(self.root).items():
                archive.add(path, arcname='adaptive_inference-0.3.0/' + name)
        self.wheel = self.root / 'runtime.whl'
        self.prefix = 'adaptive_inference-0.3.0.dist-info/'
        self.members = {'adaptive_inference/' + str(path.relative_to(self.root / 'src/adaptive_inference')).replace('\\', '/'):
                        path.read_bytes() for path in (self.root / 'src/adaptive_inference').rglob('*.py')}
        self.members.update({self.prefix + name: b'fixture\n' for name in
                            ('METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt')})
        self.members[self.prefix + 'METADATA'] = (
            'Metadata-Version: 2.4\nName: adaptive-inference\nVersion: 0.3.0\n' +
            ''.join('License-File: ' + name + '\n' for name in distribution.WHEEL_LICENSE_FILES) + '\n'
        ).encode()
        self.members.update({self.prefix + 'licenses/' + name: (self.root / name).read_bytes()
                             for name in distribution.WHEEL_LICENSE_FILES})

    def write_wheel(self, *, members=None, rows_change=None, duplicate=False):
        members = dict(self.members if members is None else members)
        record = self.prefix + 'RECORD'
        rows = [[name, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b'=').decode(), str(len(raw))]
                for name, raw in members.items()]
        rows.append([record, '', ''])
        if rows_change is not None:
            rows_change(rows)
        stream = io.StringIO(newline='')
        csv.writer(stream).writerows(rows)
        members[record] = stream.getvalue().encode()
        with zipfile.ZipFile(self.wheel, 'w') as archive:
            for name, raw in members.items():
                archive.writestr(name, raw)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr('adaptive_inference/__init__.py', b'# fixture\n')

    def check(self):
        return distribution.check(self.sdist, self.wheel, self.root)

    def test_verified_archive_identity_is_derived_from_wheel(self):
        self.write_wheel()
        result = self.check()
        self.assertTrue(result['passed'])
        self.assertEqual(result['installed_identity'], {'version': '0.3.0', 'files': {
            '__init__.py': hashlib.sha256(b'# fixture\n').hexdigest(),
            'desktop/installation.py': hashlib.sha256(b'# fixture\n').hexdigest()}})

    def test_exact_runtime_refuses_missing_extra_or_changed_modules(self):
        for kind in ('missing', 'extra', 'changed'):
            with self.subTest(kind=kind):
                members = dict(self.members)
                if kind == 'missing':
                    del members['adaptive_inference/__init__.py']
                elif kind == 'extra':
                    members['adaptive_inference/unexpected.py'] = b'pass\n'
                else:
                    members['adaptive_inference/__init__.py'] = b'changed\n'
                self.write_wheel(members=members)
                with self.assertRaisesRegex(ValueError, 'Python module'):
                    self.check()

    def test_record_rejects_malformed_missing_duplicate_hash_and_size(self):
        changes = {
            'malformed': lambda rows: rows[0].append('fourth'),
            'missing': lambda rows: rows.pop(0),
            'duplicate': lambda rows: rows.append(rows[0]),
            'hash': lambda rows: rows[0].__setitem__(1, 'sha256=wrong'),
            'size': lambda rows: rows[0].__setitem__(2, '999'),
            'self': lambda rows: rows[-1].__setitem__(1, 'sha256=wrong'),
        }
        for name, change in changes.items():
            with self.subTest(kind=name):
                self.write_wheel(rows_change=change)
                with self.assertRaisesRegex(ValueError, 'RECORD'):
                    self.check()

    def test_archive_rejects_duplicate_unsafe_and_unexpected_members(self):
        self.write_wheel(duplicate=True)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.check()
        for name in ('../outside', '/absolute', 'folder\\file', 'C:relative', 'folder//file', 'unexpected.txt'):
            with self.subTest(name=name):
                self.write_wheel(members={**self.members, name: b'extra'})
                with self.assertRaisesRegex(ValueError, 'wheel member'):
                    self.check()

    def test_source_archive_mismatch_still_refuses(self):
        self.write_wheel()
        (self.root / 'README.md').write_text('changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Source distribution differs'):
            self.check()

    def test_river_license_is_required_and_exact_in_both_archives(self):
        license_name = 'examples/validation/latency_drift/LICENSE.river'
        wheel_name = self.prefix + 'licenses/' + license_name
        for change in ('missing', 'changed'):
            with self.subTest(archive='wheel', change=change):
                members = dict(self.members)
                if change == 'missing':
                    del members[wheel_name]
                else:
                    members[wheel_name] = b'changed notice\n'
                self.write_wheel(members=members)
                with self.assertRaisesRegex(ValueError, 'wheel member|Wheel license differs'):
                    self.check()
        self.write_wheel()
        with tarfile.open(self.sdist, 'w:gz') as archive:
            for name, path in distribution.expected_files(self.root).items():
                if name != license_name:
                    archive.add(path, arcname='adaptive_inference-0.3.0/' + name)
        with self.assertRaisesRegex(ValueError, 'Source distribution omits:.*LICENSE.river'):
            self.check()

    def test_license_metadata_matches_exact_notices_without_shared_expression(self):
        original = self.members[self.prefix + 'METADATA']
        river_field = b'License-File: examples/validation/latency_drift/LICENSE.river\n'
        for raw in (original.replace(river_field, b''),
                    original.replace(river_field, river_field * 2),
                    original.replace(river_field, b'License-File: unexpected\n'),
                    b'License-Expression: Apache-2.0 AND MIT\n' + original):
            with self.subTest(metadata=raw):
                self.write_wheel(members={**self.members, self.prefix + 'METADATA': raw})
                with self.assertRaisesRegex(ValueError, 'METADATA license'):
                    self.check()

    def test_metadata_cannot_export_an_identity_the_installer_would_change(self):
        for raw in (b'Name: adaptive-inference\nVersion: 99.0\n\n',
                    b'Name: different-project\nVersion: 0.3.0\n\n',
                    b'Name: adaptive-inference\nVersion: 0.3.0\nVersion: 0.3.0\n\n',
                    b'Name: adaptive-inference\nName: different\nVersion: 0.3.0\n\n',
                    b'Name: adaptive-inference\n\n'):
            with self.subTest(metadata=raw):
                self.write_wheel(members={**self.members, self.prefix + 'METADATA': raw})
                with self.assertRaisesRegex(ValueError, 'METADATA'):
                    self.check()

    def run_cli(self, output):
        with mock.patch.object(distribution, 'ROOT', self.root), \
                mock.patch.object(distribution, 'check', side_effect=lambda s, w: distribution_check(s, w, self.root)), \
                contextlib.redirect_stdout(io.StringIO()):
            distribution.main(['--sdist', str(self.sdist), '--wheel', str(self.wheel), '--output', str(output)])

    def test_cli_publishes_identity_only_after_check_and_refuses_reuse(self):
        self.write_wheel()
        output = self.root / 'verified'
        self.run_cli(output)
        expected = (output / 'installed-identity.json').read_bytes()
        self.assertEqual(json.loads(expected), self.check()['installed_identity'])
        with self.assertRaises(FileExistsError):
            self.run_cli(output)
        self.assertEqual((output / 'installed-identity.json').read_bytes(), expected)

    def test_cli_retains_failure_without_publishing_identity(self):
        self.write_wheel(rows_change=lambda rows: rows.pop(0))
        output = self.root / 'failed'
        with self.assertRaises(ValueError):
            self.run_cli(output)
        self.assertFalse(json.loads((output / 'result.json').read_text())['passed'])
        self.assertFalse((output / 'installed-identity.json').exists())


distribution_check = distribution.check
