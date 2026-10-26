"""Real SQLite recovery with generic task data; no SDK/model/service execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from adaptive_inference.task_spec import TaskSpec, NAMESPACE, digest
from adaptive_inference.task_store import TaskStore, ReconciliationRequired
from adaptive_inference.desktop.hermes import recovery as rec
import test_desktop_report_feedback as existing
from task_spec_support import spec_data


class TaskRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name); self.work = self.run/'work'; self.work.mkdir()
        (self.work/'notes.txt').write_bytes(b'First note.\nSecond note.\n')
        self.store = TaskStore(self.run/'task.sqlite3')
        self.db = existing.NativeDB(self.run/'native.sqlite3'); self.addCleanup(self.db.close)
        self.context = None; self.addCleanup(self.release)
        self.effects = []; self.number = 0

    def prepare(self, raw=None):
        self.spec = TaskSpec(raw or spec_data())
        self.db.append({'role':'user', 'content':self.spec.prompt})
        cp = self.store.create('arbitrary-task', self.spec.prompt, max_attempts=8,
            metadata={**self.spec.metadata(), 'pre_effect_validator':self.spec.validator_identity()},
            state=rec.initial_state(self.spec.prompt,'session'))
        self.claim(cp)
        self.controller.control_safe_point()

    def claim(self, cp=None):
        cp = cp or self.store.load('arbitrary-task')
        self.context = self.store.claim(cp.task_id, expected_revision=cp.revision)
        self.owned = self.context.__enter__()
        self.controller = rec.Recovery(self.owned,self.db,self.work,self.run,
            controls=SimpleNamespace(poll=lambda owned: None))

    def release(self):
        if self.context is not None:
            self.context.__exit__(None,None,None); self.context = None

    def call(self, name, args, *, session='session', flush=True):
        self.number += 1; ident = f'tool-{self.number}'
        self.db.append({'role':'assistant','content':None,'tool_calls':[
            {'id':ident,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]})
        def effect(arguments):
            self.effects.append((name, deepcopy(arguments)))
            if name == 'write_file':
                (self.work/arguments['path']).write_bytes(arguments['content'].encode('utf-8'))
                return json.dumps({'verified': True})
            return json.dumps({'content':(self.work/arguments['path']).read_text()})
        result = self.controller.tool(name,args,effect,session_id=session,tool_call_id=ident)
        if flush:
            self.db.append({'role':'tool','tool_call_id':ident,'content':result})
            self.controller.control_safe_point()
        return result

    def test_plain_text_create_then_identical_replay_has_one_physical_write(self):
        self.prepare(); self.call('read_file',{'path':'notes.txt'})
        args = {'path':'answer.txt','content':'Two short notes.'}
        first = self.call('write_file',args)
        self.release(); self.claim()
        self.assertTrue(rec.resumable(self.owned,self.db,self.work))
        self.assertEqual(self.call('write_file',args),first)
        self.assertEqual(sum(name=='write_file' for name,args in self.effects),1)
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()),1)
        self.assertTrue(self.owned.checkpoint.state['tools'][-1]['reused'])
        self.db.append({'role':'assistant','content':'Created answer.txt.'})
        self.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'Created answer.txt.'})
        self.assertEqual(self.owned.checkpoint.state['status'],'accepted')
        self.assertEqual(self.owned.checkpoint.prompt,self.spec.prompt)

    def test_two_different_json_domains_share_the_same_validator(self):
        for expected in ({'units':17}, {'reorder':{'pens':3}}):
            with self.subTest(expected=expected):
                spec = TaskSpec(spec_data(outputs=[('result.json','json')],expected={'result.json':expected}))
                self.assertTrue(spec.validate_write('write_file',{'path':'result.json','content':json.dumps(expected)}).accepted)

    def test_rejected_json_feedback_then_correction_one_effect(self):
        self.prepare(spec_data(outputs=[('result.json','json')],expected={'result.json':{'reorder':3}}))
        response = self.call('write_file',{'path':'result.json','content':'{"reorder":4}'})
        self.assertIn('proposal_validation_failed',response); self.assertEqual(self.effects,[])
        self.assertFalse((self.work/'result.json').exists())
        self.call('write_file',{'path':'result.json','content':'{"reorder":3}'})
        self.assertEqual(len(self.effects),1)
        self.assertEqual(len(self.owned.checkpoint.state['validation_rejections']),1)
        self.db.append({'role':'assistant','content':'done'})
        self.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'done'})
        self.assertEqual(self.spec.completion(self.work,self.owned.checkpoint.state['tools'],'done')['semantic_validation'],'oracle_matched')

    def test_changed_input_blocks_read_and_resume_without_dispatch(self):
        self.prepare(); (self.work/'notes.txt').write_bytes(b'changed')
        with self.assertRaises(ReconciliationRequired): rec.resumable(self.owned,self.db,self.work)
        response = self.call('read_file',{'path':'notes.txt'},flush=False)
        self.assertIn('error',json.loads(response)); self.assertIsNotNone(self.controller.fatal)
        self.assertEqual(self.effects,[])

    def test_cross_task_path_and_wrong_session_never_dispatch(self):
        self.prepare()
        response = self.call('write_file',{'path':'../other/answer.txt','content':'bad'},flush=False)
        self.assertIn('error',json.loads(response)); self.assertIsNotNone(self.controller.fatal)
        self.assertEqual(self.effects,[])

    def test_wrong_native_session_never_dispatch(self):
        self.prepare()
        response = self.call('write_file',{'path':'answer.txt','content':'bad'},session='another',flush=False)
        self.assertIn('error',json.loads(response)); self.assertIsNotNone(self.controller.fatal)
        self.assertEqual(self.effects,[])

    def test_changed_write_cannot_overwrite_completed_output(self):
        self.prepare(); self.call('write_file',{'path':'answer.txt','content':'first'})
        response = self.call('write_file',{'path':'answer.txt','content':'second'},flush=False)
        self.assertIn('error',json.loads(response)); self.assertIsNotNone(self.controller.fatal)
        self.assertEqual((self.work/'answer.txt').read_text(),'first'); self.assertEqual(len(self.effects),1)

    def test_missing_required_artifact_never_marks_task_accepted(self):
        self.prepare(); self.db.append({'role':'assistant','content':'I am done'})
        with self.assertRaises(ValueError):
            self.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'I am done'})
        self.assertEqual(self.owned.checkpoint.state['status'],'pending')

    def test_answer_only_task_uses_original_prompt_without_file_effects(self):
        self.prepare(spec_data(inputs={},outputs=[],prompt='Explain an ordinary scheduling concept.'))
        self.db.append({'role':'assistant','content':'An explanation.'})
        self.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'An explanation.'})
        self.assertEqual(self.owned.checkpoint.state['output'],'An explanation.')
        self.assertEqual(self.effects,[])

    def test_caller_cannot_replace_declared_validator_with_accept_all(self):
        from adaptive_inference.feedback import Verdict
        self.prepare()
        with self.assertRaises(ReconciliationRequired):
            rec.Recovery(self.owned,self.db,self.work,self.run,pre_effect_validator=lambda *args:Verdict(True),
                validator_identity=self.spec.validator_identity())

    def test_new_task_contract_is_inherited_as_metadata_not_mutable_state(self):
        self.prepare(); self.call('write_file',{'path':'answer.txt','content':'saved'})
        self.assertNotIn(NAMESPACE,self.owned.checkpoint.state)
        before = deepcopy(self.owned.checkpoint.metadata)
        self.release(); self.claim()
        self.assertEqual(self.owned.checkpoint.metadata,before)
        self.assertEqual(rec.task_contract(self.owned.checkpoint),self.spec)
        self.assertTrue(rec.resumable(self.owned,self.db,self.work))

    def test_multiple_declared_outputs_keep_distinct_create_only_receipts(self):
        self.prepare(spec_data(outputs=[('summary.txt','text'),('details.json','json')]))
        self.call('write_file',{'path':'summary.txt','content':'Summary.'})
        self.call('write_file',{'path':'details.json','content':'{"count":2}'})
        self.db.append({'role':'assistant','content':'Both created.'})
        self.controller.finish({'completed':True,'failed':False,'interrupted':False,'final_response':'Both created.'})
        result = self.spec.completion(self.work,self.owned.checkpoint.state['tools'],'Both created.')
        self.assertEqual(set(result['artifacts']),{'summary.txt','details.json'})
        self.assertEqual(len(self.effects),2)
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()),2)

    def test_uncertain_generic_write_reconciles_exact_existing_effect_without_replay(self):
        self.prepare()
        def barrier(label):
            if label == 'uncertain_after_write': raise rec.RecoveryStop('synthetic stop after physical effect')
        self.controller.barrier = barrier
        args = {'path':'answer.txt','content':'Saved before interruption.'}
        with self.assertRaises(rec.RecoveryStop): self.call('write_file',args,flush=False)
        operation_id = self.owned.checkpoint.operation['id']
        self.release(); self.claim()
        self.assertTrue(self.owned.checkpoint.requires_reconciliation)
        self.db.acquire_session_turn_lease = lambda *args, **kwargs: True
        self.db.release_session_turn_lease = lambda *args, **kwargs: None
        self.db.append_message = lambda session, role, **kwargs: self.db.append({
            'role':role,'content':kwargs['content'],'tool_call_id':kwargs['tool_call_id']})
        receipt = json.loads((self.run/'effect-receipts.jsonl').read_text())
        rec.reconcile_write(self.owned,self.db,self.work,receipt,expected_operation_id=operation_id)
        self.assertFalse(self.owned.checkpoint.requires_reconciliation)
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertTrue(rec.resumable(self.owned,self.db,self.work))
        self.call('write_file',args)
        self.assertEqual(len(self.effects),1)
        self.assertEqual((self.work/'answer.txt').read_text(),args['content'])
