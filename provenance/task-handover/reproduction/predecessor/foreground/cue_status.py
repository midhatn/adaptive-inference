# SPDX-License-Identifier: Apache-2.0
"""Bounded operator cue from the existing append-only GET trace only.

No HTTP, controls, UI, database, model or child-process operation. Reuses the
reviewed binding reader and Python stream/QPC facilities documented in
operator-latency-research-01/PROPOSAL.private.md. A cue is not qualification.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / 'task-handover-safe-wait-harness-author-04'))
from bindings import load, read, unique

CLOCK = 'windows-qpc-seconds-v1'
SCHEMA = 'private.case10.first-active-cue.v1'
MAX_SECONDS = 20.0
MAX_AGE = 2.0
MAX_ROW_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 1024


class CueRefused(ValueError):
    pass


def require(condition, reason):
    if condition is not True:
        raise CueRefused(reason)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def reject_constant(_value):
    raise CueRefused('nonfinite_json')


def latest_line(path, previous=None):
    """Return only the final complete row; never bypass a partial suffix.

    The sole changing read target is this caller-bound trace. Metadata checks
    reject replacement/shrinkage and a concurrent append makes us wait again.
    Local I/O is size-bounded; no hard OS filesystem-stall deadline is claimed.
    """
    path = Path(path)
    try:
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            identity = (before.st_dev, before.st_ino)
            require(stat.S_ISREG(before.st_mode), 'trace_not_regular')
            if previous is not None:
                require(identity == previous[0] and before.st_size >= previous[1],
                        'trace_replaced_or_shrunk')
            size = before.st_size
            stream.seek(max(0, size - MAX_ROW_BYTES - 2))
            raw = stream.read(min(size, MAX_ROW_BYTES + 2))
            after = os.fstat(stream.fileno())
            named = path.stat(follow_symlinks=False)
            require(stat.S_ISREG(named.st_mode)
                    and (named.st_dev, named.st_ino) == identity, 'trace_replaced')
            require(after.st_size >= size and named.st_size >= size, 'trace_shrunk_during_read')
            current = (identity, max(after.st_size, named.st_size))
            if len(raw) != min(size, MAX_ROW_BYTES + 2) or after.st_size != size or named.st_size != size:
                return None, 'trace_appended_during_read', current
    except FileNotFoundError:
        require(previous is None, 'trace_disappeared')
        return None, 'trace_not_ready', None
    if not raw:
        return None, 'empty_trace', current
    if not raw.endswith(b'\n'):
        # An old matching complete row before this suffix is not the latest row.
        require(len(raw.rsplit(b'\n', 1)[-1]) <= MAX_ROW_BYTES, 'latest_row_oversized')
        return None, 'partial_latest_row', current
    separator = raw.rfind(b'\n', 0, len(raw) - 1)
    require(separator >= 0 or size <= MAX_ROW_BYTES + 1, 'latest_row_oversized')
    line = raw[separator + 1:-1]
    require(0 < len(line) <= MAX_ROW_BYTES, 'empty_or_oversized_latest_row')
    return line, None, current


def classify(line, instance, now):
    """Validate one latest row; return a cue or a nonmatching wait reason."""
    require(type(instance) is str and re.fullmatch('[0-9a-f]{32}', instance) is not None,
            'invalid_expected_instance')
    require(finite(now), 'invalid_local_qpc')
    require(type(line) is bytes and len(line) <= MAX_ROW_BYTES, 'invalid_row_bytes')
    try:
        row = json.loads(line, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, TypeError):
        raise CueRefused('malformed_latest_row') from None
    require(type(row) is dict and row.get('deadline_clock') == CLOCK, 'wrong_clock_or_row')
    before, after = row.get('reader_before_deadline_clock'), row.get('reader_after_deadline_clock')
    require(finite(before) and finite(after) and before <= after <= now, 'invalid_qpc_bracket')
    require('observation_error' not in row and row.get('terminal_path_exists') is False,
            'observer_error_or_terminal')
    gateway = row.get('gateway_status')
    require(type(gateway) is dict and gateway.get('service') == 'adaptive-inference',
            'invalid_gateway_status')
    require(gateway.get('instance') == instance, 'gateway_instance_changed')
    scheduler, resources = gateway.get('scheduler'), gateway.get('resources')
    require(type(scheduler) is dict and type(resources) is dict, 'invalid_status_shape')
    require(type(scheduler.get('active')) is bool
            and all(type(scheduler.get(k)) is int and scheduler[k] >= 0
                    for k in ('completed', 'pending'))
            and type(resources.get('admission_allowed')) is bool
            and type(resources.get('handoff_state')) is str
            and type(resources.get('foreground_reason')) is str
            and 0 < len(resources['foreground_reason']) <= 80,
            'invalid_status_types')
    require(scheduler.get('backend_completion_uncertain') is False
            and scheduler.get('closing') is False
            and 'fault' in resources and resources['fault'] is None,
            'uncertain_closed_or_faulted')
    require(scheduler['completed'] == 0, 'first_cycle_already_completed')
    if now - after > MAX_AGE:
        return None, 'latest_row_stale'
    if not (scheduler['active'] is True and scheduler['pending'] == 0
            and resources['admission_allowed'] is True
            and resources['handoff_state'] == 'ready'):
        return None, 'latest_not_open_ready_first_active'
    return {'schema': SCHEMA, 'status': 'ready', 'deadline_clock': CLOCK,
            'gateway_instance': instance, 'row_qpc_before': before, 'row_qpc_after': after,
            'observed_at_qpc': now, 'age_s': now - after,
            'scheduler': {k: scheduler[k] for k in
                          ('active', 'completed', 'pending', 'backend_completion_uncertain', 'closing')},
            'resources': {k: resources[k] for k in
                          ('admission_allowed', 'handoff_state', 'foreground_reason', 'fault')},
            'scope': 'Operator cue only; inspect the real window before any action.'}, None


def wait_for_cue(path, instance, *, deadline, clock=time.perf_counter, sleep=time.sleep):
    """A bounded local loop; only the declared trace is read while waiting."""
    started = clock()
    require(finite(started) and finite(deadline) and deadline - started <= MAX_SECONDS,
            'wait_must_be_at_most_20_seconds')
    previous = None
    reason = 'trace_not_ready'
    while clock() < deadline:
        line, reason, previous = latest_line(path, previous)
        now = clock()
        if now >= deadline:
            break
        if line is not None:
            cue, reason = classify(line, instance, now)
            # Recheck age/deadline after parsing, immediately before returning.
            finished = clock()
            if cue is not None and finished < deadline and finished - cue['row_qpc_after'] <= MAX_AGE:
                cue.update(observed_at_qpc=finished, age_s=finished - cue['row_qpc_after'])
                return cue
            if cue is not None:
                reason = 'latest_row_stale_or_deadline'
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(0.1, remaining))
    return {'schema': SCHEMA, 'status': 'timeout', 'reason': reason or 'wait_deadline',
            'scope': 'No cue; no control or test-budget change.'}


def encoded_output(value):
    result = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n'
    if len(result.encode('utf-8')) > MAX_OUTPUT_BYTES:
        result = json.dumps({'schema': SCHEMA, 'status': 'refused', 'reason': 'output_bound'},
                            separators=(',', ':')) + '\n'
    return result


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise CueRefused('invalid_arguments')


def main(argv=None):
    started = time.perf_counter()
    try:
        parser = Parser(add_help=False)
        parser.add_argument('--bindings', type=Path, required=True)
        parser.add_argument('--instance', required=True)
        parser.add_argument('--seconds', type=float, default=MAX_SECONDS)
        args = parser.parse_args(argv)
        require(finite(args.seconds) and args.seconds <= MAX_SECONDS, 'wait_must_be_at_most_20_seconds')
        require(re.fullmatch('[0-9a-f]{32}', args.instance) is not None, 'invalid_expected_instance')
        deadline = started + args.seconds
        info = time.get_clock_info('perf_counter')
        require(os.name == 'nt' and info.implementation == 'QueryPerformanceCounter()'
                and info.monotonic is True and info.adjustable is False
                and math.isfinite(info.resolution) and info.resolution > 0, 'windows_qpc_required')
        expected_binding = BASE / 'task-handover-installed-bindings-17.private.json'
        require(args.bindings.resolve(strict=True) == expected_binding, 'exact_case10_binding_required')
        # Static reviewed inputs only; this does not import the installed package.
        bound = load(args.bindings, installed=False)
        disabled = read(HERE / 'bindings.disabled.private.json')
        require(disabled.get('enabled') is False
                and bound['value'] == {**disabled, 'enabled': True}
                and bound['case'] == BASE / 'installed-ui-task-handover-17', 'only_case10_activation_delta')
        require(Path(sys.executable).resolve() == Path(bound['profile']['host_python']['path']).resolve(),
                'bound_host_interpreter_required')
        path = Path(str(bound['case']) + '.api-trace.private.jsonl')
        value = wait_for_cue(path, args.instance, deadline=deadline)
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, CueRefused) else 'cue_input_or_io_refused'
        value = {'schema': SCHEMA, 'status': 'refused', 'reason': reason}
    sys.stdout.write(encoded_output(value))
    return 0 if value['status'] == 'ready' else 2


if __name__ == '__main__':
    raise SystemExit(main())
