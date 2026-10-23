"""Admission checks run without network access, builds or model execution."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct


class ReconstructionChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'integration'
        (self.folder / 'patches').mkdir(parents=True)
        self.body = b'fixture patch\n'
        (self.folder / 'patches' / 'one.patch').write_bytes(self.body)
        self.lock = {'upstream_url': 'https://github.com/example/project.git', 'base_revision': 'a' * 40,
                     'patches': [{'file': 'patches/one.patch', 'sha256': hashlib.sha256(self.body).hexdigest()}],
                     'expected_files': {'source.py': 'b' * 64}}
        self.output = self.root / 'output'

    def run_setup(self):
        (self.folder / 'source-lock.json').write_text(json.dumps(self.lock), encoding='utf-8')
        with patch.object(sys, 'argv', ['setup.py', '--output', str(self.output)]), \
                patch.object(reconstruct.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            try:
                reconstruct.reconstruct(self.folder, 'https://github.com/example/project.git', 'a' * 40)
            finally:
                run.assert_not_called()

    def test_existing_directory_is_untouched(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'; marker.write_bytes(b'preserve me')
        with self.assertRaises(SystemExit): self.run_setup()
        self.assertEqual(marker.read_bytes(), b'preserve me')
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_bad_patch_hash_refuses_before_creating_output(self):
        (self.folder / 'patches' / 'one.patch').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'): self.run_setup()
        self.assertFalse(self.output.exists())

    def test_manifest_cannot_choose_another_remote(self):
        self.lock['upstream_url'] = 'https://example.invalid/other.git'
        with self.assertRaisesRegex(ValueError, 'fixed integration'): self.run_setup()
        self.assertFalse(self.output.exists())

    def test_patch_path_cannot_escape_integration(self):
        for name in ('../outside.patch', 'C:/outside.patch', '/outside.patch'):
            with self.subTest(name=name):
                self.lock['patches'][0]['file'] = name
                with self.assertRaisesRegex(ValueError, 'relative'): self.run_setup()
                self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
