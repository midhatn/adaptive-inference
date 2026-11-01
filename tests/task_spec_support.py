"""Small data fixtures; domains are test data, not product modes."""
from adaptive_inference.task_spec import BUDGET, SCHEMA, digest


def spec_data(*, prompt='Read notes.txt and write a brief summary to answer.txt.',
              inputs=None, outputs=None, expected=None):
    if inputs is None:
        inputs = {'notes.txt': b'First note.\nSecond note.\n'}
    if outputs is None:
        outputs = [('answer.txt', 'text')]
    return {'schema': SCHEMA, 'prompt': prompt,
        'inputs': [{'name': name, 'sha256': digest(raw), 'bytes': len(raw)} for name, raw in inputs.items()],
        'outputs': [{'name': name, 'required': True, 'format': form, 'max_chars': 4096} for name, form in outputs],
        'budget': dict(BUDGET), 'validation': {'validator': None if expected is None else
            {'id': 'json-equals.v1', 'expected': {name: digest(value) for name, value in expected.items()}}}}
