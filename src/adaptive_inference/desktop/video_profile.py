# SPDX-License-Identifier: Apache-2.0
"""Explicit external FFmpeg tools for the fixed calibration-clip recipe.

No binaries are bundled or auto-installed. Call the selected build under its
own license; https://ffmpeg.org/legal.html describes build-dependent terms.
"""
from dataclasses import dataclass

from adaptive_inference.desktop.compiler_recipe import Executable


@dataclass(frozen=True)
class VideoSettings:
    ffmpeg: Executable
    ffprobe: Executable
    environment: tuple


def video_settings(value):
    from adaptive_inference.desktop.profile import fields, absolute, pin
    fields(value, {'schema', 'environment', 'ffmpeg', 'ffprobe'}, 'video settings')
    if value['schema'] != 'adaptive.video-settings.v1':
        raise ValueError('Unsupported video settings')
    environment = value['environment']
    if (type(environment) is not dict or not environment or len(environment) > 128
            or any(type(k) is not str or not k or '=' in k or '\x00' in k
                   or type(v) is not str or '\x00' in v for k, v in environment.items())
            or len({key.upper() for key in environment}) != len(environment)):
        raise ValueError('Explicit unambiguous video environment required')
    tools = []
    for name in ('ffmpeg', 'ffprobe'):
        tool = fields(value[name], {'path', 'sha256'}, 'video executable')
        tools.append(Executable(absolute(tool['path']), pin(tool['sha256'])))
    return VideoSettings(*tools, environment=tuple(sorted(environment.items())))


def verify_settings(settings):
    if type(settings) is not VideoSettings:
        raise ValueError('Video task requires explicit deployment tools')
    settings.ffmpeg.verify()
    settings.ffprobe.verify()
