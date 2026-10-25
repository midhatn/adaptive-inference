"""Restore only declared clock/Pause-activity edits to the immutable failed source."""
import ast
from copy import deepcopy
import hashlib
import json

from paused_expiry_lineage import ROOT, mapping, fingerprint

ARCHIVE=ROOT/'provenance/paused-budget-expiry/clock-successor'


def record():return json.loads((ARCHIVE/'source-lineage.json').read_text(encoding='utf-8'))


def predecessor(relative, data=None):
    from thread_pause_lineage import predecessor as thread_predecessor
    if data is not None:data=thread_predecessor(relative,data)
    row=record()['modules'].get(relative)
    if row is None:return data
    if data is not None and hashlib.sha256(data).hexdigest()!=row['successor_sha256']:
        raise AssertionError('Changed exact clock successor: '+relative)
    prior=(ARCHIVE/row['predecessor_source']).read_bytes()
    if hashlib.sha256(prior).hexdigest()!=row['predecessor_sha256']:
        raise AssertionError('Changed failed clock predecessor: '+relative)
    return prior


def restore_clock(tree,relative):
    from thread_pause_lineage import restore_thread
    tree=restore_thread(tree,relative)
    row=record()['modules'].get(relative)
    if row is None:return tree
    before=ast.parse(predecessor(relative));tree=deepcopy(tree)
    if fingerprint(tree)==fingerprint(before):return tree
    for edit in row['edits']:
        container,old_container=tree,before
        for parent in edit['path'][:-1]:
            container=mapping(container)[parent];old_container=mapping(old_container)[parent]
        name=edit['path'][-1];current=mapping(container).get(name)
        if current is None or fingerprint(current)!=edit['successor_ast_sha256']:
            raise AssertionError('Changed declared clock seam: '+relative+':'+name)
        index=container.body.index(current)
        if edit['predecessor_ast_sha256'] is None:del container.body[index]
        else:
            old=mapping(old_container)[name]
            if fingerprint(old)!=edit['predecessor_ast_sha256']:raise AssertionError('Changed prior clock seam')
            container.body[index]=deepcopy(old)
    return tree
