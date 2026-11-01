# SPDX-License-Identifier: Apache-2.0
"""Retain one ordinary installed desktop child; never claim M3 acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from adaptive_inference.desktop.profile import WindowsProfile
from adaptive_inference.task_spec import TaskSpec

OUTER_SECONDS = 2700


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def prepare(profile_path, run, task_spec, task_inputs):
    """Reuse the installed profile/TaskSpec validators without staging or launch."""
    profile_path = Path(profile_path).resolve(strict=True)
    profile = WindowsProfile.load(profile_path)
    run = Path(run)
    if not run.is_absolute() or not run.parent.is_dir() or run.exists():
        raise ValueError('Fresh absolute run under an existing parent required')
    run = run.parent.resolve(strict=True) / run.name
    task_spec = Path(task_spec).resolve(strict=True)
    task_inputs = Path(task_inputs).resolve(strict=True)
    spec = TaskSpec.from_bytes(task_spec.read_bytes())
    spec.verify_inputs(task_inputs)
    if spec.data['budget']['execution_seconds'] != 900:
        raise ValueError('The existing 900-second task contract is required')
    if sha(profile.host_python) != profile.host_python_sha256:
        raise ValueError('Host interpreter differs from deployment profile')
    command = [str(profile.host_python), '-I', '-B', '-m', 'adaptive_inference',
               'desktop', '--profile', str(profile_path), '--run', str(run),
               '--task-spec', str(task_spec), '--task-inputs', str(task_inputs)]
    identity = {'profile': str(profile_path), 'profile_sha256': sha(profile_path),
                'task_spec': str(task_spec), 'task_spec_file_sha256': sha(task_spec),
                'task_spec_sha256': spec.sha256, 'task_inputs': str(task_inputs),
                'input_sha256': {row['name']: sha(task_inputs / row['name'])
                                 for row in spec.data['inputs']},
                'task_budget': spec.data['budget'], 'foreground_policy': profile.foreground_policy,
                'host_python_sha256': profile.host_python_sha256}
    return command, run, identity


def supervise(command, run, identity, *, timeout_s=OUTER_SECONDS):
    """The CLI fixes 2700 s; shorter injection is only for inert component checks.

    Adapted from task_handover/run_handover.py. Timeout is a failed attempt,
    followed by exact-child termination and an actual bounded final wait.
    """
    run = Path(run)
    receipt = Path(str(run) + '.supervisor.private.json')
    started_path = Path(str(run) + '.started.private.json')
    log = Path(str(run) + '.console.private.log')
    if any(path.exists() for path in (run, receipt, started_path, log)):
        raise ValueError('Fresh run and parent sidecars required')
    source = Path(__file__).resolve()
    before = sha(source)
    started = time.monotonic()
    child = None
    code = None
    joined = timed_out = emergency = False
    errors = []
    with log.open('xb') as stream:
        try:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, cwd=run.parent,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            save(started_path, {'pid': child.pid, 'command': command, 'run': str(run),
                'started_wall_time': time.time(), 'outer_deadline_s': timeout_s,
                'inputs': identity, 'source_sha256': before})
            code = child.wait(timeout=timeout_s)
            joined = True
        except BaseException as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            errors.append({'stage': 'launch_or_wait', 'type': type(error).__name__, 'message': str(error)})
            if child is not None:
                emergency = True
                try:
                    child.kill()
                except BaseException as failure:
                    errors.append({'stage': 'exact_child_kill', 'type': type(failure).__name__, 'message': str(failure)})
                try:
                    code = child.wait(timeout=10)
                    joined = True
                except BaseException as failure:
                    errors.append({'stage': 'final_wait', 'type': type(failure).__name__, 'message': str(failure)})
    unchanged = before == sha(source)
    result = {'pid': None if child is None else child.pid, 'command': command,
        'run': str(run), 'inputs': identity, 'exit_code': code,
        'retained_case_handle_exited': joined, 'timed_out': timed_out,
        'outer_deadline_s': timeout_s, 'elapsed_s': time.monotonic() - started,
        'emergency_termination_attempted': emergency,
        'emergency_termination_is_qualification_failure': True,
        'supervision_errors': errors, 'parent_source_sha256': before,
        'parent_source_unchanged': unchanged,
        'normal_parent_exit': joined and code == 0 and not emergency and not errors and unchanged,
        'qualification_claimed': False,
        'scope': 'Actual parent wait/join only. Task correctness, native cleanup and video coexistence require separate terminal evidence.'}
    save(receipt, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'run', 'task-spec', 'task-inputs'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise ValueError('The installed adaptive desktop composition requires Windows')
    command, run, identity = prepare(args.profile, args.run, args.task_spec, args.task_inputs)
    result = supervise(command, run, identity)
    print(json.dumps(result, allow_nan=False))
    return 0 if result['normal_parent_exit'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
