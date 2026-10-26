"""Reverse only pinned expiry AST edits; retain every outside-seam statement."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ast_preservation import preservation_dump

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'provenance/paused-budget-expiry'


def key(node):
    if isinstance(node,ast.ClassDef):return 'class:'+node.name
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):return 'function:'+node.name
    if isinstance(node,ast.ImportFrom):return 'from:'+str(node.level)+':'+str(node.module)
    if isinstance(node,ast.Import):return 'import:'+','.join(a.name for a in node.names)
    if isinstance(node,ast.Assign):return 'assign:'+','.join(ast.unparse(t) for t in node.targets)
    return 'statement:'+hashlib.sha256(preservation_dump(node).encode()).hexdigest()


def mapping(container):
    result={}
    for node in container.body:
        name=key(node)
        if name in result:raise AssertionError('Duplicate preserved statement key: '+name)
        result[name]=node
    return result


def fingerprint(node):return hashlib.sha256(preservation_dump(node).encode()).hexdigest()


def retained(relative):
    record=json.loads((ARCHIVE/'source-lineage.json').read_text(encoding='utf-8'))['modules'][relative]
    path=ARCHIVE/record['predecessor_source'];data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=record['predecessor_sha256']:
        raise AssertionError('Retained expiry predecessor changed: '+relative)
    return record,ast.parse(data.decode('utf-8'))


def restore_expiry(tree,relative):
    from execution_clock_lineage import restore_clock
    tree=restore_clock(tree,relative)
    record,before=retained(relative)
    tree=deepcopy(tree)
    if preservation_dump(tree)==preservation_dump(before):return tree
    for edit in record['edits']:
        container,old_container=tree,before
        for parent in edit['path'][:-1]:
            container=mapping(container)[parent];old_container=mapping(old_container)[parent]
        name=edit['path'][-1];current=mapping(container).get(name)
        if current is None or fingerprint(current)!=edit['successor_ast_sha256']:
            raise AssertionError('Changed declared expiry seam: '+relative+':'+name)
        index=container.body.index(current)
        if edit['predecessor_ast_sha256'] is None:
            del container.body[index]
        else:
            old=mapping(old_container)[name]
            if fingerprint(old)!=edit['predecessor_ast_sha256']:
                raise AssertionError('Expiry predecessor seam hash changed')
            container.body[index]=deepcopy(old)
    return tree
