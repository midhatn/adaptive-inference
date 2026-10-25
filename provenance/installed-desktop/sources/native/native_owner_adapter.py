"""Async, identity-bound handoff for the preserved Windows Strata owner.

The adapter controls only an explicitly supplied, hash-pinned owner package.
It never invokes competing tools. The caller must first close admission and
drain its own queue, then require the release proof before using capacity.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pin(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Expected a lowercase SHA-256 pin")
    return value


def validate_handoff_config(config):
    if type(config.get("idle_unload_s")) is not int or config["idle_unload_s"] != 0:
        raise RuntimeError("Handoff owner must disable its independent native idle timer (idle_unload_s=0)")


def identity(state):
    """Immutable owner identity; PID alone never authorizes a transition."""
    owner = state.get("owner")
    if not isinstance(owner, dict) or not state.get("owner_id") or not state.get("run"):
        raise RuntimeError("Complete owner identity unavailable")
    if type(owner.get("pid")) is not int or type(owner.get("created_filetime")) is not int or not owner.get("exe"):
        raise RuntimeError("Retained owner creation identity unavailable")
    return {"owner_id": state["owner_id"], "run": state["run"], "owner": dict(owner)}


def release_proof(before, result, retained, port_free):
    """A normal owner receipt plus independent retained-handle observations."""
    if identity(result) != identity(before):
        raise RuntimeError("Owner changed while stopping")
    processes = result.get("processes", {})
    total, exited = processes.get("retained_total"), processes.get("confirmed_exits")
    if (result.get("state") != "stopped" or result.get("running") is not False
            or result.get("cleanup_confirmed") is not True or result.get("server_exit_code") != 0
            or result.get("error") or (result.get("memory") or {}).get("error")
            or type(total) is not int or total < 1 or total != exited or processes.get("active") != []
            or not retained or not all(row.get("exited") is True for row in retained) or not port_free):
        raise RuntimeError("Normal drain and complete owned-process release were not proved")
    return {"owner_id": before["owner_id"], "identity": identity(before),
            "released": True, "cleanup_confirmed": True, "retained_processes": total,
            "confirmed_process_exits": exited, "port_free": True,
            "retained_at_stop": retained, "server_exit_code": 0,
            "scope": "Owned process exit and listener release; capacity is a separate fresh observation"}


class OwnerStartupError(RuntimeError):
    """Failed own launch; its retained Popen is evidence, never a PID to adopt.

    Popen.poll() checks the original Windows process handle. Keep that object
    alive until shutdown diagnostics have been collected, including after exit.
    https://docs.python.org/3.11/library/subprocess.html#subprocess.Popen.poll
    https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers
    """
    def __init__(self, message, *, owner_id, run, process, port=18098):
        super().__init__(message)
        self.owner_id, self.run = owner_id, str(run)
        self.process, self.port = process, port

    def diagnostic(self):
        value = {"owner_id": self.owner_id, "run": self.run, "port": self.port,
                 "process_created": self.process is not None,
                 "pid": self.process.pid if self.process is not None else None,
                 "owner_exit_confirmed": False, "owner_exit_code": None,
                 "cleanup_confirmed": False, "error": str(self),
                 "cause_type": type(self.__cause__).__name__ if self.__cause__ else None}
        if self.process is not None:
            try:
                code = self.process.poll()
                value.update(owner_exit_confirmed=code is not None, owner_exit_code=code)
            except Exception as exc:
                value["process_observation_error"] = type(exc).__name__
        # The receipt is diagnostic only. Never consult active.json or infer
        # ownership/readiness/normal cleanup from a new or incomplete receipt.
        try:
            path = Path(self.run) / "owner.json"
            if path.stat().st_size > 1024 * 1024:
                raise ValueError("Startup receipt exceeds diagnostic bound")
            receipt = json.loads(path.read_text(encoding="utf-8"))
            matches = (receipt.get("owner_id") == self.owner_id
                       and receipt.get("run") == self.run
                       and self.process is not None
                       and (receipt.get("owner") or {}).get("pid") == self.process.pid)
            value["receipt_matches_attempt"] = matches
            if matches:
                value["receipt_state"] = receipt.get("state")
                value["receipt_error"] = str(receipt.get("error") or "")[:2000]
        except FileNotFoundError:
            value["receipt_matches_attempt"] = False
        except Exception as exc:
            value["receipt_observation_error"] = type(exc).__name__
        return value


class CapacityMonitor:
    """Observations, not the live owner's emergency guard.

    Low but valid free memory remains observable, so a completed foreground
    workload can recover. Invalid/stale/blocked sensing fails closed. The
    installed owner's 3-GiB/250-MiB emergency thresholds remain unchanged.
    """
    def __init__(self, factory):
        self.factory = factory
        self.done = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.row = None
        self.error = None
        self.thread = None

    def start(self):
        def run():
            close = None
            try:
                read, close = self.factory()
                while not self.done.is_set():
                    began = time.monotonic()
                    values = read()
                    stamp = time.monotonic()
                    raw = {}
                    if type(values) is dict:
                        if set(values) != {'host', 'gpu'}:
                            raise RuntimeError('Incomplete paired capacity observation')
                        raw = {'raw_host': deepcopy(values['host']), 'raw_gpu': deepcopy(values['gpu'])}
                        values = (raw['raw_host']['available_ram_gib'],
                                  raw['raw_host']['available_commit_gib'],
                                  raw['raw_gpu']['free_bytes'] / 2**20)
                    if stamp - began > 2 or len(values) != 3 or any(
                            type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
                        raise RuntimeError("Invalid or delayed capacity observation")
                    with self.lock:
                        self.row = {"sampled_at": began, "complete": True,
                                    "available_ram_gib": values[0], "available_commit_gib": values[1],
                                    "available_vram_mib": values[2],
                                    **raw,
                                    "scope": "Fresh sampled free capacity; not a system-wide reservation"}
                    self.ready.set()
                    self.done.wait(.1)
            except BaseException as exc:
                self.error = str(exc)
                self.ready.set()
            finally:
                if close is not None:
                    try:
                        close()
                    except BaseException as exc:
                        self.error = self.error or str(exc)
        self.thread = threading.Thread(target=run, name="handoff-capacity", daemon=True)
        self.thread.start()
        if not self.ready.wait(2):
            self.error = "Capacity initialization exceeded two seconds"
            self.done.set()
            raise RuntimeError(self.error)
        self.snapshot()
        return self

    def snapshot(self):
        with self.lock:
            row = deepcopy(self.row) if self.row is not None else None
        if (self.error or row is None or not self.thread.is_alive()
                or not 0 <= time.monotonic() - row["sampled_at"] <= 2):
            raise RuntimeError(self.error or "Capacity observation unavailable or stale")
        return row

    def close(self):
        self.done.set()
        if self.thread:
            self.thread.join(2)
            if self.thread.is_alive():
                raise RuntimeError("Capacity sampler did not stop")
        if self.error:
            raise RuntimeError(self.error)


class OwnerPackage:
    """Thin composition of the preserved owner, not a second process supervisor."""
    def __init__(self, package, manifest_sha256, provenance_sha256):
        if os.name != "nt":
            raise RuntimeError("The preserved owner requires Windows")
        self.root = Path(package).resolve(strict=True)
        self.manifest_pin = _pin(manifest_sha256)
        self.provenance_pin = _pin(provenance_sha256)
        self.module = None
        self.monitor = None

    def verify(self):
        root = self.root
        if sha256(root / "MANIFEST.json") != self.manifest_pin or sha256(root / "PROVENANCE.json") != self.provenance_pin:
            raise RuntimeError("Owner package manifest/provenance changed")
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            path = (root / relative).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file() or sha256(path) != expected:
                raise RuntimeError("Owner package file changed: " + relative)
        config = json.loads((root / "config/server-template.json").read_text(encoding="utf-8"))
        validate_handoff_config(config)
        if self.module is None:
            # The owner imports these modules by their original names. Refuse a
            # different preloaded copy rather than silently mixing two packages.
            for name, directory in (("owned_job", root), ("ownership", root),
                                    ("memory_monitor", root), ("memory_reader", root),
                                    ("serve", root / "runtime/Strata"),
                                    ("strata_control", root / "runtime/Strata")):
                module = sys.modules.get(name)
                if module is not None and (not getattr(module, "__file__", None)
                        or not Path(module.__file__).resolve().is_relative_to(directory)):
                    raise RuntimeError("Another owner/source module is already imported: " + name)
            sys.path.insert(0, str(root))
            spec = importlib.util.spec_from_file_location("_adaptive_handoff_owner", root / "engine.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.module = module
        return self.module.verify()

    def status(self):
        if self.module is None:
            self.verify()
        state = self.module.status()
        state = {**state, "ready": False, "loaded": False}
        if state.get("state") == "ready" and state.get("running") is True:
            port = state["port"]
            telemetry = self.module.get_api(port, "/v1/telemetry")
            live = self.module.get_api(port, "/v1/status")
            self.module.verify_launch_attestation(telemetry, state["expected_launch_attestation"])
            if telemetry["instance"]["id"] != state["instance_id"]:
                raise RuntimeError("Live instance changed")
            listeners = {c.pid for c in self.module.psutil.net_connections(kind="tcp")
                         if c.status == "LISTEN" and c.laddr.port == port}
            if listeners != {state["server"]["pid"]}:
                raise RuntimeError("Listener ownership changed")
            if live["context"]["native"] != 65536 or not live["inference_scheduling"]["enabled"]:
                raise RuntimeError("Qualified context/scheduler changed")
            state.update(loaded=live.get("loaded") is True, ready=live.get("loaded") is True,
                         native_status=live, identity=identity(state))
        return state

    def lock_start(self):
        if self.module is None:
            self.verify()
        self.module.private_directory(self.root / "state")
        return self.module.lock(self.root / "state/start.lock")

    def unlock_start(self, token):
        self.module.unlock(token)

    def retain(self, state):
        records = [state["owner"], *state["processes"]["active"]]
        handles = []
        try:
            for record in records:
                handles.append(self.module.ProcessHandle(record["pid"], record))
            return handles
        except BaseException:
            for handle in handles:
                handle.close()
            raise

    def stop_owner(self, expected):
        # start.lock excludes ordinary starts, and the complete identity is
        # checked again immediately before the owner's authenticated stop path.
        if identity(self.module.status()) != identity(expected):
            raise RuntimeError("Owner changed before stop")
        return self.module.stop(75)

    def port_free(self, port):
        return not any(c.status == "LISTEN" and c.laddr.port == port
                       for c in self.module.psutil.net_connections(kind="tcp"))

    def start_owner(self, max_runtime_seconds):
        """Existing start recipe with start.lock already held by the adapter."""
        m = self.module
        m.private_directory(self.root / "runs")
        token = m.lock(self.root / "state/owner.lock")
        m.unlock(token)
        verified = self.verify()
        owner_id = uuid.uuid4().hex
        run = self.root / "runs" / (time.strftime("%Y%m%d-%H%M%S") + "-" + owner_id[:8])
        m.private_directory(run)
        m.save(run / "request.json", {"owner_id": owner_id, "max_runtime_seconds": max_runtime_seconds,
                                      "verification": verified})
        interpreter = m.read(self.root / "PROVENANCE.json")["dependencies"]["owner_python"]
        proc = None
        try:
            with (run / "owner.log").open("xb") as log:
                proc = subprocess.Popen([interpreter, "-B", str(self.root / "engine.py"), "_host", str(run), owner_id],
                                        cwd=self.root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                                        close_fds=True)
            deadline = time.monotonic() + 310
            while time.monotonic() < deadline:
                if (run / "owner.json").exists():
                    state = m.status()
                    if (state.get("owner_id") != owner_id or state.get("run") != str(run)
                            or (state.get("owner") or {}).get("pid") != proc.pid):
                        raise RuntimeError("New owner was replaced")
                    if state["state"] == "ready":
                        ready = self.status()
                        if identity(ready) != identity(state) or not ready.get("ready") or not ready.get("loaded"):
                            raise RuntimeError("New owner readiness changed")
                        return ready
                    if state["state"] in ("stopped", "failed"):
                        raise RuntimeError("New owner failed before readiness; see its retained run receipt")
                if proc.poll() is not None:
                    raise RuntimeError("New owner exited before readiness; see its retained run receipt")
                time.sleep(.2)
            # The owner watchdog remains responsible for cleanup. A timeout is
            # not evidence that it exited, nor permission to launch a replacement.
            raise RuntimeError("New owner did not become ready; handoff barrier remains held")
        except Exception as exc:
            raise OwnerStartupError(str(exc), owner_id=owner_id, run=run, process=proc) from exc

    def capacity(self):
        if self.module is None:
            self.verify()
        if self.monitor is None:
            p = self.module.read(self.root / "PROVENANCE.json")
            dll = p["dependencies"]["nvml"]
            reader_module = sys.modules["memory_reader"]
            def factory():
                reader = reader_module.NativeReader(dll, p["dependencies_sha256"][dll])
                def observe():
                    gpu = reader_module.checked_sample(reader.read())
                    host = reader_module.checked_host_sample(reader_module.host_memory())
                    return {'host': host, 'gpu': gpu}
                return observe, reader.close
            self.monitor = CapacityMonitor(factory)
            self.monitor.start()
        return self.monitor.snapshot()

    def load_plan_context(self):
        """Verified immutable-profile inputs; no second sampler or model probe."""
        self.verify()
        reader = sys.modules['memory_reader']
        return {'config': self.module.read(self.root / 'config/server-template.json'),
                'plan_startup_cache': self.module.plan_startup_cache,
                'checked_host_sample': reader.checked_host_sample,
                'checked_gpu_sample': reader.checked_sample}

    def close(self):
        if self.monitor is not None:
            self.monitor.close()
            self.monitor = None


class NativeOwnerAdapter:
    def __init__(self, package=None, *, manifest_sha256=None, provenance_sha256=None,
                 max_runtime_seconds=900, _driver=None):
        if max_runtime_seconds is not None and (isinstance(max_runtime_seconds, bool)
                or not math.isfinite(max_runtime_seconds) or not 60 <= max_runtime_seconds <= 604800):
            raise ValueError("Runtime bound must be 60 seconds through seven days, or None")
        self.driver = _driver or OwnerPackage(package, manifest_sha256, provenance_sha256)
        self.max_runtime_seconds = max_runtime_seconds
        self._serial = threading.RLock()
        self._barrier = None
        self._expected = None
        self._released = None
        self._observed_live = False
        self._startup_failure = None

    async def _call(self, function, *args):
        def run():
            with self._serial:
                return function(*args)
        work = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            # A canceled coordinator cannot abandon a half-completed mutation.
            try:
                await work
            finally:
                raise

    def _status(self):
        if self._startup_failure is not None:
            raise self._startup_failure
        state = self.driver.status()
        if state.get("owner_id") and state.get("owner"):
            current = identity(state)
            if self._expected is not None and current != self._expected:
                raise RuntimeError("Observed owner changed outside this adapter")
            self._expected = current
            self._observed_live = self._observed_live or state.get("running") is True
        return state

    async def status(self):
        return await self._call(self._status)

    def _stop(self, expected_identity):
        if self._startup_failure is not None:
            raise self._startup_failure
        expected_id = expected_identity if isinstance(expected_identity, str) else expected_identity["owner_id"]
        if self._expected is None or self._expected["owner_id"] != expected_id:
            raise RuntimeError("Stop requires the previously observed exact owner")
        if isinstance(expected_identity, dict) and identity(expected_identity) != self._expected:
            raise RuntimeError("Requested stop identity differs from observed owner")
        if self._released is not None:
            # Do not turn a repeated stop into a second process operation.
            if identity(self.driver.status()) != self._expected:
                raise RuntimeError("Stopped owner changed")
            return dict(self._released)
        if self._barrier is None:
            self._barrier = self.driver.lock_start()
        before = self.driver.status()
        if identity(before) != self._expected:
            raise RuntimeError("Owner changed before handoff")
        self.driver.verify()
        handles = self.driver.retain(before)
        try:
            result = self.driver.stop_owner(before)
            retained = [{**h.record, "exited": h.exited()} for h in handles]
            proof = release_proof(before, result, retained, self.driver.port_free(before["port"]))
            self._released = proof
            return dict(proof)
        finally:
            for handle in handles:
                handle.close()

    async def stop(self, expected_identity):
        return await self._call(self._stop, expected_identity)

    def _start(self):
        if self._startup_failure is not None:
            raise self._startup_failure  # No retry/adoption after an unresolved own launch.
        if self._barrier is None:
            self._barrier = self.driver.lock_start()
        current = self.driver.status()
        if current.get("running") is not False or current.get("state") not in ("stopped", "failed"):
            raise RuntimeError("Refusing to adopt or replace a live/uncertain owner")
        if self._expected is not None and identity(current) != self._expected:
            raise RuntimeError("Stopped owner was replaced")
        if self._observed_live and self._released is None:
            raise RuntimeError("Existing observed owner has no successful release proof")
        if current.get("owner_id") and (current.get("cleanup_confirmed") is not True
                or current.get("processes", {}).get("active") != []):
            raise RuntimeError("Previous owner lacks a complete cleanup receipt")
        previous = self._expected
        try:
            state = self.driver.start_owner(self.max_runtime_seconds)
        except OwnerStartupError as exc:
            self._startup_failure = exc
            self._released = None  # The previous owner's proof cannot cover this attempt.
            raise
        new = identity(state)
        if not state.get("ready") or not state.get("loaded") or (previous and new["owner_id"] == previous["owner_id"]):
            raise RuntimeError("Distinct ready loaded replacement was not proved")
        self._expected = new
        self._observed_live = True
        self._released = None
        self.driver.unlock_start(self._barrier)
        self._barrier = None
        return state

    async def start(self):
        return await self._call(self._start)

    async def fresh_capacity(self):
        return await self._call(self.driver.capacity)

    def _failed_start_status(self):
        if self._startup_failure is None:
            return None
        value = self._startup_failure.diagnostic()
        try:
            value["port_free"] = self.driver.port_free(value["port"])
        except Exception as exc:
            value.update(port_free=None, port_observation_error=type(exc).__name__)
        return value

    async def failed_start_status(self):
        return await self._call(self._failed_start_status)

    async def close(self, *, release_parked=False):
        def finish():
            if self._barrier is not None and not release_parked:
                raise RuntimeError("Handoff barrier is held; confirm competing work has stopped before releasing it")
            if self._startup_failure is not None:
                failure = self._failed_start_status()
                if ((failure["process_created"] and not failure["owner_exit_confirmed"])
                        or failure.get("process_observation_error") or failure["port_free"] is not True):
                    raise RuntimeError("Failed startup remains unresolved; handoff barrier retained") from self._startup_failure
                # The host must separately prove its containing job is empty.
                # This ends local monitoring/lock ownership, not a normal release.
            self.driver.close()
            if self._barrier is not None:
                self.driver.unlock_start(self._barrier)
                self._barrier = None
        return await self._call(finish)
