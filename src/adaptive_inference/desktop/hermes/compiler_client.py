# SPDX-License-Identifier: Apache-2.0
"""Synchronous worker client for the host's retained compiler operation.

Reuse the bridge's identity/size contract, TaskSpec's strict JSON, and the
existing validation observer's explicit no-proxy/no-redirect urllib pattern.
Only a valid pending reply permits another exchange, with identical bytes.
Transport uncertainty never authorizes a new operation or a deadline refund.

https://docs.python.org/3.11/library/urllib.request.html
https://docs.python.org/3.11/library/urllib.error.html
https://docs.python.org/3.11/library/socket.html#notes-on-socket-timeouts
urllib timeouts bound blocking operations, not an OS-enforced total duration.
The original execution clock is checked before/after every exchange and wait;
the host independently enforces that same deadline and owns process cleanup.
"""
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

from adaptive_inference.desktop.compiler_bridge import (
    HEADER, ROUTE, REQUEST_LIMIT, RESPONSE_LIMIT, STAGES, _decode as decode_request)
from adaptive_inference.execution_clock import execution_now
from adaptive_inference.task_spec import COMPILER_STATUSES, strict_json

_PRE_DISPATCH = {'binding_refused', 'preparation_failed', 'cancelled_before_dispatch'}
_RESULT_FIELDS = {'schema', 'operation_id', 'recipe_id', 'recipe_sha256', 'status',
                  'passed', 'dispatched', 'owned_processes_exited', 'task_deadline'}


class CompilerClientError(RuntimeError):
    """Fixed codes only. No exception payload, credentials or no-dispatch claim."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


class CompilerClient:
    """Callable only from the already-authorized synchronous tool handler.

    The caller supplies the original task_deadline, never a duration. Injected
    clock/opener/sleep are trusted test boundaries, not agent-selected settings.
    An uncertain exchange fences this client; the durable owner reconciles it.
    """
    def __init__(self, port, capability, task_deadline, *, clock=execution_now,
                 opener=None, sleep=time.sleep, request_timeout=2., poll_interval=.1):
        if (type(port) is not int or not 1 <= port <= 65535
                or not _sha(capability)
                or type(task_deadline) not in (int, float)
                or not math.isfinite(task_deadline) or task_deadline <= 0
                or not callable(clock) or not callable(sleep)
                or type(request_timeout) not in (int, float)
                or not 0 < request_timeout <= 2
                or type(poll_interval) not in (int, float) or not 0 < poll_interval <= 1
                or opener is not None and not callable(getattr(opener, 'open', None))):
            raise CompilerClientError('invalid_configuration')
        self.port, self.task_deadline = port, task_deadline
        self._capability, self._clock, self._sleep = capability, clock, sleep
        self._opener = opener if opener is not None else urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        self._url = f'http://127.0.0.1:{port}{ROUTE}'
        self._request_timeout, self._poll_interval = request_timeout, poll_interval
        self._lock, self._failed, self._last_clock = threading.Lock(), False, None

    def __repr__(self):
        return f'CompilerClient(port={self.port}, capability=[redacted])'

    def _remaining(self):
        now = self._clock()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or self._last_clock is not None and now < self._last_clock):
            raise CompilerClientError('invalid_clock')
        self._last_clock = now
        remaining = self.task_deadline - now
        if remaining <= 0:
            raise CompilerClientError('original_deadline_expired')
        return remaining

    def _exchange(self, body):
        request = urllib.request.Request(self._url, data=body, method='POST', headers={
            HEADER: self._capability, 'Content-Type': 'application/json',
            'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        timeout = min(self._request_timeout, self._remaining())
        try:
            with self._opener.open(request, timeout=timeout) as response:
                self._remaining()
                lengths = response.headers.get_all('Content-Length', [])
                if (response.status != 200 or response.geturl() != self._url
                        or response.headers.get_content_type() != 'application/json'
                        or response.headers.get('Transfer-Encoding') is not None
                        or response.headers.get('Content-Encoding', 'identity') != 'identity'
                        or len(lengths) != 1 or re.fullmatch('[0-9]{1,5}', lengths[0]) is None):
                    raise CompilerClientError('invalid_response')
                size = int(lengths[0])
                if not 0 < size <= RESPONSE_LIMIT:
                    raise CompilerClientError('invalid_response')
                raw = response.read(size + 1)
                self._remaining()
                if (type(raw) is not bytes or len(raw) != size
                        or self._capability.encode() in raw):
                    raise CompilerClientError('invalid_response')
            return strict_json(raw.decode('utf-8'))
        except urllib.error.HTTPError as error:
            error.close()
            raise CompilerClientError('http_outcome_unconfirmed') from None
        except CompilerClientError:
            raise
        except Exception:
            # Even a failed response may follow a dispatched retained operation.
            # Do not expose urllib's request/exception details or retry it.
            raise CompilerClientError('transport_or_protocol_unconfirmed') from None

    def _result(self, reply, request):
        if (type(reply) is not dict or set(reply) != {'ok', 'operation_id', 'state', 'result'}
                or reply['ok'] is not True or reply['operation_id'] != request['operation_id']
                or type(reply['state']) is not str or reply['state'] not in {'pending', 'completed', 'unknown'}):
            raise CompilerClientError('invalid_operation_reply')
        if reply['state'] == 'unknown':
            raise CompilerClientError('operation_outcome_unknown')
        if reply['state'] == 'pending':
            if reply['result'] is not None:
                raise CompilerClientError('invalid_pending_reply')
            return None
        result = reply['result']
        if (type(result) is not dict or not _RESULT_FIELDS <= set(result)
                or result['schema'] != 'compiler-operation-result.v1'
                or result['operation_id'] != request['operation_id']
                or result['recipe_id'] != request['recipe_id']
                or type(result['status']) is not str or result['status'] not in COMPILER_STATUSES
                or result['owned_processes_exited'] is not True
                or type(result['passed']) is not bool or type(result['dispatched']) is not bool
                or result['passed'] != (result['status'] == 'passed')
                or type(result['task_deadline']) not in (int, float)
                or result['task_deadline'] != self.task_deadline):
            raise CompilerClientError('unconfirmed_terminal_result')
        if result['status'] in _PRE_DISPATCH:
            if (set(result) != _RESULT_FIELDS or result['dispatched']
                    or result['recipe_sha256'] is not None and not _sha(result['recipe_sha256'])):
                raise CompilerClientError('unconfirmed_terminal_result')
        else:
            extra = ({'artifact_sha256', 'artifact_bytes', 'test_report_sha256', 'tests_passed'}
                     if result['passed'] else {'diagnostics'})
            if (set(result) != _RESULT_FIELDS | {'receipt_sha256', 'stages'} | extra
                    or not _sha(result['recipe_sha256']) or not _sha(result['receipt_sha256'])
                    or type(result['stages']) is not list or len(result['stages']) > len(STAGES)
                    or any(type(row) is not dict or not {'stage'} <= set(row) <= {'stage', 'exit_code'}
                           or row['stage'] not in STAGES
                           or 'exit_code' in row and type(row['exit_code']) is not int
                           for row in result['stages'])):
                raise CompilerClientError('unconfirmed_terminal_result')
            if result['passed']:
                if (not result['dispatched'] or not _sha(result['artifact_sha256'])
                        or not _sha(result['test_report_sha256'])
                        or type(result['artifact_bytes']) is not int or result['artifact_bytes'] <= 0
                        or type(result['tests_passed']) is not list or not result['tests_passed']
                        or any(type(name) is not str or not name for name in result['tests_passed'])):
                    raise CompilerClientError('unconfirmed_terminal_result')
            elif (type(result['diagnostics']) is not list or len(result['diagnostics']) > len(STAGES)
                  or any(type(row) is not dict or set(row) != {'stage', 'text', 'truncated'}
                         or row['stage'] not in STAGES or type(row['text']) is not str
                         or len(row['text']) > 4096 or type(row['truncated']) is not bool
                         for row in result['diagnostics'])):
                raise CompilerClientError('unconfirmed_terminal_result')
        return result

    def __call__(self, request):
        try:
            body = json.dumps(request, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(body) > REQUEST_LIMIT or self._capability.encode() in body:
                raise ValueError('bounded request required')
            identity = decode_request(body)
        except Exception:
            raise CompilerClientError('invalid_request') from None
        if not self._lock.acquire(blocking=False):
            raise CompilerClientError('client_busy')
        try:
            if self._failed:
                raise CompilerClientError('client_requires_reconciliation')
            while True:
                result = self._result(self._exchange(body), identity)
                if result is not None:
                    self._remaining()
                    return result
                self._sleep(min(self._poll_interval, self._remaining()))
                self._remaining()
        except CompilerClientError:
            self._failed = True
            raise
        except Exception:
            self._failed = True
            raise CompilerClientError('client_outcome_unconfirmed') from None
        finally:
            self._lock.release()
