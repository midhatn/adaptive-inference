"""Bounded external GET-only observer; never opens active qualification files.

Reuses observe-full-case.private.py's JSONL, clock, source-hash and receipt shape.
Research: https://docs.python.org/3.11/library/urllib.request.html (context-managed
responses, per-blocking-operation timeout, ProxyHandler, HTTPRedirectHandler),
https://docs.python.org/3.11/library/urllib.error.html (HTTPError owns a response).
No model request, control command, process management, or product-source change.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time
import sys
import urllib.error
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent))
from bindings import load, OUTER_SECONDS
from adaptive_inference import execution_clock

ROOT = Path(__file__).resolve().parent.parent
URL = 'http://127.0.0.1:18100/status'
MAX_BYTES = 64 * 1024
DURATION_S = OUTER_SECONDS


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def invalid_constant(value):
    raise ValueError('Non-finite JSON constant: ' + value)


def fetch_status(opener, timeout):
    request = urllib.request.Request(URL, method='GET', headers={
        'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200 or response.geturl() != URL:
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
        # HTTPError itself owns a response. Never leave its socket open.
        error.close()
        raise
    value = json.loads(raw, parse_constant=invalid_constant)
    if (type(value) is not dict or value.get('service') != 'adaptive-inference'
            or type(value.get('instance')) is not str
            or not re.fullmatch(r'[0-9a-f]{32}', value['instance'])
            or type(value.get('resources')) is not dict
            or type(value.get('scheduler')) is not dict
            or type(value['resources'].get('admission_allowed')) is not bool):
        raise ValueError('Unexpected gateway status schema')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', type=Path, required=True)
    args = parser.parse_args()
    bound = load(args.bindings, installed=True)
    deadline_clock = execution_clock.verify_execution_clock()
    case = bound['case']
    terminal = case / 'result.private.json'
    output = Path(str(case)+'.api-trace.private.jsonl')
    receipt_path = output.with_suffix('.receipt.json')
    if output.exists() or receipt_path.exists() or terminal.exists():
        raise RuntimeError('Use this observer once for the fresh, non-terminal attempt')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    source = Path(__file__).resolve()
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    started = time.monotonic()
    deadline = started + DURATION_S
    count = valid = failures = 0
    instance = None
    terminal_exists = False
    reason = 'observation_deadline'
    fault = None
    with output.open('x', encoding='utf-8') as stream:
        try:
            while time.monotonic() < deadline:
                stamp = time.monotonic()
                row = {'reader_monotonic': stamp, 'reader_wall_time': time.time()}
                row['deadline_clock'] = deadline_clock
                # Metadata existence only: never open or parse a case artifact.
                terminal_exists = terminal.exists()
                row['terminal_path_exists'] = terminal_exists
                try:
                    row['reader_before_deadline_clock'] = execution_clock.execution_now()
                    value = fetch_status(opener, min(2.0, max(.001, deadline-stamp)))
                    if instance is not None and value['instance'] != instance:
                        raise ValueError('Gateway instance changed')
                    instance = value['instance']
                    valid += 1
                    failures = 0
                    row['gateway_status'] = value
                except urllib.error.HTTPError as error:
                    row['observation_error'] = {'type': 'HTTPError', 'status': error.code}
                    reason = 'http_error'
                    fault = row['observation_error']
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
                    fault = {'type': type(error).__name__, 'message': str(error)}
                    row['observation_error'] = fault
                finally:
                    row['reader_after_deadline_clock'] = execution_clock.execution_now()
                before, after = row['reader_before_deadline_clock'], row['reader_after_deadline_clock']
                if not math.isfinite(before) or not math.isfinite(after) or not before <= after:
                    reason = 'invalid_clock_observation'
                    fault = {'type': 'ClockOrderingError'}
                    row['observation_error'] = fault
                stream.write(json.dumps(row, allow_nan=False) + '\n')
                stream.flush()
                count += 1
                if reason != 'observation_deadline':
                    break
                # At most one new request per second; no retry burst or overlap.
                time.sleep(max(0, min(deadline-time.monotonic(), 1-(time.monotonic()-stamp))))
        except BaseException as error:
            reason = 'observer_error'
            fault = {'type': type(error).__name__, 'message': str(error)}
    unchanged = source_before == hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = {'samples': count, 'valid_responses': valid,
        'elapsed_s': time.monotonic()-started, 'gateway_instance': instance,
        'end_reason': reason, 'terminal_path_exists': terminal_exists,
        'consecutive_connection_errors': failures, 'fault': fault,
        'source_sha256': source_before, 'source_unchanged': unchanged,
        'harness_manifest': bound['manifest_sha256'], 'bindings_sha256': bound['bindings_sha256'],
        'deadline_clock': deadline_clock, 'execution_clock_origin': str(Path(execution_clock.__file__).resolve()),
        'reader_monotonic_scope': 'local sampling and elapsed diagnostics; never compare with the QPC task deadline',
        'active_case_file_contents_read': False, 'task_completion_claimed': False,
        'scope': 'External bounded status observations only; terminal existence and connection refusal do not prove cleanup or task completion.',
        'timeout_scope': '2 seconds per blocking urllib operation; 2700-second loop deadline, not a hard OS wall-clock guarantee.'}
    with receipt_path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    print(json.dumps(receipt, allow_nan=False))
    return 0 if reason == 'terminal_path_exists_and_connection_refused' and unchanged else 2


if __name__ == '__main__':
    raise SystemExit(main())
