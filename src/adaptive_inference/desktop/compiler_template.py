# SPDX-License-Identifier: Apache-2.0
"""Fixed C++17 task template; model text is source, never CMake or a command.

Uses documented CMake execute_process OUTPUT_FILE and file(SHA256) to check
the executed program's exact bytes without decoding or interpolating its output:
https://cmake.org/cmake/help/latest/command/execute_process.html
https://cmake.org/cmake/help/latest/command/file.html#hash
This is a process/resource boundary, not a filesystem or network sandbox.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re

from adaptive_inference.desktop.compiler_recipe import CompilerRecipe, Executable, _plain, _hash
from adaptive_inference.handoff import ToolRequirements
from adaptive_inference.task_spec import TaskSpec

RECIPE_ID = 'cpp17-stdout.v1'
TEST_NAME = 'program_stdout'
CMAKE = '''cmake_minimum_required(VERSION 3.29)
project(adaptive_cpp LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(program program.cpp)
enable_testing()
add_test(NAME program_stdout COMMAND "${CMAKE_COMMAND}"
  "-DPROGRAM=$<TARGET_FILE:program>"
  "-DRECORD_DIR=${CMAKE_CURRENT_BINARY_DIR}"
  "-DEXPECTED=${CMAKE_CURRENT_SOURCE_DIR}/expected.stdout"
  -P "${CMAKE_CURRENT_SOURCE_DIR}/check.cmake")
set_tests_properties(program_stdout PROPERTIES TIMEOUT 15)
'''
CHECK = '''execute_process(COMMAND "${PROGRAM}" RESULT_VARIABLE status
  OUTPUT_FILE "${RECORD_DIR}/program.stdout"
  ERROR_FILE "${RECORD_DIR}/program.stderr" TIMEOUT 10)
file(WRITE "${RECORD_DIR}/program.exit" "${status}")
if(NOT "${status}" STREQUAL "0")
  message(FATAL_ERROR "Program did not exit successfully")
endif()
file(SHA256 "${EXPECTED}" expected_hash)
file(SHA256 "${RECORD_DIR}/program.stdout" actual_hash)
if(NOT "${actual_hash}" STREQUAL "${expected_hash}")
  message(FATAL_ERROR "Program stdout did not match the task's exact expected bytes")
endif()
'''


@dataclass(frozen=True)
class CompilerSettings:
    """Host-prepared tools, environment and limits; never supplied by the model."""
    cmake: Executable
    ctest: Executable
    compiler: Executable
    ninja: Executable
    linker: Executable
    environment: tuple
    parallel_jobs: int = 2
    job_memory_mib: int = 2048
    max_seconds: float = 90
    requirements: ToolRequirements = ToolRequirements(2, 2, 0)


def _content(spec, args):
    if type(spec) is not TaskSpec or spec.compiler is None:
        raise ValueError('Explicit compiler task contract required')
    verdict = spec.validate_compiler_args(args)
    if not verdict.accepted:
        raise ValueError(verdict.feedback)
    return {'CMakeLists.txt': CMAKE.encode(), 'check.cmake': CHECK.encode(),
            'program.cpp': args['source'].encode('utf-8'),
            'expected.stdout': spec.compiler['expected_stdout'].encode('utf-8')}


def prepare_cpp_recipe(settings, *, spec, args, operation_id, root):
    """One fresh immutable source snapshot per already authorized operation.

    The host first verifies the native durable operation, task owner and budget.
    This helper does not create authority or increment an operation counter.
    """
    if type(settings) is not CompilerSettings or not re.fullmatch('[0-9a-f]{32}', operation_id):
        raise ValueError('Trusted settings and exact operation identity required')
    content = _content(spec, args)
    root = Path(root)
    _plain(root, directory=True)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Absolute ordinary operation root required')
    for tool in (settings.cmake, settings.ctest, settings.compiler, settings.ninja, settings.linker):
        if type(tool) is not Executable:
            raise ValueError('Pinned tool identity required')
        tool.verify()
    area = root / operation_id
    area.mkdir()  # No existing operation can be rewritten or reused here.
    source = area / 'source'
    source.mkdir()
    for name, raw in content.items():
        with (source / name).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    recipe = CompilerRecipe(settings.cmake, settings.ctest, settings.compiler, settings.ninja,
        source, tuple(sorted((name, hashlib.sha256(raw).hexdigest()) for name, raw in content.items())),
        area / 'run', 'program.exe', (TEST_NAME,), settings.parallel_jobs,
        settings.requirements, settings.job_memory_mib, settings.max_seconds,
        settings.environment, linker=settings.linker)
    recipe.verify(fresh=True)
    return recipe


def verify_cpp_artifacts(root, *, spec, args, operation_id, result):
    """Check exact prepared source, terminal receipt and successful artifacts.

    Native task/call authorization and actual process joins are the host's job.
    This read-only check is also usable before accepting a later saved result.
    """
    if not re.fullmatch('[0-9a-f]{32}', operation_id):
        raise ValueError('Exact operation identity required')
    content = _content(spec, args)
    root = Path(root)
    _plain(root, directory=True)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Absolute ordinary operation root required')
    area = root / operation_id
    source, run = area / 'source', area / 'run'
    for directory in (area, source, run):
        _plain(directory, directory=True)
    if {p.name for p in source.iterdir()} != set(content):
        raise ValueError('Prepared compiler source set changed')
    for name, raw in content.items():
        path = source / name
        _plain(path)
        if path.stat().st_size != len(raw) or _hash(path) != hashlib.sha256(raw).hexdigest():
            raise ValueError('Prepared compiler input changed')
    if (type(result) is not dict or result.get('operation_id') != operation_id
            or result.get('recipe_id') != RECIPE_ID or result.get('owned_processes_exited') is not True
            or result.get('status') not in {'passed', 'failed', 'interrupted', 'timed_out', 'cancelled'}):
        raise ValueError('Known joined compiler result required')
    receipt = run / 'receipt.json'
    _plain(receipt)
    if _hash(receipt) != result.get('receipt_sha256'):
        raise ValueError('Terminal recipe receipt changed')
    answer = {'source_sha256': hashlib.sha256(content['program.cpp']).hexdigest()}
    if result['status'] == 'passed':
        build = run / 'build'
        _plain(build, directory=True)
        for name, expected in (('program.exe', result.get('artifact_sha256')),
                               ('program.stdout', hashlib.sha256(content['expected.stdout']).hexdigest())):
            path = build / name
            _plain(path)
            if _hash(path) != expected:
                raise ValueError('Compiler artifact or exact stdout changed')
        _plain(build / 'program.exit')
        if (build / 'program.exit').read_bytes() != b'0':
            raise ValueError('Executed program did not exit zero')
        _plain(run / 'tests.xml')
        if _hash(run / 'tests.xml') != result.get('test_report_sha256'):
            raise ValueError('CTest report changed')
        answer['stdout_sha256'] = hashlib.sha256(content['expected.stdout']).hexdigest()
    return answer
