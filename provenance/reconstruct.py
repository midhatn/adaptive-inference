"""Materialize one pinned public integration without executing its code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in value or ':' in value:
        raise ValueError('Invalid relative source path')
    return value


def reconstruct(folder: Path, upstream_url: str, revision: str) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path,
                        help='New source directory; its parent must already exist')
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    # Refuse even an empty directory or dangling symlink. Never reset, clean,
    # delete or adopt an existing checkout, including after a failed attempt.
    if os.path.lexists(output):
        parser.error('Output already exists; it was not modified')
    output = output.parent.resolve(strict=True) / output.name
    manifest = json.loads((folder / 'source-lock.json').read_text(encoding='utf-8'))
    if manifest['base_revision'] != revision or manifest['upstream_url'] != upstream_url:
        raise ValueError('Source lock differs from the fixed integration identity')
    patches = []
    for item in manifest['patches']:
        name = relative(item['file'])
        path = (folder / name).resolve(strict=True)
        if not path.is_relative_to(folder.resolve()) or not name.startswith('patches/'):
            raise ValueError('Patch is outside the integration')
        if digest(path) != item['sha256']:
            raise ValueError('Patch checksum mismatch: ' + name)
        patches.append(path)
    expected = {relative(name): sha for name, sha in manifest['expected_files'].items()}
    executable = shutil.which('git')
    if not executable:
        raise RuntimeError('Git is required')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    output.mkdir(exist_ok=False)

    def git(*arguments: str) -> str:
        result = subprocess.run([executable, '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false',
            '-c', 'core.hooksPath=' + str(output / '.git' / 'disabled-hooks'), *arguments],
            cwd=output, env=env, check=True, text=True, encoding='utf-8',
            stdout=subprocess.PIPE, timeout=600)
        return result.stdout.strip()

    try:
        git('init', '--quiet')
        git('remote', 'add', 'origin', upstream_url)
        git('fetch', '--no-tags', '--depth=1', 'origin', revision)
        if git('rev-parse', 'FETCH_HEAD') != revision:
            raise RuntimeError('Fetched revision does not match the public pin')
        git('checkout', '--quiet', '--detach', '--no-recurse-submodules', 'FETCH_HEAD')
        for path in patches:
            git('apply', '--check', '--index', str(path))
            git('apply', '--index', str(path))
        actual = set(git('diff', '--cached', '--name-only', revision, '--').splitlines())
        if actual != set(expected):
            raise RuntimeError('Reconstructed change set differs from the source lock')
        for name, sha in expected.items():
            path = output / name
            if not path.is_file() or path.is_symlink() or digest(path) != sha:
                raise RuntimeError('Reconstructed source checksum mismatch: ' + name)
        git('diff', '--cached', '--check')
        if git('diff', '--name-only'):
            raise RuntimeError('Unexpected unstaged source change')
        receipt = {'base_revision': revision, 'source_lock_sha256': digest(folder / 'source-lock.json'),
                   'patches': manifest['patches'], 'verified_changed_files': len(expected),
                   'reconstructed_git_tree': git('write-tree'),
                   'scope': 'source reconstruction only; no dependencies installed, build, model or tests run'}
        (output / '.git' / 'adaptive-integration.json').write_text(
            json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    except BaseException:
        print('Reconstruction failed; the new output was retained for inspection. Existing paths were not changed.')
        raise
