"""Real TaskStore plus durable SQLite native-history fixture; no model or GUI."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
from adaptive_inference.feedback import Verdict
from adaptive_inference.task_store import TaskStore,ReconciliationRequired
from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.report_validator import validator,identity
from adaptive_inference.desktop.hermes.run_recovery import PROMPT

REPORT={'rows':4,'units':17,'total_cents':4350,'by_item':{'folder':1100,'notebook':2250,'pen':1000}}
WRONG={**REPORT,'units':19,'total_cents':4800}

class NativeDB:
    """Only the consumed public SessionDB projection, backed by real SQLite."""
    def __init__(self,path):
        self.connection=sqlite3.connect(path)
        self.connection.execute('CREATE TABLE IF NOT EXISTS messages (n INTEGER PRIMARY KEY, body TEXT NOT NULL)')
    def append(self,row):
        self.connection.execute('INSERT INTO messages(body) VALUES (?)',(json.dumps(row),));self.connection.commit()
    def resolve_resume_session_id(self,session):return session
    def get_messages_as_conversation(self,session,include_row_ids=True):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT body FROM messages ORDER BY n')]
    def close(self):self.connection.close()

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name);self.work=self.run/'work';self.work.mkdir()
        self.db=NativeDB(self.run/'native.sqlite3');self.addCleanup(self.db.close)
        self.db.append({'role':'user','content':PROMPT})
        self.store=TaskStore(self.run/'task.sqlite3');self.validator_id=identity(REPORT)
        state=rec.initial_state(PROMPT,'session');state['native_history']=rec.native_history(self.db,'session')
        cp=self.store.create('task',PROMPT,max_attempts=8,
            metadata={'pre_effect_validator':self.validator_id},state=state)
        self.context=None;self.claim(cp);self.addCleanup(self.release)
        self.effects=[];self.holds=[];self.calls=0
    def claim(self,cp=None):
        cp=cp or self.store.load('task')
        self.context=self.store.claim('task',expected_revision=cp.revision)
        self.owned=self.context.__enter__()
        self.controller=rec.Recovery(self.owned,self.db,self.work,self.run,
            controls=SimpleNamespace(poll=lambda owned:None),pre_effect_validator=validator(REPORT),
            validator_identity=self.validator_id)
        self.controller.barrier=lambda label:self.holds.append(label)
    def release(self):
        if self.context is not None:self.context.__exit__(None,None,None);self.context=None
    def intent(self,content):
        self.calls+=1;call_id='tool-'+str(self.calls)
        args={'path':'report.json','content':content if isinstance(content,str) else json.dumps(content)}
        self.db.append({'role':'assistant','content':None,'tool_calls':[{'id':call_id,'type':'function',
            'function':{'name':'write_file','arguments':json.dumps(args)}}]})
        return call_id,args
    def effect(self,args):
        self.effects.append(deepcopy(args));(self.work/'report.json').write_text(args['content'],encoding='utf-8')
        return json.dumps({'verified':True})
    def proposal(self,content):
        call_id,args=self.intent(content)
        result=self.controller.tool('write_file',args,self.effect,session_id='session',tool_call_id=call_id)
        return call_id,args,result
    def flush(self,call_id,result):
        self.db.append({'role':'tool','tool_call_id':call_id,'content':result})
        self.controller.control_safe_point()
    def provider(self):
        def execute(request,**callbacks):
            op=callbacks['begin']('attempt-'+str(self.owned.checkpoint.state['requests']))
            callbacks['completed'](op)
            return 'fixture response'
        self.controller.provider=SimpleNamespace(execute=execute)
    def test_full05_rejected_then_corrected_exactly_one_write(self):
        call,args,result=self.proposal(WRONG)
        self.assertEqual(self.effects,[]);self.assertFalse((self.work/'report.json').exists())
        state=self.owned.checkpoint.state
        self.assertEqual(state['tools'],[]);self.assertEqual(len(state['validation_rejections']),1)
        self.assertEqual(state['phase'],'awaiting_native_flush');self.assertIsNone(self.owned.checkpoint.operation)
        self.assertFalse((self.run/'effect-receipts.jsonl').exists());self.assertEqual(self.holds,[])
        self.assertNotIn('4350',result);self.assertNotIn('4800',result)
        self.flush(call,result);self.provider()
        self.controller.llm({},None,session_id='session')
        self.assertNotIn('safe_after_write',self.holds)
        self.db.append({'role':'assistant','content':'correcting'})
        self.controller.control_safe_point()
        call,args,result=self.proposal(REPORT);self.flush(call,result)
        self.assertEqual(len(self.effects),1)
        self.assertEqual(json.loads((self.work/'report.json').read_text()),REPORT)
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()),1)
        self.assertEqual(len(self.owned.checkpoint.state['tools']),1)
        self.controller.llm({},None,session_id='session')
        self.assertEqual(self.holds.count('safe_after_write'),1)
    def test_restart_before_native_flush_refuses_then_safe_flush_preserves_feedback(self):
        call,args,result=self.proposal(WRONG)
        with self.assertRaises(ReconciliationRequired):rec.resumable(self.owned,self.db,self.work)
        self.flush(call,result);before=deepcopy(self.owned.checkpoint.state)
        self.release();self.claim()
        self.assertEqual(rec.resumable(self.owned,self.db,self.work),before['native_history'])
        self.assertEqual(self.owned.checkpoint.state,before)
        call,args,result=self.proposal(REPORT);self.flush(call,result)
        self.assertEqual(len(self.effects),1)
    def test_unrelated_native_row_cannot_satisfy_rejected_feedback_flush(self):
        self.proposal(WRONG);self.db.append({'role':'assistant','content':'unrelated'})
        with self.assertRaises(ReconciliationRequired):self.controller.control_safe_point()
        self.assertEqual(self.owned.checkpoint.state['phase'],'awaiting_native_flush')
        self.assertEqual(self.effects,[])
    def test_changed_or_missing_validator_identity_refused(self):
        for callback,ident in ((None,None),(validator(REPORT),{**self.validator_id,'version':'changed'})):
            with self.subTest(identity=ident),self.assertRaises(ReconciliationRequired):
                rec.Recovery(self.owned,self.db,self.work,self.run,pre_effect_validator=callback,validator_identity=ident)
    def test_all_wrong_stays_inside_existing_eight_request_budget(self):
        self.provider()
        for i in range(8):
            self.controller.llm({'index':i},None,session_id='session')
            call,args,result=self.proposal(WRONG);self.flush(call,result)
        with self.assertRaises(rec.RecoveryStop):self.controller.llm({},None,session_id='session')
        self.assertEqual(self.owned.checkpoint.state['requests'],8)
        self.assertEqual(len(self.owned.checkpoint.state['validation_rejections']),8)
        self.assertEqual(self.effects,[]);self.assertEqual(self.holds,[])
    def test_validator_exception_invalid_verdict_mutation_never_dispatches(self):
        def raises(*args):raise RuntimeError('validator failed')
        def mutates(name,args):args['content']=json.dumps(REPORT);return Verdict(True)
        for callback in (raises,mutates,lambda *a:True,lambda *a:Verdict(1),lambda *a:Verdict(False,'')):
            with self.subTest(callback=callback):
                self.controller.fatal=None;self.controller.pre_effect_validator=callback
                call,args,result=self.proposal(WRONG)
                self.assertTrue(json.loads(result)['recovery_required']);self.assertIsNotNone(self.controller.fatal)
                self.assertEqual(self.effects,[]);self.assertEqual(json.loads(args['content']),WRONG)
                # This fixture stops after each fatal result; append it only so
                # the next independent fault injection has coherent native input.
                self.db.append({'role':'tool','tool_call_id':call,'content':result})
    def test_rejection_save_failure_never_dispatches_and_retains_operation(self):
        with mock.patch.object(self.owned,'complete_operation',side_effect=OSError('fixture commit failure')):
            call,args,result=self.proposal(WRONG)
        self.assertEqual(self.effects,[]);self.assertIsNotNone(self.owned.checkpoint.operation)
        with self.assertRaises(ReconciliationRequired):rec.resumable(self.owned,self.db,self.work)
    def test_rejection_begin_failure_never_dispatches(self):
        with mock.patch.object(self.owned,'begin_operation',side_effect=OSError('fixture begin failure')):
            call,args,result=self.proposal(WRONG)
        self.assertEqual(self.effects,[]);self.assertTrue(json.loads(result)['recovery_required'])
    def test_different_or_duplicate_native_result_does_not_validate(self):
        call,args,result=self.proposal(WRONG)
        self.db.append({'role':'tool','tool_call_id':call,'content':'changed'})
        with self.assertRaises(ReconciliationRequired):self.controller.control_safe_point()
        self.db.append({'role':'tool','tool_call_id':call,'content':result})
        with self.assertRaises(ReconciliationRequired):self.controller.control_safe_point()
        self.assertEqual(self.effects,[])
    def test_rejection_id_cannot_overlap_completed_tool(self):
        call,args,result=self.proposal(WRONG);self.flush(call,result)
        state=deepcopy(self.owned.checkpoint.state)
        state['tools'].append({'tool_call_id':call,'result':result})
        with self.assertRaises(ReconciliationRequired):
            rec.verify_validation_rows(rec.native_history(self.db,'session'),state,self.validator_id)
    def test_duplicate_accepted_write_keeps_original_no_dispatch_deduplication(self):
        call,args,result=self.proposal(REPORT);self.flush(call,result)
        call,args,result=self.proposal(REPORT);self.flush(call,result)
        self.assertEqual(len(self.effects),1)
        self.assertTrue(self.owned.checkpoint.state['tools'][-1]['reused'])
    def test_corrected_different_write_cannot_overwrite_accepted_artifact(self):
        call,args,result=self.proposal(REPORT);self.flush(call,result)
        call,args,result=self.proposal(WRONG)
        self.assertTrue(json.loads(result)['recovery_required']);self.assertEqual(len(self.effects),1)

class ValidatorTests(unittest.TestCase):
    def test_schema_and_arithmetic_regressions(self):
        check=validator(REPORT)
        for value in (WRONG,{**REPORT,'units':17.0},{**REPORT,'rows':True},
                {**REPORT,'extra':0},{**REPORT,'by_item':{'folder':1100}},
                '{"rows":4,"rows":4}',json.dumps(REPORT)+' trailing',
                json.dumps(REPORT).replace('4350','NaN')):
            content=value if isinstance(value,str) else json.dumps(value)
            with self.subTest(content=content):self.assertFalse(check('write_file',{'content':content}).accepted)
        self.assertTrue(check('write_file',{'content':json.dumps(REPORT)}).accepted)
    def test_default_none_behavior_and_version_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TaskStore(Path(tmp)/'task.sqlite3')
            cp=store.create('task',PROMPT,state=rec.initial_state(PROMPT,'session'))
            with store.claim('task',expected_revision=cp.revision) as owned:
                controller=rec.Recovery(owned,None,Path(tmp),Path(tmp))
                self.assertIsNone(controller.pre_effect_validator)
        self.assertNotEqual(identity(REPORT),identity(WRONG))

if __name__=='__main__':unittest.main()
