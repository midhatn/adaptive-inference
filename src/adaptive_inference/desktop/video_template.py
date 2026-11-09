# SPDX-License-Identifier: Apache-2.0
"""Prepare one fixed video operation and verify its saved artifact evidence.

Reuses the checked protected_video commands/oracle through video_recipe and the
compiler's immutable preparation pattern. No model-selected command or path.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re

from adaptive_inference.desktop.compiler_recipe import Executable, _plain, _hash
from adaptive_inference.desktop.video_profile import VideoSettings
from adaptive_inference.desktop.video_recipe import VideoRecipe, _outputs
from adaptive_inference.task_spec import TaskSpec, strict_json

RECIPE_ID = 'nvenc-testclip.v1'
MEDIA = {'codec_name': 'h264', 'width': 1280, 'height': 720, 'frames': 90}


def _json(value):
    def path_value(value):
        if isinstance(value, Path):
            return str(value)
        raise TypeError('Only prepared JSON values and paths are supported')
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'), default=path_value)


def _contract(spec, args, operation_id):
    if (type(spec) is not TaskSpec or spec.video is None
            or not spec.validate_video_args(args).accepted
            or type(operation_id) is not str or not re.fullmatch('[0-9a-f]{32}', operation_id)):
        raise ValueError('Explicit fixed video task and operation required')


def _root(root):
    root = Path(root)
    _plain(root, directory=True)
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError('Absolute ordinary video operation root required')
    return root


def prepare_video_recipe(settings, *, spec, args, operation_id, root):
    _contract(spec, args, operation_id)
    if type(settings) is not VideoSettings:
        raise ValueError('Trusted pinned video settings required')
    root = _root(root)
    settings.ffmpeg.verify(); settings.ffprobe.verify()
    area = root / operation_id
    area.mkdir()
    recipe = VideoRecipe(settings.ffmpeg, settings.ffprobe, area/'run', settings.environment)
    recipe.verify(fresh=True)
    prepared = {'schema': 'video-preparation.v1', 'spec_sha256': spec.sha256,
                'args': args, 'operation_id': operation_id, 'recipe': asdict(recipe)}
    raw = _json(prepared).encode('utf-8')
    if len(raw) > 131072:
        raise ValueError('Prepared video settings exceed their bound')
    with (area/'prepared.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return recipe


def validate_success_projection(result):
    if (result.get('passed') is not True or result.get('dispatched') is not True
            or type(result.get('artifact_bytes')) is not int or not 0 < result['artifact_bytes'] <= 64*1024*1024
            or type(result.get('media')) is not dict or result['media'] != MEDIA
            or any(type(result['media'][key]) is not type(value) for key,value in MEDIA.items())
            or any(type(result.get(key)) is not str or not re.fullmatch('[0-9a-f]{64}', result[key])
                   for key in ('artifact_sha256', 'probe_sha256'))
            or result.get('stages') != [{'stage': stage, 'exit_code': 0} for stage in ('encode','probe','decode')]):
        raise ValueError('Successful video result lacks the fixed media proof')


def project_success(recipe, receipt):
    if ([{'stage': row.get('stage'), 'exit_code': row.get('exit_code')} for row in receipt['stages']]
            != [{'stage': stage, 'exit_code': 0} for stage in ('encode','probe','decode')]):
        raise ValueError('Video success requires all three completed stages')
    checked = _outputs(recipe)
    if any(receipt.get(key) != value for key,value in checked.items()):
        raise ValueError('Actual video outputs differ from the owned receipt')
    return {'artifact_sha256': checked['artifact_sha256'], 'artifact_bytes': checked['artifact_bytes'],
            'probe_sha256': checked['probe_sha256'], 'media': dict(MEDIA)}


def _read(path):
    _plain(path)
    if path.stat().st_size > 131072:
        raise ValueError('Video evidence exceeds its bound')
    return strict_json(path.read_bytes())


def verify_video_artifacts(root, *, spec, args, operation_id, result):
    _contract(spec, args, operation_id)
    area = _root(root)/operation_id
    _plain(area, directory=True)
    run = area/'run'
    _plain(run, directory=True)
    prepared = _read(area/'prepared.json')
    if (type(prepared) is not dict or set(prepared) != {'schema','spec_sha256','args','operation_id','recipe'}
            or prepared['schema'] != 'video-preparation.v1' or prepared['spec_sha256'] != spec.sha256
            or prepared['args'] != args or prepared['operation_id'] != operation_id
            or hashlib.sha256(_json(prepared['recipe']).encode()).hexdigest() != result.get('recipe_sha256')):
        raise ValueError('Prepared video identity changed')
    value = prepared['recipe']
    if (type(value) is not dict or set(value) != {'ffmpeg','ffprobe','run','environment','job_memory_mib'}
            or value['run'] != str(run)):
        raise ValueError('Prepared video location differs')
    recipe = VideoRecipe(*(Executable(Path(value[name]['path']), value[name]['sha256'])
                          for name in ('ffmpeg','ffprobe')), run,
                         tuple(tuple(pair) for pair in value['environment']), value['job_memory_mib'])
    receipt_path = run/'receipt.json'
    receipt = _read(receipt_path)
    if (type(result) is not dict or result.get('operation_id') != operation_id
            or result.get('recipe_id') != RECIPE_ID or result.get('owned_processes_exited') is not True
            or result.get('status') not in {'passed','failed','interrupted','timed_out','cancelled'}
            or _hash(receipt_path) != result.get('receipt_sha256')
            or receipt.get('schema') != 'video-recipe.v1' or receipt.get('recipe_id') != RECIPE_ID
            or receipt.get('status') != result['status'] or receipt.get('passed') != result.get('passed')
            or receipt.get('task_deadline') != result.get('task_deadline')
            or receipt.get('owned_processes_exited') is not True
            or 'cleanup_error' in receipt or 'release_error' in receipt
            or type(receipt.get('children')) is not list
            or any(row.get('joined') is not True or type(row.get('exit_code')) is not int for row in receipt['children'])
            or receipt.get('tools') != {'ffmpeg_sha256': recipe.ffmpeg.sha256, 'ffprobe_sha256': recipe.ffprobe.sha256}):
        raise ValueError('Saved video receipt lacks exact joined identity')
    if result['status'] == 'passed':
        validate_success_projection(result)
        checked = project_success(recipe, receipt)
        if any(result.get(key) != value for key,value in checked.items()):
            raise ValueError('Saved video artifact or probe changed')
    return {}
