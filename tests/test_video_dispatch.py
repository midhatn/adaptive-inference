"""Real retained HTTP/SQLite boundaries, inert video outputs; no SDK/GPU/tool run."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from adaptive_inference.desktop.compiler_bridge import _json
from adaptive_inference.desktop.compiler_host import CompilerHost
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.compiler_client import CompilerClient, CompilerClientError
from adaptive_inference.desktop.hermes.compiler_recovery import CompilerRecovery
from adaptive_inference.desktop.hermes.compiler_worker import make_recovery, binding_schema
from adaptive_inference.desktop.hermes.compiler_evidence import verify_recipe_result
from adaptive_inference.desktop.hermes.continuation_worker import effect_receipts
from adaptive_inference.desktop.recipe_dispatch import definition, expected_tool_names, completion_kwargs
from adaptive_inference.desktop.video_profile import VideoSettings
from adaptive_inference.desktop.video_recipe import _outputs
from adaptive_inference.desktop.video_template import prepare_video_recipe, MEDIA, project_success
from adaptive_inference.task_store import ReconciliationRequired
from recovery_capability_support import definitions
import test_compiler_host as host_fixture
import test_compiler_recovery as recovery_fixture
import test_compiler_wire_boundary as wire_fixture
from test_video_task_spec import video_data
from adaptive_inference.task_spec import TaskSpec

VIDEO = definition('video')
ARGS = {'recipe_id': VIDEO.recipe_id}


def settings(*pins, environment):
    return VideoSettings(*pins[:2], environment=environment)


def inert_receipt(recipe, deadline, status='passed'):
    recipe.run.mkdir()
    stages = ('encode','probe','decode') if status == 'passed' else ('encode',)
    (recipe.run/'encode.log').write_text('inert encoder unavailable' if status == 'failed' else '')
    receipt = {'schema': 'video-recipe.v1', 'recipe_id': VIDEO.recipe_id,
        'status': status, 'passed': status == 'passed', 'task_deadline': deadline,
        'deadline': deadline, 'owned_processes_exited': True,
        'tools': {'ffmpeg_sha256': recipe.ffmpeg.sha256, 'ffprobe_sha256': recipe.ffprobe.sha256},
        'children': [{'joined': True, 'exit_code': 0 if status == 'passed' else 1, 'command_delivered': True}
                     for _ in stages],
        'stages': [{'stage': stage, 'exit_code': 0 if status == 'passed' else 1} for stage in stages]}
    if status == 'passed':
        (recipe.run/recipe.artifact).write_bytes(b'INERT VIDEO FIXTURE - NOT PLAYABLE')
        (recipe.run/'probe.log').write_text(json.dumps({'streams': [
            {'codec_name': 'h264', 'width': 1280, 'height': 720, 'nb_read_frames': '90'}]}))
        (recipe.run/'decode.log').write_bytes(b'')
        receipt.update(_outputs(recipe))
    (recipe.run/'receipt.json').write_text(json.dumps(receipt))
    return receipt


def projection(recipe, request, receipt):
    value = {'schema': VIDEO.result_schema, 'operation_id': request['operation_id'],
        'recipe_id': VIDEO.recipe_id, 'recipe_sha256': rec.digest(_json(asdict(recipe)).encode()),
        'status': receipt['status'], 'passed': receipt['passed'], 'dispatched': True,
        'owned_processes_exited': True, 'task_deadline': receipt['task_deadline'],
        'receipt_sha256': rec.digest((recipe.run/'receipt.json').read_bytes()),
        'stages': receipt['stages']}
    if receipt['passed']:
        value.update(project_success(recipe, receipt))
    else:
        value['diagnostics'] = [{'stage': 'encode', 'text': 'inert encoder unavailable', 'truncated': False}]
    return value


class VideoRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = f = recovery_fixture.CompilerRecoveryTests()
        self.addCleanup(f.doCleanups)
        f.client = self.client
        self.status = 'passed'
        with mock.patch.object(recovery_fixture, 'compiler_data', lambda **_: video_data()), \
             mock.patch.object(recovery_fixture, 'CompilerSettings', settings), \
             mock.patch.object(recovery_fixture, 'CompilerRecovery', lambda *a,**kw: CompilerRecovery(*a,kind='video',**kw)):
            f.setUp()
        (f.run/'video').mkdir()

    def client(self, request):
        f = self.fixture
        cp = f.store.load('task')
        self.assertEqual(cp.operation['id'], request['operation_id'])
        self.assertEqual(cp.state['phase'], 'tool_running')
        self.assertEqual(cp.operation['details']['name'], VIDEO.tool_name)
        self.assertEqual(request['schema'], VIDEO.request_schema)
        f.calls.append(deepcopy(request))
        recipe = prepare_video_recipe(f.settings, spec=f.spec, args=ARGS,
            operation_id=request['operation_id'], root=f.run/'video')
        f.recipes.append(recipe)
        return projection(recipe, request, inert_receipt(recipe, 900., self.status))

    def intent(self):
        return self.fixture.intent(args=deepcopy(ARGS), name=VIDEO.tool_name)

    def dispatch(self, call, args, handler=None):
        f = self.fixture
        return f.controller.tool(VIDEO.tool_name, args,
            handler or (lambda value: f.controller._handle_compiler(value, task_id='task', session_id='session')),
            session_id='session', tool_call_id=call)

    def test_failure_feedback_then_success_and_completion_preserve_original_task(self):
        f = self.fixture
        self.status = 'failed'
        call, args = self.intent(); failed = self.dispatch(call,args)
        self.assertIn('inert encoder unavailable', failed)
        self.assertIsNone(f.controller.fatal)
        with self.assertRaises(ReconciliationRequired): rec.resumable(f.owned,f.db,f.work)
        f.flush(call,failed)
        seen = []
        def provider(request, **callbacks):
            seen.append(deepcopy(request)); op=callbacks['begin']('video-followup')
            callbacks['completed'](op); return 'inert reply'
        f.controller.provider = SimpleNamespace(execute=provider)
        f.controller.llm({'messages':rec.native_history(f.db,'session')},None,session_id='session')
        self.assertIn(failed,[row.get('content') for row in seen[0]['messages']])
        self.status = 'passed'
        call,args=self.intent(); passed=self.dispatch(call,args); f.flush(call,passed)
        self.assertIsNone(f.controller.fatal)
        receipts=f.controller.recipe_receipts()
        self.assertEqual([row['status'] for row in receipts],['failed','passed'])
        self.assertEqual(receipts[-1]['media'],MEDIA)
        self.assertIsNone(f.controller.compiler_receipts())
        self.assertEqual(effect_receipts(f.owned,f.run),rec.digest((f.run/'effect-receipts.jsonl').read_bytes()))
        f.db.append({'role':'assistant','content':'The checked clip is ready.'})
        f.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'Ready.'})
        self.assertEqual(f.owned.checkpoint.state['status'],'accepted')
        self.assertEqual(f.owned.checkpoint.state['deadline_monotonic'],900.)
        self.assertEqual(len(f.calls),2)
        self.assertTrue(f.spec.completion(f.work,f.owned.checkpoint.state['tools'],'Ready.',
            **completion_kwargs(f.spec,receipts))['video']['qualified'])

    def test_native_authorization_refusal_does_not_create_video_effect(self):
        f=self.fixture; call,args=self.intent()
        denied=json.dumps({'error':'permission denied'})
        self.assertEqual(self.dispatch(call,args,lambda _:denied),denied)
        self.assertEqual(f.calls,[]); self.assertIsNone(f.owned.checkpoint.operation)
        f.flush(call,denied)
        self.assertEqual(f.controller.recipe_receipts(),[])
        self.assertFalse((f.run/'effect-receipts.jsonl').exists())

    def test_completed_native_call_cannot_repeat_effect(self):
        f=self.fixture; call,args=self.intent()
        result=self.dispatch(call,args); f.flush(call,result)
        self.dispatch(call,args)
        self.assertEqual(len(f.calls),1)
        self.assertIsNotNone(f.controller.fatal)

    def test_saved_artifact_change_is_rejected_before_safe_point(self):
        f=self.fixture; call,args=self.intent()
        result=self.dispatch(call,args); f.flush(call,result)
        (f.recipes[0].run/f.recipes[0].artifact).write_bytes(b'changed')
        with self.assertRaises(ValueError): f.controller.recipe_receipts()

    def test_saved_original_deadline_cannot_be_replaced(self):
        f=self.fixture; call,args=self.intent()
        result=self.dispatch(call,args); f.flush(call,result)
        value=json.loads(result); value['task_deadline']=1800.
        with self.assertRaises(ReconciliationRequired):
            verify_recipe_result(task_root=f.run,task_spec=f.spec,args=args,
                operation_id=f.calls[0]['operation_id'],tool_call_id=call,result=value,expected_deadline=900.)

    def test_video_binding_registration_and_advertised_tool_scope(self):
        from adaptive_inference.desktop.hermes.run_recovery import verify_task_tools
        f=self.fixture
        binding={'schema':binding_schema('video'),'host_epoch':'host-1','task_id':'task',
            'execution_id':'task','task_deadline':900.,'gateway_instance':'gateway-1','capability':'a'*64}
        path=f.run/'binding.json'; raw=json.dumps(binding).encode(); path.write_bytes(raw)
        args=SimpleNamespace(compiler_binding=path,compiler_binding_sha256=rec.digest(raw),
            gateway_instance='gateway-1',deadline_monotonic=900.)
        controller=make_recovery(f.owned,f.db,f.work,f.run,task_spec=f.spec,
            plan={'gateway':'http://127.0.0.1:18100/v1'},args=args,controls=f.controller.controls)
        self.assertEqual(controller.definition,VIDEO)
        self.assertEqual(controller.compiler_client._url,'http://127.0.0.1:18100/_adaptive/video-operation')
        registered=[]
        ctx=SimpleNamespace(register_tool=lambda **kw: registered.append(kw) or object(),register_middleware=lambda *a:None)
        with mock.patch.object(rec,'ACTIVE',controller): rec.register(ctx)
        self.assertEqual(registered[0]['name'],VIDEO.tool_name)
        self.assertEqual(set(registered[0]['schema']['parameters']['properties']),{'recipe_id'})
        self.assertNotIn(binding['capability'],json.dumps(registered[0]['schema']))
        names=expected_tool_names(f.spec)
        verify_task_tools(SimpleNamespace(tools=definitions(names),valid_tool_names=names),f.spec)
        with self.assertRaises(rec.RecoveryStop):
            verify_task_tools(SimpleNamespace(tools=definitions(names|{'terminal'}),valid_tool_names=names|{'terminal'}),f.spec)
        binding['schema']=binding_schema('compiler'); raw=json.dumps(binding).encode(); path.write_bytes(raw)
        args.compiler_binding_sha256=rec.digest(raw)
        with self.assertRaises(ReconciliationRequired):
            make_recovery(f.owned,f.db,f.work,f.run,task_spec=f.spec,
                plan={'gateway':'http://127.0.0.1:18100/v1'},args=args,controls=f.controller.controls)


class VideoHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=f=host_fixture.CompilerHostTests()
        f.runner=self.runner
        with mock.patch.object(host_fixture,'compiler_data',lambda **_:video_data()), \
             mock.patch.object(host_fixture,'CompilerSettings',settings), \
             mock.patch.object(host_fixture,'CompilerHost',lambda *a,**kw:CompilerHost(*a,kind='video',**kw)):
            await f.asyncSetUp()
        self.addCleanup(f.temp.cleanup)
        self.addAsyncCleanup(f.asyncTearDown)

    async def runner(self,controller,recipe,*,task_deadline):
        f=self.fixture; f.runs.append(task_deadline); f.recipes.append(recipe); f.started.set()
        if f.mode=='held': await f.release.wait()
        return inert_receipt(recipe,task_deadline)

    def intent(self):
        f=self.fixture; cp=f.owned.checkpoint; call='video-call-1'
        f.append({'role':'assistant','content':None,'tool_calls':[{'id':call,'type':'function',
            'function':{'name':VIDEO.tool_name,'arguments':json.dumps(ARGS)}}]})
        details={'name':VIDEO.tool_name,'args':dict(ARGS),'tool_call_id':call,'session_id':'session',
            'fingerprint':rec.digest({'name':VIDEO.tool_name,'args':ARGS}),'host_epoch':'host-1',
            'task_id':'task','execution_id':cp.task_id,'owner_epoch':cp.owner_epoch,'spec_sha256':f.spec.sha256}
        state=deepcopy(cp.state); state.update(phase='tool_running',native_history=f.native('session'))
        cp=f.owned.begin_operation('effect',details=details,state=state,expected_revision=cp.revision)
        return {'schema':VIDEO.request_schema,'host_epoch':'host-1','task_id':'task','execution_id':cp.task_id,
            'owner_epoch':cp.owner_epoch,'operation_id':cp.operation['id'],'tool_call_id':call,'recipe_id':VIDEO.recipe_id}

    async def test_actual_typed_http_client_host_and_duplicate_poll_keep_one_operation(self):
        f=self.fixture; await f.bind(); request=self.intent(); f.mode='held'
        client=CompilerClient(f.client.server.port,f.capability,f.deadline,kind='video',clock=lambda:f.now)
        pending=asyncio.create_task(asyncio.to_thread(client,request))
        await asyncio.wait_for(f.started.wait(),3)
        async with f.client.post(VIDEO.route,json=request,headers={VIDEO.header:f.capability}) as response:
            self.assertEqual((await response.json())['state'],'pending')
        f.release.set(); result=await asyncio.wait_for(pending,5)
        self.assertTrue(result['passed']); self.assertEqual(result['media'],MEDIA)
        self.assertEqual(len(f.runs),1)
        async with f.client.post(VIDEO.route,json=request,headers={VIDEO.header:f.capability}) as response:
            self.assertEqual((await response.json())['result'],result)
        self.assertEqual(len(f.runs),1)
        normalized=verify_recipe_result(task_root=f.root,task_spec=f.spec,args=ARGS,
            operation_id=request['operation_id'],tool_call_id=request['tool_call_id'],result=result,
            expected_deadline=f.deadline)
        self.assertTrue(f.spec.video_completion([normalized])['qualified'])
        self.assertFalse((f.root/'compiler').exists())

    async def test_wrong_native_call_or_schema_cannot_prepare_video(self):
        f=self.fixture; await f.bind(); request=self.intent()
        for change,expected in [({'schema':'compiler-operation.v1'},400),({'tool_call_id':'not-native'},200)]:
            async with f.client.post(VIDEO.route,json={**request,**change},headers={VIDEO.header:f.capability}) as response:
                self.assertEqual(response.status,expected)
                body=await response.json()
                if expected==200: self.assertEqual(body['result']['status'],'binding_refused')
        self.assertEqual(f.runs,[]); self.assertFalse((f.root/'video').exists())

    async def test_joined_worker_exports_exact_terminal_video_without_dispatch_or_store_write(self):
        f=self.fixture; await f.bind(); request=self.intent()
        client=CompilerClient(f.client.server.port,f.capability,f.deadline,kind='video',clock=lambda:f.now)
        result=await asyncio.wait_for(asyncio.to_thread(client,request),5)
        checkpoint=f.store.load('task'); history=f.store.history('task')
        f.live,f.joined=False,True
        with mock.patch.object(f.host,'_validate',side_effect=AssertionError('no redispatch')):
            receipt=await f.host.terminal_receipt(request['operation_id'])
        self.assertEqual(json.loads(receipt['result']),result)
        self.assertEqual(receipt['name'],VIDEO.tool_name)
        self.assertEqual(receipt['video_receipt']['status'],'passed')
        self.assertEqual(receipt['owner_epoch'],checkpoint.operation['details']['owner_epoch'])
        self.assertEqual(f.store.load('task'),checkpoint)
        self.assertEqual(f.store.history('task'),history)
        self.assertEqual(f.runs,[f.deadline])
        self.assertFalse((f.root/'effect-receipts.jsonl').exists())


class VideoWireTests(unittest.TestCase):
    def test_real_serialized_request_uses_exact_declared_video_tool(self):
        f=wire_fixture.CompilerWireBoundaryTests(); self.addCleanup(f.doCleanups); f.setUp()
        f.spec=TaskSpec(video_data()); boundary=f.boundary(task_spec=f.spec)
        request=f.request(('read_file','write_file',VIDEO.tool_name))
        self.assertEqual(boundary.send(None,request).status_code,200)
        self.assertEqual(boundary.rows[0]['tool_names'],sorted(expected_tool_names(f.spec)))
        with self.assertRaises(wire_fixture.wire.Refused): boundary.send(None,f.request())
