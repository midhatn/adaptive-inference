"""Actual product interaction loop with retained fixture child; no GUI/model."""
import asyncio
from copy import deepcopy
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop import composition as product
from adaptive_inference.execution_clock import CLOCK_ID, execution_now
import test_desktop_composition as fixture


class ExpiryCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.case=fixture.make_case(self.root);self.case.root.mkdir()
        c=self.case;c.deadline=execution_now()-1;c.worker=fixture.Child()
        c.handles=[c.worker];c.worker_exit_verified=False
        c.first_ready=c.root/'ready.json';c.first_ready.write_text('{}')
        c.stop_binding=SimpleNamespace(_verify_exit=mock.Mock(return_value='paused_budget_expired'))
        c.runtime=SimpleNamespace(refresh=mock.AsyncMock(),_transitioning=False)
        c.facade=SimpleNamespace(cooperative_stop=mock.AsyncMock(return_value=dict(
            worker_joined=True,host_closed=True,uncertain=False,fault=None)))
        c.host=SimpleNamespace(controller=SimpleNamespace(fault=None));c.gui=SimpleNamespace(process=fixture.Child(42))
        self.state={'stop_requested':False,'stop_confirmed':False}
        c.transport=SimpleNamespace(lifecycle=lambda:dict(self.state),_stop_task=None)

    async def until(self,predicate):
        async def wait():
            while not predicate():await asyncio.sleep(.001)
        await asyncio.wait_for(wait(),3)

    async def stop(self,task):
        self.case.worker.finish(5)
        self.state.update(stop_requested=True,stop_confirmed=True)
        self.case.transport._stop_task=asyncio.create_task(asyncio.sleep(0))
        await asyncio.wait_for(asyncio.shield(task),3)

    async def test_expiry_wait_and_exact_child_join_leave_status_loop_responsive(self):
        c=self.case
        with mock.patch.object(c,'_paused_expiry_candidate',new=mock.AsyncMock(return_value=True)) as candidate:
            task=asyncio.create_task(c.interact())
            try:
                await self.until(lambda:candidate.await_count>0)
                self.assertFalse(task.done());self.assertFalse(c.result['execution_expired'])
                c.worker.code=5  # poll observes exit; exact retained wait deliberately unfinished.
                await self.until(lambda:c.worker.waits==1)
                for _ in range(3):await c.runtime.refresh();await asyncio.sleep(0)
                self.assertFalse(task.done());self.assertFalse(c.result['execution_expired'])
                c.stop_binding._verify_exit.assert_not_called()
                c.worker.done.set()
                await self.until(lambda:c.result['execution_expired'])
                self.assertEqual(c.worker.waits,1);self.assertFalse(c.result['task_completed'])
                self.assertEqual(c.result['worker_outcome'],'paused_budget_expired')
                self.assertFalse(task.done())
            finally:await self.stop(task)
        c.stop_binding._verify_exit.assert_called_once_with(5)
        c.facade.cooperative_stop.assert_awaited_once()

    async def test_active_or_unknown_expiry_remains_failure(self):
        c=self.case
        with mock.patch.object(c,'_paused_expiry_candidate',new=mock.AsyncMock(return_value=False)):
            with self.assertRaises(TimeoutError):await c.interact()
        self.assertFalse(c.result['execution_expired']);c.stop_binding._verify_exit.assert_not_called()

    async def test_exact_paused_candidate_does_not_claim_final_success(self):
        c=self.case
        state={'status':'pending','phase':'ready','deadline_monotonic':c.deadline,
               'deadline_clock':CLOCK_ID,'pending_request':None}
        cp=SimpleNamespace(state=state,operation=None,requires_reconciliation=False)
        snapshot=SimpleNamespace(target=cp,demand={'state':'paused'},requests=[{'command':'pause'}],
            receipts=[{'outcome':'applied'}])
        c.runtime._cache=SimpleNamespace(snapshot=snapshot)
        self.assertTrue(await c._paused_expiry_candidate());self.assertFalse(c.result['execution_expired'])
        for attribute,value in (('operation',{'inflight':True}),('requires_reconciliation',True)):
            old=getattr(cp,attribute);setattr(cp,attribute,value)
            self.assertFalse(await c._paused_expiry_candidate());setattr(cp,attribute,old)
        for key,value in (('status','accepted'),('phase','awaiting_native_flush'),
                          ('deadline_monotonic',c.deadline+900),('deadline_clock','unknown'),
                          ('pending_request',{'id':1})):
            old=state[key];state[key]=value
            self.assertFalse(await c._paused_expiry_candidate());state[key]=old
        snapshot.requests.append({'command':'resume'})
        self.assertFalse(await c._paused_expiry_candidate())


if __name__=='__main__':unittest.main()
