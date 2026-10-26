# SPDX-License-Identifier: Apache-2.0
"""Select reviewed terminal Continue evidence; no runtime, database or model runs.

Only the exact independently accepted trial is selected by role hashes.
Existing strict input/privacy helpers and frozen predicates are reused.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

HERE = Path(__file__).resolve().parent
PRIOR = 'provenance/installed-desktop/export_acceptance.py'
PRIOR_SHA = '7eeec842d1aac88b3d0f9039b54c1f8aa7dfa76d81beecbd72c98467225e4b89'
CHECKS_SHA = 'dc795462df84516d5a8f3ffac9dd0b30f74ee29d98902e4dbdb07328b95cfae8'
WHEEL = '02010db139127855e4ec5a5542e1bda3c5f7dde12ea650fe9235181cef83ce66'
SOURCE = '73fbec145f95a7f97b60ba51dd8cbe737b3124b37c442417ac4acc69effe8906'
SOURCE_REVIEW = 'd029fad77d80db22c4bc40f987806d1e81ae3372b3c5d5347882a7806c52d3ad'
PACKAGE_REVIEW = '27c78976248848b086959db781f4a4610e4318f5f0e7824bb3477bfc36606dc6'
SCOPE = 'installed-explicit-continuation-01'
ROLES = frozenset(('wheel', 'source_review', 'package_review', 'deployment_gate',
    'host_install', 'worker_install', 'installed_identity', 'installed_sdk', 'clock_probe',
    'profile', 'audit', 'evidence', 'result', 'ui', 'parent', 'observer', 'report',
    'effect_receipts', 'worker_result'))
RAW = frozenset(('wheel', 'effect_receipts'))
SUPPORT_SHA = {
    'bindings.json': 'dbfaaf31347c24a514176f0ed1465892dec7e8a015a73e8b7c1d5914019056cb',
    'tested-build-source.json': '1159fe39f029579d618ba8368247a1f32ef64e3b488932aa2e87ffbd23ae8c93',
    'source-references.json': '5236bc13f9d80c928dc3faffc5bd425af1f95f7b9149cc4c111e39ce63127b40',
    'checks.py': CHECKS_SHA,
}


def module(path, name, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Retained helper changed')
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def helpers(repository):
    prior = module(Path(repository)/PRIOR, 'continuation_retained_exporter', PRIOR_SHA)
    h = prior.helper(repository)
    checks = module(HERE/'checks.py', 'continuation_export_checks', CHECKS_SHA)
    return prior, h, checks


def support(h, inputs, name):
    raw = inputs.raw('support:'+name, HERE/name)
    h.exact(h.hash_bytes(raw), SUPPORT_SHA[name], 'support_changed')
    return raw


def selected_inputs(h, inputs, selection, binding):
    h.exact(sorted(selection), ['inputs', 'scope'], 'selection_fields_changed')
    h.exact(selection['scope'], SCOPE, 'selection_scope_changed')
    h.exact(sorted(selection['inputs']), sorted(binding['private_input_sha256']), 'input_roles_changed')
    result = {}
    for name, expected in binding['private_input_sha256'].items():
        raw = inputs.raw(name, selection['inputs'][name])
        h.exact(h.hash_bytes(raw), h.digest(expected), 'input_role_hash_changed')
        result[name] = raw if name in RAW else h.parse(raw)
    return result


def enabled_binding(h, binding):
    h.exact(binding['schema'], 'adaptive.continuation.acceptance-bindings.v1', 'binding_schema_changed')
    h.exact(binding['scope'], SCOPE, 'binding_scope_changed')
    h.true(binding['enabled'], 'acceptance_not_bound')
    h.exact(binding['wheel_sha256'], WHEEL, 'wheel_binding_changed')
    h.digest(binding['deployment_gate_sha256'])
    h.digest(binding['terminal_audit_sha256'])
    h.exact(sorted(binding['private_input_sha256']), sorted(ROLES), 'binding_roles_changed')
    h.need(type(binding['terminal_checks']) is list and bool(binding['terminal_checks'])
           and len(set(binding['terminal_checks'])) == len(binding['terminal_checks']), 'terminal_check_set_missing')
    for role, pin in (('wheel', WHEEL), ('source_review', SOURCE_REVIEW), ('package_review', PACKAGE_REVIEW),
                      ('deployment_gate', binding['deployment_gate_sha256']), ('audit', binding['terminal_audit_sha256'])):
        h.exact(binding['private_input_sha256'][role], pin, 'bound_role_changed')


def wheel_identity(h, raw):
    h.exact(h.hash_bytes(raw), WHEEL, 'wheel_changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        h.need(len(names) == len(set(names)) == 67, 'wheel_members_changed')
        files = {}
        for name in names:
            path = PurePosixPath(name)
            h.need(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'wheel_path_invalid')
            if name.startswith('adaptive_inference/') and name.endswith('.py'):
                files[name.removeprefix('adaptive_inference/')] = h.hash_bytes(archive.read(name))
    h.exact(len(files), 57, 'runtime_count_changed')
    return {'version': '0.3.0', 'files': files}


def source_identity(h, inputs, repository, identity):
    source = h.parse(support(h, inputs, 'tested-build-source.json'))
    h.exact(source['source_freeze_sha256'], SOURCE, 'source_freeze_changed')
    h.exact((source['source_files'], len(source['files']), source['runtime_files']), (904, 904, 57), 'source_count_changed')
    expected = {'src/adaptive_inference/'+name: pin for name, pin in identity['files'].items()}
    h.exact(source['runtime'], expected, 'source_wheel_changed')
    for name, pin in expected.items():
        h.exact(source['files'][name], pin, 'build_runtime_changed')
        h.exact(h.hash_bytes(inputs.raw('runtime:'+name, Path(repository)/name)), pin, 'current_runtime_changed')
    return {'reviewed_repository_files': 904, 'runtime_files_checked_directly': 57,
            'changed_runtime_modules': 8, 'unchanged_runtime_modules': 46, 'new_runtime_modules': 3,
            'whole_build_equality': 'Bound by independent build/source review; current documentation may evolve.'}


def normalized_checks(h, audit):
    h.true(audit.get('passed'), 'terminal_audit_failed')
    values = audit['checks']
    h.need(type(values) is dict and bool(values), 'terminal_checks_missing')
    names = sorted(name for name in values if name.startswith('native_owner_'))
    result = {}
    for name, value in values.items():
        h.true(value, 'terminal_check_failed')
        public = 'native_owner_check_'+str(names.index(name)+1) if name in names else h.identifier(name)
        h.need(public not in result, 'terminal_check_collision')
        result[public] = True
    return result


def project(h, checks, evidence, ui):
    """Pure allowlist; callers must bind the actual audit before claiming acceptance."""
    checks.check_continuation(evidence)
    e = evidence
    g = e['grant']
    for name in ('first_resume_clicks', 'manual_pause_clicks', 'continue_clicks', 'stop_clicks'):
        h.exact(ui[name], 1, 'one_click_sequence_changed')
    h.exact(ui['retry_clicks'], 0, 'ui_retry_changed')
    h.exact(ui['window_id'], e['gui_binding']['hwnd'], 'window_changed')
    h.true(ui['post_expiry_gui']['same_window'], 'saved_window_changed')
    h.true(ui['post_continue_gui']['same_window'], 'continued_window_changed')
    h.true(ui['post_continue_gui']['task_accepted'], 'ui_task_not_accepted')
    before = h.number(e['sealed_before']['state'][checks.SEAL]['sealed_at_monotonic'])
    authorized = h.number(g['authorized_at'])
    ready = h.number(e['readiness']['finished_qpc'])
    stop = h.number(ui['stop_qpc_before'])
    h.need(before <= authorized <= ready < stop, 'relative_chronology_changed')
    return {'task_accepted': True, 'same_window': True, 'immutable_predecessor_and_history': True,
        'logical_objective_preserved': True, 'execution_generations': [0, 1],
        'explicit_grants': 1, 'execution_budgets_s': [900, 900],
        'provider_requests': {'before_continue': len(e['wire_before']), 'after_continue': len(e['wire_after']),
                              'new_requests': len(e['wire_after'])-len(e['wire_before']), 'cumulative_limit': 8},
        'physical_writes': 1, 'report_preserved': True, 'report': dict(checks.REPORT),
        'report_sha256': h.digest(e['report_sha256']),
        'native_conversation_prefix_preserved': True, 'one_derived_resume_after_fresh_pause_ack': True,
        'ui_clicks': {'resume': 1, 'pause': 1, 'continue': 1, 'stop': 1, 'retry': 0},
        'relative_seconds_after_expiry_seal': {'grant_committed': authorized-before, 'ready': ready-before, 'stop': stop-before},
        'readiness_elapsed_s': h.number(e['readiness']['finished_qpc']-e['readiness']['started_qpc']),
        'worker_exit_codes': [5, 0], 'both_retained_workers_joined': True,
        'authority_result_hash_verified': True, 'normal_stop_confirmed': True}


def build(h, prior, checks, repository, selection, inputs, binding):
    enabled_binding(h, binding)
    rows = selected_inputs(h, inputs, selection, binding)
    identity = wheel_identity(h, rows['wheel'])
    source = source_identity(h, inputs, repository, identity)
    h.exact(rows['installed_identity'], identity, 'installed_identity_changed')
    for role in ('host_install', 'worker_install'):
        h.true(rows[role]['passed'], 'installation_failed')
        h.exact(rows[role]['package_identity'], identity, 'installation_payload_changed')
        h.need(bool(rows[role]['checks']) and all(x is True for x in rows[role]['checks'].values()), 'installed_checks_failed')
    h.true(rows['source_review']['accepted'], 'source_review_failed')
    h.exact(rows['source_review']['source_freeze_sha256'], SOURCE, 'review_source_changed')
    h.true(rows['package_review']['passed'], 'package_review_failed')
    h.exact(rows['package_review']['wheel_sha256'], WHEEL, 'package_wheel_changed')
    gate = rows['deployment_gate']
    h.true(gate['passed'], 'deployment_failed')
    h.exact(gate['wheel_sha256'], WHEEL, 'deployment_wheel_changed')
    h.need(bool(gate['checks']) and all(x is True for x in gate['checks'].values()), 'deployment_check_failed')
    for role in ('host_install', 'worker_install', 'installed_identity', 'installed_sdk', 'clock_probe', 'profile', 'wheel'):
        h.need(inputs.hashes[role] in gate['input_sha256'].values(), 'deployment_role_unbound')
    sdk = rows['installed_sdk']
    h.true(sdk['passed'], 'sdk_failed');h.true(sdk['installed_mode'], 'source_sdk_not_installed')
    h.exact(sdk['package_identity'], identity, 'sdk_payload_changed')
    clock = rows['clock_probe']
    h.true(clock['passed'], 'clock_failed');h.exact(clock['mode'], 'installed', 'clock_mode_changed')
    h.exact(clock['deadline_clock'], checks.CLOCK, 'clock_domain_changed')
    h.exact(clock['profile_sha256'], inputs.hashes['profile'], 'clock_profile_changed')
    audit = rows['audit']
    h.exact(audit['schema'], 'private.continuation.installed-audit.v1', 'audit_schema_changed')
    audit_checks = normalized_checks(h, audit)
    h.exact(sorted(audit_checks), sorted(binding['terminal_checks']), 'terminal_check_set_changed')
    for role in ('evidence', 'result', 'ui', 'parent', 'observer', 'report', 'effect_receipts', 'worker_result'):
        h.need(inputs.hashes[role] in audit['input_sha256'].values(), 'terminal_role_unbound')
    e, result = rows['evidence'], rows['result']
    h.exact(e['worker'], rows['worker_result'], 'worker_result_changed')
    h.exact(e['worker_result_sha256'], inputs.hashes['worker_result'], 'worker_result_bytes_changed')
    h.exact(rows['report'], checks.REPORT, 'report_changed')
    h.exact(e['report_sha256'], inputs.hashes['report'], 'report_bytes_changed')
    h.exact(e['effects_after_sha256'], inputs.hashes['effect_receipts'], 'effects_changed')
    h.exact([h.parse(x) for x in rows['effect_receipts'].splitlines() if x.strip()], e['effects'], 'effect_rows_changed')
    h.exact(result['fixture'], False, 'fixture_not_live')
    h.true(result['task_completed'], 'task_not_completed');h.true(result['clean_stop'], 'stop_not_clean')
    h.exact(result['source']['installed_package'], identity, 'result_payload_changed')
    outcome = project(h, checks, e, rows['ui'])
    h.exact(audit['provider_calls'], outcome['provider_requests']['after_continue'], 'audited_requests_changed')
    h.exact(audit['physical_writes'], 1, 'audited_effects_changed')
    h.exact(audit['execution_budgets'], [900, 900], 'audited_budgets_changed')
    h.exact(audit['outer_deadline_s'], 2700, 'outer_bound_changed')
    observer = rows['observer']
    h.exact(observer['end_reason'], 'three_connection_errors_after_response', 'observer_reason_changed')
    h.exact(observer['consecutive_connection_errors'], 3, 'observer_errors_changed')
    h.true(observer['terminal_path_exists'], 'observer_terminal_missing')
    h.need(h.integer(observer['valid_responses']) <= h.integer(observer['samples']), 'observer_counts_invalid')
    return {'schema': 'adaptive.explicit-continuation.acceptance.v1', 'status': 'bounded-installed-explicit-continuation-accepted',
        'wheel_sha256': WHEEL, 'source_freeze_sha256': SOURCE, 'installed_package': identity, 'source': source,
        'model': checks.MODEL, 'quality': dict(checks.QUALITY), 'context': dict(checks.CONTEXT),
        'accepted_trial': outcome, 'independent_terminal_checks': audit_checks,
        'software_evidence': {'author_source_tests': 954, 'author_provenance_tests': 71,
                             'independent_affected_tests': 150, 'independent_provenance_tests': 71,
                             'counts_overlap': True, 'scope': 'CPU/source checks, separate from this installed model trial'},
        'observer': {'valid_responses': observer['valid_responses'], 'samples': observer['samples'],
                     'end_reason': observer['end_reason'], 'terminal_path_exists': True,
                     'scope': 'Sampled availability only; connection errors are not cleanup proof',
                     'cleanup_inference': False},
        'limitations': {'physical_reboot_recovery': False, 'automatic_budget_renewal': False,
                       'general_foreground_qualification': False, 'performance_claim': False, 'complete_M2_claim': False},
        'private_input_sha256': {name: inputs.hashes[name] for name in sorted(ROLES)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repository', 'selection', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prior, h, checks = helpers(args.repository)
        h.need(not args.output.exists() and args.output.parent.is_dir(), 'output_not_fresh')
        inputs = h.Inputs(args.selection.parent)
        binding = h.parse(support(h, inputs, 'bindings.json'))
        enabled_binding(h, binding)
        selection = inputs.read('selection', args.selection)
        value = build(h, prior, checks, args.repository.resolve(strict=True), selection, inputs, binding)
        value['exporter_sha256'] = h.hash_bytes(inputs.raw('exporter', Path(__file__)))
        value['support_sha256'] = {name: h.hash_bytes(support(h, inputs, name)) for name in SUPPORT_SHA}
        data = h.encoded(value);h.privacy_check(data)
        manifest = h.encoded({'schema': 'adaptive.public-evidence-files.v1',
            'source_selection': 'Fixed input roles and explicit fields only',
            'files': {'result.json': h.hash_bytes(data)}, 'sanitizer_sha256': value['exporter_sha256'],
            'reused_helper_sha256': prior.HELPER_SHA})
        h.privacy_check(manifest);inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name, raw in (('result.json', data), ('manifest.json', manifest)):
            with (args.output/name).open('xb') as stream:stream.write(raw)
        print(json.dumps({'prepared': True, 'published': False}))
        return 0
    except (AssertionError, KeyError, IndexError, TypeError, ValueError, OSError, zipfile.BadZipFile) as error:
        print(json.dumps({'prepared': False, 'reason': str(error) if type(error).__name__ == 'Refused' else type(error).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
