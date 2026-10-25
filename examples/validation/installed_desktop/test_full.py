"""Full-trial integration boundaries; actual SQLite, no GUI/model/process launch."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest import mock

import installed_desktop_qualification as full
from installed_desktop_cold_tests import HarnessTests,Child,NOW,args_for


class FullUIBoundaries(unittest.IsolatedAsyncioTestCase):
    release_owner=HarnessTests.release_owner

    async def asyncSetUp(self):
        await HarnessTests.asyncSetUp(self)
        old=self.case
        case=full.FullUIQualification(args_for(self.root/'unused-fresh-full'))
        case.__dict__.update(old.__dict__)
        case.args.case='complete'
        case.qualification_hold_after_report=True
        self.case=case
        case.gui.binding=SimpleNamespace(session_id='retained-session')
        case.facade._fenced=False
        case.facade.session_is_live=lambda session:session=='retained-session'
        case.gui_resumes=[];case.worker_records=[];case.restart_wait=None

    async def resume(self,request_id='random-gui-id',consume=True,record=True):
        c=self.case;c.box.submit(c.capability,request_id,'resume')
        if consume:c.box.consume(self.owned,updated_at_utc=NOW)
        async def completed():return c.box.status(request_id)
        task=asyncio.create_task(completed());await task
        if record:c.transport._records[request_id]={'command':'resume','outcome':'known','task':task}
        return c.status(full.INITIAL_PAUSE)['sequence'],self.owned.checkpoint.owner_epoch

    async def test_real_mailbox_random_gui_resume_ack_preserves_original(self):
        c=self.case;sequence,owner=await self.resume()
        before=c.checkpoint()
        ack=c.gui_resume(sequence,owner)
        self.assertEqual(ack['request_id'],'random-gui-id')
        self.assertTrue(ack['owner_acknowledged'])
        self.assertEqual(c.checkpoint(),before)
        self.assertEqual(before.prompt,c.original.prompt)
        self.assertEqual(before.state['deadline_monotonic'],c.deadline)

    async def test_unacknowledged_resume_does_not_start_readiness(self):
        sequence,owner=await self.resume(consume=False)
        self.assertIsNone(self.case.gui_resume(sequence,owner))

    async def test_hidden_resume_without_authenticated_transport_record_refuses(self):
        sequence,owner=await self.resume(record=False)
        self.assertIsNone(self.case.gui_resume(sequence,owner))

    async def test_old_or_later_pause_cannot_reuse_resume(self):
        c=self.case;sequence,owner=await self.resume()
        self.assertIsNone(c.gui_resume(sequence+1,owner))
        c.box.submit(c.capability,'later-pause','pause')
        self.assertIsNone(c.gui_resume(sequence,owner))

    async def test_wrong_owner_and_expired_session_refuse(self):
        c=self.case;sequence,owner=await self.resume()
        with self.assertRaisesRegex(RuntimeError,'current safe waiting owner'):
            c.gui_resume(sequence,'wrong-owner')
        c.facade.session_is_live=lambda _:False
        with self.assertRaisesRegex(RuntimeError,'authenticated session'):
            c.gui_resume(sequence,owner)

    async def test_changed_deadline_is_not_recreated_after_resume(self):
        c=self.case;sequence,owner=await self.resume()
        original_deadline=c.deadline;c.deadline+=1
        with self.assertRaisesRegex(RuntimeError,'deadline changed'):
            c.gui_resume(sequence,owner)
        c.deadline=original_deadline

    async def test_stop_fence_prevents_restart_injection(self):
        c=self.case;self.lifecycle['stop_requested']=True
        with self.assertRaisesRegex(RuntimeError,'Stop interrupted'):
            await c.restart_at_checkpoint(c.worker,c.checkpoint())
        self.assertIsNone(c.worker.poll())
        self.assertIsNone(c.restart_wait)

    async def test_post_launch_diagnostic_failure_retains_new_child(self):
        c=self.case;c.plan={'base_python':'unused'};c.host.gateway.instance='instance'
        c.stop_binding=object();c.handles=[c.worker]
        new=Child(9003);self.addCleanup(new.finish,4)
        def failed_launch(command,label):
            self.assertIn('--qualification-hold-after-report',command)
            self.assertEqual(command[command.index('--deadline-monotonic')+1],str(c.deadline))
            c.handles.append(new)
            raise OSError('diagnostic failed after retained launch')
        c.launch=failed_launch
        with self.assertRaisesRegex(OSError,'diagnostic failed'):
            c.create_replacement_binding()
        self.assertIs(c.worker,new)
        self.assertIn(new,c.handles)
        self.assertIsNone(c.stop_binding)
        self.assertIs(c.worker_records[-1]['worker'],new)

    async def test_failed_replacement_drains_accepted_controls_before_stop_pause(self):
        c=self.case;events=[];release=asyncio.Event()
        c.worker_cap=object()
        c.stop_binding=SimpleNamespace(request_stop=lambda cap:events.append('new-stop-pause'))
        c.facade.worker_stop=object()
        c.fence=lambda:events.append('fenced')
        async def drain():
            await release.wait();events.append('accepted-db-joined')
        def request_stop():
            events.append('transport-stop')
            c.transport._stop_task=asyncio.create_task(drain())
        c.transport._request_stop=request_stop
        async def inherited(_self,failed):events.append('retained-children-cleanup')
        with mock.patch.object(full.ColdUIQualification,'dispose',inherited):
            disposal=asyncio.create_task(c.dispose(True));await asyncio.sleep(0)
            self.assertNotIn('new-stop-pause',events)
            release.set();await disposal
        self.assertEqual(events,['fenced','transport-stop','accepted-db-joined',
            'new-stop-pause','retained-children-cleanup'])


if __name__=='__main__':unittest.main()
