# SPDX-License-Identifier: Apache-2.0
"""Synthetic in-memory audit predicates only; never installed/model evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from checks import *


def fixture():
    effect={'name':'write_file','reused':False,'artifact_sha256':'a'*64,'tool_call_id':'tool1','result':'saved'}
    state={'status':'pending','phase':'ready','deadline_clock':CLOCK,'deadline_monotonic':1000.0,
        NS:{'state':'paused'},ACKS:{'receipts':[]},'requests':1,'attempts':1,'admission_attempts':1,
        'session_id':'same-session','native_history':[{'role':'tool','tool_call_id':'tool1','content':'saved'}],
        'tools':[effect]}
    paused={'task_id':'orders-report','prompt':'Original synthetic objective','max_attempts':8,'metadata':{'deadline_clock':CLOCK},
        'revision':1,'state':state,'operation':None,'requires_reconciliation':False,'owner_epoch':'old-owner'}
    marker={'deadline_clock':CLOCK,'deadline_monotonic':1000.0,'pause_observed_at_monotonic':500.0,
        'sealed_at_monotonic':1000.1,'pre_seal_revision':1,'pre_seal_state_sha256':digest(state)}
    old=deepcopy(paused);old['state'][SEAL]=marker;old.update(revision=2,owner_epoch=None)
    history=[[i,'event',json.dumps({'state':s})] for i,s in enumerate(({},state,old['state']))]
    wire={'model':MODEL,'quality':QUALITY,'class':'normal','method':'POST',
        'url':'http://127.0.0.1:18100/v1/chat/completions','started_at':10.0,'finished_at':11.0,'body_sha256':'b'*64}
    release={'worker_joined':True,'worker_pid':11,'exit_code':5,'outcome':'paused_budget_expired','execution_id':'orders-report'}
    payload={'logical_task_id':'orders-report','predecessor_id':'orders-report','predecessor_revision':2,
        'predecessor_seal_sha256':digest(marker),'successor_id':'orders-report.next','budget_s':900,
        'command_id':'continue1','host_generation':'same-host','release_evidence_sha256':digest(release),
        'demand_identity':{'registration_id':'new','task_id':'orders-report.next','owner_id':'owner','arrived_at_utc':'2026-10-26T00:00:00Z'}}
    pair={'execution_id':payload['successor_id'],'execution_generation':1}
    g={'payload':payload,'payload_sha256':digest(payload),'execution_generation':1,'authorized_at':1002.0,
        'deadline_monotonic':1902.0,'deadline_clock':CLOCK,'predecessor_state_sha256':digest(old['state']),
        'predecessor_history_sha256':digest(history),'release_proven_by_store':False,'wire_prefix_count':1,
        'wire_prefix_sha256':digest([wire]),'wire_row_sha256':[digest(wire)],'wire_body_sha256':[wire['body_sha256']]}
    newstate=deepcopy(state);newstate.pop(ACKS);newstate['deadline_monotonic']=1902.0
    newmeta={**old['metadata'],NS:payload['demand_identity'],LINK:{'logical_task_id':'orders-report',**pair,
        'command_id':'continue1','payload_sha256':g['payload_sha256']}}
    initial={**deepcopy(old),'task_id':payload['successor_id'],'revision':0,'state':newstate,'metadata':newmeta}
    g['successor_initial_state_sha256']=digest(newstate);g['successor_metadata_sha256']=digest(newmeta)
    selected=deepcopy(initial);selected['state'].update(status='accepted',phase='accepted',requests=2,attempts=2,admission_attempts=2)
    selected['state']['native_history'].append({'role':'assistant','content':'Done'})
    worker={'passed':True,'completed':True,'resumed':True,'continuation_cleanup_verified':True,
        'selected_execution':{**pair,'logical_task_id':'orders-report'},'fixture':False,
        'original_prompt_sha256':digest(old['prompt']),'provider_calls':1,'model':MODEL,'quality':QUALITY,
        'context':CONTEXT,'report':REPORT,'artifacts':{'report.json':'a'*64}}
    authority={'state':{AUTH:{'grants':[g],'execution_generation':1,'selected_execution':payload['successor_id']}},
        'owner_epoch':None,'operation':None,'requires_reconciliation':False}
    operation={'kind':'effect','details':{'schema':'adaptive.selected-worker-lifetime.v1',**pair,'payload_sha256':g['payload_sha256']}}
    proof={'execution_id':payload['successor_id'],'returncode':0,'result_sha256':'c'*64,'physical_child_exit_proven':False,
        'cleanup':{'resources_closed':True,'state_sha256':digest(selected['state']),'native_history_sha256':digest(selected['state']['native_history'])}}
    ah=[{'revision':2,'event':'operation_started','payload':{'operation':operation}},
        {'revision':3,'event':'operation_completed','payload':{'event_data':{'operation':operation,'result':proof}}}]
    suffix=g['payload_sha256'][:24]
    controls=[{'request_id':'continue-'+action+'-'+suffix,'command':action,'sequence':i,
        'outcome':'applied','owner_acknowledged':True} for i,action in enumerate(('pause','resume'),1)]
    transition={'request':{'request_id':'continue1','execution_id':'orders-report','execution_generation':0,
        'expected_task_revision':2,'session_id':'same-ui'},'committed':True,'started':True,'launch_attempted':True,'authorization_resolved':True,
        'release':release,'retained_child_identity':{'pid':12,'creation_time_100ns':200,'containing_job_verified':True}}
    return {'sealed_before':old,'sealed_after':deepcopy(old),'paused':paused,'history_before':history,'history_after':deepcopy(history),
        'grant':g,'selected':selected,'selected_initial':initial,'worker':worker,'authority':authority,'authority_history':ah,
        'wire_before':[wire],'wire_after':[wire,{**wire,'body_sha256':'d'*64,'started_at':1100.0,'finished_at':1101.0}],
        'effects':[effect],'effects_before_sha256':'e'*64,'effects_after_sha256':'e'*64,'report':REPORT,'report_sha256':'a'*64,
        'transition':transition,'gui_binding':{'session_id':'same-ui','host_epoch':'same-host'},'successor_controls':controls,
        'selection_status':{**pair,'task_revision':0,'task_status':'pending','demand':'paused','continuation':{'request_id':'continue1','phase':'preparing'}},
        'readiness':{'value':{'selected_execution':pair,'ready':True,'model':MODEL,'quality':QUALITY,'gateway_instance':'gateway1'},
            'deadline_clock':CLOCK,'started_qpc':1003.0,'finished_qpc':1004.0,
            'readiness_deadline_monotonic':1243.0,'gui_binding':{'session_id':'same-ui','host_epoch':'same-host'},
            'boot':{'task_id':payload['successor_id'],'deadline_monotonic':1902.0,'deadline_clock':CLOCK,'registration_id':'new'}},'gateway_instance':'gateway1',
        'worker_result_sha256':'c'*64,'lifetimes':[{'pid':11,'creation_time_100ns':100,'exit_code':5,'joined':True},{'pid':12,'creation_time_100ns':200,'exit_code':0,'joined':True}],
        'manual_stop_observed':True,'stop_confirmed':True,'lifecycle':{'worker_joined':True,'host_closed':True,'uncertain':False,'fault':None},
        'retained_obligations_joined':True,'joined_obligation_errors':[]}


class ContinuePredicates(unittest.TestCase):
    def rejected(self,mutate,message):
        value=fixture();mutate(value)
        with self.assertRaisesRegex(AssertionError,message):check_continuation(value)
    def test_reused_pid_keeps_distinct_retained_lifetimes(self):
        e=fixture();e['lifetimes'][1]['pid']=11;e['transition']['retained_child_identity']['pid']=11
        check_continuation(e)
    def test_same_retained_identity_rejected(self):
        def mutate(e):
            e['lifetimes'][1].update(pid=11,creation_time_100ns=100)
            e['transition']['retained_child_identity'].update(pid=11,creation_time_100ns=100)
        self.rejected(mutate,'two_actual_retained_joins')
    def test_unresolved_authorization_rejected(self):self.rejected(lambda e:e['transition'].update(authorization_resolved=False),'authenticated_one_click_selection')
    def test_recorded_readiness_deadline_enforced(self):self.rejected(lambda e:e['readiness'].update(readiness_deadline_monotonic=1003.5),'selected_readiness_exact')
    def test_positive_synthetic_chain(self):self.assertGreaterEqual(len(check_continuation(fixture())),20)
    def test_stale_grant_revision(self):self.rejected(lambda e:e['grant']['payload'].update(predecessor_revision=0),'one_exact_grant')
    def test_duplicate_physical_write(self):self.rejected(lambda e:e['effects'].append(deepcopy(e['effects'][0])),'one_unchanged_physical_effect')
    def test_shared_counter_reset(self):self.rejected(lambda e:e['selected']['state'].update(requests=1),'cumulative_wire_no_reset')
    def test_budget_over_eight(self):self.rejected(lambda e:e['wire_after'].extend([e['wire_after'][-1]]*7),'cumulative_wire_no_reset')
    def test_no_new_actual_request(self):self.rejected(lambda e:e.update(wire_after=e['wire_before']),'cumulative_wire_no_reset')
    def test_prior_wire_prefix_changed(self):self.rejected(lambda e:e['wire_after'].__setitem__(0,{**e['wire_after'][0],'body_sha256':'f'*64}),'cumulative_wire_no_reset')
    def test_predecessor_rewritten(self):self.rejected(lambda e:e['sealed_after']['state'].update(deadline_monotonic=1902.0),'immutable_predecessor')
    def test_missing_old_join(self):self.rejected(lambda e:e['lifetimes'][0].update(joined=False),'two_actual_retained_joins')
    def test_missing_new_join(self):self.rejected(lambda e:e['lifetimes'][1].update(joined=False),'two_actual_retained_joins')
    def test_missing_real_stop(self):self.rejected(lambda e:e.update(manual_stop_observed=False),'normal_final_stop')
    def test_uncertain_final_stop(self):self.rejected(lambda e:e['lifecycle'].update(uncertain=True),'normal_final_stop')
    def test_old_status_masquerading(self):self.rejected(lambda e:e['selection_status'].update(task_revision=2),'actual_selected_status')
    def test_stale_status_pair(self):self.rejected(lambda e:e['selection_status'].update(execution_generation=0),'actual_selected_status')
    def test_old_readiness(self):self.rejected(lambda e:e['readiness']['value'].update(selected_execution={'execution_id':'orders-report','execution_generation':0}),'selected_readiness_exact')
    def test_readiness_beyond240(self):self.rejected(lambda e:e['readiness'].update(finished_qpc=1244.0),'selected_readiness_exact')
    def test_repeated_resume(self):self.rejected(lambda e:e['successor_controls'].append(e['successor_controls'][1]),'fresh_pause_then_derived_resume')
    def test_lifetime_result_not_bound(self):self.rejected(lambda e:e.update(worker_result_sha256='f'*64),'completed_authority_binds_result')
    def test_missing_lifetime_completion(self):self.rejected(lambda e:e['authority_history'].pop(),'one_lifetime_completion')
    def test_duplicate_grant(self):self.rejected(lambda e:e['authority']['state'][AUTH]['grants'].append(e['grant']),'authority_selected_once')
    def test_new_prompt(self):self.rejected(lambda e:e['selected'].update(prompt='different goal'),'inherited_creation_exact')
    def test_changed_quality(self):self.rejected(lambda e:e['worker'].update(quality={**QUALITY,'max_tokens':1}),'quality_and_completed_requests')
    def test_missing_optional_feedback_is_valid(self):self.assertNotIn('validation_rejections',fixture()['selected']['state']);check_continuation(fixture())


class BindingChecks(unittest.TestCase):
    def test_disabled_template_cannot_launch(self):
        import bindings
        with self.assertRaisesRegex(ValueError,'disabled or incomplete'):
            bindings.load(Path(__file__).parent/'bindings.template.private.json')
    def test_duplicate_keys_rejected(self):
        import bindings
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'duplicate.json';path.write_text('{"enabled":true,"enabled":false}')
            with self.assertRaisesRegex(ValueError,'Duplicate JSON'):bindings.read(path)
    def test_nonfinite_rejected(self):
        import bindings
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'nan.json';path.write_text('{"value":NaN}')
            with self.assertRaisesRegex(ValueError,'Nonfinite'):bindings.read(path)


class UIObservationChecks(unittest.TestCase):
    def observations(self):
        from bindings import HERE,sha
        e=fixture();e['gui_binding']['hwnd']=42
        ui={'deadline_clock':CLOCK,'window_id':42,'first_resume_clicks':1,'manual_pause_clicks':1,
            'continue_clicks':1,'stop_clicks':1,'retry_clicks':0}
        for action,times in {'resume':(200.,201.),'pause':(500.,501.),'continue':(1001.9,1002.1),'stop':(1106.,1107.)}.items():
            for side,value in zip(('before','after'),times):
                ui[action+'_qpc_'+side]=value;ui[action+'_utc_'+side]='2026-10-26T00:00:00Z'
        ui['post_expiry_gui']={'deadline_clock':CLOCK,'hwnd':42,'same_window':True,'stop_available':True,
            'task_pending':True,'waiting_text':'This run budget ended; saved work preserved.',
            'qpc_before':1000.6,'qpc_after':1000.7}
        ui['post_continue_gui']={'deadline_clock':CLOCK,'hwnd':42,'same_window':True,'stop_available':True,
            'task_accepted':True,'task_text':'Task completed.','qpc_before':1104.,'qpc_after':1105.}
        trace=[{'deadline_clock':CLOCK,'reader_before_deadline_clock':a,'reader_after_deadline_clock':b,
                'gateway_status':{'instance':'gateway1'}} for a,b in ((1000.8,1000.9),(1102.,1103.))]
        observer={'source_unchanged':True,'source_sha256':sha(HERE/'observe_continue.py'),'deadline_clock':CLOCK,
            'task_completion_claimed':False,'active_case_file_contents_read':False,'samples':2,'valid_responses':2,
            'end_reason':'three_connection_errors_after_response'}
        result={'retained_gui_binding':e['gui_binding'],'expiry_service_observation_seconds':10.1}
        return e,result,{'at_deadline_clock':1000.5},ui,trace,observer
    def run_case(self,mutate=lambda values:None):
        from audit_continue import check_ui_and_observer
        values=self.observations();mutate(values);e,result,expiry,ui,trace,observer=values
        def data(path):return ui if Path(path).name=='ui-observations.private.json' else observer
        def check(name,value):require(bool(value),name)
        check_ui_and_observer(Path('synthetic-case'),e,result,expiry,data,lambda path:trace,check)
    def test_realistic_clock_scopes_with_inconclusive_observer_exit(self):self.run_case()
    def test_continue_before_saved_expiry_display_rejected(self):
        with self.assertRaisesRegex(AssertionError,'saved_then_selected_same_window'):
            self.run_case(lambda v:v[3].update(continue_qpc_before=1000.4))
    def test_old_completed_text_is_not_enough_on_other_window(self):
        with self.assertRaisesRegex(AssertionError,'saved_then_selected_same_window'):
            self.run_case(lambda v:v[3]['post_continue_gui'].update(hwnd=43))
    def test_runtime_selected_is_not_ui_task_completion(self):
        with self.assertRaisesRegex(AssertionError,'saved_then_selected_same_window'):
            self.run_case(lambda v:v[3]['post_continue_gui'].update(task_text='Task is in progress.'))
    def test_no_get_after_continue_rejected(self):
        with self.assertRaisesRegex(AssertionError,'observed_same_service_before_and_after_continue'):
            self.run_case(lambda v:v[4][1].update(reader_before_deadline_clock=1001.,reader_after_deadline_clock=1001.1))
    def test_ui_foreign_clock_rejected(self):
        with self.assertRaisesRegex(AssertionError,'resume_actual_clock_bracket'):
            self.run_case(lambda v:v[3].update(deadline_clock='local-monotonic'))


if __name__=='__main__':unittest.main()


class RetainedWaitCompatibility(unittest.TestCase):
    def test_only_retained_object_lookup_changes_expiry_verifier(self):
        import ast
        root=Path(__file__).parent
        def method(path,cls):
            source=path.read_text();tree=ast.parse(source)
            c=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name==cls)
            m=next(x for x in c.body if isinstance(x,ast.FunctionDef) and x.name=='verify_expired_progress')
            return '\n'.join(source.splitlines()[m.lineno-1:m.end_lineno])
        before=method(root.parents[2]/'provenance/explicit-continuation/qualification-predecessor/qualify.py','PausedExpiryQualification')
        after=method(root/'qualify_continue.py','ContinueQualification')
        self.assertEqual(before.count('self.waits.get(self.worker.pid)'),1)
        self.assertEqual(after,before.replace('self.waits.get(self.worker.pid)','self.waits.get(self.worker)'))
        self.assertNotIn('self.waits.get(child.pid)',(root/'qualify_continue.py').read_text())
