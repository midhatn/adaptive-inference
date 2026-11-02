# SPDX-License-Identifier: Apache-2.0
"""Explicit host compiler tools; no autodetection, installation, or model commands."""
from pathlib import Path

from adaptive_inference.desktop.compiler_recipe import Executable
from adaptive_inference.desktop.compiler_template import CompilerSettings


def compiler_settings(value):
    from adaptive_inference.desktop.profile import fields, absolute, pin
    names = ('cmake', 'ctest', 'compiler', 'ninja', 'linker')
    fields(value, {'schema', 'environment', *names}, 'compiler settings')
    if value['schema'] != 'adaptive.compiler-settings.v1':
        raise ValueError('Unsupported compiler settings')
    environment = value['environment']
    if (type(environment) is not dict or not environment or len(environment) > 128
            or any(type(k) is not str or not k or '=' in k or '\x00' in k
                   or type(v) is not str or '\x00' in v for k, v in environment.items())
            or len({key.upper() for key in environment}) != len(environment)):
        raise ValueError('Explicit unambiguous compiler environment required')
    tools = []
    for name in names:
        tool = fields(value[name], {'path', 'sha256'}, 'compiler executable')
        tools.append(Executable(absolute(tool['path']), pin(tool['sha256'])))
    if tools[2].path.name.lower() != 'clang-cl.exe' or tools[4].path.name.lower() != 'lld-link.exe':
        raise ValueError('This fixed recipe requires the explicit LLVM compiler and linker')
    return CompilerSettings(*tools, environment=tuple(sorted(environment.items())))


def verify_settings(settings):
    if type(settings) is not CompilerSettings:
        raise ValueError('Compiler task requires explicit deployment tools')
    for tool in (settings.cmake, settings.ctest, settings.compiler, settings.ninja, settings.linker):
        tool.verify()
