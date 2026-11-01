# SPDX-License-Identifier: Apache-2.0
"""Replay the accepted case17 files into a new private public-projection directory.

Reuses the historical exporter's strict input/privacy helpers. No original
auditor, database reader, runtime, service, SDK, model or GUI is executed.
"""
from __future__ import annotations
import argparse
import ast
import builtins
from copy import deepcopy
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import types
import zipfile

HERE = Path(__file__).resolve().parent
FOUNDATION = 'provenance/explicit-continuation/acceptance/export.py'
FOUNDATION_SHA = '1bf1eefdc90919c3bc746bf0ade44c8e52df1ed278641fd08553d193efda820f'
SCOPE = 'installed-task-handover-case17'
WHEEL = '50919bc2dd7c4cabdc661f57cab387d2df0eb999e3ca467a03852ed6ea15e33f'
SOURCE = '984cee5adbb0a80a5ed570891e119a38630f912daaef9982e6cb5c98bca14d7f'
ROLES = frozenset(('wheel', 'source_freeze', 'source_review', 'package_review',
    'package_independent_review', 'metadata_bridge', 'deployment_gate', 'host_install',
    'worker_install', 'installed_identity', 'installed_sdk', 'clock_probe', 'profile',
    'primary_audit', 'foreground_audit', 'evidence', 'result', 'ui', 'foreground',
    'trace', 'capture', 'parent', 'observer', 'joins', 'terminal_review',
    'inventory_output', 'welcome_output', 'inventory_input', 'inventory_spec',
    'welcome_spec', 'welcome_input', 'enabled_binding', 'harness_manifest'))
RAW = frozenset(('wheel', 'trace', 'welcome_output', 'inventory_input', 'welcome_input'))
# Populated from the committed case-specific public selectors, never private paths.
SUPPORT_SHA = {'bindings.json': 'af0f5b2e2a1f1a3ef538422889ab93876096352c94e40a2e18713059139a8eab', 'tested-build-source.json': '5cd561ff9ed615159ec9415167d9adec1bc78faaa28df5e99c41f989d9a0b284', 'source-references.json': 'df7195cc9af0411b165dada2b51630d929a8c7c4bd90c70dc9eb79f1201d7a2b'}


def helpers(repository):
    import importlib.util
    path = Path(repository)/FOUNDATION
    if hashlib.sha256(path.read_bytes()).hexdigest() != FOUNDATION_SHA:
        raise ValueError('Retained exporter changed')
    spec = importlib.util.spec_from_file_location('case17_retained_exporter', path)
    foundation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foundation)
    prior, h, _ = foundation.helpers(repository)
    return foundation, prior, h


def support(h, inputs, name):
    raw = inputs.raw('support:'+name, HERE/name)
    h.exact(h.hash_bytes(raw), SUPPORT_SHA[name], 'support_changed')
    return h.parse(raw)


def selected_inputs(h, inputs, selection, binding):
    h.exact(sorted(selection), ['inputs', 'scope'], 'selection_fields_changed')
    h.exact(selection['scope'], SCOPE, 'selection_scope_changed')
    h.exact(sorted(selection['inputs']), sorted(binding['private_input_sha256']), 'input_roles_changed')
    result = {}
    for role, pin in binding['private_input_sha256'].items():
        raw = inputs.raw(role, selection['inputs'][role])
        h.exact(h.hash_bytes(raw), h.digest(pin), 'input_role_hash_changed')
        result[role] = raw if role in RAW else h.parse(raw)
    return result


def definitions(h, raw, names, namespace):
    """Reuse the existing AST-selection convention; function bodies stay exact."""
    tree = ast.parse(raw)
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    h.exact(sorted(n.name for n in selected), sorted(names), 'source_definitions_missing')
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    namespace[target.id] = ast.literal_eval(node.value)
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<retained-predicates>', 'exec'), namespace)


def predicates(h, inputs, repository, refs):
    """Load only pure definitions, with the two original local imports bound exactly.

    This avoids importing database/runtime modules. The imported receipt-field
    constant and digest are selected from the pinned runtime source itself.
    """
    raw = {}
    for name, ref in refs['predicate_sources'].items():
        raw[name] = inputs.raw('predicate:'+name, Path(repository)/ref['path'])
        h.exact(h.hash_bytes(raw[name]), ref['sha256'], 'predicate_source_changed')
    digest_ns = {'json': json, 'hashlib': hashlib}
    definitions(h, raw['recovery'], ['digest'], digest_ns)
    stop_tree = ast.parse(raw['service_stop'])
    wait_fields = next(ast.literal_eval(n.value) for n in stop_tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'WAIT_RECEIPT_BINDINGS' for t in n.targets))
    safe_ns = {'json': json, 'math': math, 'deepcopy': deepcopy, 'digest': digest_ns['digest']}
    check_ns = {'csv': csv, 'io': io, 'hashlib': hashlib, 'json': json, 'math': math}
    modules = {'safe_wait': types.SimpleNamespace(),
        'adaptive_inference.desktop.hermes.service_stop': types.SimpleNamespace(WAIT_RECEIPT_BINDINGS=wait_fields)}
    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        h.need(level == 0 and name in modules, 'unexpected_predicate_import')
        return modules[name]
    safe_ns['__builtins__'] = check_ns['__builtins__'] = {**vars(builtins), '__import__': local_import}
    definitions(h, raw['checks'], ['digest', 'inventory_oracle', 'check_task', 'check_handover'], check_ns)
    safe_ns.update({k: check_ns[k] for k in ('MODEL', 'QUALITY', 'CONTEXT', 'SDK', 'NS')})
    definitions(h, raw['safe_wait'], ['check_safe_wait'], safe_ns)
    modules['safe_wait'].check_safe_wait = safe_ns['check_safe_wait']
    # first_inflight.py contains only stdlib imports, constants and pure functions.
    first_ns = {}
    exec(compile(raw['first_inflight'], '<retained-first-inflight>', 'exec'), first_ns)
    return types.SimpleNamespace(**check_ns), types.SimpleNamespace(**safe_ns), types.SimpleNamespace(**first_ns)


def wheel_identity(h, raw):
    h.exact(h.hash_bytes(raw), WHEEL, 'wheel_changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        h.need(len(names) == len(set(names)), 'duplicate_wheel_member')
        files = {}
        for name in names:
            path = PurePosixPath(name)
            h.need(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'wheel_path_invalid')
            if name.startswith('adaptive_inference/') and name.endswith('.py'):
                files[name.removeprefix('adaptive_inference/')] = h.hash_bytes(archive.read(name))
    h.exact(len(files), 60, 'runtime_count_changed')
    return {'version': '0.3.0', 'files': files}


def installation(h, inputs, rows, repository, source):
    """Same exact wheel/build-map and installation checks as the retained exporter."""
    identity = wheel_identity(h, rows['wheel'])
    h.exact(rows['installed_identity'], identity, 'installed_identity_changed')
    expected = {'src/adaptive_inference/'+n: pin for n, pin in identity['files'].items()}
    h.exact(source['source_freeze_sha256'], SOURCE, 'source_freeze_changed')
    h.exact(source['runtime'], expected, 'source_wheel_changed')
    h.exact(source['files'], rows['source_freeze']['source_files'], 'tested_build_map_changed')
    h.exact(len(source['files']), 1084, 'build_file_count_changed')
    for name, pin in expected.items():
        h.exact(source['files'][name], pin, 'build_runtime_changed')
        h.exact(h.hash_bytes(inputs.raw('runtime:'+name, Path(repository)/name)), pin, 'current_runtime_changed')
    h.true(rows['source_review']['passed'], 'source_review_failed')
    h.true(rows['source_review']['source_unchanged'], 'source_review_changed')
    h.exact(rows['source_review']['source_files'], rows['source_freeze']['behavioral_source_files'], 'behavioral_source_changed')
    changed = {n for n in source['files'] if source['files'][n] != rows['source_review']['source_files'][n]}
    h.exact(sorted(changed), ['.gitattributes', 'PLAN.md', 'docs/evidence.md'], 'metadata_bridge_scope_changed')
    bridge = rows['metadata_bridge']
    for name in changed:
        h.exact(bridge['changed_files'][name]['before_sha256'], rows['source_review']['source_files'][name], 'bridge_before_changed')
        h.exact(bridge['changed_files'][name]['after_sha256'], source['files'][name], 'bridge_after_changed')
    h.exact(rows['source_freeze']['metadata_bridge']['sha256'], inputs.hashes['metadata_bridge'], 'bridge_binding_changed')
    package, review = rows['package_review'], rows['package_independent_review']
    h.true(package['passed'], 'package_review_failed'); h.true(review['accepted'], 'independent_package_failed')
    h.exact(review['build_inputs_sha256'], SOURCE, 'package_source_changed')
    h.exact(review['build_result_sha256'], inputs.hashes['package_review'], 'package_review_binding_changed')
    h.exact(package['archive_check'], review['archive_result'], 'archive_review_changed')
    h.exact(package['archive_check']['installed_identity'], identity, 'archive_runtime_changed')
    h.exact(package['archive_check']['wheel_sha256'], WHEEL, 'package_wheel_changed')
    for role in ('host_install', 'worker_install', 'installed_sdk'):
        h.true(rows[role]['passed'], 'installation_failed')
        h.exact(rows[role]['package_identity'], identity, 'installation_payload_changed')
    for role in ('host_install', 'worker_install'):
        h.need(bool(rows[role]['checks']) and all(v is True for v in rows[role]['checks'].values()), 'installation_checks_failed')
    gate = rows['deployment_gate']
    h.true(gate['passed'], 'deployment_failed')
    h.exact(gate['wheel_sha256'], WHEEL, 'deployment_wheel_changed')
    h.need(bool(gate['checks']) and all(v is True for v in gate['checks'].values()), 'deployment_checks_failed')
    for role in ('host_install', 'worker_install', 'installed_identity', 'installed_sdk', 'clock_probe', 'profile', 'wheel'):
        h.need(inputs.hashes[role] in gate['input_sha256'].values(), 'deployment_role_unbound')
    h.true(rows['installed_sdk']['installed_mode'], 'sdk_not_installed')
    h.true(rows['clock_probe']['passed'], 'clock_failed')
    h.exact(rows['clock_probe']['profile_sha256'], inputs.hashes['profile'], 'clock_profile_changed')
    return identity


def project(h, evidence, ui, activity, onset):
    """Allowlisted public facts only; build() first binds audits and pure predicates."""
    a, b = evidence['tasks']; recovery = evidence['safe_wait']
    seal = h.number(recovery['sealed_before']['checkpoint']['state']['adaptive_inference.execution_outcome.v1']['sealed_at_monotonic'])
    clicks = {}
    for key in ('resume_a', 'continue', 'new_task', 'resume_b', 'stop', 'pause', 'retry'):
        clicks[key] = h.exact(ui[key+'_clicks'], 0 if key in ('pause', 'retry') else 1, 'control_counts_changed')
    rejected = ui['rejected_input_attempts']
    h.exact(len(rejected), 1, 'unsuccessful_input_missing')
    h.exact(rejected[0]['action'], 'set_value task picker File name', 'unsuccessful_input_changed')
    h.exact(rejected[0]['error'], 'Cannot set a value for an element that is not settable', 'unsuccessful_input_changed')
    actions = activity['actions']; preseal = [x for x in actions if x['qpc_after'] <= seal]
    decimal = lambda x: Decimal(str(x))
    gaps = [decimal(y['qpc_after'])-decimal(x['qpc_before']) for x, y in zip(preseal, preseal[1:])]
    tail = decimal(seal)-decimal(preseal[-1]['qpc_before'])
    h.need(all(0 <= gap < 60 for gap in gaps) and 0 <= tail < 60, 'foreground_coverage_failed')
    h.exact((len(actions), len(preseal)), (25, 24), 'foreground_action_count_changed')
    h.exact([len(a['wire']), len(b['wire'])], [3, 3], 'request_totals_changed')
    h.exact([len(a['effects']), len(b['effects'])], [1, 1], 'effect_totals_changed')
    return {'inventory': {'total_units': h.integer(a['artifact']['total_units']),
            'semantic_validation': 'oracle_matched', 'artifact_sha256': h.digest(a['artifact_sha256'])},
        'welcome': {'acceptance': 'format-only', 'semantic_validation': 'not_checked',
                    'artifact_sha256': h.digest(b['artifact_sha256'])},
        'provider_calls': 6, 'provider_calls_by_execution': [1, 2, 3], 'physical_writes': 2,
        'execution_budgets_s': [900, 900, 900], 'outer_budget_s': 2700,
        'readiness_budget_s': 240, 'cumulative_request_limit_per_logical_task': 8, 'admission_limit': 32,
        'original_task_and_saved_read_preserved': True, 'accepted_inventory_unchanged_after_second_task': True,
        'same_controller_two_distinct_tasks': True, 'explicit_continue_count': 1, 'ui_clicks': clicks,
        'unsuccessful_input': {'file_picker_value_setting_rejected': True, 'count': 1,
            'recovered_without_extra_task_control': True},
        'foreground': {'actions': len(actions), 'wholly_preseal_actions': len(preseal),
            'postseal_actions_excluded': len(actions)-len(preseal), 'target_interval_s': 30,
            'strict_coverage_limit_s': 60, 'strict_comparison': 'less-than',
            'maximum_adjacent_s': float(max(gaps)), 'preseal_tail_s': float(tail),
            'target_misses': sum(gap > 30 for gap in gaps), 'strict_failures': 0,
            'first_full_action_s': float(decimal(actions[0]['qpc_after'])-decimal(actions[0]['qpc_before'])),
            'same_first_admitted_cycle': True, 'continuous_hold': True, 'saved_read_lineage': True,
            'scope': 'Observed first-cycle overlap and held admission; no GPU preemption or latency claim'},
        'relative_seconds_after_expiry_seal': {
            'continue_committed': h.number(recovery['grant']['authorized_at']-seal),
            'new_task_clicked': h.number(ui['new_task_qpc_before']-seal),
            'stop_clicked': h.number(ui['stop_qpc_before']-seal)}}


def build(foundation, h, repository, selection, inputs, binding, refs, source):
    h.exact(binding['schema'], 'adaptive.task-handover.acceptance-bindings.v1', 'binding_schema_changed')
    h.exact(binding['scope'], SCOPE, 'binding_scope_changed'); h.true(binding['enabled'], 'acceptance_not_bound')
    h.exact(sorted(binding['private_input_sha256']), sorted(ROLES), 'binding_roles_changed')
    rows = selected_inputs(h, inputs, selection, binding)
    identity = installation(h, inputs, rows, repository, source)
    primary, additive = rows['primary_audit'], rows['foreground_audit']
    h.exact(primary['schema'], 'private.safe-wait-handover.installed-audit.v1', 'primary_schema_changed')
    checks = foundation.normalized_checks(h, primary)
    h.exact(sorted(checks), binding['terminal_checks'], 'primary_check_set_changed')
    h.exact(len(checks), 99, 'primary_checks_incomplete')
    h.exact(additive['schema'], 'private.case09.first-inflight-audit.v1', 'foreground_schema_changed')
    h.true(additive['passed'], 'foreground_audit_failed'); h.true(additive['qualification_claimed'], 'foreground_not_accepted')
    h.exact(additive['original_audit_sha256'], inputs.hashes['primary_audit'], 'different_primary_audit')
    h.exact(primary['bindings_sha256'], inputs.hashes['enabled_binding'], 'different_trial_binding')
    h.exact(additive['bindings_sha256'], primary['bindings_sha256'], 'different_foreground_trial')
    h.true(rows['enabled_binding']['enabled'], 'original_binding_disabled')
    h.exact(rows['enabled_binding']['harness_manifest']['sha256'], inputs.hashes['harness_manifest'], 'harness_binding_changed')
    for role, descriptor in rows['enabled_binding']['inputs'].items():
        h.exact(descriptor['sha256'], inputs.hashes[role], 'original_input_binding_changed')
    for ref in refs['predicate_sources'].values():
        h.need(ref['sha256'] in additive['input_sha256'].values(), 'predicate_not_in_original_audit')
    for path, pin in primary['input_sha256'].items():
        h.exact(additive['input_sha256'].get(path), pin, 'audit_input_disagreement')
    # Original path strings are never followed; selected bytes must be among the
    # exact original audit inputs. Relocation changes only selection paths.
    for role in ROLES-{'primary_audit', 'foreground_audit', 'joins', 'terminal_review', 'package_independent_review', 'metadata_bridge', 'enabled_binding'}:
        h.need(inputs.hashes[role] in additive['input_sha256'].values(), 'audited_role_unbound')
    review = rows['terminal_review']
    h.true(review['independent_review_passed'], 'independent_review_failed')
    h.true(review['combined_bounded_scenario_accepted'], 'combined_run_not_accepted')
    h.exact(review['blocking_findings'], [], 'independent_review_blocked')
    h.exact(review['cleanup']['native_descendants_per_cycle'], [7, 7, 7], 'reviewed_native_cleanup_changed')
    h.exact(review['cleanup']['confirmed_native_descendant_exits_per_cycle'], [7, 7, 7], 'reviewed_native_exits_changed')
    h.exact(review['cleanup']['closed_GUI_listener_transport_episodes'], 2, 'reviewed_episode_cleanup_changed')
    for role in ('primary_audit', 'foreground_audit', 'joins', 'foreground', 'ui', 'evidence', 'result'):
        h.need(inputs.hashes[role] in review['input_sha256'].values(), 'independent_review_role_unbound')
    e, ui, result = rows['evidence'], rows['ui'], rows['result']
    check, safe, first = predicates(h, inputs, repository, refs)
    predicate_checks = check.check_handover(e)
    h.exact(safe.check_safe_wait(e['safe_wait']), additive['retained_safe_wait_checks'], 'safe_wait_checks_changed')
    h.exact(rows['inventory_output'], check.inventory_oracle(rows['inventory_input']), 'original_inventory_oracle_failed')
    for task, role in zip(e['tasks'], ('inventory_output', 'welcome_output')):
        h.exact(task['artifact_sha256'], inputs.hashes[role], 'artifact_bytes_changed')
        h.exact(task['plan']['package_identity'], identity, 'task_runtime_changed')
    trace = [h.parse(line) for line in rows['trace'].splitlines() if line.strip()]
    seal = e['safe_wait']['sealed_after']['checkpoint']['state'][safe.SEAL]['sealed_at_monotonic']
    onset = first.check_onset(trace, ui, rows['foreground'], rows['capture'], e['gateway_instance'], e['safe_wait']['gui_binding'], seal)
    h.exact(onset, additive['onset'], 'foreground_onset_changed')
    argument_text = e['safe_wait']['sealed_after']['checkpoint']['state']['native_history'][1]['tool_calls'][0]['function']['arguments']
    h.exact(h.hash_bytes(argument_text.encode('utf-8')), additive['input_identity']['raw_argument_sha256'], 'raw_input_argument_changed')
    arguments = h.parse(argument_text)
    h.exact(sorted(arguments), ['path'], 'input_argument_fields_changed')
    h.exact(additive['input_identity']['input_sha256'], inputs.hashes['inventory_input'], 'lineage_input_changed')
    # Preserve the actual raw argument, not its resolved filesystem spelling.
    # Its resolution was checked by the original auditor; replay never follows it.
    lineage = first.check_lineage(e['safe_wait'], e['logical_original'], result,
        arguments['path'], rows['inventory_input'])
    h.exact(lineage, additive['lineage'], 'saved_read_lineage_changed')
    h.true(result['qualification_case_passed'], 'result_not_accepted'); h.true(result['clean_stop'], 'unclean_stop')
    h.exact(result['fixture'], False, 'fixture_not_live')
    h.exact((primary['provider_calls'], primary['physical_writes'], primary['execution_budgets'], primary['outer_deadline_s']),
            (6, 2, [900, 900, 900], 2700), 'audited_totals_changed')
    parent, observer, joins = rows['parent'], rows['observer'], rows['joins']
    h.exact((parent['exit_code'], parent['timed_out'], parent['emergency_termination_attempted']), (0, False, False), 'parent_not_normal')
    h.true(parent['retained_case_handle_exited'], 'parent_not_joined')
    h.exact((joins['parent']['joined'], joins['parent']['exit_code'], joins['observer']['joined'], joins['observer']['exit_code']), (True, 0, True, 1), 'actual_joins_changed')
    h.exact(observer['end_reason'], 'three_connection_errors_after_response', 'observer_reason_changed')
    h.exact((observer['samples'], observer['valid_responses'], observer['consecutive_connection_errors'], observer['terminal_path_exists']), (1621, 1618, 3, True), 'observer_record_changed')
    return {'schema': 'adaptive.task-handover.acceptance.v1', 'status': 'bounded-installed-case17-accepted',
        'installed_runtime_source': '7306a53085ddc31d53d2ba50e91975c80cfc0014',
        'wheel_sha256': WHEEL, 'source_freeze_sha256': SOURCE, 'installed_package': identity,
        'source': {'reviewed_build_files': 1084, 'runtime_files_checked_directly': 60,
            'whole_build_equality': 'Original build/source and metadata bridge reviews; later documentation is separate.'},
        'model': check.MODEL, 'quality': check.QUALITY, 'context': check.CONTEXT,
        'accepted_trial': project(h, e, ui, rows['foreground'], onset),
        'original_primary_checks': checks, 'replayed_in_memory_handover_checks': predicate_checks,
        'both_original_audits_passed': True, 'independent_terminal_review_accepted': True,
        'cleanup': {'parent_exit_code': 0, 'parent_elapsed_s': h.number(parent['elapsed_s']),
            'retained_child_exit_codes': [x['exit_code'] for x in e['retained_children']],
            'closed_gui_listener_transport_episodes': 2, 'native_release_cycles': 3,
            'native_descendant_exits_per_cycle': [7, 7, 7],
            'no_remaining_child_job_members_before_parent_join': True, 'normal_user_stop': True},
        'observer': {'exit_code': 1, 'valid_responses': 1618, 'samples': 1621,
            'end_reason': observer['end_reason'], 'terminal_result_present': True, 'cleanup_inference': False},
        'limitations': {'complete_M2_claim': False, 'physical_reboot_recovery': False,
            'general_desktop_or_media_qualification': False, 'performance_claim': False,
            'welcome_semantic_oracle': False, 'new_physical_trial_from_replay': False},
        'private_input_sha256': {name: inputs.hashes[name] for name in sorted(ROLES)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repository', 'selection', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        foundation, prior, h = helpers(args.repository)
        h.need(not args.output.exists() and args.output.parent.is_dir(), 'output_not_fresh')
        inputs = h.Inputs(args.selection.parent)
        binding = support(h, inputs, 'bindings.json')
        refs = support(h, inputs, 'source-references.json')
        source = support(h, inputs, 'tested-build-source.json')
        value = build(foundation, h, args.repository.resolve(strict=True), inputs.read('selection', args.selection), inputs, binding, refs, source)
        value['exporter_sha256'] = h.hash_bytes(inputs.raw('exporter', Path(__file__)))
        value['support_sha256'] = dict(SUPPORT_SHA)
        data = h.encoded(value); h.privacy_check(data)
        manifest = h.encoded({'schema': 'adaptive.public-evidence-files.v1',
            'source_selection': 'Fixed case17 roles and explicit public fields only',
            'files': {'result.json': h.hash_bytes(data)}, 'sanitizer_sha256': value['exporter_sha256'],
            'reused_exporter_sha256': FOUNDATION_SHA, 'reused_helper_sha256': prior.HELPER_SHA})
        h.privacy_check(manifest); inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name, raw in (('result.json', data), ('manifest.json', manifest)):
            with (args.output/name).open('xb') as stream: stream.write(raw)
        print(json.dumps({'prepared': True, 'published': False}))
        return 0
    except (AssertionError, KeyError, IndexError, TypeError, ValueError, OSError, zipfile.BadZipFile) as error:
        print(json.dumps({'prepared': False, 'reason': str(error) if type(error).__name__ == 'Refused' else type(error).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
