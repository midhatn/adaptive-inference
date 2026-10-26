# SPDX-License-Identifier: Apache-2.0
"""CPU prototype for one prepared task's authenticated asyncio control streams.

No listener, credential file, GUI, process API or model is started here. Reuses
the existing owner's bounded JSON/token pattern and the standard asyncio stream
lifecycle. Actual mailbox idempotency and cooperative worker join are supplied
by a trusted runtime; no new durable store/operation semantics are implemented.
"""
import asyncio
from dataclasses import dataclass
import json
import re
import secrets
import threading
from adaptive_inference.control_mailbox import ControlNotRecorded

REQUEST_LIMIT, RESPONSE_LIMIT = 4096, 65536
COMMANDS = frozenset(("pause", "resume", "cancel"))
MUTATIONS = COMMANDS | {"continue"}
METHODS = MUTATIONS | {"status", "window_ready", "window_closed", "stop"}
PHASES = {"unavailable", "available", "selected", "preparing", "ready", "running", "blocked"}
ERRORS = {"invalid_request", "unauthorized", "projection_refused", "stopping",
          "conflicting_request_id", "capacity_exhausted", "session_not_ready",
          "stale_execution", "continuation_unavailable", "continuation_blocked"}


def label(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("Invalid bounded identity")
    return value


def credential():
    return secrets.token_hex(32)


class Refused(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("invalid_request")
        result[key] = value
    return result


def reject_constant(value):
    raise Refused("invalid_request")


@dataclass(frozen=True)
class PreparedTask:
    host_epoch: str
    task_id: str
    objective: str

    def __post_init__(self):
        label(self.host_epoch)
        label(self.task_id)
        if type(self.objective) is not str or not self.objective.strip() or len(self.objective.encode("utf-8")) > 16384:
            raise ValueError("Prepared objective must fit unchanged in the bounded UI projection")


def execution(value):
    if (type(value) is not dict or set(value) != {"execution_id", "execution_generation"}
            or type(value["execution_generation"]) is not int
            or not 0 <= value["execution_generation"] <= 32):
        raise Refused("projection_refused")
    label(value["execution_id"])
    return dict(value)


def continuation_phase(value):
    if (type(value) is not dict or set(value) != {"phase", "request_id"}
            or value["phase"] not in PHASES):
        raise Refused("projection_refused")
    if value["phase"] in {"unavailable", "available"}:
        if value["request_id"] is not None: raise Refused("projection_refused")
    else:
        label(value["request_id"])
    return dict(value)


class ControlTransport:
    """Owner-loop component. Rejected admit() streams remain the caller's duty.

    Runtime methods are specified in README.md. Sync callbacks must be bounded
    and loop-owned; submit_control/cooperative_stop are awaited in retained tasks.
    Disconnect, timeout, handler cancellation and aclose timeout never cancel an
    already dispatched database mutation or a worker join.
    """
    def __init__(self, prepared, runtime, *, capability, runner_credential,
                 io_timeout=2.0, max_handlers=8, max_mutations=4, max_ids=32, max_sessions=32,
                 cooperative_progress=None):
        if type(prepared) is not PreparedTask or type(capability) is not object:
            raise TypeError("Trusted prepared task and host capability required")
        if (type(runner_credential) is not str or not runner_credential.isascii()
                or not 1 <= len(runner_credential) <= 256):
            raise ValueError("Distinct inference credential must be supplied by host")
        if type(io_timeout) not in (int, float) or not 0 < io_timeout <= 30:
            raise ValueError("Bounded stream deadline required")
        if any(type(value) is not int or not 1 <= value <= 32
               for value in (max_handlers, max_mutations, max_ids, max_sessions)):
            raise ValueError("Finite transport capacities required")
        self.prepared, self.runtime, self._capability = prepared, runtime, capability
        if cooperative_progress is not None:
            from adaptive_inference.desktop.ui_progress import CooperativeProgress
            if (type(cooperative_progress) is not CooperativeProgress
                    or getattr(runtime, 'gate', None) is not cooperative_progress.gate
                    or cooperative_progress.gate.host_epoch != prepared.host_epoch):
                raise TypeError('Cooperative progress must share the exact trusted runtime gate')
        self.cooperative_progress = cooperative_progress
        self._runner_credential = runner_credential
        self._loop, self._thread = asyncio.get_running_loop(), threading.current_thread()
        self.io_timeout = io_timeout
        self.max_handlers, self.max_mutations = max_handlers, max_mutations
        self.max_ids, self.max_sessions = max_ids, max_sessions
        self._handlers, self._records, self._sessions = set(), {}, {}
        self._connections = {}
        self._session, self._credential, self._ready = None, None, False
        self._intent_revision = 0
        self._serial = asyncio.Lock()
        self._accepting, self._stop_requested = True, False
        self._stop_task = self._close_task = None
        self._stop_confirmed = False
        self._faults, self._stream_close_failures = set(), 0
        for name in ("selected_execution", "select_continuation", "continue_selected", "lookup_continuation"):
            if not callable(getattr(runtime, name, None)):
                raise TypeError("Explicit continuation runtime hook required: " + name)
        self._selection = execution(runtime.selected_execution())
        self._seen_executions = {self._selection["execution_generation"]: self._selection["execution_id"]}
        self._continuing = None

    def _owner(self):
        if threading.current_thread() is not self._thread or asyncio.get_running_loop() is not self._loop:
            raise PermissionError("Transport belongs to its host loop/thread")

    def _adopt_execution(self, value):
        value = execution(value)
        generation, identity = value["execution_generation"], value["execution_id"]
        if (generation < self._selection["execution_generation"]
                or generation in self._seen_executions and self._seen_executions[generation] != identity
                or any(g != generation and i == identity for g, i in self._seen_executions.items())):
            raise Refused("projection_refused")
        self._seen_executions[generation] = identity
        self._selection = value
        return dict(value)

    def _current_execution(self):
        return self._adopt_execution(self.runtime.selected_execution())

    @staticmethod
    def _request_execution(request):
        return execution({key: request[key] for key in ("execution_id", "execution_generation")})

    def _require_execution(self, expected):
        if execution(expected) != self._current_execution():
            raise Refused("stale_execution")

    def _mutation_tasks(self):
        return [task for row in self._records.values()
                for task in (row["task"], row.get("lookup_task")) if task is not None]

    def bind_session(self, capability, session_id, token):
        self._owner()
        if capability is not self._capability:
            raise PermissionError("Host capability required")
        label(session_id)
        if (not self._accepting or self._stop_requested or session_id in self._sessions
                or len(self._sessions) >= self.max_sessions
                or type(token) is not str or not re.fullmatch(r"[0-9a-f]{64}", token)
                or secrets.compare_digest(token, self._runner_credential)
                or any(secrets.compare_digest(token, old) for old in self._sessions.values())):
            raise ValueError("Fresh bounded session and distinct UI credential required")
        self._deactivate()
        self._sessions[session_id] = token
        self._session, self._credential, self._ready = session_id, token, False

    def _deactivate(self):
        self._intent_revision += 1
        self.invalidate_progress('transport_intent_changed')
        self.runtime.deactivate_intent()

    def invalidate_progress(self, reason):
        self._owner()
        if self.cooperative_progress is not None:
            self.cooperative_progress.invalidate(reason)

    def reaped_status(self, task):
        """Listener only: handler joined, wait_closed succeeded, socket closed."""
        self._owner()
        if self.cooperative_progress is not None and task is not None:
            if not self._progress_available():
                self.invalidate_progress('progress_transport_unavailable')
            elif task.cancelled() or task.exception() is not None:
                self.invalidate_progress('progress_handler_failed')
            elif task.result() is not None:
                self.cooperative_progress.complete(task.result())

    def _progress_available(self):
        return (self._accepting and self._ready and not self._stop_requested and not self._faults
                and self._session is not None and self.runtime.session_is_live(self._session) is True)

    def admit(self, reader, writer):
        """Take ownership only when returning a tracked Task; None owns nothing."""
        self._owner()
        if (not self._accepting or len(self._connections) >= self.max_handlers
                or len(self._handlers) >= self.max_handlers):
            return None
        connection = {"writer": writer, "started": False, "cleanup": None, "failed": False}
        task = self._loop.create_task(self._handle(reader, writer, connection))
        connection["handler"] = task
        self._connections[task] = connection
        self._handlers.add(task)
        task.add_done_callback(self._handler_done)
        return task

    def _handler_done(self, task):
        self._handlers.discard(task)
        connection = self._connections.get(task)
        if connection is not None and connection["cleanup"] is None:
            # Ownership was transferred by admit even if cancellation prevented
            # the coroutine's first instruction (and therefore its finally).
            self._start_connection_close(connection)
        if not task.cancelled() and task.exception() is not None:
            self._faults.add("handler_failed")
        if task.cancelled() or task.exception() is not None:
            self.invalidate_progress('progress_handler_failed')

    def _start_connection_close(self, connection):
        if connection["cleanup"] is None:
            task = self._loop.create_task(self._close_writer(connection["writer"]))
            connection["cleanup"] = task
            task.add_done_callback(lambda done: self._connection_done(connection, done))
        return connection["cleanup"]

    async def _close_writer(self, writer):
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), self.io_timeout)

    def _connection_done(self, connection, task):
        if task.cancelled() or task.exception() is not None:
            self.invalidate_progress('progress_stream_close_failed')
            if not connection["failed"]:
                connection["failed"] = True
                self._stream_close_failures += 1
                self._faults.add("stream_close_failed")
            # Keep this bounded capacity/cleanup obligation; do not blindly retry.
        else:
            self._connections.pop(connection["handler"], None)

    async def _read_request(self, reader):
        data = bytearray()
        while True:
            part = await reader.read(REQUEST_LIMIT + 1 - len(data))
            if type(part) is not bytes:
                raise Refused("invalid_request")
            if not part:
                break
            data.extend(part)
            if len(data) > REQUEST_LIMIT:
                raise Refused("invalid_request")
        if not data.endswith(b"\n") or data.count(b"\n") != 1:
            raise Refused("invalid_request")
        try:
            request = json.loads(data[:-1].decode("utf-8"), object_pairs_hook=unique_object,
                                 parse_constant=reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise Refused("invalid_request") from None
        if type(request) is not dict or type(request.get("method")) is not str or request["method"] not in METHODS:
            raise Refused("invalid_request")
        keys = {"host_epoch", "session_id", "task_id", "token", "method"}
        if request["method"] in MUTATIONS:
            keys.update(("request_id", "execution_id", "execution_generation"))
        if request["method"] == "continue":
            keys.add("expected_task_revision")
        integer_keys = {"execution_generation", "expected_task_revision"}
        if set(request) != keys or any(type(value) is not str for key, value in request.items() if key not in integer_keys):
            raise Refused("invalid_request")
        try:
            for key in ("host_epoch", "session_id", "task_id"):
                label(request[key])
            if "request_id" in request:
                label(request["request_id"])
                label(request["execution_id"])
                if type(request["execution_generation"]) is not int or not 0 <= request["execution_generation"] <= 32:
                    raise ValueError("Invalid execution generation")
            if "expected_task_revision" in request and (type(request["expected_task_revision"]) is not int
                    or not 0 <= request["expected_task_revision"] < 256):
                raise ValueError("Invalid expected revision")
        except ValueError:
            raise Refused("invalid_request") from None
        if not re.fullmatch(r"[0-9a-f]{64}", request["token"]):
            raise Refused("unauthorized")
        return request

    def _authenticate(self, request):
        pending_allowed = request["method"] in {"window_ready", "window_closed", "status", "stop"}
        if (self._session is None or request["host_epoch"] != self.prepared.host_epoch
                or request["task_id"] != self.prepared.task_id or request["session_id"] != self._session
                or not secrets.compare_digest(request["token"], self._credential)
                or (not pending_allowed and not self._ready)
                or self.runtime.session_is_live(self._session) is not True):
            raise Refused("unauthorized")

    def _public_status(self):
        value = self.runtime.status()
        keys = {"host_phase", "task_status", "task_revision", "demand", "waiting_reason", "controls",
                "execution_id", "execution_generation", "continuation"}
        if (type(value) is not dict or set(value) != keys
                or value["host_phase"] not in {"starting", "ready", "parked", "restoring", "stopping", "closed", "fault"}
                or value["task_status"] not in {"pending", "accepted", "exhausted"}
                or type(value["task_revision"]) is not int or not 0 <= value["task_revision"] < 256
                or value["demand"] not in {None, "active", "waiting", "paused", "cancelled", "fulfilled"}
                or value["waiting_reason"] not in {None, "foreground", "resources", "paused", "budget_expired", "reconciliation", "stop_requested", "operation_inflight", "unknown"}):
            raise Refused("projection_refused")
        self._require_execution({key: value[key] for key in ("execution_id", "execution_generation")})
        continuation_phase(value["continuation"])
        if type(value["controls"]) is not list or len(value["controls"]) > 32:
            raise Refused("projection_refused")
        controls, ids = [], set()
        for row in value["controls"]:
            if type(row) is not dict:
                raise Refused("projection_refused")
            request_id, command = row.get("request_id"), row.get("command")
            label(request_id)
            if command not in COMMANDS or request_id in ids:
                raise Refused("projection_refused")
            ids.add(request_id)
            controls.append(self._control_result(row, request_id, command))
        value["controls"] = controls
        return {**value, "objective": self.prepared.objective, **self.lifecycle()}

    def lifecycle(self):
        self._owner()
        unresolved = sum(record["outcome"] == "unknown" for record in self._records.values())
        return {"stop_requested": self._stop_requested, "stop_confirmed": self._stop_confirmed,
                "pending_mutations": sum(not task.done() for task in self._mutation_tasks()),
                "unknown_mutations": unresolved, "handlers": len(self._handlers),
                "pending_connections": len(self._connections),
                "stream_close_failures": self._stream_close_failures, "faults": sorted(self._faults)}

    @staticmethod
    def _control_result(value, request_id, command):
        keys = {"request_id", "command", "sequence", "owner_acknowledged", "outcome"}
        if (type(value) is not dict or set(value) != keys or value["request_id"] != request_id
                or value["command"] != command or type(value["sequence"]) is not int
                or not 1 <= value["sequence"] <= 32 or type(value["owner_acknowledged"]) is not bool
                or value["outcome"] not in {"pending", "applied", "rejected"}
                or (value["outcome"] == "applied" and value["owner_acknowledged"] is not True)
                or (value["outcome"] == "pending" and value["owner_acknowledged"] is not False)):
            raise Refused("projection_refused")
        return {**value, "recorded": True}

    async def _apply_control(self, request_id, command, session, revision, new_intent):
        record = self._records[request_id]
        selected = record["execution"]
        runtime = record["runtime"]
        try:
            async with self._serial:
                try:
                    if self._stop_requested: raise Refused("stopping")
                    self._require_execution(selected)
                except Refused:
                    record["outcome"] = "known"
                    raise
                value = await runtime.submit_control(request_id, command, execution=dict(selected))
                if type(value) is ControlNotRecorded:
                    if (value.request_id != request_id or value.command != command
                            or value.reason != "execution_budget_expired"):
                        raise Refused("projection_refused")
                    record["outcome"] = "known"
                    return {"request_id": request_id, "command": command,
                            "reason": value.reason, "recorded": False}
                result = self._control_result(value, request_id, command)
                authority = False
                if new_intent and command == "resume" and result["outcome"] != "rejected":
                    authority = await runtime.resume_authority(request_id, execution=dict(selected))
                if (authority is True and new_intent and command == "resume"
                        and revision == self._intent_revision and selected == self._current_execution()
                        and runtime is self.runtime and session == self._session and self._ready
                        and not self._stop_requested and runtime.session_is_live(session) is True):
                    runtime.activate_intent(session, execution=dict(selected))
                record["outcome"] = "known"
                return result
        except BaseException:
            if record["outcome"] != "known": record["outcome"] = "unknown"
            raise

    def _completed_mutation(self, record, task):
        if task.cancelled() or task.exception() is not None:
            if record["outcome"] != "known": record["outcome"] = "unknown"

    def _record_request(self, request):
        return {key: value for key, value in request.items() if key != "token"}

    def _capacity(self, new):
        if (new and len(self._records) >= self.max_ids
                or sum(not task.done() for task in self._mutation_tasks()) >= self.max_mutations):
            raise Refused("capacity_exhausted")

    def _retain_control(self, request):
        request_id, command = request["request_id"], request["method"]
        payload = self._record_request(request)
        record = self._records.get(request_id)
        if record is not None and record["payload"] != payload:
            raise Refused("conflicting_request_id")
        if self._stop_requested: raise Refused("stopping")
        selected = self._request_execution(request)
        self._require_execution(selected)
        if "continuation_failed" in self._faults:
            raise Refused("continuation_blocked")
        if self._continuing is not None:
            raise Refused("continuation_unavailable")
        projected = continuation_phase(self.runtime.status()["continuation"])
        if projected["phase"] in {"selected", "preparing", "ready", "blocked"}:
            raise Refused("continuation_blocked")
        self.invalidate_progress("progress_control_pending")
        if command in {"pause", "cancel"}: self._deactivate()
        if record is not None and not record["task"].done(): return record["task"]
        self._capacity(record is None)
        new_intent = record is None
        self._intent_revision += 1
        record = {"command": command, "payload": payload, "execution": selected,
                  "runtime": self.runtime, "outcome": "pending"}
        self._records[request_id] = record
        task = self._loop.create_task(self._apply_control(request_id, command, self._session,
                                                        self._intent_revision, new_intent))
        record["task"] = task
        task.add_done_callback(lambda done: self._completed_mutation(record, done))
        return task

    def _grant(self, value, request):
        keys = {"request_id", "predecessor_execution_id", "predecessor_generation",
                "execution_id", "execution_generation", "phase"}
        if (type(value) is not dict or set(value) != keys
                or value["request_id"] != request["request_id"]
                or value["predecessor_execution_id"] != request["execution_id"]
                or type(value["predecessor_generation"]) is not int
                or value["predecessor_generation"] != request["execution_generation"]
                or value["phase"] not in {"selected", "preparing", "ready", "running", "blocked"}):
            raise Refused("projection_refused")
        selected = execution({key: value[key] for key in ("execution_id", "execution_generation")})
        if (selected["execution_generation"] != request["execution_generation"] + 1
                or selected["execution_id"] == request["execution_id"]):
            raise Refused("projection_refused")
        return dict(value)

    def _continuation_intent(self, record):
        self._owner()
        valid = (not self._stop_requested and self._ready
                 and record["session"] == self._session
                 and record["intent_revision"] == self._intent_revision
                 and record["runtime"] is self.runtime
                 and self.runtime.session_is_live(record["session"]) is True)
        if valid:
            expected = record["execution"] if record["grant"] is None else self._request_execution(record["grant"])
            valid = expected == self._current_execution()
        return valid

    async def _apply_continue(self, record):
        try:
            async with self._serial:
                try:
                    if not self._continuation_intent(record): raise Refused("continuation_blocked")
                    self._require_execution(record["execution"])
                except Refused:
                    record["outcome"] = "known"
                    raise
                try:
                    value = await record["runtime"].select_continuation(dict(record["payload"]),
                        intent_valid=lambda: self._continuation_intent(record))
                except Refused as error:
                    if str(error) in {"stale_execution", "continuation_unavailable", "continuation_blocked", "stopping"}:
                        record["outcome"] = "known"
                    raise
                grant = self._grant(value, record["payload"])
                if grant["phase"] != "selected": raise Refused("projection_refused")
                record["grant"] = grant
                self._adopt_execution(self._request_execution(grant))
            # Bootstrap/readiness must never occupy the serial mutation lock.
            value = await record["runtime"].continue_selected(dict(grant),
                intent_valid=lambda: self._continuation_intent(record))
            result = self._grant(value, record["payload"])
            if {k:v for k,v in result.items() if k != "phase"} != {k:v for k,v in grant.items() if k != "phase"}:
                raise Refused("projection_refused")
            record["grant"], record["outcome"] = result, "known"
            return result
        except BaseException:
            if record["outcome"] != "known":
                record["outcome"] = "unknown"
                self._faults.add("continuation_failed")
            raise
        finally:
            if self._continuing is record: self._continuing = None

    async def _lookup_continue(self, record):
        value = await record["runtime"].lookup_continuation(dict(record["payload"]))
        if value is not None:
            result = self._grant(value, record["payload"])
            if result["phase"] not in {"selected", "blocked"}: raise Refused("projection_refused")
            record["grant"] = result
        return value

    def _retain_continue(self, request):
        payload = self._record_request(request)
        record = self._records.get(request["request_id"])
        if record is not None:
            if record["payload"] != payload: raise Refused("conflicting_request_id")
            return record  # Same command is lookup only, including a stale predecessor.
        if self._stop_requested: raise Refused("stopping")
        if "continuation_failed" in self._faults: raise Refused("continuation_blocked")
        self._require_execution(self._request_execution(request))
        if self._continuing is not None: raise Refused("continuation_unavailable")
        self._capacity(True)
        self._deactivate()
        record = {"command": "continue", "payload": payload,
                  "execution": self._request_execution(request), "runtime": self.runtime,
                  "session": self._session, "intent_revision": self._intent_revision,
                  "outcome": "pending", "grant": None}
        self._records[request["request_id"]] = record
        self._continuing = record
        task = self._loop.create_task(self._apply_continue(record))
        record["task"] = task
        task.add_done_callback(lambda done: self._completed_mutation(record, done))
        return record

    async def _continue_reply(self, request):
        existing = request["request_id"] in self._records
        record = self._retain_continue(request)
        if record["grant"] is not None:
            return {"ok": True, "continuation": dict(record["grant"])}
        operation = record["task"]
        if existing and not operation.done():
            return self._pending_reply(request)
        if existing:
            operation = record.get("lookup_task")
            if operation is None or operation.done():
                self._capacity(False)
                operation = self._loop.create_task(self._lookup_continue(record))
                record["lookup_task"] = operation
                operation.add_done_callback(lambda done: self._completed_mutation(record, done))
        try:
            await asyncio.wait_for(asyncio.shield(operation), self.io_timeout)
        except asyncio.TimeoutError:
            pass
        if record["grant"] is not None:
            return {"ok": True, "continuation": dict(record["grant"])}
        return self._pending_reply(request)

    def _pending_reply(self, request):
        return {"ok": True, "state": "pending", "request_id": request["request_id"],
                "recorded": None, **self._request_execution(request)}

    def _request_stop(self):
        if self._stop_requested:
            return
        self._stop_requested = True
        try:
            self._deactivate()
        except Exception:
            self._faults.add("intent_revocation_failed")
        try:
            self.runtime.fence_admission()
        except Exception:
            self._faults.add("admission_fence_failed")
        self._stop_task = self._loop.create_task(self._cooperative_stop())

    async def _cooperative_stop(self):
        await asyncio.gather(*self._mutation_tasks(), return_exceptions=True)
        try:
            value = await self.runtime.cooperative_stop()
            if (type(value) is not dict or set(value) != {"worker_joined", "host_closed", "uncertain", "fault"}
                    or value["worker_joined"] is not True or value["host_closed"] is not True
                    or value["uncertain"] is not False or value["fault"] is not None):
                self._faults.add("stop_unresolved")
            else:
                self._stop_confirmed = (not self._faults and not any(
                    row["outcome"] == "unknown" for row in self._records.values()))
        except BaseException:
            self._faults.add("stop_failed")

    async def _dispatch(self, request, connection=None):
        self._authenticate(request)
        method = request["method"]
        if method == "status":
            if self.cooperative_progress is not None and connection is not None:
                if self._progress_available():
                    connection['progress_ticket'] = self.cooperative_progress.begin(self._session)
                else:
                    self.invalidate_progress('progress_transport_unavailable')
            return {"ok": True, "status": self._public_status()}
        if method == "stop":
            self._request_stop()
            return {"ok": True, "state": "stop_requested", **self.lifecycle()}
        if method == "window_closed":
            self._deactivate()
            session, self._session, self._ready = self._session, None, False
            self.runtime.window_closed(session)
            return {"ok": True, "state": "window_closed", "task_cancelled": False}
        if self._stop_requested:
            raise Refused("stopping")
        if method == "window_ready":
            if not self._ready:
                if self.runtime.window_ready(self._session) is not True:
                    raise Refused("session_not_ready")
                self._ready = True
            return {"ok": True, "state": "window_ready"}
        if method == "continue":
            return await self._continue_reply(request)
        operation = self._retain_control(request)
        try:
            result = await asyncio.wait_for(asyncio.shield(operation), self.io_timeout)
        except asyncio.TimeoutError:
            return self._pending_reply(request)
        return {"ok": True, **self._request_execution(request),
                "refusal" if result.get("recorded") is False else "control": result}

    async def _handle(self, reader, writer, connection):
        connection["started"] = True
        progress_ticket = None
        try:
            try:
                request = await asyncio.wait_for(self._read_request(reader), self.io_timeout)
                reply = await self._dispatch(request, connection)
            except Refused as error:
                self.invalidate_progress('progress_request_refused')
                code = str(error)
                reply = {"ok": False, "error": code if code in ERRORS else "runtime_error"}
            except asyncio.TimeoutError:
                self.invalidate_progress('progress_request_timeout')
                reply = {"ok": False, "error": "request_timeout"}
            except Exception:
                self.invalidate_progress('progress_request_failed')
                reply = {"ok": False, "error": "runtime_error"}
            encoded = (json.dumps(reply, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
            forbidden = (self._runner_credential, *self._sessions.values())
            if len(encoded) > RESPONSE_LIMIT or any(secret.encode() in encoded for secret in forbidden):
                self.invalidate_progress('progress_projection_refused')
                encoded = b'{"ok":false,"error":"projection_refused"}\n'
                connection['progress_ticket'] = None
            writer.write(encoded)
            await asyncio.wait_for(writer.drain(), self.io_timeout)
            if reply.get('ok') is True:
                progress_ticket = connection.get('progress_ticket')
        except (ConnectionError, OSError, asyncio.TimeoutError):
            self.invalidate_progress('progress_write_failed')
            pass
        finally:
            await asyncio.shield(self._start_connection_close(connection))
        return progress_ticket

    async def _finish_close(self):
        await asyncio.shield(self._stop_task)
        await asyncio.gather(*tuple(self._handlers), return_exceptions=True)
        # Done callbacks establish pre-start-cancellation cleanup obligations.
        await asyncio.sleep(0)
        await asyncio.gather(*(row["cleanup"] for row in tuple(self._connections.values())
                               if row["cleanup"] is not None), return_exceptions=True)
        await asyncio.sleep(0)

    async def aclose(self, *, timeout=2.0):
        """Deadline returns unresolved; retained shutdown/mutations are not cancelled."""
        self._owner()
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("Bounded close wait required")
        self._accepting = False
        self._request_stop()
        if self._close_task is None:
            self._close_task = self._loop.create_task(self._finish_close())
        try:
            await asyncio.wait_for(asyncio.shield(self._close_task), timeout)
        except asyncio.TimeoutError:
            pass
        state = self.lifecycle()
        state["closed"] = (self._close_task.done() and self._stop_confirmed
                           and not self._handlers and not self._connections
                           and self._stream_close_failures == 0 and not self._faults)
        return state
