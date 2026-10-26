"""Compare built release contents with this checkout; no network or extraction."""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('src', 'docs', 'examples', 'integrations', 'plugins', 'provenance',
               'tests', 'third_party', 'upstream', '.github')
TOP_LEVEL = ('README.md', 'PLAN.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CITATION.cff',
             'REFERENCES.bib', 'requirements.lock', 'CHANGELOG.md', 'AGENTS.md',
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


def wheel_identity(archive, version, expected):
    """Reuse the release verifier's complete SHA-256 RECORD and module checks.

    This checks this project's pure-Python wheel, not arbitrary wheel layouts.
    Format reference: https://packaging.python.org/specifications/binary-distribution-format/
    """
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate wheel members')
    for name in names:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name
                or ':' in name or path.as_posix() != name):
            raise ValueError('Unsafe or noncanonical wheel member: ' + name)
    runtime = {name.removeprefix('src/'): digest(source.read_bytes())
               for name, source in expected.items()
               if name.startswith('src/adaptive_inference/') and source.suffix == '.py'}
    actual = {name: digest(archive.read(name)) for name in names if name.endswith('.py')}
    if not runtime or actual != runtime:
        raise ValueError('Exact wheel Python module set or contents differ')
    prefix = f'adaptive_inference-{version}.dist-info/'
    record_name = prefix + 'RECORD'
    metadata = {prefix + name for name in
                ('METADATA', 'WHEEL', 'entry_points.txt', 'top_level.txt', 'RECORD')}
    licenses = {prefix + 'licenses/' + name for name in
                ('LICENSE', 'NOTICE', 'third_party/strata/LICENSE',
                 'third_party/finagle/LICENSE', 'third_party/finagle/NOTICE')}
    if set(names) != set(runtime) | metadata | licenses:
        raise ValueError('Unexpected or missing wheel member')
    headers = BytesParser().parsebytes(archive.read(prefix + 'METADATA'), headersonly=True)
    project_names = headers.get_all('Name', [])
    if (len(project_names) != 1
            or re.sub(r'[-_.]+', '-', project_names[0]).lower() != 'adaptive-inference'
            or headers.get_all('Version', []) != [version]):
        raise ValueError('Wheel METADATA project name or version differs')
    rows = list(csv.reader(io.StringIO(archive.read(record_name).decode('utf-8')), strict=True))
    if (any(len(row) != 3 for row in rows) or len(rows) != len(names)
            or {row[0] for row in rows} != set(names)):
        raise ValueError('Wheel RECORD is not a unique complete member list')
    for name, recorded_hash, size in rows:
        if name == record_name:
            if recorded_hash or size:
                raise ValueError('Wheel RECORD self-entry must have no hash or size')
            continue
        raw = archive.read(name)
        encoded = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b'=').decode('ascii')
        if recorded_hash != 'sha256=' + encoded or size != str(len(raw)):
            raise ValueError('Wheel RECORD hash or size differs: ' + name)
    return {'version': version, 'files': {
        name.removeprefix('adaptive_inference/'): value for name, value in actual.items()}}


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
        identity = wheel_identity(archive, version, expected)
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
            'installed_identity': identity,
            'sdist_sha256': digest(Path(sdist).read_bytes()),
            'wheel_sha256': digest(Path(wheel).read_bytes()),
            'scope': 'built source payload and runtime modules/licenses match local files; no runtime/model test'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    parser.add_argument('--sdist', type=Path, default=ROOT / 'dist' / f'adaptive_inference-{version}.tar.gz')
    parser.add_argument('--wheel', type=Path, default=ROOT / 'dist' / f'adaptive_inference-{version}-py3-none-any.whl')
    parser.add_argument('--output', type=Path,
                        help='Fresh directory for check result and wheel-derived installed identity')
    args = parser.parse_args(argv)
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=False)
    try:
        result = check(args.sdist, args.wheel)
    except Exception as exc:
        if args.output is not None:
            (args.output / 'result.json').write_text(json.dumps({
                'passed': False, 'error': type(exc).__name__, 'message': str(exc),
                'scope': 'archive validation failed; no installed identity emitted'}, indent=2) + '\n', encoding='utf-8')
        raise
    if args.output is not None:
        (args.output / 'installed-identity.json').write_text(
            json.dumps(result['installed_identity'], indent=2) + '\n', encoding='utf-8')
        (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
