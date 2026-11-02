# SPDX-License-Identifier: Apache-2.0
"""Create a launcher for an existing supported Windows desktop installation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from adaptive_inference.desktop.installation import (
    package_identity, sha, verify_interpreter, verify_sdk,
)
from adaptive_inference.desktop.profile import (
    COOPERATIVE_POLICY, SCHEMA, STRICT_POLICY, WindowsProfile,
)


def host_installation():
    if sys.platform != 'win32' or sys.version_info[:3] != (3, 11, 9):
        raise RuntimeError('Use the supported full Windows CPython 3.11.9 host')
    host = Path(sys.executable).resolve(strict=True)
    verify_interpreter(host, sha(host), current=True)
    package_identity()
    return host


def owner_identity(root):
    # Reuse the actual owner's checks for files, external dependencies, model
    # metadata and retained quality. Verification does not start its engine.
    from adaptive_inference.desktop.native_owner_adapter import OwnerPackage
    value = {'package': str(root), 'manifest_sha256': sha(root / 'MANIFEST.json'),
             'provenance_sha256': sha(root / 'PROVENANCE.json')}
    OwnerPackage(**value).verify()
    return value


def command_path(path):
    """Quote a literal batch-file path, including literal percent characters."""
    text = str(path)
    if any(character in text for character in ('"', '\r', '\n', '\0')):
        raise ValueError('Unsupported character in launcher interpreter path')
    return '"' + text.replace('%', '%%') + '"'


def create_setup(destination, *, worker_python, hermes_source,
                 hermes_site_packages, native_owner, gateway_port=18100,
                 foreground_policy=COOPERATIVE_POLICY, compiler_settings=None):
    destination = Path(destination).absolute()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Choose a new setup folder under an existing parent')
    destination = destination.parent.resolve(strict=True) / destination.name
    if destination.exists():
        raise ValueError('The setup folder already exists')
    host = host_installation()
    worker = Path(worker_python).resolve(strict=True)
    worker_pin = sha(worker)
    verify_interpreter(worker, worker_pin)
    sdk = verify_sdk(hermes_source)
    dependencies = Path(hermes_site_packages).resolve(strict=True)
    owner = Path(native_owner).resolve(strict=True)
    if not dependencies.is_dir() or not owner.is_dir():
        raise ValueError('Select existing Hermes dependencies and native owner folders')
    profile = {
        'schema': SCHEMA,
        'host_python': {'path': str(host), 'sha256': sha(host)},
        'worker_python': {'path': str(worker), 'sha256': worker_pin},
        'hermes': {'source': str(sdk), 'site_packages': str(dependencies)},
        'native_owner': owner_identity(owner),
        'gateway': {
            'listen': {'host': '127.0.0.1', 'port': gateway_port},
            'backend': {'kind': 'strata', 'base_url': 'http://127.0.0.1:18098/v1',
                        'revision': 'explicit-local-IQ3_S'},
            'scheduler': {'queue_timeout_s': 600},
            'limits': {'upstream_timeout_s': 600, 'upstream_read_timeout_s': 600},
            'default_class': 'normal',
        },
        'foreground_policy': foreground_policy,
    }
    if compiler_settings is not None:
        from adaptive_inference.desktop.compiler_profile import (
            compiler_settings as parse_compiler_settings, verify_settings,
        )
        value = json.loads(Path(compiler_settings).read_text(encoding='utf-8'))
        verify_settings(parse_compiler_settings(value))
        profile['compiler'] = value
    WindowsProfile.from_dict(profile)
    launch_source = Path(__file__).with_name('launch.py').read_bytes()
    command = ('@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n'
               + command_path(host) + ' -I -B "%~dp0launch.py"\nexit /b %errorlevel%\n')
    # All selected inputs and generated values are checked before any output.
    destination.mkdir(exist_ok=False)
    (destination / 'runs').mkdir()
    (destination / 'launch.py').write_bytes(launch_source)
    (destination / 'deployment.json').write_text(
        json.dumps(profile, indent=2) + '\n', encoding='utf-8')
    (destination / 'Start Adaptive Inference.cmd').write_text(
        command, encoding='utf-8', newline='\r\n')
    return {'profile': str(destination / 'deployment.json'),
            'launcher': str(destination / 'Start Adaptive Inference.cmd'),
            'runs': str(destination / 'runs'), 'inference_tested': False,
            'scope': 'Setup for existing installed components; no installation or model start'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--worker-python', type=Path, required=True)
    parser.add_argument('--hermes-source', type=Path, required=True)
    parser.add_argument('--hermes-site-packages', type=Path, required=True)
    parser.add_argument('--native-owner', type=Path, required=True)
    parser.add_argument('--gateway-port', type=int, default=18100)
    parser.add_argument('--foreground-policy', choices=(COOPERATIVE_POLICY, STRICT_POLICY),
                        default=COOPERATIVE_POLICY)
    parser.add_argument('--compiler-settings', type=Path,
                        help='Optional explicit compiler-settings JSON; verifies tool hashes without running them')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create_setup(**vars(args)), indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        print('Adaptive Inference setup: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
