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
from pathlib import Path, PureWindowsPath
import re
import stat

from .feedback import Verdict

NAMESPACE = 'adaptive_inference.task_spec.v1'
SCHEMA = 'adaptive.task-spec.v1'
COMPILER_SCHEMA = 'adaptive.task-spec.v2'
COMPILER_RECIPE = 'cpp17-stdout.v1'
COMPILER_STATUSES = frozenset({'passed', 'failed', 'interrupted', 'timed_out', 'cancelled',
                             'cancelled_before_dispatch', 'binding_refused', 'preparation_failed'})
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
        fields = {'schema', 'prompt', 'inputs', 'outputs', 'budget', 'validation'}
        compiler_task = type(data) is dict and data.get('schema') == COMPILER_SCHEMA
        if (type(data) is not dict or set(data) != fields | ({'compiler'} if compiler_task else set())
                or data['schema'] not in (SCHEMA, COMPILER_SCHEMA) or type(data['prompt']) is not str
                or not data['prompt'].strip() or len(data['prompt'].encode('utf-8')) > 16384
                or type(data['budget']) is not dict or data['budget'] != BUDGET
                or any(type(value) is not int for value in data['budget'].values())):
            raise ValueError('Unsupported task contract or execution budget')
        if compiler_task:
            compiler = data['compiler']
            if (type(compiler) is not dict
                    or set(compiler) != {'recipe_id', 'expected_stdout', 'max_source_chars', 'max_runs'}
                    or compiler['recipe_id'] != COMPILER_RECIPE
                    or type(compiler['expected_stdout']) is not str
                    or len(compiler['expected_stdout'].encode('utf-8')) > 4096
                    or type(compiler['max_source_chars']) is not int
                    or not 1 <= compiler['max_source_chars'] <= 16384
                    or type(compiler['max_runs']) is not int or not 1 <= compiler['max_runs'] <= 8):
                raise ValueError('Bounded trusted compiler contract required')
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

    @property
    def compiler(self):
        """Detached explicit authority; existing v1 tasks have none."""
        return self.data.get('compiler')

    def validate_compiler_args(self, args, *, completed_runs=0):
        """Check a proposed source attempt, without writing or acquiring resources."""
        compiler = self.compiler
        if compiler is None:
            return Verdict(False, 'This task does not declare a compiler capability. No compiler was started.')
        if type(completed_runs) is not int or not 0 <= completed_runs <= compiler['max_runs']:
            raise ValueError('Exact completed compiler attempt count required')
        if completed_runs == compiler['max_runs']:
            return Verdict(False, 'The original compiler attempt allowance is exhausted. No compiler was started.')
        if (type(args) is not dict or set(args) != {'recipe_id', 'source'}
                or args['recipe_id'] != compiler['recipe_id'] or type(args['source']) is not str
                or not args['source'].strip() or '\x00' in args['source']
                or len(args['source']) > compiler['max_source_chars']):
            return Verdict(False, 'Use the declared recipe and bounded C++ source only. No compiler was started.')
        try:
            args['source'].encode('utf-8')
        except UnicodeEncodeError:
            return Verdict(False, 'Source must be valid UTF-8 text. No compiler was started.')
        return Verdict(True)

    def compiler_completion(self, receipts):
        """Check normalized receipts already verified by the owning adapter.

        This validates the task's exact stdout oracle and attempt accounting.
        Native intent, host authorization, durable receipt/artifact bytes and
        actual process joins must be verified by the adapter, not inferred here.
        Unknown dispatch/cleanup is never a finalized compiler receipt.
        """
        compiler = self.compiler
        if compiler is None:
            raise ValueError('Task has no compiler contract')
        if type(receipts) is not list or len(receipts) > compiler['max_runs']:
            raise ValueError('Bounded complete compiler receipt history required')
        common = {'operation_id', 'tool_call_id', 'spec_sha256', 'recipe_id', 'source_sha256',
                  'status', 'owned_processes_exited'}
        success_fields = {'stdout_sha256', 'artifact_sha256', 'test_report_sha256'}
        operations, calls, successful = set(), set(), None
        for row in receipts:
            passed = type(row) is dict and row.get('status') == 'passed'
            if (type(row) is not dict or set(row) != common | (success_fields if passed else set())
                    or type(row['status']) is not str or row['status'] not in COMPILER_STATUSES
                    or row['spec_sha256'] != self.sha256 or row['recipe_id'] != compiler['recipe_id']
                    or row['owned_processes_exited'] is not True):
                raise ValueError('Compiler receipt does not establish this task contract')
            for name, seen in (('operation_id', operations), ('tool_call_id', calls)):
                value = row[name]
                if (type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value) is None
                        or value in seen):
                    raise ValueError('Compiler receipt identities must be unique and bounded')
                seen.add(value)
            _sha(row['source_sha256'])
            if passed:
                for name in success_fields:
                    _sha(row[name])
                if row['stdout_sha256'] != digest(compiler['expected_stdout'].encode('utf-8')):
                    raise ValueError('Compiler stdout differs from the exact declared oracle')
                successful = {name: row[name] for name in
                              ('operation_id', 'source_sha256', 'artifact_sha256', 'stdout_sha256', 'test_report_sha256')}
        return {'qualified': successful is not None, 'recipe_id': compiler['recipe_id'],
                'attempts': len(receipts), 'successful': successful}

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
        if type(name) is not str or not name or '\x00' in name or name.endswith(('/', '\\')):
            raise ValueError('File is outside the declared task capability')
        # Inspect syntax before resolving: resolution must never erase traversal,
        # Windows drive-relative, device/UNC or alternate-stream intent.
        windows = PureWindowsPath(name)
        if (name.startswith(('//', '\\\\')) or '..' in re.split(r'[/\\]+', name)
                or windows.drive and (os.name != 'nt' or re.fullmatch('[A-Za-z]:', windows.drive) is None
                                      or not windows.is_absolute())
                or ':' in (name[2:] if windows.drive else name)):
            raise ValueError('File is outside the declared task capability')
        work_info = Path(work).lstat()
        if (not stat.S_ISDIR(work_info.st_mode) or getattr(work_info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('Task workspace must be a real directory')
        root = Path(work).resolve(strict=True)
        candidate = Path(name)
        names = {row['name'] for row in declarations}
        if candidate.is_absolute():
            path = candidate
        elif (not candidate.drive and not candidate.root and
              (name in names or re.fullmatch(r'\.[/\\]+[^/\\]+', name) is not None)):
            path = root / candidate.name
        else:
            raise ValueError('File is outside the declared task capability')
        if (path.name not in names or path.parent != root or not path.parent.samefile(root)
                or path.resolve().parent != root or path.is_symlink()):
            raise ValueError('Declared file escaped task workspace')
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            _file(path, MAX_INPUT_BYTES)
        return root / path.name

    def validate_write(self, name, args, *, work=None):
        if name != 'write_file' or type(args) is not dict:
            raise ValueError('Unexpected validation capability')
        proposed = args.get('path')
        if work is not None:
            try:
                proposed = self.file_path(work, proposed, write=True).name
            except (ValueError, OSError):
                return Verdict(False, 'Use a declared output in this task workspace. No file was written.')
        row = next((row for row in self.data['outputs'] if row['name'] == proposed), None)
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

    def completion(self, work, tools, final_response, *, compiler_receipts=None):
        self.verify_inputs(work)
        writes_by_name = {}
        for tool in tools:
            if tool['name'] == 'write_file':
                name = self.file_path(work, tool['args'].get('path'), write=True).name
                writes_by_name.setdefault(name, []).append(tool)
        artifacts = {}
        for row in self.data['outputs']:
            path = self.file_path(work, row['name'], write=True)
            writes = writes_by_name.get(row['name'], [])
            if not path.exists() and not row['required'] and not writes:
                continue
            if not path.is_file() or not writes:
                raise ValueError('Required output has no durable write receipt')
            raw = _file(path, 4 * row['max_chars'])
            if any(tool['artifact_sha256'] != digest(raw) for tool in writes):
                raise ValueError('Output differs from its durable write receipt')
            content = raw.decode('utf-8')
            if not self.validate_write('write_file', {'path': row['name'], 'content': content}, work=work).accepted:
                raise ValueError('Completed output failed its declared validation')
            artifacts[row['name']] = digest(raw)
        if type(final_response) is not str or not final_response.strip() and not artifacts:
            raise ValueError('Task produced neither a response nor an artifact')
        oracle = self.data['validation']['validator']
        result = {'artifacts': artifacts, 'semantic_validation': 'not_checked' if oracle is None else 'oracle_matched',
                  'validated_artifacts': [] if oracle is None else sorted(oracle['expected'])}
        if self.compiler is not None:
            compiler_result = self.compiler_completion(compiler_receipts)
            if not compiler_result['qualified']:
                raise ValueError('Task requires a validated successful compiler receipt')
            result['compiler'] = compiler_result
        elif compiler_receipts is not None:
            raise ValueError('File-only task cannot acquire a compiler completion contract')
        return result
