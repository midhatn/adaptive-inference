# SPDX-License-Identifier: Apache-2.0
"""Private prepared-task presentation client; external boundaries are injected.

Importing this file opens no Tk window, socket, file or Windows API. See DESIGN.md.
"""
from dataclasses import dataclass, field
import json
import math
import queue
import re
import secrets
import socket
import struct
import threading
import time

REQUEST_LIMIT, RESPONSE_LIMIT, BOOTSTRAP_LIMIT = 4096, 65536, 24576
COMMANDS = frozenset(('pause', 'resume', 'cancel'))
METHODS = COMMANDS | {'status', 'window_ready', 'window_closed', 'stop'}
ERROR_CODES = {'invalid_request', 'unauthorized', 'projection_refused', 'stopping',
               'conflicting_request_id', 'capacity_exhausted', 'session_not_ready',
               'runtime_error', 'request_timeout'}
FAULTS = {'handler_failed','stream_close_failed','intent_revocation_failed',
          'admission_fence_failed','stop_unresolved','stop_failed'}
LIFECYCLE = {'stop_requested','stop_confirmed','pending_mutations','unknown_mutations',
             'handlers','pending_connections','stream_close_failures','faults'}


class ClientError(ValueError):
    """Fixed public error codes only; never attach payloads/credentials."""


def label(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value):
        raise ClientError('invalid_identity')
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClientError('invalid_json')
        result[key] = value
    return result


def constant(_):
    raise ClientError('invalid_json')


def decode(data, limit, *, line=False):
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise ClientError('invalid_frame')
    if line and (not data.endswith(b'\n') or data.count(b'\n') != 1):
        raise ClientError('invalid_frame')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ClientError('invalid_json') from None


@dataclass(frozen=True, repr=False)
class Bootstrap:
    host_epoch: str
    session_id: str
    task_id: str
    objective: str
    token: str = field(repr=False)
    host: str
    port: int
    marker_name: str
    marker_value: int

    def __post_init__(self):
        for value in (self.host_epoch, self.session_id, self.task_id):
            label(value)
        if (type(self.objective) is not str or not self.objective.strip()
                or len(self.objective.encode('utf-8')) > 16384
                or type(self.token) is not str or not re.fullmatch(r'[0-9a-f]{64}',self.token)
                or self.host != '127.0.0.1' or type(self.port) is not int or not 1 <= self.port <= 65535
                or type(self.marker_name) is not str or not 16 <= len(self.marker_name) <= 128
                or any(not 33 <= ord(char) <= 126 for char in self.marker_name)
                or type(self.marker_value) is not int or not 0 < self.marker_value < 1 << (8*struct.calcsize('P'))):
            raise ClientError('invalid_bootstrap')

    @classmethod
    def from_private_reader(cls, reader):
        """Reader owns bounded private/authentic file verification; never repairs ACLs here."""
        try:
            value = decode(reader(BOOTSTRAP_LIMIT+1), BOOTSTRAP_LIMIT)
            if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
                raise ClientError('invalid_bootstrap')
            return cls(**value)
        except Exception:
            raise ClientError('bootstrap_unavailable') from None


@dataclass(frozen=True)
class Request:
    method: str
    request_id: str | None = None

    def __post_init__(self):
        if type(self.method) is not str or self.method not in METHODS:
            raise ClientError('invalid_method')
        if self.method in COMMANDS:
            label(self.request_id)
        elif self.request_id is not None:
            raise ClientError('invalid_request_id')


def control(value, *, request=None):
    keys = {'request_id','command','sequence','owner_acknowledged','outcome','recorded'}
    if type(value) is not dict or set(value) != keys:
        raise ClientError('invalid_reply')
    label(value['request_id'])
    if (value['command'] not in COMMANDS or type(value['sequence']) is not int
            or not 1 <= value['sequence'] <= 32 or type(value['owner_acknowledged']) is not bool
            or value['outcome'] not in {'pending','applied','rejected'} or value['recorded'] is not True
            or value['outcome']=='applied' and not value['owner_acknowledged']
            or value['outcome']=='pending' and value['owner_acknowledged']
            or request is not None and (value['request_id'] != request.request_id or value['command'] != request.method)):
        raise ClientError('invalid_reply')


def lifecycle(value):
    if (type(value['stop_requested']) is not bool or type(value['stop_confirmed']) is not bool
            or value['stop_confirmed'] and not value['stop_requested']
            or any(type(value[k]) is not int or not 0 <= value[k] <= 32 for k in LIFECYCLE-{'stop_requested','stop_confirmed','faults'})
            or type(value['faults']) is not list or len(value['faults']) > len(FAULTS)
            or any(type(v) is not str or v not in FAULTS for v in value['faults'])
            or value['stop_confirmed'] and (value['faults'] or value['unknown_mutations'] or value['pending_mutations'])):
        raise ClientError('invalid_reply')


def validate_reply(value, request, bootstrap):
    if type(value) is not dict or type(value.get('ok')) is not bool:
        raise ClientError('invalid_reply')
    if value['ok'] is False:
        if set(value) != {'ok','error'} or type(value['error']) is not str or value['error'] not in ERROR_CODES:
            raise ClientError('invalid_reply')
        return value
    method = request.method
    if method=='status':
        if set(value) != {'ok','status'} or type(value['status']) is not dict:
            raise ClientError('invalid_reply')
        s = value['status']
        keys = {'host_phase','task_status','task_revision','demand','waiting_reason','controls','objective'} | LIFECYCLE
        if (set(s) != keys or s['objective'] != bootstrap.objective
                or s['host_phase'] not in {'starting','ready','parked','restoring','stopping','closed','fault'}
                or s['task_status'] not in {'pending','accepted','exhausted'}
                or type(s['task_revision']) is not int or not 0 <= s['task_revision'] < 256
                or s['demand'] not in {None,'active','waiting','paused','cancelled','fulfilled'}
                or s['waiting_reason'] not in {None,'foreground','resources','paused','budget_expired','reconciliation','stop_requested','operation_inflight','unknown'}
                or type(s['controls']) is not list or len(s['controls']) > 32):
            raise ClientError('invalid_reply')
        ids, sequences = set(), set()
        for row in s['controls']:
            control(row)
            if row['request_id'] in ids or row['sequence'] in sequences:
                raise ClientError('invalid_reply')
            ids.add(row['request_id']);sequences.add(row['sequence'])
        lifecycle(s)
    elif method in COMMANDS:
        if set(value)=={'ok','control'}:
            control(value['control'],request=request)
        elif set(value)=={'ok','refusal'}:
            refusal = value['refusal']
            if (type(refusal) is not dict or set(refusal) != {'request_id','command','reason','recorded'}
                    or refusal['request_id'] != request.request_id or refusal['command'] != request.method
                    or refusal['reason'] != 'execution_budget_expired' or refusal['recorded'] is not False):
                raise ClientError('invalid_reply')
        elif (set(value) != {'ok','state','request_id','recorded'} or value['state'] != 'pending'
              or value['request_id'] != request.request_id or value['recorded'] is not None):
            raise ClientError('invalid_reply')
    elif method=='stop':
        if set(value) != {'ok','state'}|LIFECYCLE or value['state'] != 'stop_requested' or value['stop_requested'] is not True:
            raise ClientError('invalid_reply')
        lifecycle(value)
    elif method=='window_ready':
        if value != {'ok':True,'state':'window_ready'}:
            raise ClientError('invalid_reply')
    elif (value != {'ok':True,'state':'window_closed','task_cancelled':False}
          or type(value.get('task_cancelled')) is not bool):
        raise ClientError('invalid_reply')
    return value


@dataclass(frozen=True)
class Result:
    request: Request
    reply: dict | None = None
    error: str | None = None
    cleanup_error: str | None = None
    discarded: bool = False


class WireExchange:
    """One total deadline; injected factory creates one owned plain-TCP socket.

    No default socket constructor, connection, automatic retry or payload logging.
    An injected blocking operation remains the worker's join obligation.
    """
    def __init__(self, bootstrap, socket_factory, *, timeout_s=2, clock=time.monotonic):
        if type(bootstrap) is not Bootstrap or not callable(socket_factory) or not callable(clock):
            raise TypeError('Trusted bootstrap and socket factory required')
        if type(timeout_s) not in (int,float) or not 0 < timeout_s <= 30:
            raise ClientError('invalid_deadline')
        self.bootstrap,self.socket_factory,self.timeout,self.clock=bootstrap,socket_factory,timeout_s,clock
        # A failed close is retained and fences new connections. It is not a
        # reason to drop the object or accumulate another socket on every poll.
        self._unresolved_socket=None

    def __call__(self, request):
        if self._unresolved_socket is not None:
            return Result(request,error='outcome_unconfirmed',cleanup_error='socket_close_unconfirmed')
        b=self.bootstrap
        data={'host_epoch':b.host_epoch,'session_id':b.session_id,'task_id':b.task_id,'token':b.token,'method':request.method}
        if request.request_id is not None:data['request_id']=request.request_id
        encoded=(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
        if len(encoded)>REQUEST_LIMIT:raise ClientError('request_too_large')
        sock=None;reply=None;error=None;cleanup=None
        try:
            start=self.clock();last=start
            if type(start) not in (int,float) or not math.isfinite(start) or start<0:raise ClientError('clock_invalid')
            deadline=start+self.timeout
            def remaining():
                nonlocal last
                now=self.clock()
                if type(now) not in (int,float) or not math.isfinite(now) or now<last or now>=deadline:
                    raise ClientError('request_timeout')
                last=now
                return deadline-now
            sock=self.socket_factory()
            sock.settimeout(remaining());sock.connect((b.host,b.port))
            sock.settimeout(remaining());sock.sendall(encoded)
            sock.settimeout(remaining());sock.shutdown(socket.SHUT_WR)
            received=bytearray()
            while True:
                sock.settimeout(remaining());chunk=sock.recv(RESPONSE_LIMIT+1-len(received))
                if type(chunk) is not bytes:raise ClientError('invalid_reply')
                if not chunk:break
                received.extend(chunk)
                if len(received)>RESPONSE_LIMIT:raise ClientError('reply_too_large')
            remaining()
            reply=validate_reply(decode(bytes(received),RESPONSE_LIMIT,line=True),request,b)
        except Exception:
            error='outcome_unconfirmed'
        finally:
            if sock is not None:
                try:sock.close()
                except Exception:
                    self._unresolved_socket=sock
                    cleanup='socket_close_unconfirmed'
        return Result(request,reply,error,cleanup)


class NetworkWorker:
    """Single strongly retained thread, at most one undelivered ordinary result."""
    def __init__(self, exchange):
        self._exchange=exchange
        self._condition=threading.Condition()
        self._queue=None;self._outstanding=False;self._closing=False;self._started=False
        self._results=queue.Queue(maxsize=3)
        self._thread=threading.Thread(target=self._run,name='adaptive-ui-control',daemon=False)

    def start(self):
        if self._started or self._closing:raise ClientError('worker_already_started')
        self._thread.start();self._started=True

    def submit(self, request):
        with self._condition:
            if not self._started or self._closing or self._outstanding:return False
            self._queue=request;self._outstanding=True;self._condition.notify()
            return True

    def close(self):
        with self._condition:
            if self._closing:return
            self._closing=True
            if self._queue is not None:
                self._results.put_nowait(Result(self._queue,error='not_sent',discarded=True))
                self._queue=None
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                while self._queue is None and not self._closing:self._condition.wait()
                closing=self._closing
                request=Request('window_closed') if closing else self._queue
                self._queue=None
            try:
                result=self._exchange(request)
                if type(result) is not Result or result.request != request:raise ClientError('invalid_exchange')
            except BaseException:
                result=Result(request,error='outcome_unconfirmed')
            self._results.put_nowait(result)
            if closing:return

    def take(self):
        try:result=self._results.get_nowait()
        except queue.Empty:return None
        if result.request.method!='window_closed':
            with self._condition:self._outstanding=False
        return result

    def joined(self):
        if not self._started:return True
        if self._thread.is_alive():return False
        self._thread.join(timeout=0)
        return True


WAITING = {None:'Ready for the next step.', 'foreground':'Waiting while your other work has priority.',
    'budget_expired':"This run's time budget ended. Your saved work is preserved.",
           'resources':'Waiting for enough available memory or computing resources.',
           'paused':'Paused. Resume when you want the task to continue.',
           'reconciliation':'Waiting for an earlier operation to be checked.',
           'stop_requested':'Stopping safely; waiting for the current work to finish.',
           'operation_inflight':'The current operation is still running.',
           'unknown':'Current progress is not yet known.'}


class ClientController:
    """Main-thread presentation state. Injected binding does not grant host authority."""
    def __init__(self, bootstrap, worker, binding, view, *, id_factory=lambda:secrets.token_hex(16), close_on_stop_recorded=False):
        if type(close_on_stop_recorded) is not bool:raise TypeError('Explicit presentation close mode required')
        self.bootstrap,self.worker,self.binding,self.view=bootstrap,worker,binding,view
        self._owner=threading.current_thread();self._ids=set();self._id_factory=id_factory
        self.pending=None;self.latest=None;self.latest_stage=None;self.status=None
        self.status_valid=False
        self.ready=False;self.closing=False;self.closed=False;self.stop_requested=False
        self.connection='Connecting to the engine.';self.action_text='No control request sent.'
        self.marker_removed=False;self.close_ack=False;self.cleanup_error=None
        self._started=False;self._destroy_attempted=False
        self.stop_recorded=False;self._close_on_stop_recorded=close_on_stop_recorded
        self._local_intent=None;self._local_feedback=None

    def _main(self):
        if threading.current_thread() is not self._owner:raise PermissionError('UI belongs to its creator thread')

    def _send(self,request):
        if self.pending is not None or not self.worker.submit(request):return False
        self.pending=request;return True

    def start(self):
        self._main()
        if self._started:raise ClientError('client_already_started')
        self._started=True
        try:
            if self.binding.install() is not True:raise ClientError('window_binding_unconfirmed')
            self.worker.start()
            if not self._send(Request('window_ready')):raise ClientError('worker_unavailable')
        except Exception:
            self.connection='Window identity could not be confirmed.'
            self.close()
        self.render()

    def action(self,method):
        self._main()
        if method not in COMMANDS|{'stop'}:raise ClientError('invalid_action')
        if not self.buttons()[method]:return False
        request=None
        if method in COMMANDS:
            if len(self._ids)>=32:raise ClientError('control_capacity_exhausted')
            identity=label(self._id_factory())
            if identity in self._ids:raise ClientError('request_identity_reused')
            request=Request(method,identity)
        else:request=Request(method)
        if request.request_id:self._ids.add(request.request_id)
        return self._retain_intent(request,retry=False)

    def retry(self):
        self._main()
        if not self.buttons()['retry']:return False
        return self._retain_intent(self.latest,retry=True)

    def _eligible(self,method,*,retry=False,reserved=False):
        available=(self.ready and not self.closing and self.cleanup_error is None
            and (self.pending is None or self.pending.method=='status'))
        if not available:return False
        terminal=self.status is not None and (self.status['task_status']!='pending'
            or self.status['demand'] in {'cancelled','fulfilled'})
        controls=(self.status is not None and not terminal and not self.stop_requested
            and self.status['waiting_reason']!='budget_expired')
        if retry:
            return (self.latest is not None and self.latest.method==method
                and self.latest_stage=='unconfirmed' and (method=='stop' or controls))
        if method=='stop':return not self.stop_requested
        return controls and (reserved or len(self._ids)<32) and (method!='resume' or self.status_valid)

    def _retain_intent(self,request,*,retry):
        # The GUI owns one unsent intent; the worker still owns at most one
        # request. An earlier status result must release that slot first.
        self._local_intent=(request,retry)
        self._local_feedback=('Retry waiting locally for the current status check; this retry has not been sent.' if retry
            else 'Waiting locally for the current status check; this request has not been sent.')
        waiting=self.pending is not None
        sent=self._drain_intent()
        self.render()
        return waiting or sent

    def _drain_intent(self):
        if self._local_intent is None or self.pending is not None:return False
        request,retry=self._local_intent
        self._local_intent=None
        prefix='Retry not sent; ' if retry else 'Not sent; '
        if not self._eligible(request.method,retry=retry,reserved=True) or retry and request!=self.latest:
            reason=('connection cleanup is unconfirmed.' if self.cleanup_error is not None
                else 'the latest task state no longer permits this request.')
            self._local_feedback=prefix+reason
            return False
        try:
            sent=self._send(request)
        except Exception:
            # Submission may have partly succeeded. Retain the possible reply
            # and fence further dispatch rather than calling this "not sent".
            self.pending=request;self.cleanup_error='worker_submission_unconfirmed'
            self.latest=request;self.latest_stage='unconfirmed'
            self._local_feedback='Dispatch is unconfirmed; no automatic retry was sent.'
            return False
        if not sent:
            self._local_feedback=prefix+'the control worker did not accept this attempt.'
            return False
        self._local_feedback=None
        self.latest=request;self.latest_stage='unconfirmed'
        self.action_text=('Checking the same request; recording is not yet confirmed.' if retry
            else 'Request queued; recording is not yet confirmed.')
        if request.method=='stop':self.stop_requested=True
        return True

    def poll_status(self):
        self._main()
        if self.closing or not self.ready or self._local_intent is not None:return False
        return self._send(Request('status'))

    def _apply_control(self,row):
        if self.latest is None or row['request_id'] != self.latest.request_id:return
        if row['command'] != self.latest.method:raise ClientError('conflicting_control')
        stage=row['outcome']
        if self.latest_stage in {'applied','rejected'} and stage != self.latest_stage:
            raise ClientError('control_outcome_regressed')
        self.latest_stage=stage
        self.action_text={'pending':'Recorded; waiting for the agent to acknowledge.',
                          'applied':'Applied and acknowledged by the agent.',
                          'rejected':'The agent rejected this request.'}[stage]

    def _result(self,result):
        request=result.request
        if (request.method=='window_closed' and not self.closing
                or request.method!='window_closed' and request!=self.pending):
            raise ClientError('unexpected_reply')
        if request==self.pending:self.pending=None
        if result.cleanup_error:self.cleanup_error=result.cleanup_error
        if result.discarded:
            if request==self.latest:
                self.latest_stage='unrecorded';self.action_text='Not sent; the window closed before dispatch.'
            return
        if result.error:
            if request==self.latest:
                self.latest_stage='unconfirmed';self.action_text='Outcome unconfirmed. Refresh status or retry this same request.'
            if request.method!='window_closed':
                self.status_valid=False;self.connection='Status unavailable; no outcome is assumed.'
            return
        reply=validate_reply(result.reply,request,self.bootstrap)
        if not reply['ok']:
            if request==self.latest:
                self.latest_stage='unconfirmed';self.action_text='Request outcome is unconfirmed. No automatic retry was sent.'
            self.connection='The engine could not confirm this request.'
            self.status_valid=False
            return
        if request.method=='window_ready':
            if not self.closing:self.ready=True;self.connection='Connected. Refreshing task status.'
        elif request.method=='window_closed':self.close_ack=True
        elif request.method=='status':
            new=reply['status']
            if self.status and new['task_revision']<self.status['task_revision']:raise ClientError('status_regressed')
            self.status=new;self.status_valid=True;self.connection='Connected.'
            self.stop_requested |= new['stop_requested']
            self.stop_recorded |= new['stop_requested']
            for row in new['controls']:self._apply_control(row)
            if self.latest is not None and self.latest.method=='stop' and new['stop_requested']:
                self.latest_stage='applied' if new['stop_confirmed'] else 'pending'
                self.action_text='Engine stopped safely.' if new['stop_confirmed'] else 'Stop requested; waiting for safe shutdown.'
        elif request.method=='stop':
            self.stop_requested=True
            self.stop_recorded=True
            self.latest_stage='applied' if reply['stop_confirmed'] else 'pending'
            self.action_text='Engine stopped safely.' if reply['stop_confirmed'] else 'Stop requested; waiting for safe shutdown.'
        elif 'control' in reply:self._apply_control(reply['control'])
        elif 'refusal' in reply and request==self.latest:
            self.latest_stage='unrecorded'
            self.action_text="Not recorded; this run's time budget ended. Your saved work is preserved."
        elif request==self.latest:
            self.latest_stage='unconfirmed';self.action_text='The engine is checking this request; recording is not confirmed.'
        if self._close_on_stop_recorded and self.stop_recorded:self.close()

    def tick(self):
        self._main()
        for _ in range(3):
            result=self.worker.take()
            if result is None:break
            try:self._result(result)
            except Exception:
                self.status_valid=False;self.connection='Invalid or stale status; no outcome is assumed.'
        self._drain_intent()
        if self.closing and self.marker_removed and self.worker.joined() and not self._destroy_attempted:
            self._destroy_attempted=True
            try:self.view.destroy();self.closed=True
            except Exception:self.cleanup_error='window_destroy_unconfirmed'
        if not self.closed:self.render()

    def close(self):
        self._main()
        if self.closing:return
        if self._local_intent is not None:
            _,retry=self._local_intent;self._local_intent=None
            self._local_feedback=('Retry not sent; the window closed. The earlier request outcome is unchanged.'
                if retry else 'Not sent; the window closed before local dispatch.')
        self.closing=True;self.ready=False
        try:
            self.marker_removed=self.binding.remove() is True
            if not self.marker_removed:self.cleanup_error='marker_removal_unconfirmed'
        except Exception:self.cleanup_error='marker_removal_unconfirmed'
        self.worker.close()
        self.connection=('Stop requested. Closing this window; shutdown completion remains unconfirmed.'
            if self.stop_recorded else 'Closing this window. The task and engine are not being stopped.')
        self.render()

    def buttons(self):
        free=self._local_intent is None
        return {**{method:free and self._eligible(method) for method in (*COMMANDS,'stop')},
                'retry':free and self.latest is not None and self._eligible(self.latest.method,retry=True)}

    def render(self):
        self._main()
        s=self.status
        task='Task status is not yet available.'
        waiting='Waiting for the engine to confirm the window.'
        if s:
            task={'pending':'Task is in progress.','accepted':'Task completed.','exhausted':'Task stopped after its attempt limit.'}[s['task_status']]
            if s['demand']=='cancelled':task='Task cancelled; the checkpoint is preserved.'
            elif s['demand']=='paused':task='Task paused.'
            waiting=WAITING[s['waiting_reason']]
            terminal=s['task_status']!='pending' or s['demand'] in {'cancelled','fulfilled'}
            if (self.status_valid and terminal and not s['stop_requested']
                    and not s['unknown_mutations'] and not s['faults']
                    and s['waiting_reason'] in {None,'foreground','resources','paused'}):
                waiting=''
            if s['stop_confirmed']:waiting='Engine stopped safely.'
            elif s['host_phase']=='closed':waiting='Engine is closed; stop confirmation is unavailable.'
            elif s['host_phase']=='fault':waiting='The engine reported a problem; progress is not assumed.'
        self.view.render({'objective':self.bootstrap.objective,'connection':self.connection,'task':task,
            'waiting':waiting,'action':self._local_feedback or self.action_text,'buttons':self.buttons(),
            'closing':self.closing,'cleanup_unconfirmed':self.cleanup_error is not None})


class TkView:
    """Lazy ttk adapter for an externally created root. Tests supply fake widgets."""
    def __init__(self,root,*,ttk_module=None,minimize_on_close=False):
        if type(minimize_on_close) is not bool:
            raise TypeError('Window minimize behavior must be an explicit boolean')
        if ttk_module is None:
            from tkinter import ttk as ttk_module
        self.root=root;self.owner=threading.current_thread();self.controller=None
        self.minimize_on_close=minimize_on_close
        self._rendered_options={}
        self.frame=ttk_module.Frame(root,padding=20);self.frame.grid(sticky='nsew')
        self.labels={}
        for row,name in enumerate(('objective','connection','task','waiting','action')):
            widget=ttk_module.Label(self.frame,text='',wraplength=600,justify='left')
            widget.grid(row=row,column=0,columnspan=5,sticky='w',pady=6);self.labels[name]=widget
        self.buttons={}
        for column,(name,title) in enumerate((('pause','Pause'),('resume','Resume'),('cancel','Cancel task'),('stop','Stop engine'),('retry','Retry request'))):
            widget=ttk_module.Button(self.frame,text=title,command=lambda name=name:self._click(name))
            widget.grid(row=5,column=column,padx=4,pady=12);self.buttons[name]=widget
        self._normal_footer=('X minimizes this window to the taskbar. Select it there to restore it. Use Stop engine to shut down.'
                if minimize_on_close else 'Closing this window leaves the task and engine running.')
        self.footnote=ttk_module.Label(self.frame,text=self._normal_footer,wraplength=600)
        self.footnote.grid(row=6,column=0,columnspan=5,sticky='w')

    def _main(self):
        if threading.current_thread() is not self.owner:raise PermissionError('Tk view belongs to creator thread')

    def attach(self,controller):
        self._main()
        if self.controller is not None:raise ClientError('view_already_attached')
        self.controller=controller
        self.root.protocol('WM_DELETE_WINDOW',self._minimize if self.minimize_on_close else controller.close)
        self.root.after(100,self._tick)
        self.root.after(1000,self._poll)

    def _minimize(self):
        self._main()
        self.root.iconify()

    def _click(self,name):
        self._main()
        if self.controller:
            if name=='retry':self.controller.retry()
            else:self.controller.action(name)

    def _tick(self):
        self._main();self.controller.tick()
        if not self.controller.closed:self.root.after(100,self._tick)

    def _poll(self):
        self._main()
        if not self.controller.closed:
            self.controller.poll_status()
            self.root.after(1000,self._poll)

    def render(self,state):
        self._main()
        def configure(widget,option,value):
            key=(widget,option)
            if key in self._rendered_options and self._rendered_options[key]==value:return
            # A configure call can change its option before raising. Leave
            # that entry unknown until success, so either value can be retried.
            self._rendered_options.pop(key,None)
            widget.configure(**{option:value})
            self._rendered_options[key]=value
        for name,widget in self.labels.items():configure(widget,'text',state[name])
        for name,widget in self.buttons.items():configure(widget,'state','normal' if state['buttons'][name] else 'disabled')
        configure(self.footnote,'text','Window cleanup is unconfirmed.' if state['cleanup_unconfirmed'] else
            self._normal_footer)

    def destroy(self):
        self._main();self.root.destroy()
