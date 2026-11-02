"""Exact source-only compiler delta before the existing historical readers.

Reuse the reboot-budget complete-file SHA/portable-AST projection. Retained
sources are data, never imported or executed. Current behavior has separate
tests; this view makes no compiler, installed-agent, or physical-test claim.
"""
import ast
import hashlib
import json
from pathlib import Path

from paused_expiry_lineage import fingerprint

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'provenance/compiler'


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
        raise AssertionError('Changed compiler predecessor path: ' + relative)
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed compiler predecessor identity: ' + relative)
    return before


def predecessor(relative, data, root=None):
    """Project exact successor bytes only; unknown inputs face old assertions."""
    root = ROOT if root is None else root
    rows = record(root)
    row = None if rows is None else rows['files'].get(relative)
    if row is None:
        return data
    before = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed compiler successor AST: ' + relative)
        return before
    return data


def runtime_view(current, root=None):
    """Check all declared additions before exposing the exact 84ef4d2 closure."""
    root = ROOT if root is None else root
    rows = record(root)
    result = dict(current)
    if rows is None:
        return result
    baseline = rows['baseline_runtime']
    additions = rows['additions']
    # Already projected exact predecessors are allowed for composed readers.
    if set(result) == set(baseline):
        if {name: hashlib.sha256(data).hexdigest() for name, data in result.items()} == baseline:
            return result
    if set(result) != set(baseline) | set(additions):
        raise AssertionError('Changed compiler runtime closure')
    for name, row in additions.items():
        if row['source'] != 'src/adaptive_inference/' + name:
            raise AssertionError('Changed compiler addition path: ' + name)
        data = result[name]
        if (hashlib.sha256(data).hexdigest() != row['sha256']
                or fingerprint(ast.parse(data)) != row['ast_sha256']):
            raise AssertionError('Changed compiler runtime source: ' + name)
        del result[name]
    for name, pin in baseline.items():
        result[name] = predecessor('src/adaptive_inference/' + name, result[name], root)
        if hashlib.sha256(result[name]).hexdigest() != pin:
            raise AssertionError('Changed compiler runtime source: ' + name)
    return result


def restore(tree, relative, root=None):
    """AST entry points also require exact complete current source bytes."""
    root = ROOT if root is None else root
    rows = record(root)
    source = 'src/adaptive_inference/' + relative
    row = None if rows is None else rows['files'].get(source)
    if row is None or fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = (root / source).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete reboot-budget source (compiler successor): ' + relative)
    return ast.parse(predecessor(source, data, root))
