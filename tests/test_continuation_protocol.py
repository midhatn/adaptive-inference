"""CPU component evidence only: fake runtime/streams, no DB/model/process/window."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import itertools
import json
import unittest
from unittest import mock

from adaptive_inference.desktop import control_transport as ct, control_client as cc
from adaptive_inference.control_mailbox import ControlNotRecorded
import test_desktop_control_transport as baseline
import test_desktop_control_client as client


def selected(identity='task',generation=0):
    return {'execution_id':identity,'execution_generation':generation}


def grant(request,phase='selected'):
    get=lambda key: request[key] if isinstance(request,dict) else getattr(request,key)
    return {'request_id':get('request_id'),'predecessor_execution_id':get('execution_id'),
            'predecessor_generation':get('execution_generation'),'execution_id':'next-'+get('request_id'),
            'execution_generation':get('execution_generation')+1,'phase':phase}


class Runtime(baseline.Runtime):
    def __init__(self):
        super().__init__()
        self.selected=selected()
        self.phase={'phase':'available','request_id':None}
        self.projection.update(demand='paused',waiting_reason='budget_expired')
        self.selection_entered=asyncio.Event();self.selection_release=asyncio.Event();self.selection_release.set()
        self.transition_entered=asyncio.Event();self.transition_release=asyncio.Event();self.transition_release.set()
        self.selection_count=self.launch_count=self.lookup_count=0
        self.grants={};self.resumes=[];self.fail_after_commit=False;self.transition_error=False
        self.commit_on_stop=False;self.intent_samples=[];self.return_refusal=False
        self.transport=None

    def selected_execution(self):return dict(self.selected)
    def status(self):
        return {**self.projection,**self.selected,'continuation':dict(self.phase),
                'controls':[dict(row) for row in self.controls.values()]}
    async def select_continuation(self,request,*,intent_valid):
        self.selection_entered.set();self.selection_count+=1
        self.assert_target=request['execution_id'],request['execution_generation']
        if not intent_valid():raise ct.Refused('continuation_blocked')
        await self.selection_release.wait()
        if not intent_valid() and not self.commit_on_stop:raise ct.Refused('continuation_blocked')
        if self.phase['phase']!='available':raise ct.Refused('continuation_unavailable')
        value=grant(request)
        self.grants[request['request_id']]=(deepcopy(request),value)
        self.selected={key:value[key] for key in ('execution_id','execution_generation')}
        self.phase={'phase':'selected','request_id':request['request_id']}
        self.projection.update(task_revision=0,demand='paused',waiting_reason='paused')
        self.controls={}
        if self.fail_after_commit:raise OSError('simulated lost selection result')
        return deepcopy(value)
    async def continue_selected(self,value,*,intent_valid):
        self.transition_entered.set()
        self.intent_samples.append(intent_valid())
        if self.transport is not None and self.transport._serial.locked():
            raise AssertionError('Long transition owns serial lock')
        if self.transition_error:raise OSError('simulated retained transition failure')
        if intent_valid():self.launch_count+=1
        self.phase={'phase':'preparing','request_id':value['request_id']}
        await self.transition_release.wait()
        if intent_valid():
            self.resumes.append('continue-resume-'+value['request_id'])
            self.phase={'phase':'running','request_id':value['request_id']}
            self.projection.update(demand='waiting',waiting_reason='resources',task_revision=2)
        else:self.phase={'phase':'blocked','request_id':value['request_id']}
        return {**value,'phase':self.phase['phase']}
    async def lookup_continuation(self,request):
        self.lookup_count+=1
        row=self.grants.get(request['request_id'])
        if row is None:return None
        if row[0]!=request:raise ct.Refused('conflicting_request_id')
        return deepcopy(row[1])
    def fence_admission(self):
        super().fence_admission()
        self.selection_release.set();self.transition_release.set()
    async def submit_control(self,request_id,command,*,execution):
        if execution!=self.selected:raise ct.Refused('stale_execution')
        if self.return_refusal:return ControlNotRecorded(request_id,command,'execution_budget_expired')
        controls=self.controls
        self.entered.set()
        if self.release is not None:await self.release.wait()
        if request_id not in controls:
            self.commits.append((request_id,command))
            controls[request_id]={'request_id':request_id,'command':command,'sequence':len(controls)+1,
                                  'outcome':'applied','owner_acknowledged':True}
        return dict(controls[request_id])
    async def resume_authority(self,request_id,*,execution):
        return execution==self.selected


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime=Runtime();self.cap=object();self.token='a'*64
        self.host=ct.ControlTransport(ct.PreparedTask('host','task','Objective.'),self.runtime,
                    capability=self.cap,runner_credential='b'*64,io_timeout=.025)
        self.runtime.transport=self.host
        self.host.bind_session(self.cap,'session',self.token)
        await self.call(self.frame('window_ready'))
    async def asyncTearDown(self):
        self.runtime.selection_release.set();self.runtime.transition_release.set()
        if self.runtime.release is not None:self.runtime.release.set()
        self.runtime.join.set()
        await self.host.aclose(timeout=1)
    def frame(self,method='status',**changes):
        value={'host_epoch':'host','session_id':'session','task_id':'task','token':self.token,'method':method}
        if method in ct.MUTATIONS:
            value.update(request_id='one',**self.runtime.selected_execution())
        if method=='continue':value['expected_task_revision']=self.runtime.projection['task_revision']
        value.update(changes);return value
    async def call(self,request):
        writer=baseline.Writer();raw=(json.dumps(request)+'\n').encode()
        task=self.host.admit(baseline.Reader(raw),writer)
        self.assertIsNotNone(task)
        await asyncio.wait_for(task,1);await asyncio.sleep(0)
        self.assertTrue(writer.closed and writer.joined)
        return json.loads(writer.data)
    async def test_continue_one_grant_and_derived_resume_keeps_logical_identity(self):
        request=self.frame('continue');reply=await self.call(request)
        self.assertEqual(reply['continuation']['phase'],'running')
        self.assertEqual(self.runtime.selection_count,1);self.assertEqual(self.runtime.launch_count,1)
        self.assertEqual(self.runtime.resumes,['continue-resume-one'])
        self.assertEqual(self.runtime.intent_samples,[True])
        self.assertEqual(self.host.prepared.task_id,'task');self.assertEqual(self.host._session,'session')
        status=(await self.call(self.frame()))['status']
        self.assertEqual(status['execution_id'],'next-one');self.assertEqual(status['task_status'],'pending')
    async def test_long_transition_returns_grant_without_holding_serial(self):
        self.runtime.transition_release.clear();request=self.frame('continue')
        reply=await self.call(request)
        self.assertEqual(reply['continuation']['phase'],'selected')
        self.assertFalse(self.host._serial.locked());self.assertEqual(self.host.lifecycle()['pending_mutations'],1)
        duplicate=await self.call(request)
        self.assertEqual(duplicate,reply);self.assertEqual(self.runtime.selection_count,1)
        self.assertEqual(self.runtime.launch_count,1);self.assertEqual(self.runtime.resumes,[])
        self.assertTrue((await self.call(self.frame()))['ok'])
    async def test_pending_before_grant_duplicate_never_waits_or_regrants(self):
        self.runtime.selection_release.clear();request=self.frame('continue')
        reply=await self.call(request)
        self.assertEqual(reply['state'],'pending');self.assertIsNone(reply['recorded'])
        self.assertEqual(await self.call(request),reply);self.assertEqual(self.runtime.selection_count,1)
        self.runtime.selection_release.set();await self.host._records['one']['task']
        self.assertEqual((await self.call(request))['continuation']['phase'],'running')
        self.assertEqual(self.runtime.resumes,['continue-resume-one'])
    async def test_stop_during_long_transition_is_service_scoped_and_joins_it(self):
        self.runtime.transition_release.clear();await self.call(self.frame('continue'))
        reply=await self.call(self.frame('stop'))
        self.assertTrue(reply['stop_requested']);self.assertTrue(self.runtime.fenced)
        final=await self.host.aclose(timeout=.5)
        self.assertTrue(final['closed']);self.assertEqual(self.runtime.resumes,[])
        self.assertEqual(self.host._records['one']['grant']['phase'],'blocked')
    async def test_stop_before_selection_commit_prevents_launch(self):
        self.runtime.selection_release.clear();request=self.frame('continue')
        await self.call(request);await self.call(self.frame('stop'))
        final=await self.host.aclose(timeout=.5)
        self.assertTrue(final['closed']);self.assertEqual(self.runtime.launch_count,0)
        self.assertEqual(self.runtime.grants,{})
    async def test_selection_committed_during_stop_is_retained_but_never_launched(self):
        self.runtime.selection_release.clear();self.runtime.commit_on_stop=True
        await self.call(self.frame('continue'));await self.call(self.frame('stop'))
        final=await self.host.aclose(timeout=.5)
        self.assertTrue(final['closed']);self.assertEqual(self.runtime.launch_count,0)
        self.assertEqual(self.host._records['one']['grant']['phase'],'blocked')
    async def test_lost_ui_session_blocks_derived_resume_without_regrant(self):
        self.runtime.transition_release.clear();request=self.frame('continue')
        await self.call(request);await self.call(self.frame('window_closed'))
        self.runtime.transition_release.set();await self.host._records['one']['task']
        self.assertEqual(self.runtime.resumes,[])
        self.assertEqual(self.host._records['one']['grant']['phase'],'blocked')
    async def test_duplicate_payload_conflict_and_new_old_generation_command_refuse(self):
        old=self.frame('continue');await self.call(old)
        changed={**old,'expected_task_revision':old['expected_task_revision']+1}
        self.assertEqual((await self.call(changed))['error'],'conflicting_request_id')
        other={**old,'request_id':'two'}
        self.assertEqual((await self.call(other))['error'],'stale_execution')
        self.assertEqual(self.runtime.selection_count,1)
    async def test_queued_old_control_is_rechecked_before_dispatch(self):
        request=self.frame('pause',request_id='old')
        # Hold dispatch until the bounded response proves this exact operation
        # is retained; scheduler timing cannot turn the response into an error.
        async with self.host._serial:
            reply=await self.call(request)
            self.assertEqual(reply,{'ok':True,'state':'pending','request_id':'old',
                'recorded':None,'execution_id':'task','execution_generation':0})
            operation=self.host._records['old']['task']
            self.assertFalse(operation.done())
            self.runtime.selected=selected('new',1)
        with self.assertRaisesRegex(ct.Refused,'^stale_execution$'):
            await asyncio.wait_for(asyncio.shield(operation),.5)
        self.assertEqual(await self.call(request),{'ok':False,'error':'stale_execution'})
        self.assertEqual(self.runtime.commits,[])
        self.assertEqual(self.host.lifecycle()['unknown_mutations'],0)
    async def test_inflight_old_control_reply_stamped_old_never_activates_new(self):
        self.runtime.release=asyncio.Event();request=self.frame('resume',request_id='old')
        task=asyncio.create_task(self.call(request));await self.runtime.entered.wait()
        self.runtime.selected=selected('new',1);self.runtime.release.set()
        reply=await task
        self.assertEqual(reply['execution_id'],'task');self.assertEqual(reply['execution_generation'],0)
        self.assertFalse(self.runtime.intent)
    async def test_continue_orders_after_old_control_without_self_join(self):
        self.runtime.release=asyncio.Event()
        old=asyncio.create_task(self.call(self.frame('pause',request_id='old')))
        await self.runtime.entered.wait()
        request=self.frame('continue');reply=await self.call(request)
        self.assertEqual(reply['state'],'pending');self.assertEqual(self.runtime.selection_count,0)
        self.runtime.release.set();await old
        await asyncio.wait_for(self.host._records['one']['task'],.5)
        self.assertEqual(self.runtime.selection_count,1);self.assertEqual(self.runtime.launch_count,1)
    async def test_unexpected_failure_lookup_grant_cannot_make_clean_stop(self):
        self.runtime.fail_after_commit=True;request=self.frame('continue')
        first=await self.call(request);self.assertFalse(first['ok'])
        self.assertEqual(self.runtime.launch_count,0)
        lookup=await self.call(request)
        self.assertEqual(lookup['continuation']['phase'],'selected')
        self.assertEqual(self.runtime.lookup_count,1);self.assertEqual(self.runtime.selection_count,1)
        self.assertFalse((await self.host.aclose(timeout=.5))['closed'])
        self.assertIn('continuation_failed',self.host.lifecycle()['faults'])
    async def test_transition_failure_cannot_be_erased_by_known_grant(self):
        self.runtime.transition_error=True;request=self.frame('continue')
        self.assertFalse((await self.call(request))['ok'])
        self.assertEqual((await self.call(request))['continuation']['phase'],'selected')
        self.assertFalse((await self.host.aclose(timeout=.5))['closed'])
    async def test_completed_failure_at_response_deadline_is_not_a_successful_grant_reply(self):
        loop=asyncio.get_running_loop();clock=loop.time;offset=0.0
        original=self.runtime.continue_selected
        self.runtime.transition_error=True
        async def failure_at_deadline(value,*,intent_valid):
            nonlocal offset
            # Deterministic ordering: the operation fails as the request's
            # response deadline passes, without sleeps or cancelling that task.
            offset+=self.host.io_timeout*2
            return await original(value,intent_valid=intent_valid)
        self.runtime.continue_selected=failure_at_deadline
        request=self.frame('continue')
        with mock.patch.object(loop,'time',side_effect=lambda:clock()+offset):
            reply=await self.call(request)
        operation=self.host._records['one']['task']
        self.assertTrue(operation.done());self.assertIsInstance(operation.exception(),OSError)
        self.assertEqual(reply,{'ok':False,'error':'runtime_error'})
        self.assertEqual(self.host._records['one']['outcome'],'unknown')
        self.assertIn('continuation_failed',self.host.lifecycle()['faults'])
        self.assertEqual((await self.call(request))['continuation']['phase'],'selected')
        self.assertEqual(self.runtime.selection_count,1);self.assertEqual(self.runtime.launch_count,0)
        self.assertEqual(self.runtime.resumes,[])
        self.assertFalse((await self.host.aclose(timeout=.5))['closed'])
    async def test_failed_transition_refuses_new_task_controls_but_keeps_service_stop(self):
        self.runtime.transition_error=True;request=self.frame('continue')
        await self.call(request)
        self.assertEqual((await self.call(self.frame('pause',request_id='new')))['error'],'continuation_blocked')
        self.assertEqual((await self.call(self.frame('continue',request_id='new')))['error'],'continuation_blocked')
        self.assertTrue((await self.call(self.frame('stop')))['stop_requested'])
        self.assertEqual(self.runtime.commits,[])
    async def test_projection_cannot_reuse_execution_id_with_new_generation(self):
        self.runtime.selected=selected('task',1)
        self.assertFalse((await self.call(self.frame()))['ok'])
    async def test_strict_wire_fields_types_bounds_and_service_scope(self):
        good=self.frame('continue')
        for change in ({'execution_generation':True},{'execution_generation':33},{'expected_task_revision':True},
                       {'expected_task_revision':256},{'budget_s':900},{'successor_id':'forged'}):
            with self.subTest(change=change):self.assertEqual((await self.call({**good,**change}))['error'],'invalid_request')
        missing=dict(good);del missing['execution_id']
        self.assertFalse((await self.call(missing))['ok'])
        self.assertFalse((await self.call(self.frame('stop',execution_id='old',execution_generation=0)))['ok'])
        self.assertEqual(self.runtime.selection_count,0)
    async def test_typed_refusal_is_scoped_generic_error_is_two_fields(self):
        self.runtime.return_refusal=True
        request=self.frame('resume')
        # A bounded response may precede the retained operation's refusal.
        # Queue it explicitly and await that exact operation before schema checks.
        async with self.host._serial:
            reply=await self.call(request)
            self.assertEqual(reply,{'ok':True,'state':'pending','request_id':'one',
                'recorded':None,'execution_id':'task','execution_generation':0})
            operation=self.host._records['one']['task']
            self.assertFalse(operation.done())
        refusal=await asyncio.wait_for(asyncio.shield(operation),.5)
        self.assertEqual(refusal,{'request_id':'one','command':'resume',
            'reason':'execution_budget_expired','recorded':False})
        # Ordinary retries reobserve the runtime. Supply this completed retained
        # task only for the wire-schema check, without another scheduling race.
        with mock.patch.object(self.host,'_retain_control',return_value=operation) as retain:
            reply=await self.call(request)
            retain.assert_called_once_with(request)
        self.assertEqual(set(reply),{'ok','execution_id','execution_generation','refusal'})
        self.assertIs(reply['refusal']['recorded'],False)
        self.assertEqual(self.runtime.commits,[])
        error=await self.call(self.frame('pause',request_id='stale',execution_id='old'))
        self.assertEqual(error,{'ok':False,'error':'stale_execution'})
    async def test_id_and_mutation_capacities_not_reset_by_continuation(self):
        self.host.max_ids=1;request=self.frame('continue');await self.call(request)
        self.assertTrue((await self.call(request))['ok'])
        response=await self.call(self.frame('pause',request_id='other'))
        self.assertEqual(response['error'],'capacity_exhausted')
        self.assertEqual(len(self.host._records),1)
    async def test_cancelled_handler_cannot_cancel_retained_transition(self):
        self.runtime.transition_release.clear();request=self.frame('continue')
        writer=baseline.Writer();task=self.host.admit(baseline.Reader((json.dumps(request)+'\n').encode()),writer)
        await self.runtime.transition_entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        operation=self.host._records['one']['task']
        self.assertFalse(operation.done());self.runtime.transition_release.set()
        await operation;self.assertEqual(self.runtime.resumes,['continue-resume-one'])
    async def test_second_expiry_offers_new_command_and_old_grant_remains_lookup_only(self):
        first=self.frame('continue');await self.call(first)
        self.runtime.phase={'phase':'available','request_id':None}
        self.runtime.projection.update(demand='paused',waiting_reason='budget_expired',task_revision=4)
        status=(await self.call(self.frame()))['status']
        self.assertEqual(status['continuation'],{'phase':'available','request_id':None})
        second=self.frame('continue',request_id='two');await self.call(second)
        self.assertEqual(self.runtime.selected['execution_generation'],2)
        historical=await self.call(first)
        self.assertEqual(historical['continuation']['execution_generation'],1)
        self.assertEqual(self.runtime.selection_count,2);self.assertEqual(self.runtime.launch_count,2)


def status(identity='task',generation=0,revision=5,phase='available',request_id=None,**changes):
    value=client.status()['status']
    value.update(**selected(identity,generation),task_revision=revision,demand='paused',waiting_reason='budget_expired',
                 continuation={'phase':phase,'request_id':request_id})
    value.update(changes);return {'ok':True,'status':value}


class ClientTests(unittest.TestCase):
    def client(self,**status_changes):
        worker=client.FakeWorker();view=client.View();ids=iter(['one','two','three','four'])
        controller=cc.ClientController(client.bootstrap(),worker,client.Binding(),view,id_factory=lambda:next(ids))
        controller.start();worker.respond({'ok':True,'state':'window_ready'});controller.tick()
        controller.poll_status();worker.respond(status(**status_changes));controller.tick()
        return controller,worker
    def test_request_immutable_target_and_exact_serialization(self):
        request=cc.Request('continue','id','task',0,5)
        sock=client.Socket(client.encoded({'ok':True,'continuation':grant(request)}))
        reply=cc.WireExchange(client.bootstrap(),lambda:sock)(request)
        self.assertIsNone(reply.error)
        wire=json.loads(sock.sent)
        self.assertEqual(wire['task_id'],'task');self.assertEqual(wire['execution_id'],'task')
        self.assertEqual(wire['expected_task_revision'],5);self.assertEqual(wire['execution_generation'],0)
        self.assertEqual(set(wire),{'host_epoch','session_id','task_id','token','method','request_id',
                                  'execution_id','execution_generation','expected_task_revision'})
    def test_invalid_request_fields_and_generation_bounds_rejected(self):
        for args in [('pause','id'),('continue','id','task',True,5),('continue','id','task',0,True),
                     ('continue','id','task',33,5),('continue','id','task',0,256),('stop',None,'task',0)]:
            with self.subTest(args=args),self.assertRaises((cc.ClientError,ValueError)):cc.Request(*args)
    def test_grant_adoption_clears_old_status_ack_and_needs_new_snapshot(self):
        c,w=self.client();self.assertTrue(c.action('continue'));request=c.latest
        w.respond({'ok':True,'continuation':grant(request)});c.tick()
        self.assertEqual(c.selected,selected('next-one',1));self.assertIsNone(c.status);self.assertFalse(c.status_valid)
        self.assertTrue(c.buttons()['stop'])
        for method in ('pause','resume','cancel','continue'):self.assertFalse(c.buttons()[method])
        c.poll_status();w.respond(status('next-one',1,0,'preparing','one',waiting_reason='paused'));c.tick()
        self.assertFalse(c.buttons()['resume'])
        c.poll_status();w.respond(status('next-one',1,2,'running','one',demand='waiting',waiting_reason='resources'));c.tick()
        self.assertTrue(c.buttons()['pause']);self.assertTrue(c.buttons()['resume'])
        self.assertEqual(c.bootstrap.task_id,'task')
    def test_old_queued_command_not_retargeted_after_status_advances(self):
        c,w=self.client(phase='unavailable',waiting_reason='paused')
        c.poll_status();self.assertTrue(c.action('resume'))
        queued=c._local_intent[0];self.assertEqual(queued.execution(),selected())
        w.respond(status('new',1,0,'running','external',waiting_reason='paused'));c.tick()
        self.assertNotIn(queued,w.sent);self.assertIsNone(c._local_intent)
        self.assertIn('Not sent',c._local_feedback)
    def test_old_inflight_ack_cannot_authorize_new_execution(self):
        c,w=self.client(phase='unavailable',waiting_reason='paused');c.action('resume');old=c.latest
        c._adopt_execution(selected('new',1))
        w.respond({'ok':True,**old.execution(),'control':client.receipt(old,outcome='applied',owner_acknowledged=True)});c.tick()
        self.assertIsNone(c.status);self.assertFalse(c.status_valid);self.assertIsNone(c.latest)
        self.assertFalse(c.buttons()['resume'])
    def test_generation_order_allows_new_revision_zero_and_rejects_old_high_revision(self):
        c,w=self.client(revision=200)
        c.poll_status();w.respond(status('new',1,0,'running','external',waiting_reason='paused'));c.tick()
        self.assertEqual(c.status['task_revision'],0)
        c.poll_status();w.respond(status(revision=255));c.tick()
        self.assertEqual(c.selected,selected('new',1));self.assertFalse(c.status_valid)
        self.assertEqual(c.status['task_revision'],0)
    def test_same_generation_identity_change_and_revision_regression_refuse(self):
        c,w=self.client()
        c.poll_status();w.respond(status('other',0,6));c.tick()
        self.assertEqual(c.selected,selected());self.assertFalse(c.status_valid)
        c.poll_status();w.respond(status(revision=4));c.tick()
        self.assertFalse(c.status_valid);self.assertEqual(c.status['task_revision'],5)
    def test_same_id_continue_retry_keeps_original_predecessor_after_selection(self):
        c,w=self.client();c.action('continue');request=c.latest;w.respond(error='outcome_unconfirmed');c.tick()
        c._adopt_execution(selected('next-one',1))
        self.assertTrue(c.retry());self.assertEqual(w.sent[-1],request)
        w.respond({'ok':True,'continuation':grant(request)});c.tick()
        self.assertEqual(c.selected,selected('next-one',1));self.assertIsNone(c.status)
    def test_typed_and_generic_refusals_have_distinct_strict_schema(self):
        req=cc.Request('resume','id','task',0)
        typed={'ok':True,**req.execution(),'refusal':{'request_id':'id','command':'resume',
                 'reason':'execution_budget_expired','recorded':False}}
        self.assertEqual(cc.validate_reply(typed,req,client.bootstrap()),typed)
        generic={'ok':False,'error':'stale_execution'}
        self.assertEqual(cc.validate_reply(generic,req,client.bootstrap()),generic)
        with self.assertRaises(cc.ClientError):cc.validate_reply({**generic,**req.execution()},req,client.bootstrap())
        bad=dict(typed);del bad['execution_id']
        with self.assertRaises(cc.ClientError):cc.validate_reply(bad,req,client.bootstrap())
    def test_stop_wire_has_no_execution_precondition_after_grant(self):
        c,w=self.client();c.action('continue');w.respond({'ok':True,'continuation':grant(c.latest)});c.tick()
        self.assertTrue(c.action('stop'));req=w.sent[-1]
        self.assertEqual(req,cc.Request('stop'))
    def test_next_expiry_enables_new_continue_without_reusing_prior_id(self):
        c,w=self.client();c.action('continue');first=c.latest
        w.respond({'ok':True,'continuation':grant(first)});c.tick()
        c.poll_status();w.respond(status('next-one',1,5));c.tick()
        self.assertTrue(c.buttons()['continue']);self.assertTrue(c.action('continue'))
        self.assertEqual(c.latest.execution_generation,1);self.assertNotEqual(c.latest.request_id,first.request_id)
    def test_invalid_grant_cannot_change_selection_or_claim_ready(self):
        c,w=self.client();c.action('continue');bad=grant(c.latest);bad['execution_generation']=2
        w.respond({'ok':True,'continuation':bad});c.tick()
        self.assertEqual(c.selected,selected());self.assertFalse(c.status_valid)

    def test_seen_execution_id_cannot_be_reintroduced_at_later_generation(self):
        c,w=self.client()
        c.poll_status();w.respond(status('new',1,0,'running','external',waiting_reason='paused'));c.tick()
        c.poll_status();w.respond(status('task',2,0,'running','later',waiting_reason='paused'));c.tick()
        self.assertEqual(c.selected,selected('new',1));self.assertFalse(c.status_valid)
