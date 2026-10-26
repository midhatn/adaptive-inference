"""Retained local input with existing controller, fake boundaries and one real worker."""
import threading
import time
import unittest

from adaptive_inference.desktop import control_client as cc
from test_desktop_control_client import (
    Binding, FakeTk, FakeWorker, Root, bootstrap, life, receipt, status,
)


class IntentTests(unittest.TestCase):
    def client(self, *, terminal=False):
        worker, binding = FakeWorker(), Binding()
        view = cc.TkView(Root(), ttk_module=FakeTk, minimize_on_close=True)
        ids = iter('intent-' + str(n) for n in range(40))
        client = cc.ClientController(bootstrap(), worker, binding, view,
            id_factory=lambda: next(ids), close_on_stop_recorded=True)
        view.attach(client);client.start()
        worker.respond({'ok':True,'state':'window_ready'});client.tick()
        client.poll_status()
        worker.respond(status(**({'task_status':'accepted','demand':'fulfilled'} if terminal else {})))
        client.tick()
        return client, worker, binding, view

    def click(self, view, method):
        view.buttons[method].options['command']()

    def text(self, view):
        return view.labels['action'].options['text']

    def uncertain(self, method='resume'):
        c,w,b,v = self.client()
        c.action(method);original=c.latest
        w.respond(error='outcome_unconfirmed');c.tick()
        return c,w,b,v,original

    def test_each_command_remains_enabled_and_is_retained_during_status(self):
        for method in ('pause','resume','cancel','stop'):
            with self.subTest(method=method):
                c,w,b,v=self.client(terminal=method=='stop')
                before=len(w.sent)
                v._poll();v._tick()
                self.assertEqual(v.buttons[method].options['state'],'normal')
                self.click(v,method)
                queued=c._local_intent[0]
                self.assertEqual(queued.method,method)
                self.assertEqual(c.pending.method,'status')
                self.assertEqual(len(w.sent),before+1)
                self.assertIsNone(c.latest)
                self.assertFalse(c.stop_requested);self.assertFalse(c.stop_recorded)
                self.assertIn('Waiting locally',self.text(v));self.assertIn('not been sent',self.text(v))
                self.assertFalse(any(c.buttons().values()))
                for _ in range(3):
                    self.assertFalse(c.poll_status());c.tick()
                self.assertEqual(len(w.sent),before+1)
                w.respond(status(**({'task_status':'accepted','demand':'fulfilled'} if method=='stop' else {})))
                c.tick()
                self.assertIsNone(c._local_intent)
                self.assertIs(c.pending,queued);self.assertIs(c.latest,queued)
                self.assertEqual(len(w.sent),before+2)
                self.assertEqual(sum(r==queued for r in w.sent),1)
                self.assertIn('not yet confirmed',self.text(v))
                self.assertFalse(c.poll_status())
                if method=='stop':
                    w.respond({'ok':True,'state':'stop_requested',**life(stop_requested=True)})
                else:
                    w.respond({'ok':True,'control':receipt(queued,outcome='applied',owner_acknowledged=True)})
                c.tick()
                if method=='stop':
                    self.assertTrue(c.closing);self.assertEqual(b.calls,['install','remove'])
                else:self.assertEqual(c.latest_stage,'applied')

    def test_idle_click_sends_once_and_prevents_poll_overtaking(self):
        for method in ('pause','resume','cancel','stop'):
            c,w,b,v=self.client()
            self.click(v,method);request=c.latest;before=len(w.sent)
            v._poll();c.tick()
            self.assertEqual(len(w.sent),before)
            self.assertEqual(sum(r==request for r in w.sent),1)
            self.assertIsNone(c._local_intent)

    def test_duplicate_and_conflicting_clicks_do_not_replace_the_first_intent(self):
        c,w,b,v=self.client();c.poll_status();self.assertTrue(c.action('pause'))
        queued=c._local_intent
        for method in ('pause','resume','cancel','stop','retry'):
            self.click(v,method)
            self.assertIs(c._local_intent,queued)
        self.assertEqual(len(c._ids),1)
        w.respond(status());c.tick()
        self.assertEqual([r.method for r in w.sent],['window_ready','status','status','pause'])

    def test_last_reserved_id_drains_without_renewing_the_capacity(self):
        c,w,b,v=self.client();c._ids={f'old-{n}' for n in range(31)}
        c.poll_status();self.assertTrue(c.action('pause'))
        request=c._local_intent[0];self.assertEqual(len(c._ids),32)
        w.respond(status());c.tick();self.assertIs(c.latest,request)
        w.respond({'ok':True,'control':receipt(request)});c.tick()
        self.assertFalse(c.action('pause'));self.assertFalse(c.action('resume'));self.assertFalse(c.action('cancel'))
        self.assertTrue(c.buttons()['stop'])

    def test_reused_id_is_rejected_before_local_acceptance(self):
        c,w,b,v=self.client();c._ids={'already-used'};c._id_factory=lambda:'already-used'
        c.poll_status();before=list(w.sent)
        with self.assertRaisesRegex(cc.ClientError,'request_identity_reused'):c.action('pause')
        self.assertIsNone(c._local_intent);self.assertEqual(w.sent,before)

    def test_new_terminal_state_prevents_queued_task_controls_but_not_stop(self):
        for method in ('pause','resume','cancel'):
            c,w,b,v=self.client();c.poll_status();c.action(method)
            w.respond(status(task_status='accepted',demand='fulfilled'));c.tick()
            self.assertIsNone(c._local_intent);self.assertIsNone(c.latest)
            self.assertNotIn(method,[r.method for r in w.sent])
            self.assertIn('Not sent;',self.text(v));self.assertIn('latest task state',self.text(v))
            self.assertTrue(c.buttons()['stop'])

    def test_clean_status_errors_preserve_safe_commands_but_block_new_resume(self):
        for method in ('pause','resume','cancel','stop'):
            c,w,b,v=self.client();c.poll_status();c.action(method)
            w.respond(error='outcome_unconfirmed');c.tick()
            self.assertFalse(c.status_valid)
            self.assertIsNone(c.cleanup_error)
            if method=='resume':
                self.assertIsNone(c.latest);self.assertIn('Not sent;',self.text(v))
            else:self.assertEqual(c.latest.method,method)

    def test_stale_and_malformed_status_do_not_authorize_queued_resume(self):
        for reply in (status(task_revision=0),status(objective='wrong'),{'ok':False,'error':'projection_refused'}):
            c,w,b,v=self.client();c.poll_status();c.action('resume')
            w.respond(reply);c.tick()
            self.assertFalse(c.status_valid);self.assertIsNone(c.latest)
            self.assertNotIn('resume',[r.method for r in w.sent])
            self.assertIn('Not sent;',self.text(v))

    def test_cleanup_failure_blocks_every_queued_command_without_replay(self):
        for method in ('pause','resume','cancel','stop'):
            c,w,b,v=self.client();c.poll_status();c.action(method)
            w.respond(status(),cleanup_error='socket_close_unconfirmed');c.tick()
            self.assertIsNone(c._local_intent);self.assertIsNone(c.latest)
            self.assertFalse(any(c.buttons().values()))
            self.assertIn('cleanup is unconfirmed',self.text(v))
            before=len(w.sent)
            for _ in range(3):c.tick()
            self.assertEqual(len(w.sent),before)

    def test_explicit_retry_is_retained_with_the_original_identity(self):
        for method in ('resume','stop'):
            c,w,b,v,original=self.uncertain(method)
            c.poll_status();c.tick()
            self.assertEqual(v.buttons['retry'].options['state'],'normal')
            self.click(v,'retry')
            self.assertIs(c._local_intent[0],original)
            self.assertIn('this retry has not been sent',self.text(v))
            self.assertIs(c.latest,original);self.assertEqual(c.latest_stage,'unconfirmed')
            self.assertEqual(sum(r==original for r in w.sent),1)
            # Existing explicit same-ID Retry reconciles an uncertain request;
            # unlike a new Resume, it does not require freshly valid status.
            w.respond(error='outcome_unconfirmed');c.tick()
            self.assertFalse(c.status_valid);self.assertIs(c.pending,original)
            self.assertEqual(sum(r==original for r in w.sent),2)
            self.assertEqual(len(c._ids),int(method!='stop'))

    def test_new_ack_settles_queued_retry_without_resending(self):
        c,w,b,v,original=self.uncertain()
        c.poll_status();c.retry()
        w.respond(status(controls=[receipt(original,outcome='applied',owner_acknowledged=True)]));c.tick()
        self.assertEqual(c.latest_stage,'applied')
        self.assertEqual(sum(r==original for r in w.sent),1)
        self.assertIn('Retry not sent;',self.text(v))

    def test_recorded_stop_settles_retry_then_uses_existing_close_path(self):
        c,w,b,v,original=self.uncertain('stop')
        c.poll_status();c.retry()
        w.respond(status(stop_requested=True,waiting_reason='stop_requested'));c.tick()
        self.assertEqual(sum(r==original for r in w.sent),1)
        self.assertTrue(c.stop_recorded);self.assertTrue(c.closing)
        self.assertIsNone(c._local_intent);self.assertIn('Retry not sent;',self.text(v))
        self.assertEqual(b.calls,['install','remove'])

    def test_old_ack_does_not_overwrite_a_new_locally_refused_intent(self):
        c,w,b,v,original=self.uncertain()
        c.poll_status();c.action('pause')
        w.submit=lambda request:False
        acknowledged=status(controls=[receipt(original,outcome='applied',owner_acknowledged=True)])
        w.respond(acknowledged);c.tick()
        self.assertIs(c.latest,original);self.assertEqual(c.latest_stage,'applied')
        self.assertIn('Not sent;',self.text(v));self.assertIn('worker',self.text(v))
        # Even later presentations of the prior ACK retain the unsent outcome.
        c._apply_control(acknowledged['status']['controls'][0]);c.render()
        self.assertIn('Not sent;',self.text(v))

    def test_close_settles_unsent_intent_and_never_replays_into_new_session(self):
        c,w,b,v=self.client();c.poll_status();c.action('cancel');c.close()
        self.assertIsNone(c._local_intent);self.assertIn('Not sent;',self.text(v))
        w.respond(status());w.results.append(cc.Result(cc.Request('window_closed'),
            {'ok':True,'state':'window_closed','task_cancelled':False}))
        w.is_joined=True;c.tick()
        self.assertTrue(c.closed);self.assertNotIn('cancel',[r.method for r in w.sent])
        other,worker,_,_=self.client()
        self.assertIsNone(other._local_intent);self.assertIsNone(other.latest)
        self.assertEqual([r.method for r in worker.sent],['window_ready','status'])

    def test_close_or_cleanup_of_retry_does_not_erase_original_uncertainty(self):
        for closing in (False,True):
            c,w,b,v,original=self.uncertain()
            c.poll_status();c.retry()
            if closing:c.close()
            else:
                w.respond(error='outcome_unconfirmed',cleanup_error='socket_close_unconfirmed');c.tick()
            self.assertIs(c.latest,original);self.assertEqual(c.latest_stage,'unconfirmed')
            self.assertIn('Retry not sent;',self.text(v))
            self.assertEqual(sum(r==original for r in w.sent),1)

    def test_worker_refusal_is_visible_and_is_not_retried_by_ticks(self):
        c,w,b,v=self.client();c.poll_status();c.action('pause')
        attempts=[]
        w.submit=lambda request:(attempts.append(request) or False)
        w.respond(status());c.tick()
        self.assertEqual(len(attempts),1);self.assertIsNone(c._local_intent)
        self.assertIsNone(c.latest);self.assertIn('Not sent;',self.text(v))
        for _ in range(5):c.tick()
        self.assertEqual(len(attempts),1);self.assertEqual(len(c._ids),1)

    def test_submission_exception_retains_uncertainty_and_fences_replay(self):
        c,w,b,v=self.client();c.poll_status();c.action('pause');queued=c._local_intent[0]
        def broken(request):raise RuntimeError('injected unknown submission outcome')
        w.submit=broken;w.respond(status());c.tick()
        self.assertIs(c.pending,queued);self.assertIs(c.latest,queued)
        self.assertEqual(c.latest_stage,'unconfirmed');self.assertIsNone(c._local_intent)
        self.assertFalse(any(c.buttons().values()));self.assertIn('Dispatch is unconfirmed',self.text(v))
        w.results.append(cc.Result(queued,{'ok':True,'control':receipt(queued)}));c.tick()
        self.assertEqual(c.latest_stage,'pending');self.assertIsNone(c.pending)
        self.assertIsNotNone(c.cleanup_error)


class WorkerIntentTests(unittest.TestCase):
    def test_actual_worker_finishes_status_before_one_retained_command(self):
        entered,release=threading.Event(),threading.Event()
        seen=[];status_count=0;errors=[]
        def exchange(request):
            nonlocal status_count
            seen.append(request)
            if request.method=='status':
                status_count+=1
                if status_count==2:
                    entered.set()
                    if not release.wait(2):errors.append('status barrier timed out')
                return cc.Result(request,status())
            if request.method=='window_ready':return cc.Result(request,{'ok':True,'state':'window_ready'})
            if request.method=='window_closed':return cc.Result(request,{'ok':True,'state':'window_closed','task_cancelled':False})
            return cc.Result(request,{'ok':True,'control':receipt(request,outcome='applied',owner_acknowledged=True)})
        worker=cc.NetworkWorker(exchange);view=cc.TkView(Root(),ttk_module=FakeTk)
        client=cc.ClientController(bootstrap(),worker,Binding(),view,id_factory=lambda:'thread-command')
        view.attach(client)
        def until(predicate, *, consume=True):
            end=time.monotonic()+2
            while not predicate() and time.monotonic()<end:
                if consume:client.tick()
                threading.Event().wait(.001)
            self.assertTrue(predicate())
        try:
            client.start();until(lambda:client.ready)
            client.poll_status();until(lambda:client.status is not None)
            client.poll_status();self.assertTrue(entered.wait(2))
            self.assertTrue(client.action('pause'));queued=client._local_intent[0]
            for _ in range(3):
                self.assertFalse(client.poll_status());client.tick()
            self.assertNotIn('pause',[r.method for r in seen])
            release.set();until(lambda:not worker._results.empty(),consume=False)
            self.assertNotIn('pause',[r.method for r in seen])
            self.assertFalse(worker.submit(cc.Request('status')))
            until(lambda:client.latest_stage=='applied')
            self.assertEqual([r.method for r in seen],['window_ready','status','status','pause'])
            self.assertEqual(sum(r==queued for r in seen),1)
            self.assertEqual(errors,[])
        finally:
            release.set();client.close();worker._thread.join(timeout=2)
            self.assertFalse(worker._thread.is_alive());client.tick()
            self.assertTrue(worker.joined());self.assertTrue(client.closed)


if __name__=='__main__':unittest.main()
