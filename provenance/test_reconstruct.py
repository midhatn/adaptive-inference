"""Real offline Git-object restoration and fail-closed artifact admission."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct
from offline_acceptance import OfflineGuard, _check_base, _check_tree
from preserve_source import preserve


@unittest.skipUnless(shutil.which('git'), 'Git is required for source reconstruction')
class ReconstructionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        cls.repo = root / 'upstream'; cls.repo.mkdir()
        reconstruct.git(cls.repo, 'init', '--quiet')
        (cls.repo / 'source.py').write_bytes(b'value = 1\n')
        reconstruct.git(cls.repo, 'add', 'source.py')
        reconstruct.git(cls.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '--quiet', '-m', 'parent')
        cls.parent_revision = reconstruct.git(cls.repo, 'rev-parse', 'HEAD').decode().strip()
        (cls.repo / '.gitattributes').write_bytes(b'ids.txt ident\nexcluded.txt export-ignore\n')
        (cls.repo / 'ids.txt').write_bytes(b'$Id$\n')
        (cls.repo / 'excluded.txt').write_bytes(b'An export-ignore file is still part of the complete tree.\n')
        (cls.repo / 'run.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
        (cls.repo / 'unicode-λ.txt').write_bytes('Source bytes: λ\n'.encode())
        reconstruct.git(cls.repo, 'add', '.')
        reconstruct.git(cls.repo, 'update-index', '--chmod=+x', 'run.sh')
        reconstruct.git(cls.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '--quiet', '-m', 'base')
        cls.revision = reconstruct.git(cls.repo, 'rev-parse', 'HEAD').decode().strip()
        cls.url = 'https://example.invalid/public/source.git'
        cls.template = root / 'integration'
        (cls.template / 'source').mkdir(parents=True)
        (cls.template / 'patches').mkdir()
        # The working checkout is deliberately dirty. Preservation reads only
        # the pinned object tree, including files git archive would omit.
        (cls.repo / 'source.py').write_bytes(b'value = 2\n')
        reconstruct.git(cls.repo, 'add', 'source.py')
        (cls.repo / 'private-untracked.txt').write_bytes(b'Never include this checkout file.\n')
        patch_bytes = reconstruct.git(cls.repo, 'diff', '--cached', '--binary', '--full-index', cls.revision)
        patch_path = cls.template / 'patches/change.patch'; patch_path.write_bytes(patch_bytes)
        final_tree = reconstruct.git(cls.repo, 'write-tree').decode().strip()
        result = preserve(cls.repo, cls.revision, cls.url, cls.template / 'source/base')
        cls.lock = {'schema': 2, 'upstream_url': cls.url, 'base_revision': cls.revision,
            'baseline': {'archive': {**result['archive'], 'file': 'source/base.bundle'},
                         'inventory': {**result['inventory'], 'file': 'source/base.manifest.json'}},
            'patches': [{'file': 'patches/change.patch', 'sha256': reconstruct.digest(patch_path)}],
            'expected_files': {'source.py': reconstruct.digest(cls.repo / 'source.py')},
            'expected_tree': final_tree, 'dependencies': []}

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'integration'
        shutil.copytree(self.template, self.folder)
        self.lock = copy.deepcopy(type(self).lock)
        self.output = self.root / 'output'

    def write_lock(self):
        (self.folder / 'source-lock.json').write_text(json.dumps(self.lock), encoding='utf-8')

    def run_setup(self, verify_only=False):
        self.write_lock()
        arguments = ['setup.py', '--verify-only'] if verify_only else ['setup.py', '--output', str(self.output)]
        with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            reconstruct.reconstruct(self.folder, self.url, self.revision)

    def admission_refuses(self, exception=ValueError):
        with patch.object(reconstruct.subprocess, 'run') as run, patch.object(reconstruct.subprocess, 'Popen') as popen:
            with self.assertRaises(exception):
                self.run_setup()
            run.assert_not_called(); popen.assert_not_called()
        self.assertFalse(self.output.exists())

    def mutate_inventory(self, function):
        path = self.folder / self.lock['baseline']['inventory']['file']
        value = json.loads(path.read_text())
        function(value)
        path.write_text(json.dumps(value), encoding='utf-8')
        self.lock['baseline']['inventory']['sha256'] = reconstruct.digest(path)

    def test_real_restore_preserves_commit_complete_tree_raw_bytes_and_modes(self):
        self.run_setup()
        receipt = json.loads((self.output / '.git/adaptive-integration.json').read_text())
        self.assertTrue(receipt['offline'])
        self.assertEqual(receipt['reconstructed_git_tree'], self.lock['expected_tree'])
        self.assertEqual(reconstruct.git(self.output, 'rev-parse', 'HEAD').decode().strip(), self.revision)
        self.assertEqual((self.output / 'source.py').read_bytes(), b'value = 2\n')
        self.assertEqual((self.output / 'ids.txt').read_bytes(), b'$Id$\n')
        self.assertTrue((self.output / 'excluded.txt').is_file())
        self.assertFalse((self.output / 'private-untracked.txt').exists())
        self.assertEqual(reconstruct.git(self.output, 'ls-files', '--stage', 'run.sh').split()[0], b'100755')
        if os.name != 'nt':
            self.assertTrue((self.output / 'run.sh').stat().st_mode & 0o111)
        self.assertEqual((self.output / '.git/shallow').read_text().strip(), self.revision)
        with self.assertRaises(subprocess.CalledProcessError):
            reconstruct.git(self.output, 'cat-file', '-e', self.parent_revision)
        reconstruct.git(self.output, 'fsck', '--full')

    def test_declared_dependency_restores_separate_complete_base(self):
        self.lock['dependencies'] = [{'name': 'fixture', 'upstream_url': self.url,
            'base_revision': self.revision, 'output_directory': '_adaptive_dependencies/fixture',
            'baseline': copy.deepcopy(self.lock['baseline'])}]
        self.run_setup()
        dependency = self.output / '_adaptive_dependencies/fixture'
        self.assertEqual((dependency / 'source.py').read_bytes(), b'value = 1\n')
        receipt = json.loads((self.output / '.git/adaptive-integration.json').read_text())
        self.assertEqual(receipt['dependencies'][0]['git_tree'], reconstruct.git(dependency, 'write-tree').decode().strip())

    def test_deep_output_preserves_long_file_and_refreshes_index_offline(self):
        repository = self.root / 'long-upstream'
        repository.mkdir()
        reconstruct.git(repository, 'init', '--quiet')
        relative = 'nested/' + 'a' * 55 + '/' + 'b' * 55 + '/source.txt'
        source = repository / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(b'Canonical source at a long Windows output path.\n')
        reconstruct.git(repository, 'add', '.')
        reconstruct.git(repository, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '--quiet', '-m', 'long path fixture')
        self.revision = reconstruct.git(repository, 'rev-parse', 'HEAD').decode().strip()
        tree = reconstruct.git(repository, 'rev-parse', 'HEAD^{tree}').decode().strip()
        preserved = preserve(repository, self.revision, self.url, self.folder / 'source/long-base')
        self.lock = {'schema': 2, 'upstream_url': self.url, 'base_revision': self.revision,
            'baseline': {'archive': {**preserved['archive'], 'file': 'source/long-base.bundle'},
                         'inventory': {**preserved['inventory'], 'file': 'source/long-base.manifest.json'}},
            'patches': [], 'expected_files': {}, 'expected_tree': tree, 'dependencies': []}
        parent = self.root / ('deep-' + 'p' * 95)
        parent.mkdir()
        self.output = parent / 'restored'
        materialized = self.output / relative
        self.assertGreater(len(str(materialized)), 260)
        with OfflineGuard() as guard:
            self.run_setup()
            self.assertEqual(materialized.read_bytes(), source.read_bytes())
            refresh = guard.command(self.output, 'update-index', '--refresh')
            self.assertEqual(refresh.returncode, 0, refresh.stderr)
            _check_base(guard, self.output, self.revision, tree)
            result = _check_tree(guard, self.output, tree, {relative: reconstruct.digest(source)})
            self.assertEqual(result['verified_files'], 1)
            # The failure control is Windows-specific; neither command changes
            # global or repository configuration or rewrites source content.
            if os.name == 'nt':
                disabled = guard.command(self.output, '-c', 'core.longpaths=false', 'update-index', '--refresh')
                self.assertNotEqual(disabled.returncode, 0)
                self.assertIn('needs update', disabled.stdout)
            self.assertEqual(guard.socket_attempts, 0)

    def test_verify_only_admits_artifacts_without_process_or_output(self):
        with patch.object(reconstruct.subprocess, 'run') as run, patch.object(reconstruct.subprocess, 'Popen') as popen:
            self.run_setup(verify_only=True)
            run.assert_not_called(); popen.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_directory_is_untouched(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'; marker.write_bytes(b'preserve me')
        with self.assertRaises(SystemExit):
            self.run_setup()
        self.assertEqual(marker.read_bytes(), b'preserve me')
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_bad_patch_or_bundle_hash_refuses_before_creating_output(self):
        (self.folder / 'patches/change.patch').write_bytes(b'tampered')
        self.admission_refuses()
        shutil.copyfile(self.template / 'patches/change.patch', self.folder / 'patches/change.patch')
        (self.folder / 'source/base.bundle').write_bytes(b'tampered')
        self.admission_refuses()

    def test_missing_bundle_never_fetches(self):
        (self.folder / 'source/base.bundle').unlink()
        self.admission_refuses(FileNotFoundError)

    def test_manifest_cannot_choose_another_remote_or_revision(self):
        self.lock['upstream_url'] = 'https://example.invalid/other.git'
        self.admission_refuses()

    def test_paths_cannot_escape_or_overlap_source(self):
        for name in ('../outside.patch', 'C:/outside.patch', '/outside.patch', 'patches/../outside.patch'):
            with self.subTest(name=name):
                self.lock['patches'][0]['file'] = name
                self.admission_refuses()
        self.lock['patches'][0]['file'] = 'patches/change.patch'
        self.lock['dependencies'] = [{'name': 'bad', 'base_revision': self.revision, 'upstream_url': self.url,
            'output_directory': 'source.py/dependency', 'baseline': self.lock['baseline']}]
        self.admission_refuses()

    def test_inventory_path_traversal_and_declared_omissions_refuse(self):
        self.mutate_inventory(lambda value: value['entries'][0].update(path='../escaped'))
        self.admission_refuses()
        shutil.copyfile(self.template / 'source/base.manifest.json', self.folder / 'source/base.manifest.json')
        self.mutate_inventory(lambda value: value.update(omitted_paths=['unlisted.py']))
        self.admission_refuses()

    def test_complete_tree_detects_undeclared_inventory_omission(self):
        def remove(value):
            entry = value['entries'].pop()
            value['tracked_files'] -= 1
            value['uncompressed_bytes'] -= entry['bytes']
        self.mutate_inventory(remove)
        with self.assertRaisesRegex(RuntimeError, 'Complete base tree'):
            self.run_setup()
        self.assertTrue(self.output.is_dir())
        self.assertFalse((self.output / 'source.py').exists())

    def test_complete_final_tree_is_required_beyond_changed_file_hashes(self):
        self.lock['expected_tree'] = 'a' * 40
        with self.assertRaisesRegex(RuntimeError, 'Complete reconstructed Git tree'):
            self.run_setup()
        self.assertTrue(self.output.is_dir())

    def test_preservation_is_repeatable_and_existing_outputs_are_untouched(self):
        first = preserve(self.repo, self.revision, self.url, self.root / 'first')
        second = preserve(self.repo, self.revision, self.url, self.root / 'second')
        self.assertEqual(first['archive']['sha256'], second['archive']['sha256'])
        self.assertEqual(first['inventory']['sha256'], second['inventory']['sha256'])
        with self.assertRaisesRegex(ValueError, 'already exist'):
            preserve(self.repo, self.revision, self.url, self.root / 'first')
        self.assertEqual(reconstruct.digest(self.root / 'first.bundle'), first['archive']['sha256'])

    def test_missing_local_blob_refuses_preservation_without_output(self):
        repository = self.root / 'missing-blob'
        shutil.copytree(self.repo, repository)
        oid = reconstruct.git(repository, 'rev-parse', self.revision + ':source.py').decode().strip()
        missing = repository / '.git/objects' / oid[:2] / oid[2:]
        missing.chmod(0o644)
        missing.unlink()
        with self.assertRaisesRegex(ValueError, 'unavailable locally'):
            preserve(repository, self.revision, self.url, self.root / 'unavailable')
        self.assertFalse((self.root / 'unavailable.bundle').exists())
        self.assertFalse((self.root / 'unavailable.manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
