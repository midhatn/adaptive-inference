"""Private fail-closed exporter for controlled-10 with phase-scoped wait accounting.

This does not execute a model, agent, tool, network call, or imported project
module. It reads terminal receipts and writes a NEW private output directory.
Publication and operator-condition attestation remain a separate review.
Earlier foreground measurements have their original harness identity; they are
not relabeled as runs of this successor gateway/agent implementation.
Adapted from validated sanitize_milestone_v5.py; no acceptance gate is replaced
by a component success from an earlier failed or interrupted attempt.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

MODEL = 'qwen3.8-flash-next-iq3_s-adaptive-media-beta'
QUALITY = {'max_tokens': 10923, 'reasoning_effort': 'high', 'reasoning_budget_tokens': 8192,
           'experimental_speed_projection': False, 'strata_tune': {'pcie_frac': .37}}
CONTEXT = {'context_length': 65536, 'threshold': .8, 'threshold_tokens': 46421,
           'reserved_output': 10923, 'max_tokens': 10923}
SDK = '14e1e43a23761b369641208e204365cd6cb9399d'
NATIVE = '744205e4e024b5cbba19e4b560678ffe21e6899e59050929f7af51557f3c6198'
REPORT = {'rows': 4, 'units': 17, 'total_cents': 4350,
          'by_item': {'folder': 1100, 'notebook': 2250, 'pen': 1000}}
ARITHMETIC = {**REPORT, 'by_item': {'apple': 1200, 'banana': 750, 'orange': 2400}}
ARITHMETIC_PROMPT = ('Calculate this CSV: item,quantity,unit_cents\napple,3,200\nbanana,5,150\n'
    'apple,3,200\norange,6,400\n'
    'Reply only a JSON object with rows, units, total_cents, and by_item mapping items to cents. '
    'Use integers and no markdown.')
CORRECTION_PREFIX = 'The acceptance check failed. Correct the result while preserving the original task.\n'
PROBE = {'codec_name': 'h264', 'width': 1280, 'height': 720, 'nb_read_frames': '90'}
SHA = re.compile(r'[0-9a-f]{64}\Z')
IDENT = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
MEASUREMENT = 'GDI paint submission and host-message scheduling; not physical display/input latency'
CONTROLLED_ATTEMPT = 'controlled-10'
HERMES_ATTEMPT = 'hermes-real-02'
CONTROLLED_HARNESS = 'successor-v5/run_validation.py'
CONTROLLED_NATIVE = 'successor-v5/native'
OWNER_HELPERS = ('engine.py','ownership.py','owned_job.py','memory_reader.py','memory_monitor.py')
# Frozen controlled-10 selection; sealed native v4 package is unchanged.
CONTROLLED_PACKAGE_PINS = {'manifest_sha256': 'ce79f32813a632df14e043c020789b1de9260aa34518e5f62f05645323e78213', 'provenance_sha256': '0b101e1150043deaae22722895712902f0c9aa0fb7e1ce7eef91b5386ad2e9b4'}
FROZEN_SOURCE_SHA256 = {
    "successor-v5/run_validation.py": "2f5315dcf53831509493e7f451e187a4ab748072f42992e9997aa17b17f8118e",
    "successor-v5/native/handoff-package.private.json": "2aadfd538bb59fa0701005ae7410f86c5f27340cd5ac0900733ec481d6f4bf54",
    "successor-v5/native/owner_source/source-pins.json": "19f871c8b6ca05becec6f9a76758eac94d9aa38f29951af1e20753bdd7ee7aca",
    "successor-v5/foreground/activity.py": "3c050a620bb5d58938a62b0fbfb44f8f143f5ea466ec1259db502a0cbf49e6ec",
    "successor-v5/foreground/metrics.py": "a0d0e4f7537ed977b57bd460a886960bd2572567e9f4d29d01976e1b0d669a13",
    "successor-v5/foreground/foreground_window.py": "e9f79c0e20883bfef9ded909260516ed3fd0c1e2d620cc181b0c0e1b354bd093",
    "successor-v5/foreground/quiet_window.py": "c1b9c21a3f1f754f1fb95bde848fdbd796bce9d1018afebc7d568bf76f259a84",
    "successor-v5/native/windows_host.py": "7f364433903d29656429f8afcb70ba55e4b85e40e327a8135e4543f95028c6a2",
    "successor-v5/native/native_owner_adapter.py": "b1b75cbf4632b657573aef54bc4c4ca671a5e9aaa75c02d0d3c3022dd97a6b2a",
    "successor-v5/native/owner_source/engine.py": "d0b4174d3b1aff944d749c6094e2953399bf895f31001aa2f8a1180fba18a4f4",
    "successor-v5/native/owner_source/ownership.py": "f419391c84d5d123328b8c3b454253f060e4d5d59db89fedd43fbd2313960b14",
    "successor-v5/native/owner_source/owned_job.py": "4c62671096e2fc2f559a0a0e1807645df5161022701d210f5ba6c810d7b3439f",
    "successor-v5/native/owner_source/memory_reader.py": "d3c36b74a6040b8c743bb7362275fb7fc6c7a22f8aaed38e94798ab193167e86",
    "successor-v5/native/owner_source/memory_monitor.py": "74bb33ccb7a0f6cdb3da630c12ddeac4f0d0504bd6a70af62255495169f634fd",
    "src/adaptive_inference/handoff.py": "a6fa8da1a408eacf151971aa4b488fcc1ca515cb84b9a63451dc14ecdfd44a72",
    "src/adaptive_inference/gateway.py": "261f92078e7691bc8e51cd1d67dd370cb2bfcfb008c0c2c7df44ddfbedc0a8f0",
    "src/adaptive_inference/scheduler.py": "c7f962bd9ef8e44587cadcc02a41fae8a00de7fc15b105848dcdfc4862bd5b4f",
    "src/adaptive_inference/config.py": "a6800a081a1e14a46ee18235dd21c1d1a714e6ef4e879840cd2768c590fde669",
    "src/adaptive_inference/costs.py": "9e8fcd06d39af57392f191b5d5701aa828f134e5141c7e298aa62e0c232224e1",
    "src/adaptive_inference/task_store.py": "39f4efaa0983fea5202ac1027f12c7638787e7da874e26b678a9a3812b1afacc",
    "src/adaptive_inference/feedback.py": "c76eba0110659ae67f4a0efd2ca21aff0987af7e9095998e4db9382de20826c3"
}



class Refused(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise Refused(code)


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def object_hash(value):
    return hash_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def digest(value):
    need(type(value) is str and SHA.fullmatch(value), 'invalid_sha256')
    return value


def identifier(value):
    need(type(value) is str and IDENT.fullmatch(value), 'invalid_identifier')
    return value


def number(value, minimum=0):
    need(type(value) in (int, float) and minimum <= value <= 10**16
         and math.isfinite(value), 'invalid_numeric_field')
    return value


def integer(value, minimum=0):
    need(type(value) is int and minimum <= value <= 10**12, 'invalid_integer_field')
    return value


def true(value, code):
    need(value is True, code)
    return True


def exact(value, expected, code):
    # JSON text equality is type-sensitive (True must not equal integer 1).
    need(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True), code)
    return expected


def parse(data):
    def pairs(rows):
        out = {}
        for key, value in rows:
            need(key not in out, 'duplicate_json_key')
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(Refused('nonfinite_json')))


class Inputs:
    def __init__(self, root):
        self.root = root.resolve(strict=True)
        self.hashes = {}
        self.reads = []

    def raw(self, label, path, limit=16*1024*1024):
        path = Path(path).resolve(strict=True)
        need(path.is_file() and path.stat().st_size <= limit, 'input_missing_or_too_large')
        data = path.read_bytes()
        need(len(data) <= limit, 'input_grew_too_large')
        sha = hash_bytes(data)
        need(label not in self.hashes or self.hashes[label] == sha, 'logical_input_changed')
        self.hashes[label] = sha
        self.reads.append((path, sha))
        return data

    def read(self, label, path):
        return parse(self.raw(label, path))

    def unchanged(self):
        for path, sha in self.reads:
            need(hash_bytes(path.read_bytes()) == sha, 'input_changed_during_export')


def usage(row):
    need(type(row) is dict, 'missing_usage')
    result = {k: integer(row[k]) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    need(result['prompt_tokens'] + result['completion_tokens'] == result['total_tokens'], 'inconsistent_usage')
    need(result['completion_tokens'] <= 10923 and result['prompt_tokens'] + 10923 + 8 <= 65536,
         'quality_or_context_budget_exceeded')
    for key, allowed in [('prompt_tokens_details', ('cached_tokens',)),
                         ('completion_tokens_details', ('reasoning_tokens',))]:
        if key in row and row[key] is not None:
            need(type(row[key]) is dict, 'invalid_usage_details')
            result[key] = {k: integer(row[key][k]) for k in allowed if k in row[key]}
    return result


def quality(row):
    exact(row.get('model'), MODEL, 'wrong_model')
    exact(row.get('quality'), QUALITY, 'quality_changed')


def percentile(values, quantile):
    need(bool(values), 'empty_metric_series')
    return sorted(values)[max(0, math.ceil(len(values)*quantile)-1)]


def foreground(inputs, label, directory):
    result = inputs.read(label+'_summary', directory/'result.json')
    samples = inputs.read(label+'_samples', directory/'samples.json')
    ready = inputs.read(label+'_ready', directory/'ready.json')
    exact(result['measurement'], MEASUREMENT, 'measurement_changed')
    for field in ('valid_foreground_run', 'completed_duration', 'producer_exited'):
        true(result.get(field), 'foreground_'+field)
    need(result.get('error') is None, 'foreground_error')
    need(result.get('duration_s') == 45 and result.get('warmup_s') == 5
         and result.get('target_fps') == 60, 'foreground_contract_changed')
    need(ready['pid'] == result['pid'] and ready['duration_s'] == 45, 'foreground_identity_mismatch')
    frames, observations = samples['frames'], samples['observations']
    need(0 < len(frames) <= 100000 and 0 < len(observations) <= 100000, 'sample_count_bound')
    for rows, time_field in ((frames, 'elapsed_s'), (observations, 'elapsed_s')):
        times = [number(r[time_field]) for r in rows]
        need(all(a <= b for a, b in zip(times, times[1:])), 'sample_time_regressed')
    kept = [r for r in frames if 5 <= r['elapsed_s'] <= 45]
    observed = [r for r in observations if 5 <= r['elapsed_s'] <= 45]
    need(len(kept) >= 600 and len(observed) >= 200 and kept[-1]['elapsed_s'] >= 44.7
         and observed[-1]['elapsed_s'] >= 44.7, 'incomplete_foreground_measurement')
    paints = [number(r['paint_s']) for r in kept]
    intervals = [number((b-a)*1000) for a, b in zip(paints, paints[1:])]
    latencies = [number(r['post_to_paint_ms']) for r in kept]
    flags = []
    for r in observed:
        need(type(r['target_foreground']) is bool and type(r['target_visible']) is bool, 'invalid_foreground_flag')
        flags.append([r['target_foreground'], r['target_visible']])
    calculated = {'frames': len(kept), 'samples': len(observed),
        'foreground_fraction': sum(a and b for a,b in flags)/len(flags),
        'paint_interval_p95_ms': percentile(intervals,.95),
        'paint_interval_p99_ms': percentile(intervals,.99),
        'paint_interval_max_ms': max(intervals),
        'post_to_paint_p95_ms': percentile(latencies,.95),
        'stalls_over_50ms_fraction': sum(x>50 for x in intervals)/len(intervals)}
    for key, val in calculated.items():
        need(number(result[key]) == val, 'foreground_summary_not_reproducible_'+key)
    need(calculated['foreground_fraction'] >= .95, 'insufficient_foreground_coverage')
    sources = result['source_sha256']
    need(set(sources) == {'foreground_window.py','activity.py','metrics.py'}, 'foreground_source_set_changed')
    safe = {'measurement': MEASUREMENT, 'duration_s':45, 'warmup_s':5, 'target_fps':60,
            'valid_foreground_run':True, **calculated,
            'source_sha256':{k:digest(v) for k,v in sources.items()},
            'started_monotonic_s':number(ready['started_monotonic_s'])}
    arrays = {'paint_intervals_ms':intervals, 'post_to_paint_ms':latencies,
              'foreground_visible_pairs':flags,
              'scope':'Only retained 5–45 second measurement samples; no process/input/window metadata.'}
    return safe, arrays


def comparison(receipt, summaries):
    if 'comparison' in receipt:
        receipt = receipt['comparison']
    b,u,c = summaries
    bp,up,cp = (x['paint_interval_p95_ms'] for x in summaries)
    valid = all(x['valid_foreground_run'] for x in summaries) and bp <= 25
    limit = max(25,bp*1.25)
    accepted = bool(valid and cp <= limit and c['stalls_over_50ms_fraction'] <= .01)
    degraded = bool(valid and (up > limit or u['stalls_over_50ms_fraction'] > .01))
    calculated = {'valid_comparison':bool(valid), 'controlled_p95_limit_ms':limit,
                  'controlled_responsiveness_passed':accepted,
                  'uncontrolled_degradation_detected':degraded,
                  'improvement_observed':bool(accepted and degraded and cp<up)}
    for k,v in calculated.items():
        need(type(receipt.get(k)) is type(v) and receipt[k] == v or
             k == 'controlled_p95_limit_ms' and number(receipt.get(k)) == v,
             'comparison_mismatch_'+k)
    need(valid and accepted, 'comparison_not_accepted')
    return {**calculated,'requires_external_condition_attestation':True,
            'scope':'One GDI foreground workload; numerical acceptance is separate from operator condition attestation and native/task receipts.'}


def release(proof):
    for k in ('released','cleanup_confirmed','port_free'):
        true(proof.get(k),'release_'+k)
    n=integer(proof.get('retained_processes'),1)
    need(integer(proof.get('confirmed_process_exits'),1)==n,'release_exit_count')
    result={'owner_id':identifier(proof['owner_id']),'released':True,'cleanup_confirmed':True,
            'port_free':True,'retained_processes':n,'confirmed_process_exits':n}
    if 'server_exit_code' in proof:
        exact(proof['server_exit_code'],0,'native_server_exit')
        result['server_exit_code']=0
    for row in proof.get('retained_at_stop',[]):
        true(row.get('exited'),'retained_handle_not_exited')
    return result


def capacity(row):
    true(row.get('complete'),'capacity_incomplete')
    return {'complete':True, **{k:number(row[k]) for k in
        ('sampled_at','available_ram_gib','available_commit_gib','available_vram_mib')}}


def native_profile(inputs,label,directory):
    row=inputs.read(label+'_owner',directory/'initial-owner.private.json')
    for k in ('ready','loaded'):
        true(row.get(k),'initial_owner_not_ready')
    exact(row['model'],MODEL,'owner_model_changed')
    v=row['verification']; exact(v['native_sha256'],NATIVE,'native_binary_changed')
    need(v.get('model_asset_content_hashed') is False,'unexpected_asset_attestation_scope')
    policy=row['native_status']['memory_policy']
    need(policy['idle_unload_s']==0,'comparison_owner_idle_profile_mismatch')
    exact(row['native_status']['context'],{'native':65536,'max_positions':65536},'owner_context_changed')
    startup=row['startup_cache_plan']
    return {'owner_id':identifier(row['owner_id']),
        'verification':{k:digest(v[k]) for k in ('manifest_sha256','provenance_sha256','native_sha256')},
        'model_asset_content_hashed':False,'context':65536,'idle_unload_s':0,
        'effective_config_sha256':digest(row['effective_config_sha256']),
        'expected_launch_attestation':digest(row['expected_launch_attestation']),
        'startup_cache':{k:number(startup[k]) for k in ('configured_cap_gib','available_ram_commit_gib',
            'overhead_gib','required_headroom_gib','raw_allowance_gib','resident_budget_gib')}}


def controlled_native_binding(inputs,profile,directory):
    """Bind the recorded v4 owner to its exact package/config, not an old copy.

    This reuses the owner package's existing manifest and source-pin contracts.
    It does not import the owner, load a model, or infer all-module load evidence.
    """
    native=inputs.root/CONTROLLED_NATIVE
    config=inputs.read('controlled_operator_config',native/'handoff-package.private.json')
    package=Path(config['package']).resolve(strict=True)
    need(package.is_dir(),'controlled_package_missing')
    for key in ('manifest_sha256','provenance_sha256'):
        exact(digest(config[key]),profile['verification'][key],'controlled_package_pin_mismatch')
        exact(config[key],CONTROLLED_PACKAGE_PINS[key],'controlled_frozen_package_changed')
    exact(inputs.hashes['controlled_operator_config'],
          FROZEN_SOURCE_SHA256[CONTROLLED_NATIVE+'/handoff-package.private.json'],
          'controlled_frozen_config_changed')
    manifest=inputs.read('controlled_package_manifest',package/'MANIFEST.json')
    provenance=inputs.read('controlled_package_provenance',package/'PROVENANCE.json')
    exact(inputs.hashes['controlled_package_manifest'],config['manifest_sha256'],'controlled_manifest_changed')
    exact(inputs.hashes['controlled_package_provenance'],config['provenance_sha256'],'controlled_provenance_changed')
    exact(manifest.get('schema'),'adaptive-engine-manifest.v1','controlled_manifest_schema')
    files=manifest['files']
    exact(files.get('PROVENANCE.json'),config['provenance_sha256'],'manifest_provenance_mismatch')
    exact(files.get('runtime/native/strata.exe'),NATIVE,'manifest_native_changed')
    exact(provenance.get('native_sha256'),NATIVE,'provenance_native_changed')
    handoff=provenance['handoff_profile']
    exact(handoff.get('idle_unload_s'),0,'provenance_idle_profile_changed')
    exact(handoff.get('idle_controller'),'desktop_host','provenance_idle_controller_changed')
    need(handoff.get('quality_model_guard_changes') is False,'provenance_quality_guard_changed')
    pins=inputs.read('controlled_owner_source_pins',native/'owner_source/source-pins.json')
    exact(inputs.hashes['controlled_owner_source_pins'],
          FROZEN_SOURCE_SHA256[CONTROLLED_NATIVE+'/owner_source/source-pins.json'],
          'controlled_frozen_owner_pins_changed')
    need(set(pins['files'])==set(OWNER_HELPERS),'controlled_owner_helper_set_changed')
    helpers={}
    for name in OWNER_HELPERS:
        source=hash_bytes(inputs.raw('controlled_helper_source_'+name,native/'owner_source'/name))
        installed=hash_bytes(inputs.raw('controlled_helper_package_'+name,package/name))
        exact(source,digest(pins['files'][name]['preserved_sha256']),'controlled_helper_source_changed')
        exact(installed,source,'controlled_package_helper_changed')
        exact(files.get(name),source,'controlled_manifest_helper_changed')
        helpers[name]=source
    template=inputs.read('controlled_server_template',package/'config/server-template.json')
    exact(inputs.hashes['controlled_server_template'],files.get('config/server-template.json'),
          'controlled_template_changed')
    row=inputs.read('controlled_owner',directory/'initial-owner.private.json')
    owner_run=Path(row['run']).resolve(strict=True)
    need(owner_run.is_relative_to(package/'runs'),'controlled_owner_run_outside_package')
    effective=inputs.read('controlled_effective_config',owner_run/'server.json')
    exact(inputs.hashes['controlled_effective_config'],profile['effective_config_sha256'],
          'controlled_effective_config_changed')
    # Reproduce only the existing template substitutions and measured RAM-cache
    # adjustment. Every other field, including quality/context, must match.
    expected=parse(json.dumps(template).replace('@RUN@',owner_run.as_posix()))
    args=expected['args']; index=args.index('--resident-budget-gib')+1
    chosen=number(row['startup_cache_plan']['resident_budget_gib'],1)
    need(chosen<=number(float(args[index]),1),'controlled_cache_exceeds_configured_cap')
    args[index]=format(chosen,'.8g')
    exact(effective,expected,'controlled_effective_template_mismatch')
    exact(effective.get('idle_unload_s'),0,'controlled_effective_idle_changed')
    return {'manifest_sha256':config['manifest_sha256'],'provenance_sha256':config['provenance_sha256'],
        'operator_config_sha256':inputs.hashes['controlled_operator_config'],
        'owner_source_pins_sha256':inputs.hashes['controlled_owner_source_pins'],
        'owner_helper_sha256':helpers,'template_sha256':inputs.hashes['controlled_server_template'],
        'effective_config_sha256':profile['effective_config_sha256'],
        'template_substitution_and_resident_cache_verified':True,
        'scope':'Exact controlled owner receipt, v4 package manifest/provenance, helper sources and effective initial config; not historical owner equivalence or additional runtime-load attestation.'}


def inference(rows):
    need(type(rows) is list and len(rows)==2,'exactly_two_arithmetic_requests_required')
    selected=[]
    for i,row in enumerate(rows):
        quality(row); exact(row['answer'],ARITHMETIC,'incorrect_arithmetic')
        need(row['index']==i and row['finish_reason']=='stop'
             and row['request_class']==row['gateway_class']=='background','arithmetic_boundary_changed')
        start,end=number(row['requested_at']),number(row['completed_at'])
        need(end>=start,'inference_time_regressed')
        selected.append({'index':i,'requested_at':start,'completed_at':end,'elapsed_s':end-start,
                         'answer':ARITHMETIC,'finish_reason':'stop','usage':usage(row['usage']),
                         'request_class':'background','gateway_class':'background',
                         'request_sha256':digest(row['request_sha256'])})
    need(selected[1]['requested_at']>=selected[0]['completed_at'],'arithmetic_requests_overlapped')
    return selected


def arithmetic_verdict(content,finish):
    """Independent exact acceptance; no model/generated feedback is trusted."""
    try:
        answer=parse(content)
        if (type(answer) is not dict or set(answer)!=set(ARITHMETIC)
                or any(type(answer[key]) is not int for key in ('rows','units','total_cents'))
                or type(answer['by_item']) is not dict or set(answer['by_item'])!=set(ARITHMETIC['by_item'])
                or any(type(value) is not int for value in answer['by_item'].values())):
            raise ValueError('schema')
    except (ValueError,TypeError,KeyError):
        feedback=('Return only one JSON object with exactly rows, units, total_cents, and by_item. '
                  'Use JSON integers for every numeric value, one entry for each CSV item, '
                  'no duplicate keys, no markdown and no extra text. Recompute from the original CSV.')
    else:
        feedback='' if answer==ARITHMETIC else (
            'The independent arithmetic check rejected the result. Recount CSV data rows, '
            'sum quantities, multiply quantity by unit_cents for each row, group all repeated '
            'item rows, and sum the item totals. Recompute from the original CSV.')
    if finish!='stop':
        feedback=('The response did not finish with the required stop reason. Return a complete final '
                  'JSON answer under the unchanged response budget. '+feedback).strip()
    return {'accepted':not feedback,'feedback':feedback}


def arithmetic_feedback(inputs,directory,rows):
    """Validate every v5 attempt/file and reconstruct its actual correction chain."""
    selected=inference(rows)
    ledger=inputs.read('controlled_arithmetic_tasks',directory/'inference-tasks.private.json')
    attempts=inputs.read('controlled_arithmetic_attempts',directory/'inference-attempts.private.json')
    need(type(ledger) is dict and set(ledger)=={'logical_task_count','maximum_attempts_per_task',
         'maximum_requests','request_count','tasks'},'arithmetic_task_ledger_fields')
    for key,value in (('logical_task_count',2),('maximum_attempts_per_task',3),('maximum_requests',6)):
        exact(ledger[key],value,'arithmetic_task_bounds_changed')
    need(type(attempts) is list and 2<=len(attempts)<=6,'arithmetic_attempt_count')
    exact(ledger['request_count'],len(attempts),'arithmetic_request_count_changed')
    need(type(ledger['tasks']) is list and len(ledger['tasks'])==2,'arithmetic_task_count')
    safe_attempts=[]; expected_files=set(); offset=0; previous_end=0
    for index,(task,receipt,safe) in enumerate(zip(ledger['tasks'],rows,selected)):
        exact(receipt.get('index'),index,'arithmetic_task_index_changed')
        count=integer(task.get('attempts'),1);need(count<=3,'arithmetic_attempt_bound')
        exact(task,{'index':index,'status':'accepted','accepted':True,'attempts':count},'arithmetic_task_not_accepted')
        exact(receipt.get('attempts'),count,'arithmetic_receipt_attempt_count')
        exact(receipt.get('request_count'),count,'arithmetic_receipt_request_count')
        exact(receipt.get('max_attempts'),3,'arithmetic_receipt_bound')
        indices=list(range(offset,offset+count))
        exact(receipt.get('attempt_request_indices'),indices,'arithmetic_receipt_attempt_indices')
        messages=[{'role':'user','content':ARITHMETIC_PROMPT}]; task_attempts=[]
        for attempt,position in enumerate(indices,1):
            need(position<len(attempts),'arithmetic_attempt_missing')
            row=attempts[position]
            need(type(row) is dict and not row.get('error'),'arithmetic_attempt_fatal')
            for key,value in (('index',index),('attempt',attempt),('request_index',position),
                              ('status','validated'),('http_status',200),
                              ('request_class','background'),('gateway_class','background')):
                exact(row.get(key),value,'arithmetic_attempt_boundary_changed')
            quality(row)
            stem=f'task-{index}-attempt-{attempt}'
            request_name=stem+'-request.private.json';raw_name=stem+'-response.private.bin'
            parsed_name=stem+'-response.private.json'
            exact(row.get('request_file'),request_name,'arithmetic_request_path_changed')
            exact(row.get('response_file'),raw_name,'arithmetic_response_path_changed')
            expected_files.update((request_name,raw_name,parsed_name))
            body=inputs.read('arithmetic_'+stem+'_request',directory/request_name)
            exact(body,{'model':MODEL,'messages':messages,**QUALITY},'arithmetic_request_or_feedback_chain_changed')
            request_hash=hash_bytes(json.dumps(body,sort_keys=True).encode())
            exact(row.get('request_sha256'),request_hash,'arithmetic_request_hash_changed')
            raw=inputs.raw('arithmetic_'+stem+'_response',directory/raw_name)
            exact(row.get('response_sha256'),hash_bytes(raw),'arithmetic_response_hash_changed')
            data=parse(raw)
            exact(inputs.read('arithmetic_'+stem+'_parsed',directory/parsed_name),data,'arithmetic_parsed_response_changed')
            need(type(data) is dict and data.get('model')==MODEL,'arithmetic_response_model_changed')
            choices=data.get('choices')
            need(type(choices) is list and len(choices)==1 and type(choices[0]) is dict,'arithmetic_unknown_envelope')
            choice=choices[0];message=choice.get('message');finish=choice.get('finish_reason')
            need(type(message) is dict and type(message.get('content')) is str
                 and finish in ('stop','length','content_filter','tool_calls'),'arithmetic_unknown_completion')
            content=message['content'];verdict=arithmetic_verdict(content,finish)
            exact(row.get('finish_reason'),finish,'arithmetic_finish_reason_changed')
            exact(row.get('usage'),data.get('usage'),'arithmetic_usage_mismatch')
            safe_usage=usage(data.get('usage'))
            exact(row.get('verdict'),verdict,'arithmetic_verdict_changed')
            exact(row.get('retryable'),not verdict['accepted'] and attempt<3,'arithmetic_retry_policy_changed')
            need(verdict['accepted']==(attempt==count),'arithmetic_hidden_acceptance_or_exhaustion')
            start,end=number(row['requested_at']),number(row['completed_at'])
            need(end>=start>=previous_end,'arithmetic_attempt_times_reordered')
            previous_end=end
            safe_attempt={'task_index':index,'attempt':attempt,'request_index':position,
                'requested_at':start,'completed_at':end,'request_elapsed_s':end-start,
                'accepted':verdict['accepted'],'finish_reason':finish,'usage':safe_usage,
                'request_class':'background','gateway_class':'background',
                'request_sha256':request_hash,'response_sha256':hash_bytes(raw),
                'validator_feedback_sha256':hash_bytes(verdict['feedback'].encode())}
            safe_attempts.append(safe_attempt);task_attempts.append(row)
            if verdict['accepted']:
                exact(parse(content),ARITHMETIC,'arithmetic_final_answer_changed')
                exact(row.get('answer'),ARITHMETIC,'arithmetic_accepted_ledger_answer_changed')
            else:
                need('answer' not in row,'arithmetic_rejected_answer_claimed_accepted')
                messages.extend([{'role':'assistant','content':content},
                                 {'role':'user','content':CORRECTION_PREFIX+verdict['feedback']}])
        first,last=task_attempts[0],task_attempts[-1]
        exact(receipt['requested_at'],first['requested_at'],'arithmetic_task_start_changed')
        exact(receipt['completed_at'],last['completed_at'],'arithmetic_task_end_changed')
        exact(receipt['request_sha256'],last['request_sha256'],'arithmetic_final_request_changed')
        exact(receipt['usage'],last['usage'],'arithmetic_final_usage_changed')
        safe['logical_task_duration_s']=safe.pop('elapsed_s')
        safe['final_request_usage']=safe.pop('usage')
        safe.update(attempts=count,request_count=count,max_attempts=3,attempt_request_indices=indices,
                    timing_scope='First attempt through accepted final attempt, including corrections and waits.',
                    final_request_fields='Request hash, token usage and finish reason refer to the accepted last attempt.')
        offset+=count
    need(offset==len(attempts),'arithmetic_hidden_attempts')
    actual_files={path.name for path in directory.glob('task-*-attempt-*') if path.is_file()}
    exact(sorted(actual_files),sorted(expected_files),'arithmetic_unlisted_attempt_files')
    return {'logical_task_count':2,'request_count':len(attempts),'maximum_attempts_per_task':3,
        'maximum_requests':6,'logical_tasks':selected,'attempts':safe_attempts,
        'first_request_completed_at':safe_attempts[0]['completed_at'],
        'scope':'Every bounded request and deterministic verdict checked; no first-pass or causal performance claim.'}


def release_timing(events,window_start,completed):
    first=next(row['at'] for row in events if 'release' in row)
    need(first>=completed,'release_before_active_response_completed')
    drain=next(row['at'] for row in events if row.get('to')=='draining')
    return {'window_started_at':window_start,'window_duration_s':45,'draining_at':drain,
            'first_request_completed_at':completed,'first_release_confirmed_at':first,
            'release_after_window_start_s':first-window_start,'release_after_first_completion_s':first-completed,
            'release_within_animation_window':first<=window_start+45,
            'scope':'Admission closes before release; the first HTTP attempt drains normally. This is not the later logical task completion or instantaneous resource yield.'}


def video(inputs,directory,row):
    saved=inputs.read('video_receipt',directory/'video-receipt.json')
    exact(row,saved,'video_embedded_receipt_mismatch')
    true(row.get('passed'),'video_failed'); exact(row['probe'],PROBE,'video_probe_mismatch')
    exact(row['owned_process_exit_codes'],[0,0,0],'video_three_zero_exits_required')
    need(len(row['owned_processes'])==3,'video_process_count')
    processes=[]
    for i,p in enumerate(row['owned_processes']):
        exact(p['exit_code'],0,'video_child_failed')
        need(p['executable_name'] in ('ffmpeg.exe','ffprobe.exe','ffmpeg','ffprobe'),'unexpected_video_executable')
        expected=row['ffprobe_sha256'] if i==1 else row['ffmpeg_sha256']
        exact(p['executable_sha256'],expected,'video_executable_pin_mismatch')
        processes.append({'step':('encode','probe','decode')[i], 'exit_code':0,
                          'started_at':number(p['started_at']),'executable_sha256':digest(expected)})
    artifact=inputs.raw('video_artifact',directory/'handoff-video.mp4',32*1024*1024)
    need(hash_bytes(artifact)==row['video_sha256'],'video_artifact_changed')
    cap=capacity(row['capacity'])
    need(cap['available_ram_gib']>=8 and cap['available_commit_gib']>=12
         and cap['available_vram_mib']>=6000,'video_capacity_below_admission')
    return {'passed':True,'capacity':cap,'requirements':{'ram_gib':8,'commit_gib':12,'vram_mib':6000},
            'probe':PROBE,'video_sha256':digest(row['video_sha256']),
            'video_bytes':len(artifact),'owned_processes':processes,
            'owned_process_exit_codes':[0,0,0]}


def recovery(inputs,controlled,hermes):
    row=inputs.read('recovery_receipt',controlled/'recovery-processes.json')
    true(row.get('passed'),'recovery_failed')
    true(row.get('effect_receipts_unchanged'),'effect_receipts_changed')
    exact(row.get('dispatched_file_effects'),1,'write_count_not_one')
    phases=row['processes']; need(len(phases)==2,'recovery_two_processes_required')
    before,after=phases
    need(before['phase']=='before_restart' and after['phase']=='after_restart'
         and before['pid']!=after['pid'],'recovery_process_identity')
    true(before.get('safe_boundary'),'missing_safe_boundary')
    integer(before['exit_code'],-2**31); need(before['exit_code']!=0,'first_worker_not_terminated')
    exact(after['exit_code'],0,'resumed_worker_failed')
    final=row['resume']; quality(final)
    for k in ('passed','resumed','completed'):
        true(final.get(k),'resume_'+k)
    need(final.get('fixture') is False and final['sdk_revision']==SDK,'not_real_pinned_sdk')
    exact(final['context'],CONTEXT,'recovery_context_changed')
    exact(final['report'],REPORT,'recovery_report_incorrect')
    plan=inputs.read('recovery_plan',hermes/'plan.json')
    quality(plan); need(plan.get('fixture') is False and plan['sdk_revision']==SDK,'recovery_plan_mismatch')
    need(plan['task_id']=='orders-report' and plan['max_requests']==8,'recovery_task_contract')
    saved=inputs.read('resumed_worker_result',hermes/f"result-{after['pid']}.json")
    for k in final:
        exact(saved.get(k),final[k],'resumed_result_mismatch')
    report=inputs.read('report_artifact',hermes/'work/report.json')
    exact(report,REPORT,'report_artifact_incorrect')
    report_sha=inputs.hashes['report_artifact']
    for value in (row['report_sha256'],before['report_sha256'],final['artifacts']['report.json']):
        need(digest(value)==report_sha,'report_hash_mismatch')
    effects=inputs.raw('effect_receipts',hermes/'effect-receipts.jsonl')
    need(hash_bytes(effects)==row['effect_receipts_sha256'],'effect_receipt_hash_mismatch')
    effects=[parse(line) for line in effects.splitlines() if line.strip()]
    need(len(effects)==1 and effects[0]['name']=='write_file'
         and effects[0]['artifact_sha256']==report_sha,'effect_content_mismatch')
    pause=inputs.read('safe_pause',hermes/'pause.json')
    need(pause['boundary']=='safe_after_write' and pause['pid']==before['pid']
         and pause['revision']==before['boundary_revision']
         and pause['history_sha256']==before['native_history_sha256'],'safe_pause_mismatch')
    # Read the already-terminal checkpoint with stdlib only. Never import the SDK
    # or replay a callback; raw prompt/transcript content is only hashed/compared.
    database=hermes/'task.sqlite3'
    inputs.raw('task_database',database,64*1024*1024)
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        task=db.execute('SELECT prompt,metadata,state,inflight,reconciliation FROM tasks WHERE task_id=?',
                        ('orders-report',)).fetchone()
        old=db.execute('SELECT payload FROM history WHERE task_id=? AND revision=?',
                       ('orders-report',before['boundary_revision'])).fetchone()
        created=db.execute('SELECT payload FROM history WHERE task_id=? AND revision=0',
                           ('orders-report',)).fetchone()
    need(task is not None and old is not None and created is not None,'checkpoint_history_missing')
    prompt,metadata,state,inflight,reconciliation=task
    state=parse(state); old=parse(old[0])['state']; created=parse(created[0])
    need(inflight is None and reconciliation==0 and state['status']==state['phase']=='accepted',
         'checkpoint_not_terminal')
    need(prompt==created['prompt'] and parse(metadata)==created['metadata']
         and state['messages'][0]==created['state']['messages'][0],'original_task_changed')
    prompt_sha=object_hash(prompt)
    need(prompt_sha==row['original_prompt_sha256']==final['original_prompt_sha256'],'original_prompt_hash')
    need(object_hash(old['native_history'])==before['native_history_sha256']
         and state['native_history'][:len(old['native_history'])]==old['native_history'],
         'native_prefix_changed')
    need(len(state['native_history'])==final['transcript_rows']
         and object_hash(state['native_history'])==final['transcript_sha256'],'final_transcript_hash')
    calls=integer(final['provider_calls'],1)
    need(state['requests']-old['requests']==calls,'request_lineage_changed')
    wires=inputs.read('recovery_wire_observations',hermes/'wire-observations.json')
    need(len(wires)==len(row['wire_quality'])==before['provider_calls']+calls<=8,'wire_count_changed')
    selected=[]
    for wire,record in zip(wires,row['wire_quality']):
        quality(wire); need(wire['class']=='normal' and wire['finish_reason'] in ('stop','tool_calls'),
                            'wire_class_or_finish_changed')
        for k,v in record.items():
            exact(wire.get(k),v,'wire_receipt_mismatch')
        need(type(wire['tool_names']) is list and sorted(wire['tool_names'])==
             ['patch','read_file','search_files','write_file'],
             'unexpected_tool_schema')
        start,end=number(wire['started_at']),number(wire['finished_at'])
        need(end>=start,'wire_time_regressed')
        selected.append({'class':'normal','finish_reason':wire['finish_reason'],
            'started_at':start,'finished_at':end,'elapsed_s':end-start,'usage':usage(wire['usage']),
            'tool_names':wire['tool_names'], 'gateway_request_id':identifier(wire['gateway_request_id']),
            **{k:digest(wire[k]) for k in ('body_sha256','messages_sha256','tools_sha256')}})
    sources={}
    for name in ('admission.py','recovery.py','run_recovery.py','test_recovery.py','source-lock.json'):
        expected=digest(row['source_sha256'][name])
        need(hash_bytes(inputs.raw('recovery_source_'+name,inputs.root/'hermes-recovery-v2'/name))==expected,
             'recovery_source_changed')
        sources[name]=expected
    # No raw plan paths are exported. Only these exact logical inputs are mapped.
    pin_suffixes={'admission.py':'admission.py','recovery.py':'recovery.py','run_recovery.py':'run_recovery.py',
        'task_store.py':'task_store.py','run_task.py':'hermes_task_helper.py',
        'config.yaml':'isolated_config.yaml','__init__.py':'checkpoint_plugin.py',
        'plugin.yaml':'checkpoint_plugin.yaml','orders.csv':'synthetic_orders.csv'}
    need(len(plan['pins'])==len(pin_suffixes),'plan_source_set_changed')
    plan_pins={}
    for path,sha in plan['pins'].items():
        name=Path(path).name
        need(name in pin_suffixes and pin_suffixes[name] not in plan_pins,'unknown_plan_pin')
        need(hash_bytes(inputs.raw('plan_pin_'+pin_suffixes[name],Path(path)))==digest(sha),'plan_pin_changed')
        plan_pins[pin_suffixes[name]]=sha
    wait=resource_wait(inputs,controlled,hermes,row,state,old)
    return {'passed':True,'fixture':False,'sdk_revision':SDK,'context':CONTEXT,
        'original_prompt_sha256':prompt_sha,'original_task_preserved':True,'native_prefix_preserved':True,
        'before_native_history_sha256':digest(before['native_history_sha256']),
        'final_native_history_sha256':digest(final['transcript_sha256']),
        'transcript_rows':integer(final['transcript_rows'],1),'report':REPORT,'report_sha256':report_sha,
        'effect_receipts_sha256':digest(row['effect_receipts_sha256']),
        'effect_receipts_unchanged':True,'dispatched_file_effects':1,
        'provider_calls_before_restart':integer(before['provider_calls'],1),'provider_calls_after_restart':calls,
        'processes':[{'phase':p['phase'],'exit_code':p['exit_code']} for p in phases],
        'wire_receipts':selected,'source_sha256':sources,'plan_input_sha256':plan_pins,
        'resource_wait':wait,
        'scope':'One actual process restart at a durable safe file-tool boundary; uncertain-effect refusal is separate SDK fixture evidence, not an extra real-model run or OS reboot.'}


def resource_wait(inputs,controlled,hermes,row,state,before):
    """Recheck actual safe waiting and optional proven non-dispatch attempts."""
    deadline=number(row['deadline_monotonic'])
    exact(state.get('deadline_monotonic'),deadline,'final_deadline_changed')
    exact(before.get('deadline_monotonic'),deadline,'restart_deadline_changed')
    instance=identifier(row['gateway_instance'])
    need(re.fullmatch(r'[0-9a-f]{32}',instance),'invalid_gateway_instance')
    ready=inputs.read('recovery_controller_ready',hermes/'controller-ready.json')
    true(ready.get('ready'),'controller_not_ready')
    exact(ready.get('gateway_instance'),instance,'controller_gateway_changed')
    quality(ready)
    summary,series=foreground(inputs,'agent_foreground',controlled/'hermes-foreground')
    exact(inputs.read('agent_foreground_embedded',controlled/'hermes-foreground/result.json'),
          row['agent_foreground'],'agent_foreground_receipt_mismatch')
    need(summary['paint_interval_p95_ms']<=25 and summary['stalls_over_50ms_fraction']<=.01,
         'agent_foreground_responsiveness_failed')
    process=row['agent_foreground_process']
    true(process.get('same_active_ticket_at_ready'),'no_active_agent_at_visible_readiness')
    exact(process.get('active_class_at_ready'),'normal','active_agent_class_changed')
    sequence=integer(process['active_sequence_at_ready'])
    # The first two exact arithmetic calls precede the first agent request.
    # Deferred attempts can consume ticket sequence numbers; do not invent a
    # fixed first-agent sequence or compare wall-time wire rows to monotonic UI.
    observed=number(process['observed_at_monotonic'])
    need(summary['started_monotonic_s']<=observed<=summary['started_monotonic_s']+45,
         'active_agent_readiness_time_outside_window')
    exact(process.get('exit_code'),0,'agent_foreground_process_failed')
    ready_ui=inputs.read('agent_foreground_ready_identity',controlled/'hermes-foreground/ready.json')
    result_ui=inputs.read('agent_foreground_result_identity',controlled/'hermes-foreground/result.json')
    need(process['pid']==ready_ui['pid']==result_ui['pid'],'agent_foreground_process_identity')
    exact(process.get('ready_sha256'),inputs.hashes['agent_foreground_ready_identity'],'agent_ready_hash_changed')
    exact(process.get('result_sha256'),inputs.hashes['agent_foreground_result_identity'],'agent_result_hash_changed')
    waits=row['waiting_observations']
    need(type(waits) is list and 10<=len(waits)<=18000,'waiting_sample_count')
    stamps=[number(w['at']) for w in waits]
    need(all(a<=b for a,b in zip(stamps,stamps[1:])) and stamps[-1]-stamps[0]>=1,
         'waiting_observation_span')
    # The collector begins at worker startup, before the animation exists.
    # Preserve and validate those samples, but never count them toward the
    # foreground wait gate. Bind all observations to this actual worker phase.
    phase_events=[parse(line) for line in inputs.raw('controlled_phase_events',
                  controlled/'events.jsonl').splitlines() if line.strip()]
    starts=[e for e in phase_events if e.get('kind')=='hermes_phase'
            and e.get('phase')=='before_restart']
    restarts=[e for e in phase_events if e.get('kind')=='hermes_process_restart']
    need(len(starts)==len(restarts)==1,'ambiguous_agent_wait_phase')
    phase_start=number(starts[0]['at']); safe_restart=number(restarts[0]['at'])
    true(restarts[0].get('safe_boundary'),'wait_phase_restart_not_safe')
    window_start=number(summary['started_monotonic_s'])
    need(phase_start<=window_start<=observed<=safe_restart<=deadline,
         'invalid_agent_wait_phase')
    need(stamps[0]>=phase_start and stamps[-1]<=safe_restart,
         'waiting_outside_agent_attempt')
    qualified=[w for w in waits if w['at']>=window_start]
    need(len(qualified)>=10 and qualified[-1]['at']-qualified[0]['at']>=1,
         'foreground_wait_sample_count_or_span')
    need(all(w['controller_state'] in ('draining','releasing','parked','restoring')
             and w['active'] is False for w in qualified),
         'foreground_wait_not_parked_or_draining')
    revision_order=[integer(w['task_revision'],1) for w in waits]
    boundary_revision=integer(row['processes'][0]['boundary_revision'],1)
    need(all(a<=b for a,b in zip(revision_order,revision_order[1:]))
         and all(revision<boundary_revision for revision in revision_order),
         'waiting_revision_outside_before_restart_history')
    revisions=set(revision_order)
    need(all(w['controller_state'] in ('ready','draining','releasing','parked','restoring')
             and type(w['active']) is bool for w in waits),'invalid_waiting_state')
    with closing(sqlite3.connect((hermes/'task.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        for revision in revisions:
            found=db.execute('SELECT payload FROM history WHERE task_id=? AND revision=?',
                             ('orders-report',revision)).fetchone()
            need(found is not None,'waiting_history_missing')
            checkpoint=parse(found[0]); saved=checkpoint['state']
            need(checkpoint.get('operation') is None and checkpoint.get('requires_reconciliation') is False
                 and saved.get('phase')=='waiting_admission' and saved.get('status')=='pending'
                 and type(saved.get('pending_request')) is dict,'waiting_not_durable_safe_boundary')
            exact(saved.get('deadline_monotonic'),deadline,'waiting_deadline_changed')
    attempts=integer(state.get('admission_attempts'))
    proofs=state.get('admission_deferrals')
    need(type(proofs) is list and len(proofs)<=32 and attempts<=32,'admission_attempt_bound')
    ledger_path=hermes/'admission-attempts.json'
    ledger=inputs.read('deferred_attempt_ledger',ledger_path) if ledger_path.exists() else []
    need(type(ledger) is list and len(ledger)==len(proofs),'deferral_ledger_count')
    wires=inputs.read('recovery_wire_observations',hermes/'wire-observations.json')
    completed_bodies={digest(w['body_sha256']) for w in wires}
    safe_proofs=[]; ids=set()
    for evidence,record in zip(proofs,ledger):
        need(type(evidence) is dict and set(evidence)=={'schema','http_status','dispatched',
             'gateway_instance','attempt_id','body_sha256'},'deferral_proof_shape')
        exact(evidence.get('schema'),'adaptive.not-dispatched.v1','deferral_schema')
        exact(evidence.get('http_status'),503,'deferral_http_status')
        need(evidence.get('dispatched') is False,'deferral_was_dispatched')
        exact(evidence.get('gateway_instance'),instance,'deferral_gateway_changed')
        attempt=identifier(evidence['attempt_id'])
        need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',attempt)
             and attempt not in ids,'deferral_attempt_reused'); ids.add(attempt)
        need(digest(evidence['body_sha256']) in completed_bodies,'deferred_body_not_completed_unchanged')
        exact(record.get('proof'),evidence,'deferral_proof_ledger_mismatch')
        need(number(record['finished_at'])>=number(record['started_at']),'deferral_time_regressed')
        safe_proofs.append(evidence)
    need(attempts==integer(state['requests'])+len(proofs),'admission_attempt_lineage')
    # Worker result counters are additional corroboration, not dispatch proof.
    worker=inputs.read('resumed_worker_admission_counters',hermes/f"result-{row['processes'][1]['pid']}.json")
    exact(worker.get('admission_attempts'),attempts,'worker_admission_count_changed')
    exact(worker.get('admission_deferrals'),len(proofs),'worker_deferral_count_changed')
    return {'passed':True,'gateway_instance':instance,'deadline_monotonic':deadline,
        'same_deadline_across_restart':True,'safe_wait_samples':len(qualified),
        'safe_wait_span_s':qualified[-1]['at']-qualified[0]['at'],
        'waiting_revisions_verified':len(revisions),
        'all_wait_samples_verified':len(waits),
        'pre_foreground_wait_samples':len(waits)-len(qualified),
        'pre_foreground_samples_counted_toward_gate':False,
        'worker_phase_started_at':phase_start,'safe_restart_at':safe_restart,
        'foreground_wait_started_at':qualified[0]['at'],
        'foreground_wait_ended_at':qualified[-1]['at'],
        'agent_foreground':summary,'agent_foreground_series':series,
        'active_sequence_at_visible_readiness':sequence,'same_active_ticket_at_ready':True,
        'agent_foreground_exit_code':0,'admission_attempts':attempts,'proven_deferrals':safe_proofs,
        'scope':'Safe task waiting while desktop admission was closed. Only complete matching gateway receipts authorize non-dispatched reissue; zero live deferrals does not demonstrate the race path. Active generation drains normally.'}


def handoff_events(rows):
    need(type(rows) is list and 1<=len(rows)<=256,'handoff_event_count')
    selected=[]; previous=-1
    states={'uninitialized','ready','draining','releasing','parked','restoring','fault'}
    for row in rows:
        at=number(row['at']); need(at>=previous,'handoff_event_time_regressed');previous=at
        safe={'at':at}
        if 'from' in row or 'to' in row:
            need(row['from'] in states and row['to'] in states and row['to']!='fault','invalid_handoff_transition')
            safe.update({'from':row['from'],'to':row['to']})
        elif 'release' in row:
            safe['release']=release(row['release'])
        elif 'tool_granted' in row:
            safe['tool_granted']=identifier(row['tool_granted']);safe['capacity']=capacity(row['capacity'])
        elif 'tool_completed' in row:
            safe['tool_completed']=identifier(row['tool_completed'])
            need(type(row.get('interrupted')) is bool,'missing_tool_interruption_status')
            safe['interrupted']=row['interrupted']
        else:
            raise Refused('unknown_handoff_event')
        selected.append(safe)
    return selected


def failed_attempts(inputs):
    classifications={
        'uncontrolled-01':'superseded_older_harness_and_idle60_owner_profile',
        'uncontrolled-02':'foreground_focus_coverage_failed',
        'uncontrolled-03':'foreground_focus_coverage_failed',
        'controlled-01':'desktop_admission_deadline_before_corrected_cpu_estimator',
        'controlled-02':'desktop_admission_deadline_before_corrected_cpu_estimator',
        'controlled-03':'earlier_queued_agent_provider_watchdog_failed_before_safe_restart_boundary',
        'controlled-05':'startup_failed_before_generation_original_access_denial_not_established_resolved',
        'controlled-06':'activation_without_ordinary_input_did_not_trigger_foreground_release',
        'controlled-07':'desktop_admission_deadline_before_generation',
        'controlled-08':'owner_startup_failed_before_readiness',
        'controlled-09':'completed_arithmetic_answer_failed_independent_acceptance'}
    result=[]
    for label,reason in classifications.items():
        row=inputs.read('excluded_'+label,inputs.root/label/'result.private.json')
        need(type(row.get('passed')) is bool,'excluded_pass_field_missing')
        if label!='uncontrolled-01':
            need(row['passed'] is False,'excluded_failure_reclassified')
        if label=='controlled-05':
            need(not row.get('inference') and row.get('handoff_events')==[],
                 'excluded_startup_failure_scope_changed')
        if label=='controlled-06':
            watch=inputs.read('excluded_no_input_watcher',inputs.root/label/'ui-watch-completed.json')
            exact(watch.get('ordinary_input_actions'),0,'excluded_no_input_scope_changed')
            need(watch.get('terminal_passed') is False
                 and not any('release' in event for event in row.get('handoff_events',[])),
                 'excluded_no_handoff_scope_changed')
        if label=='controlled-07':
            need(not row.get('inference') and row.get('error')==
                 'TimeoutError: Desktop admission did not become ready',
                 'excluded_admission_deadline_scope_changed')
        if label=='controlled-08':
            need(not row.get('inference') and row.get('handoff_events')==[]
                 and row.get('error')==
                 'OwnerStartupError: New owner failed before readiness; see its retained run receipt',
                 'excluded_owner_startup_scope_changed')
        if label=='controlled-09':
            need(not row.get('inference') and row.get('error')==
                 'RuntimeError: Arithmetic artifact failed independent acceptance',
                 'excluded_arithmetic_failure_scope_changed')
        item={'attempt':label,'recorded_passed':row['passed'],'included_in_comparison':False,
              'exclusion_reason':reason,'raw_error_text_exported':False}
        if row.get('harness_sha256'):
            item['harness_sha256']=digest(row['harness_sha256'])
        foreground=row.get('foreground')
        if foreground:
            item['foreground_fraction']=number(foreground['foreground_fraction'])
            item['valid_foreground_run']=foreground['valid_foreground_run'] is True
        owner=inputs.root/label/'initial-owner.private.json'
        if owner.is_file():
            native=inputs.read('excluded_owner_'+label,owner)
            item['owner_manifest_sha256']=digest(native['verification']['manifest_sha256'])
            item['idle_unload_s']=number(native['native_status']['memory_policy']['idle_unload_s'])
        else:
            item['initial_owner_receipt_present']=False
        result.append(item)
    result.append(interrupted_attempt(inputs))
    return result


def interrupted_attempt(inputs):
    directory=inputs.root/'controlled-04'
    need(not (directory/'result.private.json').exists(),'interrupted_attempt_gained_terminal_result')
    row=inputs.read('excluded_controlled-04_interruption',directory/'interruption.private.json')
    exact(row.get('schema'),'adaptive.external-interruption.v1','interruption_schema_changed')
    need(row.get('passed') is False and row.get('qualification_accepted') is False,
         'interruption_reclassified_as_accepted')
    exact(row.get('last_host_phase'),'waiting_foreground','interruption_phase_changed')
    schedule=row['last_scheduler']
    need(schedule.get('active') is False and schedule.get('pending')==0
         and schedule.get('completed')==0,'interruption_did_execute_model_work')
    for field in ('owned_test_python_processes','listeners_18098_18100'):
        exact(row['verification'].get(field),0,'interrupted_cleanup_not_verified')
    return {'attempt':'controlled-04','recorded_passed':False,'qualification_accepted':False,
        'included_in_comparison':False,'terminal_result_present':False,'interrupted':True,
        'exclusion_reason':'supervisor_interrupted_while_waiting_for_real_foreground_activity',
        'external_cleanup_observed':True,'normal_native_release_claimed':False,
        'raw_error_text_exported':False}


def build(root,comparison_path):
    inputs=Inputs(root); baseline=root/'foreground/baseline-02'
    uncontrolled=root/'uncontrolled-04'; controlled=root/CONTROLLED_ATTEMPT; hermes=root/HERMES_ATTEMPT
    u=inputs.read('uncontrolled_result',uncontrolled/'result.private.json')
    c=inputs.read('controlled_result',controlled/'result.private.json')
    for row,case in ((u,'uncontrolled'),(c,'controlled')):
        true(row.get('passed'),case+'_failed');quality(row)
        exact(row['case'],case,'wrong_run_case')
        need(not row.get('error') and not row.get('cleanup_error'),'run_error')
        need(row['gateway_default_class']=='normal' and row['standalone_generation_class']=='background',
             'gateway_class_contract_changed')
    cleanup=c['cleanup'];true(cleanup.get('closed'),'controlled_not_closed')
    true(cleanup.get('owned_children_exited'),'controlled_children_not_exited')
    u_release=release(u['cleanup'])
    c_release=release(cleanup['release']) if cleanup.get('release') is not None else None
    exact(inputs.read('controlled_host_cleanup',controlled/'host/result.json'),cleanup,
          'host_cleanup_receipt_mismatch')
    status=inputs.read('controlled_terminal_status',controlled/'host/status.json')
    need(status.get('running') is False and status.get('host_phase')=='closed','terminal_host_not_closed')
    schedule=status['scheduler']
    need(schedule.get('active') is False and schedule.get('pending')==0
         and schedule.get('backend_completion_uncertain') is False and schedule.get('closing') is True,
         'terminal_gateway_not_reconciled')
    summaries=[]; arrays={}
    for label,directory in [('baseline',baseline),('uncontrolled',uncontrolled/'foreground'),
                            ('controlled',controlled/'foreground')]:
        summary,series=foreground(inputs,label,directory);summaries.append(summary);arrays[label]=series
    for index,row in ((1,u),(2,c)):
        saved=inputs.read(('uncontrolled','controlled')[index-1]+'_foreground_embedded_check',
                         (uncontrolled if index==1 else controlled)/'foreground/result.json')
        exact(row['foreground'],saved,'embedded_foreground_mismatch')
    need(summaries[0]['source_sha256']==summaries[1]['source_sha256']==summaries[2]['source_sha256'],
         'mixed_foreground_sources')
    compare=comparison(inputs.read('comparison',comparison_path),summaries)
    harnesses={'uncontrolled':digest(u['harness_sha256']),'controlled':digest(c['harness_sha256'])}
    exact(harnesses['controlled'],FROZEN_SOURCE_SHA256[CONTROLLED_HARNESS],
          'controlled_frozen_harness_changed')
    for case,name in (('uncontrolled','run_validation.py'),('controlled',CONTROLLED_HARNESS)):
        need(hash_bytes(inputs.raw('harness_source_'+case,root/name))==harnesses[case],'harness_changed')
    exact(c.get('protocol'),'immediate-admission-v1','controlled_protocol_changed')
    true(c.get('runtime_source_unchanged'),'runtime_source_changed_during_run')
    need(compare['uncontrolled_degradation_detected'] is False and compare['improvement_observed'] is False,
         'historical_comparison_cannot_claim_improvement')
    compare.update(matched_foreground_sources=True,matched_native_owner_package=False,
                   matched_harness_runtime=False,causal_improvement_claim=False,
                   scope='Earlier baseline-02/uncontrolled-04 are historical numerical references, not a same-owner or same-runtime causal comparison. Controlled-10 must independently pass every full-workflow gate.')
    for name,sha in summaries[0]['source_sha256'].items():
        need(hash_bytes(inputs.raw('foreground_source_'+name,root/'foreground'/name))==sha,'foreground_source_changed')
    profiles=[native_profile(inputs,label,directory) for label,directory in
              [('uncontrolled',uncontrolled),('controlled',controlled)]]
    binding=controlled_native_binding(inputs,profiles[1],controlled)
    reqs=[inference(u['inference'])]
    arithmetic=arithmetic_feedback(inputs,controlled,c['inference'])
    for directory,label,expected in ((uncontrolled,'uncontrolled',u['inference']),
                                      (controlled,'controlled',c['inference'])):
        exact(inputs.read(label+'_inference_file',directory/'inference-receipts.json'),expected,'inference_file_mismatch')
    video_result=video(inputs,controlled,c['video'])
    recovery_result=recovery(inputs,controlled,hermes)
    events=handoff_events(c['handoff_events'])
    exact(handoff_events(cleanup['events']),events,'cleanup_handoff_event_mismatch')
    releases=[r for r in events if 'release' in r]
    need(len(releases)>=2,'foreground_and_tool_release_required')
    need(len({r['release']['owner_id'] for r in releases})==len(releases),'release_owner_reused')
    need(any(r.get('to')=='restoring' for r in events) and any('tool_granted' in r for r in events),
         'restore_or_tool_admission_missing')
    grants=[r for r in events if 'tool_granted' in r]
    completions=[r for r in events if 'tool_completed' in r]
    need(len(grants)==len(completions)==1
         and grants[0]['tool_granted']==completions[0]['tool_completed']
         and completions[0]['at']>=grants[0]['at'],'tool_handoff_completion_missing')
    exact(grants[0]['capacity'],video_result['capacity'],'video_grant_capacity_mismatch')
    timing=release_timing(events,summaries[2]['started_monotonic_s'],arithmetic['first_request_completed_at'])
    source_snapshot={}
    for relative in ('run_validation.py',CONTROLLED_HARNESS,'foreground/activity.py','foreground/metrics.py',
                     'foreground/foreground_window.py','foreground/quiet_window.py',
                      'successor-v5/foreground/activity.py','successor-v5/foreground/metrics.py',
                      'successor-v5/foreground/foreground_window.py','successor-v5/foreground/quiet_window.py',
                      'successor-v5/native/windows_host.py','successor-v5/native/native_owner_adapter.py',
                      'successor-v5/native/owner_source/engine.py','successor-v5/native/owner_source/owned_job.py',
                      'successor-v5/native/owner_source/ownership.py','successor-v5/native/owner_source/source-pins.json',
                      'successor-v5/native/owner_source/memory_reader.py','successor-v5/native/owner_source/memory_monitor.py'):
        source_snapshot[relative]=hash_bytes(inputs.raw('snapshot_'+relative,root/relative))
        if relative.startswith('successor-v5/'):
            exact(source_snapshot[relative],FROZEN_SOURCE_SHA256[relative],
                  'controlled_frozen_source_changed')
    for name,sha in summaries[2]['source_sha256'].items():
        exact(source_snapshot['successor-v5/foreground/'+name],sha,'controlled_foreground_source_changed')
    plan=inputs.read('recovery_plan',hermes/'plan.json')
    canonical=Path(plan['canonical'])
    for module in ('handoff.py','gateway.py','scheduler.py','config.py','costs.py','task_store.py','feedback.py'):
        relative='src/adaptive_inference/'+module
        source_snapshot[relative]=hash_bytes(inputs.raw('snapshot_'+relative,canonical/relative))
        exact(source_snapshot[relative],FROZEN_SOURCE_SHA256[relative],'controlled_frozen_runtime_changed')
        exact(c['runtime_source_sha256'].get(relative),source_snapshot[relative],'controlled_runtime_pin_changed')
    need(set(c['runtime_source_sha256'])=={'src/adaptive_inference/'+name for name in
         ('handoff.py','gateway.py','scheduler.py','config.py','costs.py','task_store.py','feedback.py')},'runtime_source_set_changed')
    receipt={'schema':'adaptive.foreground-handoff-milestone.v6','passed':True,
        'selected_attempts':{'controlled':CONTROLLED_ATTEMPT,'hermes':HERMES_ATTEMPT,
                             'historical_baseline':'baseline-02','historical_uncontrolled':'uncontrolled-04'},
        'hardware_scope':'Windows / RTX 4070 Laptop 8 GiB / existing IQ3_S / pinned Strata and Hermes composition',
        'model':MODEL,'quality':QUALITY,'context':65536,'harness_sha256':harnesses,
        'controlled_runtime_source_sha256':c['runtime_source_sha256'],
        'protocol':'immediate-admission-v1',
        'comparison':compare,'foreground':dict(zip(('baseline','uncontrolled','controlled'),summaries)),
        'native_profiles':dict(zip(('uncontrolled','controlled'),profiles)),
        'controlled_native_source_binding':binding,
        'arithmetic_requests':{'historical_uncontrolled':reqs[0]},
        'controlled_arithmetic_feedback':arithmetic,
        'gateway_default_class':'normal','standalone_generation_class':'background',
        'handoff_events':events,'handoff_timing':timing,'video':video_result,'hermes_recovery':recovery_result,
        'cleanup':{'uncontrolled':u_release,'controlled':{'closed':True,'owned_children_exited':True,'release':c_release}},
        'excluded_attempts':failed_attempts(inputs),
        'source_snapshot_at_export':source_snapshot,
        'source_snapshot_scope':'Exact source bytes read at sanitization; run-recorded harness/foreground/owner/SDK pins are separately preserved. This inventory is not additional per-module runtime-load attestation.',
        'limits':['No comparative performance improvement is inferred when improvement_observed is false.',
                  'Controlled arithmetic represents two logical tasks and all bounded correction attempts, not two first-pass successes; final token usage describes the accepted last request.',
                  'Earlier baseline/uncontrolled foreground runs retain their old harness and native owner-package identities. Controlled-10 uses the v4 owner package; this is not a same-owner or same-runtime causal comparison and no improvement is claimed.',
                  'GDI submission/host-message timing is not physical display latency or a gaming/video-playback qualification.',
                  'Sampled capacity is not a continuous guarantee or system-wide reservation.',
                  'Native model assets were metadata-bound, not fully content-hashed.',
                  'One process restart is not OS boot, physical power-loss, arbitrary-tool exactly-once or long-duration qualification.'],
        'sanitizer_sha256':hash_bytes(Path(__file__).read_bytes()),'input_sha256':inputs.hashes}
    inputs.unchanged()
    return receipt,arrays,inputs


def encoded(value):
    return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')


def privacy_check(data):
    text=data.decode('utf-8')
    need(not re.search(r'(?i)([a-z]:\\|[a-z]:/|/users/|/home/|\\\\[a-z])',text), 'absolute_path_in_export')
    for key in ('reasoning_content','assistant_reasoning','messages','native_history','prompt','api_key',
                'authorization','exe','run','project','session_id','hwnd','pid','created_filetime'):
        need(not re.search(r'"'+key+r'"\s*:',text),'private_field_in_export_'+key)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--comparison',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        need(not args.output.exists(),'output_already_exists')
        need(args.output.parent.is_dir(),'output_parent_missing')
        need(args.output.parent.resolve()==args.root.resolve(strict=True),'output_must_be_new_private_root_child')
        receipt,arrays,inputs=build(args.root.resolve(strict=True),args.comparison.resolve(strict=True))
        blobs={'result.json':encoded(receipt),'foreground-series.json':encoded(arrays)}
        for data in blobs.values():privacy_check(data)
        manifest={'schema':'adaptive.public-evidence-files.v1','source_selection':'explicit nested allowlists',
                  'files':{k:hash_bytes(v) for k,v in blobs.items()},'sanitizer_sha256':receipt['sanitizer_sha256']}
        blobs['manifest.json']=encoded(manifest)
        inputs.unchanged()
        args.output.mkdir(exist_ok=False)
        for name,data in blobs.items():
            with (args.output/name).open('xb') as stream:stream.write(data)
        print(json.dumps({'prepared':True,'published':False,'files':manifest['files']}))
        return 0
    except (Refused,KeyError,TypeError,ValueError,OSError,sqlite3.Error) as exc:
        # Error text from paths, SQLite or source payloads is deliberately not echoed.
        code=str(exc) if isinstance(exc,Refused) else type(exc).__name__
        print(json.dumps({'prepared':False,'reason':code}),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
