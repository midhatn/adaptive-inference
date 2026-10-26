"""Fake streams/runtime only. One probe uses an owned bounded thread, no sockets."""
import asyncio
from copy import deepcopy
import json
import threading
import unittest

from adaptive_inference.desktop.control_transport import ControlTransport, PreparedTask, Refused, credential


class Reader:
    def __init__(self, data=b"", eof=True):
        self.data = bytearray(data)
        self.eof = asyncio.Event()
        if eof:
            self.eof.set()

    async def read(self, count):
        if self.data:
            result = bytes(self.data[:count])
            del self.data[:count]
            return result
        await self.eof.wait()
        return b""


class Writer:
    def __init__(self, *, broken=False, close_wait=None):
        self.data = bytearray()
        self.closed = False
        self.joined = False
        self.broken, self.close_wait = broken, close_wait

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        if self.broken:
            raise ConnectionResetError("fake disconnect")

    def close(self):
        self.closed = True

    async def wait_closed(self):
        if self.close_wait is not None:
            await self.close_wait.wait()
        self.joined = True


class Runtime:
    def __init__(self):
        self.live = {"session"}
        self.ready = set()
        self.intent = False
        self.fenced = False
        self.commits = []
        self.controls = {}
        self.calls = []
        self.entered = asyncio.Event()
        self.release = None
        self.join = asyncio.Event()
        self.join.set()
        self.join_entered = asyncio.Event()
        self.stop_value = {"worker_joined": True, "host_closed": True, "uncertain": False, "fault": None}
        self.submit_error = None
        self.authority_release = None
        self.authority_entered = asyncio.Event()
        self.projection = {"host_phase": "ready", "task_status": "pending", "task_revision": 1,
                           "demand": "waiting", "waiting_reason": None}

    def session_is_live(self, session):
        return session in self.live

    def status(self):
        return {**self.projection, "controls": [dict(value) for value in self.controls.values()]}

    def deactivate_intent(self):
        self.calls.append("deactivate")
        self.intent = False

    def activate_intent(self, session):
        self.calls.append(("activate", session))
        self.intent = True

    def window_ready(self, session):
        self.ready.add(session)
        return self.session_is_live(session)

    def window_closed(self, session):
        self.live.discard(session)

    def fence_admission(self):
        self.calls.append("fence")
        self.fenced = True

    async def submit_control(self, request_id, command):
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if request_id in self.controls and self.controls[request_id]["command"] != command:
            raise ValueError("durable ID conflict")
        if request_id not in self.controls:
            self.commits.append((request_id, command))
            self.controls[request_id] = {"request_id": request_id, "command": command,
                "sequence": len(self.controls) + 1, "outcome": "pending", "owner_acknowledged": False}
        if self.submit_error is not None:
            raise self.submit_error
        return dict(self.controls[request_id])

    async def cooperative_stop(self):
        self.join_entered.set()
        await self.join.wait()
        return deepcopy(self.stop_value)

    async def resume_authority(self, request_id):
        self.authority_entered.set()
        if self.authority_release is not None:
            await self.authority_release.wait()
        # Fake of a future real mailbox/target consistency adapter, not proof of
        # atomic multi-record reads or cross-process reservation.
        latest = max(self.controls.values(), key=lambda row: row["sequence"], default=None)
        return (latest is not None and latest["request_id"] == request_id and latest["command"] == "resume"
                and self.projection["task_status"] == "pending"
                and self.projection["demand"] in ("active", "waiting", "paused")
                and self.projection["waiting_reason"] not in ("reconciliation", "unknown"))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = Runtime()
        self.capability = object()
        self.token = "a" * 64
        self.prepared = PreparedTask("host", "task", "Keep this original objective unchanged.")
        self.transport = ControlTransport(self.prepared, self.runtime, capability=self.capability,
            runner_credential="b" * 64, io_timeout=.05)
        self.transport.bind_session(self.capability, "session", self.token)
        await self.request("window_ready")

    async def asyncTearDown(self):
        if self.runtime.release is not None:
            self.runtime.release.set()
        if self.runtime.authority_release is not None:
            self.runtime.authority_release.set()
        self.runtime.join.set()
        await self.transport.aclose(timeout=1)

    def frame(self, method="status", **changes):
        request = {"host_epoch": "host", "session_id": "session", "task_id": "task",
                   "token": self.token, "method": method}
        if method in {"pause", "resume", "cancel"}:
            request["request_id"] = "request-1"
        request.update(changes)
        return (json.dumps(request, separators=(",", ":")) + "\n").encode()

    async def request(self, method="status", *, writer=None, **changes):
        writer = writer or Writer()
        task = self.transport.admit(Reader(self.frame(method, **changes)), writer)
        self.assertIsNotNone(task)
        await task
        await asyncio.sleep(0)
        self.assertTrue(writer.closed and writer.joined)
        return json.loads(writer.data)

    async def raw_request(self, raw, *, eof=True):
        writer = Writer()
        task = self.transport.admit(Reader(raw, eof=eof), writer)
        await task
        await asyncio.sleep(0)
        return json.loads(writer.data)

    async def test_status_is_bounded_read_only_and_preserves_exact_objective(self):
        response = await self.request()
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"]["objective"], self.prepared.objective)
        self.assertEqual(self.runtime.commits, [])
        self.assertFalse(self.runtime.intent)
        self.assertNotIn(self.token, json.dumps(response))
        self.assertNotIn("b" * 64, json.dumps(response))

    async def test_wrong_token_host_session_task_or_request_selected_window_never_mutates(self):
        for change in ({"token": "c" * 64}, {"host_epoch": "other"}, {"session_id": "other"},
                       {"task_id": "other"}, {"hwnd": "100"}, {"token": "b" * 64}):
            with self.subTest(change=change):
                self.assertFalse((await self.request("resume", **change))["ok"])
        self.assertEqual(self.runtime.commits, [])
        self.assertFalse(self.runtime.intent)

    async def test_invalid_frames_duplicate_keys_trailing_message_and_types_refuse(self):
        valid = self.frame("pause")
        invalid = (valid + valid, valid + b"x", valid[:-1], b"\xff\n", b"[]\n", b"NaN\n",
                   valid.replace(b'"method":"pause"', b'"method":"pause","method":"resume"'),
                   valid.replace(b'"request_id":"request-1"', b'"request_id":true'),
                   b"x" * 4097 + b"\n")
        for raw in invalid:
            with self.subTest(length=len(raw)):
                self.assertFalse((await self.raw_request(raw))["ok"])
        self.assertEqual(self.runtime.commits, [])

    async def test_no_mutation_until_half_close_and_missing_eof_times_out(self):
        reader, writer = Reader(self.frame("pause"), eof=False), Writer()
        task = self.transport.admit(reader, writer)
        await asyncio.sleep(.01)
        self.assertEqual(self.runtime.commits, [])
        reader.eof.set()
        await task
        self.assertEqual(self.runtime.commits, [("request-1", "pause")])
        response = await self.raw_request(self.frame("cancel", request_id="later"), eof=False)
        self.assertEqual(response["error"], "request_timeout")
        self.assertEqual(len(self.runtime.commits), 1)

    async def test_recorded_is_distinct_from_ack_and_retry_observes_replacement_owner(self):
        response = await self.request("pause")
        self.assertTrue(response["control"]["recorded"])
        self.assertFalse(response["control"]["owner_acknowledged"])
        self.runtime.controls["request-1"].update(outcome="applied", owner_acknowledged=True)
        retried = await self.request("pause")
        self.assertTrue(retried["control"]["owner_acknowledged"])
        self.assertEqual(len(self.runtime.commits), 1)
        conflict = await self.request("resume")
        self.assertEqual(conflict["error"], "conflicting_request_id")

    async def test_disconnect_after_commit_does_not_repeat_durable_control(self):
        await self.request("cancel", writer=Writer(broken=True))
        result = await self.request("cancel")
        self.assertTrue(result["control"]["recorded"])
        self.assertEqual(self.runtime.commits, [("request-1", "cancel")])

    async def test_response_timeout_retains_mutation_and_stop_waits_for_real_join(self):
        self.runtime.release = asyncio.Event()
        self.runtime.join.clear()
        response = await self.request("resume")
        self.assertEqual(response["state"], "pending")
        self.assertIsNone(response["recorded"])
        self.assertEqual(self.transport.lifecycle()["pending_mutations"], 1)
        stop = await self.request("stop")
        self.assertTrue(stop["stop_requested"])
        self.assertTrue(self.runtime.fenced)
        self.assertFalse(stop["stop_confirmed"])
        self.assertFalse(self.runtime.join_entered.is_set())
        first_close = await self.transport.aclose(timeout=.02)
        self.assertFalse(first_close["closed"])
        self.assertEqual(first_close["pending_mutations"], 1)
        self.runtime.release.set()
        await asyncio.wait_for(self.runtime.join_entered.wait(), .2)
        self.assertFalse(self.runtime.intent)
        self.assertFalse((await self.transport.aclose(timeout=.02))["closed"])
        self.runtime.join.set()
        self.assertTrue((await self.transport.aclose(timeout=.2))["closed"])

    async def test_cancelling_client_handler_does_not_cancel_mutation(self):
        self.runtime.release = asyncio.Event()
        writer = Writer()
        handler = self.transport.admit(Reader(self.frame("pause")), writer)
        await self.runtime.entered.wait()
        operation = self.transport._records["request-1"]["task"]
        handler.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await handler
        self.assertFalse(operation.cancelled() or operation.done())
        self.runtime.release.set()
        await asyncio.wait_for(asyncio.shield(operation), .2)
        self.assertEqual(self.runtime.commits, [("request-1", "pause")])

    async def test_real_offloaded_thread_commit_survives_stream_timeout(self):
        started, release = threading.Event(), threading.Event()
        original = self.runtime.submit_control
        async def offloaded(request_id, command):
            def blocking():
                started.set()
                if not release.wait(2):
                    raise RuntimeError("fixture release missing")
            await asyncio.to_thread(blocking)
            return await original(request_id, command)
        self.runtime.submit_control = offloaded
        try:
            result = await self.request("pause")
            self.assertTrue(started.is_set())
            self.assertEqual(result["state"], "pending")
            self.assertFalse(self.transport._records["request-1"]["task"].done())
            release.set()
            await asyncio.wait_for(asyncio.shield(self.transport._records["request-1"]["task"]), .5)
            self.assertEqual(self.runtime.commits, [("request-1", "pause")])
        finally:
            release.set()

    async def test_later_pause_revokes_immediately_and_slow_resume_cannot_reactivate(self):
        self.runtime.release = asyncio.Event()
        first_writer, second_writer = Writer(), Writer()
        first = self.transport.admit(Reader(self.frame("resume", request_id="first")), first_writer)
        await self.runtime.entered.wait()
        self.runtime.intent = True
        revoked = asyncio.Event()
        original_deactivate = self.runtime.deactivate_intent
        def observe_deactivate():
            original_deactivate()
            revoked.set()
        self.runtime.deactivate_intent = observe_deactivate
        second = self.transport.admit(Reader(self.frame("pause", request_id="second")), second_writer)
        await asyncio.wait_for(revoked.wait(), .5)
        self.assertFalse(self.runtime.intent)
        self.runtime.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.runtime.commits, [("first", "resume"), ("second", "pause")])
        self.assertFalse(self.runtime.intent)
        self.assertFalse(any(isinstance(call, tuple) and call[0] == "activate" for call in self.runtime.calls))

    async def test_window_close_reopen_revokes_old_session_without_cancelling_task(self):
        await self.request("resume")
        self.assertTrue(self.runtime.intent)
        closed = await self.request("window_closed")
        self.assertFalse(closed["task_cancelled"])
        self.assertFalse(self.runtime.intent)
        self.assertEqual(len(self.runtime.commits), 1)
        self.assertFalse((await self.request())["ok"])
        self.runtime.live.add("replacement")
        self.transport.bind_session(self.capability, "replacement", "d" * 64)
        self.assertFalse((await self.request("resume", request_id="new"))["ok"])
        self.token = "d" * 64
        self.assertTrue((await self.request("window_ready", session_id="replacement"))["ok"])
        self.assertFalse(self.runtime.intent)
        with self.assertRaises(ValueError):
            self.transport.bind_session(self.capability, "session", "e" * 64)

    async def test_retained_session_lifecycle_is_required_even_with_correct_token(self):
        self.runtime.live.clear()
        self.assertFalse((await self.request("resume"))["ok"])
        self.assertEqual(self.runtime.commits, [])

    async def test_handler_cap_refuses_without_taking_unowned_stream(self):
        self.transport.max_handlers = 1
        first_reader, first_writer = Reader(self.frame(), eof=False), Writer()
        task = self.transport.admit(first_reader, first_writer)
        refused = Writer()
        self.assertIsNone(self.transport.admit(Reader(self.frame()), refused))
        self.assertFalse(refused.closed)
        # Ownership never transferred: the future listener must perform this.
        refused.close()
        await refused.wait_closed()
        first_reader.eof.set()
        await task

    async def test_mutation_and_stable_id_limits_are_not_bypassed_by_retries(self):
        self.transport.max_mutations = self.transport.max_ids = 1
        self.runtime.release = asyncio.Event()
        await self.request("pause", request_id="one")
        self.assertEqual((await self.request("cancel", request_id="two"))["error"], "capacity_exhausted")
        self.assertEqual(len(self.transport._records), 1)
        self.runtime.release.set()
        await self.transport._records["one"]["task"]
        self.assertTrue((await self.request("pause", request_id="one"))["ok"])
        self.assertEqual((await self.request("cancel", request_id="two"))["error"], "capacity_exhausted")
        self.assertEqual(len(self.runtime.commits), 1)

    async def test_unknown_commit_is_not_cleanup_success_until_explicit_same_id_resolution(self):
        self.runtime.submit_error = OSError("private internal path must not appear")
        response = await self.request("pause")
        self.assertEqual(response, {"ok": False, "error": "runtime_error"})
        self.assertEqual(self.transport.lifecycle()["unknown_mutations"], 1)
        self.runtime.submit_error = None
        self.assertTrue((await self.request("pause"))["ok"])
        self.assertEqual(self.transport.lifecycle()["unknown_mutations"], 0)
        self.assertEqual(len(self.runtime.commits), 1)

    async def test_stop_does_not_accept_unjoined_or_uncertain_runtime_receipt(self):
        self.runtime.stop_value["worker_joined"] = False
        await self.request("stop")
        state = await self.transport.aclose(timeout=.2)
        self.assertFalse(state["closed"])
        self.assertIn("stop_unresolved", state["faults"])

    async def test_close_wait_failure_remains_visible_and_never_claims_closed(self):
        writer = Writer(close_wait=asyncio.Event())
        handler = self.transport.admit(Reader(self.frame()), writer)
        with self.assertRaises(asyncio.TimeoutError):
            await handler
        await asyncio.sleep(0)
        state = await self.transport.aclose(timeout=.2)
        self.assertFalse(state["closed"])
        self.assertEqual(state["stream_close_failures"], 1)

    async def test_invalid_or_secret_status_projection_is_refused_without_logging_it(self):
        self.runtime.projection["unexpected"] = self.token
        response = await self.request()
        self.assertEqual(response, {"ok": False, "error": "projection_refused"})
        del self.runtime.projection["unexpected"]
        self.transport.prepared = PreparedTask("host", "task", "secret " + self.token)
        response = await self.request()
        self.assertEqual(response, {"ok": False, "error": "projection_refused"})

    async def test_credential_generation_and_host_binding_are_distinct_and_bounded(self):
        values = {credential() for _ in range(3)}
        self.assertEqual(len(values), 3)
        self.assertTrue(all(len(value) == 64 for value in values))
        for token in ("b" * 64, self.token, "short"):
            with self.assertRaises(ValueError):
                self.transport.bind_session(self.capability, "other", token)
        with self.assertRaises(PermissionError):
            self.transport.bind_session(object(), "other", "f" * 64)

    async def test_completed_resume_retry_does_not_reactivate_after_later_pause(self):
        await self.request("resume", request_id="old-resume")
        self.assertTrue(self.runtime.intent)
        await self.request("pause", request_id="new-pause")
        self.assertFalse(self.runtime.intent)
        self.assertTrue((await self.request("resume", request_id="old-resume"))["ok"])
        self.assertFalse(self.runtime.intent)
        self.assertEqual(len(self.runtime.commits), 2)

    async def test_rejected_resume_never_activates_presentation_intent(self):
        self.runtime.controls["rejected"] = {"request_id": "rejected", "command": "resume",
            "sequence": 1, "owner_acknowledged": True, "outcome": "rejected"}
        reply = await self.request("resume", request_id="rejected")
        self.assertEqual(reply["control"]["outcome"], "rejected")
        self.assertFalse(self.runtime.intent)

    async def test_status_projects_current_recorded_and_owner_acknowledged_controls(self):
        await self.request("pause")
        first = (await self.request())["status"]["controls"][0]
        self.assertTrue(first["recorded"])
        self.assertFalse(first["owner_acknowledged"])
        self.runtime.controls["request-1"].update(outcome="applied", owner_acknowledged=True)
        second = (await self.request())["status"]["controls"][0]
        self.assertTrue(second["owner_acknowledged"])

    async def test_runtime_cannot_inject_private_error_text_using_refusal_exception(self):
        self.runtime.submit_error = Refused("private-path-or-secret-context")
        reply = await self.request("pause")
        self.assertEqual(reply, {"ok": False, "error": "runtime_error"})

    async def test_exact_request_byte_boundary_includes_final_newline(self):
        frame = self.frame("pause")
        exact = b" " * (4096 - len(frame)) + frame
        self.assertTrue((await self.raw_request(exact))["ok"])
        oversized = b" " + exact
        self.assertFalse((await self.raw_request(oversized))["ok"])
        self.assertEqual(len(self.runtime.commits), 1)

    async def test_cancelled_close_waiter_does_not_cancel_retained_worker_join(self):
        self.runtime.join.clear()
        closer = asyncio.create_task(self.transport.aclose(timeout=1))
        await self.runtime.join_entered.wait()
        closer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closer
        self.assertFalse(self.transport._stop_task.done())
        self.assertFalse(self.transport._close_task.done())
        self.runtime.join.set()
        self.assertTrue((await self.transport.aclose(timeout=.2))["closed"])

    async def test_old_session_late_resume_commit_does_not_activate_replacement(self):
        self.runtime.release = asyncio.Event()
        await self.request("resume")
        self.runtime.live.add("replacement")
        self.transport.bind_session(self.capability, "replacement", "d" * 64)
        self.token = "d" * 64
        await self.request("window_ready", session_id="replacement")
        self.runtime.release.set()
        await self.transport._records["request-1"]["task"]
        self.assertEqual(len(self.runtime.commits), 1)
        self.assertFalse(self.runtime.intent)

    async def test_unexpected_prestart_mutation_cancellation_cannot_be_clean_shutdown(self):
        operation = self.transport._retain_control(json.loads(self.frame("pause")))
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        await asyncio.sleep(0)
        self.assertEqual(self.transport.lifecycle()["unknown_mutations"], 1)
        state = await self.transport.aclose(timeout=.2)
        self.assertFalse(state["closed"])

    async def test_first_seen_historical_resume_cannot_undo_later_durable_pause(self):
        self.runtime.controls["old-resume"] = {"request_id": "old-resume", "command": "resume",
            "sequence": 1, "outcome": "applied", "owner_acknowledged": True}
        self.runtime.controls["later-pause"] = {"request_id": "later-pause", "command": "pause",
            "sequence": 2, "outcome": "applied", "owner_acknowledged": True}
        self.runtime.projection["demand"] = "paused"
        response = await self.request("resume", request_id="old-resume")
        self.assertTrue(response["ok"])
        self.assertEqual(self.runtime.commits, [])
        self.assertFalse(self.runtime.intent)

    async def test_prestart_handler_cancellation_retains_and_joins_owned_stream(self):
        writer = Writer()
        handler = self.transport.admit(Reader(self.frame()), writer)
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        state = await self.transport.aclose(timeout=.2)
        self.assertTrue(writer.closed and writer.joined)
        self.assertTrue(state["closed"])

    async def test_prestart_cleanup_holds_capacity_until_close_is_joined(self):
        self.transport.max_handlers = 1
        release = asyncio.Event()
        writer = Writer(close_wait=release)
        handler = self.transport.admit(Reader(self.frame()), writer)
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        await asyncio.sleep(0)
        rejected = Writer()
        self.assertIsNone(self.transport.admit(Reader(self.frame()), rejected))
        rejected.close()
        await rejected.wait_closed()
        self.assertEqual(self.transport.lifecycle()["pending_connections"], 1)
        release.set()
        self.assertTrue((await self.transport.aclose(timeout=.2))["closed"])

    async def test_prestart_cleanup_failure_is_retained_and_prevents_success(self):
        self.transport.max_handlers = 1
        writer = Writer(close_wait=asyncio.Event())
        handler = self.transport.admit(Reader(self.frame()), writer)
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        state = await self.transport.aclose(timeout=.2)
        self.assertTrue(writer.closed)
        self.assertFalse(writer.joined or state["closed"])
        self.assertEqual(state["pending_connections"], 1)
        self.assertEqual(state["stream_close_failures"], 1)
        self.assertIn("stream_close_failed", state["faults"])

    async def test_resume_authority_requires_exact_true(self):
        async def wrong_type(request_id):
            return {"allowed": True}
        self.runtime.resume_authority = wrong_type
        self.assertTrue((await self.request("resume"))["ok"])
        self.assertFalse(self.runtime.intent)

    async def test_pause_arriving_during_authority_read_fences_late_activation(self):
        self.runtime.authority_release = asyncio.Event()
        first = self.transport.admit(Reader(self.frame("resume", request_id="first")), Writer())
        await self.runtime.authority_entered.wait()
        await self.request("pause", request_id="second")
        self.runtime.authority_release.set()
        await first
        await self.transport._records["second"]["task"]
        self.assertFalse(self.runtime.intent)
        self.assertEqual(self.runtime.commits, [("first", "resume"), ("second", "pause")])

    async def test_terminal_or_unknown_target_cannot_authorize_resume(self):
        for key, value in (("task_status", "accepted"), ("demand", "cancelled"),
                           ("demand", "fulfilled"), ("waiting_reason", "reconciliation"),
                           ("demand", None), ("waiting_reason", "unknown")):
            before = dict(self.runtime.projection)
            self.runtime.projection[key] = value
            await self.request("resume", request_id="id-" + key + "-" + str(value))
            self.assertFalse(self.runtime.intent)
            self.runtime.projection = before


if __name__ == "__main__":
    unittest.main(verbosity=2)
