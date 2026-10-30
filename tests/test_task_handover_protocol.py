"""CPU protocol/client evidence; fake host/streams, no GUI, SDK, child or model."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from adaptive_inference.desktop import control_transport as ct, control_client as cc
from adaptive_inference.desktop.run_gui import choose_task
from adaptive_inference.task_spec import BUDGET
import test_desktop_control_transport as baseline
import test_desktop_control_client as client


def sources():
    root = Path(tempfile.gettempdir()).resolve()
    return {'task_spec_path': str(root / 'chosen-task.json'), 'task_spec_sha256': 'd'*64,
            'task_inputs': str(root)}


def handover_grant(request, phase='reserved'):
    rid = request['request_id'] if isinstance(request, dict) else request.request_id
    return {'request_id': rid, 'predecessor_task_id': 'task', 'task_id': 'next-task',
            'selection_revision': 1, 'phase': phase}


class Handover:
    def __init__(self):
        self.phase = {'phase': 'available', 'request_id': None, 'selection_revision': 0}
        self.entered = asyncio.Event(); self.release = asyncio.Event(); self.release.set()
        self.selects = self.opens = self.lookups = 0
        self.records = {}; self.transport = None; self.capability = None
        self.lost_commit = self.open_error = self.retire = False

    def projection(self):return dict(self.phase)

    async def select_task(self, payload, *, intent_valid):
        if not intent_valid():raise ct.Refused('task_blocked')
        self.selects += 1
        self.records[payload['request_id']] = (deepcopy(payload), handover_grant(payload))
        if self.lost_commit:raise OSError('Injected lost reservation reply')
        return handover_grant(payload)

    async def open_selected_task(self, grant, *, intent_valid):
        if self.transport._serial.locked():raise AssertionError('Readiness owns serial lock')
        self.opens += 1; self.entered.set()
        self.phase = {'phase': 'preparing', 'request_id': grant['request_id'], 'selection_revision': 1}
        if self.retire:self.transport.retire_task(self.capability, grant['request_id'])
        await self.release.wait()
        if self.open_error:raise OSError('Injected launch/staging uncertainty')
        self.phase['phase'] = 'opened' if intent_valid() else 'blocked'
        value = {**grant, 'phase': self.phase['phase']}
        old, _ = self.records[grant['request_id']]; self.records[grant['request_id']] = (old, value)
        return value

    async def lookup_task(self, payload):
        self.lookups += 1
        old, grant = self.records[payload['request_id']]
        if old != payload:raise ct.Refused('conflicting_request_id')
        return deepcopy(grant)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = baseline.Runtime()
        self.runtime.projection.update(task_status='accepted', demand='fulfilled')
        self.adapter = Handover(); self.capability = object(); self.token = 'a'*64
        self.transport = ct.ControlTransport(ct.PreparedTask('host', 'task', client.bootstrap().objective),
            self.runtime, capability=self.capability, runner_credential='b'*64, handover=self.adapter, io_timeout=.05)
        self.adapter.transport, self.adapter.capability = self.transport, self.capability
        self.transport.bind_session(self.capability, 'session', self.token)
        await self.request('window_ready')

    async def asyncTearDown(self):
        self.adapter.release.set(); self.runtime.join.set()
        await self.transport.aclose(timeout=1)

    def payload(self, method='new_task', **changes):
        value = {'host_epoch': 'host', 'task_id': 'task', 'session_id': 'session', 'token': self.token, 'method': method}
        if method in ct.MUTATIONS:
            value.update(request_id='new-one', execution_id='task', execution_generation=0)
        if method == 'new_task':
            value.update(expected_task_revision=1, expected_selection_revision=0, **sources())
        if method == 'continue':value['expected_task_revision'] = 1
        value.update(changes); return value

    async def request(self, method='new_task', *, writer=None, **changes):
        writer = writer or baseline.Writer()
        data = (json.dumps(self.payload(method, **changes))+'\n').encode()
        task = self.transport.admit(baseline.Reader(data), writer)
        self.assertIsNotNone(task); await task; await asyncio.sleep(0)
        self.assertTrue(writer.closed and writer.joined)
        return json.loads(writer.data) if writer.data else None

    async def test_exact_request_replay_does_not_open_twice_or_change_A(self):
        before = self.transport.prepared
        first = await self.request(); second = await self.request()
        self.assertEqual(first, second)
        self.assertEqual((self.adapter.selects, self.adapter.opens), (1, 1))
        self.assertIs(self.transport.prepared, before)
        self.assertEqual(self.transport._current_execution(), {'execution_id': 'task', 'execution_generation': 0})
        self.assertNotIn(self.token, json.dumps(first))
        self.assertNotIn(sources()['task_spec_path'], json.dumps(first))

    async def test_blocked_preparation_keeps_Status_Stop_and_serial_available(self):
        self.adapter.release.clear()
        operation = asyncio.create_task(self.request())
        await asyncio.wait_for(self.adapter.entered.wait(), 1)
        self.assertFalse(self.transport._serial.locked())
        status = await self.request('status'); self.assertTrue(status['ok'])
        pause = await self.request('pause', request_id='late-pause')
        self.assertEqual(pause, {'ok': False, 'error': 'task_blocked'})
        stop = await self.request('stop'); self.assertTrue(stop['stop_requested'])
        self.assertFalse(stop['stop_confirmed'])
        self.adapter.release.set(); await operation
        await asyncio.shield(self.transport._stop_task)
        self.assertEqual(self.adapter.phase['phase'], 'blocked')
        self.assertEqual(self.adapter.opens, 1)

    async def test_retired_binding_keeps_service_controls_without_old_intent_changes(self):
        self.adapter.retire = True
        reply = await self.request(); self.assertEqual(reply['handover']['phase'], 'opened')
        calls = list(self.runtime.calls)
        status = await self.request('status'); self.assertTrue(status['status']['task_view_retired'])
        self.transport.invalidate_progress('late_old_status_failure')
        self.transport._deactivate()
        self.assertEqual(self.runtime.calls, calls)
        for method in ('pause', 'resume', 'cancel', 'continue', 'new_task'):
            result = await self.request(method, request_id='stale-'+method)
            self.assertEqual(result['error'], 'task_blocked')
        self.assertEqual((await self.request())['handover'], reply['handover'])
        self.assertTrue((await self.request('stop'))['stop_requested'])
        self.assertNotIn('deactivate', self.runtime.calls[len(calls):])

    async def test_lost_commit_reply_only_looks_up_and_keeps_uncertainty(self):
        self.adapter.lost_commit = True
        first = await self.request(); self.assertFalse(first['ok'])
        second = await self.request(); self.assertEqual(second['handover']['phase'], 'reserved')
        self.assertEqual((self.adapter.selects, self.adapter.opens, self.adapter.lookups), (1, 0, 1))
        self.assertEqual(self.transport.lifecycle()['unknown_mutations'], 1)
        self.assertIn('task_handover_failed', self.transport.lifecycle()['faults'])

    async def test_completed_failure_wins_over_timeout_not_stored_grant(self):
        self.adapter.open_error = True
        original = asyncio.wait_for
        async def timeout_at_completion(awaitable, timeout):
            try:return await original(awaitable, timeout)
            except OSError:raise asyncio.TimeoutError
        with mock.patch.object(ct.asyncio, 'wait_for', timeout_at_completion):
            result = await self.request()
        self.assertFalse(result['ok'])
        self.assertEqual(self.transport.lifecycle()['unknown_mutations'], 1)

    async def test_conflict_and_stale_revisions_do_not_reopen_or_read_new_files(self):
        await self.request()
        changed = await self.request(task_spec_sha256='e'*64)
        self.assertEqual(changed['error'], 'conflicting_request_id')
        self.assertEqual((self.adapter.selects,self.adapter.opens),(1,1))
        self.assertEqual((await self.request(request_id='other',expected_selection_revision=1))['error'], 'task_unavailable')

    async def test_bounded_paths_hashes_and_strict_fields_refuse_before_adapter(self):
        for changes in ({'task_spec_path':'relative.json'}, {'task_inputs':'x'*1025},
                        {'task_spec_sha256':'z'*64}, {'expected_selection_revision':True},
                        {'extra':'unrecognized'}):
            with self.subTest(changes=changes):
                self.assertEqual((await self.request(**changes))['error'], 'invalid_request')
        self.assertEqual(self.adapter.selects,0)

    async def test_new_transport_requires_new_binding_and_credential(self):
        runtime = baseline.Runtime(); runtime.live = {'new-session'}
        runtime.selected_execution = lambda: {'execution_id':'new-task','execution_generation':0}
        cap = object()
        second = ct.ControlTransport(ct.PreparedTask('host','new-task','Another objective'),runtime,
            capability=cap,runner_credential='b'*64)
        second.bind_session(cap,'new-session','c'*64)
        try:
            with self.assertRaises(ct.Refused):second._authenticate(self.payload('stop'))
            self.assertIsNot(second.prepared,self.transport.prepared)
            self.assertNotEqual(second._credential,self.transport._credential)
        finally:await second.aclose(timeout=1)


class ClientTests(unittest.TestCase):
    def test_production_B_view_detaches_on_shared_Stop_without_a_local_click(self):
        from adaptive_inference.desktop.gui_session import GUISession
        root, view, worker, binding = mock.Mock(), client.View(), client.FakeWorker(), client.Binding()
        view.attach = lambda controller: None
        session = GUISession(root,view,client.bootstrap(task_id='B',session_id='session-B'),
            binding,None,None,None,worker_factory=lambda exchange:worker,clock=lambda:0)
        # Drive the actual production constructor after the existing private
        # handshake boundary, with fake UI/thread edges and no Tk instance.
        session.deadline = 10
        session.handshake = mock.Mock(accepted=True,error=None)
        session.handshake.joined.return_value = True
        session.tick()
        controller = session.controller
        worker.respond({'ok':True,'state':'window_ready'});controller.tick()
        controller.poll_status()
        worker.respond(client.status(execution_id='B',stop_requested=True,host_phase='stopping',
            waiting_reason='stop_requested'))
        controller.tick()
        self.assertTrue(controller.closing)
        self.assertTrue(controller.marker_removed)
        self.assertFalse(controller.closed)  # The request worker still belongs to B.
        self.assertEqual([request.method for request in worker.sent],['window_ready','status'])
        worker.is_joined = True;controller.tick()
        self.assertTrue(controller.closed);self.assertTrue(view.destroyed)
        self.assertEqual(binding.calls,['install','remove'])

    def test_new_task_wire_round_trip_uses_exact_selected_file_descriptor(self):
        observed = []
        class Peer(client.Socket):
            def shutdown(self, how):
                super().shutdown(how)
                async def serve():
                    runtime = baseline.Runtime()
                    runtime.projection.update(task_status='accepted', demand='fulfilled')
                    adapter, cap = Handover(), object()
                    host = ct.ControlTransport(ct.PreparedTask('host','task',client.bootstrap().objective),
                        runtime, capability=cap, runner_credential='b'*64, handover=adapter)
                    adapter.transport, adapter.capability = host, cap
                    try:
                        host.bind_session(cap,'session','a'*64)
                        ready = {'host_epoch':'host','task_id':'task','session_id':'session',
                                 'token':'a'*64,'method':'window_ready'}
                        await host.admit(baseline.Reader(client.encoded(ready)),baseline.Writer())
                        writer = baseline.Writer()
                        await host.admit(baseline.Reader(self.sent),writer)
                        observed.append(deepcopy(adapter.records))
                        return bytes(writer.data)
                    finally:await host.aclose(timeout=1)
                self.parts = [asyncio.run(serve()),b'']
        request = cc.Request('new_task','chosen','task',0,1,0,**sources())
        peer = Peer()
        result = cc.WireExchange(client.bootstrap(),lambda:peer)(request)
        self.assertIsNone(result.error)
        self.assertEqual(result.reply['handover']['phase'],'opened')
        self.assertLessEqual(len(peer.sent),ct.REQUEST_LIMIT)
        payload = observed[0]['chosen'][0]
        self.assertEqual({key:payload[key] for key in sources()},sources())
        self.assertEqual(payload['expected_selection_revision'],0)
        self.assertNotIn('token',payload)

    def client(self):
        controller, worker, binding, view = client.ControllerTests().client()
        controller.poll_status()
        worker.respond(client.status(task_status='accepted',demand='fulfilled',handover={
            'phase':'available','request_id':None,'selection_revision':0},task_view_retired=False))
        controller.tick()
        return controller, worker, binding, view

    def test_file_selection_and_exact_retry_preserve_request_without_adopting_B(self):
        c,w,_,_ = self.client(); original=c.bootstrap
        self.assertTrue(c.action('new_task',task_selection=sources()))
        request=c.latest; w.respond(error='outcome_unconfirmed');c.tick()
        self.assertTrue(c.retry());self.assertEqual(w.sent[-1],request)
        self.assertEqual(request.task_spec_sha256,'d'*64)
        self.assertIs(c.bootstrap,original)

    def test_opened_reply_detaches_only_A_after_B_ready(self):
        c,w,b,_ = self.client();c.action('new_task',task_selection=sources())
        w.respond({'ok':True,'handover':handover_grant(c.latest,'opened')});c.tick()
        self.assertTrue(c.closing);self.assertIn('remove',b.calls)
        self.assertEqual(c.selected,{'execution_id':'task','execution_generation':0})
        self.assertFalse(any(r.method in ('stop','cancel','resume') for r in w.sent))

    def test_queued_genuine_Stop_is_not_discarded_by_opened_status(self):
        c,w,_,_ = self.client();c.action('new_task',task_selection=sources())
        request=c.latest
        w.respond({'ok':True,'handover':handover_grant(request)});c.tick()
        c.poll_status();self.assertTrue(c.action('stop'))
        w.respond(client.status(task_status='accepted',demand='fulfilled',handover={
            'phase':'opened','request_id':request.request_id,'selection_revision':1},task_view_retired=True))
        c.tick();self.assertFalse(c.closing)
        self.assertEqual(w.sent[-1].method,'stop')

    def test_task_selection_is_not_allowed_on_unfinished_or_stale_status(self):
        c,_,_,_=client.ControllerTests().client();self.assertFalse(c.buttons()['new_task'])
        c,_,_,_=self.client();c.status_valid=False;self.assertFalse(c.buttons()['new_task'])

    def test_strict_grant_never_delivers_B_credentials_or_changes_A(self):
        request=cc.Request('new_task','new-one','task',0,1,0,**sources())
        grant=handover_grant(request)
        for changes in ({'token':'c'*64},{'task_id':'task'},{'predecessor_task_id':'another'}, {'selection_revision':0}):
            with self.subTest(changes=changes), self.assertRaises(cc.ClientError):
                cc.validate_reply({'ok':True,'handover':{**grant,**changes}},request,client.bootstrap())


class PickerTests(unittest.TestCase):
    def test_native_dialog_cancel_is_not_a_request(self):
        dialogs=mock.Mock();dialogs.askopenfilename.return_value=''
        self.assertIsNone(choose_task(object(),dialogs=dialogs));dialogs.askdirectory.assert_not_called()

    def test_picker_uses_exact_raw_file_hash_and_only_declared_input_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();path=root/'task.json'
            data={'schema':'adaptive.task-spec.v1','prompt':'Summarize my notes.',
                  'inputs':[{'name':'notes.txt','sha256':'f'*64,'bytes':1}],
                  'outputs':[],'budget':BUDGET,'validation':{'validator':None}}
            raw=(json.dumps(data,indent=2)+'\n').encode();path.write_bytes(raw)
            dialogs=mock.Mock();dialogs.askopenfilename.return_value=str(path)
            dialogs.askdirectory.return_value=str(root)
            selected=choose_task(object(),dialogs=dialogs)
            self.assertEqual(selected,{'task_spec_path':str(path),
                'task_spec_sha256':hashlib.sha256(raw).hexdigest(),'task_inputs':str(root)})
            self.assertTrue(dialogs.askdirectory.call_args.kwargs['mustexist'])
            dialogs.askdirectory.return_value=''
            self.assertIsNone(choose_task(object(),dialogs=dialogs))


if __name__=='__main__':unittest.main()
