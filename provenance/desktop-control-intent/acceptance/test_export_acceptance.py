"""Small CPU-only selector mutations; fake rows reuse the historical fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

REPOSITORY=Path(__file__).resolve().parents[3]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
export=load('intent_export',Path(__file__).with_name('export_acceptance.py'))
prior,H=export.helpers(REPOSITORY)
fixtures=load('preserved_export_fixture',REPOSITORY/'provenance/installed-desktop/test_export_acceptance.py')


def cold_fixture():
    result,supervisor,audit,ui,identity=fixtures.fixture()
    supervisor['qualification_manifest']=export.QUALIFICATION
    result['source']['manifest_sha256']=export.QUALIFICATION
    audit['checks'].update(dict.fromkeys(('ui_single_click_controls','physical_status_overlap_not_claimed','actual_deployment_gate_bound'),True))
    ui={'case':'installed-ui-cold-02','pause_clicks':1,'stop_clicks':1,'resume_clicks':0,
        'retry_clicks':0,'minimize_or_restore_tested':False,'local_unsent_wait_state_seen':False,
        'engine_recording_and_owner_acknowledgement_are_separate':True,'observer_termination_proves_cleanup':False}
    return result,supervisor,audit,ui,identity


def full_fixture():
    result,supervisor,audit,_,identity=fixtures.full_fixture()
    supervisor['qualification_manifest']=export.QUALIFICATION
    result['source']['manifest_sha256']=export.QUALIFICATION
    required=(prior.FULL_CHECKS-{'missed_first_stop_click_preserved'})|export.FULL_ADDITIONAL_CHECKS
    audit['checks']=dict.fromkeys(required,True)
    for index,owner in enumerate(audit['native_owners'],1):
        audit['checks']['native_owner_'+owner['owner_id']]=audit['checks'].pop('native_owner_generation_'+str(index))
    audit['native_owners'][0]['retained_total']=8
    ui={'case':'installed-ui-full-02','first_resume_clicks':1,'replacement_resume_clicks':1,
        'stop_clicks':1,'manual_pause_clicks':0,'retry_clicks':0,
        'same_window_retained_across_worker_replacement':True,'local_unsent_wait_state_seen':False,
        'physical_click_status_overlap_established':False,'observer_termination_proves_cleanup':False,
        'performance_improvement_claimed':False}
    return result,supervisor,audit,ui,identity


class SelectionTests(unittest.TestCase):
    def select(self,args):return export.cold(H,prior,*args)

    def test_cold_selects_one_click_and_preserves_unobserved_overlap(self):
        value=self.select(cold_fixture())
        self.assertFalse(value['task_completed']);self.assertEqual(value['provider_calls'],0)
        self.assertEqual(value['ui_observation']['pause_clicks'],1)
        self.assertEqual(value['ui_observation']['stop_clicks'],1)
        self.assertFalse(value['ui_observation']['physical_status_overlap_established'])
        H.privacy_check(H.encoded(value))

    def test_cold_refuses_changed_click_counts_or_new_ui_claims(self):
        for key,value in (('pause_clicks',2),('stop_clicks',0),('stop_clicks',2),('resume_clicks',1),
            ('retry_clicks',1),('local_unsent_wait_state_seen',True),('minimize_or_restore_tested',True)):
            args=cold_fixture();args[3][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(H.Refused):self.select(args)

    def test_failed_parent_or_cleanup_never_becomes_acceptance(self):
        for key,value in (('exit_code',1),('timed_out',True),('emergency_termination_attempted',True),
            ('retained_case_handle_exited',False),('supervision_errors',['failed']),('elapsed_s',1800)):
            args=cold_fixture();args[1][key]=value
            with self.subTest(key=key),self.assertRaises(H.Refused):self.select(args)
        for section,key,value in (('gui_cleanup','pipe_handles_closed',False),
            ('listener_cleanup','handler_pending',True),('transport_cleanup','unknown_mutations',1),
            ('transport_cleanup','stop_confirmed',False),('cleanup','controller_fault','failed')):
            args=cold_fixture();args[0][section][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(H.Refused):self.select(args)

    def test_cold_work_or_completed_task_is_refused(self):
        for key,value in (('task_completed',True),('provider_calls',1),('dispatched_file_effects',1),
            ('native_launch_intent','started'),('no_resume',False),('worker_exit_code',0)):
            args=cold_fixture();args[0][key]=value
            with self.subTest(key=key),self.assertRaises(H.Refused):self.select(args)

    def test_partial_extra_or_failed_audit_is_refused(self):
        for change in ('missing','extra','false','not_passed'):
            args=cold_fixture()
            if change=='missing':args[2]['checks'].pop('ui_single_click_controls')
            elif change=='extra':args[2]['checks']['unreviewed']=True
            elif change=='false':args[2]['checks']['actual_parent_exit_zero']=False
            else:args[2]['passed']=False
            with self.subTest(change=change),self.assertRaises(H.Refused):self.select(args)

    def test_quality_budgets_and_qualifier_binding_stay_exact(self):
        args=cold_fixture();args[0]['quality']['max_tokens']-=1
        with self.assertRaises(H.Refused):self.select(args)
        for key,value in (('qualification_manifest',prior.QUALIFICATION_SHA),('task_deadline_s',901),('outer_deadline_s',1801)):
            args=cold_fixture();args[1][key]=value
            with self.subTest(key=key),self.assertRaises(H.Refused):self.select(args)

    def test_only_reviewed_client_may_differ_from_prior_52_modules(self):
        previous=H.parse((REPOSITORY/export.PREVIOUS_RESULT).read_bytes())
        current=deepcopy(previous['installed_package']);current['files']['desktop/control_client.py']=export.CLIENT
        value=export.source_identity(H,current,previous)
        self.assertEqual(value['other_runtime_modules_byte_identical'],51)
        for key in ('desktop/control_client.py','desktop/serial_listener.py'):
            changed=deepcopy(current);changed['files'][key]='0'*64
            with self.subTest(key=key),self.assertRaises(H.Refused):export.source_identity(H,changed,previous)
        changed=deepcopy(current);changed['files'].pop('desktop/run_gui.py')
        with self.assertRaises(H.Refused):export.source_identity(H,changed,previous)

    def test_actual_input_pin_changes_are_refused_by_strict_reader(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);path=root/'row.json';path.write_bytes(b'{"passed":true}')
            digest=H.hash_bytes(path.read_bytes())
            self.assertEqual(export.pinned(H,H.Inputs(root),'receipt',path,digest),{'passed':True})
            path.write_bytes(b'{"passed":false}')
            with self.assertRaises(H.Refused):export.pinned(H,H.Inputs(root),'receipt',path,digest)

    def test_wrong_wheel_refuses_before_any_other_receipt_is_read(self):
        with tempfile.TemporaryDirectory() as name:
            wheel=Path(name)/'wrong.whl';wheel.write_bytes(b'wrong wheel')
            with self.assertRaisesRegex(H.Refused,'^wheel_changed$'):
                export.build(H,prior,REPOSITORY,{'scope':'retained-intent-cold-full-02','wheel':wheel},H.Inputs(REPOSITORY))

    def test_private_unknown_fields_are_not_selected(self):
        args=cold_fixture();args[0].update(prompt='hidden-prompt',messages=['hidden-message'],path='C:/Users/private')
        args[3].update(window_id=555,observed_sequence=['private desktop path'])
        data=H.encoded(self.select(args));H.privacy_check(data)
        for forbidden in (b'hidden-',b'C:/Users',b'window_id',b'observed_sequence'):
            self.assertNotIn(forbidden,data)

    def test_boolean_integer_confusion_is_refused(self):
        args=cold_fixture();args[3]['pause_clicks']=True
        with self.assertRaises(H.Refused):self.select(args)
        args=cold_fixture();args[0]['provider_calls']=False
        with self.assertRaises(H.Refused):self.select(args)

    def test_full_preserves_actual_task_restart_native_counts_and_single_clicks(self):
        value=export.full(H,prior,*full_fixture())
        self.assertEqual(value['report'],H.REPORT);self.assertEqual(value['file_effects'],1)
        self.assertEqual(value['retained_native_children_per_generation'],[8,7])
        self.assertEqual(value['ui_observation']['stop_clicks'],1)
        self.assertFalse(value['performance_improvement_claimed'])
        H.privacy_check(H.encoded(value))

    def test_full_missing_or_failed_independent_check_is_refused(self):
        for change in ('missing','failed','not_passed'):
            args=full_fixture()
            if change=='missing':args[2]['checks'].pop('prior_missed_stop_case_preserved')
            elif change=='failed':args[2]['checks']['actual_database_matches_terminal_receipt']=False
            else:args[2]['passed']=False
            with self.subTest(change=change),self.assertRaises(H.Refused):export.full(H,prior,*args)

    def test_full_cannot_claim_old_click_count_or_physical_overlap_or_speed(self):
        for key,value in (('stop_clicks',2),('first_resume_clicks',2),('replacement_resume_clicks',0),
            ('physical_click_status_overlap_established',True),('local_unsent_wait_state_seen',True),
            ('performance_improvement_claimed',True)):
            args=full_fixture();args[3][key]=value
            with self.subTest(key=key),self.assertRaises(H.Refused):export.full(H,prior,*args)

    def test_full_original_report_effect_and_worker_identity_are_required(self):
        for key,value in (('provider_calls',4),('dispatched_file_effects',2),('worker_exit_code',1)):
            args=full_fixture();args[0][key]=value
            with self.subTest(key=key),self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[0]['report']['units']=19
        with self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[0]['injected_restart']['joined']=False
        with self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[0]['retained_worker_lifetimes'][1]['pid']=100
        with self.assertRaises(H.Refused):export.full(H,prior,*args)

    def test_full_does_not_reuse_predecessor_seven_plus_seven_native_count(self):
        args=full_fixture();args[2]['native_owners'][0]['retained_total']=7
        with self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[2]['native_owners'][1]['server_exit_code']=1
        with self.assertRaises(H.Refused):export.full(H,prior,*args)

    def test_full_ready_identity_and_cleanup_are_required(self):
        args=full_fixture();args[0]['cooperative_readiness_observations'][1]['worker_pid']=101
        with self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[0]['cooperative_readiness_observations'][0]['host_snapshot']['activity']['foreground']['pid']=999
        with self.assertRaises(H.Refused):export.full(H,prior,*args)
        args=full_fixture();args[0]['transport_cleanup']['unknown_mutations']=1
        with self.assertRaises(H.Refused):export.full(H,prior,*args)

    def test_observer_errors_never_prove_cleanup(self):
        row={'samples':418,'valid_responses':415,'consecutive_connection_errors':3,
            'end_reason':'three_connection_errors_after_response','source_unchanged':True,
            'active_case_file_contents_read':False,'task_completion_claimed':False}
        selected=export.observer(H,row,418,415)
        self.assertEqual(selected['classification'],'inconclusive')
        self.assertFalse(selected['cleanup_proven_by_observer'])
        row['task_completion_claimed']=True
        with self.assertRaises(H.Refused):export.observer(H,row,418,415)

    def test_prior_exporter_and_acceptance_bytes_remain_exact(self):
        self.assertEqual(H.hash_bytes((REPOSITORY/export.PREVIOUS_EXPORTER).read_bytes()),export.PREVIOUS_EXPORTER_SHA)
        self.assertEqual(H.hash_bytes((REPOSITORY/export.PREVIOUS_RESULT).read_bytes()),export.PREVIOUS_RESULT_SHA)


if __name__=='__main__':unittest.main(verbosity=2)
