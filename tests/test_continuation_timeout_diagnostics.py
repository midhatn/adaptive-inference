"""Timeout evidence preserves actual CPU-child cleanup and the original error."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import continuation_timeout_diagnostics as diagnostic
import test_continuation_host as fixture


class DiagnosticBoundaryTests(unittest.TestCase):
    def test_suspended_source_location_does_not_export_locals_or_cancel_task(self):
        async def observe():
            entered = asyncio.Event()
            release = asyncio.Event()
            async def suspended():
                credential = 'private-frame-value-never-export'
                entered.set()
                await release.wait()
                return credential
            task = asyncio.create_task(suspended())
            await entered.wait()
            child = SimpleNamespace(poll=lambda: None)
            identity = {'child': child, 'pid': 123, 'created_filetime_100ns': 134378523922675271}
            case = SimpleNamespace(c=SimpleNamespace(continuation=SimpleNamespace(
                current={'phase': 'preparing', 'child': child})), child_receipts=[identity])
            try:
                evidence = diagnostic.before_teardown(case, task)
                self.assertEqual(evidence['phase'], 'preparing')
                self.assertFalse(evidence['task']['done'])
                self.assertFalse(evidence['task']['cancelled'])
                frame, = evidence['task']['stack']
                self.assertEqual(frame['source'], 'tests/test_continuation_timeout_diagnostics.py')
                self.assertEqual(frame['function'], 'suspended')
                self.assertGreater(frame['line'], 0)
                self.assertEqual(evidence['children'][0]['created_filetime_100ns'], 134378523922675271)
                self.assertTrue(evidence['children'][0]['selected'])
                text = json.dumps(evidence)
                self.assertNotIn('private-frame-value', text)
                self.assertNotIn(str(diagnostic.ROOT), text)
                self.assertNotIn('credential', text)
            finally:
                release.set()
                self.assertEqual(await task, 'private-frame-value-never-export')
        asyncio.run(observe())

    def test_join_guard_and_bounded_allowlists_do_not_export_file_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root/'work'; work.mkdir()
            selected = work/'selected'; selected.mkdir()
            # Objects retained by real Popen are hashable; use one for this boundary test.
            child = object()
            stream = SimpleNamespace(closed=False)
            case = SimpleNamespace(c=SimpleNamespace(root=root, work=work, logs=[stream],
                continuation=SimpleNamespace(current={'child': child, 'diagnostics': selected})),
                child_receipts=[{'child': child, 'pid': 321, 'created_filetime_100ns': 134378523922675271}])
            with self.assertRaisesRegex(ValueError, 'not all joined'):
                diagnostic.after_join(case, set())
            with self.assertRaisesRegex(ValueError, 'streams remain open'):
                diagnostic.after_join(case, {child})
            stream.closed = True
            (root/'events.private.jsonl').write_text(json.dumps({'kind': 'worker_launched',
                'pid': 321, 'at_monotonic': 17.5, 'secret': 'private-json-value'})+'\n', encoding='utf-8')
            (selected/'bootstrap-321.json').write_text(json.dumps({'pid': 321, 'revision': 9,
                'owner_epoch': 8, 'prompt': 'private-json-value'}), encoding='utf-8')
            result = selected/'result-321.json'
            result.write_text(json.dumps({'passed': False, 'completed': False, 'provider_calls': 0,
                'service_stop': {'secret': 'private-json-value'}, 'error': 'private-json-value'}), encoding='utf-8')
            observed = diagnostic.after_join(case, {child})
            self.assertEqual(observed['events']['worker_launched'], [{'pid': 321, 'at_monotonic': 17.5}])
            self.assertEqual(observed['selected']['result'], {'passed': False, 'completed': False, 'provider_calls': 0})
            self.assertNotIn('private-json-value', json.dumps(observed))
            for content, expected in ((b'{"secret":', 'JSONDecodeError'),
                                      (b'x'*(diagnostic.LIMIT+1), 'ValueError')):
                result.write_bytes(content)
                self.assertEqual(diagnostic.after_join(case, {child})['selected']['result'],
                                 {'capture_error': expected})


@unittest.skipUnless(os.name == 'nt', 'Windows retained-process CPU timeout fixture')
class TimeoutCleanupTests(unittest.TestCase):
    def run_held_transition(self, *, capture_fails=False):
        class HeldTransition(fixture.HostTests):
            async def asyncSetUp(self):
                await super().asyncSetUp()
                release = asyncio.Event(); self.releases.append(release)
                self.hold_entered = False
                async def held_ready(record, intent_valid):
                    self.hold_entered = True
                    await release.wait()
                self.c.ready_continuation = held_ready

            async def test_injected_timeout(self):
                await self.test_transport_continue_preserves_live_intent_and_duplicate_does_not_launch()

            async def asyncTearDown(self):
                # Bound the regression's cleanup only; do not alter the tested
                # five-second wait, product deadlines or CPU child watchdog.
                await asyncio.wait_for(super().asyncTearDown(), 20)

        case = HeldTransition('test_injected_timeout'); result = unittest.TestResult()
        parent_destination = os.environ.get('CONTINUATION_TEST_RECEIPTS')
        with tempfile.TemporaryDirectory() as directory:
            patches = [mock.patch.dict(os.environ, {'CONTINUATION_TEST_RECEIPTS': directory})]
            if capture_fails:
                patches.append(mock.patch.object(diagnostic, 'before_teardown',
                                                 side_effect=RuntimeError('private-capture-message')))
                patches.append(mock.patch.object(diagnostic, 'after_join',
                                                 side_effect=RuntimeError('private-capture-message')))
            for patch in patches:patch.start()
            try:case.run(result)
            finally:
                for patch in reversed(patches):patch.stop()
            receipt = json.loads((Path(directory)/'test_injected_timeout.json').read_bytes())
        self.assertEqual(result.testsRun, 1)
        self.assertFalse(result.failures)
        self.assertEqual(len(result.errors), 1)
        self.assertIn('await asyncio.wait_for(asyncio.shield(task),5)', result.errors[0][1])
        self.assertTrue(result.errors[0][1].rstrip().endswith('TimeoutError'))
        self.assertTrue(case.hold_entered)
        self.assertTrue(case.c.runtime._stopping)
        self.assertFalse(case.c.runtime._continuation_tasks)
        self.assertTrue(all(task.done() and not task.cancelled() for task in case.tasks))
        self.assertEqual([child.returncode for child in case.c.handles], [5, 4])
        self.assertTrue(all(stream.closed for stream in case.c.logs))
        self.assertFalse(case.c.work.exists())
        self.assertTrue(all(row['joined'] and not row['cleanup_killed'] for row in receipt['children']))
        self.assertNotIn('private-capture-message', json.dumps(receipt))
        if parent_destination:
            output = Path(parent_destination); output.mkdir(exist_ok=True)
            receipt['injected_error'] = {'expected': 'TimeoutError', 'actual_errors': len(result.errors),
                                         'actual_final_line': result.errors[0][1].rstrip().splitlines()[-1]}
            (output/(self._testMethodName+'.json')).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        return receipt

    def test_actual_timeout_observed_before_stop_then_exact_children_join(self):
        receipt = self.run_held_transition()
        before = receipt['timeout_observation']['before_teardown']
        after = receipt['timeout_observation']['after_join']
        self.assertEqual(before['phase'], 'running')
        self.assertFalse(before['task']['done'])
        self.assertFalse(before['task']['cancelled'])
        selected, = [row for row in before['children'] if row['selected']]
        self.assertIsNone(selected['exit_code'])
        self.assertEqual(after['selected']['pid'], selected['pid'])
        self.assertEqual(after['selected']['created_filetime_100ns'], selected['created_filetime_100ns'])
        self.assertGreater(after['observed_monotonic'], before['observed_monotonic'])
        self.assertEqual(after['selected']['bootstrap']['pid'], selected['pid'])
        self.assertTrue(after['selected']['result']['service_stopped'])
        self.assertTrue(after['selected']['result']['continuation_cleanup_verified'])
        self.assertFalse(after['selected']['result']['passed'])
        self.assertEqual(after['selected']['result']['provider_calls'], 0)

    def test_capture_failures_do_not_replace_actual_timeout_or_skip_cleanup(self):
        receipt = self.run_held_transition(capture_fails=True)
        self.assertEqual(receipt['timeout_observation'], {
            'before_teardown': {'capture_error': 'RuntimeError'},
            'after_join': {'capture_error': 'RuntimeError'}})


if __name__ == '__main__':
    unittest.main()
