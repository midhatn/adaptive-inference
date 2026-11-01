# SPDX-License-Identifier: Apache-2.0
"""Focused synthetic predicate coverage only; no SDK/native/UI/model imports."""
from copy import deepcopy
import base64,json,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from first_inflight import *

def observation(lo,hi):
    return {'deadline_clock':CLOCK,'qpc_before':float(lo),'qpc_after':float(hi),'utc_before':'2026-10-30T00:00:00+00:00','utc_after':'2026-10-30T00:00:01+00:00'}
def onset_fixture():
    binding={'pid':100,'hwnd':200,'host_epoch':'host','session_id':'gui','task_id':'task','creation_time_100ns':300}
    ui={'resume_a_qpc_before':100.,'resume_a_qpc_after':101.,'window_a':binding}
    phase={'phase':'inventory_paused_ready_for_resume','qpc':30.,'deadline_clock':CLOCK,'gui_binding':binding};raw=json.dumps(phase).encode()
    capture={'schema':'private.case09.pre-resume-ui-binding.v1','deadline_clock':CLOCK,'capture_qpc_before':50.,'capture_qpc_after':51.,'phase_raw_base64':base64.b64encode(raw).decode(),'phase_sha256':digest(raw),'observation':{**observation(40,41),'pid':100,'hwnd':200,'title':'Synthetic task','note':'Synthetic observed Pause/Resume window'}}
    activity={'schema':'private.case09.real-foreground.v1','deadline_clock':CLOCK,'document':{'pid':101,'hwnd':201,'title':'Synthetic document','path':'synthetic.txt'},'prepared_observation':{**observation(20,21),'note':'Synthetic prepared document'},'actions':[{**observation(200,201),'pid':101,'hwnd':201,'observed_before':'Synthetic page 1','action':'Read and PageDown','observed_after':'Synthetic page 2'},{**observation(230,231),'pid':101,'hwnd':201,'observed_before':'Synthetic page 2','action':'Read and PageDown','observed_after':'Synthetic page 3'}]}
    def row(t,active,count,admission,phase,reason):
        return {'deadline_clock':CLOCK,'reader_before_deadline_clock':float(t),'reader_after_deadline_clock':t+.1,'gateway_status':{'service':'adaptive-inference','instance':'a'*32,'scheduler':{'active':active,'completed':count,'pending':0,'backend_completion_uncertain':False,'closing':False},'resources':{'admission_allowed':admission,'handoff_state':phase,'foreground_reason':reason,'fault':None}}}
    trace=[row(198,True,0,True,'ready','cooperative_clear'),row(202,True,0,False,'draining','foreground_activity'),row(203,False,1,False,'parked','foreground_activity'),row(249,False,1,False,'parked','foreground_activity')]
    return [trace,ui,activity,capture,'a'*32,binding,250.]

def lineage_fixture():
    text=b'item,on_hand,target,pack_size\npens,3,10,4\n';prompt='Synthetic inventory task'
    user={'role':'user','content':prompt};call={'id':'read-1','call_id':'read-1','response_item_id':'fc-1','type':'function','function':{'name':'read_file','arguments':'{"path":"inventory.csv"}'}}
    assistant={'role':'assistant','content':'','reasoning':'synthetic','reasoning_content':'synthetic','finish_reason':'tool_calls','tool_calls':[call]}
    toolresult=json.dumps({'content':'1|item,on_hand,target,pack_size\n2|pens,3,10,4','file_size':len(text),'total_lines':2,'truncated':False,'is_binary':False,'is_image':False,'not_found':False})
    tool={'name':'read_file','args':{'path':'inventory.csv'},'tool_call_id':'read-1','session_id':'native-session','operation_id':'read-op','fingerprint':'f'*64,'result':toolresult,'reused':False}
    toolrow={'role':'tool','content':toolresult,'tool_call_id':'read-1','tool_name':'read_file'}
    initial={'model':'same-model','messages':[{'role':'system','content':'synthetic system'},user],'tools':[{'type':'function','function':{'name':'read_file'}}],'max_tokens':10923,'reasoning_effort':'high','timeout':1800,'extra_body':{'reasoning_budget_tokens':8192}}
    generation={'id':'generation-op','kind':'generation','details':{'request_sha256':digest(initial),'attempt_id':'one-attempt','pure_provider_request':True}}
    readop={'id':'read-op','kind':'validation','details':{k:tool[k] for k in ('name','tool_call_id','args','fingerprint','session_id')}}
    projection={k:deepcopy(assistant[k]) for k in ('role','content','reasoning','reasoning_content','tool_calls')};projection['tool_calls']=[{k:v for k,v in call.items() if k not in ('call_id','response_item_id')}]
    pending={**deepcopy(initial),'messages':deepcopy(initial['messages'])+[projection,{k:toolrow[k] for k in ('role','content','tool_call_id')}]}
    logical={'task_id':'task','prompt':prompt,'state':{'native_history':[],'tools':[],'requests':0,'messages':[user],'session_id':'native-session'}}
    state={'requests':1,'session_id':'native-session','native_history':[user,assistant,toolrow],'tools':[tool],'pending_request':pending,SEAL:{'pending_request_sha256':digest(pending)}}
    hist=[[1,'operation_started',json.dumps({'operation':generation,'state':{'pending_request':initial,'requests':0,'tools':[],'native_history':[user]}})],[2,'operation_completed',json.dumps({'event_data':{'operation':generation,'result':{'provider_returned':True}}})],[3,'operation_started',json.dumps({'operation':readop,'state':{}})],[4,'operation_completed',json.dumps({'event_data':{'operation':readop,'result':tool}})]]
    wire={'finish_reason':'tool_calls','body_sha256':'b'*64,'messages_sha256':digest(initial['messages']),'tools_sha256':digest(initial['tools']),'response_sha256':'c'*64,'assistant_sha256':'d'*64,'gateway_request_id':'gateway-first','started_at':10.,'finished_at':20.}
    recovery={'sealed_after':{'checkpoint':{'task_id':'task','prompt':prompt,'state':state},'worker':{'fixture':False,'provider_calls':1},'history':hist},'wire_before':[wire],'effects_before':[],'selected':{'state':{'tools':[tool,{'name':'write_file'}]}}}
    result={'fixture':False,'gateway_history':[{'request_id':'gateway-first','status':200,'backend_completion_uncertain':False}]}
    return [recovery,logical,result,'inventory.csv',text]

class OnsetTests(unittest.TestCase):
    def test_full_log_retains_straddling_and_postseal_actions(self):
        x=onset_fixture()
        for lo,hi in [(249,251),(280,281)]:
            a=deepcopy(x[2]['actions'][-1]);a.update(observation(lo,hi));x[2]['actions'].append(a)
        result=check_onset(*x)
        self.assertEqual((result['full_action_count'],result['preseal_action_count']),(4,2))
        self.assertEqual(len(x[2]['actions']),4)
    def test_straddler_cannot_cover_missing_preseal_hold(self):
        x=onset_fixture();x[2]['actions']=x[2]['actions'][:1];x[-1]=270.
        a=deepcopy(x[2]['actions'][0]);a.update(observation(269,271));x[2]['actions'].append(a)
        with self.assertRaisesRegex(ValueError,'real_activity_hold_gap'):check_onset(*x)
    def test_pre_action_admission_already_closed(self):
        x=onset_fixture();x[0][0]['gateway_status']['resources'].update(admission_allowed=False,handoff_state='draining',foreground_reason='foreground_activity')
        with self.assertRaisesRegex(ValueError,'pre_action_admission_must_be_open'):check_onset(*x)
    def test_terminal_auditor_refuses_unjoined_before_reading(self):
        from audit_first_inflight import audit
        with self.assertRaisesRegex(ValueError,'actual_retained_parent'):audit(Path('missing'),Path('missing'))
    def test_disabled_capture_refuses_before_clock_or_live_phase(self):
        from unittest.mock import patch
        from capture_binding import main
        args=['capture_binding.py','--bindings',str(Path(__file__).resolve().parent/'bindings.disabled.private.json'),'--observation','does-not-exist']
        with patch.object(sys,'argv',args):
            with self.assertRaisesRegex(ValueError,'Qualification bindings are disabled'):main()
    def test_observed_same_first_ticket(self):self.assertEqual(check_onset(*onset_fixture())['draining_index'],1)
    def test_missed_post_action_overlap(self):
        x=onset_fixture();x[0][1]['gateway_status']['scheduler'].update(active=False,completed=1)
        with self.assertRaises(ValueError):check_onset(*x)
    def test_ambiguous_clock_overlap(self):
        x=onset_fixture();x[2]['actions'][0]['qpc_after']=202.1
        with self.assertRaises(ValueError):check_onset(*x)
    def test_boolean_counter_rejected(self):
        x=onset_fixture();x[0][0]['gateway_status']['scheduler']['completed']=False
        with self.assertRaises(ValueError):check_onset(*x)
    def test_gateway_changed(self):
        x=onset_fixture();x[0][1]['gateway_status']['instance']='b'*32
        with self.assertRaises(ValueError):check_onset(*x)
    def test_unknown_or_closed_or_faulted(self):
        for branch,key,value in [('scheduler','backend_completion_uncertain',True),('scheduler','closing',True),('resources','fault','bad')]:
            with self.subTest(key=key):
                x=onset_fixture();x[0][1]['gateway_status'][branch][key]=value
                with self.assertRaises(ValueError):check_onset(*x)
    def test_other_pressure_cannot_substitute_foreground(self):
        x=onset_fixture();x[0][1]['gateway_status']['resources']['foreground_reason']='host_memory_pressure'
        with self.assertRaises(ValueError):check_onset(*x)
    def test_second_dispatch_during_hold(self):
        x=onset_fixture();x[0][2]['gateway_status']['scheduler']['active']=True
        with self.assertRaises(ValueError):check_onset(*x)
    def test_counter_replacement_inside_overlap(self):
        x=onset_fixture();row=deepcopy(x[0][0]);row.update(reader_before_deadline_clock=199.,reader_after_deadline_clock=199.1);row['gateway_status']['scheduler']['completed']=1;x[0].insert(1,row)
        with self.assertRaises(ValueError):check_onset(*x)
    def test_hold_requires_actual_repeated_action(self):
        x=onset_fixture();x[2]['actions']=x[2]['actions'][:1];x[-1]=270.
        with self.assertRaises(ValueError):check_onset(*x)
    def test_capture_cannot_be_retroactive_or_wrong_window(self):
        for key,value in [('capture_qpc_after',102.),('phase_sha256','e'*64)]:
            with self.subTest(key=key):
                x=onset_fixture();x[3][key]=value
                with self.assertRaises(ValueError):check_onset(*x)
        x=onset_fixture();x[3]['observation']['pid']=999
        with self.assertRaises(ValueError):check_onset(*x)
    def test_missing_action_refresh(self):
        x=onset_fixture();x[2]['actions'][0]['observed_after']=''
        with self.assertRaises(ValueError):check_onset(*x)

class LineageTests(unittest.TestCase):
    def test_boolean_initial_counter_rejected(self):
        x=lineage_fixture();x[1]['state']['requests']=False
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_one_generation_read_and_pending_projection(self):self.assertEqual(check_lineage(*lineage_fixture())['read_operation_id'],'read-op')
    def test_extra_wire(self):
        x=lineage_fixture();x[0]['wire_before']*=2
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_no_preexisting_assistant(self):
        x=lineage_fixture();x[1]['state']['native_history']=[{'role':'assistant','content':'old'}]
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_actual_native_read_cannot_be_omitted_or_faked(self):
        for kind in ('missing','wrong_result','truncated','wrong_argument','reused'):
            with self.subTest(kind=kind):
                x=lineage_fixture();s=x[0]['sealed_after']['checkpoint']['state']
                if kind=='missing':s['tools']=[]
                elif kind=='wrong_result':s['native_history'][2]['content']='different'
                elif kind=='truncated':p=json.loads(s['tools'][0]['result']);p['truncated']=True;s['tools'][0]['result']=json.dumps(p)
                elif kind=='wrong_argument':s['tools'][0]['args']={'path':'elsewhere.csv'}
                else:s['tools'][0]['reused']=True
                with self.assertRaises(ValueError):check_lineage(*x)
    def test_pending_read_projection_mismatch(self):
        x=lineage_fixture();x[0]['sealed_after']['checkpoint']['state']['pending_request']['messages'][-1]['content']='invented result'
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_pending_tool_id_or_reasoning_drift(self):
        for field in ('tool_calls','reasoning'):
            with self.subTest(field=field):
                x=lineage_fixture();msg=x[0]['sealed_after']['checkpoint']['state']['pending_request']['messages'][-2]
                if field=='tool_calls':msg[field][0]['id']='different'
                else:msg[field]='different'
                with self.assertRaises(ValueError):check_lineage(*x)
    def test_extra_generation_or_native_assistant(self):
        for target in ('generation','assistant'):
            with self.subTest(target=target):
                x=lineage_fixture()
                if target=='generation':x[0]['sealed_after']['history'].append(deepcopy(x[0]['sealed_after']['history'][0]))
                else:x[0]['sealed_after']['checkpoint']['state']['native_history'].append({'role':'assistant','content':'extra'})
                with self.assertRaises(ValueError):check_lineage(*x)
    def test_initial_request_wire_digest_mismatch(self):
        x=lineage_fixture();x[0]['wire_before'][0]['messages_sha256']='e'*64
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_fixture_or_gateway_mismatch(self):
        for key in ('fixture','gateway'):
            with self.subTest(key=key):
                x=lineage_fixture()
                if key=='fixture':x[2]['fixture']=True
                else:x[2]['gateway_history'][0]['request_id']='other'
                with self.assertRaises(ValueError):check_lineage(*x)
    def test_read_replay_cannot_manufacture_recovery(self):
        x=lineage_fixture();x[0]['selected']['state']['tools'].append({'name':'read_file'})
        with self.assertRaises(ValueError):check_lineage(*x)
    def test_preserve_request_options_and_pending_seal(self):
        for target in ('option','seal'):
            with self.subTest(target=target):
                x=lineage_fixture();s=x[0]['sealed_after']['checkpoint']['state']
                if target=='option':s['pending_request']['max_tokens']=10
                else:s[SEAL]['pending_request_sha256']='f'*64
                with self.assertRaises(ValueError):check_lineage(*x)
if __name__=='__main__':unittest.main(verbosity=2)
