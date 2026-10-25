# SPDX-License-Identifier: Apache-2.0
"""Explicit local desktop host; no HTTP endpoint executes processes or tools.

The containing process must be a dedicated worker. Its job owns subsequently
created backend/tool children and is closed by Windows on process death.
"""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import threading
import time
import traceback

from aiohttp import web
from adaptive_inference.config import Config, load_config
from adaptive_inference.gateway import create_app, GATEWAY
from adaptive_inference.handoff import ForegroundPolicy, HandoffController
from adaptive_inference.desktop.native_owner_adapter import NativeOwnerAdapter, sha256

HERE = Path(__file__).resolve().parent
QUALITY = {"max_tokens": 10923, "reasoning_effort": "high", "reasoning_budget_tokens": 8192,
           "experimental_speed_projection": False, "strata_tune": {"pcie_frac": .37}}
MODEL = "qwen3.8-flash-next-iq3_s-adaptive-media-beta"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def public_events(events):
    result = []
    for event in events:
        row = {k: v for k, v in event.items() if k not in ("release",)}
        if "release" in event:
            proof = event["release"]
            row["release"] = {k: proof[k] for k in ("owner_id", "released", "cleanup_confirmed",
                                                    "retained_processes", "confirmed_process_exits", "port_free")}
        result.append(row)
    return result


class DesktopHost:
    def __init__(self, owner_config: dict, gateway_config: Config, run: Path,
                 policy: ForegroundPolicy | None = None, *, max_runtime_seconds=900,
                 _adapter=None, _reader=None, _job=None, _controller=None, runtime_timing=False):
        if max_runtime_seconds is not None and (type(max_runtime_seconds) not in (int, float) or not math.isfinite(max_runtime_seconds) or not 60 <= max_runtime_seconds <= 3600):
            raise ValueError("Dedicated host runtime must be 60 through 3600 seconds")
        gateway_config.validate()
        if (gateway_config.host != "127.0.0.1" or gateway_config.backend_kind != "strata"
                or gateway_config.backend_url != "http://127.0.0.1:18098/v1" or gateway_config.port == 18098):
            raise ValueError("This owned host requires explicit loopback Strata on port 18098")
        self.config, self.owner_config = gateway_config, dict(owner_config)
        self.run = Path(run).absolute()
        if self.run.exists() or not self.run.parent.is_dir() or self.run.parent.resolve() != self.run.parent:
            raise ValueError("Use a new run directory under an existing non-redirected parent")
        self.max_runtime = max_runtime_seconds
        self.adapter = _adapter or NativeOwnerAdapter(**owner_config)
        self.controller = _controller or HandoffController(self.adapter, policy)
        self.app = create_app(gateway_config, capacity=self.controller, runtime_timing=runtime_timing)
        self.gateway = self.app[GATEWAY]
        self.controller.bind_scheduler(self.gateway.scheduler)
        self.job, self.reader = _job, _reader
        self.runner = self.site = None
        self.activity_thread = None
        self.activity_stop = threading.Event()
        self.watchdog_done = threading.Event()
        self.activity = None
        self.activity_error = None
        self.drive_task = None
        self.closing = False
        self.closed = False
        self.started_owner = False
        self.startup_exception = None
        self.started_at = None
        self.close_result = None
        self.phase = "created"
        self._close_lock = asyncio.Lock()

    def _prepare_job(self):
        if self.job is None:
            from adaptive_inference.desktop import owned_job
            self.job = owned_job
        self.job.contain_current_process()

    def _start_activity(self, loop):
        def deliver(row):
            if not self.closed:
                self.activity = row
                self.controller.observe(row)
        def run():
            try:
                from adaptive_inference.desktop.activity import WindowsActivityReader
                reader = self.reader or WindowsActivityReader()
                while not self.activity_stop.is_set():
                    sample = reader.sample()
                    loop.call_soon_threadsafe(deliver, sample)
                    self.activity_stop.wait(.2)
            except BaseException as exc:
                self.activity_error = type(exc).__name__
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(deliver, {"errors": [self.activity_error]})
        self.activity_thread = threading.Thread(target=run, name="desktop-activity", daemon=True)
        self.activity_thread.start()

    def _watchdog(self, loop):
        if self.max_runtime is None:
            return  # Persistent host lifetime; native transitions keep their bounds.
        def run():
            if self.watchdog_done.wait(self.max_runtime):
                return
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self.close(timeout_s=120)))
            if not self.watchdog_done.wait(130):
                # Dedicated owner exit closes its job; no global/name-based kill.
                os._exit(124)
        threading.Thread(target=run, name="desktop-runtime-bound", daemon=True).start()

    def snapshot(self):
        return {"schema": "adaptive.desktop-host.v1", "observed_at": time.time(),
                "host_pid": os.getpid(), "running": not self.closed, "host_phase": self.phase,
                "controller": self.controller.status(), "scheduler": self.gateway.scheduler.status(),
                "activity": self.activity, "activity_error": self.activity_error,
                "events": public_events(self.controller.events),
                "gateway": f"http://127.0.0.1:{self.config.port}/v1",
                "model": MODEL, "quality": QUALITY,
                "owner_id": (self.controller.identity or {}).get("owner_id"),
                "scope": "Cooperative desktop admission and owned process lifecycle; no OS-wide reservation"}

    async def _drive(self):
        try:
            while not self.closing:
                await self.controller.step()
                save(self.run / "status.json", self.snapshot())
                await asyncio.sleep(.1)
        except BaseException as exc:
            self.activity_error = self.activity_error or type(exc).__name__
            save(self.run / "status.json", self.snapshot())
            raise

    async def _startup_status(self):
        while True:
            save(self.run / "status.json", self.snapshot())
            await asyncio.sleep(.5)

    async def _startup_remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self.controller._fail("startup_deadline_exceeded")
            await self.close(timeout_s=120)
            raise TimeoutError("Startup deadline elapsed; the owned backend was closed without admitting work")
        return remaining

    async def start(self, timeout_s=180):
        if self.started_at is not None or not 1 <= timeout_s <= 600:
            raise ValueError("Start once with a bounded deadline")
        self.run.mkdir()
        self.started_at = time.monotonic()
        self._prepare_job()  # Before any child process can be created.
        loop = asyncio.get_running_loop()
        self._watchdog(loop)
        self._start_activity(loop)
        deadline = self.started_at + timeout_s
        self.phase = "verifying_owner"
        save(self.run / "status.json", self.snapshot())
        updates = asyncio.create_task(self._startup_status(), name="desktop-startup-status")
        try:
            state = await self.adapter.status()
            if state.get("running") is not False or state.get("state") not in ("stopped", "failed"):
                raise RuntimeError("Dedicated host refuses to adopt an existing live/uncertain owner")
            self.phase = "waiting_foreground"
            save(self.run / "status.json", self.snapshot())
            while not (self.controller.policy.allowed and self.controller.policy.fresh(time.monotonic())):
                await self._startup_remaining(deadline)
                if self.activity_error:
                    raise TimeoutError("Fresh sustained foreground clearance was not observed")
                await asyncio.sleep(.05)
            await self._startup_remaining(deadline)
            # The adapter finishes an in-progress transition before propagating
            # cancellation. Record ownership intent first so close reconciles it.
            self.started_owner = True
            self.phase = "native_starting"
            save(self.run / "status.json", self.snapshot())
            state = await self.adapter.start()
            await self._startup_remaining(deadline)
            if not state.get("ready") or not state.get("loaded") or state.get("model") != MODEL:
                raise RuntimeError("Initial native owner did not become ready")
            self.phase = "initializing"
            await self.controller.initialize()
            await self._startup_remaining(deadline)
            self.runner = web.AppRunner(self.app, shutdown_timeout=120)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, self.config.host, self.config.port)
            await self.site.start()
            self.drive_task = asyncio.create_task(self._drive(), name="desktop-transitions")
            try:
                receipt = await self.wait_ready(timeout_s=await self._startup_remaining(deadline))
            except TimeoutError:
                self.controller._fail("startup_deadline_exceeded")
                await self.close(timeout_s=120)
                raise
            self.phase = "running"
            save(self.run / "status.json", self.snapshot())
            return receipt
        except BaseException as exc:
            self.startup_exception = exc
            save(self.run / "startup-error.private.json", {
                "type": type(exc).__name__, "message": str(exc),
                "traceback": "".join(traceback.format_exception(exc))})
            if not self.closed:
                self.phase = "startup_failed"
                save(self.run / "status.json", self.snapshot())
            raise
        finally:
            updates.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await updates

    async def wait_ready(self, timeout_s=180):
        if not 0 < timeout_s <= 600:
            raise ValueError("Readiness timeout must be bounded")
        deadline = time.monotonic() + timeout_s
        while not self.controller():
            if self.controller.fault or self.closing or self.activity_error:
                raise RuntimeError("Desktop controller is not available for dispatch")
            if self.drive_task is not None and self.drive_task.done():
                await self.drive_task
                raise RuntimeError("Desktop transition loop stopped")
            if time.monotonic() >= deadline:
                raise TimeoutError("Desktop admission did not become ready")
            await asyncio.sleep(.05)
        if time.monotonic() >= deadline:
            raise TimeoutError("Desktop admission did not become ready before its deadline")
        receipt = {"ready": True, "observed_at": time.time(), "model": MODEL, "quality": QUALITY,
                   "gateway": f"http://127.0.0.1:{self.config.port}/v1",
                   "owner_id": self.controller.identity["owner_id"], "host_pid": os.getpid()}
        save(self.run / "ready.json", receipt)
        return receipt

    async def close(self, timeout_s=120):
        async with self._close_lock:
            if self.closed:
                return self.close_result
            if not 1 <= timeout_s <= 600:
                raise ValueError("Shutdown deadline must be bounded")
            self.closing = True
            self.phase = "closing"
            deadline = time.monotonic() + timeout_s
            await self.gateway.scheduler.close()  # Pending requests cannot dispatch.
            if self.controller.tool is not None:
                self.controller.tool.interruption.set()
            if self.site is not None:
                await self.site.stop()
                self.site = None
            if self.drive_task is not None:
                # No cancellation may abandon an in-flight stop/start thread.
                try:
                    await asyncio.wait_for(asyncio.shield(self.drive_task), max(.01, deadline-time.monotonic()))
                except Exception:
                    if not self.drive_task.done():
                        raise RuntimeError("Native transition still owns shutdown")
            while self.gateway.scheduler.active is not None or self.controller.tool is not None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Active inference/tool did not acknowledge shutdown; no cleanup claim")
                await asyncio.sleep(.05)
            failed_start = await self.adapter.failed_start_status()
            proof = None
            if failed_start is not None:
                save(self.run / "failed-start-cleanup.private.json", failed_start)
                if ((failed_start["process_created"] and not failed_start["owner_exit_confirmed"])
                        or failed_start.get("process_observation_error") or failed_start["port_free"] is not True):
                    raise RuntimeError("Failed startup cleanup is unresolved; no release claimed") from self.startup_exception
                # Exact launch-handle exit is separate from the containing job:
                # children can outlive that process. Never close on a PID guess.
                if self.job.active_process_ids() != {os.getpid()}:
                    raise RuntimeError("Owned descendants remain after failed startup; no release claimed") from self.startup_exception
            else:
                state = await self.adapter.status()
                known = {os.getpid()}
                if state.get("owner"):
                    known.add(state["owner"]["pid"])
                    known.update(row["pid"] for row in state.get("processes", {}).get("active", []))
                if self.job.active_process_ids() - known:
                    raise RuntimeError("An owned external worker is still alive; stop it before closing the host")
                if self.started_owner and state.get("running") is True:
                    proof = await self.adapter.stop(state)
                elif self.started_owner and not state.get("cleanup_confirmed"):
                    raise RuntimeError("Native owner stopped without complete cleanup")
            if self.job.active_process_ids() != {os.getpid()}:
                raise RuntimeError("Owned descendants remain after native shutdown")
            await self.adapter.close(release_parked=True)
            if self.runner is not None:
                await self.runner.cleanup()
            self.activity_stop.set()
            if self.activity_thread is not None:
                await asyncio.to_thread(self.activity_thread.join, 2)
                if self.activity_thread.is_alive():
                    raise RuntimeError("Foreground sensor did not stop")
            self.closed = True
            self.phase = "closed"
            if proof is not None:
                save(self.run / "release.private.json", proof)
            safe_proof = public_events([{"release": proof}])[0]["release"] if proof is not None else None
            self.close_result = {"closed": True, "owned_children_exited": True, "release": safe_proof,
                                 "events": public_events(self.controller.events), "stopped_at": time.time()}
            if failed_start is not None:
                self.close_result.update(outcome="failed_start_cleanup", native_cleanup_confirmed=False,
                                         startup_failed=True)
            save(self.run / "result.json", self.close_result)
            save(self.run / "status.json", self.snapshot())
            self.watchdog_done.set()
            return self.close_result


async def cli(args):
    owner = json.loads(args.owner_config.read_text(encoding="utf-8-sig"))
    host = DesktopHost(owner, load_config(args.gateway_config), args.run,
                       max_runtime_seconds=args.max_runtime_seconds)
    try:
        await host.start(timeout_s=args.start_timeout)
        while not host.closed and time.monotonic()-host.started_at < args.max_runtime_seconds:
            if host.controller.fault or host.activity_error:
                raise RuntimeError("Desktop host fault requires reconciliation")
            if host.drive_task is not None and host.drive_task.done():
                await host.drive_task
                raise RuntimeError("Desktop transition loop ended")
            await asyncio.sleep(.2)
    finally:
        await host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-config", type=Path, required=True)
    parser.add_argument("--gateway-config", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--max-runtime-seconds", type=float, default=900)
    parser.add_argument("--start-timeout", type=float, default=180)
    asyncio.run(cli(parser.parse_args()))


if __name__ == "__main__":
    main()
