# SPDX-License-Identifier: Apache-2.0
"""Fixed NVENC test clip using the existing checked recipe process owner.

Commands/oracle are retained from examples/validation/windows_handoff/
run_validation.py:protected_video. See docs/video-tool-recipe.md for sources,
licenses and the boundary between component and physical qualification.
"""
from dataclasses import dataclass
import asyncio
import json
import math
import os
from pathlib import Path
import time

from adaptive_inference.handoff import ToolRequirements
from .compiler_recipe import (
    Executable, RecipeCleanupError, RecipeInterrupted, _ProcessOwner, _hash, _plain,
)


@dataclass(frozen=True)
class VideoRecipe:
    """Host-prepared pins and fresh output; no agent-controlled argv or paths."""
    ffmpeg: Executable
    ffprobe: Executable
    run: Path
    environment: tuple
    job_memory_mib: int = 2048

    @property
    def recipe_id(self):
        return 'nvenc-testclip.v1'

    @property
    def artifact(self):
        return 'handoff-video.mp4'

    @property
    def max_seconds(self):
        return 90

    @property
    def requirements(self):
        return ToolRequirements(8, 12, 6000)

    def verify(self, *, fresh=False):
        if not isinstance(self.run, Path) or not self.run.is_absolute():
            raise ValueError('Absolute video run directory required')
        _plain(self.run.parent, directory=True)
        if fresh and self.run.exists():
            raise ValueError('Recipe output already exists; consumed runs are never replayed')
        if self.run.exists():
            _plain(self.run, directory=True)
        if type(self.job_memory_mib) is not int or not 64 <= self.job_memory_mib <= 65536:
            raise ValueError('Bounded job memory limit required')
        if (type(self.environment) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2
                    or any(type(value) is not str or '\x00' in value for value in pair)
                    or not pair[0] or '=' in pair[0] for pair in self.environment)
                or len({pair[0].casefold() for pair in self.environment}) != len(self.environment)):
            raise ValueError('Explicit unique environment required')
        for tool in (self.ffmpeg, self.ffprobe):
            if type(tool) is not Executable:
                raise TypeError('Pinned Executable required')
            tool.verify()

    def commands(self):
        # Preserve the historically checked arguments; no encoder fallback.
        video = str(self.run / self.artifact)
        return (
            ('encode', [str(self.ffmpeg.path), '-hide_banner', '-nostdin', '-n',
                '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30', '-t', '3',
                '-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p', '-an', video]),
            ('probe', [str(self.ffprobe.path), '-v', 'error', '-count_frames',
                '-select_streams', 'v:0', '-show_entries',
                'stream=codec_name,width,height,nb_read_frames', '-of', 'json', video]),
            ('decode', [str(self.ffmpeg.path), '-hide_banner', '-nostdin', '-v',
                'error', '-i', video, '-f', 'null', '-']),
        )


def _outputs(recipe):
    artifact = recipe.run / recipe.artifact
    _plain(artifact)
    if not 0 < artifact.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('Video artifact is empty or exceeds its bound')
    probe = recipe.run / 'probe.log'
    _plain(probe)
    if probe.stat().st_size > 1024 * 1024:
        raise ValueError('Video probe exceeds its bound')
    body = json.loads(probe.read_bytes())
    expected = {'codec_name': 'h264', 'width': 1280, 'height': 720, 'nb_read_frames': '90'}
    if type(body) is not dict or body.get('streams') != [expected]:
        raise ValueError('Video probe did not confirm the exact H264 1280x720 90-frame clip')
    decode = recipe.run / 'decode.log'
    _plain(decode)
    if decode.stat().st_size:
        raise ValueError('Video decode reported errors')
    return {'artifact': recipe.artifact, 'artifact_sha256': _hash(artifact),
        'artifact_bytes': artifact.stat().st_size, 'probe': expected,
        'probe_sha256': _hash(probe), 'decode_sha256': _hash(decode)}


async def run_recipe(controller, recipe, *, task_deadline, clock=time.perf_counter,
                     _owner_factory=_ProcessOwner):
    """One grant for encode/probe/decode, including wait in the original budget.

    The host persists intent before calling and the receipt before another model
    generation. Cleanup ownership/cancellation follows compiler_recipe; an
    uncertain exit keeps inference closed. This function never renews a budget.
    """
    if type(recipe) is not VideoRecipe:
        raise TypeError('Prepared VideoRecipe required')
    recipe.verify(fresh=True)
    started = clock()
    if type(task_deadline) not in (int, float) or not math.isfinite(task_deadline) or task_deadline <= started:
        raise ValueError('Live original execution deadline required')
    deadline = min(task_deadline, started + recipe.max_seconds)
    recipe.run.mkdir()
    receipt = {'schema': 'video-recipe.v1', 'recipe_id': recipe.recipe_id,
        'status': 'failed', 'passed': False, 'task_deadline': task_deadline,
        'deadline': deadline, 'started': started, 'job_commit_limit_mib': recipe.job_memory_mib,
        'tools': {'ffmpeg_sha256': recipe.ffmpeg.sha256, 'ffprobe_sha256': recipe.ffprobe.sha256},
        'stages': [], 'children': [], 'owned_processes_exited': False,
        'scope': 'fixed synthetic silent NVENC clip; no agent/model, H3, audio, playback or reboot qualification'}
    grant = owner = None
    cancelled = False
    cleanup_error = None
    try:
        grant = await controller.acquire_tool(recipe.requirements, timeout_s=max(.01, deadline - clock()))
        receipt['grant_token'] = grant.token
        owner = _owner_factory(recipe.job_memory_mib, dict(recipe.environment), clock=clock)
        for stage, command in recipe.commands():
            recipe.verify()
            owner.check(deadline, grant.interruption)
            row = {'stage': stage, 'argv': command, 'started': clock()}
            receipt['stages'].append(row)
            code = await owner.run(command, cwd=recipe.run, log=recipe.run / (stage + '.log'),
                deadline=deadline, interruption=grant.interruption)
            row.update(exit_code=code, finished=clock())
            if code != 0:
                receipt.update(status='failed', failure_stage=stage)
                break
        else:
            owner.check(deadline, grant.interruption)
            recipe.verify()
            receipt.update(_outputs(recipe))
            receipt.update(status='passed', passed=True)
    except asyncio.CancelledError:
        cancelled = True
        receipt['status'] = 'cancelled'
    except RecipeInterrupted as error:
        receipt.update(status='interrupted', error=str(error))
    except TimeoutError as error:
        receipt.update(status='timed_out', error=str(error))
    except Exception as error:
        receipt.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
    finally:
        if owner is not None:
            cleanup = asyncio.create_task(owner.close())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            try:
                receipt['job_accounting'] = cleanup.result()
                receipt['job_terminated'] = owner.terminated
                receipt['owned_processes_exited'] = True
            except Exception as error:
                cleanup_error = error
                receipt['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
            receipt['children'] = owner.records
        else:
            receipt['owned_processes_exited'] = True
        if grant is not None:
            try:
                controller.complete_tool(grant, owned_processes_exited=receipt['owned_processes_exited'])
            except Exception as error:
                cleanup_error = error
                receipt['release_error'] = {'type': type(error).__name__, 'message': str(error)}
        if cancelled or cleanup_error:
            receipt.update(passed=False, status='cleanup_unconfirmed' if cleanup_error else 'cancelled')
        receipt['finished'] = clock()
        with (recipe.run / 'receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(receipt, stream, indent=2, ensure_ascii=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    if cleanup_error:
        error = RecipeCleanupError('Recipe ownership remains unconfirmed; inference must stay closed')
        error.owner, error.receipt = owner, receipt
        raise error from cleanup_error
    if cancelled:
        raise asyncio.CancelledError
    return receipt
