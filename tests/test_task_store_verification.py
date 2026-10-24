"""Actual bounded SQLite/OS-lock regressions; no model, GPU, native owner or UI."""
from contextlib import contextmanager
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from adaptive_inference import task_store as module
from adaptive_inference.task_store import InvalidStoreError, TaskBusyError, TaskStore


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="store-verification-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "tasks.sqlite"
        self.store = TaskStore(self.path)
        self.initial = self.store.create("task", "Keep the original objective and all history.")

    def child(self, source, path=None, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-B", "-c",
                                 source, str(path or self.path), *map(str, args)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.finish, proc)
        return proc

    def finish(self, proc):
        if proc.poll() is None:
            proc.kill()
        return proc.communicate(timeout=10)

    def wait_child(self, proc, expected):
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.finish(proc)
            self.fail("Owned fixture child exceeded its deadline")
        self.assertEqual(proc.returncode, expected, stderr)
        return stdout

    def hot(self, path=None, *, replace_foreign_schema=False):
        path = path or self.path
        proc = self.child('''
import json, os, sqlite3, sys
from adaptive_inference.task_store import _SCHEMA
db=sqlite3.connect(sys.argv[1]); db.execute('PRAGMA cache_size=1')
db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
if sys.argv[2]=='replace':
    db.execute('DROP TABLE unrelated')
    for sql in _SCHEMA.values(): db.execute(sql)
    for i in range(12):
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)',
                   (str(i),'uncommitted',3,'{}',0,'x'*100000,None,None,0))
else:
    table=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if ('unrelated',) in table:
        db.execute('UPDATE unrelated SET value=?', ('uncommitted-'*60000,))
    else:
        state=json.loads(db.execute("SELECT state FROM tasks WHERE task_id='task'").fetchone()[0])
        state['output']='uncommitted-'*60000
        db.execute("UPDATE tasks SET state=?,revision=1 WHERE task_id='task'", (json.dumps(state),))
        db.execute("INSERT INTO history VALUES ('task',1,'uncommitted',?)", (json.dumps({'state':state}),))
os._exit(19)
''', path, "replace" if replace_foreign_schema else "plain")
        self.wait_child(proc, 19)
        journal = Path(str(path) + "-journal")
        self.assertTrue(journal.is_file())
        self.assertGreater(journal.stat().st_size, 512)
        self.assertEqual(journal.read_bytes()[:8], module._JOURNAL_MAGIC)
        return journal

    @staticmethod
    def hashes(*paths):
        return tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)

    def foreign(self):
        path = self.root / "foreign.sqlite"
        db = sqlite3.connect(path)
        try:
            with db:
                db.execute("CREATE TABLE unrelated (value TEXT)")
                db.execute("INSERT INTO unrelated VALUES (?)", ("retain-" * 20000,))
                db.execute(f"PRAGMA application_id={module.APPLICATION_ID}")
                db.execute(f"PRAGMA user_version={module.SCHEMA_VERSION}")
        finally:
            db.close()
        return path

    def test_normal_verification_uses_read_transaction_without_raw_open_or_immutable(self):
        calls, traces = [], []
        real_connect, real_open = sqlite3.connect, Path.open
        def connect(database, *args, **kwargs):
            calls.append(str(database))
            db = real_connect(database, *args, **kwargs)
            rows = []
            traces.append(rows)
            db.set_trace_callback(rows.append)
            return db
        def path_open(path, *args, **kwargs):
            if path == self.path:
                raise AssertionError("normal verification opened the raw database")
            return real_open(path, *args, **kwargs)
        with mock.patch.object(module.sqlite3, "connect", side_effect=connect), \
                mock.patch.object(Path, "open", path_open):
            self.assertEqual(self.store.load("task"), self.initial)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("mode=ro" in uri and "immutable" not in uri for uri in calls))
        self.assertEqual(traces[0][:2], ["PRAGMA locking_mode=EXCLUSIVE", "BEGIN"])
        self.assertIn("PRAGMA quick_check", traces[0])

    def test_complete_connection_gate_prevents_reader_overlapping_uncommitted_writer(self):
        entered, release, started, finished = (threading.Event() for _ in range(4))
        failures, observed = [], []
        def writer():
            try:
                with self.store._connection(write=True) as db:
                    db.execute("UPDATE tasks SET metadata=? WHERE task_id='task'", ('{"committed":true}',))
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError("writer fixture release missing")
            except BaseException as exc:
                failures.append(exc)
        def reader():
            started.set()
            try:
                observed.append(TaskStore(self.path).load("task").metadata)
            except BaseException as exc:
                failures.append(exc)
            finally:
                finished.set()
        first, second = threading.Thread(target=writer), threading.Thread(target=reader)
        first.start()
        try:
            self.assertTrue(entered.wait(3))
            second.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(finished.wait(.1), "reader bypassed the complete-operation gate")
        finally:
            release.set()
            first.join(4)
            if second.ident is not None:
                second.join(4)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(observed, [{"committed": True}])

    def test_actual_multiple_readers_and_checkpoint_writer_preserve_history(self):
        start, done = threading.Event(), threading.Event()
        failures, samples = [], []
        def writer():
            try:
                start.wait(2)
                with self.store.claim("task", expected_revision=self.initial.revision) as owned:
                    for number in range(20):
                        state = copy.deepcopy(owned.checkpoint.state)
                        state["output"] = str(number) + "x" * 8192
                        owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
            except BaseException as exc:
                failures.append(exc)
            finally:
                done.set()
        def reader():
            try:
                start.wait(2)
                other = TaskStore(self.path)
                last = -1
                for _ in range(25):
                    checkpoint = other.load("task")
                    self.assertGreaterEqual(checkpoint.revision, last)
                    self.assertEqual(checkpoint.prompt, self.initial.prompt)
                    last = checkpoint.revision
                    history = other.history("task")
                    self.assertEqual([row["revision"] for row in history], list(range(len(history))))
                    samples.append(last)
            except BaseException as exc:
                failures.append(exc)
        threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(10)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(len(samples), 75)
        self.assertTrue(done.is_set())
        self.assertEqual(self.store.load("task").revision, 21)
        self.assertEqual(len(self.store.history("task")), 22)

    def test_gate_wait_is_bounded_then_original_lock_can_be_released(self):
        lock = module._FileLock(str(self.path) + ".init.lock")
        try:
            started = time.monotonic()
            with mock.patch.object(module, "STORE_GATE_TIMEOUT", .12):
                with self.assertRaisesRegex(TaskBusyError, "Timed out"):
                    self.store.load("task")
            self.assertGreaterEqual(time.monotonic() - started, .1)
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            lock.close()
        self.assertEqual(TaskStore(self.path).load("task"), self.initial)

    def test_gate_open_permission_error_is_not_retried(self):
        with mock.patch.object(module, "_FileLock", side_effect=PermissionError(errno.EACCES, "fixture")) as lock:
            with self.assertRaises(PermissionError):
                self.store.load("task")
        self.assertEqual(lock.call_count, 1)

    def test_owned_child_death_releases_short_store_gate(self):
        marker = self.root / "inside-gate"
        proc = self.child('''
from pathlib import Path
import sys,time
from adaptive_inference.task_store import TaskStore
store=TaskStore(sys.argv[1])
with store._connection(write=True):
    Path(sys.argv[2]).write_text('held')
    time.sleep(30)
''', self.path, marker)
        deadline = time.monotonic() + 5
        while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(marker.exists())
        with mock.patch.object(module, "STORE_GATE_TIMEOUT", .1):
            with self.assertRaises(TaskBusyError):
                self.store.load("task")
        self.finish(proc)
        self.assertIsNotNone(proc.returncode)
        self.assertEqual(self.store.load("task"), self.initial)

    def test_actual_foreign_hot_journal_is_refused_without_changing_either_file(self):
        path = self.foreign()
        journal = self.hot(path)
        before = self.hashes(path, journal)
        with self.assertRaisesRegex(InvalidStoreError, "schema changed"):
            TaskStore(path)
        self.assertEqual(self.hashes(path, journal), before)

    def test_foreign_committed_schema_refused_after_uncommitted_replacement_schema(self):
        path = self.foreign()
        journal = self.hot(path, replace_foreign_schema=True)
        before = self.hashes(path, journal)
        # Actual SQLite transaction created our exact schema before crashing.
        # Do not claim page 1/schema was physically spilled: SQLite may retain it
        # in its cache. The recovered copied pair must still reveal and refuse
        # the foreign committed schema, preserving the original pair.
        with self.assertRaisesRegex(InvalidStoreError, "schema changed"):
            TaskStore(path)
        self.assertEqual(self.hashes(path, journal), before)

    def test_potential_super_journal_is_refused_before_copy_sqlite_or_external_access(self):
        journal = self.hot()
        external = self.root / "external-super-journal"
        external.write_bytes(b"")
        name = str(external).encode("utf-8")
        # SQLite's documented/pinned trailer format; no recovery parser is used.
        with journal.open("ab") as stream:
            stream.write(b"\0" * 4 + name + len(name).to_bytes(4, "big")
                         + sum(name).to_bytes(4, "big") + module._JOURNAL_MAGIC)
        before = self.hashes(self.path, journal, external)
        original = TaskStore._verify_sqlite
        paths = []
        def verify(path, *, mode):
            paths.append((path, mode))
            return original(path, mode=mode)
        with mock.patch.object(TaskStore, "_verify_sqlite", side_effect=verify):
            with self.assertRaisesRegex(InvalidStoreError, "Multi-database"):
                TaskStore(self.path)
        self.assertEqual(paths, [(self.path, "ro")])
        self.assertEqual(self.hashes(self.path, journal, external), before)

    def test_copy_io_failure_preserves_original_pair(self):
        journal = self.hot()
        before = self.hashes(self.path, journal)
        original = TaskStore._copy_bounded
        def fail_journal(source, destination, maximum):
            if source == journal:
                raise PermissionError("simulated journal copy failure")
            return original(source, destination, maximum)
        with mock.patch.object(TaskStore, "_copy_bounded", side_effect=fail_journal):
            with self.assertRaisesRegex(PermissionError, "simulated"):
                TaskStore(self.path)
        self.assertEqual(self.hashes(self.path, journal), before)

    def test_copy_validation_error_retains_sqlite_diagnostic_and_original_pair(self):
        journal = self.hot()
        before = self.hashes(self.path, journal)
        original = TaskStore._verify_sqlite
        error = sqlite3.OperationalError("simulated copied SQLite failure")
        error.sqlite_errorcode, error.sqlite_errorname = sqlite3.SQLITE_BUSY, "SQLITE_BUSY"
        def verify(path, *, mode):
            if path != self.path:
                raise error
            return original(path, mode=mode)
        with mock.patch.object(TaskStore, "_verify_sqlite", side_effect=verify):
            with self.assertRaisesRegex(InvalidStoreError, "code=5, name=SQLITE_BUSY") as caught:
                TaskStore(self.path)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(self.hashes(self.path, journal), before)

    def test_temporary_cleanup_failure_precedes_original_recovery(self):
        journal = self.hot()
        before = self.hashes(self.path, journal)
        real_temp = tempfile.TemporaryDirectory
        @contextmanager
        def failed_cleanup(*args, **kwargs):
            with real_temp(*args, **kwargs) as value:
                yield value
            raise OSError("simulated completed-temp-cleanup error")
        with mock.patch.object(module.tempfile, "TemporaryDirectory", failed_cleanup):
            with self.assertRaisesRegex(OSError, "completed-temp-cleanup"):
                TaskStore(self.path)
        self.assertEqual(self.hashes(self.path, journal), before)

    def test_only_exact_readonly_rollback_code_enters_recovery(self):
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_CORRUPT,
                     sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_READONLY_DIRECTORY, None):
            error = sqlite3.OperationalError("original SQLite error")
            if code is not None:
                error.sqlite_errorcode = code
            with self.subTest(code=code), \
                    mock.patch.object(TaskStore, "_verify_sqlite", side_effect=error), \
                    mock.patch.object(TaskStore, "_recover_journal_locked") as recovery:
                with self.assertRaises(InvalidStoreError) as caught:
                    TaskStore(self.path)
                self.assertIs(caught.exception.__cause__, error)
                recovery.assert_not_called()
        error = sqlite3.OperationalError("actual extended code fixture")
        error.sqlite_errorcode = sqlite3.SQLITE_READONLY_ROLLBACK
        with mock.patch.object(TaskStore, "_verify_sqlite", side_effect=error), \
                mock.patch.object(TaskStore, "_recover_journal_locked") as recovery:
            TaskStore(self.path)
            recovery.assert_called_once_with()

    def test_oversized_recovery_journal_is_refused_without_copy_or_mutation(self):
        journal = self.hot()
        before = self.hashes(self.path, journal)
        with mock.patch.object(module, "MAX_RECOVERY_JOURNAL_BYTES", journal.stat().st_size - 1), \
                mock.patch.object(TaskStore, "_copy_bounded") as copying:
            with self.assertRaisesRegex(InvalidStoreError, "bounds"):
                TaskStore(self.path)
            copying.assert_not_called()
        self.assertEqual(self.hashes(self.path, journal), before)

    def test_unsupported_wal_sidecar_is_refused_before_sqlite_and_is_unchanged(self):
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"preserve unsupported layout")
        before = self.hashes(self.path, sidecar)
        with mock.patch.object(module.sqlite3, "connect") as connect:
            with self.assertRaisesRegex(InvalidStoreError, "DELETE journal layout"):
                TaskStore(self.path)
            connect.assert_not_called()
        self.assertEqual(self.hashes(self.path, sidecar), before)

    def test_closed_wal_database_without_sidecars_is_refused_without_creating_any(self):
        path = self.foreign()
        db = sqlite3.connect(path)
        try:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        finally:
            db.close()
        self.assertFalse(Path(str(path) + "-wal").exists())
        self.assertFalse(Path(str(path) + "-shm").exists())
        before = self.hashes(path)
        with self.assertRaises(InvalidStoreError):
            TaskStore(path)
        self.assertEqual(self.hashes(path), before)
        self.assertFalse(Path(str(path) + "-wal").exists())
        self.assertFalse(Path(str(path) + "-shm").exists())

    def test_recovery_copy_stays_inside_private_store_directory_with_private_mode(self):
        journal = self.hot()
        original = TaskStore._verify_sqlite
        observed = []
        def verify(path, *, mode):
            if path != self.path:
                self.assertEqual(path.parent.parent, self.path.parent)
                if os.name != "nt":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(Path(str(path) + "-journal").stat().st_mode & 0o777, 0o600)
                observed.append(path.parent)
            return original(path, mode=mode)
        with mock.patch.object(TaskStore, "_verify_sqlite", side_effect=verify):
            self.assertEqual(TaskStore(self.path).load("task"), self.initial)
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].exists())
        self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
