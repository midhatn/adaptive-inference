# SPDX-License-Identifier: Apache-2.0
"""One trusted CMake/Ninja/CTest recipe under an existing tool grant.

No agent command, shell, retry, installation or model operation is accepted here.
The caller owns durable task intent and supplies its ORIGINAL execution deadline.
Source/API reuse: owned_job.py, gui_launch.WindowsLaunchAPI, and the retained
windows_handoff protected_video runner. Windows support has the same pinned full
CPython 3.11.9 requirement as WindowsLaunchAPI.

Primary contracts (accessed 2026-11-02; no external implementation copied):
https://cmake.org/cmake/help/latest/manual/cmake.1.html
https://cmake.org/cmake/help/latest/manual/ctest.1.html
https://cmake.org/cmake/help/latest/policy/CMP0141.html
https://cmake.org/cmake/help/latest/variable/CMAKE_MSVC_DEBUG_INFORMATION_FORMAT.html
https://cmake.org/cmake/help/latest/variable/CMAKE_TRY_COMPILE_CONFIGURATION.html
https://cmake.org/cmake/help/latest/variable/CMAKE_LINKER_TYPE.html
https://clang.llvm.org/docs/UsersManual.html#clang-cl
https://lld.llvm.org/windows_support.html
https://learn.microsoft.com/en-us/cpp/build/reference/fs-force-synchronous-pdb-writes
https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information

The dedicated job bounds aggregate committed memory, NOT physical RAM or CPU
usage. CMake/CTest job counts bound their requested parallelism, not arbitrary
threads created by trusted project code. Job emptiness covers descendants even
when a short-lived descendant was never individually sampled.
"""
import asyncio
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _relative(value):
    return (type(value) is str and value and '\\' not in value and ':' not in value
            and not PurePosixPath(value).is_absolute()
            and all(part not in ('', '.', '..') for part in value.split('/')))


def _plain(path, *, directory=False):
    info = path.lstat()
    if (getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('Recipe paths must be ordinary files/directories, without links')


@dataclass(frozen=True)
class Executable:
    path: Path
    sha256: str

    def verify(self):
        if type(self.path) is not Path and not isinstance(self.path, Path):
            raise ValueError('Explicit executable Path required')
        if not self.path.is_absolute() or not _sha(self.sha256):
            raise ValueError('Explicit absolute executable and SHA256 required')
        _plain(self.path)
        if _hash(self.path) != self.sha256:
            raise ValueError('Prepared recipe executable changed')


@dataclass(frozen=True)
class CompilerRecipe:
    cmake: Executable
    ctest: Executable
    compiler: Executable
    ninja: Executable
    source: Path
    source_files: tuple
    run: Path
    artifact: str
    expected_tests: tuple
    parallel_jobs: int
    requirements: object
    job_memory_mib: int
    max_seconds: float
    environment: tuple
    linker: Executable | None = None

    @property
    def build(self):
        return self.run / 'build'

    def verify(self, *, fresh=False):
        from adaptive_inference.handoff import ToolRequirements
        if (not isinstance(self.source, Path) or not isinstance(self.run, Path)
                or not self.source.is_absolute() or not self.run.is_absolute()
                or type(self.parallel_jobs) is not int or not 1 <= self.parallel_jobs <= 16
                or type(self.job_memory_mib) is not int or not 64 <= self.job_memory_mib <= 65536
                or type(self.max_seconds) not in (int, float) or not math.isfinite(self.max_seconds)
                or not 0 < self.max_seconds <= 900 or type(self.requirements) is not ToolRequirements
                or not _relative(self.artifact) or type(self.expected_tests) is not tuple
                or not 1 <= len(self.expected_tests) <= 64
                or any(type(v) is not str or not v or len(v) > 256 for v in self.expected_tests)
                or len(set(self.expected_tests)) != len(self.expected_tests)):
            raise ValueError('Bounded trusted compiler recipe required')
        _plain(self.source, directory=True)
        _plain(self.run.parent, directory=True)
        source, run = self.source.resolve(), self.run.resolve()
        if source == run or source in run.parents or run in source.parents:
            raise ValueError('Separate source and new output directory required')
        if fresh and self.run.exists():
            raise ValueError('Recipe output already exists; no replay or overwrite')
        if (type(self.environment) is not tuple or any(type(row) is not tuple or len(row) != 2
                or any(type(v) is not str or '\x00' in v for v in row)
                or not row[0] or '=' in row[0] for row in self.environment)
                or len({k.upper() for k, _ in self.environment}) != len(self.environment)):
            raise ValueError('Explicit unambiguous environment required')
        for executable in (self.cmake, self.ctest, self.compiler, self.ninja):
            if type(executable) is not Executable:
                raise ValueError('Pinned recipe executables required')
            executable.verify()
        if self.linker is not None:
            if (type(self.linker) is not Executable or self.compiler.path.name.lower() != 'clang-cl.exe'
                    or self.linker.path.name.lower() != 'lld-link.exe'):
                raise ValueError('Explicit LLVM linker requires the trusted clang-cl/lld-link pair')
            self.linker.verify()
        if (type(self.source_files) is not tuple or not 1 <= len(self.source_files) <= 256
                or any(type(row) is not tuple or len(row) != 2
                       or not _relative(row[0]) or not _sha(row[1]) for row in self.source_files)
                or len(dict(self.source_files)) != len(self.source_files)):
            raise ValueError('Complete bounded source manifest required')
        found, total, directories = {}, 0, [self.source]
        while directories:
            for path in directories.pop().iterdir():
                if path.is_dir():
                    _plain(path, directory=True)
                    directories.append(path)
                else:
                    _plain(path)
                    total += path.stat().st_size
                    if len(found) >= 256 or total > 4 * 1024 * 1024:
                        raise ValueError('Recipe source exceeds its bound')
                    found[path.relative_to(self.source).as_posix()] = _hash(path)
        if found != dict(self.source_files) or 'CMakeLists.txt' not in found:
            raise ValueError('Prepared compiler source changed')

    def commands(self):
        """Host-only fixed argv; no model-supplied flags or shell expansion."""
        # CMake cache paths use forward slashes; a native backslash can become
        # an invalid escape when CMake writes its compiler-description script.
        linker = ([] if self.linker is None else [
            '-DCMAKE_LINKER_TYPE=LLD', '-DCMAKE_LINKER:FILEPATH=' + self.linker.path.as_posix(),
            '-DCMAKE_LINKER_LLD:FILEPATH=' + self.linker.path.as_posix()])
        return (
            ('configure', [str(self.cmake.path), '-S', str(self.source), '-B', str(self.build),
                '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                # Compiler checks otherwise may use Debug /Zi /FS and leave an
                # owned PDB server alive. Embedded (/Z7) also reaches try_compile;
                # keep strict descendant exit and the original recipe deadline.
                '-DCMAKE_POLICY_DEFAULT_CMP0141=NEW',
                '-DCMAKE_MSVC_DEBUG_INFORMATION_FORMAT=Embedded',
                '-DCMAKE_TRY_COMPILE_CONFIGURATION=Release',
                '-DCMAKE_CXX_COMPILER=' + self.compiler.path.as_posix(),
                '-DCMAKE_MAKE_PROGRAM=' + self.ninja.path.as_posix()] + linker),
            ('build', [str(self.cmake.path), '--build', str(self.build), '--parallel', str(self.parallel_jobs)]),
            ('test', [str(self.ctest.path), '--test-dir', str(self.build), '--parallel', str(self.parallel_jobs),
                '--output-on-failure', '--no-tests=error', '--output-junit', str(self.run / 'tests.xml')]),
        )


class RecipeInterrupted(RuntimeError):
    pass


class RecipeCleanupError(RuntimeError):
    pass


class _Job:
    """Only this new recipe's retained job; never the containing desktop job."""
    def __init__(self, memory_mib):
        from adaptive_inference.desktop.gui_launch import WindowsLaunchAPI
        self.api = WindowsLaunchAPI()
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
        self.k.CreateJobObjectW.restype = W.HANDLE
        self.k.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        self.k.SetInformationJobObject.restype = W.BOOL
        self.k.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
        self.k.AssignProcessToJobObject.restype = W.BOOL
        self.k.QueryInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p]
        self.k.QueryInformationJobObject.restype = W.BOOL
        self.k.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
        self.k.TerminateJobObject.restype = W.BOOL
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.CloseHandle.restype = W.BOOL
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        # Same documented layouts/kill-on-close flag as desktop.owned_job.
        class Basic(C.Structure):
            _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                ('flags', W.DWORD), ('min_ws', C.c_size_t), ('max_ws', C.c_size_t),
                ('active', W.DWORD), ('affinity', C.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class Io(C.Structure):
            _fields_ = [(name, C.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                'read_bytes', 'write_bytes', 'other_bytes')]
        class Limits(C.Structure):
            _fields_ = [('basic', Basic), ('io', Io), ('process_mem', C.c_size_t),
                ('job_mem', C.c_size_t), ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]
        limits = Limits()
        limits.basic.flags = 0x2000 | 0x200  # kill-on-close + aggregate committed-memory limit; no breakaway
        limits.job_mem = memory_mib * 1024 * 1024
        if not self.k.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            error = C.get_last_error()
            self.close()
            raise C.WinError(error)

    def assign(self, child):
        handle = self.api.handle(child)
        if not self.k.AssignProcessToJobObject(self.handle, handle):
            raise C.WinError(C.get_last_error())
        if not self.api.in_job(handle, int(self.handle)):
            raise RuntimeError('Recipe child did not enter its retained job')
        return self.api.identity(handle)

    def accounting(self):
        class Accounting(C.Structure):
            _fields_ = [(name, C.c_longlong) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
                (name, W.DWORD) for name in ('page_faults', 'total', 'active', 'limit_terminated')]
        value = Accounting()
        if not self.k.QueryInformationJobObject(self.handle, 1, C.byref(value), C.sizeof(value), None):
            raise C.WinError(C.get_last_error())
        return {name: int(getattr(value, name)) for name in ('total', 'active', 'limit_terminated')}

    def terminate(self):
        if not self.k.TerminateJobObject(self.handle, 125):
            raise C.WinError(C.get_last_error())

    def close(self):
        if self.handle:
            if not self.k.CloseHandle(self.handle):
                raise C.WinError(C.get_last_error())
            self.handle = None


class _ProcessOwner:
    """Gated helper permits argv only AFTER exact child-to-job assignment."""
    def __init__(self, memory_mib, environment, *, clock=time.perf_counter):
        self.job = _Job(memory_mib)
        self.environment, self.clock = environment, clock
        self.children, self.records = [], []
        self.terminated = False
        self.closed = False
        self.final_accounting = None

    async def run(self, command, *, cwd, log, deadline, interruption):
        if self.closed or self.job.accounting()['active']:
            raise RuntimeError('Recipe job not empty before next stage')
        self.check(deadline, interruption)
        payload = json.dumps({'argv': command, 'cwd': str(cwd)}, ensure_ascii=True).encode('utf-8') + b'\n'
        if len(payload) > 16384:
            raise ValueError('Recipe command exceeds fixed bootstrap bound')
        with log.open('xb') as output:
            child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child'],
                stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, close_fds=True,
                creationflags=0x08000000, env=self.environment)
            record = {'bootstrap_pid': child.pid, 'assigned': False, 'command_delivered': False,
                'joined': False, 'exit_code': None, 'forced_cleanup': False}
            self.records.append(record)
            retained = {'process': child, 'communication': None, 'record': record}
            self.children.append(retained)
            identity = self.job.assign(child)
            record.update(assigned=True, creation_time_100ns=identity[1])
            self.check(deadline, interruption)
            retained['communication'] = asyncio.create_task(asyncio.to_thread(child.communicate, payload))
            record['command_delivered'] = True
            while child.poll() is None or self.job.accounting()['active']:
                self.check(deadline, interruption)
                await asyncio.sleep(.02)
            await asyncio.shield(retained['communication'])
            record.update(joined=True, exit_code=child.returncode)
            return child.returncode

    def check(self, deadline, interruption):
        if interruption.is_set():
            raise RecipeInterrupted('Foreground or host interruption requested')
        if self.clock() >= deadline:
            raise TimeoutError('Original recipe/task deadline expired')

    async def close(self):
        if self.closed:
            return self.final_accounting
        # Cleanup has its own short wait allowance, never permission for more work.
        deadline = self.clock() + 10
        for retained in self.children:
            retained['record']['forced_cleanup'] = retained['process'].poll() is None
        if self.job.accounting()['active']:
            self.job.terminate()
            self.terminated = True
        for retained in self.children:
            child, record = retained['process'], retained['record']
            if child.poll() is None:
                if not record['assigned']:
                    child.kill()  # only our retained, still-gated bootstrap
            if retained['communication'] is None:
                retained['communication'] = asyncio.create_task(asyncio.to_thread(child.communicate, b''))
            while not retained['communication'].done():
                if self.clock() >= deadline:
                    raise RecipeCleanupError('Retained recipe child wait is unconfirmed')
                await asyncio.sleep(.02)
            retained['communication'].result()
            if child.returncode is None:
                raise RecipeCleanupError('Recipe child has no retained exit')
            record.update(joined=True, exit_code=child.returncode)
        while self.job.accounting()['active']:
            if self.clock() >= deadline:
                raise RecipeCleanupError('Recipe descendant exit is unconfirmed')
            await asyncio.sleep(.02)
        self.final_accounting = self.job.accounting()
        for retained in self.children:
            self.job.api.close_process_handle(retained['process'])
        self.job.close()
        self.closed = True
        return self.final_accounting


def _outputs(recipe):
    artifact = recipe.build / recipe.artifact
    if recipe.build.resolve() not in artifact.resolve().parents:
        raise ValueError('Compiler artifact escaped its build directory')
    _plain(artifact)
    if not 0 < artifact.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('Compiler artifact is absent, empty or exceeds its bound')
    report = recipe.run / 'tests.xml'
    _plain(report)
    if report.stat().st_size > 1024 * 1024:
        raise ValueError('CTest report exceeds its bound')
    root = ET.fromstring(report.read_bytes())
    cases = list(root.iter('testcase'))
    if (len(cases) != len(recipe.expected_tests)
            or {case.get('name') for case in cases} != set(recipe.expected_tests)
            or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped'))):
        raise ValueError('CTest did not pass the exact declared tests')
    return {'artifact_sha256': _hash(artifact), 'artifact_bytes': artifact.stat().st_size,
        'test_report_sha256': _hash(report), 'tests_passed': list(recipe.expected_tests)}


async def run_recipe(controller, recipe, *, task_deadline, clock=time.perf_counter,
                     _owner_factory=_ProcessOwner):
    """Return truthful terminal evidence; uncertainty faults the existing grant.

    The future agent bridge must persist intent before this call and the returned
    receipt before another generation. This function never renews the task budget.
    Cancellation propagates only after its bounded cleanup attempt and receipt.
    """
    if type(recipe) is not CompilerRecipe:
        raise TypeError('Prepared CompilerRecipe required')
    recipe.verify(fresh=True)
    started = clock()
    if type(task_deadline) not in (int, float) or not math.isfinite(task_deadline) or task_deadline <= started:
        raise ValueError('Live original execution deadline required')
    deadline = min(task_deadline, started + recipe.max_seconds)
    recipe.run.mkdir()  # exclusive fresh destination; never replay a consumed run
    receipt = {'schema': 'compiler-recipe.v1', 'status': 'failed', 'passed': False,
        'task_deadline': task_deadline, 'deadline': deadline, 'started': started,
        'parallel_jobs': recipe.parallel_jobs, 'job_commit_limit_mib': recipe.job_memory_mib,
        'stages': [], 'children': [], 'owned_processes_exited': False,
        'scope': 'trusted CMake/Ninja/CTest recipe; no agent/model or reboot qualification'}
    grant = owner = None
    cancelled = False
    cleanup_error = None
    try:
        grant = await controller.acquire_tool(recipe.requirements, timeout_s=max(.01, deadline - clock()))
        receipt['grant_token'] = grant.token
        env = dict(recipe.environment)
        env.update(CMAKE_BUILD_PARALLEL_LEVEL=str(recipe.parallel_jobs), CTEST_PARALLEL_LEVEL=str(recipe.parallel_jobs))
        owner = _owner_factory(recipe.job_memory_mib, env, clock=clock)
        for stage, command in recipe.commands():
            recipe.verify()
            owner.check(deadline, grant.interruption)
            row = {'stage': stage, 'argv': command, 'started': clock()}
            receipt['stages'].append(row)
            code = await owner.run(command, cwd=recipe.run, log=recipe.run / (stage + '.log'),
                deadline=deadline, interruption=grant.interruption)
            row.update(exit_code=code, finished=clock())
            if code != 0:
                receipt.update(status='failed', failure_stage=stage)
                break
        else:
            owner.check(deadline, grant.interruption)
            recipe.verify()
            receipt.update(_outputs(recipe))
            receipt.update(status='passed', passed=True)
    except asyncio.CancelledError:
        cancelled = True
        receipt['status'] = 'cancelled'
    except RecipeInterrupted as error:
        receipt.update(status='interrupted', error=str(error))
    except TimeoutError as error:
        receipt.update(status='timed_out', error=str(error))
    except Exception as error:
        receipt.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
    finally:
        if owner is not None:
            cleanup = asyncio.create_task(owner.close())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            try:
                receipt['job_accounting'] = cleanup.result()
                receipt['job_terminated'] = owner.terminated
                receipt['owned_processes_exited'] = True
            except Exception as error:
                cleanup_error = error
                receipt['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
            receipt['children'] = owner.records
        else:
            receipt['owned_processes_exited'] = True  # no child creation was attempted
        if grant is not None:
            try:
                controller.complete_tool(grant, owned_processes_exited=receipt['owned_processes_exited'])
            except Exception as error:
                cleanup_error = error
                receipt['release_error'] = {'type': type(error).__name__, 'message': str(error)}
        if cancelled or cleanup_error:
            receipt.update(passed=False, status='cleanup_unconfirmed' if cleanup_error else 'cancelled')
        receipt['finished'] = clock()
        with (recipe.run / 'receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(receipt, stream, indent=2, ensure_ascii=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    if cleanup_error:
        error = RecipeCleanupError('Recipe ownership remains unconfirmed; inference must stay closed')
        error.owner, error.receipt = owner, receipt  # retain cleanup obligations for the host
        raise error from cleanup_error
    if cancelled:
        raise asyncio.CancelledError
    return receipt


def _child_main():
    # Stdlib-only bootstrap: import of this file and waiting for stdin cannot
    # create a compiler. The retained parent writes ONLY after job assignment.
    raw = sys.stdin.buffer.readline(16385)
    if not raw or len(raw) > 16384 or not raw.endswith(b'\n'):
        return 126
    request = json.loads(raw)
    if (type(request) is not dict or set(request) != {'argv', 'cwd'}
            or type(request['argv']) is not list or not request['argv']
            or any(type(arg) is not str or '\x00' in arg for arg in request['argv'])
            or not Path(request['argv'][0]).is_absolute() or not Path(request['cwd']).is_absolute()):
        return 126
    child = subprocess.Popen(request['argv'], cwd=request['cwd'], stdin=subprocess.DEVNULL,
        close_fds=True, shell=False)
    return child.wait()


if __name__ == '__main__':
    if sys.argv[1:] != ['--child']:
        raise SystemExit('Only the owned recipe bootstrap is supported')
    raise SystemExit(_child_main())
