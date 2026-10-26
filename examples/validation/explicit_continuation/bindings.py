# SPDX-License-Identifier: Apache-2.0
"""Explicit inputs for this one private qualification; no evidence discovery."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
OUTER_SECONDS = 2700
INPUTS = frozenset(('profile','wheel','source_freeze','source_review','package_review',
    'deployment_gate','host_install','worker_install','installed_identity','clock_probe','installed_sdk'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def read(path):
    def bad(value): raise ValueError('Nonfinite JSON value')
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=bad)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def descriptor(value):
    if (type(value) is not dict or set(value) != {'path','sha256'}
            or type(value['path']) is not str or type(value['sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None):
        raise ValueError('Explicit reviewed file binding required')
    path = Path(value['path'])
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file():
        raise ValueError('Absolute regular input file required')
    if sha(path) != value['sha256']: raise ValueError('Bound input bytes differ: '+path.name)
    return path


def load(path, *, installed=False):
    path = Path(path).resolve(strict=True)
    value = read(path)
    if (set(value) != {'schema','enabled','case','harness_manifest','inputs'}
            or value['schema'] != 'private.continuation.installed-inputs.v1'
            or value['enabled'] is not True or set(value['inputs']) != INPUTS):
        raise ValueError('Qualification bindings are disabled or incomplete')
    manifest = descriptor(value['harness_manifest'])
    if manifest != HERE/'source-manifest.json': raise ValueError('Wrong harness manifest')
    closure = read(manifest)
    if closure['schema'] != 'private.continuation.harness-source.v1': raise ValueError('Wrong closure schema')
    for name, pin in closure['files'].items():
        item = (HERE/name).resolve(strict=True)
        if not item.is_relative_to(HERE) or sha(item) != pin: raise ValueError('Harness source differs')
    inputs = {name:descriptor(pin) for name,pin in value['inputs'].items()}
    case = Path(value['case'])
    if not case.is_absolute() or '..' in case.parts or case.is_relative_to(HERE):
        raise ValueError('Explicit case outside source required')
    case.parent.resolve(strict=True)
    expected = read(inputs['installed_identity'])
    if set(expected) != {'version','files'} or not expected['files']: raise ValueError('Missing installed identity')
    gate = read(inputs['deployment_gate'])
    if gate.get('passed') is not True or gate.get('wheel_sha256') != value['inputs']['wheel']['sha256']:
        raise ValueError('Reviewed deployment gate is missing')
    profile = read(inputs['profile'])
    descriptor(profile['host_python']); descriptor(profile['worker_python'])
    if installed:
        if Path(sys.executable).resolve() != Path(profile['host_python']['path']).resolve():
            raise ValueError('Run with the explicitly bound host interpreter')
        from adaptive_inference.desktop.installation import package_identity
        if package_identity() != expected: raise ValueError('Installed modules differ from reviewed identity')
    return {'path':path,'value':value,'case':case,'inputs':inputs,'profile':profile,
            'identity':expected,'manifest_sha256':sha(manifest),'bindings_sha256':sha(path)}


def baseline(name):
    """Load the exact public predecessor or the two retained pure QPC helpers."""
    lineage = read(HERE/'source-lineage.json')
    if name == 'installed_desktop/qualify.py':
        root = HERE.parents[2]/'provenance/explicit-continuation/qualification-predecessor'
        for relative, pin in lineage['qualification_predecessor'].items():
            item = (root/relative).resolve(strict=True)
            if not item.is_relative_to(root) or sha(item) != pin:
                raise ValueError('Public qualification predecessor changed')
        path = root/'qualify.py'
    elif name == 'audit_expiry.py':
        path = HERE/'qpc_helpers.py'
        if sha(path) != lineage['qpc_helpers_sha256']:
            raise ValueError('Retained QPC helper changed')
    else:
        raise ValueError('Unknown retained helper')
    spec = importlib.util.spec_from_file_location('continue_baseline_'+name.replace('/','_').replace('.','_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
