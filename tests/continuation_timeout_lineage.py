"""Exact outer input view for fixture-only timeout diagnostics.

Unknown bytes are never projected. Legacy disposable roots lacking this new
archive still pass their bytes to unchanged inner validators, which reject
unrecognized complete inputs. Retained source is parsed, never executed.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE = 'provenance/task-handover/continuation-timeout-diagnostics'
INPUTS = {'tests/test_continuation_host.py', 'tests/test_continuation_readiness.py',
          'tests/continuation_diagnostics_lineage.py', 'tests/admission_activity_lineage.py'}


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE / 'source-lineage.json').read_bytes())


def predecessor(relative, data, root=None):
    data = preparation_predecessor(relative, data, root)
    if relative not in INPUTS:
        return data
    root = ROOT if root is None else root
    if not (root / ARCHIVE / 'source-lineage.json').exists():
        return data
    row = record(root)['files'][relative]
    expected = ARCHIVE + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed timeout diagnostic predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed timeout diagnostic predecessor identity')
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed complete timeout diagnostic AST')
        return before
    return data


# Ordinary task authoring is a later source delta, not installed case17 evidence.
# Reuse this outer byte view; all inner historical assertions remain unchanged.
PREPARATION = 'provenance/task-preparation'


def preparation_record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / PREPARATION / 'source-lineage.json').read_bytes())


def preparation_inputs(root=None):
    root = ROOT if root is None else root
    return [root / PREPARATION / 'source-lineage.json', root / PREPARATION / 'cli.before.py']


def preparation_predecessor(relative, data, root=None):
    """Reverse only exact declared CLI/reader/version bytes, never unknown changes."""
    root = ROOT if root is None else root
    if not (root / PREPARATION / 'source-lineage.json').exists():
        return data  # Legacy disposable roots still face the original checks.
    row = preparation_record(root)['files'].get(relative)
    if row is None or hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        return data
    if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
        raise AssertionError('Changed task-preparation successor AST')
    if relative == 'src/adaptive_inference/cli.py':
        if row['predecessor_source'] != PREPARATION + '/cli.before.py':
            raise AssertionError('Changed task-preparation predecessor path')
        before = (root / row['predecessor_source']).read_bytes()
    else:
        before = data
        for rule in reversed(row['replacements']):
            old, new = rule['old'].encode(), rule['new'].encode()
            if before.count(new) != rule['count']:
                raise AssertionError('Changed task-preparation reader edit')
            before = before.replace(new, old)
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed task-preparation predecessor identity')
    return before


def preparation_runtime_view(root=None):
    """Check declared addition/CLI/version deltas before historical closure checks.

    Every other module and byte passes through to those original assertions.
    No unknown module is omitted and no retained runtime is executed.
    """
    root = ROOT if root is None else root
    runtime = root / 'src/adaptive_inference'
    current = {path.relative_to(runtime).as_posix(): path.read_bytes()
               for path in runtime.rglob('*.py')}
    rows = preparation_record(root)
    for name, pin in {'task_prepare.py': rows['addition_sha256'],
                      '__init__.py': rows['files']['src/adaptive_inference/__init__.py']['successor_sha256'],
                      'cli.py': rows['files']['src/adaptive_inference/cli.py']['successor_sha256']}.items():
        if name not in current:
            raise AssertionError('Changed task-preparation runtime closure: ' + name)
        if hashlib.sha256(current[name]).hexdigest() != pin:
            raise AssertionError('Changed task-preparation runtime source: ' + name)
    del current['task_prepare.py']
    for name in ('cli.py', '__init__.py'):
        current[name] = preparation_predecessor('src/adaptive_inference/' + name, current[name], root)
    return current


def restore_preparation(tree, relative, root=None):
    """Existing AST readers see only the exact declared CLI/version deltas."""
    if relative not in ('cli.py', '__init__.py'):
        return tree
    root = ROOT if root is None else root
    source = 'src/adaptive_inference/' + relative
    row = preparation_record(root)['files'][source]
    if fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = (root / source).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete task-handover source (task-preparation): ' + relative)
    return ast.parse(preparation_predecessor(source, data, root))
