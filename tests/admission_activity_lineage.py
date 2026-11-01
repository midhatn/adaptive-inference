"""Exact outer source view for the admission-wait activity correction.

Reuses the existing complete-file byte/AST projection. Only declared successor
bytes are projected; other inputs reach the unchanged historical validators.
No retained runtime is executed and no historical receipt is rewritten.
"""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint
import continuation_timeout_lineage as timeout_lineage

ARCHIVE = 'provenance/task-handover/admission-activity'


def record(root=None):
    root = ROOT if root is None else root
    return json.loads((root / ARCHIVE / 'source-lineage.json').read_bytes())


def inputs(root=None):
    root = ROOT if root is None else root
    return [root / ARCHIVE / 'source-lineage.json',
            *(root / row['predecessor_source'] for row in record(root)['files'].values())]


def retained(relative, root=None):
    root = ROOT if root is None else root
    row = record(root)['files'].get(relative)
    if row is None:
        return None, None
    expected = ARCHIVE + '/predecessor/' + relative
    if (not relative.startswith(('src/adaptive_inference/', 'tests/'))
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))
            or row['predecessor_source'] != expected):
        raise AssertionError('Changed admission-activity predecessor path')
    before = (root / expected).read_bytes()
    if (hashlib.sha256(before).hexdigest() != row['predecessor_sha256']
            or fingerprint(ast.parse(before)) != row['predecessor_ast_sha256']):
        raise AssertionError('Changed admission-activity predecessor identity')
    return row, before


def predecessor(relative, data, root=None):
    data = timeout_lineage.predecessor(relative, data, root)
    row, before = retained(relative, root)
    if row is not None and hashlib.sha256(data).hexdigest() == row['successor_sha256']:
        if fingerprint(ast.parse(data)) != row['successor_ast_sha256']:
            raise AssertionError('Changed complete task-handover AST (admission-activity)')
        return before
    # Existing inner validators still reject unknown complete files and accept
    # only their own declared historical inputs. Do not guess a historical path.
    return data


def restore(tree, relative, root=None):
    row, before = retained(relative, root)
    if row is not None and fingerprint(tree) == row['successor_ast_sha256']:
        return ast.parse(before)
    return tree
