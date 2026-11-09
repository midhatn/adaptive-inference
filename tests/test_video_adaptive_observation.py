"""Real inert child handles and fake loopback observations; no desktop sampling."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
RETAINED_JOINS = []
OBSERVATIONS = []


def load(name):
    spec = importlib.util.spec_from_file_location(name,
        ROOT / 'examples/validation/video_coexistence' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parent = load('run_adaptive')
observer = load('observe_adaptive')


class FakeActivity:
    def __init__(self, before_sample=None):
        self.before_sample = before_sample

    def sample(self):
        if self.before_sample:
            self.before_sample()
        return {'schema': 'adaptive.foreground-sample.v2', 'monotonic_s': time.monotonic(),
                'foreground': {'hwnd': 1, 'pid': 123, 'creation_time_100ns': 456,
                               'valid': True, 'cpu_cores_used': None, 'cpu_window_s': None},
                'session_input_idle_s': 61., 'host': {'cpu_busy_fraction': None,
                    'ram_available_gib': None, 'commit_available_gib': None}, 'errors': []}


class FakeClock:
    def __init__(self):
        self.now = 0.

    def monotonic(self):
        return self.now

    def time(self):
        return 1000. + self.now

    def sleep(self, seconds):
        self.now += seconds


class AdaptiveBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()

    def profile(self, port=18100):
        path = self.folder / 'deployment.json'
        interpreter = str(Path(sys.executable).resolve())
        value = {'schema': 'adaptive.desktop.windows-orders.v1',
            'host_python': {'path': interpreter, 'sha256': parent.sha(interpreter)},
            'worker_python': {'path': interpreter, 'sha256': parent.sha(interpreter)},
            'hermes': {'source': str(self.folder), 'site_packages': str(self.folder)},
            'native_owner': {'package': str(self.folder), 'manifest_sha256': '0' * 64,
                             'provenance_sha256': '0' * 64},
            'gateway': {'listen': {'host': '127.0.0.1', 'port': port},
                'backend': {'kind': 'strata', 'base_url': 'http://127.0.0.1:18098/v1'}},
            'foreground_policy': 'cooperative-owned-foreground.v1'}
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def server(self, responses, delay=0):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.command, self.path))
                code, headers, raw = responses[min(len(calls) - 1, len(responses) - 1)]
                if delay:
                    time.sleep(delay)
                self.send_response(code)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01),
                                  name='fake-adaptive-status')
        thread.start()
        closed = False
        def close():
            nonlocal closed
            if closed:
                return
            server.shutdown()
            server.server_close()
            thread.join(30)
            joined = not thread.is_alive()
            RETAINED_JOINS.append({'kind': 'fake_http_server', 'thread_ident': thread.ident,
                                   'joined': joined})
            self.assertTrue(joined, 'Retained fake status server must join')
            closed = True
        self.addCleanup(close)
        return server.server_port, calls, close

    @staticmethod
    def status(instance='a' * 32):
        raw = json.dumps({'service': 'adaptive-inference', 'instance': instance,
                          'resources': {'admission_allowed': False}, 'scheduler': {}}).encode()
        return 200, {'Content-Type': 'application/json', 'Content-Length': str(len(raw))}, raw

    def observe(self, profile, run, reader, **options):
        settings = {'duration_s': 3, 'sample_interval_s': .01, 'status_interval_s': .03}
        settings.update(options)
        result = observer.observe(profile, run, activity_reader=reader,
            qpc_now=time.perf_counter, clock_id='injected-component-clock',
            **settings)
        rows = [json.loads(line) for line in Path(str(run) + '.api-trace.private.jsonl').read_text().splitlines()]
        OBSERVATIONS.append({'receipt': result, 'rows': rows})
        return result

    def test_preparation_preserves_installed_command_task_and_input_identity(self):
        profile = self.profile()
        task = ROOT / 'examples/tasks/inventory/task.json'
        inputs = task.parent / 'inputs'
        run = self.folder / 'fresh-run'
        command, returned, identity = parent.prepare(profile, run, task, inputs)
        self.assertEqual(command, [str(Path(sys.executable).resolve()), '-I', '-B', '-m',
            'adaptive_inference', 'desktop', '--profile', str(profile), '--run', str(run),
            '--task-spec', str(task), '--task-inputs', str(inputs)])
        self.assertEqual(returned, run)
        self.assertEqual(identity['task_budget']['execution_seconds'], 900)
        self.assertEqual(identity['input_sha256']['inventory.csv'],
                         hashlib.sha256((inputs / 'inventory.csv').read_bytes()).hexdigest())
        self.assertEqual(parent.OUTER_SECONDS, 2700)
        self.assertFalse(run.exists())
        changed = json.loads(task.read_text(encoding='utf-8'))
        changed['budget']['execution_seconds'] = 899
        wrong = self.folder / 'wrong-task.json'
        wrong.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unsupported task contract or execution budget'):
            parent.prepare(profile, run, wrong, inputs)

    def test_actual_inert_children_retain_exit_and_emergency_join(self):
        for name, code, timeout, expected, emergency in (
            ('normal', 'print("inert child")', 30, 0, False),
            ('failed', 'raise SystemExit(7)', 30, 7, False),
            ('timeout', 'import time; time.sleep(60)', .1, None, True),
        ):
            with self.subTest(name=name):
                run = self.folder / name
                result = parent.supervise([sys.executable, '-I', '-B', '-c', code],
                    run, {'fixture': 'inert Python only'}, timeout_s=timeout)
                RETAINED_JOINS.append({'kind': 'inert_child', **result})
                self.assertTrue(result['retained_case_handle_exited'])
                self.assertIsInstance(result['exit_code'], int)
                self.assertEqual(result['emergency_termination_attempted'], emergency)
                self.assertEqual(result['timed_out'], emergency)
                self.assertFalse(result['qualification_claimed'])
                self.assertEqual(result['normal_parent_exit'], name == 'normal')
                if expected is not None:
                    self.assertEqual(result['exit_code'], expected)
                self.assertEqual(json.loads(Path(str(run) + '.supervisor.private.json').read_text()), result)
                with self.assertRaisesRegex(ValueError, 'Fresh'):
                    parent.supervise([sys.executable, '-c', 'raise SystemExit(99)'], run, {})

    def test_observation_keeps_unknown_cpu_gaps_and_never_parses_terminal(self):
        port, calls, close = self.server([self.status()], delay=.05)
        profile = self.profile(port)
        run = self.folder / 'observed'
        def finish_after_response():
            if calls:
                close()
                run.mkdir(exist_ok=True)
                # Deliberately not JSON: existence is the only active case read.
                (run / 'result.private.json').write_text('unread terminal marker')
        result = self.observe(profile, run, FakeActivity(finish_after_response),
                              duration_s=1, status_interval_s=10)
        self.assertEqual(result['end_reason'], 'observation_deadline')
        self.assertTrue(result['terminal_path_exists'])
        self.assertEqual(result['valid_responses'], 1)
        self.assertFalse(result['active_case_file_contents_read'])
        self.assertFalse(result['task_completion_claimed'])
        self.assertTrue(result['sources_unchanged'])
        rows = [json.loads(line) for line in Path(str(run) + '.api-trace.private.jsonl').read_text().splitlines()]
        self.assertGreater(len(rows), 1)
        self.assertEqual(result['maximum_sample_gap_s'],
                         max(row['sample_gap_s'] for row in rows if row['sample_gap_s'] is not None))
        self.assertTrue(all(row['activity']['foreground']['cpu_cores_used'] is None for row in rows))
        self.assertTrue(all(row['activity']['session_input_idle_s'] == 61 for row in rows))
        for row in rows:
            for prefix in ('activity', 'status'):
                if prefix + '_before_deadline_clock' in row:
                    self.assertLessEqual(row[prefix + '_before_deadline_clock'],
                                         row[prefix + '_after_deadline_clock'])
        self.assertEqual(calls, [('GET', '/status')])

    def test_changed_gateway_instance_is_not_combined_into_one_run(self):
        port, calls, _ = self.server([self.status(), self.status('b' * 32)])
        result = self.observe(self.profile(port), self.folder / 'changed', FakeActivity())
        self.assertEqual(result['end_reason'], 'invalid_status_or_identity')
        self.assertEqual(result['gateway_instance'], 'a' * 32)
        self.assertEqual(result['valid_responses'], 1)
        self.assertFalse(result['task_completion_claimed'])
        self.assertEqual(calls, [('GET', '/status'), ('GET', '/status')])

    def test_known_terminal_gateway_requires_real_refusal_after_owned_listener_closes(self):
        port, calls, close = self.server([self.status()])
        run = self.folder / 'closed-gateway'
        original_fetch = observer.fetch_status
        def fetch(opener, url, timeout):
            value = original_fetch(opener, url, timeout)
            close()
            run.mkdir()
            (run / 'result.private.json').write_text('existence only, not JSON')
            return value
        with mock.patch.object(observer, 'fetch_status', side_effect=fetch):
            result = self.observe(self.profile(port), run, FakeActivity(), duration_s=10)
        rows = OBSERVATIONS[-1]['rows']
        requests = [row for row in rows if 'status_timeout_s' in row]
        self.assertEqual(result['end_reason'], 'terminal_path_exists_and_connection_refused')
        self.assertEqual(result['valid_responses'], 1)
        self.assertEqual(calls, [('GET', '/status')])
        self.assertEqual([row['status_timeout_limit_s'] for row in requests], [2., 5.])
        self.assertEqual([row['status_timeout_s'] for row in requests], [2., 5.])
        error = requests[-1]['observation_error']
        self.assertEqual(error['reason_type'], 'ConnectionRefusedError')
        self.assertTrue(error['connection_refused'])
        self.assertIsInstance(error['errno'], int)
        if sys.platform == 'win32':
            self.assertEqual(error['winerror'], 10061)
        self.assertFalse(result['task_completion_claimed'])

    def test_terminal_marker_does_not_turn_timeout_or_reset_into_closure(self):
        for name, error in (('wrapped-timeout', urllib.error.URLError(TimeoutError())),
                            ('response-timeout', TimeoutError()),
                            ('reset', ConnectionResetError(10054, 'fixture reset'))):
            with self.subTest(error=name):
                run = self.folder / name
                calls = []
                def fetch(opener, url, timeout):
                    calls.append(timeout)
                    if len(calls) == 1:
                        run.mkdir()
                        (run / 'result.private.json').write_text('existence only')
                        return json.loads(self.status()[2])
                    raise error
                with mock.patch.object(observer, 'fetch_status', side_effect=fetch):
                    result = self.observe(self.profile(), run, FakeActivity(), duration_s=10)
                self.assertEqual(result['end_reason'], 'three_connection_errors_after_response')
                self.assertEqual(calls, [2., 5., 5., 5.])
                errors = [row['observation_error'] for row in OBSERVATIONS[-1]['rows']
                          if 'observation_error' in row]
                self.assertEqual(len(errors), 3)
                self.assertTrue(all(not item['connection_refused'] for item in errors))
                self.assertFalse(result['qualification_claimed'])

    def test_terminal_marker_without_known_instance_keeps_normal_bound(self):
        run = self.folder / 'unknown-gateway'
        clock = FakeClock()
        calls = []
        def fetch(opener, url, timeout):
            calls.append(timeout)
            run.mkdir(exist_ok=True)
            (run / 'result.private.json').write_text('existence only')
            raise urllib.error.URLError(ConnectionRefusedError(10061, 'fixture refusal'))
        with mock.patch.object(observer, 'time', clock), \
                mock.patch.object(observer, 'fetch_status', side_effect=fetch):
            result = self.observe(self.profile(), run, FakeActivity(), duration_s=.15)
        requests = [row for row in OBSERVATIONS[-1]['rows'] if 'status_timeout_s' in row]
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any(row['terminal_path_exists'] for row in requests))
        self.assertTrue(all(row['status_timeout_limit_s'] == 2. for row in requests))
        self.assertTrue(all(0 < bound <= 2. for bound in calls))
        self.assertEqual(result['end_reason'], 'observation_deadline')
        self.assertIsNone(result['gateway_instance'])

    def test_known_instance_without_terminal_marker_keeps_normal_bound(self):
        calls = []
        def fetch(opener, url, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                return json.loads(self.status()[2])
            raise urllib.error.URLError(ConnectionRefusedError(10061, 'fixture refusal'))
        with mock.patch.object(observer, 'fetch_status', side_effect=fetch):
            result = self.observe(self.profile(), self.folder / 'no-marker', FakeActivity(),
                                  duration_s=10)
        self.assertEqual(calls, [2., 2., 2., 2.])
        self.assertEqual(result['end_reason'], 'three_connection_errors_after_response')
        self.assertFalse(result['terminal_path_exists'])

    def test_terminal_timeout_is_clamped_to_original_outer_allowance(self):
        clock = FakeClock()
        run = self.folder / 'near-deadline'
        calls = []
        def fetch(opener, url, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                run.mkdir()
                (run / 'result.private.json').write_text('existence only')
                clock.now = 9.5
                return json.loads(self.status()[2])
            clock.now += timeout
            raise TimeoutError()
        with mock.patch.object(observer, 'time', clock), \
                mock.patch.object(observer, 'fetch_status', side_effect=fetch):
            result = self.observe(self.profile(), run, FakeActivity(), duration_s=10)
        self.assertEqual(calls, [2., .5])
        self.assertEqual(result['elapsed_s'], 10.)
        self.assertEqual(result['end_reason'], 'observation_deadline')
        requests = [row for row in OBSERVATIONS[-1]['rows'] if 'status_timeout_s' in row]
        self.assertEqual(requests[-1]['status_timeout_limit_s'], 5.)
        self.assertEqual(requests[-1]['status_timeout_s'], .5)

    def test_redirect_and_oversize_are_refused_without_followup(self):
        for response, expected in (
            ((302, {'Location': '/other', 'Content-Length': '0'}, b''), urllib.error.HTTPError),
            ((200, {'Content-Type': 'application/json', 'Content-Length': str(observer.MAX_BYTES + 1)}, b''), ValueError),
        ):
            with self.subTest(response=response[0]):
                port, calls, close = self.server([response])
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), observer.NoRedirect())
                with self.assertRaises(expected):
                    observer.fetch_status(opener, f'http://127.0.0.1:{port}/status', 2)
                self.assertEqual(calls, [('GET', '/status')])
                close()


if __name__ == '__main__':
    unittest.main()
