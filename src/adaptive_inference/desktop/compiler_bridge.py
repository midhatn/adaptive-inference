# SPDX-License-Identifier: Apache-2.0
"""Recipe-only worker/host bridge on the existing aiohttp application.

Reuse ControlTransport's bounded, authenticated, idempotent retained-operation
pattern, without its GUI authority or another listener. A trusted callback owns
TaskStore/native-call authorization; the existing recipe runner owns the grant
and compiler subtree. This module never grants an agent a command or path.

https://docs.aiohttp.org/en/stable/web_quickstart.html#handler
https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation
"""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import stat
import threading

from aiohttp import web
from adaptive_inference.desktop.compiler_recipe import CompilerRecipe, RecipeCleanupError, run_recipe

ROUTE = '/_adaptive/compiler-operation'
HEADER = 'X-Adaptive-Compiler-Capability'
REQUEST_LIMIT, RESPONSE_LIMIT = 4096, 24576
FIELDS = {'schema', 'host_epoch', 'task_id', 'execution_id', 'owner_epoch',
          'operation_id', 'tool_call_id', 'recipe_id'}
STAGES = ('configure', 'build', 'test')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Non-finite JSON')


def _decode(raw):
    value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
    if (type(value) is not dict or set(value) != FIELDS
            or value['schema'] != 'compiler-operation.v1'
            or any(type(value[key]) is not str
                   or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value[key])
                   for key in FIELDS - {'schema'})):
        raise ValueError('Bounded compiler identity required')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'), default=lambda item: str(item) if isinstance(item, Path) else _constant(item))


def _plain(path):
    info = path.lstat()
    if getattr(info, 'st_file_attributes', 0) & 0x400 or not stat.S_ISREG(info.st_mode):
        raise ValueError('Expected ordinary recipe output')
    return info


class CompilerBridge:
    """One host-loop bridge; trusted factories prepare one recipe per operation.

    validate_binding(request) must asynchronously return exactly True only for
    this selected worker's live, native-durable inflight effect. The allowed
    recipes map contains async factories(request) -> frozen CompilerRecipe.
    Factories run once after authorization; identical retries never resnapshot.
    No database ownership is transferred to this bridge.
    """
    def __init__(self, controller, recipes, *, capability, task_deadline,
                 validate_binding, runner=run_recipe, reply_timeout=.1, max_operations=16):
        if (type(capability) is not str or not re.fullmatch('[0-9a-f]{64}', capability)
                or type(task_deadline) not in (int, float) or not math.isfinite(task_deadline)
                or task_deadline <= 0 or not callable(validate_binding) or not callable(runner)
                or type(recipes) is not dict or not 1 <= len(recipes) <= 16
                or any(type(name) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', name)
                       or not callable(factory) for name, factory in recipes.items())
                or type(reply_timeout) not in (int, float) or not 0 < reply_timeout <= 2
                or type(max_operations) is not int or not 1 <= max_operations <= 32):
            raise ValueError('Bounded trusted compiler bridge configuration required')
        self.controller, self.recipes = controller, dict(recipes)
        self.task_deadline, self.validate_binding, self.runner = task_deadline, validate_binding, runner
        self._capability = capability
        self.reply_timeout, self.max_operations = reply_timeout, max_operations
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self._records, self._closing, self._installed = {}, False, False

    def _owner(self):
        if asyncio.get_running_loop() is not self._loop or threading.current_thread() is not self._thread:
            raise RuntimeError('Compiler bridge belongs to its original host loop')

    def add_route(self, app):
        self._owner()
        if self._installed or self._closing:
            raise RuntimeError('Install the compiler route once before host startup')
        app.router.add_post(ROUTE, self.handle)
        self._installed = True

    def _reply(self, value, *, status=200):
        encoded = _json(value).encode('utf-8')
        if len(encoded) > RESPONSE_LIMIT or self._capability.encode() in encoded:
            return web.json_response({'ok': False, 'error': 'projection_refused'}, status=500)
        return web.Response(body=encoded, status=status, content_type='application/json')

    async def handle(self, request):
        self._owner()
        token = request.headers.get(HEADER, '')
        if (request.headers.get('Origin') is not None or type(token) is not str
                or not re.fullmatch('[0-9a-f]{64}', token)
                or not secrets.compare_digest(token, self._capability)):
            return self._reply({'ok': False, 'error': 'unauthorized'}, status=403)
        try:
            # Bound decompressed input too, without accepting an oversized body
            # merely because the host inference application permits one.
            body = bytearray()
            async with asyncio.timeout(2):
                async for chunk in request.content.iter_chunked(REQUEST_LIMIT + 1):
                    body.extend(chunk)
                    if len(body) > REQUEST_LIMIT:
                        raise ValueError('Request too large')
            value = _decode(body)
        except (ValueError, UnicodeError, RecursionError, TimeoutError):
            return self._reply({'ok': False, 'error': 'invalid_request'}, status=400)
        operation_id = value['operation_id']
        record = self._records.get(operation_id)
        if record is not None:
            if record['request'] != value:
                return self._reply({'ok': False, 'error': 'conflicting_operation'}, status=409)
        else:
            if self._closing:
                return self._reply({'ok': False, 'error': 'stopping'}, status=409)
            if value['recipe_id'] not in self.recipes:
                return self._reply({'ok': False, 'error': 'unknown_recipe'}, status=400)
            if len(self._records) >= self.max_operations or any(
                    not row['task'].done() or row['unknown'] for row in self._records.values()):
                return self._reply({'ok': False, 'error': 'capacity_unavailable'}, status=409)
            record = {'request': deepcopy(value), 'recipe': None, 'recipe_sha256': None,
                      'runner': None, 'entered_runner': False, 'interrupted': False,
                      'cancel_sent': False, 'result': None, 'unknown': False,
                      'error': None, 'owner': None, 'receipt': None}
            self._records[operation_id] = record
            record['task'] = self._loop.create_task(self._execute(record), name='compiler-operation')
        try:
            await asyncio.wait_for(asyncio.shield(record['task']), self.reply_timeout)
        except TimeoutError:
            pass  # Only a response deadline; the original operation is retained.
        return self._reply({'ok': True, 'operation_id': operation_id,
                            'state': 'unknown' if record['unknown'] else 'completed' if record['result'] else 'pending',
                            'result': deepcopy(record['result'])})

    def _terminal(self, record, status, *, dispatched=False):
        # Dispatch is tri-state: True/False require evidence; None is unknown.
        return {'schema': 'compiler-operation-result.v1', 'operation_id': record['request']['operation_id'],
                'recipe_id': record['request']['recipe_id'], 'recipe_sha256': record['recipe_sha256'],
                'status': status, 'passed': False, 'dispatched': dispatched,
                'owned_processes_exited': not record['unknown'], 'task_deadline': self.task_deadline}

    async def _invoke(self, record):
        record['entered_runner'] = True
        return await self.runner(self.controller, record['recipe'], task_deadline=self.task_deadline)

    async def _execute(self, record):
        try:
            if await self.validate_binding(deepcopy(record['request'])) is not True:
                record['result'] = self._terminal(record, 'binding_refused')
                return
            if record['interrupted']:
                record['result'] = self._terminal(record, 'cancelled_before_dispatch')
                return
            recipe = await self.recipes[record['request']['recipe_id']](deepcopy(record['request']))
            if type(recipe) is not CompilerRecipe:
                raise TypeError('Trusted factory did not prepare a CompilerRecipe')
            record['recipe'] = recipe
            record['recipe_sha256'] = hashlib.sha256(_json(asdict(recipe)).encode()).hexdigest()
            if record['interrupted']:
                record['result'] = self._terminal(record, 'cancelled_before_dispatch')
                return
            # A factory may await disk work. Recheck live authority before work;
            # duplicate HTTP requests still use this single frozen preparation.
            if await self.validate_binding(deepcopy(record['request'])) is not True:
                record['result'] = self._terminal(record, 'binding_refused')
                return
            if record['interrupted']:
                record['result'] = self._terminal(record, 'cancelled_before_dispatch')
                return
            record['runner'] = self._loop.create_task(self._invoke(record), name='compiler-recipe')
            try:
                receipt = await asyncio.shield(record['runner'])
            except asyncio.CancelledError:
                if not record['runner'].done():
                    raise  # Never turn cancellation of this owner into a joined runner.
                if not record['entered_runner']:
                    record['result'] = self._terminal(record, 'cancelled_before_dispatch')
                    return
                receipt = self._read_receipt(recipe)
                if receipt.get('status') != 'cancelled':
                    raise ValueError('Cancelled runner lacks its actual cancellation receipt')
            record['receipt'] = deepcopy(receipt)
            record['result'] = self._project(record, receipt)
        except BaseException as error:
            record['error'] = error
            record['owner'] = getattr(error, 'owner', None)
            if isinstance(error, RecipeCleanupError):
                record['receipt'] = getattr(error, 'receipt', None)
            # Any exception after runner entry can conceal an effect or a lost
            # receipt. Preserve the original exception/owner for host cleanup.
            record['unknown'] = record['entered_runner']
            record['result'] = self._terminal(record, 'outcome_unknown' if record['unknown'] else 'preparation_failed',
                                              dispatched=None if record['unknown'] else False)

    @staticmethod
    def _read_receipt(recipe):
        path = recipe.run / 'receipt.json'
        if _plain(path).st_size > 131072:
            raise ValueError('Recipe receipt exceeds its bound')
        with path.open('rb') as stream:
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise ValueError('Recipe receipt exceeds its bound')
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)

    def _diagnostics(self, recipe):
        result = []
        redactions = [self._capability, *(value for _, value in recipe.environment if value)]
        redactions.extend(str(path) for path in (recipe.source, recipe.run,
            recipe.cmake.path.parent, recipe.ctest.path.parent, recipe.compiler.path.parent, recipe.ninja.path.parent))
        for stage in STAGES:
            path = recipe.run / (stage + '.log')
            if not path.exists():
                continue
            size = _plain(path).st_size
            with path.open('rb') as stream:
                stream.seek(max(0, size - 4096))
                raw = stream.read(4096)
            if size > 4096:
                raw = raw.partition(b'\n')[2]  # Never expose a secret cut mid-line at the tail boundary.
            text = raw.decode('utf-8', errors='replace')
            text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
            text = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)
            for secret in sorted(set(redactions), key=len, reverse=True):
                for spelling in {secret, secret.replace('\\', '/')}:
                    text = re.sub(re.escape(spelling), '[redacted]', text, flags=re.IGNORECASE)
            result.append({'stage': stage, 'text': text[:4096], 'truncated': size > len(raw)})
        return result

    def _project(self, record, receipt):
        recipe = record['recipe']
        if (type(receipt) is not dict or receipt.get('schema') != 'compiler-recipe.v1'
                or receipt != self._read_receipt(recipe)
                or receipt.get('task_deadline') != self.task_deadline
                or type(receipt.get('deadline')) not in (int, float)
                or not math.isfinite(receipt['deadline']) or receipt['deadline'] > self.task_deadline
                or receipt.get('status') not in {'passed', 'failed', 'interrupted', 'timed_out', 'cancelled'}
                or type(receipt.get('passed')) is not bool
                or receipt['passed'] != (receipt['status'] == 'passed')
                or receipt.get('owned_processes_exited') is not True
                or 'cleanup_error' in receipt or 'release_error' in receipt
                or type(receipt.get('children')) is not list
                or any(child.get('joined') is not True or type(child.get('exit_code')) is not int
                       for child in receipt['children'])
                or type(receipt.get('stages')) is not list
                or any(row.get('stage') not in STAGES for row in receipt['stages'])):
            raise ValueError('Recipe result lacks exact confirmed terminal evidence')
        result = self._terminal(record, receipt['status'],
                                dispatched=any(c.get('command_delivered') is True for c in receipt['children']))
        result.update(passed=receipt['passed'], receipt_sha256=hashlib.sha256((recipe.run / 'receipt.json').read_bytes()).hexdigest(),
                      stages=[{k: row[k] for k in ('stage', 'exit_code') if k in row} for row in receipt['stages']])
        if receipt['passed']:
            for key in ('artifact_sha256', 'test_report_sha256'):
                if type(receipt.get(key)) is not str or not re.fullmatch('[0-9a-f]{64}', receipt[key]):
                    raise ValueError('Successful recipe lacks artifact identity')
            if receipt.get('tests_passed') != list(recipe.expected_tests):
                raise ValueError('Successful recipe tests differ')
            result.update({key: receipt[key] for key in ('artifact_sha256', 'artifact_bytes', 'test_report_sha256', 'tests_passed')})
        else:
            result['diagnostics'] = self._diagnostics(recipe)
        return result

    def interrupt(self, operation_id=None):
        """Host authority only. Interrupt owned runners once; never cancel HTTP tasks."""
        self._owner()
        rows = self._records.values() if operation_id is None else [self._records[operation_id]]
        for record in rows:
            record['interrupted'] = True
            task = record['runner']
            if task is not None and not task.done() and not record['cancel_sent']:
                record['cancel_sent'] = True
                task.cancel()

    def obligations(self):
        """Private host references, including the original unknown cleanup owner."""
        self._owner()
        return tuple({'operation_id': key, 'task': row['task'], 'runner': row['runner'],
                      'error': row['error'], 'owner': row['owner'], 'receipt': row['receipt']}
                     for key, row in self._records.items())

    def lifecycle(self):
        self._owner()
        pending = sum(not row['task'].done() or row['runner'] is not None and not row['runner'].done()
                      for row in self._records.values())
        unknown = sum(row['unknown'] for row in self._records.values())
        return {'accepting': not self._closing, 'operations': len(self._records),
                'pending': pending, 'unknown': unknown, 'closed': self._closing and not pending and not unknown}

    async def close(self, *, timeout=2):
        """Fence new work, interrupt owned recipes, retain unresolved joins."""
        self._owner()
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError('Bounded compiler close wait required')
        self._closing = True
        self.interrupt()
        tasks = [task for row in self._records.values() for task in (row['task'], row['runner']) if task is not None]
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
        return self.lifecycle()
