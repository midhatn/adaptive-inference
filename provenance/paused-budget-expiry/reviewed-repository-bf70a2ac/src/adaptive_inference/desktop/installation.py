# SPDX-License-Identifier: Apache-2.0
"""Verify a regular installation before composing the dedicated desktop host.

Uses the wheel's existing RECORD through importlib.metadata, not a checkout
path or another module loader. Relative content pins travel to the separately
installed Hermes interpreter; installation roots need not be the same.
"""
from __future__ import annotations

import base64
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_identity(expected=None):
    import adaptive_inference

    distribution = metadata.distribution('adaptive-inference')
    direct = distribution.read_text('direct_url.json')
    if direct and json.loads(direct).get('dir_info', {}).get('editable') is True:
        raise RuntimeError('The desktop composition requires a regular installed wheel')
    root = Path(distribution.locate_file('adaptive_inference')).resolve(strict=True)
    if (Path(adaptive_inference.__file__).resolve(strict=True) != root/'__init__.py'
            or not distribution.files):
        raise RuntimeError('The imported package is not the recorded installation')
    pins = {}
    for item in distribution.files:
        name = item.as_posix()
        if not name.startswith('adaptive_inference/') or not name.endswith('.py'):
            continue
        relative = name.removeprefix('adaptive_inference/')
        path = Path(distribution.locate_file(item)).resolve(strict=True)
        if path != root/relative or not path.is_relative_to(root):
            raise RuntimeError('Installed package source is redirected')
        digest = sha(path)
        encoded = base64.urlsafe_b64encode(bytes.fromhex(digest)).rstrip(b'=').decode('ascii')
        if item.hash is None or item.hash.mode != 'sha256' or item.hash.value != encoded:
            raise RuntimeError('Installed package differs from wheel RECORD: '+relative)
        if relative in pins:
            raise RuntimeError('Duplicate installed source entry')
        pins[relative] = digest
    if not {'__init__.py', 'desktop/__init__.py', 'desktop/composition.py',
            'desktop/hermes/run_recovery.py'} <= pins.keys():
        raise RuntimeError('The installed desktop composition is incomplete')
    # Do not let an already imported alternate copy pass a disk-only check.
    for name, module in tuple(sys.modules.items()):
        if name == 'adaptive_inference' or name.startswith('adaptive_inference.'):
            path = getattr(module, '__file__', None)
            relative = name.removeprefix('adaptive_inference').lstrip('.').replace('.', '/')
            candidates = ('__init__.py',) if not relative else (relative+'.py', relative+'/__init__.py')
            recorded = {root/item for item in candidates if item in pins}
            if path is None or Path(path).resolve(strict=True) not in recorded:
                raise RuntimeError('Mixed canonical module identity: '+name)
    value = {'version': distribution.version, 'files': pins}
    if expected is not None and value != expected:
        raise RuntimeError('Host and worker installed package contents differ')
    return value


def verify_sdk(source):
    from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES

    root = Path(source).resolve(strict=True)
    for relative, expected in SDK_FILES.items():
        path = (root/relative).resolve(strict=True)
        if not path.is_relative_to(root) or sha(path) != expected:
            raise RuntimeError('Qualified Hermes source changed: '+relative)
    return root


def verify_sdk_imports(source):
    """The pinned SDK interfaces may not resolve to a preloaded second SDK."""
    from adaptive_inference.desktop.hermes.sdk_pins import SDK_FILES

    root = Path(source).resolve(strict=True)
    for relative in SDK_FILES:
        if not relative.endswith('.py'):
            continue
        name = relative[:-3].replace('/', '.')
        module = sys.modules.get(name)
        if module is not None and (getattr(module, '__file__', None) is None
                or Path(module.__file__).resolve(strict=True) != root/relative):
            raise RuntimeError('Mixed Hermes SDK import identity: '+name)


def verify_interpreter(path, expected, *, current=False):
    path = Path(path).resolve(strict=True)
    if sha(path) != expected:
        raise RuntimeError('Configured interpreter changed')
    if current and (Path(sys.executable).resolve() != path
                    or Path(sys._base_executable).resolve() != path
                    or sys.prefix != sys.base_prefix):
        raise RuntimeError('Use the configured full Python interpreter, not a venv redirector')
    return path
