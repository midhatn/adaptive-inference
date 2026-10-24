"""CPU-only tests of unchanged v5 generations in v6; no model/server/UI is started."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from aiohttp import ClientConnectionError

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('arithmetic_harness_v5',HERE/'run_validation.py')
harness=importlib.util.module_from_spec(spec); spec.loader.exec_module(harness)


def response(content=None, *, finish='stop', model=None, status=200, work_class='background', raw=None):
    data={'model':harness.MODEL if model is None else model,
          'choices':[{'message':{'role':'assistant','content':json.dumps(harness.EXPECTED) if content is None else content},
                      'finish_reason':finish}], 'usage':{'completion_tokens':17}}
    return {'status':status,'headers':{'X-Adaptive-Class':work_class},
            'raw':json.dumps(data).encode() if raw is None else raw}


class FakeResponse:
    def __init__(self, row):
        self.row=row; self.status=row['status']; self.headers=row['headers']
    async def __aenter__(self): return self
    async def __aexit__(self,*args): return False
    async def read(self): return self.row['raw']


class FakeSession:
    def __init__(self, script): self.script=list(script); self.calls=[]
    async def __aenter__(self): return self
    async def __aexit__(self,*args): return False
    def post(self,url,*,json,headers):
        self.calls.append({'url':url,'body':copy.deepcopy(json),'headers':dict(headers)})
        if not self.script: raise AssertionError('Request exceeded expected bound')
        row=self.script.pop(0)
        if isinstance(row,BaseException): raise row
        return FakeResponse(row)


class ArithmeticFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name)

    async def execute(self, script):
        self.session=FakeSession(script)
        with mock.patch.object(harness,'ClientSession',return_value=self.session) as constructor, \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                return await harness.generations(self.run,object())
            finally:
                self.assertFalse(constructor.call_args.kwargs['trust_env'])

    def read(self,name): return json.loads((self.run/name).read_text(encoding='utf-8'))

    def assert_request_contract(self):
        for call in self.session.calls:
            body=call['body']
            self.assertEqual(call['url'],'http://127.0.0.1:18100/v1/chat/completions')
            self.assertEqual(call['headers'],{'X-Adaptive-Class':'background'})
            self.assertEqual(body['model'],harness.MODEL)
            self.assertEqual(body['messages'][0],{'role':'user','content':harness.PROMPT})
            self.assertEqual({key:body[key] for key in harness.QUALITY},harness.QUALITY)
            self.assertEqual(set(body),{'model','messages',*harness.QUALITY})

    async def test_wrong_then_correct_actual_next_request_contains_original_output_and_feedback(self):
        wrong=copy.deepcopy(harness.EXPECTED); wrong['total_cents']+=1
        rejected=json.dumps(wrong)
        receipts=await self.execute([response(rejected),response(),response()])
        self.assertEqual([row['attempts'] for row in receipts],[2,1])
        self.assertEqual(len(self.session.calls),3)
        attempts=self.read('inference-attempts.private.json')
        feedback=attempts[0]['verdict']['feedback']
        messages=self.session.calls[1]['body']['messages']
        self.assertEqual(messages[1],{'role':'assistant','content':rejected})
        self.assertEqual(messages[2],{'role':'user','content':
            'The acceptance check failed. Correct the result while preserving the original task.\n'+feedback})
        self.assertEqual(len(self.session.calls[2]['body']['messages']),1)
        for secret_answer in ('4350','1200','750','2400'): self.assertNotIn(secret_answer,feedback)
        self.assertFalse(attempts[0]['verdict']['accepted'])
        for row,call in zip(attempts,self.session.calls):
            self.assertEqual(self.read(row['request_file']),call['body'])
            raw=(self.run/row['response_file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['response_sha256'])
        self.assert_request_contract()

    async def test_three_wrong_exhausts_first_task_and_retains_all_rejections(self):
        with self.assertRaisesRegex(RuntimeError,'exhausted'):
            await self.execute([response('{}') for _ in range(3)]+[response()])
        self.assertEqual(len(self.session.calls),3)
        ledger=self.read('inference-tasks.private.json')
        self.assertEqual((ledger['logical_task_count'],ledger['request_count']),(2,3))
        self.assertEqual([row['status'] for row in ledger['tasks']],['exhausted','not_started'])
        self.assertEqual(self.read('inference-receipts.json'),[])
        attempts=self.read('inference-attempts.private.json')
        self.assertTrue(all(row['verdict']['accepted'] is False for row in attempts))
        self.assertEqual([row['retryable'] for row in attempts],[True,True,False])
        self.assertEqual([len(row['body']['messages']) for row in self.session.calls],[1,3,5])
        self.assert_request_contract()

    async def test_two_tasks_each_with_three_attempts_have_six_distinct_requests(self):
        receipts=await self.execute([response('{}'),response('not json'),response()]*2)
        self.assertEqual(len(receipts),2)
        self.assertEqual([row['request_count'] for row in receipts],[3,3])
        self.assertEqual([row['attempt_request_indices'] for row in receipts],[[0,1,2],[3,4,5]])
        ledger=self.read('inference-tasks.private.json')
        self.assertEqual(ledger['request_count'],6)
        self.assertTrue(all(row['accepted'] for row in ledger['tasks']))
        attempts=self.read('inference-attempts.private.json')
        self.assertEqual(len({row['request_file'] for row in attempts}),6)
        self.assertEqual(len({row['response_file'] for row in attempts}),6)
        self.assert_request_contract()

    async def test_wrong_model_class_http_or_unknown_envelope_never_retry(self):
        failures=[response(model='other'),response(work_class='normal'),response(status=503),
                  response(raw=b'not an envelope'),response(raw=b'{}'),response(finish=None),
                  response(raw=b'{"model":"duplicate","model":"other"}')]
        for first in failures:
            with self.subTest(first=first):
                with self.assertRaises((RuntimeError,ValueError)):
                    await self.execute([first,response(),response()])
                self.assertEqual(len(self.session.calls),1)
                row=self.read('inference-attempts.private.json')[0]
                self.assertEqual(row['status'],'fatal_error')
                self.assertFalse(row['retryable']); self.assertIsNone(row['verdict'])
                self.assertEqual((self.run/row['response_file']).read_bytes(),first['raw'])
                self.assertEqual(self.read('inference-tasks.private.json')['tasks'][0]['status'],'fatal_error')

    async def test_transport_failure_has_request_evidence_and_no_retry(self):
        with self.assertRaises(ClientConnectionError):
            await self.execute([ClientConnectionError('fixture connection lost'),response()])
        self.assertEqual(len(self.session.calls),1)
        row=self.read('inference-attempts.private.json')[0]
        self.assertTrue((self.run/row['request_file']).is_file())
        self.assertFalse((self.run/row['response_file']).exists())
        self.assertEqual(row['status'],'fatal_error')
        self.assertIsNone(row['verdict'])

    async def test_known_length_finish_is_rejected_before_bounded_correction(self):
        receipts=await self.execute([response(finish='length'),response(),response()])
        self.assertEqual(receipts[0]['attempts'],2)
        row=self.read('inference-attempts.private.json')[0]
        self.assertFalse(row['verdict']['accepted'])
        self.assertIn('stop reason',row['verdict']['feedback'])
        self.assertIn(row['verdict']['feedback'],self.session.calls[1]['body']['messages'][-1]['content'])

    async def test_three_nonstop_answers_fail_even_when_arithmetic_matches(self):
        with self.assertRaisesRegex(RuntimeError,'exhausted'):
            await self.execute([response(finish='length')]*3)
        self.assertEqual(len(self.session.calls),3)
        self.assertFalse(any(row['verdict']['accepted'] for row in self.read('inference-attempts.private.json')))

    async def test_exact_integer_schema_and_json_only_are_enforced(self):
        boolean=copy.deepcopy(harness.EXPECTED); boolean['rows']=True
        floating=copy.deepcopy(harness.EXPECTED); floating['rows']=4.0
        nested=copy.deepcopy(harness.EXPECTED); nested['by_item']['apple']=1200.0
        extra=copy.deepcopy(harness.EXPECTED); extra['extra']=0
        missing=copy.deepcopy(harness.EXPECTED); del missing['by_item']['orange']
        bad=[json.dumps(row) for row in (boolean,floating,nested,extra,missing)]
        bad.extend(['```json\n'+json.dumps(harness.EXPECTED)+'\n```',
                    json.dumps(harness.EXPECTED).replace('"rows": 4','"rows": 9, "rows": 4'),'{'])
        for content in bad:
            with self.subTest(content=content):
                receipts=await self.execute([response(content),response(),response()])
                self.assertEqual(receipts[0]['attempts'],2)
                self.assertFalse(self.read('inference-attempts.private.json')[0]['verdict']['accepted'])
                self.assertEqual(self.session.calls[1]['body']['messages'][1]['content'],content)

    async def test_second_task_exhaustion_keeps_prior_accepted_task(self):
        with self.assertRaisesRegex(RuntimeError,'exhausted'):
            await self.execute([response()]+[response('{}')]*3)
        self.assertEqual(len(self.session.calls),4)
        self.assertEqual(len(self.read('inference-receipts.json')),1)
        ledger=self.read('inference-tasks.private.json')
        self.assertEqual([row['status'] for row in ledger['tasks']],['accepted','exhausted'])

    def test_helper_is_actual_canonical_function_and_source_is_bound(self):
        from adaptive_inference.feedback import run_with_feedback
        self.assertIs(harness.run_with_feedback,run_with_feedback)
        self.assertIn('src/adaptive_inference/feedback.py',harness.runtime_sources())

    def test_frozen_predecessor_other_functions_constants_and_helpers_unchanged(self):
        previous=HERE.parent/'successor-v4'
        before=ast.parse((previous/'run_validation.py').read_text(encoding='utf-8'))
        after=ast.parse((HERE/'run_validation.py').read_text(encoding='utf-8'))
        def nodes(tree):
            return {node.name:ast.dump(node,include_attributes=False) for node in tree.body
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        old,new=nodes(before),nodes(after)
        self.assertEqual(set(old) | {'close_controlled_host'},set(new))
        self.assertEqual({k:v for k,v in old.items() if k not in ('runtime_sources','generations','main')},
                         {k:v for k,v in new.items() if k not in ('runtime_sources','generations','main','close_controlled_host')})
        def constants(tree):
            return {node.targets[0].id:ast.dump(node.value,include_attributes=False) for node in tree.body
                    if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name)
                    and node.targets[0].id in ('PROMPT','MODEL','QUALITY','EXPECTED')}
        self.assertEqual(constants(before),constants(after))
        manifest=json.loads((HERE/'predecessor-source-manifest.json').read_text(encoding='utf-8-sig'))
        for row in manifest:
            self.assertEqual(hashlib.sha256((previous/row['path']).read_bytes()).hexdigest(),row['predecessor_sha256'])
            if row['path']!='run_validation.py':
                self.assertEqual((HERE/row['path']).read_bytes(),(previous/row['path']).read_bytes())


if __name__=='__main__': unittest.main(verbosity=2)
