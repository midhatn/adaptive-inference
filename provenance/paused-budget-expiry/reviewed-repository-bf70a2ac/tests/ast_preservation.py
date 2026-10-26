"""Compare the existing Python 3.11 AST fixtures on CI Python 3.11/3.12.

Python 3.12 added type_params to these three definitions, including an empty
list for old syntax: https://docs.python.org/3.12/library/ast.html#ast.FunctionDef
Only that empty representation difference is omitted. New generic parameters
are rejected rather than hidden; all historical expected digests stay intact.
"""
import ast
from copy import deepcopy


def preservation_dump(tree):
    tree = deepcopy(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and hasattr(node, 'type_params'):
            parameters = node.type_params
            if type(parameters) is not list or parameters:
                raise ValueError('New or invalid type parameters are outside the preserved Python 3.11 source')
            del node.type_params
    return ast.dump(tree, include_attributes=False)
