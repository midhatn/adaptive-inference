# SPDX-License-Identifier: Apache-2.0
"""Prepare ordinary file tasks for the existing desktop host; no execution."""
from pathlib import Path

from .task_spec import BUDGET, MAX_INPUT_BYTES, MAX_SPEC_BYTES, SCHEMA, TaskSpec, _file, canonical, digest


def prepare_task(destination, *, prompt=None, prompt_file=None, inputs=(),
                 output='answer.txt', output_format='text', max_chars=4096):
    """Snapshot selected bytes and publish a validated task.json last.

    An I/O failure may leave a partial destination; it is never reused. No
    caller-provided task content changes the existing budget or validator.
    """
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError(f'Task destination must be new: {destination}')
    if (prompt is None) == (prompt_file is None):
        raise ValueError('Supply exactly one prompt or UTF-8 prompt file')
    if prompt_file is not None:
        prompt = _file(Path(prompt_file), MAX_SPEC_BYTES).decode('utf-8-sig')
    snapshots = [(Path(path).name, _file(Path(path), MAX_INPUT_BYTES)) for path in inputs]
    spec = TaskSpec({'schema': SCHEMA, 'prompt': prompt,
        'inputs': [{'name': name, 'sha256': digest(raw), 'bytes': len(raw)}
                   for name, raw in snapshots],
        'outputs': [{'name': output, 'required': True, 'format': output_format,
                     'max_chars': max_chars}],
        'budget': dict(BUDGET), 'validation': {'validator': None}})
    encoded = canonical(spec.data)
    # All task and selected-file validation precedes the first write.
    destination.mkdir()
    source = destination / 'inputs'
    source.mkdir()
    for name, raw in snapshots:
        with (source / name).open('xb') as stream:
            stream.write(raw)
    spec.verify_inputs(source)
    path = destination / 'task.json'
    with path.open('xb') as stream:
        stream.write(encoded)
    return {'task_spec': str(path), 'task_inputs': str(source),
            'semantic_validation': 'not_checked'}
