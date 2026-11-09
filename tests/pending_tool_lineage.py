"""Exact pending-tool-recovery source view before historical recipe evidence.

Reuse recipe_reconciliation_lineage's complete-file SHA and portable-AST projection. Retained
93eba3c sources are data, never imported or executed. Current recovery behavior
has separate tests; this view does not transfer historical qualification.
"""
import ast
import hashlib
import json
from pathlib import Path

from paused_expiry_lineage import fingerprint
import automatic_tool_recovery_lineage

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'provenance/pending-tool-recovery'


def record(root=None):
    root = ROOT if root is None else root
    path = root / ARCHIVE / 'source-lineage.json'
    return json.loads(path.read_bytes()) if path.exists() else None


def inputs(root=None):
    root = ROOT if root is None else root
    rows = record(root)
    if rows is None:
        return []
    return [root / ARCHIVE / 'source-lineage.json',
            *(root / row['predecessor_source'] for row in rows['files'].values()),
            *automatic_tool_recovery_lineage.inputs(root)]


def retained(relative, row, root):
    expected = ARCHIVE + '/predecessor/' + relative
    if (not relative.startswith(('src/adaptive_inference/', 'tests/'))
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))
            or row['predecessor_source'] != expected):
        raise AssertionError('Changed pending-tool-recovery predecessor path: ' + relative)
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed pending-tool-recovery predecessor identity: ' + relative)
    return before


def predecessor(relative, data, root=None):
    """Project known complete successor bytes; unknown bytes remain unknown."""
    root = ROOT if root is None else root
    data = automatic_tool_recovery_lineage.predecessor(relative, data, root)
    rows = record(root)
    row = None if rows is None else rows['files'].get(relative)
    if row is None:
        return data
    before = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed pending-tool-recovery successor AST: ' + relative)
        return before
    return data


def runtime_view(current, root=None):
    """Require the complete 77-module closure before restoring recipe sources."""
    root = ROOT if root is None else root
    rows = record(root)
    result = dict(current)
    if rows is None:
        return result
    baseline = rows['baseline_runtime']
    if set(result) == set(baseline):
        if {name: hashlib.sha256(data).hexdigest() for name, data in result.items()} == baseline:
            return result
    result = automatic_tool_recovery_lineage.runtime_view(result, root)
    if set(result) != set(baseline):
        raise AssertionError('Changed pending-tool-recovery runtime closure')
    for name, pin in baseline.items():
        result[name] = predecessor('src/adaptive_inference/' + name, result[name], root)
        if hashlib.sha256(result[name]).hexdigest() != pin:
            raise AssertionError('Changed pending-tool-recovery runtime source: ' + name)
    return result


def restore(tree, relative, root=None):
    """AST restoration also requires exact complete on-disk successor bytes."""
    root = ROOT if root is None else root
    tree = automatic_tool_recovery_lineage.restore(tree, relative, root)
    rows = record(root)
    source = 'src/adaptive_inference/' + relative
    row = None if rows is None else rows['files'].get(source)
    if row is None or fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = automatic_tool_recovery_lineage.predecessor(source, (root / source).read_bytes(), root)
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete reboot-budget source (pending-tool-recovery source): ' + relative)
    return ast.parse(predecessor(source, data, root))
