"""Exact source-only outer view for generic task contracts and admission.

Reuses the complete-file byte/AST projection in thread_pause_lineage. No retained
code executes. Current behavioral tests qualify current code separately; this
view only keeps the previous published source assertions reproducible.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE_RELATIVE = 'provenance/task-contract'


def record():
    return json.loads((ROOT / ARCHIVE_RELATIVE / 'source-lineage.json').read_text(encoding='utf-8'))


def retained(relative, row):
    expected = ARCHIVE_RELATIVE + '/predecessor/src/adaptive_inference/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed task-contract predecessor path: ' + relative)
    data = (ROOT / expected).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed task-contract predecessor bytes: ' + relative)
    if fingerprint(ast.parse(data)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed task-contract predecessor AST: ' + relative)
    return data


def predecessor(relative, data):
    row = record()['modules'].get(relative)
    if row is None:
        return data
    prior = retained(relative, row)
    if hashlib.sha256(data).hexdigest() not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete task-contract source: ' + relative)
    return prior


def restore_task_contract(tree, relative):
    row = record()['modules'].get(relative)
    if row is None:
        return tree
    before = ast.parse(retained(relative, row))
    current = fingerprint(tree)
    if current == row['predecessor_ast_sha256']:
        return tree
    if current != row['successor_ast_sha256']:
        raise AssertionError('Changed complete task-contract AST: ' + relative)
    return before


def runtime_view():
    """Validate every current module, then return only the exact historical set."""
    rows = record()
    groups = [set(rows[key]) for key in ('modules', 'unchanged_runtime', 'new_modules')]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise AssertionError('Overlapping task-contract source groups')
    runtime = ROOT / 'src/adaptive_inference'
    actual = {path.relative_to(runtime).as_posix() for path in runtime.rglob('*.py')}
    expected = set.union(*groups)
    if actual != expected:
        raise AssertionError('Changed complete task-contract runtime closure')
    result = {}
    for relative in sorted(actual):
        data = (runtime / relative).read_bytes()
        changed = relative in rows['modules']
        row = rows['modules'][relative] if changed else {
            **rows['unchanged_runtime'], **rows['new_modules']}[relative]
        byte_pin = row['successor_sha256'] if changed else row['sha256']
        ast_pin = row['successor_ast_sha256'] if changed else row['ast_sha256']
        if hashlib.sha256(data).hexdigest() != byte_pin or fingerprint(ast.parse(data)) != ast_pin:
            raise AssertionError('Changed current task-contract runtime source: ' + relative)
        if relative not in rows['new_modules']:
            result[relative] = retained(relative, row) if changed else data
    if len(result) != rows['baseline_runtime_count']:
        raise AssertionError('Changed task-contract baseline closure')
    return result
