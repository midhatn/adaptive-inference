"""Exact source-only view of the bounded task-file alias repair.

Reuses task_handover_lineage's complete-file byte/AST projection, including the
existing cross-version fingerprint. Retained code is parsed, never executed.
Current behavior tests remain separate from preserved historical assertions.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE_RELATIVE = 'provenance/task-handover/task-file-aliases'


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE_RELATIVE / 'source-lineage.json').read_text(encoding='utf-8'))


def retained(relative, row, root=None):
    root = ROOT if root is None else root
    expected = ARCHIVE_RELATIVE + '/predecessor/src/adaptive_inference/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed task-file-alias predecessor path: ' + relative)
    data = (root / expected).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed task-file-alias predecessor bytes: ' + relative)
    if fingerprint(ast.parse(data)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed task-file-alias predecessor AST: ' + relative)
    return data


def predecessor(relative, data, root=None):
    data = observation_predecessor(relative, data, root=root)
    row = record(root)['modules'].get(relative)
    if row is None:
        return data
    prior = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete task-handover source (task-file-alias): ' + relative)
    return prior


def restore_file_aliases(tree, relative, root=None):
    tree = restore_observation(tree, relative, root=root)
    row = record(root)['modules'].get(relative)
    if row is None:
        return tree
    before = ast.parse(retained(relative, row, root))
    current = fingerprint(tree)
    if current == row['predecessor_ast_sha256']:
        return tree
    if current != row['successor_ast_sha256']:
        raise AssertionError('Changed complete task-handover AST (task-file-alias): ' + relative)
    return before


def preserved_records(root=None):
    """Require unchanged historical manifests and exact saved test/helper bytes."""
    root = ROOT if root is None else root
    rows = record(root)
    for relative, expected in rows['historical_json'].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise AssertionError('Changed historical task-file-alias input: ' + relative)
    for relative, row in rows['preserved_tests'].items():
        expected = ARCHIVE_RELATIVE + '/predecessor/' + relative
        if not relative.startswith('tests/') or row['source'] != expected:
            raise AssertionError('Changed retained task-file-alias test path: ' + relative)
        data = (root / expected).read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise AssertionError('Changed retained task-file-alias test bytes: ' + relative)


def runtime_view(root=None):
    """Validate the whole successor runtime, then expose the exact pre-alias closure."""
    root = ROOT if root is None else root
    rows = record(root)
    groups = [set(rows[key]) for key in ('modules', 'unchanged_runtime', 'new_modules')]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise AssertionError('Overlapping task-file-alias source groups')
    runtime = root / 'src/adaptive_inference'
    actual = {path.relative_to(runtime).as_posix() for path in runtime.rglob('*.py')}
    if actual != set.union(*groups):
        raise AssertionError('Changed complete task-file-alias runtime closure')
    result = {}
    for relative in sorted(actual):
        data = (runtime / relative).read_bytes()
        data = observation_predecessor(relative, data, root=root)
        changed = relative in rows['modules']
        row = rows['modules'][relative] if changed else {
            **rows['unchanged_runtime'], **rows['new_modules']}[relative]
        byte_pin = row['successor_sha256'] if changed else row['sha256']
        ast_pin = row['successor_ast_sha256'] if changed else row['ast_sha256']
        if hashlib.sha256(data).hexdigest() != byte_pin or fingerprint(ast.parse(data)) != ast_pin:
            raise AssertionError('Changed current task-file-alias runtime source: ' + relative)
        if relative not in rows['new_modules']:
            result[relative] = retained(relative, row, root) if changed else data
    if len(result) != rows['baseline_runtime_count']:
        raise AssertionError('Changed task-file-alias baseline closure')
    return result


# Current pause-observation delta; reuse the already retained bf70 predecessors.
OBSERVATION_ARCHIVE = 'provenance/task-handover/pause-observation'
OBSERVATION_BASE = 'provenance/paused-budget-expiry/reviewed-repository-bf70a2ac/src/adaptive_inference/'


def observation_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / OBSERVATION_ARCHIVE / 'source-lineage.json').read_bytes())


def observation_inputs(root=None):
    """Exact extra source files needed by the existing disposable-root tests."""
    root = ROOT if root is None else root
    rows = observation_record(root)
    return [root / OBSERVATION_ARCHIVE / 'source-lineage.json',
            *(root / row['predecessor_source'] for row in rows['modules'].values())]


def _observation_before(relative, root=None):
    root = ROOT if root is None else root
    row = observation_record(root)['modules'].get(relative)
    if row is None:
        return None, None
    expected = OBSERVATION_BASE + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed pause-observation predecessor path')
    before = (root / expected).read_bytes()
    if hashlib.sha256(before).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed pause-observation predecessor bytes')
    if fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed pause-observation predecessor AST')
    return row, before


def observation_predecessor(relative, data, root=None):
    row, before = _observation_before(relative, root)
    if row is None:
        return data
    if hashlib.sha256(data).hexdigest() not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete task-handover source (pause-observation): ' + relative)
    return before


def restore_observation(tree, relative, root=None):
    row, before = _observation_before(relative, root)
    if row is None:
        return tree
    current = fingerprint(tree)
    if current == row['predecessor_ast_sha256']:
        return tree
    if current != row['successor_ast_sha256']:
        raise AssertionError('Changed complete task-handover AST (pause-observation): ' + relative)
    return ast.parse(before)
