# SPDX-License-Identifier: Apache-2.0
"""Host-supplied compiler binding for the existing bounded Hermes worker.

The capability is private launch data, never model-visible tool arguments.
The host independently verifies durable intent before dispatch. This reader
does not grant a new deadline, operation, or network destination.
"""
import hashlib
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from adaptive_inference.desktop.hermes.recovery import Recovery, ReconciliationRequired
from adaptive_inference.task_spec import strict_json

SCHEMA = 'adaptive.compiler-worker-binding.v1'
FIELDS = {'schema', 'host_epoch', 'task_id', 'execution_id', 'task_deadline',
          'gateway_instance', 'capability'}


def make_recovery(owned, db, work, run, *, task_spec, plan, args, **kwargs):
    """Select the opted-in controller before bootstrap or SDK construction."""
    path = getattr(args, 'compiler_binding', None)
    expected = getattr(args, 'compiler_binding_sha256', None)
    if task_spec is None or task_spec.compiler is None:
        if path is not None or expected is not None:
            raise ReconciliationRequired('File-only task cannot receive compiler authority')
        return Recovery(owned, db, work, run, **kwargs)
    if (path is None or type(expected) is not str
            or re.fullmatch('[0-9a-f]{64}', expected) is None):
        raise ReconciliationRequired('Compiler task requires its explicit host binding')
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file():
        raise ReconciliationRequired('Compiler binding must be an ordinary absolute file')
    if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
        raise ReconciliationRequired('Redirected compiler binding refused')
    with path.open('rb') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096 or hashlib.sha256(raw).hexdigest() != expected:
        raise ReconciliationRequired('Compiler binding changed')
    binding = strict_json(raw)
    cp = owned.checkpoint
    logical = cp.metadata.get('adaptive_inference.execution_authorization.v1', {}).get('logical_task_id', cp.task_id)
    endpoint = urlsplit(plan['gateway'])
    deadline = cp.state.get('deadline_monotonic')
    if (type(binding) is not dict or set(binding) != FIELDS or binding['schema'] != SCHEMA
            or binding['task_id'] != logical or binding['execution_id'] != cp.task_id
            or binding['gateway_instance'] != args.gateway_instance
            or type(binding['task_deadline']) not in (int, float)
            or not math.isfinite(binding['task_deadline']) or binding['task_deadline'] != deadline
            or deadline != args.deadline_monotonic
            or endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1'
            or endpoint.path != '/v1' or endpoint.username is not None
            or endpoint.password is not None or endpoint.query or endpoint.fragment or endpoint.port is None):
        raise ReconciliationRequired('Compiler binding differs from the original selected task')
    from adaptive_inference.desktop.hermes.compiler_client import CompilerClient
    from adaptive_inference.desktop.hermes.compiler_recovery import CompilerRecovery
    client = CompilerClient(endpoint.port, binding['capability'], deadline)
    return CompilerRecovery(owned, db, work, run, compiler_client=client,
        host_epoch=binding['host_epoch'], task_id=logical, execution_id=cp.task_id, **kwargs)
