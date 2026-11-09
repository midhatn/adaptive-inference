"""Exact automatic-tool-recovery source view before historical pending-tool evidence.

Reuse pending_tool_lineage's complete-file SHA and portable-AST projection. Retained
9242434 sources are data, never imported or executed. Current automatic recovery behavior
has separate tests; this view does not transfer historical qualification.
"""
import ast
import hashlib
import json
from pathlib import Path

from paused_expiry_lineage import fingerprint

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'provenance/automatic-tool-recovery'


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
            *(root / row['predecessor_source'] for row in rows['files'].values())]


def retained(relative, row, root):
    expected = ARCHIVE + '/predecessor/' + relative
    if (not relative.startswith(('src/adaptive_inference/', 'tests/'))
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))
            or row['predecessor_source'] != expected):
        raise AssertionError('Changed automatic-tool-recovery predecessor path: ' + relative)
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed automatic-tool-recovery predecessor identity: ' + relative)
    return before


def predecessor(relative, data, root=None):
    """Project known complete successor bytes; unknown bytes remain unknown."""
    root = ROOT if root is None else root
    rows = record(root)
    row = None if rows is None else rows['files'].get(relative)
    if row is None:
        return data
    before = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed automatic-tool-recovery successor AST: ' + relative)
        return before
    return data


def runtime_view(current, root=None):
    """Require the complete 77-module closure before restoring pending-tool sources."""
    root = ROOT if root is None else root
    rows = record(root)
    result = dict(current)
    if rows is None:
        return result
    baseline = rows['baseline_runtime']
    if set(result) != set(baseline):
        raise AssertionError('Changed automatic-tool-recovery runtime closure')
    for name, pin in baseline.items():
        result[name] = predecessor('src/adaptive_inference/' + name, result[name], root)
        if hashlib.sha256(result[name]).hexdigest() != pin:
            raise AssertionError('Changed automatic-tool-recovery runtime source: ' + name)
    return result


def restore(tree, relative, root=None):
    """AST restoration also requires exact complete on-disk successor bytes."""
    root = ROOT if root is None else root
    rows = record(root)
    source = 'src/adaptive_inference/' + relative
    row = None if rows is None else rows['files'].get(source)
    if row is None or fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = (root / source).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete reboot-budget source (automatic-tool-recovery source): ' + relative)
    return ast.parse(predecessor(source, data, root))
