"""CPU-only selection/refusal tests; no private trial fixture is required."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('installed_export', Path(__file__).with_name('export_acceptance.py'))
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)
H = exporter.helper(REPOSITORY)


def fixture():
    identity = {'version': '0.3.0', 'files': {'desktop/example.py': 'a'*64}}
    supervisor = {'exit_code': 0, 'timed_out': False, 'emergency_termination_attempted': False,
        'retained_case_handle_exited': True, 'parent_source_unchanged': True,
        'supervision_error': None, 'supervision_errors': [], 'task_deadline_s': 900,
        'outer_deadline_s': 1800, 'qualification_manifest': exporter.QUALIFICATION_SHA,
        'parent_source_sha256_before': 'b'*64, 'parent_source_sha256_after': 'b'*64,
        'elapsed_s': 80}
    progress = {'policy_id': exporter.POLICY, 'bounds': deepcopy(exporter.BOUNDS),
        'totals': {'attempts': 0, 'successful_exchanges': 0, 'successful_pairs': 0,
          'max_observed_exchange_s': 0.0, 'max_successful_exchange_s': 0.0,
          'max_observed_arrival_gap_s': 0.0, 'max_observed_completed_age_s': 0.0},
        'invalidations': {'listener_closed': 3, 'progress_control_pending': 1}}
    gui = dict.fromkeys(('closed', 'session_revoked', 'pipe_threads_joined', 'pipe_handles_closed',
        'process_handle_closed', 'verifier_handle_closed', 'child_exit_observed'), True)
    gui.update(child_exit_code=0, pending_pipe_operations=0, faults=[])
    transport = {'closed': True, 'stop_requested': True, 'stop_confirmed': True, 'faults': []}
    transport.update(dict.fromkeys(('pending_mutations', 'unknown_mutations', 'handlers',
        'pending_connections', 'stream_close_failures'), 0))
    row = dict.fromkeys(('clean_stop', 'qualification_case_passed', 'case_checks_and_cleanup_passed',
        'asyncio_teardown_completed', 'manual_stop_observed', 'owner_released',
        'retained_obligations_joined', 'full_handoff_ledger', 'gui_pause_observed_before_stop'), True)
    row.update(model=H.MODEL, quality=deepcopy(H.QUALITY), fixture=False,
        live_M2_milestone_claimed=False, foreground_policy_id=exporter.POLICY,
        source={'manifest_sha256': exporter.QUALIFICATION_SHA, 'files': 5,
                'installed_package': deepcopy(identity)},
        lifecycle={'worker_joined': True, 'host_closed': True, 'uncertain': False, 'fault': None},
        gui_cleanup=gui, listener_cleanup={'clean_close': True, 'faults': [],
            'owned_connection_pending': False, 'setup_pending': False, 'handler_pending': False},
        transport_cleanup=transport, cleanup={'closed': True},
        cooperative_foreground_final=progress, case='cold-gui-installed-worker-stop',
        task_completed=False, provider_calls=0, dispatched_file_effects=0,
        native_launch_intent=None, no_resume=True, worker_exit_code=4,
        task_status='pending', demand_state='paused',
        controls=[{'sequence': i, 'command': 'pause', 'outcome': 'applied',
            'owner_acknowledged': True} for i in range(1, 4)])
    audit = {'passed': True, 'checks': dict.fromkeys(exporter.COLD_CHECKS, True)}
    ui = {'schema': 'adaptive.manual-ui-observations.v1', 'resume_performed': False,
          'taskbar_click_performed': False, 'restore_method': 'supported desktop window activation'}
    return row, supervisor, audit, ui, identity


def full_fixture():
    row, supervisor, _, _, identity = fixture()
    row.update(case='gui-iq3s-installed-worker-recovery', task_completed=True,
        provider_calls=3, dispatched_file_effects=1, worker_exit_code=0,
        worker_stop_outcome='task_completed', task_status='accepted',
        task_case_checks_passed=True, replacement_binding_committed=True,
        report=deepcopy(H.REPORT), report_sha256='1'*64, effect_receipts_sha256='2'*64,
        retained_prompt_sha256='3'*64, native_history_sha256='4'*64,
        controls=[{'sequence': i, 'request_id': str(i), 'command': command,
          'outcome': 'applied', 'owner_acknowledged': True}
          for i, command in enumerate(('pause', 'resume', 'pause', 'resume'), 1)],
        injected_restart={'pid': 100, 'exit_code': 1, 'joined': True,
                          'product_stop': False, 'safe_checkpoint_revision': 26},
        retained_worker_lifetimes=[{'pid': 100, 'exit_code': 1}, {'pid': 200, 'exit_code': 0}],
        runtime_binding={'enabled': True, 'generation': 2,
          'verified_owner_bindings': [{'generation': 1}, {'generation': 2}],
          'performance_claimed': False, 'cold_start_had_no_context': True},
        retained_gui_binding={'pid': 300, 'hwnd': 400, 'creation_time_100ns': 500})
    row['gui_resume_acknowledgements'] = [deepcopy(row['controls'][i]) for i in (1, 3)]
    observations = []
    for index in range(2):
        guard = deepcopy(row['cooperative_foreground_final'])
        guard.update(consecutive=2, completed={'intent_revision': index+1})
        guard['totals'].update(attempts=10, successful_exchanges=10, successful_pairs=9)
        observations.append({'admission_observed': True, 'worker_live': True,
            'worker_pid': row['retained_worker_lifetimes'][index]['pid'], 'intent_revision': index+1,
            'host_snapshot': {'controller': {'handoff_state': 'ready', 'admission_allowed': True,
                'foreground_reason': 'cooperative_clear', 'fault': None},
                'activity': {'errors': [], 'foreground': dict(row['retained_gui_binding'],
                    valid=True, cpu_cores_used=.046, cpu_window_s=1.016),
                    'host': {'cpu_busy_fraction': .1, 'ram_available_gib': 12,
                             'commit_available_gib': 37}}, 'cooperative_foreground': guard}})
    row['cooperative_readiness_observations'] = observations
    audit = {'passed': True, 'checks': {'fixture_terminal_audit': True,
        'native_owner_a': True, 'native_owner_b': True}, 'validation_rejection_count': 0,
        'native_owners': [{'owner_id': name, 'retained_total': 7, 'server_exit_code': 0}
                          for name in ('a', 'b')]}
    ui = {'schema': 'adaptive.manual-ui-observations.v1', 'resume_click_attempts': 2,
          'stop_click_attempts': 2, 'first_stop_click_registered_in_ui': False}
    return row, supervisor, audit, ui, identity


class InstalledSelectionTests(unittest.TestCase):
    def full_selection(self, args):
        with patch.object(exporter, 'FULL_CHECKS', frozenset(['fixture_terminal_audit',
                'native_owner_generation_1', 'native_owner_generation_2'])):
            return exporter.full(H, *args)

    def test_full_preserves_correct_report_worker_restart_and_missed_stop(self):
        value = self.full_selection(full_fixture())
        self.assertEqual(value['report'], H.REPORT)
        self.assertEqual(value['worker_restart']['original_exit_code'], 1)
        self.assertEqual(value['ui_observation']['stop_click_attempts'], 2)
        self.assertFalse(value['ui_observation']['first_stop_click_registered_in_ui'])
        self.assertEqual(value['observed_readiness'][0]['foreground_cpu_cores'], .046)
        H.privacy_check(H.encoded(value))

    def test_full_requires_its_independent_audit_selection(self):
        with patch.object(exporter, 'FULL_CHECKS', frozenset()), self.assertRaises(H.Refused):
            exporter.full(H, *full_fixture())
        args = full_fixture(); args[2]['passed'] = False
        with self.assertRaises(H.Refused): self.full_selection(args)

    def test_full_cannot_hide_missed_first_stop(self):
        for key, value in [('stop_click_attempts', 1), ('first_stop_click_registered_in_ui', True)]:
            args = full_fixture(); args[3][key] = value
            with self.subTest(key=key), self.assertRaises(H.Refused): self.full_selection(args)

    def test_full_arithmetic_and_single_effect_oracle_are_preserved(self):
        for field, value in [('provider_calls', 4), ('dispatched_file_effects', 2),
                             ('task_status', 'pending')]:
            args = full_fixture(); args[0][field] = value
            with self.subTest(field=field), self.assertRaises(H.Refused): self.full_selection(args)
        args = full_fixture(); args[0]['report']['units'] = 19
        with self.assertRaises(H.Refused): self.full_selection(args)

    def test_full_rejects_wrong_worker_or_foreground_or_generation(self):
        for key, value in [('worker_pid', 101), ('intent_revision', 999), ('admission_observed', False)]:
            args = full_fixture(); args[0]['cooperative_readiness_observations'][0][key] = value
            with self.subTest(key=key), self.assertRaises(H.Refused): self.full_selection(args)
        args = full_fixture()
        args[0]['cooperative_readiness_observations'][0]['host_snapshot']['activity']['foreground']['pid'] = 999
        with self.assertRaises(H.Refused): self.full_selection(args)

    def test_full_raw_private_fields_and_timing_events_are_not_exported(self):
        args = full_fixture(); args[0].update(messages=['secret'], prompt='secret prompt')
        args[0]['cooperative_foreground_final']['events'] = [{'pid': 999, 'prompt': 'secret'}]
        data = H.encoded(self.full_selection(args))
        H.privacy_check(data)
        self.assertNotIn(b'secret', data)

    def test_cold_remains_unfinished_with_zero_work(self):
        value = exporter.cold(H, *fixture())
        self.assertFalse(value['task_completed'])
        self.assertEqual(value['provider_calls'], 0)
        self.assertEqual(value['worker_exit_code'], 4)
        self.assertFalse(value['ui_observation']['actual_window_destroy_reopen_tested'])
        H.privacy_check(H.encoded(value))

    def test_parent_timeout_or_emergency_cannot_supply_acceptance(self):
        for field, value in [('exit_code', 124), ('timed_out', True),
                             ('emergency_termination_attempted', True),
                             ('retained_case_handle_exited', False), ('elapsed_s', 1800)]:
            with self.subTest(field=field):
                args = fixture(); args[1][field] = value
                with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_missing_false_or_extra_audit_check_is_refused(self):
        for operation in ('missing', 'false', 'extra'):
            args = fixture(); rows = args[2]['checks']
            if operation == 'missing': rows.pop('actual_parent_exit_zero')
            elif operation == 'false': rows['actual_parent_exit_zero'] = False
            else: rows['invented_check'] = True
            with self.subTest(operation=operation), self.assertRaises(H.Refused):
                exporter.cold(H, *args)

    def test_boolean_cannot_stand_in_for_zero_or_integer(self):
        args = fixture(); args[0]['provider_calls'] = False
        with self.assertRaises(H.Refused): exporter.cold(H, *args)
        with self.assertRaises(H.Refused): H.integer(True)

    def test_unfinished_cold_task_cannot_be_marked_completed(self):
        args = fixture(); args[0]['task_completed'] = True
        with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_any_inference_effect_or_resume_refuses_cold(self):
        for field, value in [('provider_calls', 1), ('dispatched_file_effects', 1),
                             ('native_launch_intent', 'started'), ('no_resume', False)]:
            args = fixture(); args[0][field] = value
            with self.subTest(field=field), self.assertRaises(H.Refused):
                exporter.cold(H, *args)
        args = fixture(); args[0]['controls'][1]['command'] = 'resume'
        with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_cleanup_faults_or_pending_work_are_refused(self):
        for section, field, value in [('gui_cleanup', 'faults', ['close_failed']),
                ('listener_cleanup', 'handler_pending', True),
                ('transport_cleanup', 'unknown_mutations', 1),
                ('cleanup', 'controller_fault', 'failed')]:
            args = fixture(); args[0][section][field] = value
            with self.subTest(section=section), self.assertRaises(H.Refused):
                exporter.cold(H, *args)

    def test_model_quality_policy_and_original_budgets_are_exact(self):
        args = fixture(); args[0]['quality']['max_tokens'] -= 1
        with self.assertRaises(H.Refused): exporter.cold(H, *args)
        args = fixture(); args[0]['foreground_policy_id'] = 'another-policy'
        with self.assertRaises(H.Refused): exporter.cold(H, *args)
        args = fixture(); args[1]['task_deadline_s'] = 901
        with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_installed_source_mismatch_is_refused(self):
        args = fixture(); args[0]['source']['installed_package']['files']['desktop/example.py'] = 'c'*64
        with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_raw_unknown_fields_do_not_leak(self):
        args = fixture()
        args[0].update(prompt='private text', messages=[{'content': 'secret'}],
                       api_key='secret-token', pid=1234, hwnd=5678, run='C:\\private\\path')
        value = H.encoded(exporter.cold(H, *args))
        H.privacy_check(value)
        self.assertNotIn(b'secret', value)
        self.assertNotIn(b'private text', value)

    def test_changed_policy_bounds_and_nonfinite_values_refuse(self):
        args = fixture(); args[0]['cooperative_foreground_final']['bounds']['recovery_s'] = 1
        with self.assertRaises(H.Refused): exporter.cold(H, *args)
        args = fixture(); args[0]['cooperative_foreground_final']['totals']['max_observed_exchange_s'] = float('nan')
        with self.assertRaises(H.Refused): exporter.cold(H, *args)

    def test_original_strict_parser_rejects_duplicate_or_nonfinite_json(self):
        for data in ('{"passed":true,"passed":false}', '{"duration":NaN}'):
            with self.subTest(data=data), self.assertRaises(H.Refused): H.parse(data)

    def test_privacy_checker_retains_original_refusals(self):
        for data in (b'{"prompt":"x"}', b'{"root":"C:/Users/private"}',
                     b'{"pid":123}', b'{"messages":[]}'):
            with self.subTest(data=data), self.assertRaises(H.Refused): H.privacy_check(data)

    def test_minimize_does_not_turn_into_taskbar_or_reopen_claim(self):
        args = fixture(); args[3]['taskbar_click_performed'] = True
        with self.assertRaises(H.Refused): exporter.cold(H, *args)


if __name__ == '__main__':
    unittest.main()
