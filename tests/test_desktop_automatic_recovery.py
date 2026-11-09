# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Milestone 2: Automatic Desktop Tool Recovery (FEAT-RECOV-04).

Covers UT-M2-01 through UT-M2-09:
- UT-M2-01: Compiler recipe automatic recovery on worker exit 86.
- UT-M2-02: Video recipe automatic recovery on worker exit 86.
- UT-M2-03: Clean worker exit (code 0) skips recovery hook.
- UT-M2-04: Worker exit during stop_requested skips recovery hook.
- UT-M2-05: In-flight or failed host tool raises ValueError, falling through to RecoveryStop.
- UT-M2-06: DesktopControlLifecycle.replace_recovered_worker accepts active demand and commits.
- UT-M2-07: DesktopComposition.compiler_launch_args generation & retirement bookkeeping.
- UT-M2-08: Monotonic deadline exhaustion (< 5.0s remaining) aborts recovery.
- UT-M2-09: Max attempts exhaustion aborts recovery.
"""
import asyncio
from copy import deepcopy
import json
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / 'src', ROOT / 'tests'):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from adaptive_inference.desktop import composition as comp
from adaptive_inference.desktop.desktop_controls import DesktopControlLifecycle, PreparedTask
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.service_stop import WorkerStopBinding, RecoveryStop
from adaptive_inference.execution_clock import execution_now, CLOCK_ID
from adaptive_inference.desktop.installation import sha
from adaptive_inference.task_store import TaskStore


class Child:
    def __init__(self, pid=41, code=None):
        self.pid = pid
        self.code = code
        self.done = threading.Event()
        self.waits = 0
        if code is not None:
            self.done.set()

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.waits += 1
        if timeout == 0:
            if not self.done.is_set():
                raise TimeoutError('Child still running')
            return self.code
        if not self.done.wait(timeout if timeout is not None else 3):
            raise TimeoutError('Fixture child not released')
        return self.code

    def finish(self, code):
        self.code = code
        self.done.set()

    def kill(self):
        raise AssertionError('No product kill')

    def terminate(self):
        raise AssertionError('No product terminate')


def make_case(root, *, video=False):
    c = object.__new__(comp.DesktopComposition)
    c.root = root / 'run'
    c.root.mkdir(parents=True, exist_ok=True)
    c.work = c.root / 'work'
    c.work.mkdir(parents=True, exist_ok=True)
    c.handles = []
    c.logs = []
    c.waits = {}
    c.result = {'schema': 'adaptive.desktop.windows-orders.result.v1', 'clean_stop': False,
                'task_completed': False, 'execution_expired': False,
                'model': comp.MODEL, 'quality': deepcopy(comp.QUALITY)}
    c.worker_exit_verified = False
    c.continuation = None
    c.handover = None
    c.compiler_kind = 'video' if video else 'compiler'
    c.compiler_bindings = {}
    c.compiler_bindings_history = []
    c.compiler_generations = {}
    c.recovery_records = {}
    c.worker_replacements_count = 0
    c.compiler_native_reader = None
    c.profile = SimpleNamespace(compiler=object() if not video else None, video=object() if video else None)
    c.task_spec_path = None
    c.first_ready = c.work / 'controller-ready-1.json'
    c.host_epoch = 'epoch-test-1'
    c.stop_id = 'stop-init-1'
    c.saved_task = None
    c.saved_diagnostics = None
    c.saved = None
    c.reopen_context = None
    c.qualification_hold_after_report = False
    c.box = SimpleNamespace(snapshot=mock.Mock())
    c.capability = object()
    c.worker_cap = object()
    c.fence = mock.Mock()
    return c


class AutomaticDesktopRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.case = make_case(self.root)
        from test_compiler_task_spec import compiler_data
        from adaptive_inference.task_spec import TaskSpec
        spec = TaskSpec(compiler_data())
        self.case.plan = {
            'base_python': os.path.abspath(comp.sys.executable),
            'gateway': 'http://127.0.0.1:8000/v1',
            'task_spec': spec.data,
            'task_spec_sha256': spec.sha256
        }
        self.case.identity = SimpleNamespace(task_id='task-auto-recov-01', registration_id='reg-01')
        self.case.original = SimpleNamespace(
            prompt='Build harness',
            metadata={'deadline_clock': CLOCK_ID},
            max_attempts=4,
            state={'messages': [{'role': 'user', 'content': 'Build harness'}], 'deadline_monotonic': 900.0, 'deadline_clock': CLOCK_ID}
        )

    def _setup_mock_host(self, c, *, bound=True, receipt=None):
        host_mock = SimpleNamespace(
            closing=False, closed=False,
            controller=SimpleNamespace(fault=None, identity={'owner_id': 'ctrl-1'}),
            gateway=SimpleNamespace(instance='inst-1'),
            wait_ready=mock.AsyncMock()
        )
        c.host = host_mock
        c.transport = SimpleNamespace(
            lifecycle=lambda: {'stop_requested': False, 'stop_confirmed': False},
            _stop_task=None
        )
        c.registry = SimpleNamespace(observe=lambda rid: SimpleNamespace(eligible=True))

        bound_state = {'bound': bound}
        compiler_host = SimpleNamespace(
            lifecycle=lambda: dict(bound_state),
            terminal_receipt=mock.AsyncMock(return_value=receipt or {
                'operation_id': 'op-comp-1',
                'tool': 'clang-cl',
                'units': 23,
                'owned_processes_exited': True,
                'returncode': 0
            }),
            retire=mock.AsyncMock(),
            bind=mock.AsyncMock(),
            interrupt=mock.Mock()
        )
        async def fake_retire(timeout=30):
            bound_state['bound'] = False
        compiler_host.retire.side_effect = fake_retire
        c.compiler_host = compiler_host

    async def test_ut_m2_01_worker_exit_86_compiler_recovery(self):
        """UT-M2-01: Worker exits with code 86 while host holds compiler terminal result."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker_1 = Child(pid=101, code=86)
        c.handles = [worker_1]
        c.worker = worker_1
        c.worker_exit_verified = False

        receipt_data = {
            'operation_id': 'op-comp-1',
            'tool': 'clang-cl',
            'units': 23,
            'owned_processes_exited': True,
            'returncode': 0
        }
        self._setup_mock_host(c, bound=True, receipt=receipt_data)

        # Mock TaskStore checkpoint target
        cp_target = SimpleNamespace(
            task_id=c.identity.task_id,
            revision=1,
            max_attempts=4,
            operation={'id': 'op-comp-1', 'kind': 'effect', 'tool': 'clang-cl'},
            requires_reconciliation=True,
            state={'status': 'pending', 'phase': 'tool_running', 'attempts': 1, 'tools': []}
        )
        mailbox_mock = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(target=cp_target, requests=[], demand={'state': 'active'})
        )
        stop_binding = SimpleNamespace(
            worker=worker_1,
            mailbox=mailbox_mock,
            _verify_exit=mock.Mock(return_value='task_completed'),
            run=c.root
        )
        c.stop_binding = stop_binding

        # Mock reconcile step to transition cp_target to repaired
        worker_2 = Child(pid=102, code=None)
        replacement_binding = SimpleNamespace(
            worker=worker_2,
            mailbox=mailbox_mock,
            _capability=object(),
            request_id='stop-req-2',
            _verify_exit=mock.Mock(return_value='task_completed'),
            run=c.root
        )

        def mock_launch(cmd, label):
            if 'reconcile' in label:
                reconciler = Child(pid=201, code=0)
                c.handles.append(reconciler)
                # Repair checkpoint
                cp_target.operation = None
                cp_target.requires_reconciliation = False
                cp_target.state['phase'] = 'ready'
                cp_target.state['status'] = 'pending'
                return reconciler
            elif 'worker' in label:
                # Write bootstrap file for worker 2
                boot_path = c.worker_diagnostics() / f'bootstrap-{worker_2.pid}.json'
                boot_path.parent.mkdir(parents=True, exist_ok=True)
                boot_path.write_text(json.dumps({
                    'pid': worker_2.pid, 'task_id': c.identity.task_id,
                    'registration_id': c.identity.registration_id,
                    'deadline_monotonic': c.deadline,
                    'deadline_clock': CLOCK_ID,
                    'owner_epoch': 'epoch-1'
                }))
                c.handles.append(worker_2)
                return worker_2
            child = Child(pid=301, code=0)
            c.handles.append(child)
            return child

        c.launch = mock.Mock(side_effect=mock_launch)
        def fake_bind_worker_stop():
            c.stop_binding = replacement_binding
            c.worker_cap = replacement_binding._capability
        c.bind_worker_stop = fake_bind_worker_stop
        def fake_replace(expected, cb):
            cb()
            return replacement_binding
        c.facade = SimpleNamespace(
            replace_recovered_worker=mock.Mock(side_effect=fake_replace),
            cooperative_stop=mock.AsyncMock(return_value={'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None})
        )
        c.runtime = SimpleNamespace(
            refresh=mock.AsyncMock(), _transitioning=False,
            prepared=SimpleNamespace(task_id=c.identity.task_id),
            selected_execution=lambda: {'execution_id': c.identity.task_id}
        )
        c.gui = SimpleNamespace(process=Child(pid=42))
        c.original.state['deadline_monotonic'] = c.deadline
        c.checkpoint = mock.Mock(return_value=SimpleNamespace(
            revision=2,
            owner_epoch='epoch-1',
            prompt=c.original.prompt,
            metadata=c.original.metadata,
            state=deepcopy(c.original.state)
        ))

        # Run recovery helper directly
        recovered = await c._try_recover_pending_tool_worker(86)
        self.assertTrue(recovered)
        self.assertIn((101, 'op-comp-1'), c.recovery_records)
        c.compiler_host.terminal_receipt.assert_called_once_with('op-comp-1')
        c.compiler_host.retire.assert_called_once()
        c.facade.replace_recovered_worker.assert_called_once()
        self.assertIs(c.worker, worker_2)
        self.assertIs(c.stop_binding, replacement_binding)

    async def test_ut_m2_02_worker_exit_86_video_recovery(self):
        """UT-M2-02: Worker exits with code 86 while host holds video terminal result."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker_1 = Child(pid=111, code=86)
        c.handles = [worker_1]
        c.worker = worker_1
        c.worker_exit_verified = False

        video_receipt = {
            'operation_id': 'op-vid-99',
            'tool': 'ffmpeg',
            'frames': 90,
            'owned_processes_exited': True,
            'returncode': 0
        }
        self._setup_mock_host(c, bound=True, receipt=video_receipt)

        cp_target = SimpleNamespace(
            task_id=c.identity.task_id,
            revision=1,
            max_attempts=4,
            operation={'id': 'op-vid-99', 'kind': 'effect', 'tool': 'ffmpeg'},
            requires_reconciliation=True,
            state={'status': 'pending', 'phase': 'tool_running', 'attempts': 1, 'tools': []}
        )
        mailbox_mock = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(target=cp_target, requests=[], demand={'state': 'waiting'})
        )
        stop_binding = SimpleNamespace(
            worker=worker_1,
            mailbox=mailbox_mock,
            _verify_exit=mock.Mock(return_value='task_completed'),
            run=c.root
        )
        c.stop_binding = stop_binding

        worker_2 = Child(pid=112, code=None)
        replacement_binding = SimpleNamespace(
            worker=worker_2,
            mailbox=mailbox_mock,
            _capability=object(),
            request_id='stop-req-video-2',
            _verify_exit=mock.Mock(return_value='task_completed'),
            run=c.root
        )

        def mock_launch(cmd, label):
            if 'reconcile' in label:
                reconciler = Child(pid=202, code=0)
                c.handles.append(reconciler)
                cp_target.operation = None
                cp_target.requires_reconciliation = False
                cp_target.state['phase'] = 'ready'
                cp_target.state['status'] = 'pending'
                return reconciler
            elif 'worker' in label:
                boot_path = c.worker_diagnostics() / f'bootstrap-{worker_2.pid}.json'
                boot_path.parent.mkdir(parents=True, exist_ok=True)
                boot_path.write_text(json.dumps({
                    'pid': worker_2.pid, 'task_id': c.identity.task_id,
                    'registration_id': c.identity.registration_id,
                    'deadline_monotonic': c.deadline,
                    'deadline_clock': CLOCK_ID,
                    'owner_epoch': 'epoch-video'
                }))
                c.handles.append(worker_2)
                return worker_2
            child = Child(pid=302, code=0)
            c.handles.append(child)
            return child

        from test_video_task_spec import video_data
        from adaptive_inference.task_spec import TaskSpec
        video_spec = TaskSpec(video_data())
        c.plan['task_spec'] = video_spec.data
        c.plan['task_spec_sha256'] = video_spec.sha256
        c.compiler_kind = 'video'
        c.profile.video = object()
        c.profile.compiler = None

        c.launch = mock.Mock(side_effect=mock_launch)
        def fake_bind_worker_stop():
            c.stop_binding = replacement_binding
            c.worker_cap = replacement_binding._capability
        c.bind_worker_stop = fake_bind_worker_stop
        def fake_replace(expected, cb):
            cb()
            return replacement_binding
        c.facade = SimpleNamespace(
            replace_recovered_worker=mock.Mock(side_effect=fake_replace),
            cooperative_stop=mock.AsyncMock()
        )
        c.runtime = SimpleNamespace(
            refresh=mock.AsyncMock(), _transitioning=False,
            prepared=SimpleNamespace(task_id=c.identity.task_id),
            selected_execution=lambda: {'execution_id': c.identity.task_id}
        )
        c.gui = SimpleNamespace(process=Child(pid=43))
        c.original.state['deadline_monotonic'] = c.deadline
        c.checkpoint = mock.Mock(return_value=SimpleNamespace(
            revision=2,
            owner_epoch='epoch-video',
            prompt=c.original.prompt,
            metadata=c.original.metadata,
            state=deepcopy(c.original.state)
        ))

        recovered = await c._try_recover_pending_tool_worker(86)
        self.assertTrue(recovered)
        self.assertIn((111, 'op-vid-99'), c.recovery_records)
        self.assertEqual(c.recovery_records[(111, 'op-vid-99')]['receipt']['frames'], 90)

    async def test_ut_m2_03_clean_worker_exit_0_skips_recovery(self):
        """UT-M2-03: Clean worker exit (code 0) skips recovery hook."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker = Child(pid=103, code=0)
        c.worker = worker
        self._setup_mock_host(c, bound=True)

        recovered = await c._try_recover_pending_tool_worker(0)
        self.assertFalse(recovered)
        c.compiler_host.terminal_receipt.assert_not_called()

    async def test_ut_m2_04_worker_exit_during_stop_skips_recovery(self):
        """UT-M2-04: Worker exit while stop was requested skips recovery hook."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker = Child(pid=104, code=3)
        c.worker = worker
        self._setup_mock_host(c, bound=True)
        # Stop requested
        c.transport.lifecycle = lambda: {'stop_requested': True, 'stop_confirmed': False}

        recovered = await c._try_recover_pending_tool_worker(3)
        self.assertFalse(recovered)
        c.compiler_host.terminal_receipt.assert_not_called()

    async def test_ut_m2_05_host_tool_in_flight_or_failed_aborts_recovery(self):
        """UT-M2-05: Host tool still in-flight or failed causes terminal_receipt to fail, aborting recovery."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker = Child(pid=105, code=86)
        c.worker = worker
        self._setup_mock_host(c, bound=True)
        # terminal_receipt raises ValueError
        c.compiler_host.terminal_receipt.side_effect = ValueError('Exact joined terminal recipe result is unavailable')

        cp_target = SimpleNamespace(
            task_id=c.identity.task_id,
            revision=1,
            max_attempts=4,
            operation={'id': 'op-comp-inflight', 'kind': 'effect', 'tool': 'clang-cl'},
            requires_reconciliation=True,
            state={'status': 'pending', 'phase': 'tool_running', 'attempts': 1, 'tools': []}
        )
        mailbox_mock = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(target=cp_target, requests=[], demand={'state': 'active'})
        )
        c.stop_binding = SimpleNamespace(worker=worker, mailbox=mailbox_mock)

        recovered = await c._try_recover_pending_tool_worker(86)
        self.assertFalse(recovered)
        # Binding was NOT retired since recovery was aborted
        c.compiler_host.retire.assert_not_called()

    async def test_ut_m2_06_lifecycle_replace_recovered_worker_accepts_active_demand(self):
        """UT-M2-06: DesktopControlLifecycle.replace_recovered_worker accepts active/waiting demand and commits."""
        old_worker = Child(pid=106, code=86)
        old_cap = object()
        prepared = PreparedTask('epoch-host', 'task-lifecycle', 'Objective')

        cp = SimpleNamespace(
            task_id='task-lifecycle',
            revision=2,
            operation=None,
            requires_reconciliation=False,
            owner_epoch=None,
            state={'status': 'pending', 'phase': 'ready', 'messages': [{'role': 'user', 'content': 'Objective'}]}
        )
        snapshot = SimpleNamespace(target=cp, requests=[], demand={'state': 'active'})
        mailbox_mock = SimpleNamespace(snapshot=lambda: snapshot, store=SimpleNamespace(path=':memory:'))

        old_binding = object.__new__(WorkerStopBinding)
        old_binding.worker = old_worker
        old_binding._capability = old_cap
        old_binding._work = None
        old_binding._fault = None
        old_binding.mailbox = mailbox_mock
        old_binding._owner = lambda: None
        old_binding._original = lambda cp: None
        old_binding.deadline = 900.0
        old_binding.run = self.root
        old_binding.model = 'model-1'
        old_binding.quality = {}
        old_binding.request_id = 'stop-1'
        old_binding._requester = object()
        old_binding.original = object()

        gui_mock = SimpleNamespace(session_live=mock.Mock(), window_live=mock.Mock(),
                                   revoke_session=mock.Mock(), join=mock.AsyncMock())
        host_mock = SimpleNamespace(closing=False, closed=False)

        lifecycle = DesktopControlLifecycle(host_mock, prepared, worker_stop=old_binding,
                                            worker_capability=old_cap, gui=gui_mock)

        # Confirm old replace_worker rejects active demand
        with self.assertRaisesRegex(RuntimeError, 'known paused task'):
            lifecycle.replace_worker(old_binding, lambda: None)

        # Confirm replace_recovered_worker succeeds with active demand
        new_worker = Child(pid=107, code=None)
        new_cap = object()
        new_binding = object.__new__(WorkerStopBinding)
        new_binding.worker = new_worker
        new_binding._capability = new_cap
        new_binding._work = None
        new_binding._fault = None
        new_binding.mailbox = mailbox_mock
        new_binding._requester = old_binding._requester
        new_binding.original = old_binding.original
        new_binding.run = old_binding.run
        new_binding.deadline = 900.0
        new_binding.model = old_binding.model
        new_binding.quality = old_binding.quality
        new_binding.request_id = 'stop-2'
        new_binding._loop = lifecycle._loop
        new_binding._thread = lifecycle._thread

        # Attach mock service (HostTaskHandover)
        service_mock = SimpleNamespace(current={}, replace_worker_episode=mock.Mock())
        lifecycle.service = service_mock

        res = lifecycle.replace_recovered_worker(old_binding, lambda: (new_binding, new_cap))
        self.assertIs(res, new_binding)
        self.assertIs(lifecycle.worker_stop, new_binding)
        self.assertIs(lifecycle._worker_capability, new_cap)
        service_mock.replace_worker_episode.assert_called_once_with(new_worker, new_binding, new_cap, 'stop-2')

    async def test_ut_m2_07_compiler_launch_args_retirement_and_generation(self):
        """UT-M2-07: DesktopComposition.compiler_launch_args generation & retirement bookkeeping."""
        c = self.case
        worker = Child(pid=108, code=86)
        c.worker = worker
        c.handles = [worker]
        c.waits[worker] = asyncio.create_task(asyncio.sleep(0, result=86))
        await c.waits[worker]

        from test_compiler_task_spec import compiler_data
        from adaptive_inference.task_spec import TaskSpec
        spec = TaskSpec(compiler_data())
        c.plan = {'base_python': os.path.abspath(comp.sys.executable), 'gateway': 'http://127.0.0.1:8000/v1',
                  'task_spec': spec.data, 'task_spec_sha256': spec.sha256}

        self._setup_mock_host(c, bound=True)
        c.host_epoch = 'epoch-host-7'
        c.compiler_kind = 'compiler'

        # First launch args call
        args_1 = c.compiler_launch_args(c.work, c.plan, execution_id='exec-1', task_id='task-1',
                                       deadline=900.0, diagnostics=c.work)
        self.assertTrue(any('--compiler-binding' in arg for arg in args_1))

        # Second launch args while host is still bound raises RuntimeError
        with self.assertRaisesRegex(RuntimeError, 'cannot be reused'):
            c.compiler_launch_args(c.work, c.plan, execution_id='exec-1', task_id='task-1',
                                   deadline=900.0, diagnostics=c.work)

        # Retire host
        await c.compiler_host.retire()
        self.assertFalse(c.compiler_host.lifecycle()['bound'])

        # Now second launch args succeeds with incremented generation and fresh capability
        args_2 = c.compiler_launch_args(c.work, c.plan, execution_id='exec-1', task_id='task-1',
                                       deadline=900.0, diagnostics=c.work)
        self.assertTrue(any('--compiler-binding' in arg for arg in args_2))
        self.assertEqual(len(c.compiler_bindings_history), 1)
        self.assertEqual(c.compiler_generations[('task-1', 'exec-1')], 1)

    async def test_ut_m2_08_monotonic_deadline_exhaustion_aborts_recovery(self):
        """UT-M2-08: Monotonic deadline exhaustion (< 5.0s remaining) aborts recovery."""
        c = self.case
        # Deadline expired or remaining < 5.0
        c.deadline = execution_now() + 3.0
        worker = Child(pid=109, code=86)
        c.worker = worker
        self._setup_mock_host(c, bound=True)

        cp_target = SimpleNamespace(
            task_id=c.identity.task_id,
            revision=1,
            max_attempts=4,
            operation={'id': 'op-comp-8', 'kind': 'effect', 'tool': 'clang-cl'},
            requires_reconciliation=True,
            state={'status': 'pending', 'phase': 'tool_running', 'attempts': 1, 'tools': []}
        )
        mailbox_mock = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(target=cp_target, requests=[], demand={'state': 'active'})
        )
        c.stop_binding = SimpleNamespace(worker=worker, mailbox=mailbox_mock)

        recovered = await c._try_recover_pending_tool_worker(86)
        self.assertFalse(recovered)
        c.compiler_host.terminal_receipt.assert_not_called()

    async def test_ut_m2_09_max_attempts_exceeded_aborts_recovery(self):
        """UT-M2-09: Repeated worker loss reaching max_attempts aborts recovery."""
        c = self.case
        c.deadline = execution_now() + 600.0
        worker = Child(pid=110, code=86)
        c.worker = worker
        self._setup_mock_host(c, bound=True)

        cp_target = SimpleNamespace(
            task_id=c.identity.task_id,
            revision=1,
            max_attempts=4,
            operation={'id': 'op-comp-9', 'kind': 'effect', 'tool': 'clang-cl'},
            requires_reconciliation=True,
            state={'status': 'pending', 'phase': 'tool_running', 'attempts': 4, 'tools': []}
        )
        mailbox_mock = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(target=cp_target, requests=[], demand={'state': 'active'})
        )
        c.stop_binding = SimpleNamespace(worker=worker, mailbox=mailbox_mock)

        recovered = await c._try_recover_pending_tool_worker(86)
        self.assertFalse(recovered)
        c.compiler_host.terminal_receipt.assert_not_called()

    async def test_ut_m2_10_reopen_context_and_durable_budget_preserved_across_automatic_recovery(self):
        """UT-M2-10: Reopen context and durable execution_budget.v1 are preserved across replacement launch."""
        from adaptive_inference.desktop.execution_budget import (
            BUDGET, create_budget, reopen_budget, tighten_budget, validate_budget,
        )
        c = self.case
        c.deadline = 608.0
        boot_a = 'a' * 64
        boot_b = {'boot_utc': '2026-11-08T12:00:00Z', 'computer_name': 'TEST-HOST'}
        boot_b_digest = rec.digest(boot_b)
        obs0 = {'utc_ns': 1_793_568_000_000_000_000, 'qpc_before': 100.0, 'qpc_after': 102.0}
        obs1 = {'utc_ns': 1_793_568_200_000_000_000, 'qpc_before': 300.0, 'qpc_after': 302.0}
        obs2 = {'utc_ns': 1_793_568_300_000_000_000, 'qpc_before': 10.0, 'qpc_after': 12.0}
        budget = reopen_budget(
            tighten_budget(create_budget(boot_id=boot_a, deadline=1000.0, observation=obs0),
                           boot_id=boot_a, observation=obs1),
            boot_id=boot_b_digest, observation=obs2,
        )
        c.reopen_context = {'boot': boot_b}
        c.saved = {'task_id': c.identity.task_id}
        c.saved_task = c.work
        c.saved_diagnostics = self.root / 'saved-episodes'
        c.saved_diagnostics.mkdir(parents=True, exist_ok=True)
        c.original.state['deadline_monotonic'] = c.deadline
        c.original.state[BUDGET] = deepcopy(budget)

        worker_1 = Child(pid=121, code=86)
        c.handles = [worker_1]
        c.worker = worker_1
        c.waits[worker_1] = asyncio.create_task(asyncio.sleep(0, result=86))
        await c.waits[worker_1]
        self._setup_mock_host(c, bound=True)
        await c.compiler_host.retire()

        launched_commands = []
        def mock_launch(cmd, label):
            launched_commands.append((label, list(cmd)))
            child = Child(pid=122, code=None)
            c.handles.append(child)
            return child

        c.launch = mock.Mock(side_effect=mock_launch)
        def fake_bind_worker_stop():
            c.stop_binding = SimpleNamespace(worker=c.worker, request_id=c.stop_id)
        c.bind_worker_stop = fake_bind_worker_stop
        binding, cap = c.create_replacement_binding()
        self.assertIsNotNone(binding)
        self.assertIsNotNone(cap)
        self.assertEqual(len(launched_commands), 1)
        label, cmd = launched_commands[0]
        self.assertEqual(label, 'worker-2')
        self.assertIn('--execution-boot-id', cmd)
        self.assertEqual(cmd[cmd.index('--execution-boot-id') + 1], boot_b_digest)
        self.assertIn('--diagnostics', cmd)
        self.assertEqual(cmd[cmd.index('--diagnostics') + 1], str(c.saved_diagnostics))
        self.assertIn('--deadline-monotonic', cmd)
        self.assertEqual(float(cmd[cmd.index('--deadline-monotonic') + 1]), c.deadline)
        self.assertEqual(validate_budget(c.original.state[BUDGET]), budget)


if __name__ == '__main__':
    unittest.main()
