# SPDX-License-Identifier: Apache-2.0
"""CPU-only actual-SDK and actual-process restart tests; no model requests."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ARGS = None


class RestartTests(unittest.TestCase):
    workers = []

    def prepare(self, name):
        run = ARGS.output / name
        command = [str(ARGS.python), '-I', '-B', str(HERE / 'run_recovery.py'), 'prepare', '--run', str(run),
                   '--hermes-source', str(ARGS.hermes_source), '--canonical', str(ARGS.canonical),
                   '--python', str(ARGS.python), '--fixture']
        proc = subprocess.run(command, capture_output=True, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors='replace'))
        return run

    def spawn(self, run, *args):
        plan = json.loads((run / 'plan.json').read_text())
        n = len(self.workers)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('HERMES_', 'OPENAI_', 'ANTHROPIC_', 'STRATA_'))
               and k not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        out = (run / f'process-{n}.stdout.log').open('wb')
        err = (run / f'process-{n}.stderr.log').open('wb')
        mode = args[0] if args and args[0] == 'reconcile' else 'worker'
        if mode == 'reconcile': args = args[1:]
        process = subprocess.Popen([plan['base_python'], '-I', '-B', str(HERE / 'run_recovery.py'), mode,
                   '--run', str(run), *args], stdout=out, stderr=err, cwd=run / 'work', env=env,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.workers.append((process, out, err))
        return process

    def wait_pause(self, run, process, boundary):
        until = time.monotonic() + 60
        while time.monotonic() < until and process.poll() is None:
            if (run / 'pause.json').exists():
                value = json.loads((run / 'pause.json').read_text())
                self.assertEqual(value['pid'], process.pid)  # base executable, not venv shim
                self.assertEqual(value['boundary'], boundary)
                return value
            time.sleep(.05)
        self.fail('Worker did not reach the intended pause; inspect retained private logs')

    def finish(self, run, process, expected=0):
        self.assertEqual(process.wait(timeout=60), expected)
        return json.loads((run / f'result-{process.pid}.json').read_text())

    def kill(self, process):
        process.kill()
        process.wait(timeout=10)
        self.assertIsNotNone(process.poll())

    def effect_count(self, run):
        return len((run / 'effect-receipts.jsonl').read_text().splitlines())

    def test_01_safe_restart_preserves_original_and_no_duplicate_write(self):
        run = self.prepare('safe')
        first = self.spawn(run, '--pause', 'safe_after_write')
        marker = self.wait_pause(run, first, 'safe_after_write')
        from adaptive_inference.task_store import TaskStore
        before = TaskStore(run / 'task.sqlite3').load('orders-report')
        self.assertEqual(before.state['phase'], 'ready')
        self.assertIsNone(before.operation)
        self.assertEqual(self.effect_count(run), 1)
        self.assertEqual(len(json.loads((run / 'wire-observations.json').read_text())), 2)
        contender = self.spawn(run)
        denied = self.finish(run, contender, 2)
        self.assertEqual(denied['error_type'], 'TaskBusyError')
        self.kill(first)
        resumed = self.spawn(run)
        result = self.finish(run, resumed)
        self.assertTrue(result['passed']); self.assertTrue(result['resumed'])
        self.assertEqual(result['provider_calls'], 1)
        self.assertEqual(result['report']['units'], 17)
        self.assertEqual(result['report']['total_cents'], 4350)
        self.assertEqual(self.effect_count(run), 1)
        after = TaskStore(run / 'task.sqlite3').load('orders-report')
        self.assertEqual(after.prompt, before.prompt)
        self.assertEqual(after.state['messages'][0], {'role':'user', 'content': before.prompt})
        self.assertEqual(after.state['native_history'][:len(before.state['native_history'])], before.state['native_history'])
        self.assertEqual(after.state['status'], 'accepted')
        last = self.spawn(run)
        self.assertTrue(self.finish(run, last)['terminal_noop'])
        self.assertEqual(self.effect_count(run), 1)
        # A terminal ledger is not proof that an externally edited artifact is intact.
        (run / 'work/report.json').write_text('{}', encoding='utf-8')
        changed = self.spawn(run)
        refused = self.finish(run, changed, 2)
        self.assertEqual(refused['error_type'], 'ReconciliationRequired')
        self.assertEqual(refused['provider_calls'], 0)

    def test_02_uncertain_effect_blocks_then_explicit_reconciliation(self):
        run = self.prepare('uncertain')
        first = self.spawn(run, '--pause', 'uncertain_after_write')
        self.wait_pause(run, first, 'uncertain_after_write')
        self.kill(first)
        for _ in range(2):
            resumed = self.spawn(run)
            rejected = self.finish(run, resumed, 2)
            self.assertEqual(rejected['error_type'], 'ReconciliationRequired')
            self.assertEqual(self.effect_count(run), 1)
            self.assertEqual(len(json.loads((run / 'wire-observations.json').read_text())), 2)
        receipt = json.loads((run / 'effect-receipts.jsonl').read_text().splitlines()[0])
        receipt_file = run / 'explicit-observed-receipt.json'
        receipt_file.write_text(json.dumps(receipt), encoding='utf-8')
        wrong = self.spawn(run, 'reconcile', '--receipt', str(receipt_file), '--operation-id', 'not-this-operation')
        self.assertEqual(self.finish(run, wrong, 2)['error_type'], 'ReconciliationRequired')
        proc = self.spawn(run, 'reconcile', '--receipt', str(receipt_file), '--operation-id', receipt['operation_id'])
        self.assertTrue(self.finish(run, proc)['reconciled'])
        resumed = self.spawn(run)
        self.assertTrue(self.finish(run, resumed)['passed'])
        self.assertEqual(self.effect_count(run), 1)

    def test_03_real_middleware_baseexception_does_not_fail_open(self):
        import recovery
        from hermes_cli.middleware import run_llm_execution_middleware
        calls = []
        controller = recovery.Recovery(types.SimpleNamespace(checkpoint=None), None, HERE, HERE)
        controller.fatal = 'storage admission failed'
        manager = types.SimpleNamespace(_middleware={'llm_execution':[controller.llm]},
                                        _report_hook_failure=lambda *a, **k: self.fail('Fail-open reporter reached'))
        with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            with self.assertRaises(recovery.RecoveryStop):
                run_llm_execution_middleware({}, lambda request: calls.append(request), session_id='test')
        self.assertEqual(calls, [])

    def test_04_real_middleware_tool_failure_shortcircuits(self):
        import recovery
        from hermes_cli.middleware import run_tool_execution_middleware
        calls = []
        controller = recovery.Recovery(types.SimpleNamespace(checkpoint=None), None, HERE, HERE)
        manager = types.SimpleNamespace(_middleware={'tool_execution':[controller.tool]},
                                        _report_hook_failure=lambda *a, **k: self.fail('Fail-open reporter reached'))
        with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            result = run_tool_execution_middleware('write_file', {'path':'report.json','content':'x'},
                                                   lambda args: calls.append(args), session_id='test', tool_call_id='call')
        self.assertTrue(json.loads(result)['recovery_required'])
        self.assertEqual(calls, [])

    def test_05_interrupt_notification_failure_still_cannot_dispatch(self):
        import recovery
        from hermes_cli.middleware import run_tool_execution_middleware
        calls = []
        controller = recovery.Recovery(types.SimpleNamespace(checkpoint=None), None, HERE, HERE)
        def broken_interrupt(**_):
            raise RuntimeError('advisory interrupt failed')
        controller.agent = types.SimpleNamespace(interrupt=broken_interrupt)
        manager = types.SimpleNamespace(_middleware={'tool_execution':[controller.tool]},
                                        _report_hook_failure=lambda *a, **k: self.fail('Fail-open reporter reached'))
        with patch('hermes_cli.plugins._delivery_manager', return_value=manager):
            result = run_tool_execution_middleware('write_file', {'path':'report.json','content':'x'},
                                                   lambda args: calls.append(args), session_id='test', tool_call_id='call')
        self.assertTrue(json.loads(result)['recovery_required'])
        self.assertIsNotNone(controller.fatal)
        self.assertEqual(calls, [])

    def test_06_changed_pin_refused_before_importing_consumer(self):
        import run_recovery
        run = ARGS.output / 'pin-order'; run.mkdir()
        changed = run / 'changed-consumer.py'; changed.write_text('raise AssertionError("must not execute")')
        plan = {'sdk_revision':run_recovery.SDK_REV, 'model':run_recovery.MODEL,
                'quality':run_recovery.QUALITY, 'fixture':True, 'max_requests':8,
                'task_id':'orders-report', 'pins':{str(changed):'0'*64}}
        (run / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
        with patch.object(run_recovery, 'setup') as imported:
            with self.assertRaisesRegex(RuntimeError, 'before import'):
                run_recovery.worker(types.SimpleNamespace(run=run))
        imported.assert_not_called()

    @classmethod
    def tearDownClass(cls):
        for process, out, err in cls.workers:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
            out.close(); err.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--canonical', type=Path, required=True)
    p.add_argument('--hermes-source', type=Path, required=True)
    p.add_argument('--python', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    ARGS = p.parse_args()
    ARGS.output.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(HERE), str(ARGS.canonical / 'src'), str(ARGS.hermes_source)]
    # Importing SDK modules in the test parent must never touch the ordinary profile.
    os.environ.update(HERMES_HOME=str(ARGS.output / 'test-parent-home'),
                      HERMES_BUNDLED_PLUGINS=str(ARGS.output / 'empty-bundled'))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RestartTests)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    import recovery
    recovery.save(ARGS.output / 'result.json', {'passed':result.wasSuccessful(), 'tests':result.testsRun,
         'failures':len(result.failures), 'errors':len(result.errors), 'elapsed_s':time.monotonic()-started,
         'fixture':True, 'model_started':False, 'workers':len(RestartTests.workers),
         'all_retained_workers_exited':all(p.poll() is not None for p,_,_ in RestartTests.workers),
         'source_sha256':{name:recovery.digest((HERE/name).read_bytes()) for name in
                          ('recovery.py','run_recovery.py','test_recovery.py')}})
    raise SystemExit(0 if result.wasSuccessful() else 1)
