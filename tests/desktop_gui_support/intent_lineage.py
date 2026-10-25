"""Restore only the reviewed local-intent seam for historical comparisons."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path

from ast_preservation import preservation_dump

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/'provenance/desktop-control-intent/control_client.before.py'
BEFORE_SHA256='5c614b6f4b568bb6837fc9360913750c574c1ec7343ef283579c79f0744f46c9'
EDITED=('__init__','action','retry','poll_status','tick','close','buttons','render')
ADDED=('_eligible','_retain_intent','_drain_intent')


def predecessor_tree():
    data=BEFORE.read_bytes()
    if hashlib.sha256(data).hexdigest()!=BEFORE_SHA256:
        raise AssertionError('The retained pre-fix client changed')
    return ast.parse(data.decode('utf-8'))


def controller(tree):
    matches=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ClientController']
    if len(matches)!=1:raise AssertionError('Exactly one client controller is required')
    return matches[0]


def signature(node):
    node=deepcopy(node);node.body=[ast.Pass()]
    return preservation_dump(node)


def restore_predecessor(tree):
    """Keep every other definition intact; do not exempt the whole controller."""
    tree=deepcopy(tree);before=predecessor_tree()
    if preservation_dump(tree)==preservation_dump(before):return tree
    prior={n.name:n for n in controller(before).body if isinstance(n,ast.FunctionDef)}
    current=controller(tree)
    for name in (*EDITED,*ADDED):
        matches=[n for n in current.body if isinstance(n,ast.FunctionDef) and n.name==name]
        if len(matches)!=1:raise AssertionError('Missing or duplicate declared intent method: '+name)
        if name in EDITED and signature(matches[0])!=signature(prior[name]):
            raise AssertionError('Existing method signature changed: '+name)
    current.body=[deepcopy(prior[n.name]) if isinstance(n,ast.FunctionDef) and n.name in EDITED else n
        for n in current.body if not isinstance(n,ast.FunctionDef) or n.name not in ADDED]
    return tree
