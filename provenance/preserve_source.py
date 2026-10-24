"""Preserve a complete local Git source snapshot without fetching or executing it.

Example: python provenance/preserve_source.py --repository LOCAL_REPO
  --revision FULL_COMMIT --upstream-url PUBLIC_URL --output-prefix NEW_PREFIX

The .bundle and .manifest.json outputs must not exist. All tracked files, modes,
trees and the exact original commit are preserved, but ancestor history is not.
Submodules, symlinks, LFS pointers and unavailable blobs are refused explicitly.
The caller must review and retain upstream licensing before redistribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from reconstruct import GIT_OPTIONS, MAX_ARCHIVE, MAX_SOURCE, _inventory, digest, git, git_environment, hash_value


def preserve(repository, revision, upstream_url, output_prefix):
    repository = Path(repository).resolve(strict=True)
    hash_value(revision, 40)
    prefix = Path(output_prefix).expanduser().absolute()
    prefix = prefix.parent.resolve(strict=True) / prefix.name
    archive = Path(str(prefix) + '.bundle')
    inventory_path = Path(str(prefix) + '.manifest.json')
    if any(os.path.lexists(path) for path in (archive, inventory_path)):
        raise ValueError('Preservation outputs already exist; neither was modified')
    if not isinstance(upstream_url, str) or not upstream_url.startswith('https://') or '@' in upstream_url:
        raise ValueError('A public HTTPS provenance URL without credentials is required')
    if git(repository, 'rev-parse', revision + '^{commit}').decode().strip() != revision:
        raise ValueError('The exact commit is unavailable locally')
    commit = git(repository, 'cat-file', 'commit', revision)
    tree = git(repository, 'rev-parse', revision + '^{tree}').decode().strip()
    entries, objects, cache = [], {revision, tree}, {}
    raw_tree = git(repository, 'ls-tree', '-rtz', revision)
    process = subprocess.Popen([shutil.which('git'), *GIT_OPTIONS, 'cat-file', '--batch'], cwd=repository,
        env=git_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for row in raw_tree.split(b'\0'):
            if not row:
                continue
            metadata, path = row.split(b'\t', 1)
            mode, kind, oid = metadata.decode('ascii').split()
            objects.add(oid)
            if kind == 'tree':
                continue
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError('Submodules or symlinks require a separate reviewed preservation policy')
            if oid not in cache:
                process.stdin.write(oid.encode('ascii') + b'\n'); process.stdin.flush()
                header = process.stdout.readline().decode('ascii').split()
                if len(header) != 3 or header[:2] != [oid, 'blob']:
                    raise ValueError('A source blob is unavailable locally; preservation never fetches')
                size = int(header[2])
                if not 0 <= size <= MAX_SOURCE:
                    raise ValueError('Source blob exceeds size limit')
                content = process.stdout.read(size)
                if len(content) != size or process.stdout.read(1) != b'\n':
                    raise ValueError('Incomplete local source blob')
                if content.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                    raise ValueError('LFS pointer is not a complete source asset')
                cache[oid] = (size, hashlib.sha256(content).hexdigest())
            size, checksum = cache[oid]
            entries.append({'path': path.decode('utf-8'), 'mode': mode, 'git_blob': oid,
                            'bytes': size, 'sha256': checksum})
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise ValueError('Local source object reader failed')
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
    inventory = {'schema': 1, 'format': 'git-bundle-v2', 'upstream_url': upstream_url,
        'revision': revision, 'tree': tree, 'commit_sha256': hashlib.sha256(commit).hexdigest(),
        'parents': [line.split()[1].decode('ascii') for line in commit.split(b'\n\n', 1)[0].splitlines() if line.startswith(b'parent ')],
        'history': 'single pinned shallow commit; parent history is intentionally not included',
        'tracked_files': len(entries), 'uncompressed_bytes': sum(entry['bytes'] for entry in entries),
        'omitted_paths': [], 'lfs_pointer_paths': [], 'entries': entries}
    _inventory(inventory, revision, upstream_url)
    # Explicit object list excludes ancestor commits but includes every current
    # tree/blob. No thin pack or reused external delta can become a prerequisite.
    # Sorted IDs, one thread and no object/delta reuse make repeated creation
    # independent of source checkout state and existing pack layout.
    with archive.open('xb') as handle:
        handle.write(b'# v2 git bundle\n' + revision.encode('ascii') + b' HEAD\n\n')
        handle.flush()
        subprocess.run([shutil.which('git'), *GIT_OPTIONS, 'pack-objects', '--stdout',
            '--no-reuse-delta', '--no-reuse-object', '--threads=1', '--compression=9',
            '--window=10', '--depth=50'], cwd=repository, env=git_environment(),
            input=('\n'.join(sorted(objects)) + '\n').encode('ascii'), stdout=handle,
            stderr=subprocess.PIPE, check=True, timeout=600)
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Bundle exceeds shipping size limit; retained for inspection, not silently split or truncated')
    with inventory_path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
    return {'revision': revision, 'tree': tree, 'tracked_files': len(entries),
            'uncompressed_bytes': inventory['uncompressed_bytes'],
            'archive': {'file': archive.name, 'bytes': archive.stat().st_size, 'sha256': digest(archive)},
            'inventory': {'file': inventory_path.name, 'sha256': digest(inventory_path)},
            'scope': 'complete tracked source snapshot with exact commit; no ancestor history, network, dependencies or model execution'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--upstream-url', required=True)
    parser.add_argument('--output-prefix', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(preserve(args.repository, args.revision, args.upstream_url, args.output_prefix), indent=2))


if __name__ == '__main__':
    main()
