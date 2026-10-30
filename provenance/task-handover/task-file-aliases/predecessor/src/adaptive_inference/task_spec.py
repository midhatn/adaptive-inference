# SPDX-License-Identifier: Apache-2.0
"""Immutable, engine-neutral contracts for bounded create-only file tasks.

The prompt and file declarations are task data. Provider configuration belongs
to the adapter. Format checks are not a claim of semantic correctness; the
optional built-in JSON oracle checks only a declared canonical value digest.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .feedback import Verdict

NAMESPACE = 'adaptive_inference.task_spec.v1'
SCHEMA = 'adaptive.task-spec.v1'
BUDGET = {'max_requests': 8, 'max_attempts': 8, 'max_admission_attempts': 32,
          'execution_seconds': 900}
MAX_INPUT_BYTES = 256 * 1024
MAX_SPEC_BYTES = 64 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))
    canonical(value)  # Also rejects numeric overflow parsed as infinity.
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Exact SHA256 required')


def _name(value):
    reserved = {'con', 'prn', 'aux', 'nul', 'clock$', 'conin$', 'conout$'}
    reserved.update(f'{prefix}{n}' for prefix in ('com', 'lpt') for n in range(1, 10))
    if (type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', value) is None
            or value.endswith('.') or value.split('.')[0].casefold() in reserved):
        raise ValueError('A flat portable file name is required')


def _file(path, maximum):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_size > maximum):
        raise ValueError('Declared file must be a bounded regular private file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('Declared file exceeded its bound')
    return raw


@dataclass(frozen=True, init=False)
class TaskSpec:
    _encoded: bytes

    def __init__(self, raw):
        encoded = canonical(raw)
        if len(encoded) > MAX_SPEC_BYTES:
            raise ValueError('Task specification exceeds its bound')
        data = strict_json(encoded)
        if (type(data) is not dict or set(data) != {'schema', 'prompt', 'inputs', 'outputs', 'budget', 'validation'}
                or data['schema'] != SCHEMA or type(data['prompt']) is not str
                or not data['prompt'].strip() or len(data['prompt'].encode('utf-8')) > 16384
                or type(data['budget']) is not dict or data['budget'] != BUDGET
                or any(type(value) is not int for value in data['budget'].values())):
            raise ValueError('Unsupported task contract or execution budget')
        inputs, outputs = data['inputs'], data['outputs']
        if (type(inputs) is not list or type(outputs) is not list or len(inputs) + len(outputs) > 16):
            raise ValueError('Bounded input and output declarations required')
        names = set()
        total = 0
        for row in inputs + outputs:
            if type(row) is not dict:
                raise ValueError('File declaration must be an object')
            _name(row.get('name'))
            key = row['name'].casefold()
            if key in names:
                raise ValueError('File declarations collide')
            names.add(key)
        for row in inputs:
            if (set(row) != {'name', 'sha256', 'bytes'} or type(row['bytes']) is not int
                    or not 0 <= row['bytes'] <= MAX_INPUT_BYTES):
                raise ValueError('Bounded immutable input required')
            _sha(row['sha256']); total += row['bytes']
        if total > MAX_INPUT_BYTES:
            raise ValueError('Combined input size exceeds bound')
        for row in outputs:
            if (set(row) != {'name', 'required', 'format', 'max_chars'} or type(row['required']) is not bool
                    or row['format'] not in ('text', 'json') or type(row['max_chars']) is not int
                    or not 1 <= row['max_chars'] <= 4096):
                raise ValueError('Bounded create-only output required')
        validation = data['validation']
        if type(validation) is not dict or set(validation) != {'validator'}:
            raise ValueError('Explicit validation declaration required')
        oracle = validation['validator']
        if oracle is not None:
            if (type(oracle) is not dict or set(oracle) != {'id', 'expected'} or oracle['id'] != 'json-equals.v1'
                    or type(oracle['expected']) is not dict or not oracle['expected']):
                raise ValueError('Unknown trusted validator')
            allowed = {row['name'] for row in outputs if row['required'] and row['format'] == 'json'}
            if not set(oracle['expected']) <= allowed:
                raise ValueError('Oracle must name required JSON outputs')
            for expected in oracle['expected'].values():
                _sha(expected)
        object.__setattr__(self, '_encoded', encoded)

    @property
    def data(self):
        return strict_json(self._encoded)

    @property
    def prompt(self):
        return self.data['prompt']

    @property
    def sha256(self):
        return digest(self._encoded)

    def metadata(self):
        return {NAMESPACE: {'spec': self.data, 'sha256': self.sha256}}

    @classmethod
    def from_metadata(cls, metadata):
        if NAMESPACE not in metadata:
            return None
        row = metadata[NAMESPACE]
        if type(row) is not dict or set(row) != {'spec', 'sha256'}:
            raise ValueError('Malformed stored task specification')
        spec = cls(row['spec'])
        if spec.sha256 != row['sha256']:
            raise ValueError('Stored task specification changed')
        return spec

    @classmethod
    def read(cls, path, expected_sha256):
        raw = _file(Path(path), MAX_SPEC_BYTES)
        if digest(raw) != expected_sha256:
            raise ValueError('Task specification input changed')
        return cls.from_bytes(raw)

    @classmethod
    def from_bytes(cls, raw):
        if type(raw) is not bytes or len(raw) > MAX_SPEC_BYTES:
            raise ValueError('Bounded serialized task specification required')
        return cls(strict_json(raw))

    def validator_identity(self):
        return {'version': 'bounded-file-validation.v1', 'spec_sha256': self.sha256,
                'source_sha256': digest(Path(__file__).read_bytes())}

    def verify_inputs(self, work):
        work = Path(work).resolve(strict=True)
        for row in self.data['inputs']:
            raw = _file(work / row['name'], row['bytes'])
            if len(raw) != row['bytes'] or digest(raw) != row['sha256']:
                raise ValueError('Immutable task input changed')

    def stage_inputs(self, source, work):
        source, work = Path(source).resolve(strict=True), Path(work).resolve(strict=True)
        self.verify_inputs(source)
        for row in self.data['inputs']:
            raw = _file(source / row['name'], row['bytes'])
            if digest(raw) != row['sha256']:
                raise ValueError('Input changed while staging')
            with (work / row['name']).open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        self.verify_inputs(work)

    def file_path(self, work, name, *, write=False):
        declarations = self.data['outputs'] if write else self.data['inputs'] + self.data['outputs']
        if type(name) is not str or name not in {row['name'] for row in declarations}:
            raise ValueError('File is outside the declared task capability')
        root = Path(work).resolve(strict=True)
        path = root / name
        if path.resolve().parent != root or path.is_symlink():
            raise ValueError('Declared file escaped task workspace')
        if path.exists():
            _file(path, MAX_INPUT_BYTES)
        return path

    def validate_write(self, name, args):
        if name != 'write_file' or type(args) is not dict:
            raise ValueError('Unexpected validation capability')
        row = next((row for row in self.data['outputs'] if row['name'] == args.get('path')), None)
        if row is None or type(args.get('content')) is not str or len(args['content']) > row['max_chars']:
            return Verdict(False, 'Use a declared output name and stay within its text length limit. No file was written.')
        try:
            parsed = strict_json(args['content']) if row['format'] == 'json' else args['content']
        except (ValueError, TypeError, RecursionError):
            return Verdict(False, 'Output must be valid JSON with no duplicate keys or nonfinite numbers. No file was written.')
        oracle = self.data['validation']['validator']
        if oracle is not None and row['name'] in oracle['expected'] and digest(parsed) != oracle['expected'][row['name']]:
            return Verdict(False, 'Output did not match the declared validation check. Recheck the original inputs and correct the proposed content. No file was written.')
        return Verdict(True)

    def completion(self, work, tools, final_response):
        self.verify_inputs(work)
        artifacts = {}
        for row in self.data['outputs']:
            path = self.file_path(work, row['name'], write=True)
            writes = [tool for tool in tools if tool['name'] == 'write_file' and tool['args'].get('path') == row['name']]
            if not path.exists() and not row['required'] and not writes:
                continue
            if not path.is_file() or not writes:
                raise ValueError('Required output has no durable write receipt')
            raw = _file(path, 4 * row['max_chars'])
            if any(tool['artifact_sha256'] != digest(raw) for tool in writes):
                raise ValueError('Output differs from its durable write receipt')
            content = raw.decode('utf-8')
            if not self.validate_write('write_file', {'path': row['name'], 'content': content}).accepted:
                raise ValueError('Completed output failed its declared validation')
            artifacts[row['name']] = digest(raw)
        if type(final_response) is not str or not final_response.strip() and not artifacts:
            raise ValueError('Task produced neither a response nor an artifact')
        oracle = self.data['validation']['validator']
        return {'artifacts': artifacts, 'semantic_validation': 'not_checked' if oracle is None else 'oracle_matched',
                'validated_artifacts': [] if oracle is None else sorted(oracle['expected'])}
