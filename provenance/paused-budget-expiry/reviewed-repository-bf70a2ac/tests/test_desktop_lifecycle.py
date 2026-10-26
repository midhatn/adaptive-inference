"""Lifecycle and shutdown races; real Scheduler, fake native/GUI/worker joins."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest

from adaptive_inference.config import Config
from adaptive_inference.scheduler import Scheduler, AdmissionError
from adaptive_inference.desktop.control_transport import PreparedTask
from adaptive_inference.desktop.ui_intent import UIBinding
from adaptive_inference.desktop.desktop_controls import DesktopControlLifecycle, ControlledDesktopHost


def worker_receipt():
    return dict(worker_joined=True, safe_checkpoint=True, outcome='service_stopped',
                exit_code=4, uncertain=False, fault=None)


def gui_receipt():
    return dict(startup_complete=True, startup_aborted=False, child_retained=True,
                child_exit_observed=True, child_exit_code=0, pending_pipe_operations=0,
                pipe_threads_joined=True, pipe_handles_closed=True, verifier_handle_closed=True,
                process_handle_closed=True, session_revoked=True, authentication_revoked=True,
                faults=[], closed=True)


class Worker:
    def __init__(self):
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        self.requests = 0
        self.result = worker_receipt()
        self.joined = False

    def request_stop(self, capability):
        self.requests += 1

    async def join(self, *, timeout):
        self.entered.set()
        await self.release.wait()
        self.joined = True
        return deepcopy(self.result)


class GUI:
    def __init__(self):
        self.binding = UIBinding('host', 'session', 'task', 101, 202, 303)
        self.verifier = SimpleNamespace(verify_current=lambda binding: ('observed', binding))
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        self.alive = self.marker = True
        self.revoked = False
        self.joined = False
        self.result = gui_receipt()

    def session_live(self, session_id):
        return session_id == 'session' and self.alive and not self.revoked

    def window_live(self, session_id):
        return self.session_live(session_id) and self.marker

    def revoke_session(self, session_id):
        assert session_id == 'session'
        self.revoked = True

    async def join(self, *, timeout_s):
        self.entered.set()
        await self.release.wait()
        self.joined = True
        self.alive = False
        self.revoked = True
        return deepcopy(self.result)


class Controller:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.fault = None
        self.state = 'ready'
        self.policy = SimpleNamespace(reason='foreground_clear')

    def __call__(self):
        return self.state == 'ready' and not self.scheduler.closing


class Host:
    def __init__(self, worker, gui):
        self.worker, self.gui = worker, gui
        self.gateway = SimpleNamespace(scheduler=Scheduler(Config()))
        self.controller = Controller(self.gateway.scheduler)
        self.closing = self.closed = False
        self.phase = 'running'
        self.primary_error = self.cleanup_error = self.demand_error = None
        self.closes = 0

    async def close(self, *, timeout_s):
        assert self.worker.joined and self.gui.joined
        self.closes += 1
        self.closed = True
        return dict(closed=True, primary_error=None, cleanup_error=None, controller_fault=None)


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker, self.gui = Worker(), GUI()
        self.host = Host(self.worker, self.gui)
        self.facade = DesktopControlLifecycle(self.host, PreparedTask('host', 'task', 'Original objective'),
            worker_stop=self.worker, worker_capability=object(), gui=self.gui, shutdown_timeout_s=5)
        self.facade.bind_window(self.gui.binding, self.gui.verifier,
            SimpleNamespace(host_epoch='host', task_id='task', session_id='session', objective='Original objective'))

    async def asyncTearDown(self):
        self.worker.release.set()
        self.gui.release.set()
        if self.facade._stop is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self.facade._stop), 2)
            except Exception:
                pass
        if self.facade._wake is not None:
            await self.facade._wake
        self.assertFalse([t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()])

    async def test_immediate_fence_refuses_real_scheduler_without_posting_stop_pause(self):
        self.facade.fence_admission()
        self.assertTrue(self.host.closing)
        self.assertFalse(self.host.controller())
        self.assertEqual(self.worker.requests, 0)
        with self.assertRaises(AdmissionError):
            await self.host.gateway.scheduler.acquire('normal', 1, wait=False)
        await self.facade._wake
        self.assertEqual(self.worker.requests, 0)

    async def test_internal_watchdog_cannot_bypass_worker_and_gui_join_path(self):
        with self.assertRaisesRegex(ValueError, 'watchdog is external'):
            ControlledDesktopHost(max_runtime_seconds=1800)

    async def test_marker_removal_allows_close_auth_but_not_window_readiness(self):
        self.gui.marker = False
        self.assertTrue(self.facade.session_is_live('session'))
        self.assertIsNone(self.facade.window_ready('session'))
        self.facade.window_closed('session')
        self.assertFalse(self.facade.session_is_live('session'))
        self.assertFalse(self.gui.joined)
        self.assertEqual(self.host.closes, 0)
        self.assertEqual(self.worker.requests, 0)
        self.gui.alive = True
        self.gui.revoked = False
        self.assertFalse(self.facade.session_is_live('session'))

    async def test_stop_waits_for_both_actual_obligations_before_native_close(self):
        stop = asyncio.create_task(self.facade.cooperative_stop())
        await self.worker.entered.wait()
        await self.gui.entered.wait()
        self.assertEqual(self.worker.requests, 1)
        self.worker.release.set()
        await asyncio.sleep(.01)
        self.assertEqual(self.host.closes, 0)
        self.assertFalse(stop.done())
        self.gui.release.set()
        result = await asyncio.wait_for(stop, 2)
        self.assertEqual(result, dict(worker_joined=True, host_closed=True, uncertain=False, fault=None))
        self.assertEqual(self.host.closes, 1)
        self.assertEqual(await self.facade.cooperative_stop(), result)
        self.assertEqual(self.worker.requests, 1)

    async def test_cancelled_stop_waiter_does_not_cancel_owned_joins(self):
        waiter = asyncio.create_task(self.facade.cooperative_stop())
        await self.gui.entered.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertFalse(self.facade._stop.cancelled())
        self.assertTrue(all(not task.cancelled() for task in self.facade._joins))
        self.worker.release.set()
        self.gui.release.set()
        result = await self.facade.cooperative_stop()
        self.assertTrue(result['host_closed'])

    async def test_worker_exit_without_safe_checkpoint_refuses_native_cleanup(self):
        self.worker.result.update(safe_checkpoint=False, uncertain=True, fault='worker_checkpoint_unverified')
        self.worker.release.set()
        self.gui.release.set()
        result = await self.facade.cooperative_stop()
        self.assertTrue(result['worker_joined'])
        self.assertFalse(result['host_closed'])
        self.assertTrue(result['uncertain'])
        self.assertEqual(self.host.closes, 0)

    async def test_missing_gui_evidence_does_not_count_as_successful_exit(self):
        self.gui.result.pop('pipe_threads_joined')
        self.worker.release.set()
        self.gui.release.set()
        result = await self.facade.cooperative_stop()
        self.assertEqual(result['fault'], 'gui_close_unconfirmed')
        self.assertFalse(result['host_closed'])
        self.assertEqual(self.host.closes, 0)

    async def test_original_window_binding_cannot_be_replaced(self):
        with self.assertRaises(RuntimeError):
            self.facade.bind_window(self.gui.binding, self.gui.verifier,
                SimpleNamespace(host_epoch='host', task_id='task', session_id='session', objective='Original objective'))
        self.assertIsNone(self.facade.verify_current(None))

    async def test_closing_during_demand_await_does_not_start_forbidden_ui_refresh(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def demand():
            entered.set()
            await release.wait()
        async def ui():
            calls.append('unexpected')
            raise RuntimeError('Forbidden refresh after fence')
        # Exercise the actual subclass observer with explicit fake dependencies.
        host = object.__new__(ControlledDesktopHost)
        host.closing = False
        host.demand_error = None
        host.controller = SimpleNamespace(refresh_demand=demand, _demand_valid=True)
        host.control_runtime = SimpleNamespace(refresh=ui)
        observer = asyncio.create_task(host._observe_demand())
        await entered.wait()
        host.closing = True
        release.set()
        await asyncio.wait_for(observer, 1)
        self.assertEqual(calls, [])
        self.assertIsNone(host.demand_error)
        self.assertTrue(host.controller._demand_valid)


if __name__ == '__main__':
    unittest.main()
