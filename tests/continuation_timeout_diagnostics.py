"""Opt-in observations for one CPU-fixture timeout; never product acceptance.

Uses documented Task.get_stack(limit=1), without locals, source text, task repr,
exception messages or arbitrary JSON fields. Existing cleanup owns all children.
"""
import json
from pathlib import Path
import time

LIMIT = 65536
ROOT = Path(__file__).resolve().parents[1]
PHASES = {'selected', 'preparing', 'ready', 'running', 'blocked'}


def before_teardown(case, task):
    """Observe the same retained task/handles synchronously, before Stop fencing."""
    record = case.c.continuation.current or {}
    phase = record.get('phase')
    frames = []
    for frame in task.get_stack(limit=1):
        source = Path(frame.f_code.co_filename).resolve()
        frames.append({'source': source.relative_to(ROOT).as_posix()
                       if source.is_relative_to(ROOT) else '<external>',
                       'function': frame.f_code.co_name, 'line': frame.f_lineno})
    children = []
    for item in case.child_receipts[:8]:
        child = item['child']
        children.append({'pid': item['pid'],
                         'created_filetime_100ns': item['created_filetime_100ns'],
                         'selected': child is record.get('child'),
                         'exit_code': child.poll()})
    return {'observed_monotonic': time.monotonic(),
            'phase': phase if phase in PHASES else 'unavailable',
            'task': {'done': task.done(), 'cancelled': task.cancelled(), 'stack': frames},
            'children': children, 'children_truncated': len(case.child_receipts) > 8,
            'scope': 'Observation before fixture teardown; no timeout cause or success inferred'}


def _read(path, *, lines=False):
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Fixture diagnostic exceeds byte bound')
    if lines:
        rows = data.splitlines()
        if len(rows) > 256:
            raise ValueError('Fixture diagnostic exceeds row bound')
        return [json.loads(row) for row in rows]
    return json.loads(data)


def _summary(path, kind):
    try:
        data = _read(path, lines=kind == 'events')
        if kind == 'events':
            rows = []
            for row in data:
                if row.get('kind') == 'worker_launched':
                    rows.append({key: row[key] for key in ('pid', 'at_monotonic')
                                 if type(row.get(key)) in (int, float)})
            return {'worker_launched': rows[-8:], 'truncated': len(rows) > 8}
        if kind == 'bootstrap':
            return {key: data[key] for key in ('pid', 'revision', 'owner_epoch')
                    if type(data.get(key)) is int}
        result = {key: data[key] for key in
                  ('passed', 'completed', 'service_stopped', 'controlled', 'continuation_cleanup_verified')
                  if type(data.get(key)) is bool}
        if type(data.get('provider_calls')) is int:
            result['provider_calls'] = data['provider_calls']
        return result
    except Exception as exc:
        # A partial/missing/malformed file must not replace the original error
        # or disclose arbitrary file content through its exception message.
        return {'capture_error': type(exc).__name__}


def after_join(case, joined):
    """Summarize only exact fixture files, after retained handles/streams close."""
    if any(item['child'] not in joined for item in case.child_receipts):
        raise ValueError('Retained children have not all joined')
    if any(not stream.closed for stream in case.c.logs):
        raise ValueError('Retained child streams remain open')
    result = {'observed_monotonic': time.monotonic(),
              'events': _summary(case.c.root / 'events.private.jsonl', 'events')}
    record = case.c.continuation.current or {}
    child = record.get('child')
    matches = [item for item in case.child_receipts if item['child'] is child]
    if len(matches) == 1:
        diagnostics = record['diagnostics'].resolve()
        if not diagnostics.is_relative_to(case.c.work.resolve()):
            raise ValueError('Selected fixture diagnostics escaped its run')
        pid = matches[0]['pid']
        result['selected'] = {'pid': pid,
                              'created_filetime_100ns': matches[0]['created_filetime_100ns'],
                              'bootstrap': _summary(diagnostics / f'bootstrap-{pid}.json', 'bootstrap'),
                              'result': _summary(diagnostics / f'result-{pid}.json', 'result')}
    return result
