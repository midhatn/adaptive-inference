"""Expiry refusal over actual retained SQLite/transport and existing client fixtures."""
import asyncio
from copy import deepcopy
import json
import unittest
from unittest import mock

from adaptive_inference.control_mailbox import ControlBlocked, EXECUTION_OUTCOME
from adaptive_inference.desktop import control_client as cc
from adaptive_inference.desktop import mailbox_runtime
from adaptive_inference.execution_clock import CLOCK_ID
import test_desktop_mailbox_runtime as runtime_fixture
import test_desktop_control_client as client_fixture


class ExpiryRuntimeTests(runtime_fixture.DataFixture, unittest.IsolatedAsyncioTestCase):
    asyncSetUp=runtime_fixture.RuntimeTests.asyncSetUp
    asyncTearDown=runtime_fixture.RuntimeTests.asyncTearDown
    request=runtime_fixture.RuntimeTests.request
    frame=runtime_fixture.RuntimeTests.frame
    completed_control=runtime_fixture.RuntimeTests.completed_control
    matches=runtime_fixture.RuntimeTests.matches

    def deadline(self,value=10.0):
        with self.claim() as owned:
            state=deepcopy(owned.checkpoint.state);state['deadline_monotonic']=value
            owned.save_checkpoint(state,expected_revision=owned.checkpoint.revision)
        self.now=9.0;self.runtime._clock=lambda:self.now

    def seal(self):
        self.deadline()
        self.submit('final-pause','pause')
        with self.claim() as owned:
            self.box.consume(owned,updated_at_utc=runtime_fixture.NOW)
            observation=self.box.paused_execution_observation(owned)
            self.box.seal_paused_execution(owned,deadline_monotonic=10.0,
                pause_observed_at_monotonic=9.0,observed_pause=observation,sealed_at_monotonic=10.0)
        self.now=10.0

    async def test_exact_known_refusal_has_no_ack_or_append_and_does_not_fault_runtime(self):
        self.seal();await self.runtime.refresh()
        before=self.box.snapshot()
        reply=await self.completed_control('resume',request_id='too-late')
        # A pending handler is allowed; resolve the same retained request again.
        reply=await self.request('resume',request_id='too-late')
        self.assertEqual(reply,{'ok':True,'refusal':{'request_id':'too-late','command':'resume',
            'reason':'execution_budget_expired','recorded':False}})
        self.assertEqual(self.box.snapshot(),before)
        self.assertFalse(self.matches());self.assertFalse(self.runtime._faults)
        state=(await self.request('status'))['status']
        self.assertEqual(state['waiting_reason'],'budget_expired')
        self.assertEqual(state['task_status'],'pending');self.assertEqual(state['demand'],'paused')
        self.assertEqual(state['unknown_mutations'],0);self.assertFalse(state['faults'])
        stopped=await self.request('stop')
        self.assertTrue(stopped['ok']);await self.transport._stop_task
        self.assertTrue(self.transport.lifecycle()['stop_confirmed'])

    async def test_existing_pause_id_keeps_real_ack_after_seal(self):
        self.seal();await self.runtime.refresh()
        reply=await self.completed_control('pause',request_id='final-pause')
        reply=await self.request('pause',request_id='final-pause')
        self.assertTrue(reply['control']['recorded']);self.assertTrue(reply['control']['owner_acknowledged'])
        self.assertEqual(reply['control']['outcome'],'applied')
        self.assertNotIn('refusal',reply)

    async def test_stale_async_authority_cannot_activate_at_original_deadline(self):
        self.deadline();await self.runtime.refresh()
        self.submit('resume','resume');self.consume()
        self.assertTrue(await self.runtime.resume_authority('resume'))
        self.assertTrue(self.runtime.activate_intent('session'));self.assertTrue(self.matches())
        self.now=10.0
        self.assertFalse(self.runtime.activate_intent('session'));self.assertFalse(self.matches())
        self.assertFalse(await self.runtime.resume_authority('resume'))

    async def test_malformed_deadline_does_not_grant_authority(self):
        for deadline in (True,'10',None,-1,float('inf')):
            with self.subTest(deadline=deadline):
                self.assertRaises(runtime_fixture.RuntimeUnavailable,self.runtime._execution_live,
                    {'deadline_monotonic':deadline})
        self.assertTrue(self.runtime._execution_live({}))

    async def test_tagged_deadline_uses_shared_clock_even_when_local_observation_clock_lags(self):
        self.runtime._clock=lambda:2.0
        state={'deadline_monotonic':10.0,'deadline_clock':CLOCK_ID}
        with mock.patch.object(mailbox_runtime,'execution_now',return_value=10.0):
            self.assertFalse(self.runtime._execution_live(state))
        with mock.patch.object(mailbox_runtime,'execution_now',return_value=9.99):
            self.assertTrue(self.runtime._execution_live(state))
        with self.assertRaises(runtime_fixture.RuntimeUnavailable):
            self.runtime._execution_live({**state,'deadline_clock':'unknown'})


class ExpiryClientTests(unittest.TestCase):
    client=client_fixture.ControllerTests.client

    def refusal(self,request):
        return {'ok':True,'refusal':{'request_id':request.request_id,'command':request.method,
            'reason':'execution_budget_expired','recorded':False}}

    def test_refusal_is_known_not_recorded_and_never_fabricates_owner_ack(self):
        for command in ('pause','resume','cancel'):
            c,w,_,v=self.client();self.assertTrue(c.action(command));request=c.latest
            w.respond(self.refusal(request));c.tick()
            self.assertEqual(c.latest_stage,'unrecorded');self.assertIn('Not recorded',c.action_text)
            self.assertNotIn('Not sent',c.action_text);self.assertFalse(c.buttons()['retry'])
            self.assertIsNone(c.cleanup_error);self.assertTrue(c.buttons()['stop'])

    def test_exact_refusal_schema_rejects_unknown_ids_extra_ack_and_wrong_types(self):
        request=cc.Request('resume','one');good=self.refusal(request)
        cc.validate_reply(good,request,client_fixture.bootstrap())
        for changes in ({'recorded':0},{'recorded':True},{'sequence':1},{'owner_acknowledged':False},
                        {'request_id':'other'},{'command':'pause'},{'reason':'unknown'}):
            wrong=deepcopy(good);wrong['refusal'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(cc.ClientError):
                cc.validate_reply(wrong,request,client_fixture.bootstrap())

    def test_expired_pending_task_preserves_stop_and_discards_unsent_control(self):
        c,w,_,v=self.client();c.poll_status();self.assertTrue(c.action('resume'))
        w.respond(client_fixture.status(demand='paused',waiting_reason='budget_expired'));c.tick()
        self.assertEqual([r.method for r in w.sent],['window_ready','status','status'])
        self.assertIn('Not sent',v.states[-1]['action'])
        self.assertIn('saved work is preserved',v.states[-1]['waiting'])
        self.assertNotIn('completed',v.states[-1]['task'])
        self.assertTrue(c.buttons()['stop'])
        self.assertFalse(any(c.buttons()[k] for k in ('pause','resume','cancel','retry')))

    def test_expired_status_refuses_unsent_retry_without_erasing_earlier_uncertainty(self):
        c,w,_,v=self.client();c.action('resume');original=c.latest
        w.respond(error='outcome_unconfirmed');c.tick();c.poll_status();self.assertTrue(c.retry())
        w.respond(client_fixture.status(demand='paused',waiting_reason='budget_expired'));c.tick()
        self.assertEqual(c.latest,original);self.assertEqual(c.latest_stage,'unconfirmed')
        self.assertIn('Retry not sent',v.states[-1]['action'])
        self.assertEqual(sum(r==original for r in w.sent),1)


if __name__=='__main__':unittest.main()
