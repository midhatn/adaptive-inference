"""Actual worker/Recovery/Provider control flow; scripted SDK, no transport/model."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import safe_wait_fixture as fixture
from adaptive_inference.desktop.hermes import admission, recovery as rec
from adaptive_inference.control_mailbox import EXECUTION_OUTCOME

EXPECT_SAFE_EXPIRY = True
EVIDENCE_ROOT = None

class PreBeginDeadlineEdges(unittest.TestCase):
    exercise = fixture.SafeWaitCases.exercise
    preserve = fixture.SafeWaitCases.preserve
    verify_exit = fixture.SafeWaitCases.verify_exit
    record = fixture.SafeWaitCases.record

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        fixture.OUTPUT = EVIDENCE_ROOT or Path(temporary.name).resolve()
        fixture.SafeWaitCases.setUp(self)
        self.edge_events=[]
        self.second_begins=0
        self.transport_entries=0

    def run_edge(self, edge):
        original_execute=admission.Provider.execute
        original_llm=rec.Recovery.llm
        outer=self
        saved_controls=[]
        def llm(controller,*args,**kwargs):
            try:return original_llm(controller,*args,**kwargs)
            finally:
                if saved_controls:
                    controller.controls=saved_controls.pop()
        def execute(provider,request,**callbacks):
            if not provider.boundary.rows:
                return original_execute(provider,request,**callbacks)
            actual_begin=callbacks['begin']
            def begin(attempt):
                outer.second_begins+=1
                value=actual_begin(attempt)
                outer.edge_events.append('begin_committed')
                return value
            callbacks['begin']=begin
            if edge in ('after_poll','without_controls'):
                actual_poll=callbacks['poll_control']
                def poll():
                    actual_poll()
                    outer.assertLess(outer.fixture.now,provider.deadline)
                    if edge=='without_controls':
                        saved_controls.append(rec.ACTIVE.controls)
                        rec.ACTIVE.controls=None
                    outer.fixture.now=provider.deadline
                    outer.edge_events.append('clock_crossed_after_poll')
                callbacks['poll_control']=poll
            elif edge in ('after_admitted','final_presend'):
                actual_status=provider.status_reader
                def status():
                    value=deepcopy(actual_status())
                    value['resources']['admission_allowed']=True
                    return value
                provider.status_reader=status
                if edge=='after_admitted':
                    actual_admitted=provider.admitted
                    def admitted():
                        value=actual_admitted()
                        outer.assertTrue(value)
                        outer.assertLess(outer.fixture.now,provider.deadline)
                        outer.fixture.now=provider.deadline
                        outer.edge_events.append('clock_crossed_after_admitted')
                        return value
                    provider.admitted=admitted
                else:
                    def create(**unused):
                        outer.transport_entries+=1
                        outer.assertIsNotNone(rec.ACTIVE.owned.checkpoint.operation)
                        outer.fixture.now=provider.deadline
                        outer.edge_events.append('clock_crossed_at_final_presend')
                        provider.inspect_request(SimpleNamespace(method='POST'))
                        raise AssertionError('Final pre-send must refuse')
                    provider.client.chat.completions.create=create
            elif edge=='generic_admission':
                def admitted():
                    raise admission.AdmissionStop('Gateway requires reconciliation')
                provider.admitted=admitted
            else:raise AssertionError(edge)
            return original_execute(provider,request,**callbacks)
        with mock.patch.object(admission.Provider,'execute',execute),mock.patch.object(rec.Recovery,'llm',llm):
            code=self.exercise('expiry')
        self.assertEqual(len(self.dispatched),1)
        self.assertEqual(self.cp.state['requests'],1)
        self.assertEqual(self.cp.state['attempts'],1)
        self.assertEqual(self.cp.state['pending_request'],self.pending)
        self.assertEqual(self.cp.state['native_history'],self.history)
        self.assertEqual(len(self.cp.state['tools']),1)
        self.assertEqual(self.cp.state['tools'][0]['name'],'read_file')
        self.assertIsNone(self.cp.owner_epoch)
        self.assertFalse((self.fixture.run/'work/report.json').exists())
        self.assertFalse((self.fixture.run/'effect-receipts.jsonl').exists())
        projection={'edge':edge,'returncode':code,'error_type':self.result.get('error_type'),
            'error_chain_types':self.result.get('error_chain_types'),'error':self.result.get('error'),
            'second_begin_calls':self.second_begins,'transport_entries':self.transport_entries,
            'completed_dispatches':len(self.dispatched),'phase':self.cp.state['phase'],
            'requires_reconciliation':self.cp.requires_reconciliation,'operation':self.cp.operation,
            'sealed':EXECUTION_OUTCOME in self.cp.state,'edge_events':self.edge_events,
            'pending_request_sha256':rec.digest(self.pending),'native_history_sha256':rec.digest(self.history)}
        (self.case/'edge.private.json').write_text(json.dumps(projection,indent=2)+'\n',encoding='utf-8')
        return code

    def safe_edge(self,edge):
        code=self.run_edge(edge)
        self.assertEqual(self.second_begins,0)
        self.assertEqual(self.transport_entries,0)
        self.assertIsNone(self.cp.operation)
        self.assertFalse(self.cp.requires_reconciliation)
        self.assertEqual(self.cp.state['phase'],'waiting_admission')
        self.assertEqual(self.cp.state['admission_attempts'],1)
        if EXPECT_SAFE_EXPIRY:
            self.assertEqual(code,6,self.result)
            self.assertIn('admission_wait_expiry',self.result)
            self.assertNotIn('error_type',self.result)
            self.assertEqual(self.verify_exit(6),'admission_wait_budget_expired')
        else:
            self.assertEqual(code,2,self.result)
            self.assertEqual(self.result['error_type'],'RecoveryStop')
            self.assertIn('AdmissionStop',self.result['error_chain_types'])
            self.assertNotIn(EXECUTION_OUTCOME,self.cp.state)
            with self.assertRaises(rec.RecoveryStop):self.verify_exit(2)

    def test_clock_crosses_after_control_poll_before_begin(self):
        self.safe_edge('after_poll')

    def test_clock_crosses_after_admitted_before_begin(self):
        self.safe_edge('after_admitted')

    def test_final_presend_stays_inflight_and_refused(self):
        self.assertEqual(self.run_edge('final_presend'),2,self.result)
        self.assertEqual(self.second_begins,1);self.assertEqual(self.transport_entries,1)
        self.assertIsNotNone(self.cp.operation);self.assertTrue(self.cp.requires_reconciliation)
        self.assertEqual(self.cp.state['phase'],'generating')
        self.assertEqual(self.cp.state['admission_attempts'],2)
        self.assertNotIn(EXECUTION_OUTCOME,self.cp.state)
        self.assertIn('AdmissionStop',self.result['error_chain_types'])
        with self.assertRaises(rec.RecoveryStop):self.verify_exit(2)

    def test_missing_controls_cannot_finalize_typed_wait(self):
        self.assertEqual(self.run_edge('without_controls'),2,self.result)
        self.assertEqual(self.second_begins,0);self.assertIsNone(self.cp.operation)
        self.assertEqual(self.result['error_type'],'RecoveryStop')
        self.assertNotIn(EXECUTION_OUTCOME,self.cp.state)
        self.assertNotIn('admission_wait_expiry',self.result)

    def test_generic_admission_error_cannot_become_expiry(self):
        self.assertEqual(self.run_edge('generic_admission'),2,self.result)
        self.assertEqual(self.second_begins,0);self.assertIsNone(self.cp.operation)
        self.assertEqual(self.result['error_type'],'RecoveryStop')
        self.assertIn('Gateway requires reconciliation',self.result['error'])
        self.assertNotIn(EXECUTION_OUTCOME,self.cp.state)
        self.assertNotIn('admission_wait_expiry',self.result)

