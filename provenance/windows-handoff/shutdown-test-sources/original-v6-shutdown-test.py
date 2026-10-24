"""CPU-only shutdown ledger regression checks; no native host/model/UI starts."""
import ast
import asyncio
import contextlib
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('shutdown_harness_v6', HERE / 'run_validation.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class FakeHost:
    def __init__(self, *, fault=None, state='parked', error=None):
        self.controller = SimpleNamespace(events=[{'at': 1, 'from': 'ready', 'to': 'draining'}],
                                          fault=None, state='releasing')
        self.gateway = SimpleNamespace(scheduler=SimpleNamespace(
            closing=True, active=None, pending={}, uncertain=False))
        self.entered, self.finish = asyncio.Event(), asyncio.Event()
        self.final_fault, self.final_state, self.error = fault, state, error
        self.cleanup = {'closed': True, 'owned_children_exited': True}

    async def close(self, *, timeout_s):
        assert timeout_s == 180
        self.entered.set()
        await asyncio.wait_for(self.finish.wait(), 1)
        self.controller.events.extend([
            {'at': 2, 'release': {'released': True, 'confirmed_process_exits': 10}},
            {'at': 3, 'from': 'releasing', 'to': self.final_state}])
        self.controller.fault, self.controller.state = self.final_fault, self.final_state
        if self.error is not None:
            raise self.error
        return deepcopy(self.cleanup)


class ShutdownReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_waits_for_close_and_contains_final_release(self):
        host, result = FakeHost(), {}
        operation = asyncio.create_task(harness.close_controlled_host(host, result))
        await asyncio.wait_for(host.entered.wait(), 1)
        self.assertNotIn('handoff_events', result)
        self.assertNotIn('cleanup', result)
        host.finish.set()
        await asyncio.wait_for(operation, 1)
        self.assertEqual(result['handoff_events'], host.controller.events)
        self.assertIsNot(result['handoff_events'], host.controller.events)
        self.assertEqual(len(result['handoff_events']), 3)
        self.assertEqual(result['cleanup'], host.cleanup)

    async def test_terminal_fault_rejected_after_capturing_full_ledger(self):
        for fault, state in [('gateway_completion_unreconciled', 'fault'), ('other_fault', 'parked'),
                             (None, 'fault')]:
            with self.subTest(fault=fault, state=state):
                host, result = FakeHost(fault=fault, state=state), {}
                host.finish.set()
                with self.assertRaisesRegex(RuntimeError, 'Terminal controller fault'):
                    await harness.close_controlled_host(host, result)
                self.assertEqual(result['handoff_events'], host.controller.events)
                self.assertEqual(len(result['handoff_events']), 3)
                self.assertEqual(result['cleanup'], host.cleanup)

    async def test_failed_close_keeps_final_events_and_original_error(self):
        error = RuntimeError('Native cleanup still owns shutdown')
        host, result = FakeHost(error=error), {}
        host.finish.set()
        with self.assertRaises(RuntimeError) as caught:
            await harness.close_controlled_host(host, result)
        self.assertIs(caught.exception, error)
        self.assertEqual(result['handoff_events'], host.controller.events)
        self.assertNotIn('cleanup', result)

    async def test_terminal_scheduler_state_is_checked_independently_of_controller(self):
        for change in ({'closing': False}, {'active': object()}, {'pending': {1: object()}},
                       {'uncertain': True}):
            with self.subTest(change=change):
                host, result = FakeHost(), {}
                for key, value in change.items():
                    setattr(host.gateway.scheduler, key, value)
                host.finish.set()
                with self.assertRaisesRegex(RuntimeError, 'Terminal gateway completion remains unreconciled'):
                    await harness.close_controlled_host(host, result)
                self.assertIsNone(host.controller.fault)
                self.assertEqual(result['handoff_events'], host.controller.events)
                self.assertEqual(result['cleanup'], host.cleanup)

    async def test_uncertain_active_release_after_host_drive_exit_is_rejected(self):
        from test_windows_host import HostTests
        fixture = HostTests(methodName='test_close_waits_for_actual_scheduler_active_owner')
        await fixture.asyncSetUp()
        try:
            host = fixture.host
            await host.start(timeout_s=5)
            scheduler = host.gateway.scheduler
            ticket = await scheduler.acquire('normal', None)
            result = {}
            closing = asyncio.create_task(harness.close_controlled_host(host, result))
            async def await_closing():
                while not scheduler.closing:
                    await asyncio.sleep(0)
            await asyncio.wait_for(await_closing(), 1)
            await asyncio.wait_for(asyncio.shield(host.drive_task), 1)
            self.assertFalse(closing.done())
            self.assertIs(scheduler.active, ticket)
            await scheduler.release(ticket, uncertain=True)
            with self.assertRaisesRegex(RuntimeError, 'Terminal gateway completion remains unreconciled'):
                await asyncio.wait_for(closing, 2)
            self.assertTrue(scheduler.uncertain)
            self.assertIsNone(host.controller.fault)  # No later controller step can latch it.
            self.assertTrue(result['cleanup']['closed'])
            self.assertEqual(result['handoff_events'], list(host.controller.events))
        finally:
            await fixture.asyncTearDown()

    def test_actual_main_finally_awaits_close_helper_and_marks_failures(self):
        tree = ast.parse((HERE / 'run_validation.py').read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main')
        outer = next(node for node in main.body if isinstance(node, ast.Try))
        cleanup = outer.finalbody[0]
        host_branch = next(node for node in cleanup.body if isinstance(node, ast.If)
                           and isinstance(node.test, ast.Name) and node.test.id == 'host')
        self.assertEqual(len(host_branch.body), 1)
        call = host_branch.body[0].value
        self.assertIsInstance(call, ast.Await)
        self.assertEqual(call.value.func.id, 'close_controlled_host')
        self.assertEqual([arg.id for arg in call.value.args], ['host', 'result'])
        handler = cleanup.handlers[0]
        assignments = [node for node in handler.body if isinstance(node, ast.Assign)]
        self.assertTrue(any(isinstance(node.value, ast.Constant) and node.value.value is False
                            and ast.unparse(node.targets[0]) == "result['passed']" for node in assignments))
        self.assertTrue(any(isinstance(node, ast.Raise) for node in ast.walk(handler)))

    async def test_actual_main_preserves_primary_error_when_close_also_fails(self):
        primary = RuntimeError('Primary startup failure')
        cleanup = RuntimeError('Secondary cleanup failure')
        host = FakeHost(error=cleanup)
        async def start(**kwargs):
            raise primary
        host.start = start
        host.finish.set()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = root / 'owner.json'
            owner.write_text('{}', encoding='utf-8')
            args = SimpleNamespace(case='controlled', run=root/'run', owner_config=owner)
            fake_module = SimpleNamespace(DesktopHost=lambda *args, **kwargs: host)
            with mock.patch.dict('sys.modules', {'windows_host': fake_module}), \
                 mock.patch.object(harness.threading, 'Thread'), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError) as caught:
                    await harness.main(args)
            self.assertIs(caught.exception, primary)
            receipt = json.loads((args.run/'result.private.json').read_text())
            self.assertFalse(receipt['passed'])
            self.assertEqual(receipt['error'], 'RuntimeError: Primary startup failure')
            self.assertEqual(receipt['cleanup_error'], 'Secondary cleanup failure')
            self.assertEqual(receipt['handoff_events'], host.controller.events)
            self.assertNotIn('cleanup', receipt)

    def test_main_requires_no_controller_fault_before_acceptance(self):
        tree = ast.parse((HERE / 'run_validation.py').read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'main')
        outer = next(node for node in main.body if isinstance(node, ast.Try))
        host_branch = outer.body[-2]
        self.assertEqual(ast.unparse(host_branch.test), 'host')
        terminal_guard = host_branch.body[-1]
        self.assertEqual(ast.unparse(terminal_guard.test),
                         "host.controller.fault is not None or host.controller.state == 'fault'")
        self.assertIsInstance(terminal_guard.body[0], ast.Raise)
        self.assertEqual(ast.unparse(outer.body[-1]), "result['passed'] = True")

    def test_v5_functions_except_main_and_all_native_helpers_unchanged(self):
        previous = HERE.parent / 'successor-v5'
        def functions(path):
            return {node.name: ast.dump(node, include_attributes=False)
                    for node in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        old, new = functions(previous / 'run_validation.py'), functions(HERE / 'run_validation.py')
        self.assertEqual(set(new) - set(old), {'close_controlled_host'})
        self.assertEqual({k: v for k, v in old.items() if k != 'main'},
                         {k: v for k, v in new.items() if k not in ('main', 'close_controlled_host')})
        for directory in ('native', 'foreground'):
            for source in (previous / directory).rglob('*'):
                if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.md', '.json'):
                    target = HERE / source.relative_to(previous)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),
                                     hashlib.sha256(source.read_bytes()).hexdigest(), str(target))


if __name__ == '__main__':
    unittest.main(verbosity=2)
