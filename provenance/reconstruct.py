"""Restore pinned integration source entirely from bundled local Git objects."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

MAX_ARCHIVE = 95 * 1024 * 1024
MAX_INVENTORY = 32 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024 * 1024
GIT_OPTIONS = ['-c', 'protocol.allow=never', '-c', 'core.autocrlf=false',
               '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
               '-c', 'core.attributesFile=' + os.devnull,
               '-c', 'core.filemode=' + ('false' if os.name == 'nt' else 'true')]


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def relative(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Invalid relative source path')
    path = PurePosixPath(value)
    if (not value or str(path) != value or path.is_absolute() or '..' in path.parts
            or '\\' in value or ':' in value or any(ord(c) < 32 for c in value)
            or any(p.lower() in ('.git', 'git~1') or p.endswith((' ', '.')) for p in path.parts)):
        raise ValueError('Invalid relative source path')
    return value


def hash_value(value, size=64):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
        raise ValueError('Invalid source hash')
    return value


def integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Source size/count exceeds its bound')
    return value


def git_environment():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
    return env


def git(directory, *arguments, input=None):
    executable = shutil.which('git')
    if not executable:
        raise RuntimeError('Git is required for local source-object restoration')
    result = subprocess.run([executable, *GIT_OPTIONS, *arguments], cwd=directory,
        env=git_environment(), input=input, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=600)
    return result.stdout


def _artifact(folder, item, prefix, *, maximum):
    name = relative(item['file'])
    path = (folder / name).resolve(strict=True)
    if not path.is_relative_to(folder.resolve()) or not name.startswith(prefix + '/') or not path.is_file():
        raise ValueError('Source artifact is outside its integration directory')
    if path.stat().st_size > maximum or digest(path) != hash_value(item['sha256']):
        raise ValueError('Artifact checksum or size mismatch: ' + name)
    return path


def _inventory(value, revision, upstream_url):
    if (value.get('schema') != 1 or value.get('format') != 'git-bundle-v2'
            or value.get('revision') != revision or value.get('upstream_url') != upstream_url
            or value.get('omitted_paths') != [] or value.get('lfs_pointer_paths') != []):
        raise ValueError('Inventory must identify the complete pinned source snapshot')
    hash_value(value['tree'], 40)
    hash_value(value['commit_sha256'])
    if not isinstance(value['parents'], list):
        raise ValueError('Invalid source parent list')
    for parent in value['parents']:
        hash_value(parent, 40)
    entries = value['entries']
    if not isinstance(entries, list) or not entries or len(entries) > 100000:
        raise ValueError('Invalid source inventory entries')
    paths, folded = set(), set()
    total = 0
    for entry in entries:
        if set(entry) != {'path', 'mode', 'git_blob', 'bytes', 'sha256'}:
            raise ValueError('Invalid source inventory entry')
        name = relative(entry['path'])
        if name in paths or name.casefold() in folded:
            raise ValueError('Duplicate or nonportable source path')
        paths.add(name); folded.add(name.casefold())
        if entry['mode'] not in ('100644', '100755'):
            raise ValueError('Only complete regular-file source trees are supported')
        hash_value(entry['git_blob'], 40); hash_value(entry['sha256'])
        total += integer(entry['bytes'], MAX_SOURCE)
    if total > MAX_SOURCE or total != value['uncompressed_bytes'] or len(entries) != value['tracked_files']:
        raise ValueError('Source inventory totals differ')
    for name in paths:
        if any(str(parent) in paths for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ValueError('Source file conflicts with a parent directory')
    return value


def _source(folder, descriptor, revision, upstream_url):
    hash_value(revision, 40)
    archive = _artifact(folder, descriptor['archive'], 'source', maximum=MAX_ARCHIVE)
    if archive.stat().st_size != integer(descriptor['archive']['bytes'], MAX_ARCHIVE):
        raise ValueError('Archive length differs from source lock')
    inventory_path = _artifact(folder, descriptor['inventory'], 'source', maximum=MAX_INVENTORY)
    inventory = _inventory(json.loads(inventory_path.read_text(encoding='utf-8')), revision, upstream_url)
    with archive.open('rb') as handle:
        if handle.readline(64) != b'# v2 git bundle\n':
            raise ValueError('Unsupported bundle header')
        if handle.readline(256) != (revision + ' HEAD\n').encode('ascii') or handle.readline(2) != b'\n':
            raise ValueError('Bundle has prerequisites or unexpected source references')
    return {'archive': archive, 'inventory_path': inventory_path, 'inventory': inventory,
            'descriptor': descriptor, 'revision': revision}


def load_plan(folder, upstream_url, revision):
    folder = folder.resolve(strict=True)
    manifest = json.loads((folder / 'source-lock.json').read_text(encoding='utf-8'))
    if manifest['base_revision'] != revision or manifest['upstream_url'] != upstream_url:
        raise ValueError('Source lock differs from the fixed integration identity')
    if manifest.get('schema') != 2:
        raise ValueError('Source lock requires bundled offline sources (schema 2)')
    hash_value(manifest['expected_tree'], 40)
    patches = []
    for item in manifest['patches']:
        patches.append(_artifact(folder, item, 'patches', maximum=32 * 1024 * 1024))
    expected = {relative(name): hash_value(sha) for name, sha in manifest['expected_files'].items()}
    baseline = _source(folder, manifest['baseline'], revision, upstream_url)
    used_paths = {entry['path'] for entry in baseline['inventory']['entries']} | set(expected)
    dependencies = []
    prefixes = []
    for dependency in manifest['dependencies']:
        prefix = relative(dependency['output_directory'])
        if (any(name == prefix or name.startswith(prefix + '/') or prefix.startswith(name + '/') for name in used_paths)
                or any(prefix == old or prefix.startswith(old + '/') or old.startswith(prefix + '/') for old in prefixes)):
            raise ValueError('Dependency output overlaps another source tree')
        prefixes.append(prefix)
        source = _source(folder, dependency['baseline'], dependency['base_revision'], dependency['upstream_url'])
        source.update(name=dependency['name'], output_directory=prefix)
        dependencies.append(source)
    return manifest, baseline, dependencies, patches, expected


def _raw_tree(directory, revision):
    result = {}
    for row in git(directory, 'ls-tree', '-rz', revision).split(b'\0'):
        if row:
            header, name = row.split(b'\t', 1)
            mode, kind, oid = header.decode('ascii').split()
            if kind != 'blob':
                raise ValueError('Source contains an undeclared submodule or non-file entry')
            result[name.decode('utf-8')] = (mode, oid)
    return result


def _materialize(directory, source):
    inventory, revision = source['inventory'], source['revision']
    git(directory, 'init', '--quiet')
    git(directory, 'bundle', 'verify', str(source['archive']))
    git(directory, 'bundle', 'unbundle', str(source['archive']))
    commit = git(directory, 'cat-file', 'commit', revision)
    parents = [line.split()[1].decode('ascii') for line in commit.split(b'\n\n', 1)[0].splitlines()
               if line.startswith(b'parent ')]
    if hashlib.sha256(commit).hexdigest() != inventory['commit_sha256'] or parents != inventory['parents']:
        raise RuntimeError('Original commit bytes/parents differ from inventory')
    if git(directory, 'rev-parse', revision + '^{tree}').decode().strip() != inventory['tree']:
        raise RuntimeError('Base tree differs from inventory')
    expected = {entry['path']: (entry['mode'], entry['git_blob']) for entry in inventory['entries']}
    if _raw_tree(directory, revision) != expected:
        raise RuntimeError('Complete base tree differs from file/mode/blob inventory')
    (directory / '.git/shallow').write_text(revision + '\n', encoding='ascii', newline='\n')
    git(directory, 'update-ref', 'HEAD', revision)
    git(directory, 'read-tree', revision)
    # Preserve canonical blobs: tracked attributes cannot expand identifiers,
    # invoke smudge filters or rewrite line endings. Git parses its own pack.
    executable = shutil.which('git')
    process = subprocess.Popen([executable, *GIT_OPTIONS, 'cat-file', '--batch'], cwd=directory,
        env=git_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for entry in inventory['entries']:
            oid, size = entry['git_blob'], entry['bytes']
            process.stdin.write(oid.encode('ascii') + b'\n'); process.stdin.flush()
            if process.stdout.readline().decode('ascii').split() != [oid, 'blob', str(size)]:
                raise RuntimeError('Source blob is missing or has an unexpected size')
            data = process.stdout.read(size)
            if (len(data) != size or process.stdout.read(1) != b'\n'
                    or hashlib.sha256(data).hexdigest() != entry['sha256']):
                raise RuntimeError('Source blob content differs: ' + entry['path'])
            path = directory / entry['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as handle:
                handle.write(data)
            path.chmod(0o755 if entry['mode'] == '100755' else 0o644)
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise RuntimeError('Local Git object reader failed')
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
    if git(directory, 'write-tree').decode().strip() != inventory['tree']:
        raise RuntimeError('Restored index tree differs')
    git(directory, 'update-index', '--refresh')
    receipt = {'base_revision': revision, 'git_tree': inventory['tree'],
               'archive_sha256': source['descriptor']['archive']['sha256'],
               'inventory_sha256': source['descriptor']['inventory']['sha256'],
               'verified_files': inventory['tracked_files'], 'history': inventory['history']}
    (directory / '.git/adaptive-source.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def reconstruct(folder: Path, upstream_url: str, revision: str) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--output', type=Path, help='New source directory; its parent must already exist')
    choices.add_argument('--verify-only', action='store_true', help='Verify local artifact hashes/inventories without creating output')
    args = parser.parse_args()
    output = None
    if args.output is not None:
        output = args.output.expanduser().absolute()
        if os.path.lexists(output):
            parser.error('Output already exists; it was not modified')
        output = output.parent.resolve(strict=True) / output.name
    manifest, baseline, dependencies, patches, expected = load_plan(folder, upstream_url, revision)
    if args.verify_only:
        print(json.dumps({'offline': True, 'base_revision': revision,
            'verified_source_archives': 1 + len(dependencies), 'verified_patches': len(patches),
            'scope': 'local artifact hashes, inventory and bundle-header admission only; no extraction or build'}, indent=2))
        return
    if not shutil.which('git'):
        raise RuntimeError('Git is required')
    output.mkdir(exist_ok=False)
    try:
        base_receipt = _materialize(output, baseline)
        for path in patches:
            git(output, 'apply', '--check', '--index', str(path))
            git(output, 'apply', '--index', str(path))
        actual = {name.decode('utf-8') for name in git(output, 'diff', '--cached', '--name-only', '-z', revision, '--').split(b'\0') if name}
        if actual != set(expected):
            raise RuntimeError('Reconstructed change set differs from the source lock')
        for name, sha in expected.items():
            path = output / name
            if not path.is_file() or path.is_symlink() or digest(path) != sha:
                raise RuntimeError('Reconstructed source checksum mismatch: ' + name)
        tree = git(output, 'write-tree').decode().strip()
        if tree != manifest['expected_tree']:
            raise RuntimeError('Complete reconstructed Git tree differs from the pinned expected tree')
        git(output, 'diff', '--cached', '--check')
        if git(output, 'diff', '--name-only'):
            raise RuntimeError('Unexpected unstaged source change')
        dependency_receipts = []
        for source in dependencies:
            destination = output / source['output_directory']
            destination.mkdir(parents=True, exist_ok=False)
            receipt = _materialize(destination, source)
            receipt.update(name=source['name'], output_directory=source['output_directory'])
            dependency_receipts.append(receipt)
        receipt = {'schema': 2, 'offline': True, 'base_revision': revision,
                   'base_tree': baseline['inventory']['tree'], 'baseline': base_receipt,
                   'source_lock_sha256': digest(folder / 'source-lock.json'), 'patches': manifest['patches'],
                   'verified_changed_files': len(expected), 'reconstructed_git_tree': tree,
                   'dependencies': dependency_receipts,
                   'scope': 'complete pinned source snapshots and overlays only; no dependencies installed, build, model or tests run'}
        (output / '.git/adaptive-integration.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    except BaseException:
        print('Reconstruction failed; the new output was retained for inspection. Existing paths were not changed.')
        raise
