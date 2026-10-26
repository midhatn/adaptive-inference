# SPDX-License-Identifier: Apache-2.0
"""Select terminal installed-desktop evidence into a NEW private directory.

Reuses the unchanged controlled-11/v7 exporter's bounded strict-JSON reader,
type checks, hashes, encoder and privacy checker. Historical build()/pins are
not reused or modified: this selection binds the installed qualification.
No runtime modules, models, databases, UI automation or network are executed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

HELPER_RELATIVE = 'provenance/windows-handoff/sanitizer/sanitize_milestone_v7.py'
HELPER_SHA = '12004621166522cb80682e2bf1e4bc6d19e2ca72aeb585d21ce6408c2a965b33'
WHEEL_SHA = 'c3f85f7d4b5047a170c2ee8f4fd14111bb902cff9951c9bbb53e9a787ae3a99a'
QUALIFICATION_SHA = 'ebb7582477b901058e0840cd20a2f7d9c815bcd6af74e024cae46fd08e4ad06e'
QUALIFIER_SHA = 'f84c7894699d70b3f902df2dd7691e0f2242fab80c7e9767ef9eb98bca628a98'
COLD_AUDIT_SHA = 'ba0d07616d49139af15c23d4e014c7dfc99639f250c64e2de19e7798266797f6'
FULL_AUDIT_SHA = '5c3717b55730130da1f82a97d00c17cc0f889d4bb60b043fe9eb3a3129723848'
FULL_CHECKS = frozenset('task_db_integrity actual_database_matches_terminal_receipt accepted_task_all_owners_released original_task_metadata_messages_deadline validator_identity_unchanged_across_owners paused_replacement_state_exact checkpoint_files_match_actual_revision_history preserved_native_prefix_and_tools csv_oracle_original_and_written_report one_unchanged_actual_file_effect completed_tool_results_exact wire_prefix_and_three_real_quality_preserved_calls no_real_model_feedback_correction_claim replacement_worker_completed_original_context native_db_integrity actual_native_rows_equal_durable_checkpoint exact_control_ledger controlled_retained_replacement_not_product_stop two_exact_readiness_receipts readiness1_current_identity_admission readiness1_positive_pairs_and_fresh_bounds readiness1_unchanged240bound readiness2_current_identity_admission readiness2_positive_pairs_and_fresh_bounds readiness2_unchanged240bound readiness_generations_distinct two_owner_runtime_generations_three_correlated_requests full_handoff_ledger native_owner_generation_1 native_owner_generation_2 host_native_cleanup_views completed_excluded_from_effective_demand normal_stop_completed_task gui_owned_cleanup listener_transport_closure retained_children_joined_job_empty parent_normal_exit_no_emergency case_pass_scope installed52identity_and_current_bytes qualification_source5_exact profile_parent_exact sdk14_and_prepared_input_pins postcleanup_progress_snapshot_without_error full_and_public_ledger_views_consistent observer_inconclusive_preserved missed_first_stop_click_preserved all_inputs_unchanged'.split())
PROFILE_SHA = '849f392cde67e0a20dddadd375aa084e659625a00d41f86bd06947067356b931'
POLICY = 'cooperative-owned-foreground.v1'
BOUNDS = {'exchange_max_s': .5, 'next_arrival_max_s': 2.5,
          'completion_max_age_s': 2.5, 'required_consecutive': 2,
          'host_cpu_clear_fraction': .8, 'host_cpu_busy_fraction': .95,
          'activity_max_age_s': 1, 'memory_min_gib': 4,
          'recovery_s': 5, 'busy_samples': 2}
COLD_CHECKS = frozenset('sqlite_integrity actual_sqlite_matches_terminal original_objective_and_quality unchanged_messages zero_work_state owner_released_pending_paused unchanged_task_budget deadline_exact_launch_plus900 exact_three_pause_requests_no_resume actual_owner_ack_ledger gui_pause_origin_ack stop_receipt_exact_checkpoint worker_stopped_not_completed no_effect_provider_report_artifacts native_history_empty native_never_launched full_handoff_ledger_no_restore native_cleanup_clean lifecycle_exact gui_exit_and_revoked_joined listener_closed_no_pending transport_stop_confirmed_clean retained_processes_exited_no_emergency actual_parent_exit_zero qualification_pass_scoped profile_and_worker_current package52_equal_frozenwheel host_worker_current_sources_unchanged qualification_source5_exact parent_exact_before_after cold_diagnostics_zero_positive_pairs cold_diagnostics_no_failures ui_observation_same_owned_window observer_scoped_inconclusive terminal_case_files_unchanged'.split())


def helper(repository):
    path = Path(repository).resolve(strict=True)/HELPER_RELATIVE
    if hashlib.sha256(path.read_bytes()).hexdigest() != HELPER_SHA:
        raise ValueError('Historical helper changed')
    spec = importlib.util.spec_from_file_location('installed_evidence_v7_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checks(h, audit, required):
    h.true(audit.get('passed'), 'independent_audit_not_passed')
    rows = audit.get('checks')
    h.need(type(rows) is dict and set(rows) == required, 'independent_audit_selection_changed')
    for key, value in rows.items():
        h.identifier(key)
        h.true(value, 'independent_check_failed')
    return {key: True for key in sorted(rows)}


def parent(h, row):
    h.exact(row.get('exit_code'), 0, 'parent_nonzero_exit')
    for key in ('timed_out', 'emergency_termination_attempted'):
        h.exact(row.get(key), False, 'parent_emergency_or_timeout')
    for key in ('retained_case_handle_exited', 'parent_source_unchanged'):
        h.true(row.get(key), 'parent_unjoined_or_changed')
    h.exact(row.get('supervision_error'), None, 'parent_error')
    h.exact(row.get('supervision_errors'), [], 'parent_errors')
    h.exact(row.get('task_deadline_s'), 900, 'task_budget_changed')
    h.exact(row.get('outer_deadline_s'), 1800, 'outer_budget_changed')
    h.exact(row.get('qualification_manifest'), QUALIFICATION_SHA, 'parent_qualification_changed')
    before = h.digest(row.get('parent_source_sha256_before'))
    h.exact(row.get('parent_source_sha256_after'), before, 'parent_source_changed')
    elapsed = h.number(row.get('elapsed_s'))
    h.need(elapsed < 1800, 'parent_elapsed_exceeds_bound')
    return {'exit_code': 0, 'retained_handle_exited': True, 'emergency_termination': False,
            'elapsed_s': elapsed, 'parent_source_sha256': before}


def progress(h, row):
    h.exact(row.get('policy_id'), POLICY, 'progress_policy_changed')
    h.exact(row.get('bounds'), BOUNDS, 'progress_bounds_changed')
    totals = row['totals']
    count_names = ('attempts', 'successful_exchanges', 'successful_pairs')
    time_names = ('max_observed_exchange_s', 'max_successful_exchange_s',
                  'max_observed_arrival_gap_s', 'max_observed_completed_age_s')
    h.need(set(totals) == set(count_names+time_names), 'progress_totals_changed')
    selected = {name: h.integer(totals[name]) for name in count_names}
    selected.update({name: h.number(totals[name]) for name in time_names})
    invalidations = {h.identifier(name): h.integer(value) for name, value in row['invalidations'].items()}
    return {'policy_id': POLICY, 'bounds': BOUNDS, 'totals': selected,
            'invalidations': invalidations,
            'scope': 'Host lifetime totals, including commanded resets; not UI or GPU latency'}


def clean_case(h, result, supervisor, identity):
    h.quality(result)
    for key in ('clean_stop', 'qualification_case_passed', 'case_checks_and_cleanup_passed',
                'asyncio_teardown_completed', 'manual_stop_observed', 'owner_released',
                'retained_obligations_joined', 'full_handoff_ledger'):
        h.true(result.get(key), 'case_or_cleanup_not_passed')
    h.exact(result.get('fixture'), False, 'fixture_not_live')
    h.exact(result.get('live_M2_milestone_claimed'), False, 'scope_changed')
    h.exact(result.get('foreground_policy_id'), POLICY, 'policy_changed')
    h.exact(result.get('source'), {'manifest_sha256': QUALIFICATION_SHA,
                                 'files': 5, 'installed_package': identity}, 'case_source_changed')
    h.exact(result.get('lifecycle'), {'worker_joined': True, 'host_closed': True,
                                    'uncertain': False, 'fault': None}, 'lifecycle_not_clean')
    for key in ('primary_error', 'cleanup_error', 'cooperative_diagnostic_error'):
        h.need(result.get(key) is None, 'case_error')
    h.need(not result.get('joined_obligation_errors'), 'obligation_error')
    gui = result['gui_cleanup']
    for key in ('closed', 'session_revoked', 'pipe_threads_joined', 'pipe_handles_closed',
                'process_handle_closed', 'verifier_handle_closed', 'child_exit_observed'):
        h.true(gui.get(key), 'gui_cleanup_incomplete')
    h.exact(gui.get('child_exit_code'), 0, 'gui_nonzero_exit')
    h.exact(gui.get('pending_pipe_operations'), 0, 'gui_pipe_pending')
    h.exact(gui.get('faults'), [], 'gui_fault')
    listener, transport, native = (result[k] for k in ('listener_cleanup', 'transport_cleanup', 'cleanup'))
    h.true(listener.get('clean_close'), 'listener_not_closed')
    h.exact(listener.get('faults'), [], 'listener_fault')
    for key in ('owned_connection_pending', 'setup_pending', 'handler_pending'):
        h.exact(listener.get(key), False, 'listener_work_pending')
    for key in ('closed', 'stop_requested', 'stop_confirmed'):
        h.true(transport.get(key), 'transport_not_closed')
    for key in ('pending_mutations', 'unknown_mutations', 'handlers', 'pending_connections', 'stream_close_failures'):
        h.exact(transport.get(key), 0, 'transport_work_or_fault_pending')
    h.exact(transport.get('faults'), [], 'transport_fault')
    h.true(native.get('closed'), 'native_not_closed')
    for key in ('primary_error', 'cleanup_error', 'controller_fault'):
        h.need(native.get(key) is None, 'native_fault')
    return {'passed': True, 'supervisor': parent(h, supervisor),
            'cleanup': {'worker_joined': True, 'native_closed': True, 'gui_closed': True,
                        'listener_closed': True, 'transport_closed': True,
                        'retained_obligations_joined': True, 'uncertainty': False},
            'control_progress': progress(h, result['cooperative_foreground_final'])}


def cold(h, result, supervisor, audit, ui, identity):
    selected = clean_case(h, result, supervisor, identity)
    selected['independent_checks'] = checks(h, audit, COLD_CHECKS)
    h.exact(result.get('case'), 'cold-gui-installed-worker-stop', 'cold_case_changed')
    for key, expected in (('task_completed', False), ('provider_calls', 0),
            ('dispatched_file_effects', 0), ('native_launch_intent', None),
            ('no_resume', True), ('worker_exit_code', 4),
            ('task_status', 'pending'), ('demand_state', 'paused')):
        h.exact(result.get(key), expected, 'cold_work_or_outcome_changed')
    h.true(result.get('gui_pause_observed_before_stop'), 'gui_pause_missing')
    rows = result.get('controls')
    h.need(type(rows) is list and len(rows) == 3, 'cold_control_count_changed')
    for sequence, row in enumerate(rows, 1):
        h.exact(row.get('sequence'), sequence, 'control_order_changed')
        h.exact(row.get('command'), 'pause', 'cold_resume_or_other_control')
        h.exact(row.get('outcome'), 'applied', 'control_not_applied')
        h.true(row.get('owner_acknowledged'), 'owner_ack_missing')
    h.exact(ui.get('schema'), 'adaptive.manual-ui-observations.v1', 'ui_observation_schema')
    h.exact(ui.get('resume_performed'), False, 'ui_resume_observed')
    h.exact(ui.get('taskbar_click_performed'), False, 'ui_restore_method_changed')
    h.exact(ui.get('restore_method'), 'supported desktop window activation', 'ui_restore_method_changed')
    h.exact(selected['control_progress']['totals']['successful_pairs'], 0, 'cold_admission_claim')
    selected.update(provider_calls=0, file_effects=0, native_launches=0,
        task_completed=False, task_state='pending_paused', worker_exit_code=4,
        acknowledged_pause_commands=3,
        ui_observation={'title_bar_close_minimized': True, 'same_window_restored': True,
            'restore_method': 'supported desktop window activation', 'taskbar_click_tested': False,
            'actual_window_destroy_reopen_tested': False},
        scope='Installed model-free Pause/Stop and observed same-window minimize/restore; no admission or inference proof')
    return selected


def full(h, result, supervisor, audit, ui, identity):
    selected = clean_case(h, result, supervisor, identity)
    h.need(bool(FULL_CHECKS), 'full_audit_selection_not_bound')
    audit_checks = dict(audit['checks'])
    h.exact(len(audit['native_owners']), 2, 'native_owner_count_changed')
    for index, owner in enumerate(audit['native_owners'], 1):
        audit_checks['native_owner_generation_'+str(index)] = audit_checks.pop('native_owner_'+owner['owner_id'])
        h.exact(owner['retained_total'], 7, 'native_retained_count_changed')
        h.exact(owner['server_exit_code'], 0, 'native_server_failed')
    selected['independent_checks'] = checks(h, dict(audit, checks=audit_checks), FULL_CHECKS)
    h.exact(audit.get('validation_rejection_count'), 0, 'real_feedback_scope_changed')
    h.exact(result.get('case'), 'gui-iq3s-installed-worker-recovery', 'full_case_changed')
    for key, expected in (('task_completed', True), ('provider_calls', 3),
            ('dispatched_file_effects', 1), ('worker_exit_code', 0),
            ('worker_stop_outcome', 'task_completed'), ('task_status', 'accepted'),
            ('task_case_checks_passed', True), ('replacement_binding_committed', True)):
        h.exact(result.get(key), expected, 'full_work_or_outcome_changed')
    h.exact(result.get('report'), h.REPORT, 'report_oracle_mismatch')
    rows = result.get('controls')
    h.need(type(rows) is list and len(rows) == 4, 'full_control_count_changed')
    for sequence, (row, command) in enumerate(zip(rows, ('pause', 'resume', 'pause', 'resume')), 1):
        h.exact(row.get('sequence'), sequence, 'control_order_changed')
        h.exact(row.get('command'), command, 'full_control_changed')
        h.exact(row.get('outcome'), 'applied', 'control_not_applied')
        h.true(row.get('owner_acknowledged'), 'owner_ack_missing')
    acknowledgements = result['gui_resume_acknowledgements']
    h.exact([row.get('sequence') for row in acknowledgements], [2, 4], 'gui_resume_missing')
    for row, control in zip(acknowledgements, (rows[1], rows[3])):
        for key in ('sequence', 'request_id', 'command', 'outcome', 'owner_acknowledged'):
            h.exact(row.get(key), control[key], 'gui_resume_ack_mismatch')
    restart = result['injected_restart']
    h.exact(restart.get('exit_code'), 1, 'injected_restart_outcome_changed')
    h.true(restart.get('joined'), 'original_worker_unjoined')
    h.exact(restart.get('product_stop'), False, 'restart_was_product_stop')
    lifetimes = result['retained_worker_lifetimes']
    h.exact([row.get('exit_code') for row in lifetimes], [1, 0], 'worker_lifetimes_changed')
    h.need(lifetimes[0]['pid'] == restart['pid'] and lifetimes[0]['pid'] != lifetimes[1]['pid'],
           'worker_replacement_identity_mismatch')
    binding = result['runtime_binding']
    h.true(binding.get('enabled'), 'runtime_binding_disabled')
    h.exact(binding.get('generation'), 2, 'owner_generation_changed')
    h.exact([row['generation'] for row in binding['verified_owner_bindings']], [1, 2],
            'owner_bindings_changed')
    h.exact(binding.get('performance_claimed'), False, 'performance_scope_changed')
    h.true(binding.get('cold_start_had_no_context'), 'cold_runtime_scope_changed')
    readiness = []
    observations = result['cooperative_readiness_observations']
    h.exact(len(observations), 2, 'readiness_count_changed')
    for index, row in enumerate(observations):
        h.true(row.get('admission_observed'), 'ready_admission_unobserved')
        h.true(row.get('worker_live'), 'ready_worker_not_live')
        h.exact(row.get('worker_pid'), lifetimes[index]['pid'], 'ready_worker_identity_mismatch')
        snapshot = row['host_snapshot']
        controller, activity = snapshot['controller'], snapshot['activity']
        h.exact(controller.get('handoff_state'), 'ready', 'not_ready')
        h.true(controller.get('admission_allowed'), 'admission_not_allowed')
        h.exact(controller.get('foreground_reason'), 'cooperative_clear', 'readiness_policy_changed')
        h.exact(controller.get('fault'), None, 'controller_fault')
        h.exact(activity.get('errors'), [], 'activity_errors')
        foreground = activity['foreground']
        h.true(foreground.get('valid'), 'foreground_invalid')
        for key in ('hwnd', 'pid', 'creation_time_100ns'):
            h.exact(foreground.get(key), result['retained_gui_binding'][key], 'foreground_identity_mismatch')
        guard = snapshot['cooperative_foreground']
        h.exact(guard.get('consecutive'), 2, 'progress_pair_missing')
        h.exact(guard['completed']['intent_revision'], row['intent_revision'], 'progress_generation_mismatch')
        selected_guard = progress(h, guard)
        readiness.append({'owner_generation': index+1,
            'foreground_cpu_cores': h.number(foreground['cpu_cores_used']),
            'foreground_cpu_window_s': h.number(foreground['cpu_window_s']),
            'host_cpu_busy_fraction': h.number(activity['host']['cpu_busy_fraction']),
            'ram_available_gib': h.number(activity['host']['ram_available_gib']),
            'commit_available_gib': h.number(activity['host']['commit_available_gib']),
            'successful_exchanges_so_far': selected_guard['totals']['successful_exchanges'],
            'successful_pairs_so_far': selected_guard['totals']['successful_pairs'],
            'actual_owned_foreground_identity_matched': True, 'admission_observed': True})
    h.exact(ui.get('schema'), 'adaptive.manual-ui-observations.v1', 'ui_observation_schema')
    h.exact(ui.get('resume_click_attempts'), 2, 'resume_observation_changed')
    h.exact(ui.get('stop_click_attempts'), 2, 'stop_limitation_changed')
    h.exact(ui.get('first_stop_click_registered_in_ui'), False, 'missed_stop_click_not_preserved')
    selected.update(task_completed=True, task_state='accepted', provider_calls=3, file_effects=1,
        report=h.REPORT, report_sha256=h.digest(result['report_sha256']),
        effect_receipts_sha256=h.digest(result['effect_receipts_sha256']),
        retained_prompt_sha256=h.digest(result['retained_prompt_sha256']),
        native_history_sha256=h.digest(result['native_history_sha256']),
        worker_restart={'original_exit_code': 1, 'replacement_exit_code': 0,
            'original_joined_before_replacement': True, 'distinct_retained_identity': True,
            'safe_checkpoint_revision': h.integer(restart['safe_checkpoint_revision']),
            'product_stop_injected': False},
        real_model_validation_rejections=0, real_model_correction_observed=False,
        acknowledged_gui_resumes=2, observed_readiness=readiness,
        ui_observation={'stop_click_attempts': 2, 'first_stop_click_registered_in_ui': False,
            'second_stop_completed_normal_shutdown': True,
            'missed_click_cause': 'Not established by this live observation'},
        scope='One bounded installed report task and retained-worker restart; no reboot, all-agent, performance or single-click Stop reliability claim')
    return selected


def wheel_identity(h, data):
    h.exact(h.hash_bytes(data), WHEEL_SHA, 'wheel_changed')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        h.need(len(names) == len(set(names)), 'duplicate_wheel_entry')
        files = {}
        for name in names:
            if name.startswith('adaptive_inference/') and name.endswith('.py'):
                relative = name.removeprefix('adaptive_inference/')
                path = PurePosixPath(relative)
                h.need(not path.is_absolute() and '..' not in path.parts and '\\' not in relative,
                       'wheel_path_invalid')
                files[relative] = h.hash_bytes(archive.read(name))
    h.exact(len(files), 52, 'wheel_module_count_changed')
    return {'version': '0.3.0', 'files': files}


def software(h, producer, installed):
    expected = {'core': 698, 'provenance': 22, 'hermes-boundary': 12, 'foreground': 11,
        'native-contracts': 64, 'arithmetic-feedback': 11, 'shutdown-receipts': 9, 'sanitizer': 158}
    h.true(producer.get('passed'), 'software_checks_not_passed')
    h.exact(producer.get('required_suite_tests'), expected, 'software_counts_changed')
    h.exact(producer.get('required_suite_total'), 985, 'software_total_changed')
    h.exact(producer['artifacts']['adaptive_inference-0.3.0-py3-none-any.whl']['sha256'],
            WHEEL_SHA, 'software_wheel_changed')
    for name, value in (('tests', 348), ('failures', 0), ('errors', 0), ('skipped', []),
                        ('wheel_sha256', WHEEL_SHA), ('installed_module_count', 52)):
        h.exact(installed.get(name), value, 'installed_software_check_changed')
    h.true(installed.get('repository_pins_unchanged'), 'tested_source_changed')
    h.true(installed.get('installed_sources_unchanged'), 'tested_installation_changed')
    return {'required_suites': expected, 'required_total': 985,
            'targeted_tests_already_in_core': {'product_and_policy': 174, 'gui': 141,
                                             'qualification_adapter': 33},
            'independent_regular_wheel_tests': 348,
            'tested_source_manifest_sha256': h.digest(installed['aggregate_manifest_sha256']),
            'scope': 'Software and private-target installation checks; no additional inference claims'}


def installation(h, host, worker, bindings, identity):
    counts = {}
    for name, report, expected in (('host', host, 248), ('worker', worker, 301), ('bindings', bindings, 19)):
        rows = report.get('checks')
        h.need(type(rows) is dict and len(rows) == expected
               and all(value is True for value in rows.values()), 'actual_installation_check_failed')
        if name != 'bindings':
            h.true(report.get('passed'), 'actual_installation_not_passed')
            h.exact(report.get('package_identity'), identity, 'actual_installation_sources_changed')
        counts[name] = expected
    return {'actual_installation_predicates': counts, 'host_worker_package_contents_equal': True,
            'source_checkout_fallback': False,
            'scope': 'Direct full interpreters and regular installed package origins; separate live cases below'}


def build(h, selection, inputs):
    """Select only the independently audited terminal cold/full case pair."""
    identity = wheel_identity(h, inputs.raw('wheel', selection['wheel']))
    result_path = Path(selection['cold_result']).resolve(strict=True)
    supervisor = inputs.read('cold_parent', selection['cold_parent'])
    parent(h, supervisor)  # Refuse a nonterminal parent before reading case files.
    result = inputs.read('cold_result', result_path)
    audit = inputs.read('cold_audit', selection['cold_audit'])
    h.exact(inputs.hashes['cold_audit'], COLD_AUDIT_SHA, 'cold_audit_changed')
    h.exact(audit['evidence_sha256'].get(str(result_path)), inputs.hashes['cold_result'],
            'audit_result_binding_mismatch')
    ui = inputs.read('cold_ui', selection['cold_ui'])
    h.exact(audit.get('supervisor'), supervisor, 'audit_parent_binding_mismatch')
    h.exact(audit.get('ui_observations'), ui, 'audit_ui_binding_mismatch')
    h.exact(audit['evidence_sha256'].get(str(Path(selection['cold_ui']).resolve(strict=True))),
            inputs.hashes['cold_ui'], 'audit_ui_hash_mismatch')
    selected = cold(h, result, supervisor, audit, ui, identity)
    profile = inputs.read('profile', selection['profile'])
    h.exact(inputs.hashes['profile'], PROFILE_SHA, 'deployment_profile_changed')
    h.exact(profile.get('schema'), 'adaptive.desktop.windows-orders.v1', 'profile_schema_changed')
    h.exact(profile.get('foreground_policy'), POLICY, 'profile_policy_changed')
    deployment = {'schema': profile['schema'], 'profile_sha256': PROFILE_SHA,
        'foreground_policy': POLICY,
        'host_interpreter_sha256': h.digest(profile['host_python']['sha256']),
        'worker_interpreter_sha256': h.digest(profile['worker_python']['sha256']),
        'native_manifest_sha256': h.digest(profile['native_owner']['manifest_sha256']),
        'native_provenance_sha256': h.digest(profile['native_owner']['provenance_sha256']),
        'native_executable_sha256': h.NATIVE, 'hermes_sdk_revision': h.SDK,
        'model_assets_content_hashed': False,
        'model_asset_verification': 'Existing owner metadata and unchanged quality contract'}
    software_checks = software(h, inputs.read('software_producer', selection['software_producer']),
                               inputs.read('installed_wheel_tests', selection['installed_wheel_tests']))
    actual_installation = installation(h, inputs.read('host_install', selection['host_install']),
        inputs.read('worker_install', selection['worker_install']),
        inputs.read('deployment_bindings', selection['deployment_bindings']), identity)
    h.exact(selection.get('scope'), 'installed-cold-full-01', 'case_selection_changed')
    full_parent = inputs.read('full_parent', selection['full_parent'])
    parent(h, full_parent)
    full_path = Path(selection['full_result']).resolve(strict=True)
    full_result = inputs.read('full_result', full_path)
    full_audit = inputs.read('full_audit', selection['full_audit'])
    h.exact(inputs.hashes['full_audit'], FULL_AUDIT_SHA, 'full_audit_changed')
    full_ui_path = Path(selection['full_ui']).resolve(strict=True)
    full_ui = inputs.read('full_ui', full_ui_path)
    h.exact(full_audit['input_sha256'].get(str(full_path)), inputs.hashes['full_result'],
            'full_audit_result_binding_mismatch')
    h.exact(full_audit['input_sha256'].get(str(full_ui_path)), inputs.hashes['full_ui'],
            'full_audit_ui_hash_mismatch')
    h.exact(full_audit.get('supervisor'), full_parent, 'full_audit_parent_binding_mismatch')
    h.exact(full_audit.get('ui_observations'), full_ui, 'full_audit_ui_binding_mismatch')
    full_selected = full(h, full_result, full_parent, full_audit, full_ui, identity)
    return {'schema': 'adaptive.installed-desktop-evidence.v1',
            'status': 'bounded-installed-cold-and-full-accepted',
            'wheel_sha256': WHEEL_SHA, 'installed_package': identity,
            'qualification_manifest_sha256': QUALIFICATION_SHA,
            'qualifier_sha256': QUALIFIER_SHA, 'model': h.MODEL, 'quality': h.QUALITY,
            'deployment': deployment,
            'software_checks': software_checks, 'actual_installation': actual_installation,
            'qualification_bounds': {'task_deadline_s': 900, 'provider_request_limit': 8,
                                     'readiness_deadline_s': 240, 'outer_deadline_s': 1800},
            'cold': selected, 'full': full_selected,
            'private_input_sha256': dict(inputs.hashes),
            'helper_source': {'path': HELPER_RELATIVE, 'sha256': HELPER_SHA}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    h = helper(args.repository)
    try:
        h.need(not args.output.exists() and args.output.parent.is_dir(), 'output_not_fresh')
        inputs = h.Inputs(args.selection.parent)
        selection = inputs.read('selection', args.selection)
        value = build(h, selection, inputs)
        value['selection_exporter_sha256'] = h.hash_bytes(Path(__file__).read_bytes())
        data = h.encoded(value)
        h.privacy_check(data)
        manifest = {'schema': 'adaptive.public-evidence-files.v1',
                    'source_selection': 'explicit nested allowlists',
                    'files': {'result.json': h.hash_bytes(data)},
                    'sanitizer_sha256': value['selection_exporter_sha256'],
                    'reused_helper_sha256': HELPER_SHA}
        manifest_data = h.encoded(manifest)
        h.privacy_check(manifest_data)
        inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name, blob in (('result.json', data), ('manifest.json', manifest_data)):
            with (args.output/name).open('xb') as stream:
                stream.write(blob)
        print(json.dumps({'prepared': True, 'published': False, 'files': manifest['files']}))
        return 0
    except (h.Refused, KeyError, IndexError, TypeError, ValueError, OSError) as error:
        print(json.dumps({'prepared': False, 'reason': str(error) if isinstance(error, h.Refused)
                          else type(error).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
