"""CPU fake sockets/windows/widgets only; bounded real thread ownership probes."""
import asyncio
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest

from adaptive_inference.desktop import control_client as cc

HERE=Path(__file__).resolve().parent
def bootstrap(**changes):
    values=dict(host_epoch='host',session_id='session',task_id='task',objective='Keep the original objective.\nIncluding this line.',
        token='a'*64,host='127.0.0.1',port=18101,marker_name='Adaptive.UI.session-1234',marker_value=1234)
    values.update(changes);return cc.Bootstrap(**values)
def life(**changes):
    value=dict(stop_requested=False,stop_confirmed=False,pending_mutations=0,unknown_mutations=0,
        handlers=1,pending_connections=1,stream_close_failures=0,faults=[])
    value.update(changes);return value
def status(**changes):
    value=dict(host_phase='parked',task_status='pending',task_revision=1,demand='waiting',waiting_reason='foreground',
        controls=[],objective=bootstrap().objective,execution_id='task',execution_generation=0,
        continuation={'phase':'unavailable','request_id':None},**life())
    value.update(changes);return {'ok':True,'status':value}
def receipt(request,**changes):
    value=dict(request_id=request.request_id,command=request.method,sequence=1,outcome='pending',owner_acknowledged=False,recorded=True)
    value.update(changes);return value
def encoded(value):return (json.dumps(value,separators=(',',':'))+'\n').encode()


class Socket:
    def __init__(self,data=b'',*,parts=None,close_error=False):
        self.parts=list(parts) if parts is not None else [data,b'']
        self.calls=[];self.sent=None;self.close_error=close_error
    def settimeout(self,value):self.calls.append(('timeout',value))
    def connect(self,target):self.calls.append(('connect',target))
    def sendall(self,data):self.sent=data;self.calls.append(('send',len(data)))
    def shutdown(self,how):self.calls.append(('shutdown',how))
    def recv(self,size):
        self.calls.append(('recv',size))
        if not self.parts:raise TimeoutError('private data must not leak')
        part=self.parts.pop(0)
        if isinstance(part,Exception):raise part
        return part
    def close(self):
        self.calls.append(('close',))
        if self.close_error:raise OSError('private close detail')


class WireTests(unittest.TestCase):
    def test_bootstrap_private_reader_and_no_secret_repr(self):
        b=bootstrap();calls=[]
        got=cc.Bootstrap.from_private_reader(lambda limit:(calls.append(limit) or json.dumps(asdict(b)).encode()))
        self.assertEqual(got,b);self.assertEqual(calls,[cc.BOOTSTRAP_LIMIT+1]);self.assertNotIn(b.token,repr(got))
        for changes in ({'host':'localhost'},{'host':'192.0.2.1'},{'port':True},{'token':'bad'},{'marker_value':False},{'objective':'x'*16385}):
            with self.subTest(changes=list(changes)),self.assertRaises(cc.ClientError):bootstrap(**changes)

    def test_bootstrap_errors_do_not_expose_secret_or_repair_permissions(self):
        def denied(limit):raise PermissionError('a'*64)
        with self.assertRaisesRegex(cc.ClientError,'^bootstrap_unavailable$'):
            cc.Bootstrap.from_private_reader(denied)
        for data in (b'{"port":1,"port":2}',b'{}',b'x'*(cc.BOOTSTRAP_LIMIT+1)):
            with self.assertRaises(cc.ClientError):cc.Bootstrap.from_private_reader(lambda n:data)

    def test_exact_lf_halfclose_and_eof_order(self):
        sock=Socket(encoded({'ok':True,'state':'window_ready'}))
        result=cc.WireExchange(bootstrap(),lambda:sock)(cc.Request('window_ready'))
        self.assertIsNone(result.error);self.assertEqual(json.loads(sock.sent)['method'],'window_ready')
        self.assertEqual(sock.sent.count(b'\n'),1);self.assertEqual(sock.sent[-1:],b'\n')
        operations=[x[0]for x in sock.calls]
        self.assertLess(operations.index('send'),operations.index('shutdown'));self.assertLess(operations.index('shutdown'),operations.index('recv'))
        self.assertIn(('shutdown',socket.SHUT_WR),sock.calls);self.assertEqual(operations.count('close'),1)
        self.assertEqual(operations.count('recv'),2)

    def test_reply_must_end_at_eof_with_one_bounded_line(self):
        good=encoded({'ok':True,'state':'window_ready'})
        for parts in ([good,TimeoutError()],[good,b'junk',b''],[good+good,b''],[good[:-1],b''],[b'x'*65537,b''],[b'{"ok":true,"ok":true}\n',b''],[b'{"ok":NaN}\n',b''],[b'\xff\n',b'']):
            with self.subTest(parts=[len(p) if isinstance(p,bytes) else type(p).__name__ for p in parts]):
                sock=Socket(parts=parts);result=cc.WireExchange(bootstrap(),lambda:sock)(cc.Request('window_ready'))
                self.assertEqual(result.error,'outcome_unconfirmed');self.assertIsNone(result.reply)
                self.assertEqual(sock.calls[-1],('close',))

    def test_total_deadline_does_not_reset_each_receive(self):
        clock=iter([0,.1,.2,.3,1.0,1.9,2.01])
        sock=Socket(parts=[b'{',b'"',b''])
        result=cc.WireExchange(bootstrap(),lambda:sock,clock=lambda:next(clock))(cc.Request('status'))
        self.assertEqual(result.error,'outcome_unconfirmed')
        values=[x[1]for x in sock.calls if x[0]=='timeout'];self.assertEqual(values,sorted(values,reverse=True))

    def test_clock_regression_and_close_error_remain_unknown(self):
        clock=iter([10,9]);sock=Socket(close_error=True)
        result=cc.WireExchange(bootstrap(),lambda:sock,clock=lambda:next(clock))(cc.Request('resume','one','task',0))
        self.assertEqual(result.error,'outcome_unconfirmed');self.assertEqual(result.cleanup_error,'socket_close_unconfirmed')
        self.assertNotIn('private',repr(result));self.assertIsNone(sock.sent)

    def test_recorded_pending_and_unconfirmed_are_distinct(self):
        req=cc.Request('pause','id','task',0)
        for response in ({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(req)}, {'ok':True,'execution_id':'task','execution_generation':0,'state':'pending','request_id':'id','recorded':None}):
            result=cc.WireExchange(bootstrap(),lambda:Socket(encoded(response)))(req)
            self.assertIsNone(result.error);self.assertEqual(result.reply,response)
        invalid={'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(req,outcome='applied')}
        self.assertIsNotNone(cc.WireExchange(bootstrap(),lambda:Socket(encoded(invalid)))(req).error)

    def test_failed_socket_close_is_retained_and_fences_new_connections(self):
        sock=Socket(encoded({'ok':True,'state':'window_ready'}),close_error=True);factories=[]
        exchange=cc.WireExchange(bootstrap(),lambda:(factories.append(True) or sock))
        first=exchange(cc.Request('window_ready'))
        self.assertEqual(first.reply,{'ok':True,'state':'window_ready'})
        self.assertEqual(first.cleanup_error,'socket_close_unconfirmed')
        self.assertIs(exchange._unresolved_socket,sock)
        second=exchange(cc.Request('window_closed'))
        self.assertEqual(second.error,'outcome_unconfirmed');self.assertEqual(len(factories),1)
        self.assertEqual(sum(call[0]=='close' for call in sock.calls),1)

    def test_status_original_objective_and_stop_proof(self):
        for response in (status(objective='changed'),status(stop_confirmed=True),status(stop_requested=True,stop_confirmed=True,unknown_mutations=1),status(controls=[receipt(cc.Request('pause','a','task',0)),receipt(cc.Request('resume','b','task',0))])):
            with self.assertRaises(cc.ClientError):cc.validate_reply(response,cc.Request('status'),bootstrap())
        self.assertEqual(cc.validate_reply(status(),cc.Request('status'),bootstrap()),status())

    def test_unchanged_transport_round_trip_with_fake_streams(self):
        from adaptive_inference.desktop import control_transport as transport
        import test_desktop_control_transport as fixture
        class Peer(Socket):
            def shutdown(self,how):
                super().shutdown(how)
                async def serve():
                    runtime=fixture.Runtime();host=transport.ControlTransport(
                        transport.PreparedTask('host','task',bootstrap().objective),runtime,capability=cap,
                        runner_credential='b'*64,io_timeout=.1)
                    try:
                        host.bind_session(cap,'session','a'*64)
                        ready={'host_epoch':'host','session_id':'session','task_id':'task','token':'a'*64,'method':'window_ready'}
                        initial=fixture.Writer();await host.admit(fixture.Reader(encoded(ready)),initial)
                        writer=fixture.Writer();await host.admit(fixture.Reader(self.sent),writer)
                        return bytes(writer.data)
                    finally:
                        await host.aclose(timeout=1)
                self.parts=[asyncio.run(serve()),b'']
        cap=object();peer=Peer()
        result=cc.WireExchange(bootstrap(),lambda:peer)(cc.Request('pause','actual-id','task',0))
        self.assertIsNone(result.error);self.assertTrue(result.reply['control']['recorded'])
        self.assertFalse(result.reply['control']['owner_acknowledged'])


class WorkerTests(unittest.TestCase):
    def finish(self,worker):
        deadline=time.monotonic()+2
        while not worker.joined() and time.monotonic()<deadline:time.sleep(.001)
        self.assertTrue(worker.joined())

    def test_started_exchange_is_retained_until_close_and_join(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def exchange(request):
            calls.append(request.method)
            if request.method=='resume':entered.set();self.assertTrue(release.wait(2))
            return cc.Result(request,error='outcome_unconfirmed')
        worker=cc.NetworkWorker(exchange);worker.start()
        try:
            self.assertFalse(worker._thread.daemon);self.assertTrue(worker.submit(cc.Request('resume','id','task',0)))
            self.assertTrue(entered.wait(1));worker.close();worker.close()
            self.assertFalse(worker.joined());self.assertFalse(worker.submit(cc.Request('pause','later','task',0)))
        finally:release.set();self.finish(worker)
        self.assertEqual(calls,['resume','window_closed'])
        results=[worker.take(),worker.take()];self.assertEqual([x.request.method for x in results],calls)

    def test_unsent_action_is_explicitly_discarded_not_recorded(self):
        calls=[];worker=cc.NetworkWorker(lambda request:(calls.append(request.method)or cc.Result(request,error='outcome_unconfirmed')))
        with worker._condition:
            worker.start();self.assertTrue(worker.submit(cc.Request('resume','id','task',0)));worker.close()
        self.finish(worker);first=worker.take()
        self.assertTrue(first.discarded);self.assertEqual(first.error,'not_sent');self.assertEqual(calls,['window_closed'])

    def test_worker_capacity_remains_held_until_result_consumed(self):
        done=threading.Event()
        def exchange(request):done.set();return cc.Result(request,error='outcome_unconfirmed')
        worker=cc.NetworkWorker(exchange);worker.start()
        try:
            worker.submit(cc.Request('status'));self.assertTrue(done.wait(1))
            self.assertFalse(worker.submit(cc.Request('status')))
        finally:worker.close();self.finish(worker)


class FakeWorker:
    def __init__(self):self.sent=[];self.results=[];self.is_joined=False;self.started=False;self.closing=False
    def start(self):self.started=True
    def submit(self,request):self.sent.append(request);return not self.closing
    def take(self):return self.results.pop(0)if self.results else None
    def respond(self,reply=None,**kwargs):self.results.append(cc.Result(self.sent[-1],reply,**kwargs))
    def close(self):self.closing=True
    def joined(self):return self.is_joined
class Binding:
    def __init__(self,remove=True):self.calls=[];self.removal=remove
    def install(self):self.calls.append('install');return True
    def remove(self):self.calls.append('remove');return self.removal
class View:
    def __init__(self):self.states=[];self.destroyed=False
    def render(self,state):self.states.append(state)
    def destroy(self):self.destroyed=True


class ControllerTests(unittest.TestCase):
    def client(self):
        worker=FakeWorker();binding=Binding();view=View();ids=iter(['one','two','three'])
        client=cc.ClientController(bootstrap(),worker,binding,view,id_factory=lambda:next(ids))
        client.start();worker.respond({'ok':True,'state':'window_ready'});client.tick()
        client.poll_status();worker.respond(status());client.tick()
        return client,worker,binding,view

    def test_open_never_resumes_and_status_is_read_only(self):
        c,w,b,v=self.client();self.assertEqual([r.method for r in w.sent],['window_ready','status'])
        self.assertEqual(v.states[-1]['objective'],bootstrap().objective);self.assertIn('other work',v.states[-1]['waiting'])
        c.poll_status();w.respond(status());c.tick();self.assertIsNone(c.latest)

    def test_click_recorded_and_ack_are_three_visible_states(self):
        c,w,b,v=self.client();c.action('pause');req=c.latest
        self.assertIn('not yet confirmed',c.action_text);self.assertFalse(c.buttons()['resume'])
        w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(req)});c.tick();self.assertIn('Recorded;',c.action_text)
        c.poll_status();w.respond(status(task_revision=2,controls=[receipt(req,outcome='applied',owner_acknowledged=True)]));c.tick()
        self.assertEqual(c.latest_stage,'applied');self.assertIn('acknowledged',c.action_text)

    def test_retry_preserves_id_and_old_resume_not_replayed_after_pause(self):
        c,w,b,v=self.client();c.action('resume');old=c.latest
        w.respond(error='outcome_unconfirmed');c.tick();self.assertTrue(c.retry());self.assertEqual(w.sent[-1],old)
        w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(old)});c.tick()
        self.assertTrue(c.action('pause'));new=c.latest;self.assertNotEqual(new.request_id,old.request_id)
        w.respond(error='outcome_unconfirmed');c.tick();self.assertTrue(c.retry());self.assertEqual(w.sent[-1],new)
        self.assertEqual(sum(r==old for r in w.sent),2)

    def test_reopen_uses_new_session_and_no_previous_command_queue(self):
        c,w,b,v=self.client();c.action('resume');w.respond(error='outcome_unconfirmed');c.tick()
        other=cc.ClientController(bootstrap(session_id='new-session',token='c'*64),FakeWorker(),Binding(),View())
        other.start();self.assertEqual([r.method for r in other.worker.sent],['window_ready']);self.assertIsNone(other.latest)

    def test_status_poll_does_not_retry_pending_command(self):
        c,w,b,v=self.client();c.action('resume');request=c.latest
        w.respond({'ok':True,'execution_id':'task','execution_generation':0,'state':'pending','request_id':request.request_id,'recorded':None});c.tick()
        for _ in range(3):c.poll_status();w.respond(status());c.tick()
        self.assertEqual(sum(r.method=='resume'for r in w.sent),1);self.assertEqual(c.latest_stage,'unconfirmed')

    def test_terminal_and_cancelled_disable_controls_without_fabricating_completion(self):
        for updates,word in (({'task_status':'accepted'},'completed'),({'demand':'cancelled'},'cancelled'),({'demand':'paused'},'paused')):
            c,w,b,v=self.client();c.poll_status();w.respond(status(task_revision=2,**updates));c.tick()
            self.assertIn(word,v.states[-1]['task'])
            if word!='paused':self.assertFalse(c.buttons()['resume']);self.assertFalse(c.buttons()['cancel'])
            self.assertTrue(c.buttons()['stop'])

    def test_confirmed_terminal_task_clears_only_ordinary_waiting_explanations(self):
        for updates in ({'task_status':'accepted','demand':'fulfilled'},
                        {'task_status':'exhausted'}, {'demand':'cancelled'}):
            for reason in (None,'foreground','resources','paused'):
                with self.subTest(updates=updates,reason=reason):
                    c,w,b,v=self.client();c.poll_status()
                    w.respond(status(task_revision=2,waiting_reason=reason,**updates));c.tick()
                    self.assertEqual(v.states[-1]['waiting'],'')
                    self.assertFalse(c.buttons()['resume']);self.assertTrue(c.buttons()['stop'])

    def test_pending_paused_and_terminal_uncertainty_messages_remain_visible(self):
        for updates in ({}, {'demand':'paused','waiting_reason':'paused'},
                        {'task_status':'accepted','waiting_reason':'reconciliation'},
                        {'task_status':'accepted','waiting_reason':'unknown'},
                        {'task_status':'accepted','waiting_reason':'operation_inflight'},
                        {'task_status':'accepted','waiting_reason':'stop_requested','stop_requested':True},
                        {'task_status':'accepted','unknown_mutations':1},
                        {'task_status':'accepted','faults':['stop_unresolved']}):
            with self.subTest(updates=updates):
                c,w,b,v=self.client();c.poll_status();w.respond(status(task_revision=2,**updates));c.tick()
                self.assertEqual(v.states[-1]['waiting'],cc.WAITING[updates.get('waiting_reason','foreground')])
        c,w,b,v=self.client();c.poll_status();w.respond(status(task_revision=2,task_status='accepted'));c.tick()
        c.poll_status();w.respond(error='outcome_unconfirmed');c.tick()
        self.assertFalse(c.status_valid)
        self.assertIn('unavailable',v.states[-1]['connection'])
        self.assertEqual(v.states[-1]['waiting'],cc.WAITING['foreground'])

    def test_terminal_task_keeps_engine_stop_closed_and_fault_precedence(self):
        for updates,expected in (({'host_phase':'closed','stop_requested':True,'stop_confirmed':True},'Engine stopped safely.'),
                                ({'host_phase':'closed'},'Engine is closed; stop confirmation is unavailable.'),
                                ({'host_phase':'fault'},'The engine reported a problem; progress is not assumed.')):
            with self.subTest(updates=updates):
                c,w,b,v=self.client();c.poll_status()
                w.respond(status(task_revision=2,task_status='accepted',**updates));c.tick()
                self.assertEqual(v.states[-1]['waiting'],expected)

    def test_stop_requested_is_not_stop_confirmed(self):
        c,w,b,v=self.client();c.action('stop')
        w.respond({'ok':True,'state':'stop_requested',**life(stop_requested=True)});c.tick()
        self.assertIn('waiting',c.action_text);self.assertFalse(c.buttons()['resume'])
        c.poll_status();w.respond(status(host_phase='closed',stop_requested=True,stop_confirmed=True));c.tick()
        self.assertEqual(c.action_text,'Engine stopped safely.')

    def test_close_removes_marker_and_never_cancels_or_stops_task(self):
        c,w,b,v=self.client();c.action('resume');req=c.latest;c.close();c.close()
        self.assertEqual(b.calls,['install','remove']);self.assertFalse(c.action('cancel'));c.tick();self.assertFalse(v.destroyed)
        w.respond(error='outcome_unconfirmed');w.results.append(cc.Result(cc.Request('window_closed'),{'ok':True,'state':'window_closed','task_cancelled':False}));w.is_joined=True;c.tick()
        self.assertTrue(v.destroyed);self.assertTrue(c.close_ack);self.assertEqual(c.latest,req)
        self.assertNotIn('cancel',[r.method for r in w.sent]);self.assertNotIn('stop',[r.method for r in w.sent])

    def test_discarded_close_action_stays_unrecorded(self):
        c,w,b,v=self.client();c.action('resume');c.close()
        w.respond(error='not_sent',discarded=True);w.is_joined=True;c.tick()
        self.assertEqual(c.latest_stage,'unrecorded');self.assertIn('Not sent',c.action_text)

    def test_marker_removal_failure_prevents_normal_destroy(self):
        c,w,b,v=self.client();b.removal=False;c.close();w.is_joined=True;c.tick()
        self.assertFalse(v.destroyed);self.assertFalse(c.closed);self.assertEqual(c.cleanup_error,'marker_removal_unconfirmed')

    def test_stale_status_and_invalid_reply_do_not_authorize_resume(self):
        c,w,b,v=self.client();c.poll_status();w.respond(status(task_revision=0));c.tick()
        self.assertFalse(c.buttons()['resume']);self.assertIn('stale',c.connection)
        c.poll_status();w.respond(status(objective='wrong objective'));c.tick();self.assertEqual(v.states[-1]['objective'],bootstrap().objective)

    def test_wrong_thread_actions_are_refused_without_view_calls(self):
        c,w,b,v=self.client();before=len(v.states);errors=[]
        def wrong():
            try:c.action('resume')
            except Exception as exc:errors.append(type(exc))
        thread=threading.Thread(target=wrong);thread.start();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[PermissionError]);self.assertEqual(len(v.states),before)

    def test_finite_command_ids_never_forget_or_renew_old_controls(self):
        c,w,b,v=self.client();c._id_factory=lambda:f'command-{len(c._ids)}'
        for index in range(32):
            self.assertTrue(c.action('pause'))
            w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(c.latest,sequence=index+1)});c.tick()
        self.assertEqual(len(c._ids),32)
        self.assertFalse(c.action('resume'));self.assertFalse(c.action('cancel'))
        self.assertTrue(c.buttons()['stop']);self.assertEqual(len(w.sent),34)

    def test_reused_id_is_refused_before_dispatch(self):
        c,w,b,v=self.client();c._id_factory=lambda:'same'
        c.action('resume');w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(c.latest)});c.tick()
        before=list(w.sent)
        with self.assertRaisesRegex(cc.ClientError,'request_identity_reused'):c.action('pause')
        self.assertEqual(w.sent,before)

    def test_socket_cleanup_error_remains_visible_and_fences_actions(self):
        c,w,b,v=self.client();c.action('pause')
        w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(c.latest)},cleanup_error='socket_close_unconfirmed');c.tick()
        self.assertEqual(c.latest_stage,'pending')
        self.assertTrue(v.states[-1]['cleanup_unconfirmed']);self.assertFalse(any(c.buttons().values()))

    def test_binding_failure_never_starts_worker_or_sends_controls(self):
        worker=FakeWorker();binding=Binding();binding.install=lambda:False
        client=cc.ClientController(bootstrap(),worker,binding,View())
        client.start()
        self.assertTrue(client.closing);self.assertFalse(worker.started);self.assertEqual(worker.sent,[])
        self.assertEqual(binding.calls,['remove'])

    def test_applied_receipt_cannot_regress_to_pending(self):
        c,w,b,v=self.client();c.action('pause');request=c.latest
        w.respond({'ok':True,'execution_id':'task','execution_generation':0,'control':receipt(request,outcome='applied',owner_acknowledged=True)});c.tick()
        c.poll_status();w.respond(status(task_revision=2,controls=[receipt(request)]));c.tick()
        self.assertEqual(c.latest_stage,'applied');self.assertFalse(c.status_valid)
        self.assertIn('stale',c.connection)


class Widget:
    def __init__(self,*args,**kwargs):self.options=dict(kwargs)
    def grid(self,**kwargs):pass
    def configure(self,**kwargs):self.options.update(kwargs)
class FakeTk:
    Frame=Label=Button=Widget
class Root:
    def __init__(self):self.calls=[];self.protocols={}
    def protocol(self,name,callback):self.protocols[name]=callback
    def after(self,ms,callback):self.calls.append((ms,callback))
    def destroy(self):self.calls.append(('destroy',))


class ViewTests(unittest.TestCase):
    def test_ttk_view_uses_main_after_poll_and_close_binding_without_tk(self):
        root=Root();view=cc.TkView(root,ttk_module=FakeTk)
        c=cc.ClientController(bootstrap(),FakeWorker(),Binding(),view)
        view.attach(c);c.start()
        self.assertEqual([row[0]for row in root.calls],[100,1000])
        self.assertEqual(view.labels['objective'].options['text'],bootstrap().objective)
        self.assertIn('WM_DELETE_WINDOW',root.protocols)
        self.assertEqual(root.protocols['WM_DELETE_WINDOW'],c.close)
        self.assertEqual(view.footnote.options['text'],'Closing this window leaves the task and engine running.')
        root.protocols['WM_DELETE_WINDOW']();self.assertTrue(c.closing)
        self.assertNotIn('token',str(view.labels))

    def test_opt_in_x_minimizes_without_revoking_binding_or_stopping_polling(self):
        root=Root();root.iconify=lambda:root.calls.append(('iconify',))
        view=cc.TkView(root,ttk_module=FakeTk,minimize_on_close=True)
        worker=FakeWorker();binding=Binding();c=cc.ClientController(bootstrap(),worker,binding,view)
        view.attach(c);c.start();worker.respond({'ok':True,'state':'window_ready'});c.tick()
        sent=list(worker.sent);binding_calls=list(binding.calls);pending=c.pending
        root.protocols['WM_DELETE_WINDOW']()
        self.assertEqual(root.calls[-1],('iconify',))
        self.assertFalse(c.closing);self.assertFalse(c.closed)
        self.assertEqual(binding.calls,binding_calls);self.assertEqual(worker.sent,sent)
        self.assertIs(c.pending,pending)
        view._poll();self.assertEqual(worker.sent[-1].method,'status')
        self.assertEqual(root.calls[-1][0],1000)
        view._tick();self.assertEqual(root.calls[-1][0],100)
        self.assertIn('taskbar',view.footnote.options['text'])
        self.assertIn('Stop engine',view.footnote.options['text'])
        c.cleanup_error='marker_removal_unconfirmed';c.render()
        self.assertEqual(view.footnote.options['text'],'Window cleanup is unconfirmed.')

    def test_opt_in_minimize_rejects_wrong_thread_before_window_call(self):
        root=Root();root.iconify=lambda:root.calls.append(('iconify',))
        view=cc.TkView(root,ttk_module=FakeTk,minimize_on_close=True)
        c=cc.ClientController(bootstrap(),FakeWorker(),Binding(),view);view.attach(c)
        errors=[]
        def wrong():
            try:root.protocols['WM_DELETE_WINDOW']()
            except Exception as error:errors.append(type(error))
        thread=threading.Thread(target=wrong);thread.start();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[PermissionError])
        self.assertFalse(any(row[0]=='iconify' for row in root.calls));self.assertFalse(c.closing)

    def test_opt_in_still_allows_recorded_stop_to_use_actual_close_protocol(self):
        root=Root();root.iconify=lambda:root.calls.append(('iconify',))
        view=cc.TkView(root,ttk_module=FakeTk,minimize_on_close=True)
        worker=FakeWorker();binding=Binding()
        c=cc.ClientController(bootstrap(),worker,binding,view,close_on_stop_recorded=True)
        view.attach(c);c.start();worker.respond({'ok':True,'state':'window_ready'});c.tick()
        c.poll_status();worker.respond(status());c.tick()
        view._click('stop');worker.respond({'ok':True,'state':'stop_requested',**life(stop_requested=True)});c.tick()
        self.assertTrue(c.closing);self.assertTrue(c.marker_removed)
        self.assertEqual(binding.calls,['install','remove'])
        self.assertFalse(any(row[0]=='iconify' for row in root.calls))

    def test_minimize_option_must_be_an_explicit_boolean(self):
        with self.assertRaises(TypeError):cc.TkView(Root(),ttk_module=FakeTk,minimize_on_close='yes')


if __name__=='__main__':unittest.main()
