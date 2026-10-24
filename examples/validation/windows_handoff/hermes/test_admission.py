# SPDX-License-Identifier: Apache-2.0
"""CPU-only exact-wire tests using the installed OpenAI SDK and MockTransport."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import httpx
import admission

INSTANCE='a'*32
BASE='http://127.0.0.1:18100/v1'
MODEL='qwen3.8-flash-next-iq3_s-adaptive-media-beta'

def response_for(req, instance=INSTANCE):
    fields={'dispatched':False,'gateway_instance':instance,
            'attempt_id':req.headers['X-Adaptive-Attempt-Id'],
            'body_sha256':admission.sha(req.content)}
    return httpx.Response(503,request=req,headers={
        'X-Adaptive-Dispatch':'not-dispatched','X-Adaptive-Gateway-Instance':instance,
        'X-Adaptive-Attempt-Id':fields['attempt_id'],'X-Adaptive-Body-SHA256':fields['body_sha256']},
        json={'error':{'type':'adaptive_inference_error','code':'admission_deferred'},'admission':fields})

class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock=0.;self.sent=[];self.events=[];self.inflight=None
        self.provider=admission.Provider(base_url=BASE,model=MODEL,instance=INSTANCE,boundary=None,
            deadline=20,status=lambda:{'service':'adaptive-inference','instance':INSTANCE,
              'scheduler':{'active':False,'pending':0,'closing':False,'backend_completion_uncertain':False},
              'resources':{'admission_allowed':True}},clock=lambda:self.clock,sleep=self.sleep)
        self.addCleanup(self.provider.close)
        self.request={'model':MODEL,'messages':[{'role':'user','content':'unchanged task'}],
            'timeout':1800.,'max_tokens':10923,'reasoning_effort':'high','temperature':.2,
            'tools':[{'type':'function','function':{'name':'fixture','parameters':{'type':'object'}}}],
            'tool_choice':'auto','extra_body':{'reasoning_budget_tokens':8192,'experimental_speed_projection':False},
            'extra_headers':{'X-Caller':'keep'}}
    def sleep(self,seconds):self.clock+=seconds
    def begin(self,attempt):self.inflight=attempt;self.events.append('begin');return attempt
    def deferred(self,operation,proof):
        self.assertEqual(operation,self.inflight);self.inflight=None;self.events.append('deferred')
    def complete(self,operation):
        self.assertEqual(operation,self.inflight);self.inflight=None;self.events.append('complete')
    def execute(self,begin=None):
        return self.provider.execute(self.request,waiting=lambda _:self.events.append('waiting'),
            begin=begin or self.begin,deferred=self.deferred,completed=self.complete)
    def install(self,handler):
        self.provider.client._client.close()
        def wrapped(req):
            self.provider.inspect_request(req)
            self.sent.append(req)
            response=handler(req)
            self.provider.inspect_response(req,response)
            return response
        self.provider.client._client=httpx.Client(transport=httpx.MockTransport(wrapped),trust_env=False)
    def success(self,req):
        return httpx.Response(200,request=req,json={'id':'fixture','object':'chat.completion','created':0,
            'model':MODEL,'choices':[{'index':0,'message':{'role':'assistant','content':'done'},'finish_reason':'stop'}]})
    def test_exact_race_reissue_preserves_all_caller_options_and_zero_sdk_retries(self):
        original=copy.deepcopy(self.request)
        self.install(lambda req:response_for(req) if len(self.sent)==1 else self.success(req))
        result=self.execute()
        self.assertEqual(result.choices[0].message.content,'done')
        self.assertEqual(self.provider.client.max_retries,0)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[0].content,self.sent[1].content)
        self.assertEqual(self.request,original)
        wire=json.loads(self.sent[1].content)
        for key in ('model','messages','tools','tool_choice','temperature','max_tokens','reasoning_effort'):
            self.assertEqual(wire[key],original[key])
        self.assertEqual(wire['reasoning_budget_tokens'],8192)
        self.assertIs(wire['experimental_speed_projection'],False)
        self.assertEqual(self.sent[1].headers['X-Caller'],'keep')
        self.assertEqual(self.sent[1].headers['Authorization'],'Bearer local-no-key')
        self.assertEqual(self.sent[1].extensions['timeout']['read'],1800)
        self.assertIsNone(self.inflight)
    def test_generic_transport_failure_never_retries_and_retains_operation(self):
        def failure(req):raise httpx.ReadTimeout('unknown',request=req)
        self.install(failure)
        with self.assertRaises(Exception):self.execute()
        self.assertEqual(len(self.sent),1);self.assertIsNotNone(self.inflight)
        self.assertNotIn('deferred',self.events);self.assertNotIn('complete',self.events)
    def test_generic_or_spoofed_503_never_retries(self):
        for mode in ('missing','instance','hash','attempt','duplicate','wrong-body','backend'):
            with self.subTest(mode=mode):
                req=httpx.Request('POST',BASE+'/chat/completions',headers={'X-Adaptive-Attempt-Id':'abc'},content=b'{}')
                response=response_for(req)
                if mode=='missing':del response.headers['X-Adaptive-Dispatch']
                elif mode=='instance':response.headers['X-Adaptive-Gateway-Instance']='b'*32
                elif mode=='hash':response.headers['X-Adaptive-Body-SHA256']='0'*64
                elif mode=='attempt':response.headers['X-Adaptive-Attempt-Id']='other'
                elif mode=='duplicate':response.headers=httpx.Headers([*response.headers.multi_items(),('X-Adaptive-Dispatch','not-dispatched')])
                elif mode=='wrong-body':response._content=response.content.replace(b'false',b'true')
                elif mode=='backend':response.headers=httpx.Headers({})
                self.assertIsNone(admission.proof(response,req,instance=INSTANCE,attempt='abc'))
        self.install(lambda req:httpx.Response(503,request=req,json={'error':{'code':'admission_deferred'}}))
        with self.assertRaises(Exception):self.execute()
        self.assertEqual(len(self.sent),1);self.assertIsNotNone(self.inflight)
    def test_changed_reissue_bytes_refused_before_second_transport_dispatch(self):
        original=self.provider.inspect_request
        def alter(req):
            if self.sent:req._content=b'{"model":"changed"}'
            original(req)
        self.provider.inspect_request=alter
        self.install(lambda req:response_for(req))
        with self.assertRaisesRegex(admission.AdmissionStop,'bytes changed'):self.execute()
        self.assertEqual(len(self.sent),1);self.assertIsNotNone(self.inflight)
    def test_deadline_consumed_by_durable_begin_refuses_before_any_send(self):
        self.install(self.success)
        def late(attempt):
            operation=self.begin(attempt);self.clock=21;return operation
        with self.assertRaisesRegex(admission.AdmissionStop,'final pre-send'):self.execute(begin=late)
        self.assertEqual(self.sent,[]);self.assertIsNotNone(self.inflight)
    def test_changed_instance_during_wait_refuses_without_begin(self):
        self.install(self.success)
        self.provider.status_reader=lambda:{'service':'adaptive-inference','instance':'b'*32}
        with self.assertRaisesRegex(admission.AdmissionStop,'identity'):self.execute()
        self.assertEqual(self.sent,[]);self.assertIsNone(self.inflight)
    def test_deadline_expires_in_wait_without_begin(self):
        self.install(self.success)
        self.provider.admitted=lambda:False
        with self.assertRaisesRegex(admission.AdmissionStop,'wait deadline'):self.execute()
        self.assertEqual(self.sent,[]);self.assertIsNone(self.inflight)
    def test_unsupported_caller_option_is_not_silently_dropped(self):
        self.install(self.success)
        self.request['unknown_sdk_option']='must refuse'
        with self.assertRaises(TypeError):self.execute()
        self.assertEqual(self.sent,[]);self.assertIsNotNone(self.inflight)

if __name__=='__main__':unittest.main(verbosity=2)
