# SPDX-License-Identifier: Apache-2.0
"""Private composition of existing host, mailbox, worker and GUI lifecycles.

No process launch, listener creation, credentials, task adoption or new policy.
The trusted caller supplies the exact already-retained worker and GUI records.
"""
import asyncio
from copy import deepcopy
import math
import threading
import time

from adaptive_inference.desktop.control_transport import PreparedTask
from adaptive_inference.desktop.mailbox_runtime import MailboxRuntime
from adaptive_inference.desktop.persistent_host import PersistentDesktopHost
from adaptive_inference.desktop.ui_intent import UIBinding
from adaptive_inference.control_mailbox import execution_outcome


def bounded(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('A finite positive lifecycle deadline is required')
    return value


class ControlledDesktopHost(PersistentDesktopHost):
    """Reuse the existing sequential observer; each UI poll remains retained."""
    def __init__(self, *args, **kwargs):
        if kwargs.get('max_runtime_seconds') is not None:
            raise ValueError('Controlled service lifetime is persistent; qualification watchdog is external')
        super().__init__(*args, **kwargs)
        self.control_runtime = None
        self._control_thread = threading.current_thread()
        self._control_loop = asyncio.get_running_loop()
        self._control_rebinding = False

    def attach_control_runtime(self, runtime):
        if (threading.current_thread() is not self._control_thread
                or asyncio.get_running_loop() is not self._control_loop
                or type(runtime) is not MailboxRuntime or self.control_runtime is not None
                or self.closing or runtime.lifecycle.host is not self):
            raise RuntimeError('Bind one actual control runtime on the original host loop')
        self.control_runtime = runtime

    def snapshot(self):
        value = super().snapshot()
        progress = getattr(self.controller.policy, 'cooperative_progress', None)
        if progress is not None:
            value['cooperative_foreground'] = progress.snapshot()
        return value

    async def _observe_demand(self):
        try:
            while not self.closing:
                if self._control_rebinding:
                    await asyncio.sleep(.05)
                    continue
                await self.controller.refresh_demand()
                if self.closing:
                    break
                if self.control_runtime is not None and not self._control_rebinding:
                    await self.control_runtime.refresh()
                if not self.closing:
                    await asyncio.sleep(.1)
        except BaseException as exc:
            self.demand_error = type(exc).__name__
            self.controller._demand_valid = False
            raise

    def commit_selected_runtime(self, runtime, record, staged, continuation):
        """Synchronous complete rebind while both existing controller locks hold."""
        if (runtime is not self.control_runtime or runtime._continuation is not continuation
                or continuation.composition.host is not self or runtime._pending
                or threading.current_thread() is not self._control_thread
                or asyncio.get_running_loop() is not self._control_loop
                or not self._control_rebinding or not self.controller.lock.locked()
                or not self.controller._demand_lock.locked() or not record['committed']):
            raise RuntimeError('Selected rebind lacks exact quiescent host authority')
        from adaptive_inference.desktop.continuation_host import selection
        registry,mailbox,capability,observation = staged
        selected = selection(record['grant'])
        if (mailbox.registry is not registry or mailbox._capability is not capability
                or observation.snapshot.target.task_id != selected['execution_id']
                or observation.snapshot.target.prompt != runtime.prepared.objective):
            raise RuntimeError('Selected binding does not describe its actual successor')
        continuation.composition.assert_continuation_parked(record['release'])
        runtime._check_observation(observation,execution=selected)
        controller = self.controller
        controller.demand = registry
        controller._demand_rows = ()
        controller._demand_stamp = None
        controller._demand_valid = False
        controller._demand_revisions = {}
        controller._idle_since = None
        runtime.mailbox,runtime._requester = mailbox,capability
        runtime._selection = selected
        runtime._cache = observation
        composition = continuation.composition
        composition.registry,composition.box,composition.capability = registry,mailbox,capability
        composition.identity = record['identity']
        composition.original = observation.snapshot.target
        composition.deadline = record['grant']['deadline_monotonic']
        composition.worker_exit_verified = False
        record['registry'],record['mailbox'],record['requester'] = registry,mailbox,capability
        record['original'] = observation.snapshot.target


class DesktopControlLifecycle:
    """One prepared-task session, no automatic reopening or task replacement.

    The launch callback binds the current GUI before its private ready ACK.
    Product Stop waits the supplied safe worker result and actual GUI cleanup,
    then invokes the existing native host close. Transport teardown is separate.
    """
    def __init__(self, host, prepared, *, worker_stop, worker_capability, gui,
                 shutdown_timeout_s=120, clock=time.monotonic):
        if type(prepared) is not PreparedTask or type(worker_capability) is not object:
            raise TypeError('Exact prepared task and private worker capability required')
        for target, names in ((worker_stop, ('request_stop', 'join')),
                              (gui, ('session_live', 'window_live', 'revoke_session', 'join'))):
            if any(not callable(getattr(target, name, None)) for name in names):
                raise TypeError('Explicit retained lifecycle methods required')
        if not callable(clock):
            raise TypeError('Monotonic clock required')
        self.host, self.prepared, self.worker_stop, self.gui = host, prepared, worker_stop, gui
        self._worker_capability = worker_capability
        self.timeout = bounded(shutdown_timeout_s, 600)
        self.clock = clock
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self.binding = None
        self._session_closed = self._fenced = False
        self._wake = self._stop = None
        self._joins = []
        self._faults = set()
        self.worker_receipt = self.gui_receipt = self.native_receipt = None
        self._worker_bindings = [(worker_stop, worker_capability)]
        self._replacement_pending = False
        self.worker_replacements = []
        self.selected_transitions = []
        self._selected = self._selection_coordinator = None

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise RuntimeError('Desktop control belongs to the original host loop/thread')

    def replace_worker(self, expected, create_replacement_binding):
        """Trusted synchronous replacement after the harness's safe restart join.

        No await may separate precheck, retained launch, construction and commit.
        The callback must retain Popen before diagnostics, including on failure,
        and return (WorkerStopBinding, private capability) for that exact child.
        This method never launches by PID, signals a process or retries a failure.
        The harness owns failed-launch cleanup through its existing retained list.
        """
        self._owner()
        from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding
        if (expected is not self.worker_stop or type(expected) is not WorkerStopBinding
                or self._worker_capability is not expected._capability
                or self._fenced or self._stop is not None or self._replacement_pending
                or self._faults or self.host.closing or self.host.closed
                or expected._work is not None or expected._fault is not None
                or not callable(create_replacement_binding)):
            raise RuntimeError('Replacement requires the exact current unfenced worker binding')
        expected._owner()
        code = expected.worker.poll()
        if type(code) is not int or expected.worker.wait(timeout=0) != code:
            raise RuntimeError('The exact previous worker must already have exited and joined')
        snapshot = expected.mailbox.snapshot()
        expected._original(snapshot.target)
        if (snapshot.target.task_id != self.prepared.task_id
                or execution_outcome(snapshot.target.state) is not None
                or snapshot.target.state['status'] != 'pending'
                or snapshot.target.operation is not None or snapshot.target.requires_reconciliation
                or snapshot.demand is None or snapshot.demand['state'] != 'paused'):
            raise RuntimeError('Replacement requires the same known paused task')
        # Failure after child creation must never let the old binding authorize
        # native close. Retain this obligation before calling fallible launch.
        record = {'previous_binding': expected, 'previous_exit_code': code,
                  'worker': None, 'binding': None, 'capability': None, 'committed': False}
        self.worker_replacements.append(record)
        self._replacement_pending = True
        try:
            replacement, capability = create_replacement_binding()
            record['binding'], record['capability'] = replacement, capability
            if type(replacement) is WorkerStopBinding:
                record['worker'] = replacement.worker
            if (type(replacement) is not WorkerStopBinding or type(capability) is not object
                    or replacement._capability is not capability
                    or replacement._loop is not self._loop or replacement._thread is not self._thread
                    or replacement._work is not None or replacement._fault is not None
                    or replacement.mailbox is not expected.mailbox
                    or replacement._requester is not expected._requester
                    or replacement.original is not expected.original or replacement.run != expected.run
                    or replacement.deadline != expected.deadline or replacement.model != expected.model
                    or replacement.quality != expected.quality
                    or any(replacement.worker is old.worker or replacement.request_id == old.request_id
                           or capability is old_cap for old, old_cap in self._worker_bindings)
                    or any(row['request_id'] == replacement.request_id for row in snapshot.requests)):
                raise RuntimeError('Replacement changed task accounting or reused a worker/Stop identity')
            # Owner-loop callbacks cannot interleave here, but reject reentrant
            # Stop/fencing initiated by a trusted callback before committing.
            if self._fenced or self._stop is not None or self.host.closing or self.host.closed:
                raise RuntimeError('Stop won before replacement commit')
            self._worker_bindings.append((replacement, capability))
            self.worker_stop, self._worker_capability = replacement, capability
            self.worker_receipt = None
            record['committed'] = True
            self._replacement_pending = False
            return replacement
        except BaseException as primary:
            self._faults.add('worker_replacement_failed')
            try:
                self.fence_admission()
            except BaseException as cleanup:
                raise BaseExceptionGroup('Worker replacement and admission fence failed', [primary, cleanup])
            raise

    def bind_window(self, binding, verifier, bootstrap):
        """Trusted launch callback only; network requests cannot supply these."""
        self._owner()
        if (self._fenced or self.binding is not None or self._session_closed
                or type(binding) is not UIBinding or binding.host_epoch != self.prepared.host_epoch
                or binding.task_id != self.prepared.task_id or bootstrap.host_epoch != binding.host_epoch
                or bootstrap.task_id != binding.task_id or bootstrap.session_id != binding.session_id
                or bootstrap.objective != self.prepared.objective or self.gui.binding != binding
                or self.gui.verifier is not verifier):
            raise RuntimeError('Retained launcher/session binding mismatch')
        self.binding = binding

    def select_execution(self, record, coordinator):
        """Retain committed/no-child obligation before any fallible staging."""
        self._owner()
        if not record['committed'] or record['grant'] is None or record in self.selected_transitions:
            raise RuntimeError('Exact new committed selection required')
        self.selected_transitions.append(record)
        self._selected,self._selection_coordinator = record,coordinator
        self.worker_receipt = None

    def bind_selected_worker(self, record, binding, capability):
        self._owner()
        from adaptive_inference.desktop.continuation_host import SelectedWorkerStopBinding
        if (record is not self._selected or type(binding) is not SelectedWorkerStopBinding
                or binding.worker is not record['child'] or binding.mailbox is not record['mailbox']
                or binding.grant != record['grant'] or binding._capability is not capability
                or binding._loop is not self._loop or binding._thread is not self._thread
                or any(binding.worker is previous.worker for previous,_ in self._worker_bindings)):
            raise RuntimeError('Selected binding does not own its retained child')
        record['binding'],record['capability'] = binding,capability
        self._worker_bindings.append((binding,capability))
        self.worker_stop,self._worker_capability = binding,capability
        self.worker_receipt = None

    def session_is_live(self, session_id):
        self._owner()
        return (not self._session_closed and self.binding is not None
                and session_id == self.binding.session_id
                and self.gui.session_live(session_id) is True)

    def window_ready(self, session_id):
        self._owner()
        if (self._fenced or not self.session_is_live(session_id)
                or self.gui.window_live(session_id) is not True):
            return None
        return self.binding

    def window_closed(self, session_id):
        """Never wait here: the child needs this reply before its thread can exit."""
        self._owner()
        if self.binding is None or self.binding.session_id != session_id:
            raise RuntimeError('Cannot revoke a different session')
        if not self._session_closed:
            self._session_closed = True
            self.gui.revoke_session(session_id)

    def verify_current(self, binding):
        self._owner()
        if type(binding) is not UIBinding or binding != self.binding or not self.session_is_live(binding.session_id):
            return None
        return self.gui.verifier.verify_current(binding)

    def status(self):
        self._owner()
        host, controller = self.host, self.host.controller
        if (self._faults or controller.fault is not None or host.primary_error is not None
                or host.cleanup_error is not None or host.demand_error is not None):
            return {'host_phase': 'fault', 'waiting_reason': 'unknown'}
        if host.closed:
            return {'host_phase': 'closed', 'waiting_reason': None}
        if self._fenced or host.closing:
            return {'host_phase': 'stopping', 'waiting_reason': 'stop_requested'}
        state = controller.state
        if state == 'uninitialized':
            return {'host_phase': 'starting', 'waiting_reason': 'unknown'}
        if state == 'restoring':
            return {'host_phase': 'restoring', 'waiting_reason': 'resources'}
        if controller():
            return {'host_phase': 'ready', 'waiting_reason': None}
        reason = controller.policy.reason
        if reason in ('host_memory_pressure', 'host_cpu_pressure', 'cooperative_host_cpu_unavailable'):
            waiting = 'resources'
        elif reason in ('foreground_activity', 'foreground_recovery_margin', 'foreground_recovery_dwell'):
            waiting = 'foreground'
        elif state == 'parked' and reason == 'foreground_clear':
            waiting = 'resources'
        elif reason == 'cooperative_clear':
            waiting = 'resources'
        elif reason.startswith('cooperative_'):
            waiting = 'foreground'
        else:
            waiting = 'unknown'
        return {'host_phase': 'parked', 'waiting_reason': waiting}

    def fence_admission(self):
        self._owner()
        if self._fenced:
            return
        self._fenced = True
        # These existing owner-loop latches are checked by actual acquire,
        # capacity and observer/drive paths. No worker command is appended yet.
        self.host.closing = True
        self.host.phase = 'closing'
        self.host.gateway.scheduler.closing = True
        self._wake = self._loop.create_task(self.host.gateway.scheduler.close())
        self._wake.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    async def cooperative_stop(self):
        self._owner()
        if self._stop is None:
            self.fence_admission()
            self._stop = self._loop.create_task(self._finish_stop())
        return deepcopy(await asyncio.shield(self._stop))

    async def _wait_worker(self, deadline):
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                return
            value = await self.worker_stop.join(timeout=min(30, remaining))
            self.worker_receipt = deepcopy(value)
            if value.get('worker_joined') is True or value.get('fault') is not None:
                return
            await asyncio.sleep(0)

    async def _wait_gui(self, deadline):
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                return
            value = await self.gui.join(timeout_s=min(30, remaining))
            self.gui_receipt = deepcopy(value)
            if value.get('closed') is True or value.get('faults'):
                return
            await asyncio.sleep(0)

    def _worker_safe(self):
        value = self.worker_receipt
        return (not self._replacement_pending and type(value) is dict and value.get('worker_joined') is True
                and value.get('safe_checkpoint') is True and value.get('uncertain') is False
                and value.get('fault') is None
                and value.get('outcome') in ('service_stopped', 'task_completed', 'task_cancelled', 'paused_budget_expired',
                                             'selected_not_launched'))

    def _gui_safe(self):
        value = self.gui_receipt
        return (type(value) is dict and value.get('closed') is True and value.get('faults') == []
                and value.get('startup_complete') is True and value.get('startup_aborted') is False
                and value.get('child_retained') is True and value.get('child_exit_observed') is True
                and type(value.get('child_exit_code')) is int and value['child_exit_code'] == 0
                and type(value.get('pending_pipe_operations')) is int and value['pending_pipe_operations'] == 0
                and all(value.get(key) is True for key in ('pipe_threads_joined', 'pipe_handles_closed',
                    'verifier_handle_closed', 'process_handle_closed', 'session_revoked', 'authentication_revoked')))

    def _receipt(self):
        native = self.native_receipt
        closed = (type(native) is dict and native.get('closed') is True)
        return {'worker_joined': bool(not self._replacement_pending and self.worker_receipt
                                      and self.worker_receipt.get('worker_joined') is True),
                'host_closed': closed,
                'uncertain': not (self._worker_safe() and self._gui_safe() and closed) or bool(self._faults),
                'fault': sorted(self._faults)[0] if self._faults else None}

    async def _finish_stop(self):
        deadline = self.clock() + self.timeout
        try:
            await asyncio.shield(self._wake)
            if self._replacement_pending:
                # A replacement may exist without a constructed Stop binding.
                # Its retained exceptional cleanup must run; the old worker's
                # receipt cannot authorize native cleanup or clean product Stop.
                self._faults.add('worker_replacement_unbound')
                return self._receipt()
            # MailboxRuntime invokes us only after already accepted DB work;
            # appending this final Pause earlier would race a pending Resume.
            if self._selected is not None and self._selected['binding'] is None:
                self.worker_receipt = await asyncio.to_thread(self._selection_coordinator.verify_unlaunched,self._selected)
                self._joins = [self._loop.create_task(self._wait_gui(deadline))]
            else:
                self.worker_stop.request_stop(self._worker_capability)
                self._joins = [self._loop.create_task(self._wait_worker(deadline)),
                               self._loop.create_task(self._wait_gui(deadline))]
            await asyncio.gather(*(asyncio.shield(task) for task in self._joins), return_exceptions=False)
            if not self._worker_safe():
                self._faults.add('worker_stop_unconfirmed')
            if not self._gui_safe():
                self._faults.add('gui_close_unconfirmed')
            if self._faults:
                return self._receipt()
            remaining = deadline - self.clock()
            if remaining < 1:
                self._faults.add('shutdown_deadline')
                return self._receipt()
            self.native_receipt = await self.host.close(timeout_s=min(600, remaining))
            if (type(self.native_receipt) is not dict or self.native_receipt.get('closed') is not True
                    or not {'primary_error', 'cleanup_error', 'controller_fault'} <= self.native_receipt.keys()
                    or any(self.native_receipt.get(key) is not None for key in
                           ('primary_error', 'cleanup_error', 'controller_fault'))):
                self._faults.add('native_close_unconfirmed')
        except BaseException:
            self._faults.add('desktop_stop_failed')
            raise
        return self._receipt()
