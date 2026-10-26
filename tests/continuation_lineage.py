"""Strict outer historical view of the explicitly pinned continuation delta.

This is test-only source preservation, not execution of predecessor code.
Current behavior is exercised by the ordinary tests. Historical assertions
retain their original hashes after this exact, fully pinned projection.
"""
import ast
from copy import deepcopy
import hashlib
import json

from paused_expiry_lineage import ROOT, mapping, fingerprint

ARCHIVE = ROOT / 'provenance/explicit-continuation'


def record():
    return json.loads((ARCHIVE / 'source-lineage.json').read_text(encoding='utf-8'))


def retained(relative, row):
    path = ROOT / row['predecessor_source']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row['predecessor_sha256']:
        raise AssertionError('Changed continuation predecessor bytes: ' + relative)
    if fingerprint(ast.parse(data)) != row['predecessor_ast_sha256']:
        raise AssertionError('Changed continuation predecessor AST: ' + relative)
    return data


def predecessor(relative, data):
    row = record()['modules'].get(relative)
    if row is None:
        return data
    prior = retained(relative, row)
    digest = hashlib.sha256(data).hexdigest()
    if digest not in (row['predecessor_sha256'], row['successor_sha256']):
        raise AssertionError('Changed complete continuation source: ' + relative)
    return prior


def restore_continuation(tree, relative):
    row = record()['modules'].get(relative)
    if row is None:
        return tree
    before = ast.parse(retained(relative, row))
    digest = fingerprint(tree)
    if digest == row['predecessor_ast_sha256']:
        return tree
    if digest != row['successor_ast_sha256']:
        raise AssertionError('Changed complete continuation AST: ' + relative)
    tree = deepcopy(tree)
    for edit in row['edits']:
        container, old_container = tree, before
        for parent in edit['path'][:-1]:
            container = mapping(container)[parent]
            old_container = mapping(old_container)[parent]
        name = edit['path'][-1]
        current = mapping(container).get(name)
        if current is None or fingerprint(current) != edit['successor_ast_sha256']:
            raise AssertionError('Changed continuation seam: ' + relative + ':' + name)
        index = container.body.index(current)
        if edit['predecessor_ast_sha256'] is None:
            del container.body[index]
        else:
            old = mapping(old_container)[name]
            if fingerprint(old) != edit['predecessor_ast_sha256']:
                raise AssertionError('Changed prior continuation seam: ' + relative)
            container.body[index] = deepcopy(old)
    if fingerprint(tree) != row['predecessor_ast_sha256']:
        raise AssertionError('Incomplete continuation restoration: ' + relative)
    return tree
