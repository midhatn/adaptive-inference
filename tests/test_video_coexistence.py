"""Video-observation arithmetic and local HTTP output, never playback evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

SOURCE = Path(__file__).resolve().parents[1]/'examples/validation/video_coexistence/serve.py'
SPEC = importlib.util.spec_from_file_location('video_observation', SOURCE)
video = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video)


def report(outcome='completed', reason='window_elapsed'):
    return {'outcome': outcome, 'reason': reason, 'warmup_elapsed_ms': 10000,
        'measurement_start': {'at_ms': 12000, 'media_time_s': 10,
            'totalVideoFrames': 600, 'droppedVideoFrames': 5},
        'measurement_end': {'at_ms': 192000, 'media_time_s': 190,
            'totalVideoFrames': 11400, 'droppedVideoFrames': 17},
        'observations_truncated': False, 'events': [], 'samples': [],
        'callback_observations': {'max_callback_gap_ms': 500, 'skipped_callback_frames': 30}}


class MetricTests(unittest.TestCase):
    def test_warmup_deltas_and_w3c_denominator(self):
        observed = video.summarize(report())
        self.assertEqual(observed['outcome'], 'completed')
        self.assertEqual(observed['frames']['total_frames'], 10800)
        self.assertEqual(observed['frames']['dropped_frames'], 12)
        self.assertEqual(observed['frames']['dropped_fraction'], 12/10800)
        self.assertEqual(observed['elapsed_s'], 180)
        # Missed callbacks are neither physical stalls nor W3C dropped frames.
        self.assertNotIn('physical_stalls', observed)

    def test_reset_short_window_and_truncated_observations_cannot_complete(self):
        for kind in ('reset', 'short', 'truncated'):
            current = report()
            if kind == 'reset': current['measurement_end']['totalVideoFrames'] = 100
            if kind == 'short': current['measurement_end']['at_ms'] = 191999
            if kind == 'truncated': current['observations_truncated'] = True
            with self.subTest(kind=kind):
                self.assertEqual(video.summarize(current)['outcome'], 'error')

    def test_interrupted_measurement_keeps_observations_without_success(self):
        current = report('incomplete', 'manual_stop')
        current['measurement_end']['at_ms'] = 17000
        result = video.summarize(current)
        self.assertEqual(result['outcome'], 'incomplete')
        self.assertEqual(result['elapsed_s'], 5)


class LocalOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_range_response_and_first_terminal_result_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root/'fixture.mp4'; clip.write_bytes(b'0123456789')
            capture = video.Capture(clip, root/'fresh', 'baseline-before', 'synthetic component check')
            saved = capture.output/'result.private.json'
            self.assertEqual(json.loads(saved.read_bytes())['summary']['outcome'], 'incomplete')
            app, prefix = video.make_app(capture)
            client = TestClient(TestServer(app, host='127.0.0.1'))
            await client.start_server()
            try:
                response = await client.get(prefix+'/video', headers={'Range': 'bytes=2-4'})
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers['Content-Range'], 'bytes 2-4/10')
                self.assertEqual(await response.read(), b'234')
                response = await client.post(prefix+'/start', json={'fixture': True})
                self.assertEqual(response.status, 200)
                response = await client.post(prefix+'/finish', json=report())
                self.assertEqual((await response.json())['outcome'], 'completed')
                first = saved.read_bytes()
                self.assertEqual((await client.post(prefix+'/finish', json=report('error', 'later'))).status, 409)
                self.assertEqual(saved.read_bytes(), first)
            finally:
                await client.close()
            self.assertTrue(client.session.closed)

    async def test_fresh_output_and_missing_terminal_report_remain_honest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root/'fixture.mp4'; clip.write_bytes(b'fixture')
            capture = video.Capture(clip, root/'fresh', 'adaptive')
            capture.start({'fixture': True})
            saved = json.loads((capture.output/'result.private.json').read_bytes())
            self.assertEqual(saved['summary'], {'outcome': 'incomplete', 'reason': 'started_without_terminal_report'})
            with self.assertRaises(FileExistsError):
                video.Capture(clip, root/'fresh', 'adaptive')


if __name__ == '__main__':
    unittest.main()
