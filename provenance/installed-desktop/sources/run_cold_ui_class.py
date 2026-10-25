# SPDX-License-Identifier: Apache-2.0
class ColdUIQualification:
    event=prior.Qualification.event
    until=prior.Qualification.until
    remaining=prior.Qualification.remaining
    checkpoint=prior.Qualification.checkpoint
    status=prior.Qualification.status
    submit=prior.Qualification.submit
    ack=prior.Qualification.ack

    def __init__(self,args):
        self.args=args;self.args.fixture=False;self.root=args.run.resolve()
        self.handles=[];self.logs=[];self.waits={};self.host=self.job=self.worker=None
        self.gui=self.facade=self.runtime=self.transport=self.listener=self.stop_binding=None
        self.deadline=self.original=self.initial_events=None;self.stop_id='service-stop-'+uuid.uuid4().hex
        self.result={'qualification_case_passed':False,'case_checks_and_cleanup_passed':False,
            'asyncio_teardown_completed':False,'case':'cold-gui-installed-worker-stop','fixture':False,
            'task_completed':False,'live_M2_milestone_claimed':False,'provider_calls':None,
            'dispatched_file_effects':None,'model':MODEL,'quality':deepcopy(QUALITY)}

    def launch(self,command,label):
        before=len(self.handles)
        try:return prior.Qualification.launch(self,command,label)
        finally:
            # The original helper retains Popen before its diagnostic write.
            # Keep the worker reference even if that write raises afterward.
            if label=='worker' and len(self.handles)==before+1:self.worker=self.handles[-1]

    def bind_worker_stop(self):
        if self.stop_binding is None:
            self.worker_cap=object()
            self.stop_binding=WorkerStopBinding(self.worker,self.work,self.box,requester_capability=self.capability,
                capability=self.worker_cap,stop_request_id=self.stop_id,original=self.original,
                deadline_monotonic=self.deadline,model=MODEL,quality=QUALITY,fence=self.fence)

    async def join_child(self,child):
        if child not in self.handles:raise RuntimeError('Cannot adopt a child for cleanup')
        task=self.waits.get(child.pid)
        if task is None:
            task=self.waits[child.pid]=asyncio.create_task(asyncio.to_thread(child.wait))
        code=await asyncio.shield(task)
        self.event('retained_process_exit',pid=child.pid,exit_code=code,terminated=False)
        return code

    def fence(self):
        if self.facade is not None:self.facade.fence_admission()
        elif self.host is not None:
            self.host.closing=True;self.host.gateway.scheduler.closing=True

    def paused_ack(self):
        snapshot=self.box.snapshot();ack=snapshot.status(INITIAL_PAUSE);cp=snapshot.target
        if ack['outcome']!='applied' or ack['owner_acknowledged'] is not True:return None
        if type(cp.owner_epoch) is not str or len(cp.owner_epoch)!=32:return None
        if self.worker.poll() is not None:raise RuntimeError('Worker exited before paused ownership proof')
        no_work(cp,self.original,self.deadline,self.host,self.work)
        if snapshot.demand is None or snapshot.demand['state']!='paused':raise RuntimeError('No durable paused demand')
        return {'ack':ack,'checkpoint':asdict(cp),'worker_pid':self.worker.pid}

    def bind_gui(self,binding,verifier,bootstrap):
        self.facade.bind_window(binding,verifier,bootstrap)
        self.transport.bind_session(self.transport_cap,binding.session_id,bootstrap.token)
        return True

    async def prepare(self):
        if (Path(sys.executable).resolve()!=BASE_PYTHON.resolve() or sha(BASE_PYTHON)!=BASE_SHA
                or self.args.gui_python.resolve()!=BASE_PYTHON.resolve()
                or sha(self.args.owner_config)!=PACKAGE_SHA):
            raise RuntimeError('Pinned host/GUI interpreter or native package configuration changed')
        self.job=module('_cold_ui_containing_job',HERE/'native/owner_source/owned_job.py')
        self.job.contain_current_process()
        self.work=self.root/'hermes-task'
        child=self.launch([str(self.args.hermes_python),'-I','-B',str(HERE/'hermes/run_recovery.py'),
            'prepare','--run',str(self.work),'--hermes-source',str(self.args.hermes_source),
            '--canonical',str(HERE),'--python',str(self.args.hermes_python),'--control-case','complete'],'prepare')
        await self.until(lambda:child.poll() is not None,timeout=60)
        if await self.join_child(child)!=0:raise RuntimeError('Fresh paused-task preparation failed')
        self.plan=read(self.work/'plan.json');self.store=TaskStore(self.work/'task.sqlite3')
        self.identity=DemandIdentity(**self.plan['demand_identity'])
        self.registry=DemandRegistry((Registration(self.store,self.identity),))
        self.capability=object();self.box=Mailbox(self.registry,self.identity.registration_id,requester_capability=self.capability)
        self.original=self.checkpoint();rec.save(self.root/'original-checkpoint.private.json',asdict(self.original))
        self.submit(INITIAL_PAUSE,'pause')
        self.host_epoch='cold-ui-'+uuid.uuid4().hex;self.intent_cap=object()
        self.gate=UIIntentGate(host_epoch=self.host_epoch,capability=self.intent_cap,
            verify_current=lambda binding:None if self.facade is None else self.facade.verify_current(binding))
        self.progress=None
        if getattr(self.args,'cooperative_foreground_policy',False):
            from ui_progress import CooperativeProgress,POLICY_ID
            self.progress=CooperativeProgress(self.gate,self.intent_cap)
            self.result['foreground_policy_id']=POLICY_ID
        else:
            self.result['foreground_policy_id']='strict-foreground.v3'
        owner=read(self.args.owner_config);owner.pop('max_runtime_seconds',None)
        self.result['owner_config_sha256']=PACKAGE_SHA
        self.reader=module('_cold_ui_activity',HERE/'foreground/activity.py').WindowsActivityReader()
        adapter=ColdStartAdapter(**owner,job=self.job,max_runtime_seconds=None)
        config=Config(backend_kind='strata',backend_url='http://127.0.0.1:18098/v1',
            default_class='normal',queue_timeout_s=600,upstream_timeout_s=600,upstream_read_timeout_s=600,
            backend_revision='qualified-IQ3_S-native-744205e4')
        self.host=ControlledDesktopHost(owner,config,self.root/'host',ForegroundPolicy(
            ui_intent=self.gate,cooperative_progress=self.progress),
            demand=self.registry,restore_requirements=ToolRequirements(3,3,250),adapter=adapter,
            reader=self.reader,job=self.job,max_runtime_seconds=None,idle_grace_s=30,runtime_timing=True)
        await self.host.start(timeout_s=30)
        self.initial_events=deepcopy(list(self.host.controller.events))
        prior.complete_ledger(self.host.controller.events,self.initial_events)
        if adapter.launch_intent is not None or adapter.started_owner or self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Cold host unexpectedly loaded before paused owner bootstrap')
        self.deadline=time.monotonic()+900;self.result['deadline_monotonic']=self.deadline
        self.worker=self.launch([self.plan['base_python'],'-I','-B',str(HERE/'hermes/run_recovery.py'),
            'worker','--run',str(self.work),'--controller-ready',str(self.work/'controller-ready-never-written.json'),
            '--gateway-instance',self.host.gateway.instance,'--deadline-monotonic',str(self.deadline),
            '--stop-request-id',self.stop_id],'worker')
        self.bind_worker_stop()
        self.launch_api=WindowsLaunchAPI()
        handle=self.launch_api.handle(self.worker)
        self.worker_identity=self.launch_api.identity(handle)
        if (self.launch_api.in_job(handle,self.job._HANDLE) is not True
                or self.worker_identity[0]!=self.worker.pid or self.worker.poll() is not None):
            raise RuntimeError('Retained installed worker is not live in this exact containing job')
        self.result['retained_worker_identity']={'pid':self.worker_identity[0],
            'creation_time_100ns':self.worker_identity[1],'containing_job_verified':True}
        paused=await self.until(self.paused_ack,self.worker,timeout=60)
        self.result['initial_paused_owner']=paused
        rec.save(self.root/'paused-before-gui.private.json',paused)
        self.gui=OwnedUILaunch(api=self.launch_api)
        prepared=PreparedTask(self.host_epoch,self.identity.task_id,PROMPT)
        self.facade=DesktopControlLifecycle(self.host,prepared,worker_stop=self.stop_binding,
            worker_capability=self.worker_cap,gui=self.gui,shutdown_timeout_s=120)
        self.runtime=MailboxRuntime(prepared,self.box,requester_capability=self.capability,
            gate=self.gate,intent_capability=self.intent_cap,lifecycle=self.facade)
        await self.runtime.refresh();self.host.attach_control_runtime(self.runtime)
        self.transport_cap=object()
        self.transport=ControlTransport(prepared,self.runtime,capability=self.transport_cap,
            runner_credential='local-no-key',cooperative_progress=self.progress)
        self.listener=SerialListener(self.transport);endpoint=self.listener.start()
        bootstrap=Bootstrap(self.host_epoch,'session-'+uuid.uuid4().hex,self.identity.task_id,PROMPT,
            credential(),endpoint[0],endpoint[1],'AdaptiveInference.'+uuid.uuid4().hex,secrets.randbelow(2**31-1)+1)
        spec=LaunchSpec(BASE_PYTHON,BASE_SHA,HERE/'run_gui.py',
            tuple((name,sha(HERE/name)) for name in sorted(CHILD_SOURCES)))
        await self.gui.start(spec,bootstrap,containing_job=self.job._HANDLE,
            launch_ready=lambda:self.host.started_at is not None and not self.host.closing
                and self.host.adapter.launch_intent is None and self.paused_ack() is not None,
            bind_session=self.bind_gui,revoke_session=self.facade.window_closed,timeout_s=10)
        await self.until(lambda:self.transport._ready,self.worker,timeout=30)
        no_work(self.checkpoint(),self.original,self.deadline,self.host,self.work)
        ready={'ready':True,'case':self.result['case'],'gui_pid':self.gui.process.pid,'gui_title':TITLE,
            'worker_pid':self.worker.pid,'task_id':self.identity.task_id,'paused_owner_acknowledged':True,
            'source':self.result['source'],'no_resume_requested':True,'model_started':False,
            'instructions':'Use ordinary Pause, observe its acknowledgement, then Stop. Do not Resume.'}
        rec.save(self.root/'ready.private.json',ready)
        self.result['real_window_bound']=True;self.result['runtime_class_binding_verified']=True
        self.result['gui_diagnostic']={'pid':self.gui.process.pid,'title':TITLE}
        self.result['retained_gui_binding']=asdict(self.gui.binding)

    async def interact(self):
        self.gui_pause_seen=[]
        while not self.transport.lifecycle()['stop_requested']:
            self.remaining()
            no_work(self.checkpoint(),self.original,self.deadline,self.host,self.work)
            observed=gui_controls(self.transport,self.box,self.stop_id)
            if observed:self.gui_pause_seen=observed
            if self.worker.poll() is not None:raise RuntimeError('Worker exited before manual Stop')
            if self.gui.process.poll() is not None:raise RuntimeError('GUI exited without explicit manual Stop')
            status={'phase':'ready_for_manual_pause_and_stop','gui_pid':self.gui.process.pid,'gui_title':TITLE,
                'worker_pid':self.worker.pid,'gui_pause_acknowledged':bool(self.gui_pause_seen),
                'no_resume':True,'native_launch_intent':None,'provider_calls':0,
                'runtime':self.runtime.status(),'transport':self.transport.lifecycle()}
            rec.save(self.root/'status.private.json',status)
            await asyncio.sleep(.1)
        self.result['manual_stop_observed']=True
        gui_controls(self.transport,self.box,self.stop_id)
        if not self.gui_pause_seen:raise RuntimeError('Manual Stop lacks an independently observed GUI Pause ACK')
        self.result['gui_pause_observed_before_stop']=True
        self.result['gui_pause_acknowledgements']=deepcopy(self.gui_pause_seen)
        await asyncio.shield(self.transport._stop_task)
        if not self.transport.lifecycle()['stop_confirmed']:raise RuntimeError('Manual Stop is not confirmed')
        self.result['lifecycle']=await self.facade.cooperative_stop()
        if self.result['lifecycle']!={'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None}:
            raise RuntimeError('Cooperative Stop lacks exact verified closure')

    def obligations(self):
        tasks=[]
        if self.facade is not None:tasks += [self.facade._wake,self.facade._stop,*self.facade._joins]
        if self.runtime is not None:tasks += [self.runtime._stop_task,*tuple(self.runtime._pending)]
        if self.stop_binding is not None:tasks += [self.stop_binding._work]
        if self.gui is not None:tasks += [self.gui._start_task,*self.gui._io]
        if self.listener is not None:
            tasks += [self.listener._driver,self.listener._close_task]
            if self.listener._record is not None:
                tasks += [self.listener._record.get(key) for key in ('setup','handler','cleanup')]
        if self.transport is not None:
            tasks += [self.transport._stop_task,self.transport._close_task,*tuple(self.transport._handlers)]
            tasks += [row.get('task') for row in self.transport._records.values()]
            tasks += [row.get('cleanup') for row in self.transport._connections.values()]
        return tasks

    def control_io_released(self):
        listener_ok=(self.listener is None or self.listener.lifecycle()['resources_closed'] is True)
        transport_ok=(self.transport is None or not self.transport._handlers and not self.transport._connections
            and self.transport._close_task is not None and self.transport._close_task.done()
            and not self.transport._close_task.cancelled())
        return listener_ok and transport_ok

    async def join_gui_resources(self):
        if self.gui is None:return
        if self.gui._start_task is not None and not self.gui._bound:self.gui.abort_startup()
        while True:
            receipt=await self.gui.join(timeout_s=2)
            if (receipt['pending_pipe_operations']==0 and receipt['pipe_handles_closed']
                    and receipt['process_handle_closed'] and receipt['verifier_handle_closed']
                    and (not receipt['child_retained'] or receipt['child_exit_observed'])):
                self.result['gui_cleanup']=receipt
                return
            await asyncio.sleep(.05)

    async def dispose_control_io(self):
        if self.listener is not None:
            while True:
                value=await self.listener.aclose(timeout=2)
                if value['resources_closed']:break
                await asyncio.sleep(.05)
            self.result['listener_cleanup']=value
        if self.transport is not None:
            while True:
                value=await self.transport.aclose(timeout=2)
                if (value['handlers']==0 and value['pending_connections']==0
                        and self.transport._close_task.done()):break
                await asyncio.sleep(.05)
            self.result['transport_cleanup']=value

    async def dispose(self,failed):
        """Cooperative cleanup only. Live/unknown obligations stay retained."""
        self.fence()
        if self.worker is not None and self.stop_binding is None:self.bind_worker_stop()
        if self.transport is not None:
            self.transport._request_stop()  # Trusted failure cleanup; no network command or auto Resume.
            await asyncio.shield(self.transport._stop_task)
        elif self.stop_binding is not None:
            self.stop_binding.request_stop(self.worker_cap)
            while self.worker.poll() is None:await self.stop_binding.join(timeout=2)
        # Failed startup closes only its owned input when safe. A started GUI
        # sees stop_requested through the still-live listener and exits.
        await self.join_gui_resources()
        for child in self.handles:await self.join_child(child)
        # The listener must remain usable for the GUI's final close reply, but
        # its live accept driver cannot be joined until acceptance is fenced.
        if self.listener is not None:self.listener.close()
        errors=await join_retained(self.obligations())
        self.result['retained_obligations_joined']=True
        if any(isinstance(value,BaseException) for value in errors):
            self.result['joined_obligation_errors']=[diagnostic(value) for value in errors if isinstance(value,BaseException)]
        if self.host is not None:
            # Even a failed trial may safely clean native resources once every
            # actual retained child and pipe/handle obligation is positively joined.
            self.result['cleanup']=await self.host.close(timeout_s=180)
        await self.dispose_control_io()
        self.result['all_retained_process_exits']=[{'pid':child.pid,'exit_code':child.poll()} for child in self.handles]

    def validate_terminal(self):
        cp=self.checkpoint();no_work(cp,self.original,self.deadline,self.host,self.work)
        if cp.owner_epoch is not None:raise RuntimeError('Worker did not release actual task ownership')
        if self.worker.poll()!=STOP_EXIT:raise RuntimeError('Installed worker did not exit via cooperative Stop')
        if self.stop_binding._verify_exit(STOP_EXIT)!='service_stopped':
            raise RuntimeError('Final worker receipt no longer matches its durable checkpoint')
        observed=gui_controls(self.transport,self.box,self.stop_id)
        snapshot=self.box.snapshot()
        expected={INITIAL_PAUSE,self.stop_id,*[row['request_id'] for row in observed]}
        if (not observed or set(row['request_id'] for row in snapshot.requests)!=expected
                or any(snapshot.status(row['request_id'])['outcome']!='applied' or
                       snapshot.status(row['request_id'])['owner_acknowledged'] is not True
                       for row in snapshot.requests)):
            raise RuntimeError('Complete cold-control request/ACK ledger differs')
        worker=read(self.work/f'result-{self.worker.pid}.json')
        if (worker.get('provider_calls')!=0 or worker.get('service_stopped') is not True
                or worker.get('passed') is not False or worker.get('completed') is not False):
            raise RuntimeError('Worker Stop result contains unverified work/completion')
        if self.result.get('joined_obligation_errors'):raise RuntimeError('Retained obligation failed')
        if (self.result.get('retained_obligations_joined') is not True
                or self.result.get('gui_cleanup',{}).get('closed') is not True
                or self.result.get('gui_cleanup',{}).get('faults')!=[]):
            raise RuntimeError('Final child/pipe obligations are not cleanly joined')
        if not self.result.get('listener_cleanup',{}).get('clean_close') or not self.result.get('transport_cleanup',{}).get('closed'):
            raise RuntimeError('Control transport/listener did not close cleanly')
        if self.job.active_process_ids()!={os.getpid()}:raise RuntimeError('Actual containing job still has children')
        scheduler=self.host.gateway.scheduler
        if not scheduler.closing or self.host.controller.fault or not self.host.closed:
            raise RuntimeError('Terminal host/scheduler closure differs')
        cleanup=self.result['cleanup']
        if cleanup.get('closed') is not True or any(cleanup.get(k) is not None for k in ('primary_error','cleanup_error','controller_fault')):
            raise RuntimeError('Native cold cleanup has a fault')
        events=prior.complete_ledger(self.host.controller.events,self.initial_events)
        if any(row.get('restore_requested') is True for row in events):raise RuntimeError('Unexpected native restoration')
        self.result.update(provider_calls=0,dispatched_file_effects=0,native_launch_intent=None,
            handoff_events=events,full_handoff_ledger=True,task_status='pending',demand_state='paused',
            owner_released=True,worker_exit_code=STOP_EXIT,task_completed=False,no_resume=True,
            actual_job_members_after_cleanup=[os.getpid()],native_cold_cleanup=deepcopy(cleanup),
            worker_stop_receipt=deepcopy(worker['service_stop']))
        self.result['controls']=[snapshot.status(row['request_id']) for row in snapshot.requests]
        rec.save(self.root/'terminal-checkpoint.private.json',asdict(cp))
        if verify_closure()!=self.result['source']:raise RuntimeError('Runtime source changed during trial')

    async def run(self):
        if self.root.is_relative_to(HERE):raise ValueError('Fresh evidence must be outside frozen source')
        self.root.mkdir(exist_ok=False);self.result['source']=verify_closure()
        try:
            await self.prepare();await self.interact()
        except BaseException as error:
            self.result['primary_error']=diagnostic(error)
        try:
            await self.dispose('primary_error' in self.result)
            if 'primary_error' not in self.result:self.validate_terminal()
        except BaseException as error:
            self.result['cleanup_error']=diagnostic(error)
            # Do not tear down an event loop while retained children/tasks still
            # own operations. The no-I/O external guard bounds this failure.
            try:rec.save(self.root/'unresolved.private.json',self.result)
            except BaseException as failure:self.result['diagnostic_write_error']=diagnostic(failure)
            try:
                # The GUI is separate from the legacy helper's worker list.
                # Never drop that actual child on an exceptional cleanup path.
                await self.join_gui_resources()
                if self.listener is not None:self.listener.close()
                await join_retained(self.obligations())
                for child in self.handles:await self.join_child(child)
                try:
                    if self.host is not None:self.result['failure_cleanup']=await self.host.close(timeout_s=180)
                    await self.dispose_control_io()
                except BaseException as failure:
                    self.result['failure_cleanup_error']=diagnostic(failure)
                    if not self.control_io_released():
                        raise RuntimeError('Control listener/handler/stream ownership remains unresolved') from failure
                if self.job is not None:
                    while True:
                        try:
                            if self.job.active_process_ids()=={os.getpid()}:break
                        except BaseException as failure:
                            self.result.setdefault('job_observation_error',diagnostic(failure))
                        await asyncio.sleep(1)
            except BaseException as failure:
                self.result['retention_error']=diagnostic(failure)
                try:rec.save(self.root/'retention-failure.private.json',self.result)
                except BaseException:pass
                # No normal process exit while the exact child/task obligation
                # is unknown. The no-I/O external guard classifies exit124.
                while True:
                    try:
                        await asyncio.sleep(1)
                    except asyncio.CancelledError:continue
        if getattr(self,'progress',None) is not None:
            try:self.result['cooperative_foreground_final']=self.progress.snapshot()
            except Exception as error:self.result['cooperative_diagnostic_error']=diagnostic(error)
        self.result['case_checks_and_cleanup_passed']=not any(k in self.result for k in ('primary_error','cleanup_error'))
        for stream in self.logs:stream.close()
        rec.save(self.root/'result.private.json',self.result)
        return self.result

