"""Durable task ownership and interruption boundaries, without a model service."""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from adaptive_inference.task_store import (
    APPLICATION_ID, MAX_RECORD_BYTES, SCHEMA_VERSION, InvalidStoreError,
    OwnershipError, ReconciliationRequired, RevisionConflict, TaskBusyError,
    TaskStore, TaskStoreError, TerminalTaskError,
)


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.sqlite"
        self.store = TaskStore(self.path)
        self.original = "Produce exactly the requested report; retain the cited evidence."
        self.initial = self.store.create("task", self.original, max_attempts=3,
            metadata={"generator": "fixed-test-1", "validator": "report-v2"})

    def claim(self):
        return self.store.claim("task", expected_revision=self.store.load("task").revision)

    def test_original_rejections_output_and_terminal_survive_reopening(self):
        with self.claim() as owned:
            state = copy.deepcopy(owned.checkpoint.state)
            state.update(attempts=1, phase="generating")
            started = owned.begin_operation("generation", state=state,
                expected_revision=owned.checkpoint.revision)
            state.update(output="draft without citation", phase="awaiting_validation")
            done = owned.complete_operation(started.operation["id"], result={"output": state["output"]},
                state=state, expected_revision=started.revision)
            durable = TaskStore(self.path).load("task")
            self.assertEqual(durable.state["output"], "draft without citation")
            self.assertIsNone(durable.operation)
            started = owned.begin_operation("validation", expected_revision=done.revision)
            state["feedback"].append("Include the missing source citation")
            state["messages"].extend([{"role": "assistant", "content": state["output"]},
                                      {"role": "user", "content": state["feedback"][0]}])
            state["phase"] = "ready"
            done = owned.complete_operation(started.operation["id"], result={"accepted": False},
                state=state, expected_revision=started.revision)
            state.update(attempts=2, output="report with source", status="accepted")
            accepted = owned.save_checkpoint(state, expected_revision=done.revision)
            for action in (
                lambda: owned.begin_operation("effect", expected_revision=accepted.revision),
                lambda: owned.save_checkpoint(state, expected_revision=accepted.revision),
            ):
                with self.assertRaises(TerminalTaskError):
                    action()
        reopened = TaskStore(self.path)
        loaded = reopened.load("task")
        self.assertEqual(loaded.prompt, self.original)
        self.assertEqual(loaded.metadata, self.initial.metadata)
        self.assertEqual(loaded.state["messages"][0]["content"], self.original)
        self.assertEqual(loaded.state["attempts"], 2)
        self.assertEqual(loaded.state["feedback"], ["Include the missing source citation"])
        history = reopened.history("task")
        self.assertEqual(history[0]["payload"]["prompt"], self.original)
        self.assertIn("draft without citation", json.dumps(history))
        self.assertIn('"accepted": false', json.dumps(history))
        with reopened.claim("task", expected_revision=loaded.revision) as owned:
            self.assertEqual(owned.checkpoint.revision, loaded.revision)
        self.assertEqual(reopened.history("task"), history)

    def test_active_owner_stale_revision_and_closed_handle_are_fenced(self):
        with self.claim() as owned:
            with self.assertRaises(TaskBusyError):
                with TaskStore(self.path).claim("task", expected_revision=owned.checkpoint.revision):
                    self.fail("A second runner acquired the same task")
            state = copy.deepcopy(owned.checkpoint.state)
            state["phase"] = "ready"
            old_revision = owned.checkpoint.revision
            new = owned.save_checkpoint(state, expected_revision=old_revision)
            with self.assertRaises(RevisionConflict):
                owned.save_checkpoint(state, expected_revision=old_revision)
        with self.assertRaises(OwnershipError):
            owned.save_checkpoint(state, expected_revision=new.revision)
        with self.assertRaises(RevisionConflict):
            with self.store.claim("task", expected_revision=old_revision):
                self.fail("Stale claim succeeded")

    def test_owner_epoch_is_checked_even_if_revision_is_current(self):
        with self.claim() as owned:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE tasks SET owner_epoch=?", ("f" * 32,))
            with self.assertRaises(OwnershipError):
                owned.begin_operation("effect", expected_revision=owned.checkpoint.revision)

    def test_interrupted_effect_needs_explicit_evidence_never_retries(self):
        with self.claim() as owned:
            effect = owned.begin_operation("effect", details={"operation": "delivery"},
                expected_revision=owned.checkpoint.revision)
        with self.claim() as owned:
            checkpoint = owned.checkpoint
            self.assertTrue(checkpoint.requires_reconciliation)
            self.assertEqual(checkpoint.operation, effect.operation)
            for action in (
                lambda: owned.begin_operation("generation", expected_revision=checkpoint.revision),
                lambda: owned.save_checkpoint(checkpoint.state, expected_revision=checkpoint.revision),
                lambda: owned.complete_operation(effect.operation["id"], result="sent", state=checkpoint.state,
                                                  expected_revision=checkpoint.revision),
                lambda: owned.retry_generation(effect.operation["id"], expected_revision=checkpoint.revision),
            ):
                with self.assertRaises(ReconciliationRequired):
                    action()
            with self.assertRaises(ValueError):
                owned.reconcile_operation(effect.operation["id"], resolution="completed", result=None,
                    state=checkpoint.state, expected_revision=checkpoint.revision)
            state = copy.deepcopy(checkpoint.state)
            state.update(status="accepted", output="delivery confirmed")
            resolved = owned.reconcile_operation(effect.operation["id"], resolution="completed",
                result={"external_receipt": "delivery-1"}, state=state, expected_revision=checkpoint.revision)
            self.assertIsNone(resolved.operation)
            self.assertFalse(resolved.requires_reconciliation)
        event = self.store.history("task")[-1]
        self.assertEqual(event["event"], "operation_reconciled")
        self.assertEqual(event["payload"]["event_data"]["operation"], effect.operation)
        self.assertEqual(event["payload"]["event_data"]["result"], {"external_receipt": "delivery-1"})

    def test_only_pure_generation_retry_preserves_consumed_attempt(self):
        with self.claim() as owned:
            state = copy.deepcopy(owned.checkpoint.state)
            state.update(attempts=1, phase="generating")
            operation = owned.begin_operation("generation", state=state, expected_revision=owned.checkpoint.revision)
            with self.assertRaises(ReconciliationRequired):
                owned.retry_generation(operation.operation["id"], expected_revision=operation.revision)
        with self.claim() as owned:
            before = owned.checkpoint
            state["phase"] = "ready"
            retried = owned.retry_generation(before.operation["id"], state=state, expected_revision=before.revision)
            self.assertEqual(retried.state["attempts"], 1)
            self.assertEqual(retried.state["phase"], "ready")
            self.assertIsNone(retried.operation)
            state["attempts"] = 0
            with self.assertRaises(ValueError):
                owned.save_checkpoint(state, expected_revision=retried.revision)
            state["attempts"] = 2
            active = owned.begin_operation("validation", state=state, expected_revision=retried.revision)
        with self.claim() as owned:
            with self.assertRaises(ReconciliationRequired):
                owned.retry_generation(active.operation["id"], expected_revision=owned.checkpoint.revision)
        self.assertIn("generation_retry_authorized", [row["event"] for row in self.store.history("task")])

    def test_malformed_or_oversized_updates_are_atomic_and_history_is_append_only(self):
        with self.claim() as owned:
            valid = owned.checkpoint
            history = self.store.history("task")
            variants = []
            for changes in ({"output": "x" * MAX_RECORD_BYTES}, {"attempts": True}, {"attempts": 4},
                            {"status": "exhausted"}, {"arbitrary": float("nan")},
                            {"messages": [{"role": "user", "content": "replace task"}]}):
                state = copy.deepcopy(valid.state)
                state.update(changes)
                variants.append(state)
            variants.extend([None, [], {"status": "pending"}])
            for state in variants:
                with self.subTest(state_type=type(state).__name__):
                    with self.assertRaises(ValueError):
                        owned.save_checkpoint(state, expected_revision=valid.revision)
                    self.assertEqual(self.store.load("task").revision, valid.revision)
                    self.assertEqual(self.store.history("task"), history)
            state = copy.deepcopy(valid.state)
            state["feedback"].append("Preserve this feedback")
            state["messages"].append({"role": "user", "content": "Preserve this follow-up"})
            updated = owned.save_checkpoint(state, expected_revision=valid.revision)
            with self.assertRaises(ValueError):
                owned.save_checkpoint(valid.state, expected_revision=updated.revision)
        with self.assertRaises(RevisionConflict):
            self.store.create("task", "replacement")
        self.assertEqual(self.store.load("task").prompt, self.original)

    def test_history_limit_refuses_without_partial_checkpoint(self):
        with self.claim() as owned:
            checkpoint = owned.checkpoint
            with patch("adaptive_inference.task_store.MAX_REVISIONS", checkpoint.revision + 1):
                with self.assertRaises(TaskStoreError):
                    owned.save_checkpoint(checkpoint.state, expected_revision=checkpoint.revision)
            self.assertEqual(self.store.load("task").revision, checkpoint.revision)

    def test_foreign_corrupt_and_unsupported_database_bytes_are_unchanged(self):
        foreign = Path(self.directory.name) / "foreign.sqlite"
        with closing(sqlite3.connect(foreign)) as db, db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
            db.execute("INSERT INTO unrelated VALUES ('retain me')")
        invalid = Path(self.directory.name) / "invalid.sqlite"
        invalid.write_bytes(b"not a database" * 100)
        unsupported = Path(self.directory.name) / "unsupported.sqlite"
        TaskStore(unsupported)
        with closing(sqlite3.connect(unsupported)) as db, db:
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        same_header = Path(self.directory.name) / "foreign-same-header.sqlite"
        with closing(sqlite3.connect(same_header)) as db, db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        for path in (foreign, invalid, unsupported, same_header):
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.subTest(path=path.name), self.assertRaises(InvalidStoreError):
                TaskStore(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_declared_sqlite_durability_and_bounds_are_applied(self):
        with self.store._connection(write=True) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            pages = db.execute("PRAGMA max_page_count").fetchone()[0]
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            self.assertLessEqual(pages * page_size, 64 * 1024 * 1024)

    def _child(self, source, *arguments):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        return subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-B", "-c", source,
                                 str(self.path), *map(str, arguments)], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _finish_child(self, child, *, kill=False):
        if kill and child.poll() is None:
            child.kill()
        try:
            return child.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=10)
            self.fail("Bounded subprocess did not finish")

    def test_real_process_death_releases_lock_but_preserves_uncertain_effect(self):
        marker = Path(self.directory.name) / "effect.txt"
        child = self._child('''
import os, pathlib, sys, time
from adaptive_inference.task_store import TaskStore
s = TaskStore(sys.argv[1]); c = s.load('task')
with s.claim('task', expected_revision=c.revision) as owned:
    owned.begin_operation('effect', details={'delivery': 1}, expected_revision=owned.checkpoint.revision)
    with open(sys.argv[2], 'a', encoding='utf-8') as f:
        f.write('delivered once\\n'); f.flush(); os.fsync(f.fileno())
    time.sleep(30)
''', marker)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.exists(), "Child never reached its committed operation/effect boundary")
            with self.assertRaises(TaskBusyError):
                with self.claim():
                    self.fail("Live child lost ownership")
        finally:
            self._finish_child(child, kill=True)
        self.assertIsNotNone(child.returncode)
        reopened = self._child('''
import json, sys
from adaptive_inference.task_store import TaskStore, ReconciliationRequired
s = TaskStore(sys.argv[1]); c = s.load('task')
with s.claim('task', expected_revision=c.revision) as owned:
    assert owned.checkpoint.requires_reconciliation
    try:
        owned.begin_operation('effect', expected_revision=owned.checkpoint.revision)
    except ReconciliationRequired:
        print(json.dumps({'prompt': owned.checkpoint.prompt, 'blocked': True}))
    else:
        raise AssertionError('effect could repeat')
''')
        stdout, stderr = self._finish_child(reopened)
        self.assertEqual(reopened.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), {"prompt": self.original, "blocked": True})
        self.assertEqual(marker.read_text().splitlines(), ["delivered once"])

    def test_actual_hot_journal_rolls_back_uncommitted_state_and_history(self):
        before = self.store.load("task")
        history = self.store.history("task")
        child = self._child('''
import json, os, sys
from adaptive_inference.task_store import TaskStore
s = TaskStore(sys.argv[1])
with s._connection(write=True) as db:
    db.execute('PRAGMA cache_size=4')
    state = json.loads(db.execute("SELECT state FROM tasks WHERE task_id='task'").fetchone()[0])
    state['output'] = 'uncommitted-' * 60000
    db.execute("UPDATE tasks SET state=?,revision=1 WHERE task_id='task'", (json.dumps(state),))
    db.execute("INSERT INTO history VALUES ('task',1,'uncommitted',?)", (json.dumps({'state': state}),))
    os._exit(19)
''')
        _, stderr = self._finish_child(child)
        self.assertEqual(child.returncode, 19, stderr)
        journal = Path(str(self.path) + "-journal")
        self.assertTrue(journal.exists())
        self.assertGreater(journal.stat().st_size, 512)
        self.assertNotEqual(journal.read_bytes()[:8], b"\0" * 8, "Probe must leave a real hot journal")
        reopened = TaskStore(self.path)
        after = reopened.load("task")
        self.assertEqual(after, before)
        self.assertEqual(reopened.history("task"), history)
        self.assertFalse(journal.exists())
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
