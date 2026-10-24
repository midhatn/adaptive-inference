"""Bounded local task checkpoints, exclusive runners, and interrupted-operation receipts.

The per-operation SQLite/BEGIN IMMEDIATE/revision-check pattern is adapted from
medking82's Strata PR #1136, serve/chat_archive.py at
64d119cd602ddc439c311dedf61fda460f2785ef (MIT):
https://github.com/medking82/Strata/blob/64d119cd602ddc439c311dedf61fda460f2785ef/serve/chat_archive.py
Copyright (c) 2026 Niko1221 and the Strata contributors; see third_party/strata/LICENSE.
The OS ownership lock and interrupted-operation ledger are new, not upstream
archive capabilities. This module never executes a tool or retries work.

Use a private directory on a local filesystem. Locks coordinate cooperating
runners using this API; they cannot fence unrelated executors, prove an external
effect's outcome, or guarantee power-loss survival on every filesystem/device.
Do not delete lock files while runners may exist. The original objective,
identity metadata, checkpoint history and operation receipts are retained.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid


MAX_DB_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_TASKS = 1000
MAX_REVISIONS = 256
APPLICATION_ID = 0x4149544B
SCHEMA_VERSION = 1
_SCHEMA = {
    "tasks": "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, prompt TEXT NOT NULL, max_attempts INTEGER NOT NULL, metadata TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, owner_epoch TEXT, inflight TEXT, reconciliation INTEGER NOT NULL)",
    "history": "CREATE TABLE history (task_id TEXT NOT NULL REFERENCES tasks(task_id), revision INTEGER NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(task_id, revision))",
}


class TaskStoreError(RuntimeError):
    pass


class TaskBusyError(TaskStoreError):
    pass


class RevisionConflict(TaskStoreError):
    pass


class ReconciliationRequired(TaskStoreError):
    pass


class TerminalTaskError(TaskStoreError):
    pass


class InvalidStoreError(TaskStoreError):
    pass


class OwnershipError(TaskStoreError):
    pass


@dataclass(frozen=True, slots=True)
class Checkpoint:
    task_id: str
    prompt: str
    max_attempts: int
    metadata: dict
    revision: int
    state: dict
    operation: dict | None
    requires_reconciliation: bool
    owner_epoch: str | None


def _task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("task_id must be 1-128 identifier characters")
    return value


def _json(value):
    count = 0

    def visit(item, depth):
        nonlocal count
        count += 1
        if count > 10000 or depth > 32:
            raise ValueError("Checkpoint JSON exceeds structural bounds")
        kind = type(item)
        if kind is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("Checkpoint object keys must be strings")
            for child in item.values():
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("Checkpoint numbers must be finite")
        elif kind not in (str, int, bool, type(None)):
            raise ValueError("Checkpoint values must be JSON types")
    visit(value, 0)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("Checkpoint record exceeds 1 MiB")
    return raw


def _copy(value):
    return json.loads(_json(value))


def _state(value, prompt, maximum, previous=None):
    value = _copy(value)
    if type(value) is not dict or not {"status", "messages", "attempts", "feedback", "output"} <= value.keys():
        raise ValueError("Checkpoint state requires status, messages, attempts, feedback and output")
    if value["status"] not in ("pending", "accepted", "exhausted"):
        raise ValueError("Unknown task status")
    if type(value["attempts"]) is not int or not 0 <= value["attempts"] <= maximum:
        raise ValueError("Task attempts exceed the declared bound")
    if value["status"] == "exhausted" and value["attempts"] != maximum:
        raise ValueError("Exhausted status requires the declared attempt limit")
    messages, feedback = value["messages"], value["feedback"]
    if (type(messages) is not list or not 1 <= len(messages) <= 1000
            or messages[0] != {"role": "user", "content": prompt}
            or any(type(row) is not dict for row in messages)):
        raise ValueError("Messages must retain the exact original task as their first entry")
    if (type(feedback) is not list or len(feedback) > 20
            or any(type(row) is not str for row in feedback) or type(value["output"]) is not str):
        raise ValueError("Feedback and output must remain bounded text")
    if previous is not None:
        if (value["attempts"] < previous["attempts"]
                or messages[:len(previous["messages"])] != previous["messages"]
                or feedback[:len(previous["feedback"])] != previous["feedback"]):
            raise ValueError("A checkpoint cannot discard task history, feedback or attempts")
    return value


class _FileLock:
    """A stable sidecar, never unlinked while another process could open it."""

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.held = False
        self.pid = os.getpid()
        try:
            os.set_inheritable(self.fd, False)
            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b"0")
            os.lseek(self.fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.held = True
        except OSError as exc:
            os.close(self.fd)
            raise TaskBusyError("A cooperating runner already owns this task/store") from exc

    def close(self):
        if self.held:
            self.held = False
            try:
                # A forked child must close its duplicate without unlocking the
                # parent's shared lock description. Non-inheritable handles
                # additionally keep ordinary spawned/executed children out.
                if self.pid != os.getpid():
                    return
                os.lseek(self.fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)


class TaskStore:
    """A versioned, private SQLite file; foreign/corrupt stores are never repaired."""

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.parent.is_dir():
            raise ValueError("The task store's private parent directory must exist")
        init_lock = _FileLock(str(self.path) + ".init.lock")
        try:
            if self.path.exists():
                self._verify_existing()
            else:
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                # An interrupted first initialization leaves evidence that is
                # refused on reopen, not a file silently reset as a new store.
                db = sqlite3.connect(self.path, timeout=5)
                try:
                    with db:
                        if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                            raise InvalidStoreError("Task store requires DELETE journaling")
                        db.execute("PRAGMA synchronous=FULL")
                        db.execute("BEGIN IMMEDIATE")
                        for statement in _SCHEMA.values():
                            db.execute(statement)
                        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                finally:
                    db.close()
                self._verify_existing()
        except sqlite3.Error as exc:
            raise InvalidStoreError("Cannot initialize or read task store") from exc
        finally:
            init_lock.close()

    @staticmethod
    def _verify_schema(db):
        if (db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION):
            raise InvalidStoreError("Foreign or unsupported task store schema")
        actual = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        if actual != _SCHEMA:
            raise InvalidStoreError("Task store schema changed")

    def _verify_existing(self):
        if not self.path.is_file() or not 100 <= self.path.stat().st_size <= MAX_DB_BYTES:
            raise InvalidStoreError("Invalid or oversized task store file")
        with self.path.open("rb") as handle:
            header = handle.read(100)
            if header[:16] != b"SQLite format 3\0":
                raise InvalidStoreError("Task store is not a SQLite database")
            if (int.from_bytes(header[68:72], "big") != APPLICATION_ID
                    or int.from_bytes(header[60:64], "big") != SCHEMA_VERSION):
                raise InvalidStoreError("Foreign or unsupported task store header")
        try:
            # Our schema never changes after initialization. Check that static
            # identity without rollback/recovery first: ordinary mode=ro can
            # reject a recoverable hot journal because recovery needs writes.
            # Do not inspect task payloads through immutable=1: those pages can
            # contain uncommitted changes until SQLite rolls the journal back.
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)
            try:
                self._verify_schema(db)
            finally:
                db.close()
            # Only the exact identified schema may now recover its own journal.
            # No persistent PRAGMA or application-level repair is performed.
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
            try:
                self._verify_schema(db)
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise InvalidStoreError("Task store integrity check failed")
            finally:
                db.close()
        except sqlite3.Error as exc:
            raise InvalidStoreError("Task store cannot be verified or recovered by SQLite") from exc

    @contextmanager
    def _connection(self, *, write=False):
        # Identity checks precede persistent PRAGMA changes on an existing file.
        self._verify_existing()
        db = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                             uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            self._verify_schema(db)
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                    raise InvalidStoreError("Task store requires DELETE journaling")
                db.execute("PRAGMA synchronous=FULL")
                page_size = db.execute("PRAGMA page_size").fetchone()[0]
                db.execute(f"PRAGMA max_page_count={MAX_DB_BYTES // page_size}")
                db.execute("BEGIN IMMEDIATE")
            else:
                db.execute("BEGIN")
            yield db
            db.commit()
        except sqlite3.Error as exc:
            db.rollback()
            raise TaskStoreError("Task store transaction failed; no partial checkpoint adopted") from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (_task_id(task_id),)).fetchone()
        if row is None:
            raise KeyError(task_id)
        try:
            if (type(row["prompt"]) is not str or not row["prompt"].strip()
                    or len(row["prompt"].encode("utf-8")) > 256 * 1024
                    or type(row["max_attempts"]) is not int or not 1 <= row["max_attempts"] <= 20
                    or type(row["revision"]) is not int or not 0 <= row["revision"] < MAX_REVISIONS
                    or row["reconciliation"] not in (0, 1)
                    or (row["owner_epoch"] is not None and not re.fullmatch(r"[0-9a-f]{32}", row["owner_epoch"]))):
                raise ValueError("Invalid stored identity or bounds")
            state = _state(json.loads(row["state"]), row["prompt"], row["max_attempts"])
            metadata = _copy(json.loads(row["metadata"]))
            operation = _copy(json.loads(row["inflight"])) if row["inflight"] is not None else None
            if (type(metadata) is not dict or (operation is not None and
                    (type(operation) is not dict or set(operation) != {"id", "kind", "details"}
                     or type(operation["id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", operation["id"])
                     or operation["kind"] not in ("generation", "validation", "effect")))
                    or (row["reconciliation"] and operation is None)
                    or (state["status"] != "pending" and operation is not None)):
                raise ValueError("Invalid stored records")
            return Checkpoint(row["task_id"], row["prompt"], row["max_attempts"], metadata,
                              row["revision"], state, operation, bool(row["reconciliation"]), row["owner_epoch"])
        except (ValueError, TypeError, RecursionError) as exc:
            raise InvalidStoreError("Task checkpoint data is invalid") from exc

    def create(self, task_id, prompt, *, max_attempts=3, metadata=None, state=None):
        _task_id(task_id)
        if type(prompt) is not str or not prompt.strip() or len(prompt.encode("utf-8")) > 256 * 1024:
            raise ValueError("An original prompt of at most 256 KiB is required")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        metadata = {} if metadata is None else _copy(metadata)
        if type(metadata) is not dict:
            raise ValueError("Task identity metadata must be an object")
        state = _state(state if state is not None else {
            "status": "pending", "messages": [{"role": "user", "content": prompt}],
            "attempts": 0, "feedback": [], "output": "",
        }, prompt, max_attempts)
        payload = _json({"prompt": prompt, "max_attempts": max_attempts, "metadata": metadata,
                         "state": state, "operation": None})
        with self._connection(write=True) as db:
            if db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
                raise RevisionConflict("Task already exists; load it instead of replacing its original objective")
            if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= MAX_TASKS:
                raise TaskStoreError("Task count limit reached")
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)",
                       (task_id, prompt, max_attempts, _json(metadata), 0, _json(state), None, None, 0))
            db.execute("INSERT INTO history VALUES (?,?,?,?)", (task_id, 0, "created", payload))
            return self._read(db, task_id)

    def load(self, task_id):
        with self._connection() as db:
            return self._read(db, task_id)

    def history(self, task_id):
        with self._connection() as db:
            self._read(db, task_id)
            return tuple({"revision": row[0], "event": row[1], "payload": json.loads(row[2])}
                         for row in db.execute("SELECT revision,event,payload FROM history WHERE task_id=? ORDER BY revision", (task_id,)))

    @staticmethod
    def _revision(snapshot, expected):
        if type(expected) is not int or expected != snapshot.revision:
            raise RevisionConflict("Task revision changed; reload before acting")

    def _write(self, db, before, *, state, operation, reconciliation, epoch, event, event_data=None):
        if before.revision + 1 >= MAX_REVISIONS:
            raise TaskStoreError("Task checkpoint history limit reached")
        state = _state(state, before.prompt, before.max_attempts, before.state)
        payload = _json({"state": state, "operation": operation,
                         "requires_reconciliation": reconciliation, "event_data": event_data})
        revision = before.revision + 1
        count = db.execute("UPDATE tasks SET revision=?,state=?,owner_epoch=?,inflight=?,reconciliation=? WHERE task_id=? AND revision=? AND owner_epoch IS ?",
                           (revision, _json(state), epoch, _json(operation) if operation is not None else None,
                            int(reconciliation), before.task_id, before.revision, before.owner_epoch)).rowcount
        if count != 1:
            raise RevisionConflict("Task revision changed")
        db.execute("INSERT INTO history VALUES (?,?,?,?)", (before.task_id, revision, event, payload))
        return self._read(db, before.task_id)

    @contextmanager
    def claim(self, task_id, *, expected_revision, owner_id="runner"):
        _task_id(task_id)
        if type(owner_id) is not str or not 1 <= len(owner_id) <= 128:
            raise ValueError("owner_id must be a short nonempty label")
        # Never allow aliases of a task id to create independent lock paths.
        lock_path = str(self.path) + ".task-" + hashlib.sha256(task_id.encode()).hexdigest() + ".lock"
        lock = _FileLock(lock_path)
        owned = None
        try:
            with self._connection(write=True) as db:
                before = self._read(db, task_id)
                self._revision(before, expected_revision)
                terminal = before.state["status"] in ("accepted", "exhausted")
                epoch = None if terminal else uuid.uuid4().hex
                snapshot = before if terminal else self._write(db, before, state=before.state,
                    operation=before.operation, reconciliation=before.operation is not None,
                    epoch=epoch, event="claimed", event_data={"owner_id": owner_id})
            owned = OwnedTask(self, snapshot, epoch, lock)
            yield owned
        finally:
            try:
                if owned is not None:
                    owned._closed = True
                    if owned._epoch is not None and owned._pid == os.getpid():
                        with self._connection(write=True) as db:
                            # Ownership metadata release is not a content revision.
                            # An unfinished operation remains explicitly blocked.
                            db.execute("UPDATE tasks SET owner_epoch=NULL,reconciliation=CASE WHEN inflight IS NULL THEN 0 ELSE 1 END WHERE task_id=? AND owner_epoch=?",
                                       (task_id, owned._epoch))
            finally:
                lock.close()


class OwnedTask:
    """Only valid inside TaskStore.claim; an epoch also fences stale checkpoints."""

    def __init__(self, store, checkpoint, epoch, lock):
        self._store, self.checkpoint, self._epoch, self._lock = store, checkpoint, epoch, lock
        self._closed = False
        self._pid = os.getpid()

    def _check(self, db, expected_revision):
        if self._closed or not self._lock.held or self._pid != os.getpid():
            raise OwnershipError("Task runner ownership has ended or belongs to another process")
        current = self._store._read(db, self.checkpoint.task_id)
        self._store._revision(current, expected_revision)
        if current.state["status"] in ("accepted", "exhausted"):
            raise TerminalTaskError("Accepted and exhausted tasks are immutable")
        if self._epoch is None or current.owner_epoch != self._epoch:
            raise OwnershipError("Task runner ownership changed")
        return current

    def _change(self, expected_revision, action):
        with self._store._connection(write=True) as db:
            current = self._check(db, expected_revision)
            arguments = action(current)
            snapshot = self._store._write(db, current, epoch=self._epoch, **arguments)
        self.checkpoint = snapshot
        return snapshot

    def save_checkpoint(self, state, *, expected_revision):
        def action(current):
            if current.operation is not None or current.requires_reconciliation:
                raise ReconciliationRequired("Finish or explicitly reconcile the pending operation first")
            return dict(state=state, operation=None, reconciliation=False, event="checkpoint")
        return self._change(expected_revision, action)

    def begin_operation(self, kind, *, details=None, state=None, expected_revision):
        if kind not in ("generation", "validation", "effect"):
            raise ValueError("Operation kind must be generation, validation or effect")
        # 'generation' is an explicit host declaration: no tools/effects may be
        # hidden inside it. Only that kind has an opt-in retry path after a crash.
        operation = {"id": uuid.uuid4().hex, "kind": kind, "details": _copy(details)}
        def action(current):
            if current.operation is not None or current.requires_reconciliation:
                raise ReconciliationRequired("A pending operation must be reconciled before new work")
            next_state = current.state if state is None else state
            if type(next_state) is not dict or next_state.get("status") != "pending":
                raise ValueError("An operation may start only in pending state")
            return dict(state=next_state, operation=operation, reconciliation=False, event="operation_started")
        return self._change(expected_revision, action)

    @staticmethod
    def _operation(current, operation_id):
        if current.operation is None or current.operation.get("id") != operation_id:
            raise RevisionConflict("The expected in-flight operation does not match")

    def complete_operation(self, operation_id, *, result, state, expected_revision):
        result = _copy(result)
        def action(current):
            self._operation(current, operation_id)
            if current.requires_reconciliation:
                raise ReconciliationRequired("Interrupted work requires explicit reconciliation")
            return dict(state=state, operation=None, reconciliation=False, event="operation_completed",
                        event_data={"operation": current.operation, "result": result})
        return self._change(expected_revision, action)

    def reconcile_operation(self, operation_id, *, resolution, result, state, expected_revision):
        if resolution not in ("completed", "not_performed") or result is None:
            raise ValueError("Reconciliation requires a resolution and explicit caller evidence")
        result = _copy(result)
        def action(current):
            self._operation(current, operation_id)
            if not current.requires_reconciliation:
                raise ReconciliationRequired("Only an interrupted operation can be reconciled")
            return dict(state=state, operation=None, reconciliation=False, event="operation_reconciled",
                        event_data={"operation": current.operation, "resolution": resolution, "result": result})
        return self._change(expected_revision, action)

    def retry_generation(self, operation_id, *, expected_revision, state=None):
        """Explicit host opt-in only; preserve the interrupted attempt/receipt."""
        def action(current):
            self._operation(current, operation_id)
            if not current.requires_reconciliation or current.operation.get("kind") != "generation":
                raise ReconciliationRequired("Only interrupted, declared pure generation may be retried")
            return dict(state=current.state if state is None else state, operation=None,
                        reconciliation=False, event="generation_retry_authorized",
                        event_data={"operation": current.operation, "outcome": "unknown"})
        return self._change(expected_revision, action)
