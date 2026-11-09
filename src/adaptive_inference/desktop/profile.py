# SPDX-License-Identifier: Apache-2.0
"""Explicit first installed Windows/IQ3_S/orders-report deployment profile."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from adaptive_inference.config import Config

SCHEMA = 'adaptive.desktop.windows-orders.v1'
STRICT_POLICY = 'strict-foreground.v3'
COOPERATIVE_POLICY = 'cooperative-owned-foreground.v1'


def fields(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('Explicit '+label+' fields required: '+', '.join(sorted(names)))
    return value


def pin(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('A lowercase SHA-256 pin is required')
    return value


def absolute(value):
    if type(value) is not str or not value or not Path(value).is_absolute():
        raise ValueError('Explicit absolute deployment paths are required')
    return Path(value)


@dataclass(frozen=True)
class WindowsProfile:
    host_python: Path
    host_python_sha256: str
    worker_python: Path
    worker_python_sha256: str
    hermes_source: Path
    hermes_site_packages: Path
    owner: dict
    gateway: Config
    foreground_policy: str
    compiler: object = None

    @classmethod
    def from_dict(cls, value):
        names = {'schema', 'host_python', 'worker_python', 'hermes',
                 'native_owner', 'gateway', 'foreground_policy'}
        if type(value) is dict and 'compiler' in value: names.add('compiler')
        fields(value, names, 'profile')
        if value['schema'] != SCHEMA:
            raise ValueError('Unsupported installed desktop profile')
        host = fields(value['host_python'], {'path', 'sha256'}, 'host interpreter')
        worker = fields(value['worker_python'], {'path', 'sha256'}, 'worker interpreter')
        hermes = fields(value['hermes'], {'source', 'site_packages'}, 'Hermes')
        owner = fields(value['native_owner'], {'package', 'manifest_sha256', 'provenance_sha256'}, 'native owner')
        native = {'package': str(absolute(owner['package'])),
                  'manifest_sha256': pin(owner['manifest_sha256']),
                  'provenance_sha256': pin(owner['provenance_sha256'])}
        gateway = Config.from_dict(value['gateway'])
        if (gateway.host != '127.0.0.1' or gateway.backend_kind != 'strata'
                or gateway.backend_url != 'http://127.0.0.1:18098/v1'
                or gateway.port == 18098 or gateway.api_key_env is not None
                or gateway.backend_key_env is not None):
            raise ValueError('This local profile requires the owned Strata endpoint on port 18098')
        policy = value['foreground_policy']
        if policy not in (STRICT_POLICY, COOPERATIVE_POLICY):
            raise ValueError('Select the explicit strict or cooperative foreground profile')
        compiler = None
        if 'compiler' in value:
            from adaptive_inference.desktop.compiler_profile import compiler_settings
            compiler = compiler_settings(value['compiler'])
        return cls(absolute(host['path']), pin(host['sha256']),
                   absolute(worker['path']), pin(worker['sha256']),
                   absolute(hermes['source']), absolute(hermes['site_packages']),
                   native, gateway, policy, compiler)

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
