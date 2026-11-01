# SPDX-License-Identifier: Apache-2.0
"""Bounded GET-only status plus independent foreground observations, no control."""
import argparse
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from adaptive_inference.desktop.profile import WindowsProfile

OUTER_SECONDS = 2700
MAX_BYTES = 64 * 1024


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def invalid_constant(value):
    raise ValueError('Non-finite JSON constant: ' + value)


def fetch_status(opener, url, timeout):
    """Reuse the task-handover observer's bounded response/identity checks."""
    request = urllib.request.Request(url, method='GET', headers={
        'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError('Unexpected status or response URL')
            if response.headers.get_content_type() != 'application/json':
                raise ValueError('Expected JSON response')
            size = int(response.headers.get('Content-Length', '-1'))
            if not 0 <= size <= MAX_BYTES:
                raise ValueError('Missing or oversized response length')
            raw = response.read(MAX_BYTES + 1)
            if len(raw) != size or len(raw) > MAX_BYTES:
                raise ValueError('Incomplete or oversized response body')
    except urllib.error.HTTPError as error:
        error.close()
        raise
    value = json.loads(raw, parse_constant=invalid_constant)
    if (type(value) is not dict or value.get('service') != 'adaptive-inference'
            or type(value.get('instance')) is not str
            or re.fullmatch(r'[0-9a-f]{32}', value['instance']) is None
            or type(value.get('resources')) is not dict
            or type(value.get('scheduler')) is not dict
            or type(value['resources'].get('admission_allowed')) is not bool):
        raise ValueError('Unexpected gateway status schema')
    return value


def observe(profile_path, run, *, activity_reader, qpc_now, clock_id,
            duration_s=OUTER_SECONDS, sample_interval_s=.2, status_interval_s=1):
    """Injected reader/clock and short durations support CPU-only component tests.

    The ordinary command uses WindowsActivityReader and the verified QPC clock.
    This reader is independent of the controller's reader, not its policy input.
    """
    profile_path = Path(profile_path).resolve(strict=True)
    profile = WindowsProfile.load(profile_path)
    run = Path(run)
    if not run.is_absolute() or not run.parent.is_dir():
        raise ValueError('Explicit absolute run under an existing parent required')
    run = run.parent.resolve(strict=True) / run.name
    terminal = run / 'result.private.json'
    output = Path(str(run) + '.api-trace.private.jsonl')
    receipt_path = Path(str(run) + '.observer.private.json')
    if any(path.exists() for path in (output, receipt_path, terminal)):
        raise ValueError('Fresh observer sidecars and nonterminal run required')
    url = f'http://127.0.0.1:{profile.gateway.port}/status'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    source = Path(__file__).resolve()
    reader_source = Path(inspect.getfile(type(activity_reader))).resolve(strict=True)
    pins = {'observer': sha(source), 'activity_reader': sha(reader_source), 'profile': sha(profile_path)}
    started = time.monotonic()
    deadline = started + duration_s
    next_status = started
    count = valid = failures = activity_errors = 0
    previous_sample = max_gap = instance = None
    terminal_exists = False
    reason, fault = 'observation_deadline', None
    with output.open('x', encoding='utf-8') as stream:
        try:
            while time.monotonic() < deadline:
                stamp = time.monotonic()
                gap = None if previous_sample is None else stamp - previous_sample
                if gap is not None:
                    max_gap = max(max_gap or 0, gap)
                previous_sample = stamp
                row = {'reader_monotonic': stamp, 'reader_wall_time': time.time(),
                       'sample_gap_s': gap, 'deadline_clock': clock_id}
                # Metadata only; never parse mutable result, status or SQLite files.
                terminal_exists = terminal.exists()
                row['terminal_path_exists'] = terminal_exists
                row['activity_before_deadline_clock'] = qpc_now()
                try:
                    row['activity'] = activity_reader.sample()
                    if row['activity'].get('errors'):
                        activity_errors += 1
                except Exception as error:
                    activity_errors += 1
                    row['activity_error'] = {'type': type(error).__name__, 'message': str(error)}
                finally:
                    row['activity_after_deadline_clock'] = qpc_now()
                if stamp >= next_status:
                    row['status_before_deadline_clock'] = qpc_now()
                    next_status = time.monotonic() + status_interval_s
                    try:
                        value = fetch_status(opener, url, min(2., max(.001, deadline - time.monotonic())))
                        if instance is not None and value['instance'] != instance:
                            raise ValueError('Gateway instance changed')
                        instance = value['instance']
                        valid += 1
                        failures = 0
                        row['gateway_status'] = value
                    except urllib.error.HTTPError as error:
                        reason = 'http_error'
                        fault = row['observation_error'] = {'type': 'HTTPError', 'status': error.code}
                    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                        failures += 1
                        underlying = error.reason if isinstance(error, urllib.error.URLError) else error
                        refused = (isinstance(underlying, ConnectionRefusedError)
                                   or getattr(underlying, 'winerror', None) == 10061)
                        row['observation_error'] = {'type': type(error).__name__,
                            'reason_type': type(underlying).__name__, 'connection_refused': refused}
                        row['consecutive_connection_errors'] = failures
                        if terminal_exists and refused and instance is not None:
                            reason = 'terminal_path_exists_and_connection_refused'
                        elif instance is not None and failures >= 3:
                            reason = 'three_connection_errors_after_response'
                    except (ValueError, TypeError, UnicodeError) as error:
                        reason = 'invalid_status_or_identity'
                        fault = row['observation_error'] = {'type': type(error).__name__, 'message': str(error)}
                    finally:
                        row['status_after_deadline_clock'] = qpc_now()
                for prefix in ('activity', 'status'):
                    if prefix + '_before_deadline_clock' in row:
                        lo, hi = (row[prefix + suffix] for suffix in ('_before_deadline_clock', '_after_deadline_clock'))
                        if not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
                            reason = 'invalid_clock_observation'
                            fault = {'type': 'ClockOrderingError'}
                stream.write(json.dumps(row, allow_nan=False) + '\n')
                stream.flush()
                count += 1
                if reason != 'observation_deadline':
                    break
                # One loop, no retry burst; blocking HTTP gaps remain in the trace.
                time.sleep(max(0, min(deadline - time.monotonic(),
                                     sample_interval_s - (time.monotonic() - stamp))))
        except BaseException as error:
            reason = 'observer_error'
            fault = {'type': type(error).__name__, 'message': str(error)}
    unchanged = pins == {'observer': sha(source), 'activity_reader': sha(reader_source), 'profile': sha(profile_path)}
    receipt = {'run': str(run), 'profile': str(profile_path), 'url': url,
        'samples': count, 'valid_responses': valid, 'activity_error_samples': activity_errors,
        'elapsed_s': time.monotonic() - started, 'duration_limit_s': duration_s,
        'sample_interval_s': sample_interval_s, 'status_interval_s': status_interval_s,
        'maximum_sample_gap_s': max_gap, 'gateway_instance': instance,
        'end_reason': reason, 'terminal_path_exists': terminal_exists,
        'consecutive_connection_errors': failures, 'fault': fault,
        'source_sha256': pins, 'sources_unchanged': unchanged,
        'activity_reader_source': str(reader_source), 'deadline_clock': clock_id,
        'active_case_file_contents_read': False, 'task_completion_claimed': False,
        'qualification_claimed': False,
        'scope': 'Independent foreground samples and GET-only gateway status. Not the controller sample stream, GPU attribution, task acceptance or cleanup proof.',
        'timeout_scope': 'Two seconds per blocking HTTP operation and a bounded sampling loop; not a hard OS wall-clock deadline. CPU gaps remain unknown.'}
    with receipt_path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        raise ValueError('Windows foreground observation required')
    from adaptive_inference import execution_clock
    from adaptive_inference.desktop.activity import WindowsActivityReader
    clock = execution_clock.verify_execution_clock()
    result = observe(args.profile, args.run, activity_reader=WindowsActivityReader(),
                     qpc_now=execution_clock.execution_now, clock_id=clock)
    print(json.dumps(result, allow_nan=False))
    return 0 if (result['end_reason'] == 'terminal_path_exists_and_connection_refused'
                 and result['sources_unchanged']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
