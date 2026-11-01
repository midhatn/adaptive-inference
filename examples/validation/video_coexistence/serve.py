# SPDX-License-Identifier: Apache-2.0
"""Manual local video observation; never starts an agent or capture tool."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import sys

import aiohttp
from aiohttp import web

HERE = Path(__file__).resolve().parent
WARMUP_S = 10
MEASURE_S = 180
MAX_EVENTS = 256
MAX_SAMPLES = 220


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Missing or non-finite observation')
    return value


def frame_delta(start, end):
    """W3C totalVideoFrames already includes dropped frames."""
    counters = []
    for sample in (start, end):
        total = number(sample['totalVideoFrames'])
        dropped = number(sample['droppedVideoFrames'])
        if total < 0 or dropped < 0 or dropped > total or int(total) != total or int(dropped) != dropped:
            raise ValueError('Invalid playback counters')
        counters.append((total, dropped))
    total = counters[1][0] - counters[0][0]
    dropped = counters[1][1] - counters[0][1]
    if total <= 0 or dropped < 0 or dropped > total:
        raise ValueError('Playback counters reset or did not advance')
    return {'total_frames': total, 'dropped_frames': dropped,
            'displayed_frames': total-dropped, 'dropped_fraction': dropped/total}


def summarize(report):
    """Completion describes collection, never a performance acceptance verdict."""
    result = {'outcome': report.get('outcome', 'error'), 'reason': str(report.get('reason', 'missing'))[:200]}
    if result['outcome'] not in ('completed', 'incomplete', 'error'):
        result.update(outcome='error', reason='Invalid reported outcome')
    try:
        start, end = report.get('measurement_start'), report.get('measurement_end')
        if start is not None and end is not None:
            result['frames'] = frame_delta(start, end)
            result['elapsed_s'] = (number(end['at_ms'])-number(start['at_ms']))/1000
            result['media_progress_s'] = number(end['media_time_s'])-number(start['media_time_s'])
            result['finish_timer_lateness_ms'] = max(0, result['elapsed_s']*1000-MEASURE_S*1000)
        if result['outcome'] == 'completed':
            if (start is None or end is None or result['reason'] != 'window_elapsed'
                    or number(report['warmup_elapsed_ms']) < WARMUP_S*1000
                    or result['elapsed_s'] < MEASURE_S
                    or report.get('observations_truncated') is not False):
                raise ValueError('Measurement window or observations are incomplete')
    except (KeyError, TypeError, ValueError) as exc:
        result.update(outcome='error', reason=str(exc)[:200])
    return result


class Capture:
    def __init__(self, video, output, condition, notes=''):
        self.video = Path(video).resolve(strict=True)
        if not self.video.is_file():
            raise ValueError('Video must be an existing file')
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.started = self.finished = False
        self.record = {
            'schema': 'adaptive.video-playback-observation.v1', 'created_utc': utc_now(),
            'scope': 'Browser video observations only; no audio-sync, physical-stall, GPU, agent or M3 acceptance',
            'condition': condition, 'operator_notes': notes,
            'clip': {'path': str(self.video), 'size': self.video.stat().st_size, 'sha256': file_hash(self.video)},
            'settings': {'warmup_s': WARMUP_S, 'measurement_s': MEASURE_S,
                         'max_events': MAX_EVENTS, 'max_samples': MAX_SAMPLES},
            'implementation': {'python': sys.version, 'aiohttp': aiohttp.__version__,
                'sources_sha256': {name: file_hash(HERE/name) for name in ('serve.py', 'page.html', 'page.js')}},
            'summary': {'outcome': 'incomplete', 'reason': 'not_started'},
        }
        self.save()

    def save(self):
        temporary = self.output/'result.private.json.tmp'
        temporary.write_text(json.dumps(self.record, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(self.output/'result.private.json')

    def start(self, client):
        if self.started:
            raise web.HTTPConflict(text='This output already has a started run; use a fresh output.')
        self.started = True
        self.record.update(started_utc=utc_now(), browser_start=client)
        self.record['summary'] = {'outcome': 'incomplete', 'reason': 'started_without_terminal_report'}
        self.save()

    def finish(self, report):
        if not self.started or self.finished:
            raise web.HTTPConflict(text='No active unfinished run.')
        if (not isinstance(report, dict) or not isinstance(report.get('events'), list)
                or not isinstance(report.get('samples'), list)
                or len(report['events']) > MAX_EVENTS or len(report['samples']) > MAX_SAMPLES):
            raise web.HTTPBadRequest(text='Invalid or unbounded observation report.')
        self.record.update(finished_utc=utc_now(), browser_report=report, summary=summarize(report))
        self.save()
        self.finished = True
        return self.record['summary']


def make_app(capture):
    # A per-run URL keeps unrelated local web pages from posting a result.
    prefix = '/'+secrets.token_urlsafe(24)
    app = web.Application(client_max_size=512*1024)

    async def page(request):
        return web.FileResponse(HERE/'page.html', headers={'Cache-Control': 'no-store'})

    async def script(request):
        return web.FileResponse(HERE/'page.js', headers={'Cache-Control': 'no-store'})

    async def video(request):
        return web.FileResponse(capture.video)  # aiohttp implements byte ranges.

    async def config(request):
        return web.json_response({'clip_name': capture.video.name, 'condition': capture.record['condition'],
            **capture.record['settings']}, headers={'Cache-Control': 'no-store'})

    async def start(request):
        capture.start(await request.json())
        return web.json_response({'started': True})

    async def finish(request):
        return web.json_response(capture.finish(await request.json()))

    app.add_routes([web.get(prefix+'/', page), web.get(prefix+'/page.js', script),
                    web.get(prefix+'/video', video), web.get(prefix+'/config', config),
                    web.post(prefix+'/start', start), web.post(prefix+'/finish', finish)])
    return app, prefix


async def serve(capture, port):
    app, prefix = make_app(capture)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '127.0.0.1', port).start()
        actual_port = runner.addresses[0][1]
        print(f'Open http://127.0.0.1:{actual_port}{prefix}/ and click Start measurement.', flush=True)
        print(f'Result: {capture.output / "result.private.json"}; Ctrl+C stops this server.', flush=True)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Fresh directory; existing directories are refused')
    parser.add_argument('--condition', required=True, choices=('baseline-before', 'adaptive', 'baseline-after', 'uncontrolled'))
    parser.add_argument('--notes', default='', help='Declared display, power, driver/HAGS and external run references')
    parser.add_argument('--port', type=int, default=0, help='Loopback port; 0 selects a free port')
    args = parser.parse_args()
    capture = Capture(args.video, args.output, args.condition, args.notes)
    try:
        asyncio.run(serve(capture, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
