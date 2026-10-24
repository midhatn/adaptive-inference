"""Independent storage boundaries; fresh private databases and bounded CPU workers."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent/'task-store-verification-prototype'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import copy
import sqlite3
import threading
import time
import unittest
from unittest import mock
from test_task_store_verification import VerificationTests,module,TaskStore,InvalidStoreError,TaskBusyError
from adaptive_inference.demand import DemandIdentity,DemandRegistry,Registration,NAMESPACE
from adaptive_inference.control_mailbox import Mailbox

class Additional(VerificationTests):
    def test_idle_claim_does_not_hold_short_gate_or_block_mailbox_submit(self):
        identity=DemandIdentity('review-registration','controlled-task','review-owner','2026-10-24T12:00:00Z')
        cp=self.store.create(identity.task_id,'Preserve objective.',metadata={NAMESPACE:identity.metadata()})
        registry=DemandRegistry((Registration(self.store,identity),));cap=object()
        mailbox=Mailbox(registry,identity.registration_id,requester_capability=cap)
        finished=threading.Event();rows=[];errors=[]
        def request():
            try:rows.append(mailbox.submit(cap,'pause-1','pause'))
            except BaseException as exc:errors.append(exc)
            finally:finished.set()
        with self.store.claim(identity.task_id,expected_revision=cp.revision) as owned:
            before=owned.checkpoint
            worker=threading.Thread(target=request);worker.start()
            try:self.assertTrue(finished.wait(2),'Idle owner monopolized store gate')
            finally:worker.join(3)
            self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
            self.assertEqual(rows[0]['outcome'],'pending');self.assertFalse(rows[0]['owner_acknowledged'])
            self.assertEqual(self.store.load(identity.task_id),before)
            mailbox.consume(owned,updated_at_utc='2026-10-24T12:01:00Z')
            self.assertEqual(mailbox.status('pause-1')['outcome'],'applied')

    def test_baseexception_rolls_back_and_releases_short_gate(self):
        original_history=self.store.history('task')
        class Interrupted(BaseException):pass
        with self.assertRaises(Interrupted):
            with self.store._connection(write=True) as db:
                db.execute("UPDATE tasks SET metadata=? WHERE task_id='task'",('{"uncommitted":true}',))
                raise Interrupted('Fixture interruption before commit')
        rows=[];errors=[]
        def read():
            try:rows.append(TaskStore(self.path).load('task'))
            except BaseException as exc:errors.append(exc)
        worker=threading.Thread(target=read);worker.start();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(rows,[self.initial]);self.assertEqual(self.store.history('task'),original_history)

    def test_resolved_path_aliases_contend_on_same_short_gate(self):
        directory=self.root/'child';directory.mkdir()
        alias=TaskStore(directory/'..'/self.path.name)
        self.assertEqual(alias.path,self.store.path)
        held=module._FileLock(str(self.path)+'.init.lock')
        try:
            with mock.patch.object(module,'STORE_GATE_TIMEOUT',.1):
                with self.assertRaises(TaskBusyError):alias.load('task')
        finally:held.close()
        self.assertEqual(alias.load('task'),self.initial)

    def test_valid_schema_converted_to_clean_wal_is_refused_without_sidecars(self):
        db=sqlite3.connect(self.path)
        try:self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal')
        finally:db.close()
        before=self.hashes(self.path)
        self.assertFalse(Path(str(self.path)+'-wal').exists())
        self.assertFalse(Path(str(self.path)+'-shm').exists())
        with self.assertRaises(InvalidStoreError):TaskStore(self.path)
        self.assertEqual(self.hashes(self.path),before)
        self.assertFalse(Path(str(self.path)+'-wal').exists())
        self.assertFalse(Path(str(self.path)+'-shm').exists())

if __name__=='__main__':
    names=[n for n in Additional.__dict__ if n.startswith('test_')]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(Additional(n) for n in names))
    raise SystemExit(not result.wasSuccessful())
