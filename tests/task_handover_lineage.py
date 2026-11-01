"""Exact outer source view for sequential desktop task handover.

Reuses task_contract_lineage's complete-file byte/AST projection and the existing
cross-version AST fingerprint. Retained code is parsed, never executed here.
Current behavioral tests remain separate from preserved historical assertions.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE_RELATIVE = 'provenance/task-handover'


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE_RELATIVE / 'source-lineage.json').read_text(encoding='utf-8'))


def retained(relative, row, root=None):
    root = ROOT if root is None else root
    expected = ARCHIVE_RELATIVE + '/predecessor/src/adaptive_inference/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed task-handover predecessor path: ' + relative)
    data = (root / expected).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed task-handover predecessor bytes: ' + relative)
    if fingerprint(ast.parse(data)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed task-handover predecessor AST: ' + relative)
    return data


def predecessor(relative, data, root=None):
    from task_file_alias_lineage import predecessor as alias_predecessor
    data = alias_predecessor(relative, data, root=root)
    row = record(root)['modules'].get(relative)
    if row is None:
        return data
    prior = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete task-handover source: ' + relative)
    return prior


def restore_task_handover(tree, relative, root=None):
    from task_file_alias_lineage import restore_file_aliases
    tree = restore_file_aliases(tree, relative, root=root)
    row = record(root)['modules'].get(relative)
    if row is None:
        return tree
    before = ast.parse(retained(relative, row, root))
    current = fingerprint(tree)
    if current == row['predecessor_ast_sha256']:
        return tree
    if current != row['successor_ast_sha256']:
        raise AssertionError('Changed complete task-handover AST: ' + relative)
    return before


def preserved_records(root=None):
    """Require unchanged historical manifests and exact saved test/helper bytes."""
    root = ROOT if root is None else root
    rows = record(root)
    for relative, expected in rows['historical_json'].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise AssertionError('Changed historical task-handover input: ' + relative)
    for relative, row in rows['preserved_tests'].items():
        expected = ARCHIVE_RELATIVE + '/predecessor/' + relative
        if not relative.startswith('tests/') or row['source'] != expected:
            raise AssertionError('Changed retained task-handover test path: ' + relative)
        data = (root / expected).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise AssertionError('Changed retained task-handover test bytes: ' + relative)


def runtime_view(root=None):
    """Validate the whole successor runtime, then expose the exact c3 closure."""
    root = ROOT if root is None else root
    rows = record(root)
    groups = [set(rows[key]) for key in ('modules', 'unchanged_runtime', 'new_modules')]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise AssertionError('Overlapping task-handover source groups')
    from task_file_alias_lineage import runtime_view as alias_view
    current = alias_view(root=root)
    actual = set(current)
    if actual != set.union(*groups):
        raise AssertionError('Changed complete task-handover runtime closure')
    result = {}
    for relative in sorted(actual):
        data = current[relative]
        changed = relative in rows['modules']
        row = rows['modules'][relative] if changed else {
            **rows['unchanged_runtime'], **rows['new_modules']}[relative]
        byte_pin = row['successor_sha256'] if changed else row['sha256']
        ast_pin = row['successor_ast_sha256'] if changed else row['ast_sha256']
        if hashlib.sha256(data).hexdigest() != byte_pin or fingerprint(ast.parse(data)) != ast_pin:
            raise AssertionError('Changed current task-handover runtime source: ' + relative)
        if relative not in rows['new_modules']:
            result[relative] = retained(relative, row, root) if changed else data
    if len(result) != rows['baseline_runtime_count']:
        raise AssertionError('Changed task-handover baseline closure')
    return result
