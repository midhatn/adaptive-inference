"""Exact test-only outer view; retained source is parsed, never executed.

Reuses the complete-file byte/AST boundary and cross-version fingerprint from
task_file_alias_lineage. The existing alias runtime manifest is unchanged.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE = 'provenance/task-handover/task-file-aliases/ci-diagnostics'
FIXTURE = 'tests/test_continuation_host.py'
READINESS = 'provenance/task-handover/fixture-readiness'


def readiness_predecessor(data, root=None):
    """Project only the pinned readiness observation change to the old fixture."""
    root = ROOT if root is None else root
    row = json.loads((root / READINESS / 'source-lineage.json').read_bytes())
    before = (root / READINESS / 'predecessor-test_continuation_host.py').read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed CI diagnostic readiness predecessor')
    pin = hashlib.sha256(data).hexdigest()
    if pin == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed complete CI diagnostic fixture readiness AST')
        return before
    # The existing diagnostic layer still rejects every unknown complete file.
    return data


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE / 'source-lineage.json').read_bytes())


def retained(relative, root=None):
    root = ROOT if root is None else root
    row = record(root)['files'][relative]
    expected = ARCHIVE + '/predecessor/' + relative
    if row['predecessor_source'] != expected:
        raise AssertionError('Changed CI diagnostic predecessor path')
    data = (root / expected).read_bytes()
    if hashlib.sha256(data).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed CI diagnostic predecessor bytes')
    if fingerprint(ast.parse(data)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed CI diagnostic predecessor AST')
    return data


def predecessor(data, root=None):
    """Validate the complete diagnostic fixture before the old d1 assertions."""
    data = readiness_predecessor(data, root)
    row = record(root)['files'][FIXTURE]
    before = retained(FIXTURE, root)
    digest = hashlib.sha256(data).hexdigest()
    if digest not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete CI diagnostic fixture bytes')
    expected = row['predecessor_ast_sha256'] if digest == row['predecessor_sha256'] else row['successor_ast_sha256']
    if fingerprint(ast.parse(data)) != expected:
        raise AssertionError('Changed complete CI diagnostic fixture AST')
    return before
