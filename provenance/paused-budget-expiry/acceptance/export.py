# SPDX-License-Identifier: Apache-2.0
"""Replay the exact accepted paused-expiry03 selection into a fresh directory.

Reads explicit private receipt paths; never starts a model or changes a runtime.
Reuses the retained strict reader, privacy filters and scoped selectors unchanged.
The wheel reader is the existing installed-desktop reader with this wheel's pins.
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
PINS = {
    'selection.py': 'e314c9d88226673c386eb06c1e1c4b7b87c06d3e99a9dfb669ff25d11279e79d',
    'gates.py': 'b6719b84908b70bc0908561082b9e55ec7f34552f34497c04f8e45bcc0565fff',
    'bindings.json': 'd86a617c6dd731ec10f43036fd52297843ae04eb674efc5ddd852425a857f82e',
    'reviewed-source.json': 'bf70a2acc69cd6a1d9954ad3fe8dbd69f3c43aefa97803f079b15b5662e071db',
}
WHEEL = 'b28aeb0b09db16d38a8ab9a9af3ed6467fc33181f45caca92bda5fa722660f80'
HISTORICAL_SUPPORT = {'docs/paused-budget-expiry.md': 'reviewed-support/paused-budget-expiry.md'}
RAW_INPUTS = frozenset(('wheel', 'trace', 'effect_receipts'))


def load_module(name):
    path = HERE/name
    if hashlib.sha256(path.read_bytes()).hexdigest() != PINS[name]:
        raise ValueError('Adjacent selector changed')
    spec = importlib.util.spec_from_file_location('paused_expiry_'+path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contained(h, root, relative):
    path = PurePosixPath(relative)
    h.need(not path.is_absolute() and '..' not in path.parts and '\\' not in relative,
           'source_path_invalid')
    target = (root/relative).resolve(strict=True)
    h.need(target.is_relative_to(root.resolve(strict=True)), 'source_path_escaped')
    return target


def reviewed_source(h, inputs, repository, bindings):
    """Only the exact historical feature document has a preserved-file mapping."""
    freeze = inputs.read('reviewed_source', HERE/'reviewed-source.json')
    h.exact(inputs.hashes['reviewed_source'], PINS['reviewed-source.json'], 'source_freeze_changed')
    h.exact(bindings['reviewed_support'], HISTORICAL_SUPPORT, 'support_mapping_changed')
    h.exact(len(freeze['files']), 120, 'source_closure_count_changed')
    for name, expected in freeze['files'].items():
        root, relative = (HERE, HISTORICAL_SUPPORT[name]) if name in HISTORICAL_SUPPORT else (repository, name)
        data = inputs.raw('source:'+name, contained(h, root, relative))
        h.exact(h.hash_bytes(data), h.digest(expected), 'reviewed_source_file_changed')
    h.exact(freeze['runtime_files'], 54, 'source_runtime_count_changed')
    h.exact(freeze['sdk_pin_count'], 20, 'sdk_pin_count_changed')
    return freeze


def selected_inputs(h, inputs, selection, bindings):
    h.exact(sorted(selection), ['inputs', 'scope'], 'selection_fields_changed')
    h.exact(selection['scope'], 'installed-paused-expiry-03', 'selection_scope_changed')
    paths = selection['inputs']
    h.exact(sorted(paths), sorted(bindings['private_input_sha256']), 'input_label_set_changed')
    rows = {}
    for label, expected in bindings['private_input_sha256'].items():
        raw = inputs.raw(label, paths[label])
        h.exact(h.hash_bytes(raw), h.digest(expected), 'accepted_input_changed')
        rows[label] = raw if label in RAW_INPUTS else h.parse(raw)
    return rows


def wheel_identity(h, data):
    """Adapt the retained installed-desktop wheel selector's 52-module bound to 54."""
    h.exact(h.hash_bytes(data), WHEEL, 'wheel_changed')
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
    h.exact(len(files), 54, 'wheel_module_count_changed')
    return {'version': '0.3.0', 'files': files}


def test_receipt(h, row, count, *, installed=None):
    for key, value in (('passed', True), ('tests', count), ('failures', 0), ('errors', 0),
                       ('skipped', 0), ('source_unchanged', True)):
        h.exact(row.get(key), value, 'test_receipt_not_passed')
    if 'source_before' in row:
        h.exact(row['source_before'], row['source_after'], 'test_source_changed')
    if installed is not None:
        h.exact(row['installed_mode'], installed, 'sdk_execution_mode_changed')


def software(h, rows, inputs, freeze, identity):
    review = rows['source_review']
    for key, value in (('source_review_passed', True), ('cleared_for_package_build', True),
                       ('installed_or_live_acceptance', False), ('source_file_count', 120),
                       ('source_freeze_sha256', PINS['reviewed-source.json'])):
        h.exact(review.get(key), value, 'source_review_changed')
    for label, name in (('source_cpu', 'cpu-01/tests.private.json'), ('source_sdk', 'sdk-source-01/tests.private.json')):
        h.exact(review['files'][name], inputs.hashes[label], 'source_review_receipt_changed')
    test_receipt(h, rows['source_cpu'], 105)
    for key, value in (('distinct_ids', 105), ('distinct_implementations', 105), ('runtime_modules', 54),
                       ('sdk_current_count', 20), ('qualifier_unchanged', True),
                       ('public_fixture_class_ast_unchanged', True)):
        h.exact(rows['source_cpu'][key], value, 'source_review_scope_changed')
    test_receipt(h, rows['source_sdk'], 3, installed=False)
    h.exact(rows['source_sdk']['package_identity'], None, 'source_test_relabelled_installed')
    for label in ('producer_311', 'producer_312'):
        test_receipt(h, rows[label], 104)
        h.true(rows[label]['actual_sdk20_file_check_passed'], 'sdk_source_dependency_changed')
        h.exact(freeze[label+'_sha256'], inputs.hashes[label], 'producer_receipt_changed')
    test_receipt(h, rows['installed_sdk'], 3, installed=True)
    h.exact(rows['installed_sdk']['package_identity'], identity, 'sdk_installed_payload_changed')
    h.need(rows['installed_sdk']['python'].startswith('3.14.7'), 'sdk_worker_version_changed')
    fixture = rows['scaffold_tests']
    for key, value in (('tests', 28), ('failures', 0), ('errors', 0), ('skipped', 0), ('source_unchanged', True)):
        h.exact(fixture[key], value, 'selector_fixture_test_failed')
    h.exact(fixture['source_before'], fixture['source_after'], 'selector_fixture_source_changed')
    h.exact(fixture['source_binding_sha256'], inputs.hashes['scaffold_binding'], 'scaffold_receipt_changed')
    binding = rows['scaffold_binding']
    h.exact(binding['source_freeze_sha256'], PINS['reviewed-source.json'], 'scaffold_source_changed')
    h.exact(binding['sdk_pin_count'], 20, 'scaffold_sdk_count_changed')
    for key in ('current_wheel_sha256', 'deployment_gate_sha256', 'accepted_terminal_audit_sha256'):
        h.exact(binding[key], None, 'disabled_scaffold_rearmed')
    h.exact(binding['acceptance_enabled'], False, 'scaffold_rearmed')
    return {'producer_source_tests': {'python_3_11': 104, 'python_3_12': 104},
            'independent_distinct_source_tests': 105, 'actual_sdk_source_dispatch_tests': 3,
            'actual_sdk_installed_dispatch_tests': 3, 'sdk_worker_python': '3.14.7',
            'selector_fixture_tests': 28, 'sdk_dependency_files': 20,
            'scope': 'Source tests use fixtures; actual pinned SDK dispatch uses a reduced native fixture, without model inference. The separate terminal trial supplies real-model evidence.'}


def installation(h, prior, rows, inputs, bindings, identity):
    package = rows['package_review']
    # Package checks include relative module names with slashes, so the older
    # identifier-only helper does not apply. Keep exact names and strict booleans.
    h.true(package['passed'], 'independent_package_audit_failed')
    h.exact(sorted(package['checks']), bindings['package_checks'], 'package_check_names_changed')
    for value in package['checks'].values():
        h.true(value, 'independent_package_check_failed')
    for key, value in (('wheel_sha256', WHEEL), ('record_entries', 64), ('added_members', [])):
        h.exact(package[key], value, 'package_review_changed')
    h.exact(package['runtime_pins'], {'adaptive_inference/'+k: v for k, v in identity['files'].items()},
            'reviewed_wheel_payload_changed')
    h.exact(package['changed_members'], ['adaptive_inference-0.3.0.dist-info/RECORD'] +
            ['adaptive_inference/desktop/hermes/'+name for name in
             ('pause_activity.py', 'recovery.py', 'run_recovery.py', 'sdk_pins.py', 'service_stop.py')],
            'package_delta_changed')
    gate = rows['deployment_gate']
    prior.checks(h, gate, set(bindings['deployment_checks']))
    for key, value in (('wheel_sha256', WHEEL), ('host_checks', 254), ('worker_checks', 307),
                       ('runtime_modules', 54), ('native_files', 4847), ('dependencies', 8),
                       ('asset_metadata', 14), ('run_agent_executed_by_this_gate', False),
                       ('preflight_is_resource_reservation', False), ('installed_sdk_dispatch_tests', 3)):
        h.exact(gate.get(key), value, 'deployment_gate_changed')
    for label, field in (('installed_sdk', 'installed_sdk_dispatch_receipt_sha256'),
                         ('clock_probe', 'installed_clock_probe_sha256')):
        h.exact(gate[field], inputs.hashes[label], 'actual_deployment_receipt_changed')
    for label in ('host_install', 'worker_install', 'clock_probe', 'installed_sdk', 'profile', 'wheel'):
        h.need(inputs.hashes[label] in gate['input_sha256'].values(), 'deployment_input_unbound')
    for label, count in (('host_install', 254), ('worker_install', 307)):
        row = rows[label]
        h.true(row['passed'], 'installed_check_failed')
        h.need(type(row['checks']) is dict and len(row['checks']) == count
               and all(v is True for v in row['checks'].values()), 'installed_checks_changed')
        h.exact(row['package_identity'], identity, 'installed_payload_changed')
    clock = rows['clock_probe']
    for key, value in (('mode', 'installed'), ('passed', True), ('source_unchanged', True),
                       ('deadline_clock', 'windows-qpc-seconds-v1'), ('profile_sha256', inputs.hashes['profile'])):
        h.exact(clock.get(key), value, 'actual_clock_probe_changed')
    h.exact(len(clock['pairs']), 3, 'clock_pair_count_changed')
    for pair in clock['pairs']:
        h.true(pair['passed'], 'clock_pair_failed')
        h.exact(pair['returncode'], 0, 'clock_worker_failed')
        h.exact(pair['stderr'], '', 'clock_worker_error')
        h.exact(pair['worker']['deadline_clock'], clock['deadline_clock'], 'clock_domain_changed')
        h.need(h.number(pair['host_before']) <= h.number(pair['worker']['execution_now'])
               <= h.number(pair['host_after']), 'clock_causal_bracket_failed')
    return {'independent_package_checks': 91, 'independent_deployment_checks': 9,
            'host_checks': 254, 'worker_checks': 307, 'runtime_modules': 54,
            'native_files_verified': 4847, 'dependencies_verified': 8,
            'model_asset_metadata_verified': 14, 'full_model_content_hash_claimed': False,
            'actual_installed_clock_pairs': 3, 'preflight_is_resource_reservation': False}


def terminal(h, selector, retained, prior, gates, rows, inputs, bindings, identity):
    result, audit, ui = rows['result'], rows['audit'], rows['ui']
    checks = dict(audit['checks'])
    for index, owner in enumerate(audit['native_owners'], 1):
        checks['native_owner_generation_'+str(index)] = checks.pop('native_owner_'+owner['owner_id'])
    accepted = prior.checks(h, {'passed': audit['passed'], 'checks': checks}, set(bindings['terminal_checks']))
    # Hash roles are fixed by bindings.json. Membership adds the independent audit
    # binding without requiring historic absolute paths to exist on replay hosts.
    for label in ('result', 'worker_result', 'paused_checkpoint', 'terminal_checkpoint',
                  'expiry_observation', 'readiness', 'parent', 'observer', 'trace', 'ui',
                  'effect_receipts', 'report', 'installed_identity'):
        h.need(inputs.hashes[label] in audit['input_sha256'].values(), 'terminal_input_unbound')
    for field, value in (('supervisor', rows['parent']), ('observer', rows['observer']),
                         ('ui_observations', ui), ('readiness', [rows['readiness']]),
                         ('controls', result['controls']), ('expiry_observation', rows['expiry_observation']),
                         ('parked_observation', result['expiry_parked_observation']),
                         ('paused_expiry', result['paused_expiry_receipt']),
                         ('actual_deployment_gate_sha256', inputs.hashes['deployment_gate']),
                         ('shared_clock_probe_sha256', inputs.hashes['clock_probe']),
                         ('deadline_clock', gates.CLOCK_ID), ('task_revision', 27),
                         ('validation_rejection_count', 0), ('provider_calls', 2),
                         ('observer_termination_proves_cleanup', False)):
        h.exact(audit[field], value, 'terminal_audit_cross_binding_changed')
    h.exact(result['source'], {'manifest_sha256': bindings['qualification_manifest_sha256'],
                             'files': 6, 'installed_package': identity}, 'terminal_source_changed')
    h.exact(rows['report'], h.REPORT, 'report_contract_changed')
    for key, label in (('report_sha256', 'report'), ('effect_sha256', 'effect_receipts')):
        h.exact(audit[key], inputs.hashes[label], 'effect_hash_changed')
    effects = [h.parse(line) for line in rows['effect_receipts'].splitlines() if line.strip()]
    h.exact(len(effects), 1, 'effect_count_changed')
    outcome = selector.expiry_state(h, result, rows['worker_result'], rows['paused_checkpoint'],
                                   rows['terminal_checkpoint'], rows['expiry_observation'])
    h.exact(outcome['sealed_state_sha256'], audit['task_state_sha256'], 'audited_state_changed')
    h.exact(outcome['native_history_sha256'], audit['native_history_sha256'], 'audited_native_history_changed')
    outcome['pre_seal_revision'] = h.exact(rows['paused_checkpoint']['revision'], 26, 'pre_seal_revision_changed')
    outcome['sealed_revision'] = 27
    outcome['cleanup'] = selector.cleanup(h, result)
    outcome['native_release'] = selector.native_releases(h, result, audit['native_owners'])
    outcome['request_correlation'] = selector.request_generations(h, result)
    outcome['ui'] = gates.timing(h, result, [rows['readiness']], rows['expiry_observation'], ui)
    outcome['supervision'] = gates.parent(h, rows['parent'], bindings)
    outcome['observer'] = retained.observer(h, rows['observer'], 957, 954)
    h.exact(rows['observer']['source_sha256'], bindings['observer_source_sha256'], 'observer_source_changed')
    trace = [h.parse(line) for line in rows['trace'].splitlines() if line.strip()]
    h.exact(len(trace), 957, 'observer_sample_count_changed')
    outcome['post_expiry_availability'] = gates.get_observations(h, trace,
        expiry_at=result['verified_expiry_observed_deadline_clock'], stop_at=ui['stop_qpc_before'],
        gateway_instance=rows['observer']['gateway_instance'])
    h.exact(outcome['post_expiry_availability']['successful_post_expiry_gets'],
            audit['post_expiry_get_responses'], 'audited_get_count_changed')
    h.exact(audit['post_expiry_get_responses'], 55, 'get_count_changed')
    outcome['independent_checks'] = accepted
    return outcome


def build(h, retained, prior, selector, gates, repository, selection, inputs):
    bindings = inputs.read('bindings', HERE/'bindings.json')
    h.exact(inputs.hashes['bindings'], PINS['bindings.json'], 'bindings_changed')
    freeze = reviewed_source(h, inputs, repository, bindings)
    rows = selected_inputs(h, inputs, selection, bindings)
    identity = wheel_identity(h, rows['wheel'])
    h.exact(rows['installed_identity'], identity, 'terminal_installed_identity_changed')
    source_runtime = {k.removeprefix('src/adaptive_inference/'): v for k, v in freeze['files'].items()
                      if k.startswith('src/adaptive_inference/')}
    h.exact(source_runtime, identity['files'], 'wheel_reviewed_source_changed')
    lineage = [h.parse(inputs.raw('lineage:'+name, repository/'provenance/paused-budget-expiry'/name))
               for name in ('thread-successor/source-lineage.json', 'clock-successor/source-lineage.json', 'source-lineage.json')]
    source = selector.thread_source_identity(h, identity, *lineage)
    source['reviewed_source_files'] = 120
    return {'schema': 'adaptive.paused-expiry.acceptance.v1',
            'status': 'bounded-installed-paused-expiry-accepted', 'wheel_sha256': WHEEL,
            'installed_package': identity, 'source': source,
            'source_freeze_sha256': PINS['reviewed-source.json'],
            'qualification_manifest_sha256': bindings['qualification_manifest_sha256'],
            'model': h.MODEL, 'quality': h.QUALITY,
            'qualification_bounds': {'task_deadline_s': 900, 'provider_request_limit': 8,
                                     'readiness_deadline_s': 240, 'outer_deadline_s': 1800},
            'software_checks': software(h, rows, inputs, freeze, identity),
            'actual_installation': installation(h, prior, rows, inputs, bindings, identity),
            'accepted_trial': terminal(h, selector, retained, prior, gates, rows, inputs, bindings, identity),
            'failed_trials': {'expiry01_clock': selector.failed_trial(h, rows['failed01'], inputs.hashes['failed01']),
                              'expiry02_tool_thread': selector.failed_thread_trial(h, rows['failed02'], inputs.hashes['failed02'])},
            'limitations': {'task_completion_claimed': False, 'deadline_renewal_claimed': False,
                           'post_expiry_resume_claimed': False, 'computer_restart_recovery_claimed': False,
                           'physical_foreground_overlap_claimed': False, 'performance_claimed': False,
                           'live_M2_milestone_claimed': False},
            'private_input_sha256': {k: inputs.hashes[k] for k in bindings['private_input_sha256']},
            'export_support_sha256': dict(PINS)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        selector, gates = load_module('selection.py'), load_module('gates.py')
        retained, prior, h = selector.helpers(args.repository)
        h.need(not args.output.exists() and args.output.parent.is_dir(), 'output_not_fresh')
        inputs = h.Inputs(args.selection.parent)
        selection = inputs.read('private_selection', args.selection)
        value = build(h, retained, prior, selector, gates, args.repository.resolve(strict=True), selection, inputs)
        value['selection_exporter_sha256'] = h.hash_bytes(inputs.raw('exporter', Path(__file__)))
        for name, expected in PINS.items():
            h.exact(h.hash_bytes(inputs.raw('support:'+name, HERE/name)), expected, 'export_support_changed')
        data = h.encoded(value)
        h.privacy_check(data)
        manifest = {'schema': 'adaptive.public-evidence-files.v1',
                    'source_selection': 'Explicit fields with fixed role hashes; private paths are never exported',
                    'files': {'result.json': h.hash_bytes(data)},
                    'sanitizer_sha256': value['selection_exporter_sha256'],
                    'reused_helper_sha256': '12004621166522cb80682e2bf1e4bc6d19e2ca72aeb585d21ce6408c2a965b33'}
        manifest_data = h.encoded(manifest)
        h.privacy_check(manifest_data)
        inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name, blob in (('result.json', data), ('manifest.json', manifest_data)):
            with (args.output/name).open('xb') as stream:
                stream.write(blob)
        print(json.dumps({'prepared': True, 'published': False, 'files': manifest['files']}))
        return 0
    except (KeyError, IndexError, TypeError, ValueError, OSError, zipfile.BadZipFile) as error:
        # Do not print private paths or raw receipt values on refusal.
        print(json.dumps({'prepared': False, 'reason': str(error) if type(error).__name__ == 'Refused'
                          else type(error).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
