# SPDX-License-Identifier: Apache-2.0
"""Coherent snapshots using real SQLite transactions and owned test threads."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import Mailbox, ControlBlocked, ACKS
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.task_store import TaskStore, TaskBusyError

NOW = '2026-10-24T18:00:00Z'
OBJECTIVE = 'Keep the original task and finish the validated artifact.'


class DataFixture:
    def data(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui-mailbox-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / 'task.sqlite')
        self.identity = DemandIdentity('registered', 'task', 'trusted-host', NOW)
        self.store.create('task', OBJECTIVE, metadata={NAMESPACE: self.identity.metadata()})
        self.registry = DemandRegistry((Registration(self.store, self.identity),))
        self.cap = object()
        self.box = Mailbox(self.registry, 'registered', requester_capability=self.cap)

    def claim(self):
        return self.store.claim('task', expected_revision=self.store.load('task').revision)

    def demand(self, state='waiting'):
        with self.claim() as owned:
            self.registry.transition('registered', owned, state,
                expected_revision=owned.checkpoint.revision, updated_at_utc=NOW)

    def submit(self, ident, command):
        return self.box.submit(self.cap, ident, command)

    def consume(self):
        with self.claim() as owned:
            return self.box.consume(owned, updated_at_utc=NOW)


class SnapshotTests(DataFixture, unittest.TestCase):
    def setUp(self):
        self.data()
        self.demand()

    def test_one_transaction_no_nested_load_or_target_claim_detached_data(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            revision = owned.checkpoint.revision
            real_connection = self.store._connection
            with mock.patch.object(self.store, '_connection', wraps=real_connection) as opened, \
                    mock.patch.object(self.store, 'load', side_effect=AssertionError('Nested load')), \
                    mock.patch.object(self.store, 'claim', side_effect=AssertionError('Target takeover')):
                snap = self.box.snapshot()
                self.assertEqual(opened.call_count, 1)
            self.assertEqual(snap.target.revision, revision)
            self.assertEqual(snap.status('resume'), self.box.status('resume'))
            snap.requests[0]['command'] = 'cancel'
            snap.target.state['output'] = 'Changed private copy'
            self.assertEqual(self.box.snapshot().requests[0]['command'], 'resume')
            self.assertEqual(owned.checkpoint.state['output'], '')
            with self.assertRaises(TaskBusyError):
                with self.claim():
                    pass

    def test_writer_cannot_commit_between_two_snapshot_reads(self):
        self.submit('resume', 'resume')
        entered, release, writer_started, writer_done = (threading.Event() for _ in range(4))
        snapshots, failures = [], []
        actual_read = self.store._read
        reader_thread = None

        def read(db, task_id):
            value = actual_read(db, task_id)
            if threading.current_thread() is reader_thread and task_id == 'task':
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Bounded snapshot gate timed out')
            return value

        def reader():
            try:
                snapshots.append(self.box.snapshot())
            except BaseException as exc:
                failures.append(exc)

        def writer():
            writer_started.set()
            try:
                self.consume()
                self.submit('pause', 'pause')
                self.consume()
            except BaseException as exc:
                failures.append(exc)
            finally:
                writer_done.set()

        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)
        with mock.patch.object(self.store, '_read', side_effect=read):
            reader_thread.start()
            try:
                self.assertTrue(entered.wait(2))
                writer_thread.start()
                self.assertTrue(writer_started.wait(1))
                self.assertFalse(writer_done.wait(.05))
            finally:
                release.set()
                reader_thread.join(4)
                if writer_thread.ident is not None:
                    writer_thread.join(4)
        self.assertFalse(reader_thread.is_alive() or writer_thread.is_alive())
        self.assertEqual(failures, [])
        before = snapshots[0]
        self.assertEqual(len(before.requests), 1)
        self.assertEqual(len(before.receipts), 0)
        after = self.box.snapshot()
        self.assertEqual([r['command'] for r in after.requests], ['resume', 'pause'])
        self.assertEqual(len(after.receipts), 2)
        self.assertEqual(after.demand['state'], 'paused')

    def test_status_missing_id_precedes_ack_validation_but_snapshot_validates_all(self):
        self.submit('resume', 'resume')
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state[ACKS] = {'mailbox_task_id': 'foreign', 'receipts': []}
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        with self.assertRaises(KeyError):
            self.box.status('absent')
        with self.assertRaises(ControlBlocked):
            self.box.snapshot()

    def test_same_transaction_checks_registration_identity(self):
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state[NAMESPACE]['owner_id'] = 'changed'
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        with self.assertRaises(ValueError):
            self.box.snapshot()

    def test_terminal_projection_preserves_unacknowledged_rejection(self):
        self.submit('pause', 'pause')
        with self.claim() as owned:
            state = deepcopy(owned.checkpoint.state)
            state.update(status='accepted', output='Validated fixture artifact')
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
        snap = self.box.snapshot()
        self.assertEqual(snap.status('pause'), self.box.status('pause'))
        self.assertEqual(snap.status('pause')['outcome'], 'rejected')
        self.assertIs(snap.status('pause')['owner_acknowledged'], False)


if __name__ == '__main__':
    unittest.main()
