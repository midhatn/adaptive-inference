# SPDX-License-Identifier: Apache-2.0
"""Bind the existing compiler bridge to one selected, retained Hermes worker.

Reuses MailboxRuntime's retained/shielded _database offload and transactional
Mailbox.snapshot observations; no new database owner, ledger or listener.
The injected native reader uses recovery.native_history / Hermes' public
SessionDB getters, in that offload (never a thread-affine connection borrowed
from the event loop). Two equal mailbox snapshots bracket the native read;
they prove observed intent, not a cross-database reservation.

Primary contracts reviewed 2026-11-02; no external implementation copied:
https://docs.python.org/3.11/library/asyncio-task.html#asyncio.to_thread
https://docs.python.org/3.11/library/asyncio-task.html#shielding-from-cancellation
https://docs.python.org/3.11/library/sqlite3.html#sqlite3.connect
https://github.com/NousResearch/hermes-agent/blob/14e1e43a23761b369641208e204365cd6cb9399d/hermes_state_messages.py
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import re
import threading

from aiohttp import web
from adaptive_inference.control_mailbox import execution_outcome
from adaptive_inference.desktop.compiler_bridge import CompilerBridge, ROUTE, _decode, _json
from adaptive_inference.desktop.compiler_recipe import _plain, run_recipe
from adaptive_inference.desktop.compiler_template import CompilerSettings, RECIPE_ID, prepare_cpp_recipe
from adaptive_inference.desktop.execution_budget import BUDGET, validate_budget
from adaptive_inference.desktop.hermes.recovery import digest, task_contract
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.execution_clock import CLOCK_ID, execution_now
from adaptive_inference.task_spec import strict_json

_LINK = 'adaptive_inference.execution_authorization.v1'
_DETAILS = {'name', 'args', 'tool_call_id', 'session_id', 'fingerprint',
            'host_epoch', 'task_id', 'execution_id', 'owner_epoch', 'spec_sha256'}


def _require(condition):
    if not condition:
        raise ValueError('Selected compiler binding is unavailable or changed')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


@dataclass(repr=False)
class _Binding:
    runtime: object
    mailbox: object
    selection: dict
    worker: object
    is_current: object
    is_joined: object
    read_native: object
    root: Path
    deadline: float
    owner: str
    spec: object
    metadata: dict
    bridge: object = None
    close_task: object = None
    error: object = None
    fenced: bool = False


class CompilerHost:
    """Host-loop composition helper; bind only after actual paused ownership.

    is_current_worker(worker) must confirm the captured retained child is both
    selected and live. is_worker_joined(worker) must confirm the actual wait on
    that exact child, not merely PID disappearance. The host owns these hooks.
    Call interrupt BEFORE requesting worker Stop, keep HTTP alive for the worker
    to collect cancellation feedback, then close/join/retire explicitly.
    """
    def __init__(self, controller, settings, *, host_epoch, clock=execution_now,
                 runner=run_recipe):
        _require(type(settings) is CompilerSettings and callable(clock) and callable(runner)
                 and type(host_epoch) is str
                 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', host_epoch))
        self.controller, self.settings, self.host_epoch = controller, settings, host_epoch
        self._clock, self._runner = clock, runner
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self._binding, self._binding_pending = None, False
        self._installed, self._fenced, self._last_clock = False, False, None

    def _owner(self):
        _require(asyncio.get_running_loop() is self._loop and threading.current_thread() is self._thread)

    def _now(self):
        value = self._clock()
        _require(_number(value) and (self._last_clock is None or value >= self._last_clock))
        self._last_clock = value
        return value

    def add_route(self, app):
        self._owner()
        _require(not self._installed and not self._fenced)
        app.router.add_post(ROUTE, self.handle)
        self._installed = True

    async def handle(self, request):
        self._owner()
        binding = self._binding
        if binding is None:
            return web.json_response({'ok': False, 'error': 'compiler_unbound'}, status=409)
        # Closing bridges still answer identical pending/completed polls.
        return await binding.bridge.handle(request)

    def _current(self, binding, *, dispatch=True):
        self._owner()
        runtime = binding.runtime
        _require(not self._fenced and not binding.fenced and self._binding is binding
                 and not runtime._stopping and (not dispatch or not runtime._transitioning)
                 and not runtime._task_retired
                 and runtime.mailbox is binding.mailbox
                 and runtime.prepared.host_epoch == self.host_epoch
                 and runtime.selected_execution() == binding.selection
                 and binding.is_current(binding.worker) is True
                 and binding.is_joined(binding.worker) is False
                 and self._now() < binding.deadline)

    def _checkpoint(self, binding, snapshot, *, dispatch):
        cp, logical = snapshot.target, binding.runtime.prepared.task_id
        link = cp.metadata.get(_LINK)
        if cp.task_id == logical:
            _require(link is None and binding.selection['execution_generation'] == 0)
        else:
            _require(type(link) is dict and link.get('logical_task_id') == logical
                     and link.get('execution_id') == cp.task_id
                     and link.get('execution_generation') == binding.selection['execution_generation'])
        _require(cp.task_id == binding.selection['execution_id'] and cp.metadata == binding.metadata
                 and cp.owner_epoch == binding.owner and not cp.requires_reconciliation
                 and cp.state.get('status') == 'pending'
                 and cp.state.get('deadline_clock') == CLOCK_ID
                 and type(cp.state.get('deadline_monotonic')) in (int, float)
                 and cp.state['deadline_monotonic'] == binding.deadline
                 and execution_outcome(cp.state) is None
                 and task_contract(cp) == binding.spec)
        if BUDGET in cp.state:
            budget = validate_budget(cp.state[BUDGET])
            _require(budget['episode']['deadline'] == binding.deadline and not budget['clean_stop'])
        if dispatch:
            latest = snapshot.requests[-1] if snapshot.requests else None
            _require(snapshot.demand is not None and snapshot.demand['state'] in ('active', 'waiting')
                     and (latest is None or latest['command'] not in ('pause', 'cancel')))
        return cp

    async def bind(self, *, runtime, worker, is_current_worker, is_worker_joined,
                   read_native_history, task_root, capability, task_deadline):
        self._owner()
        _require(self._installed and self._binding is None and not self._binding_pending and not self._fenced
                 and type(runtime) is MailboxRuntime and runtime.prepared.host_epoch == self.host_epoch
                 and worker is not None and all(callable(value) for value in
                     (is_current_worker, is_worker_joined, read_native_history))
                 and type(capability) is str and re.fullmatch('[0-9a-f]{64}', capability)
                 and _number(task_deadline) and self._now() < task_deadline)
        runtime._owner()
        selection, mailbox, root = runtime.selected_execution(), runtime.mailbox, Path(task_root)
        _require(root.is_absolute() and root.resolve() == root
                 and mailbox.store.path == root / 'task.sqlite3')
        self._binding_pending = True
        try:
            def observe():
                _plain(root, directory=True)
                _plain(root / 'work', directory=True)
                return runtime._observe(mailbox)

            def check(observation):
                snapshot = runtime._check_observation(observation, execution=selection)
                cp, spec = snapshot.target, task_contract(snapshot.target)
                _require(not self._fenced and not runtime._stopping
                         and not runtime._task_retired and runtime.mailbox is mailbox
                         and runtime.selected_execution() == selection
                         and is_current_worker(worker) is True and is_worker_joined(worker) is False
                         and self._now() < task_deadline and cp.operation is None
                         and type(cp.owner_epoch) is str and re.fullmatch('[0-9a-f]{32}', cp.owner_epoch)
                         and spec is not None and spec.compiler is not None)
                binding = _Binding(runtime, mailbox, selection, worker, is_current_worker,
                    is_worker_joined, read_native_history, root, task_deadline, cp.owner_epoch,
                    spec, deepcopy(cp.metadata))
                self._checkpoint(binding, snapshot, dispatch=False)
                return binding

            binding = await runtime._database(observe, check)
            _require(not self._fenced and self._binding is None)
            self._binding = binding
            try:
                # Continue binds an actually owned paused worker before Resume
                # and readiness clear its transition. This observation alone
                # never grants dispatch; every _intent keeps dispatch=True.
                self._current(binding, dispatch=False)
                binding.bridge = CompilerBridge(self.controller,
                    {RECIPE_ID: lambda request: self._prepare(binding, request)},
                    capability=capability, task_deadline=task_deadline,
                    validate_binding=lambda request: self._validate(binding, request), runner=self._runner)
            except BaseException:
                self._binding = None
                raise
            return {'host_epoch': self.host_epoch, 'task_id': runtime.prepared.task_id,
                    **selection, 'owner_epoch': binding.owner, 'spec_sha256': binding.spec.sha256,
                    'task_deadline': binding.deadline}
        finally:
            self._binding_pending = False

    async def _intent(self, binding, request):
        self._current(binding)
        _require(_decode(_json(request)) == request)
        expected = {'host_epoch': self.host_epoch, 'task_id': binding.runtime.prepared.task_id,
                    'execution_id': binding.selection['execution_id'], 'owner_epoch': binding.owner,
                    'recipe_id': RECIPE_ID}
        _require(all(request[key] == value for key, value in expected.items())
                 and re.fullmatch('[0-9a-f]{32}', request['operation_id']))

        def read():
            first = binding.runtime._observe(binding.mailbox)
            cp = self._checkpoint(binding, first.snapshot, dispatch=True)
            operation = cp.operation
            _require(type(operation) is dict and operation.get('id') == request['operation_id']
                     and operation.get('kind') == 'effect' and cp.state.get('phase') == 'tool_running')
            details = operation.get('details')
            _require(type(details) is dict and set(details) == _DETAILS
                     and all(details.get(key) == value for key, value in expected.items() if key != 'recipe_id')
                     and details['name'] == 'build_and_test' and details['tool_call_id'] == request['tool_call_id']
                     and details['session_id'] == cp.state.get('session_id')
                     and details['spec_sha256'] == binding.spec.sha256
                     and details['fingerprint'] == digest({'name': 'build_and_test', 'args': details['args']}))
            native = binding.read_native(details['session_id'])
            _require(type(native) is list and native == cp.state.get('native_history'))
            calls = [(row, call) for row in native for call in row.get('tool_calls', [])
                     if call.get('id') == request['tool_call_id']]
            _require(len(calls) == 1 and calls[0][0].get('role') == 'assistant'
                     and calls[0][1].get('type') == 'function'
                     and calls[0][1]['function']['name'] == 'build_and_test'
                     and strict_json(calls[0][1]['function']['arguments']) == details['args']
                     and not any(row.get('role') == 'tool' and row.get('tool_call_id') == request['tool_call_id']
                                 for row in native)
                     and not any(row.get('tool_call_id') == request['tool_call_id'] for row in cp.state['tools']))
            from adaptive_inference.desktop.hermes.compiler_evidence import verify_compiler_evidence
            prior = verify_compiler_evidence(cp, binding.root, native, store_path=binding.mailbox.store.path)
            _require(binding.spec.validate_compiler_args(details['args'], completed_runs=len(prior)).accepted)
            binding.spec.verify_inputs(binding.root / 'work')
            return first, binding.runtime._observe(binding.mailbox), deepcopy(details['args'])

        def check(value):
            self._current(binding)
            first, last, args = value
            a = binding.runtime._check_observation(first, execution=binding.selection)
            b = binding.runtime._check_observation(last, execution=binding.selection)
            _require(a == b)
            return args
        return await binding.runtime._database(read, check)

    async def _validate(self, binding, request):
        try:
            await self._intent(binding, request)
            return True
        except Exception as error:
            binding.error = error  # Private evidence only; never project database/path details.
            return False

    async def _prepare(self, binding, request):
        args = await self._intent(binding, request)

        def prepare():
            root = binding.root / 'compiler'
            root.mkdir(exist_ok=True)
            return prepare_cpp_recipe(self.settings, spec=binding.spec, args=args,
                                      operation_id=request['operation_id'], root=root)

        def check(recipe):
            self._current(binding)
            return recipe
        return await binding.runtime._database(prepare, check)

    def interrupt(self):
        """Fence synchronously; retain the close before the caller joins its worker."""
        self._owner()
        self._fenced = True
        binding = self._binding
        if binding is not None:
            binding.fenced = True
            binding.bridge.interrupt()
            if binding.close_task is None:
                binding.close_task = self._loop.create_task(binding.bridge.close(), name='compiler-host-close')

    async def close(self, *, timeout=2):
        self._owner()
        _require(type(timeout) in (int, float) and 0 < timeout <= 30)
        self.interrupt()
        binding = self._binding
        if binding is not None:
            await asyncio.wait({binding.close_task}, timeout=timeout)
            if binding.close_task.done():
                binding.close_task.result()
        return self.lifecycle()

    async def retire(self, *, timeout=2):
        """Explicitly remove only a joined worker and resolved bridge; never retry."""
        self._owner()
        _require(not self._binding_pending)
        binding = self._binding
        _require(binding is not None)
        await self.close(timeout=timeout)
        _require(binding is self._binding and binding.bridge.lifecycle()['closed']
                 and binding.close_task.done() and binding.is_joined(binding.worker) is True
                 and binding.is_current(binding.worker) is False)
        self._binding = None
        self._fenced = False
        return self.lifecycle()

    def lifecycle(self):
        self._owner()
        binding = self._binding
        return {'bound': binding is not None, 'binding_pending': self._binding_pending,
                'fenced': self._fenced,
                'bridge': None if binding is None else binding.bridge.lifecycle()}

    def obligations(self):
        """Private retained references; no capability or HTTP projection."""
        self._owner()
        binding = self._binding
        return () if binding is None else ({'worker': binding.worker, 'close_task': binding.close_task,
            'binding_error': binding.error, 'operations': binding.bridge.obligations()},)
