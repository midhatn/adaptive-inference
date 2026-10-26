"""Restore only exact, complete thread-repair files to the preserved failed source."""
import ast
import hashlib
import json

from paused_expiry_lineage import ROOT, fingerprint

ARCHIVE=ROOT/'provenance/paused-budget-expiry/thread-successor'


def record():return json.loads((ARCHIVE/'source-lineage.json').read_text(encoding='utf-8'))


def predecessor(relative,data):
    from continuation_lineage import predecessor as continuation_predecessor
    data=continuation_predecessor(relative,data)
    row=record()['modules'].get(relative)
    if row is None:return data
    if hashlib.sha256(data).hexdigest()!=row['successor_sha256']:
        raise AssertionError('Changed exact thread successor: '+relative)
    prior=(ARCHIVE/row['predecessor_source']).read_bytes()
    if hashlib.sha256(prior).hexdigest()!=row['predecessor_sha256']:
        raise AssertionError('Changed failed thread predecessor: '+relative)
    return prior


def restore_thread(tree,relative):
    from continuation_lineage import restore_continuation
    tree=restore_continuation(tree,relative)
    row=record()['modules'].get(relative)
    if row is None:return tree
    prior=(ARCHIVE/row['predecessor_source']).read_bytes()
    if hashlib.sha256(prior).hexdigest()!=row['predecessor_sha256']:
        raise AssertionError('Changed failed thread predecessor: '+relative)
    before=ast.parse(prior)
    if fingerprint(tree)==fingerprint(before):return tree
    if fingerprint(tree)!=row['successor_ast_sha256']:
        raise AssertionError('Changed complete thread successor AST: '+relative)
    return before
