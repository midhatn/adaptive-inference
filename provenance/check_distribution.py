"""Compare built release contents with this checkout; no network or extraction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('src', 'docs', 'examples', 'integrations', 'plugins', 'provenance',
               'tests', 'third_party', 'upstream', '.github')
TOP_LEVEL = ('README.md', 'PLAN.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CITATION.cff',
             'REFERENCES.bib', 'requirements.lock', 'CHANGELOG.md', 'AGENTS.md', 'HANDOFF.md',
             'LICENSE', 'NOTICE', 'MANIFEST.in', 'pyproject.toml', '.gitattributes', '.gitignore')


def expected_files(root=ROOT):
    result = {name: root / name for name in TOP_LEVEL}
    for directory in DIRECTORIES:
        for path in (root / directory).rglob('*'):
            if (not path.is_file() or '__pycache__' in path.parts
                    or any(part.endswith('.egg-info') for part in path.parts)
                    or path.suffix in {'.pyc', '.pyo', '.log'}):
                continue
            if path.is_symlink():
                raise ValueError('Unexpected source symlink: ' + str(path))
            result[path.relative_to(root).as_posix()] = path
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check(sdist, wheel, root=ROOT):
    metadata = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    version = metadata['project']['version']
    prefix = f'adaptive_inference-{version}/'
    expected = expected_files(root)
    with tarfile.open(sdist, 'r:gz') as archive:
        members = {}
        for item in archive:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in item.name
                    or not item.name.startswith(prefix)):
                if item.isdir() and item.name == prefix.rstrip('/'):
                    continue
                raise ValueError('Unexpected distribution member: ' + item.name)
            name = item.name[len(prefix):]
            if item.isdir():
                continue
            if not item.isfile() or name in members:
                raise ValueError('Duplicate or non-file distribution member: ' + name)
            members[name] = item
        for name, source in expected.items():
            if name not in members:
                raise ValueError('Source distribution omits: ' + name)
            with archive.extractfile(members[name]) as stream:
                if digest(stream.read()) != digest(source.read_bytes()):
                    raise ValueError('Source distribution differs: ' + name)
    wheel_files = 0
    with zipfile.ZipFile(wheel) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate wheel members')
        for name, source in expected.items():
            if name.startswith('src/adaptive_inference/') and source.suffix == '.py':
                packaged = name.removeprefix('src/')
                if archive.read(packaged) != source.read_bytes():
                    raise ValueError('Wheel source differs: ' + packaged)
                wheel_files += 1
        license_prefix = f'adaptive_inference-{version}.dist-info/licenses/'
        for name in ('LICENSE', 'NOTICE', 'third_party/strata/LICENSE',
                     'third_party/finagle/LICENSE', 'third_party/finagle/NOTICE'):
            if archive.read(license_prefix + name) != (root / name).read_bytes():
                raise ValueError('Wheel license differs: ' + name)
    return {'passed': True, 'version': version, 'source_files_verified': len(expected),
            'wheel_modules_verified': wheel_files,
            'sdist_sha256': digest(Path(sdist).read_bytes()),
            'wheel_sha256': digest(Path(wheel).read_bytes()),
            'scope': 'built source payload and runtime modules/licenses match local files; no runtime/model test'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    parser.add_argument('--sdist', type=Path, default=ROOT / 'dist' / f'adaptive_inference-{version}.tar.gz')
    parser.add_argument('--wheel', type=Path, default=ROOT / 'dist' / f'adaptive_inference-{version}-py3-none-any.whl')
    args = parser.parse_args()
    print(json.dumps(check(args.sdist, args.wheel), indent=2))


if __name__ == '__main__':
    main()
