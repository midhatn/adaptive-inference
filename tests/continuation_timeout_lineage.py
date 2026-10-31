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
