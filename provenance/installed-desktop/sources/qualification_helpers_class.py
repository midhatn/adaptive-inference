# SPDX-License-Identifier: Apache-2.0
class Qualification:
    def __init__(self,args):
        self.args=args;self.root=args.run.resolve();self.handles=[];self.logs=[];self.host=None
        self.job=None;self.driver=None;self.deadline=None;self.original=None;self.initial_events=None
        self.runtime_bindings=[];self.cold_timing_verified=False
        self.result={'case':args.case,'fixture':args.fixture,'qualification_case_passed':False,
                     'task_completed':False,'model':MODEL,'quality':QUALITY,
                     'live_M2_milestone_claimed':False,'timing_learning_qualified':False}

    def activate_verified_runtime(self,identity):
        gateway,controller=self.host.gateway,self.host.controller
        if (gateway.scheduler.capacity is not controller or gateway.capacity is not controller
                or controller.identity!=identity or gateway._runtime_loop is not asyncio.get_running_loop()
                or controller() or gateway.scheduler.active is not None or gateway.scheduler.uncertain
                or gateway.scheduler.closing or len(self.runtime_bindings)>=255):
            raise RuntimeError('Verified runtime binding context refused')
        previous=gateway._runtime_context
        gateway.activate_runtime(identity)
        current=gateway._runtime_context
        self.runtime_bindings.append({'at_monotonic':time.monotonic(),'owner_id':identity['owner_id'],
            'generation':current.generation,'previous_generation':previous.generation if previous else None,
            'gateway_startup_completed':True,'admission_closed':True,'controller_identity_verified':True})

    def verify_runtime_bindings(self):
        gateway,controller=self.host.gateway,self.host.controller
        if (gateway.runtime_timing is not True or gateway.scheduler.capacity is not controller
                or gateway.capacity is not controller or gateway._runtime_error is not None):
            raise RuntimeError('Runtime timing integration unavailable')
        starts=sum(row.get('restore_requested') is True for row in controller.events)
        if len(self.runtime_bindings)!=starts:
            raise RuntimeError('Runtime generations do not cover exact successful owner transitions')
        generation=0;last_owner=None
        for row in self.runtime_bindings:
            expected=generation if row['owner_id']==last_owner else generation+1
            if (row['generation']!=expected or row['previous_generation']!=(generation or None)
                    or not all(row[key] is True for key in
                        ('gateway_startup_completed','admission_closed','controller_identity_verified'))):
                raise RuntimeError('Runtime generation identity sequence refused')
            generation,last_owner=expected,row['owner_id']
        context=gateway._runtime_context
        if (context is None)!=(generation==0) or context is not None and context.generation!=generation:
            raise RuntimeError('Final runtime generation differs from verified owner ledger')
        if self.args.case=='cancel' and generation:
            raise RuntimeError('Cancelled bootstrap unexpectedly activated runtime')
        if self.result.get('task_case_checks_passed') and self.args.case=='complete' and not generation:
            raise RuntimeError('Completed case lacks verified runtime activation')
        history=deepcopy(list(gateway.history))
        if len(history)>=gateway.history.maxlen:
            raise RuntimeError('Runtime request history full; completeness not established')
        for row in history:
            actual,predicted=row['execution_runtime_generation'],row['prediction_runtime_generation']
            if (type(actual) is not int or not 1<=actual<=generation
                    or predicted is not None and (type(predicted) is not int or not 1<=predicted<=actual)
                    or row['prediction_matches_execution_runtime'] is not (actual==predicted)):
                raise RuntimeError('Request runtime generation labels refused')
        if not self.args.fixture and len(history)!=self.result.get('provider_calls'):
            raise RuntimeError('Native provider calls lack complete runtime request evidence')
        return {'enabled':True,'generation':generation or None,'verified_owner_bindings':deepcopy(self.runtime_bindings),
                'request_history':history,'request_path':'fixture_provider' if self.args.fixture else 'actual_gateway',
                'cold_start_had_no_context':self.cold_timing_verified,'performance_claimed':False}

    def event(self,kind,**fields):
        value={'kind':kind,'at_monotonic':time.monotonic(),**fields}
        with (self.root/'events.private.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,allow_nan=False)+'\n');stream.flush()

    def launch(self,command,label):
        stream=(self.root/(label+'.log')).open('wb');self.logs.append(stream)
        child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
            cwd=self.root,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.handles.append(child)
        if self.args.fixture:self.job.children.add(child.pid)
        self.event('worker_launched',label=label,pid=child.pid)
        return child

    async def joined(self,child,*,kill=False,timeout=10):
        if kill and child.poll() is None:child.kill()
        code=await asyncio.to_thread(child.wait,timeout)
        if self.args.fixture:self.job.children.discard(child.pid)
        self.event('retained_process_exit',pid=child.pid,exit_code=code,terminated=kill)
        return code

    async def until(self,predicate,child=None,timeout=240):
        limit=min(time.monotonic()+timeout,self.deadline or float('inf'))
        while True:
            value=predicate()
            if value:return value
            if child is not None and child.poll() is not None:
                raise RuntimeError('Owned worker exited before required boundary; see retained log')
            if time.monotonic()>=limit:raise TimeoutError('Qualification boundary deadline')
            if self.host and self.host.controller.fault:raise RuntimeError('Controller fault: '+str(self.host.controller.fault))
            await asyncio.sleep(.05)

    def remaining(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Original900second task deadline exhausted')
        return remaining

    def worker(self,number):
        ready=self.work/f'controller-ready-{number}.json'
        if ready.exists():raise RuntimeError('Worker readiness receipt must be fresh')
        child=self.launch([self.plan['base_python'],'-I','-B',str(HERE/'hermes/run_recovery.py'),
            'worker','--run',str(self.work),'--controller-ready',str(ready),
            '--gateway-instance',self.host.gateway.instance,
            '--deadline-monotonic',str(self.deadline)],'worker-'+str(number))
        return child,ready

    def status(self,request_id):return self.box.status(request_id)
    def submit(self,request_id,command):
        receipt=self.box.submit(self.capability,request_id,command)
        self.event('control_recorded',**receipt);return receipt

    async def ack(self,request_id,child):
        receipt=await self.until(lambda:self.status(request_id) if self.status(request_id)['owner_acknowledged'] else None,child)
        if receipt['outcome']!='applied':raise RuntimeError('Required user control was rejected')
        self.event('control_acknowledged',**receipt)
        return receipt

    def checkpoint(self):return self.store.load(self.identity.task_id)

    def assert_original(self,cp):
        if (cp.prompt!=self.original.prompt or cp.metadata!=self.original.metadata
                or cp.state['messages'][0]!=self.original.state['messages'][0]
                or cp.state.get('deadline_monotonic')!=self.deadline):
            raise RuntimeError('Original identity, objective or deadline changed')

    def safe_report(self,*,pid=None):
        cp=self.checkpoint();self.assert_original(cp)
        if (cp.state['status']!='pending' or cp.state['phase']!='ready'
                or cp.operation is not None or cp.requires_reconciliation):
            raise RuntimeError('Task is not at the verified native safe boundary')
        marker=read(self.work/'pause.json')
        if (marker['boundary']!='safe_after_write' or (pid is not None and marker['pid']!=pid)
                or marker['history_sha256']!=rec.digest(cp.state['native_history'])):
            raise RuntimeError('Native safe-point receipt differs from checkpoint')
        rec.verify_tool_rows(cp.state['native_history'],cp.state['tools'])
        rec.verify_artifacts(cp.state,self.work/'work')
        if read(self.work/'work/report.json')!=REPORT:raise RuntimeError('Original report acceptance failed')
        effect_bytes=(self.work/'effect-receipts.jsonl').read_bytes()
        effects=[json.loads(row) for row in effect_bytes.splitlines() if row.strip()]
        report_hash=sha(self.work/'work/report.json')
        if len(effects)!=1 or effects[0]['name']!='write_file' or effects[0]['artifact_sha256']!=report_hash:
            raise RuntimeError('Expected exactly one independently verified dispatched write')
        wires=read(self.work/'wire-observations.json')
        if any(not row.get('finished_at') for row in wires):raise RuntimeError('Provider outcome still uncertain')
        return cp,report_hash,effect_bytes,wires

    async def ready(self,child,path):
        await self.until(lambda:(self.work/f'bootstrap-{child.pid}.json').exists(),child)
        boot=read(self.work/f'bootstrap-{child.pid}.json');cp=self.checkpoint()
        self.assert_original(cp)
        if (boot['pid']!=child.pid or boot['task_id']!=self.identity.task_id
                or boot['registration_id']!=self.identity.registration_id
                or boot['deadline_monotonic']!=self.deadline or boot['owner_epoch']!=cp.owner_epoch):
            raise RuntimeError('Bootstrap receipt is not the retained owner')
        if not self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Readiness waiting lacks actual trusted durable demand')
        self.event('demand_before_readiness',pid=child.pid,revision=cp.revision)
        await self.host.wait_ready(timeout_s=min(240,self.remaining()))
        rec.save(path,{'ready':True,'model':MODEL,'quality':QUALITY,'gateway':self.plan['gateway'],
            'gateway_instance':self.host.gateway.instance,'observed_at':time.time()})
        self.event('controller_ready',pid=child.pid,owner_id=self.host.controller.identity['owner_id'])

    async def complete_case(self):
        self.submit('pause-before-bootstrap','pause')
        first,ready=self.worker(1)
        await self.ack('pause-before-bootstrap',first)
        cp=self.checkpoint();self.assert_original(cp)
        if (self.host.adapter.launch_intent is not None or cp.operation is not None
                or cp.state['requests']!=0 or cp.state['attempts']!=0):
            raise RuntimeError('Prequeued pause admitted initial work')
        self.submit('resume-before-bootstrap','resume');await self.ack('resume-before-bootstrap',first)
        await self.ready(first,ready)
        await self.until(lambda:(self.work/'pause.json').exists(),first,timeout=self.remaining())
        self.safe_report(pid=first.pid)
        recorded=self.submit('pause-after-safe','pause')
        await self.ack('pause-after-safe',first)
        before,report_hash,effects,wires=self.safe_report(pid=first.pid)
        rec.save(self.root/'paused-checkpoint.private.json',asdict(before))
        rec.save(self.root/'paused-wire.private.json',wires)
        self.event('paused_safe_interval_begin',revision=before.revision,provider_calls=len(wires),
            report_sha256=report_hash,history_sha256=rec.digest(before.state['native_history']))
        await asyncio.sleep(1)
        after,after_hash,after_effects,after_wires=self.safe_report(pid=first.pid)
        if (after!=before or after_hash!=report_hash or after_effects!=effects or after_wires!=wires
                or self.host.gateway.scheduler.active is not None or self.host.gateway.scheduler.pending
                or self.host.gateway.scheduler.uncertain):
            raise RuntimeError('New or uncertain work appeared after pause acknowledgement')
        self.event('paused_safe_interval_end',revision=after.revision)
        await self.joined(first,kill=True)
        second,ready2=self.worker(2)
        await self.until(lambda:self.checkpoint().owner_epoch not in (None,before.owner_epoch),second)
        claimed=self.checkpoint();self.assert_original(claimed)
        if (claimed.state[NAMESPACE]['state']!='paused' or claimed.operation is not None
                or claimed.requires_reconciliation or claimed.state['attempts']!=before.state['attempts']
                or claimed.state['native_history']!=before.state['native_history']):
            raise RuntimeError('Replacement lost paused safe progress')
        rec.save(self.root/'replacement-checkpoint.private.json',asdict(claimed))
        self.submit('resume-after-safe','resume');await self.ack('resume-after-safe',second)
        await self.ready(second,ready2)
        await self.until(lambda:second.poll() is not None,timeout=self.remaining())
        if await self.joined(second)!=0:raise RuntimeError('Replacement Hermes failed original task')
        final=read(self.work/f'result-{second.pid}.json');cp=self.checkpoint();self.assert_original(cp)
        if (any(final.get(key) is not True for key in ('passed','completed','resumed'))
                or final.get('fixture') is not self.args.fixture or final.get('model')!=MODEL
                or final.get('quality')!=QUALITY or final.get('context')!=CONTEXT
                or final.get('sdk_revision')!=self.plan['sdk_revision'] or final.get('report')!=REPORT
                or final.get('artifacts')!={'report.json':report_hash}
                or final.get('original_prompt_sha256')!=rec.digest(self.original.prompt)):
            raise RuntimeError('Original M1 report/SDK/quality/context acceptance failed')
        if (cp.state['status']!='accepted' or cp.state['phase']!='accepted' or cp.operation is not None
                or cp.requires_reconciliation or cp.state['native_history'][:len(before.state['native_history'])]!=before.state['native_history']
                or cp.state['requests']-before.state['requests']!=final['provider_calls']
                or (self.work/'effect-receipts.jsonl').read_bytes()!=effects
                or sha(self.work/'work/report.json')!=report_hash):
            raise RuntimeError('Task progress or single-write proof changed during replacement')
        final_wires=read(self.work/'wire-observations.json')
        if (final_wires[:len(wires)]!=wires or len(final_wires)-len(wires)!=final['provider_calls']
                or any(row.get('model')!=MODEL or row.get('quality')!=QUALITY or row.get('class')!='normal'
                       or not row.get('finished_at') for row in final_wires)):
            raise RuntimeError('Exact wire quality or lineage was not retained')
        if self.registry.observe(self.identity.registration_id).eligible:
            raise RuntimeError('Accepted task remains eligible for new demand')
        self.result.update(task_completed=True,report=REPORT,report_sha256=report_hash,
            dispatched_file_effects=1,effect_receipts_sha256=hashlib.sha256(effects).hexdigest(),
            provider_calls=len(final_wires),retained_prompt_sha256=rec.digest(cp.prompt),
            native_history_sha256=rec.digest(cp.state['native_history']),
            task_status=cp.state['status'],demand_state=cp.state[NAMESPACE]['state'])

    async def cancel_case(self):
        self.submit('cancel-before-bootstrap','cancel')
        original_epoch=None
        for number in (1,2):
            child,_=self.worker(number)
            await self.until(lambda:child.poll() is not None,timeout=min(60,self.remaining()))
            if await self.joined(child)!=3:raise RuntimeError('Expected durable controlled cancellation')
            result=read(self.work/f'result-{child.pid}.json');cp=self.checkpoint();self.assert_original(cp)
            if not result.get('owner_epoch') or result['owner_epoch']==original_epoch:
                raise RuntimeError('Cancellation replacement did not claim a distinct durable owner')
            original_epoch=result['owner_epoch']
            if (result.get('passed') is not False or result.get('controlled') is not True
                    or result.get('control_state')!='cancelled' or result.get('provider_calls')!=0
                    or cp.state['status']!='pending' or cp.state[NAMESPACE]['state']!='cancelled'
                    or cp.operation is not None or cp.requires_reconciliation
                    or cp.state['requests'] or cp.state['attempts'] or cp.state['admission_attempts']
                    or cp.state['tools'] or self.host.adapter.launch_intent is not None
                    or self.host.adapter.started_owner or self.host.gateway.scheduler.active is not None
                    or self.host.gateway.scheduler.pending or self.host.gateway.scheduler.uncertain):
                raise RuntimeError('Cancelled task admitted work or lost cancellation')
            for filename in ('effect-receipts.jsonl','wire-observations.json','work/report.json'):
                path=self.work/filename
                if path.exists() and path.read_bytes().strip() not in (b'',b'[]'):
                    raise RuntimeError('Unexpected work artifact for cancelled task')
            self.event('cancelled_owner_exit',pid=child.pid,revision=cp.revision,provider_calls=0)
            rec.save(self.root/f'cancelled-checkpoint-{number}.private.json',asdict(cp))
        if self.status('cancel-before-bootstrap')['outcome']!='applied':raise RuntimeError('Cancellation lacks owner ACK')
        self.result.update(task_completed=False,task_status='pending',demand_state='cancelled',
            provider_calls=0,dispatched_file_effects=0,native_launch_intent=None)

    async def run(self):
        if self.root.is_relative_to(HERE):raise ValueError('Run output must be outside immutable source closure')
        self.root.mkdir(parents=False,exist_ok=False)
        self.result['source']=verify_closure()
        try:
            if self.args.fixture:
                from test_persistent_host import Job,Reader,RichDriver
                from fixture_listener import Runner,Site
                self.job=Job();self.reader=Reader();self.driver=RichDriver()
                listener={'_runner_factory':Runner,'_site_factory':Site}
                policy=ForegroundPolicy(input_hold_s=1,recovery_s=0,engage_samples=1)
            else:
                if not self.args.owner_config:raise ValueError('Real case requires explicit owner config')
                self.job=module('_qualification_containing_job',HERE/'native/owner_source/owned_job.py')
                self.reader=module('_qualification_activity',HERE/'foreground/activity.py').WindowsActivityReader()
                listener={};policy=ForegroundPolicy()
            self.job.contain_current_process()
            self.work=self.root/'hermes-task'
            command=[str(self.args.hermes_python),'-I','-B',str(HERE/'hermes/run_recovery.py'),
                'prepare','--run',str(self.work),'--hermes-source',str(self.args.hermes_source),
                '--canonical',str(HERE),'--python',str(self.args.hermes_python),'--control-case',self.args.case]
            if self.args.fixture:command.append('--fixture')
            prepare=self.launch(command,'prepare')
            await self.until(lambda:prepare.poll() is not None,timeout=60)
            if await self.joined(prepare)!=0:raise RuntimeError('Fresh task preparation failed')
            self.plan=read(self.work/'plan.json');self.store=TaskStore(self.work/'task.sqlite3')
            self.identity=DemandIdentity(**self.plan['demand_identity'])
            self.registry=DemandRegistry((Registration(self.store,self.identity),))
            self.capability=object();self.box=Mailbox(self.registry,self.identity.registration_id,requester_capability=self.capability)
            self.original=self.checkpoint()
            rec.save(self.root/'original-checkpoint.private.json',asdict(self.original))
            owner={} if self.args.fixture else read(self.args.owner_config)
            self.result['owner_configuration']=deepcopy(owner)
            self.result['owner_config_sha256']=None if self.args.fixture else sha(self.args.owner_config)
            owner={key:value for key,value in owner.items() if key!='max_runtime_seconds'}
            adapter=ColdStartAdapter(**owner,job=self.job,max_runtime_seconds=1800,_driver=self.driver)
            config=Config(backend_kind='strata',backend_url='http://127.0.0.1:18098/v1',
                default_class='normal',queue_timeout_s=600,upstream_timeout_s=600,upstream_read_timeout_s=600,
                backend_revision='qualified-IQ3_S-native-744205e4')
            self.host=PersistentDesktopHost(owner,config,self.root/'host',policy,demand=self.registry,
                restore_requirements=ToolRequirements(3,3,250),adapter=adapter,reader=self.reader,job=self.job,
                max_runtime_seconds=1800,idle_grace_s=30,runtime_timing=True,**listener)
            self.host.controller.on_verified_owner=self.activate_verified_runtime
            await self.host.start(timeout_s=30)
            self.initial_events=deepcopy(list(self.host.controller.events))
            complete_ledger(self.host.controller.events,self.initial_events)
            rec.save(self.root/'initial-handoff-events.private.json',self.initial_events)
            await asyncio.sleep(.25)
            if (adapter.launch_intent is not None or adapter.started_owner
                    or self.registry.observe(self.identity.registration_id).eligible or self.host.controller()
                    or self.host.gateway._runtime_context is not None or self.runtime_bindings
                    or self.host.gateway._runtime_loop is not asyncio.get_running_loop()):
                raise RuntimeError('Cold host started model without eligible task demand')
            self.cold_timing_verified=True
            self.event('cold_listener_no_demand',native_launch_intent=None)
            self.deadline=time.monotonic()+900;self.result['deadline_monotonic']=self.deadline
            await (self.complete_case() if self.args.case=='complete' else self.cancel_case())
            control_ids=(('pause-before-bootstrap','resume-before-bootstrap','pause-after-safe','resume-after-safe')
                if self.args.case=='complete' else ('cancel-before-bootstrap',))
            self.result['controls']=[self.status(request_id) for request_id in control_ids]
            if any(r['outcome']!='applied' or not r['owner_acknowledged'] for r in self.result['controls']):
                raise RuntimeError('Required control did not retain owner acknowledgement')
            rec.save(self.root/'terminal-checkpoint.private.json',asdict(self.checkpoint()))
            self.result['task_case_checks_passed']=True
        except BaseException as exc:
            self.result['primary_error']=diagnostic(exc)
            try:self.event('case_failed',**self.result['primary_error'])
            except BaseException as logging:
                self.result['diagnostic_write_error']=diagnostic(logging)
        finally:
            for child in self.handles:
                try:await self.joined(child,kill=child.poll() is None)
                except BaseException as exc:
                    self.result.setdefault('worker_cleanup_errors',[]).append({'pid':child.pid,**diagnostic(exc)})
            if self.host is not None:
                try:
                    self.result['cleanup']=await self.host.close(timeout_s=180)
                    scheduler=self.host.gateway.scheduler
                    if (self.host.controller.fault or not scheduler.closing or scheduler.active is not None
                            or scheduler.pending or scheduler.uncertain or self.job.active_process_ids()!={os.getpid()}):
                        raise RuntimeError('Terminal controller/scheduler/job evidence refused')
                    if self.driver is not None:self.result['fixture_native_starts']=self.driver.starts
                except BaseException as exc:
                    self.result['cleanup_error']=diagnostic(exc)
                finally:
                    self.result['handoff_events']=deepcopy(list(self.host.controller.events))
                    try:
                        complete_ledger(self.host.controller.events,self.initial_events)
                        self.result['full_handoff_ledger']=True
                    except BaseException as exc:
                        self.result['full_handoff_ledger']=False
                        self.result['ledger_error']=diagnostic(exc)
                try:
                    self.result['runtime_binding']=self.verify_runtime_bindings()
                    self.result['runtime_binding_checks_passed']=True
                except BaseException as exc:
                    self.result['runtime_binding_checks_passed']=False
                    self.result['runtime_binding_error']=diagnostic(exc)
            self.result['case_checks_and_cleanup_passed']=bool(self.result.get('task_case_checks_passed')
                and 'primary_error' not in self.result and 'cleanup_error' not in self.result
                and not self.result.get('worker_cleanup_errors') and self.result.get('cleanup',{}).get('closed')
                and self.result.get('full_handoff_ledger') and self.result.get('runtime_binding_checks_passed'))
            try:self.result['runtime_source_unchanged']=verify_closure()==self.result['source']
            except BaseException as exc:
                self.result['runtime_source_unchanged']=False
                self.result['source_error']=diagnostic(exc)
            self.result['case_checks_and_cleanup_passed'] &= self.result['runtime_source_unchanged']
            self.result['asyncio_teardown_completed']=False
            self.result['qualification_case_passed']=False
            for stream in self.logs:stream.close()
            rec.save(self.root/'result.private.json',self.result)
        return self.result

