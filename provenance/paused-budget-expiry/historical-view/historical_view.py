# SPDX-License-Identifier: Apache-2.0
"""Build the small exact PR20 source view; no runtime, Git or network execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import tempfile
import types

HERE = Path(__file__).absolute().parent
MAP_SHA = '32c61bee28553073d9d68352471f1c4e5d01d789e4b711b8492461f5f3eef726'
FREEZE_SHA = 'bf70a2acc69cd6a1d9954ad3fe8dbd69f3c43aefa97803f079b15b5662e071db'
RECONSTRUCT = 'provenance/reconstruct.py'
RECONSTRUCT_SHA = '07366fc4d8712d08a51d81f5cf5c2b9a5ff4d17fbd23a8a0d4037ad7c062feee'
MAX_BYTES = 2 * 1024 * 1024


def _plain(path, directory):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('Historical source path is not a plain directory/file')
    return info


def _root(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Explicit absolute local root required')
    current = Path(path.anchor)
    _plain(current, True)
    for part in path.parts[1:]:
        current /= part
        _plain(current, True)
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise ValueError('Redirected historical root')
    return resolved


def _file(root, name):
    # Public descriptors additionally pass reconstruct.relative below.
    value = PurePosixPath(name)
    if (not name or str(value) != name or value.is_absolute() or '..' in value.parts
            or '\\' in name or ':' in name):
        raise ValueError('Invalid historical input path')
    current = root
    for index, part in enumerate(value.parts):
        if PureWindowsPath(part).is_reserved():
            raise ValueError('Reserved historical path component')
        if part not in {entry.name for entry in current.iterdir()}:
            raise ValueError('Missing or differently cased historical path')
        current /= part
        _plain(current, index != len(value.parts)-1)
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved != current:
        raise ValueError('Historical input escaped its root')
    return current


def _names(names, relative):
    exact, folded = set(), {}
    for name in names:
        relative(name)
        if name in exact:
            raise ValueError('Duplicate historical output path')
        exact.add(name)
        parts = PurePosixPath(name).parts
        for index, part in enumerate(parts):
            if PureWindowsPath(part).is_reserved(): raise ValueError('Reserved output component')
            prefix = '/'.join(parts[:index+1])
            old = folded.setdefault(prefix.casefold(), prefix)
            if old != prefix: raise ValueError('Case-colliding historical output path')
    for name in exact:
        if any(str(parent) in exact for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ValueError('Historical file/directory collision')


def load_plan(repository):
    repository = _root(repository)
    helper_path = _file(repository, RECONSTRUCT)
    code = helper_path.read_bytes()
    if hashlib.sha256(code).hexdigest() != RECONSTRUCT_SHA:
        raise ValueError('Reconstruction helpers changed')
    helper = types.ModuleType('pr20_reconstruct_helpers')
    helper.__file__ = str(helper_path)
    exec(compile(code, str(helper_path), 'exec'), helper.__dict__)
    if helper.digest(_file(repository, RECONSTRUCT)) != RECONSTRUCT_SHA:
        raise ValueError('Reconstruction helpers changed during load')
    map_root = _root(HERE)
    map_path = _file(map_root, 'source-map.json')
    if helper.digest(map_path) != MAP_SHA: raise ValueError('Historical mapping changed')
    mapping = json.loads(map_path.read_bytes())
    if (set(mapping) != {'schema','reviewed_source','helper_files','mappings','files','bytes'}
            or mapping['schema'] != 'adaptive.paused-expiry.historical-view.v1'
            or mapping['files'] != 123 or mapping['bytes'] != 1594016
            or len(mapping['helper_files']) != 3):
        raise ValueError('Historical mapping schema changed')
    descriptor = mapping['reviewed_source']
    if set(descriptor) != {'path','sha256'} or descriptor['sha256'] != FREEZE_SHA:
        raise ValueError('Historical freeze binding changed')
    freeze_path = _file(repository, helper.relative(descriptor['path']))
    if helper.digest(freeze_path) != FREEZE_SHA: raise ValueError('Historical source freeze changed')
    freeze = json.loads(freeze_path.read_bytes())
    if (len(freeze['files']) != 120 or freeze['runtime_files'] != 54 or freeze['sdk_pin_count'] != 20):
        raise ValueError('Historical source counts changed')
    expected = {helper.relative(name):helper.hash_value(value) for name,value in freeze['files'].items()}
    if set(expected) & set(mapping['helper_files']): raise ValueError('Helper overlaps historical source')
    expected.update({helper.relative(name):helper.hash_value(value) for name,value in mapping['helper_files'].items()})
    _names(expected, helper.relative)
    if set(mapping['mappings']) != set(expected):
        raise ValueError('Historical snapshot mapping must cover the complete frozen closure')
    entries = []
    for name, expected_hash in sorted(expected.items()):
        source = name
        if name in mapping['mappings']:
            item = mapping['mappings'][name]
            if set(item) != {'source','sha256'} or helper.hash_value(item['sha256']) != expected_hash:
                raise ValueError('Historical predecessor hash differs')
            source = helper.relative(item['source'])
        path = _file(repository, source)
        size = path.stat().st_size
        if not 0 <= size <= MAX_BYTES or helper.digest(path) != expected_hash:
            raise ValueError('Historical source checksum changed: ' + name)
        entries.append({'path':name,'source':source,'sha256':expected_hash,'bytes':size})
    if sum(row['bytes'] for row in entries) != mapping['bytes']:
        raise ValueError('Historical source byte count changed')
    guards = [(repository, RECONSTRUCT, RECONSTRUCT_SHA),
              (repository, descriptor['path'], FREEZE_SHA),
              (map_root, 'source-map.json', MAP_SHA)]
    plan = {'repository':repository,'helper':helper,'entries':entries,'guards':guards}
    _verify_inputs(plan)
    return plan


def _verify_inputs(plan):
    helper, repository = plan['helper'], _root(plan['repository'])
    for root, name, expected in plan['guards']:
        if helper.digest(_file(_root(root), name)) != expected:
            raise ValueError('Historical metadata input changed')
    for row in plan['entries']:
        source = _file(repository, row['source'])
        if source.stat().st_size != row['bytes'] or helper.digest(source) != row['sha256']:
            raise ValueError('Historical input changed during use: ' + row['path'])


def verify_view(view, plan):
    view = _root(view)
    actual, directories = [], set()
    for directory, subdirs, files in os.walk(view, followlinks=False):
        parent = Path(directory)
        _plain(parent, True)
        for name in subdirs:
            _plain(parent/name, True)
            directories.add((parent/name).relative_to(view).as_posix())
        for name in files:
            _plain(parent/name, False)
            actual.append((parent/name).relative_to(view).as_posix())
    _names(actual, plan['helper'].relative)
    if sorted(actual) != sorted(row['path'] for row in plan['entries']):
        raise ValueError('Historical view file set changed')
    expected_directories = {str(parent) for row in plan['entries']
        for parent in PurePosixPath(row['path']).parents if str(parent) != '.'}
    if directories != expected_directories:
        raise ValueError('Historical view directory set changed')
    for row in plan['entries']:
        path = _file(view, row['path'])
        if path.stat().st_size != row['bytes'] or plan['helper'].digest(path) != row['sha256']:
            raise ValueError('Historical view bytes changed: ' + row['path'])
    return {'files':len(actual),'bytes':sum(row['bytes'] for row in plan['entries']),
            'reviewed_source_sha256':FREEZE_SHA,'mapping_sha256':MAP_SHA,
            'source_sha256':{row['path']:row['sha256'] for row in plan['entries']}}


def _materialize(plan, destination):
    destination = Path(destination)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError('Fresh absolute historical view required')
    parent = _root(destination.parent)
    if destination.is_relative_to(plan['repository']):
        raise ValueError('Historical output must be outside the source repository')
    plan['helper'].relative(destination.name)
    if PureWindowsPath(destination.name).is_reserved(): raise ValueError('Reserved view directory')
    _verify_inputs(plan)
    destination.mkdir(exist_ok=False)
    _root(destination)
    for row in plan['entries']:
        source = _file(plan['repository'], row['source'])
        target = destination/row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        _root(target.parent)
        if target.exists() or target.is_symlink(): raise ValueError('Historical output file already exists')
        shutil.copyfile(source, target, follow_symlinks=False)
        if plan['helper'].digest(_file(destination, row['path'])) != row['sha256']:
            raise ValueError('Historical copy differs')
    _verify_inputs(plan)
    return verify_view(destination, plan)


def build_view(repository, destination):
    """Materialize one fresh retained view; preserve a partial output on failure."""
    return _materialize(load_plan(repository), destination)


@contextmanager
def historical_view(repository, temp_parent):
    """Own a fresh temporary view; never delete an unverified cleanup target."""
    plan = load_plan(repository)
    parent = _root(temp_parent)
    if parent.is_relative_to(plan['repository']):
        raise ValueError('Temporary parent must be outside the source repository')
    # mkdtemp is TemporaryDirectory's standard creation primitive. Explicit
    # cleanup lets a failed target check retain the directory instead of an
    # implicit finalizer attempting a recursive deletion of an unverified path.
    owned = Path(tempfile.mkdtemp(prefix='pr20-source-',dir=parent))
    owned_info = _plain(owned, True)
    owned_identity = (owned_info.st_dev, owned_info.st_ino)
    if not all(owned_identity):
        raise ValueError('Owned temporary identity unavailable; retained for inspection')
    try:
        owned = _root(owned)
        if owned.parent != parent or not owned.is_relative_to(parent):
            raise ValueError('Owned temporary directory escaped its parent')
        view = owned/'repository'
        _materialize(plan, view)
        try:
            yield view
        finally:
            _verify_inputs(plan)
            verify_view(view, plan)
    finally:
        checked = _root(owned)
        if checked != owned or checked.parent != parent or not checked.is_relative_to(parent):
            raise ValueError('Owned temporary cleanup target changed; retained for inspection')
        checked_info = _plain(checked, True)
        checked_identity = (checked_info.st_dev, checked_info.st_ino)
        if not all(checked_identity) or checked_identity != owned_identity:
            raise ValueError('Owned temporary identity changed; retained for inspection')
        shutil.rmtree(checked)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args(argv)
    receipt=build_view(args.repository,args.destination)
    print(json.dumps(receipt,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
