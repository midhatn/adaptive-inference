# SPDX-License-Identifier: Apache-2.0
"""Private composition of reviewed M1 host and M2 components; no CLI/service installer."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import math
import os
import time
import traceback

from aiohttp import web
from adaptive_inference.handoff import HandoffController, ToolRequirements
from adaptive_inference.demand import DemandRegistry
from adaptive_inference.desktop.cold_start import ColdStartAdapter
from adaptive_inference.desktop.load_feasibility import preview
from adaptive_inference.desktop.windows_host_base import DesktopHost, public_events, save


class LoadAwareController(HandoffController):
    """Only restoration uses the cache preview; tool-capacity checks are unchanged."""
    def __init__(self, adapter, policy, *, demand, restore_requirements,
                 idle_grace_s=30, demand_max_age_s=1, clock=time.monotonic):
        super().__init__(adapter, policy, demand=demand, restore_requirements=restore_requirements,
                         idle_grace_s=idle_grace_s, demand_max_age_s=demand_max_age_s, clock=clock)
        self.load_context = None
        self.load_preview = None

    async def configure_load_plan(self):
        # Exact adapter serialization; package verification and source binding are
        # inherited. No separate native reader or model probe is constructed here.
        context = await self.adapter._call(self.adapter.driver.load_plan_context)
        required = {'config','plan_startup_cache','checked_host_sample','checked_gpu_sample'}
        if type(context) is not dict or set(context) != required or any(
                not callable(context[k]) for k in required - {'config'}):
            raise RuntimeError('Verified load-planner inputs unavailable')
        self.load_context = {**context, 'config': deepcopy(context['config'])}

    def _capacity_fits(self, sample, requirements):
        fits = super()._capacity_fits(sample, requirements)
        if requirements is not self.restore_requirements:
            return fits
        if not fits or self.load_context is None:
            self.load_preview = {'state':'unknown','reason':'profile_floors_or_context_unavailable',
                                 'model_load_proved':False,'resource_reservation':False,
                                 'native_launch_attempted':False}
            return False
        self.load_preview = preview(self.load_context['config'], sample.get('raw_host'),
            sample.get('raw_gpu'), observation_started_at=sample['sampled_at'],
            now_monotonic=self.clock(), now_wall=time.time(), demand_state=self._demand_state(),
            startup_unresolved=(self.adapter._cold_start_error is not None
                                or self.adapter._startup_failure is not None),
            **{k:v for k,v in self.load_context.items() if k != 'config'})
        return self.load_preview['state'] == 'candidate'


class PersistentDesktopHost(DesktopHost):
    """Cold parked service lifecycle, with bounded transitions and no dispatch worker.

    The caller supplies the exact containing job, activity reader, cold adapter,
    registry and qualified-profile floors. This prototype has no discovery,
    permission-changing path, request-to-process endpoint or service installer.
    """
    def __init__(self, owner_config, gateway_config, run, policy, *, demand,
                 restore_requirements, adapter, reader, job, max_runtime_seconds=None,
                 idle_grace_s=30, demand_max_age_s=1, _runner_factory=web.AppRunner,
                 _site_factory=web.TCPSite, runtime_timing=False):
        if type(demand) is not DemandRegistry or not isinstance(adapter, ColdStartAdapter):
            raise TypeError('Explicit canonical demand and reviewed cold adapter required')
        if job is None or reader is None or adapter.job is not job:
            raise ValueError('One explicit containing job and activity reader required')
        if adapter.max_runtime_seconds != max_runtime_seconds:
            raise ValueError('Native owner and service lifetime policy must match')
        controller = LoadAwareController(adapter, policy, demand=demand,
            restore_requirements=restore_requirements, idle_grace_s=idle_grace_s,
            demand_max_age_s=demand_max_age_s)
        super().__init__(owner_config, gateway_config, run, policy,
            max_runtime_seconds=max_runtime_seconds, _adapter=adapter, _reader=reader,
            _job=job, _controller=controller, runtime_timing=runtime_timing)
        if runtime_timing:
            self.controller.on_verified_owner = self.gateway.activate_runtime
        self.demand_task = None
        self.setup_task = None
        self.demand_error = None
        self.primary_error = None
        self.cleanup_error = None
        self._close_work = None
        self._runner_factory, self._site_factory = _runner_factory, _site_factory

    @staticmethod
    def _diagnostic(exc):
        return {'type':type(exc).__name__,'message':str(exc),
                'traceback':''.join(traceback.format_exception(exc))}

    def snapshot(self):
        row = super().snapshot()
        row.update(service_lifetime_seconds=self.max_runtime,
            launch_intent=deepcopy(self.adapter.launch_intent),
            load_preview=deepcopy(self.controller.load_preview),
            demand_observer_error=self.demand_error,
            primary_error=self.primary_error, cleanup_error=self.cleanup_error)
        return row

    async def _observe_demand(self):
        try:
            while not self.closing:
                # Controller's single lock serializes this with step's before/
                # after-start reads. Age begins before the SQLite read. Never
                # cancel/forget that read on shutdown; the host retains this task.
                await self.controller.refresh_demand()
                await asyncio.sleep(.1)
        except BaseException as exc:
            self.demand_error = type(exc).__name__
            self.controller._demand_valid = False
            raise

    async def _drive(self):
        try:
            while not self.closing:
                await self.controller.step()
                save(self.run / 'status.json', self.snapshot())
                await asyncio.sleep(.1)
        except BaseException as exc:
            self.primary_error = self.primary_error or self._diagnostic(exc)
            save(self.run / 'status.json', self.snapshot())
            raise

    def _setup_open(self):
        if self.closing:
            raise RuntimeError('Cold setup was fenced by shutdown')

    async def _setup_service(self):
        self._prepare_job()  # Before any native/worker child could exist.
        self._watchdog(asyncio.get_running_loop())  # None means no service timer.
        self._start_activity(asyncio.get_running_loop())
        self._setup_open()
        await self.controller.initialize(parked=True)
        self._setup_open()
        await self.controller.configure_load_plan()
        self._setup_open()
        self.runner = self._runner_factory(self.app, shutdown_timeout=120)
        await self.runner.setup()
        self._setup_open()
        self.site = self._site_factory(self.runner, self.config.host, self.config.port)
        await self.site.start()
        self._setup_open()
        self.demand_task = asyncio.create_task(self._observe_demand(), name='persistent-demand')
        self.drive_task = asyncio.create_task(self._drive(), name='persistent-transitions')
        self.phase = 'running'
        receipt = {'service_started':True,'model_ready':False,'native_launch_attempted':False,
                   'service_lifetime_seconds':self.max_runtime,
                   'state_at_initialization':'parked',
                   'scope':'Cold listener initialized; current model readiness must be observed separately'}
        save(self.run / 'service-ready.json', receipt)
        save(self.run / 'status.json', self.snapshot())
        return receipt

    def _begin_close(self, timeout_s):
        work = self._close_work
        if work is None or (work.done() and (work.cancelled() or work.exception() is not None)):
            work = asyncio.create_task(self._finish_close(timeout_s), name='persistent-close')
            self._close_work = work
            # Preserve the retained task while also retrieving a background
            # cleanup failure when setup already returned its primary timeout.
            work.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return work

    async def start(self, timeout_s=30):
        if self.started_at is not None or not 1 <= timeout_s <= 600:
            raise ValueError('Start once with a bounded setup deadline')
        self.run.mkdir()
        self.started_at = time.monotonic()
        self.phase = 'cold_verifying'
        self.setup_task = asyncio.create_task(self._setup_service(), name='persistent-setup')
        try:
            return await asyncio.wait_for(asyncio.shield(self.setup_task), timeout_s)
        except BaseException as exc:
            self.startup_exception = exc
            self.primary_error = self._diagnostic(exc)
            self.phase = 'startup_failed'
            self.closing = True
            # The setup task and any serialized native read remain retained.
            # A bounded caller timeout is not a completed cleanup receipt.
            await self.gateway.scheduler.close()
            self._begin_close(120)
            raise

    async def _join(self, task, deadline, label):
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), max(.001, deadline-time.monotonic()))
        except TimeoutError:
            if not task.done():
                raise RuntimeError(label+' still owns work; shutdown remains unresolved')
            # wait_for and the task itself can both raise TimeoutError. A
            # completed task is joined, even when its own operation timed out;
            # preserve that failure and continue only evidence-based cleanup.
            try:
                task.result()
            except BaseException as exc:
                self.primary_error = self.primary_error or self._diagnostic(exc)
        except BaseException as exc:
            # A completed failed transition is still joined. Cleanup may use only
            # its exact retained launch evidence; the primary failure is preserved.
            if not task.done():
                raise
            self.primary_error = self.primary_error or self._diagnostic(exc)

    async def close(self, timeout_s=120):
        if not 1 <= timeout_s <= 600:
            raise ValueError('Shutdown must have a bounded deadline')
        work = self._begin_close(timeout_s)
        cancelled = None
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError as exc:
                cancelled = exc
            except BaseException:
                break
        try:
            return deepcopy(work.result())
        finally:
            if cancelled is not None:
                raise cancelled

    async def _finish_close(self, timeout_s):
        if self.closed:
            return self.close_result
        self.closing, self.phase = True, 'closing'
        deadline = time.monotonic()+timeout_s
        try:
            await self.gateway.scheduler.close()
            if self.controller.tool is not None:
                self.controller.tool.interruption.set()
            await self._join(self.setup_task, deadline, 'Cold setup')
            if self.site is not None:
                await self.site.stop()
                self.site = None
            await self._join(self.demand_task, deadline, 'Demand observation')
            await self._join(self.drive_task, deadline, 'Native transition')
            while self.gateway.scheduler.active is not None or self.controller.tool is not None:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Active inference/tool has not acknowledged shutdown')
                await asyncio.sleep(.05)
            scheduler = self.gateway.scheduler
            if not scheduler.closing or scheduler.pending or scheduler.uncertain:
                raise RuntimeError('Scheduler completion remains unresolved; no normal release')
            # The adapter records intent before its first potential Popen. Never
            # infer obligation from the eager M1 host's started_owner flag.
            if self.adapter.started_owner and self.adapter._cold_start_error is None:
                state = await self.adapter.status()
                known = {os.getpid()}
                if state.get('owner'):
                    known.add(state['owner']['pid'])
                    known.update(p['pid'] for p in state.get('processes',{}).get('active',[]))
                if self.job.active_process_ids() - known:
                    raise RuntimeError('Owned external worker is still alive')
                if state.get('running') is True:
                    await self.adapter.stop(state)
            receipt = await self.adapter.close_parked()
            if self.runner is not None:
                await self.runner.cleanup()
            self.activity_stop.set()
            if self.activity_thread is not None:
                await asyncio.to_thread(self.activity_thread.join, 2)
                if self.activity_thread.is_alive():
                    raise RuntimeError('Foreground sensor did not stop')
            # Recheck after all awaited cleanup. Terminal proof cannot predate a
            # late uncertain dispatch, nor substitute for the exact job evidence.
            if scheduler.active is not None or scheduler.pending or scheduler.uncertain:
                raise RuntimeError('Scheduler became unresolved during final cleanup')
            if self.job.active_process_ids() != {os.getpid()}:
                raise RuntimeError('Owned descendants remain after final cleanup')
            self.closed, self.phase = True, 'closed'
            self.watchdog_done.set()
            self.close_result = {'closed':True, **receipt,
                'primary_error':deepcopy(self.primary_error),
                'controller_fault':self.controller.fault,'qualification_claimed':False,
                'cleanup_error':None,'events':public_events(self.controller.events),
                'scope':'Observed local shutdown; no model task, reboot recovery or M2 acceptance claim'}
            save(self.run / 'result.json', self.close_result)
            save(self.run / 'status.json', self.snapshot())
            return self.close_result
        except BaseException as exc:
            self.cleanup_error = self._diagnostic(exc)
            # Diagnostic write failure cannot replace the root cleanup exception.
            try:
                save(self.run / 'shutdown-error.private.json',
                     {'primary_error':self.primary_error,'cleanup_error':self.cleanup_error,
                      'closed':False,'cleanup_confirmed':False})
            except Exception:
                pass
            raise

