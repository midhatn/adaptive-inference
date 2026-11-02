"""Exact video-tool source view before the unchanged compiler history.

Reuses compiler_lineage's complete-file SHA and portable-AST projection.
Retained 1f7f28e sources are data, never imported or executed. This source view
does not transfer compiler qualification to video or change historical receipts.
"""
import ast
import hashlib
import json
from pathlib import Path

from paused_expiry_lineage import fingerprint
import recipe_reconciliation_lineage

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'provenance/video-tool'


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
            *recipe_reconciliation_lineage.inputs(root)]


def retained(relative, row, root):
    expected = ARCHIVE + '/predecessor/' + relative
    if (not relative.startswith(('src/adaptive_inference/', 'tests/', 'examples/'))
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))
            or row['predecessor_source'] != expected):
        raise AssertionError('Changed video-tool predecessor path: ' + relative)
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed video-tool predecessor identity: ' + relative)
    return before


def predecessor(relative, data, root=None):
    """Project known complete successor bytes; unknown bytes remain unknown."""
    root = ROOT if root is None else root
    data = recipe_reconciliation_lineage.predecessor(relative, data, root)
    rows = record(root)
    row = None if rows is None else rows['files'].get(relative)
    if row is None:
        return data
    before = retained(relative, row, root)
    if hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed video-tool successor AST: ' + relative)
        return before
    return data


def runtime_view(current, root=None):
    """Expose the exact 73-module compiler closure after checking all additions."""
    root = ROOT if root is None else root
    rows = record(root)
    result = dict(current)
    if rows is None:
        return result
    baseline, additions = rows['baseline_runtime'], rows['additions']
    if set(result) == set(baseline):
        if {name: hashlib.sha256(data).hexdigest() for name, data in result.items()} == baseline:
            return result
    result = recipe_reconciliation_lineage.runtime_view(result, root)
    if set(result) != set(baseline) | set(additions):
        raise AssertionError('Changed video-tool runtime closure')
    for name, row in additions.items():
        if row['source'] != 'src/adaptive_inference/' + name:
            raise AssertionError('Changed video-tool addition path: ' + name)
        data = result[name]
        if (hashlib.sha256(data).hexdigest() != row['sha256']
                or fingerprint(ast.parse(data)) != row['ast_sha256']):
            raise AssertionError('Changed video-tool runtime source: ' + name)
        del result[name]
    for name, pin in baseline.items():
        result[name] = predecessor('src/adaptive_inference/' + name, result[name], root)
        if hashlib.sha256(result[name]).hexdigest() != pin:
            raise AssertionError('Changed video-tool runtime source: ' + name)
    return result


def restore(tree, relative, root=None):
    """AST restoration also requires exact complete on-disk successor bytes."""
    root = ROOT if root is None else root
    tree = recipe_reconciliation_lineage.restore(tree, relative, root)
    rows = record(root)
    source = 'src/adaptive_inference/' + relative
    row = None if rows is None else rows['files'].get(source)
    if row is None or fingerprint(tree) != row['successor_ast_sha256']:
        return tree
    data = recipe_reconciliation_lineage.predecessor(source, (root / source).read_bytes(), root)
    if hashlib.sha256(data).hexdigest() != row['successor_sha256']:
        raise AssertionError('Changed complete reboot-budget source (complete video-tool source): ' + relative)
    return ast.parse(predecessor(source, data, root))
