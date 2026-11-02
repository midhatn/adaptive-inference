"""Real task/native SQLite and inert compiler artifacts; no SDK or compiler execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from adaptive_inference.desktop.hermes import recovery as rec
from adaptive_inference.desktop.hermes.compiler_recovery import CompilerRecovery, TOOL_NAME
from adaptive_inference.desktop.compiler_recipe import Executable
from adaptive_inference.desktop.compiler_template import CompilerSettings, prepare_cpp_recipe, TEST_NAME
from adaptive_inference.task_spec import TaskSpec, digest
from adaptive_inference.task_store import TaskStore, ReconciliationRequired
from adaptive_inference.execution_clock import CLOCK_ID
from adaptive_inference.desktop.execution_budget import BUDGET, create_budget, tighten_budget, reopen_budget
from test_compiler_task_spec import compiler_data
from test_desktop_report_feedback import NativeDB


class CompilerRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name).resolve(); self.work = self.run/'work'; self.work.mkdir()
        (self.run/'compiler').mkdir()
        self.db = NativeDB(self.run/'native.sqlite3'); self.addCleanup(self.db.close)
        self.store = TaskStore(self.run/'task.sqlite3')
        self.spec = TaskSpec(compiler_data(max_runs=3))
        self.db.append({'role': 'user', 'content': self.spec.prompt})
        state = rec.initial_state(self.spec.prompt, 'session')
        state['deadline_monotonic'] = 900.0
        state['deadline_clock'] = CLOCK_ID
        state['native_history'] = rec.native_history(self.db, 'session')
        cp = self.store.create('task', self.spec.prompt, max_attempts=8,
            metadata={**self.spec.metadata(), 'pre_effect_validator': self.spec.validator_identity()}, state=state)
        self.context = self.store.claim(cp.task_id, expected_revision=cp.revision)
        self.owned = self.context.__enter__(); self.addCleanup(self.release)
        tools = []
        for name in ('cmake', 'ctest', 'clang-cl', 'ninja', 'lld-link'):
            path = self.run/(name+'.exe'); path.write_bytes(b'inert file '+name.encode())
            tools.append(Executable(path, digest(path.read_bytes())))
        self.settings = CompilerSettings(*tools, environment=())
        self.calls, self.recipes, self.polls = [], [], []
        self.status = 'passed'; self.serial = 0
        self.controller = CompilerRecovery(self.owned, self.db, self.work, self.run,
            controls=SimpleNamespace(poll=lambda owned: self.polls.append(owned.checkpoint.revision)),
            compiler_client=self.client, host_epoch='host-1', task_id='task', execution_id='task')

    def release(self):
        if self.context is not None:
            self.context.__exit__(None, None, None)
            self.context = None

    def client(self, request):
        # Observe actual durable intent before constructing fixture artifacts.
        cp = self.store.load('task')
        self.assertEqual(cp.operation['id'], request['operation_id'])
        self.assertEqual(cp.operation['kind'], 'effect')
        self.assertEqual(cp.state['phase'], 'tool_running')
        self.assertEqual(cp.operation['details']['tool_call_id'], request['tool_call_id'])
        self.assertEqual(request['owner_epoch'], cp.owner_epoch)
        self.assertEqual(set(request), {'schema', 'host_epoch', 'task_id', 'execution_id',
                                       'owner_epoch', 'operation_id', 'tool_call_id', 'recipe_id'})
        self.calls.append(deepcopy(request))
        result = {'schema': 'compiler-operation-result.v1', 'operation_id': request['operation_id'],
                  'recipe_id': request['recipe_id'], 'recipe_sha256': 'a'*64, 'task_deadline': 900.0,
                  'status': self.status, 'passed': self.status == 'passed', 'dispatched': True,
                  'owned_processes_exited': True}
        if self.status == 'outcome_unknown':
            return {**result, 'dispatched': None, 'owned_processes_exited': False}
        if self.status == 'preparation_failed':
            return {**result, 'dispatched': False}
        recipe = prepare_cpp_recipe(self.settings, spec=self.spec, args=cp.operation['details']['args'],
                                    operation_id=request['operation_id'], root=self.run/'compiler')
        self.recipes.append(recipe)
        recipe.run.mkdir()
        (recipe.run/'receipt.json').write_bytes(b'{"inert_fixture":true}')
        result['receipt_sha256'] = digest((recipe.run/'receipt.json').read_bytes())
        if self.status == 'passed':
            recipe.build.mkdir()
            (recipe.build/'program.exe').write_bytes(b'inert compiled artifact')
            (recipe.build/'program.stdout').write_bytes(self.spec.compiler['expected_stdout'].encode('utf-8'))
            (recipe.build/'program.exit').write_bytes(b'0')
            (recipe.run/'tests.xml').write_bytes(b'<testsuite name="fixture"/>')
            result.update(artifact_sha256=digest((recipe.build/'program.exe').read_bytes()),
                          test_report_sha256=digest((recipe.run/'tests.xml').read_bytes()), tests_passed=[TEST_NAME])
        else:
            result['diagnostics'] = [{'stage': 'build', 'text': 'error: missing semicolon', 'truncated': False}]
        return result

    def intent(self, args=None, *, name=TOOL_NAME):
        self.serial += 1
        call = f'call-{self.serial}'
        args = args or {'recipe_id': 'cpp17-stdout.v1', 'source': 'int main() { return 0; }'}
        self.db.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': call, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]})
        return call, args

    def dispatch(self, call, args, next_call=None):
        if next_call is None:
            next_call = lambda actual: self.controller._handle_compiler(actual, task_id='task', session_id='session')
        return self.controller.tool(TOOL_NAME, args, next_call, session_id='session', tool_call_id=call)

    def flush(self, call, result):
        self.db.append({'role': 'tool', 'tool_call_id': call, 'content': result})
        self.controller.control_safe_point()

    def test_denied_authorization_never_starts_effect_or_calls_host(self):
        call, args = self.intent()
        denied = json.dumps({'error': 'permission denied'})
        result = self.dispatch(call, args, lambda actual: denied)
        self.assertEqual(result, denied)
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.controller.compiler_receipts(), [])
        self.assertFalse((self.run/'effect-receipts.jsonl').exists())
        self.flush(call, result)
        self.assertIsNone(self.controller.fatal)

    def test_failed_source_feedback_then_corrected_source_continues_same_task(self):
        self.status = 'failed'
        first, args = self.intent({'recipe_id': 'cpp17-stdout.v1', 'source': 'int main() { bad; }'})
        failed = self.dispatch(first, args)
        self.assertIn('missing semicolon', failed)
        self.assertIsNone(self.controller.fatal)
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertEqual(self.owned.checkpoint.state['phase'], 'awaiting_native_flush')
        with self.assertRaises(ReconciliationRequired): rec.resumable(self.owned, self.db, self.work)
        self.flush(first, failed)
        seen = []
        def provider(request, **callbacks):
            seen.append(deepcopy(request))
            operation = callbacks['begin']('fixture-attempt')
            callbacks['completed'](operation)
            return 'fixture response'
        self.controller.provider = SimpleNamespace(execute=provider)
        self.controller.llm({'messages': rec.native_history(self.db, 'session')}, None, session_id='session')
        self.assertIn(failed, [row.get('content') for row in seen[0]['messages']])
        self.status = 'passed'
        second, corrected = self.intent()
        passed = self.dispatch(second, corrected); self.flush(second, passed)
        self.assertEqual(len(self.calls), 2)
        self.assertNotEqual(self.calls[0]['operation_id'], self.calls[1]['operation_id'])
        self.assertEqual((self.recipes[0].source/'program.cpp').read_text(), args['source'])
        receipts = self.controller.compiler_receipts()
        self.assertEqual([row['status'] for row in receipts], ['failed', 'passed'])
        self.assertEqual(self.spec.compiler_completion(receipts)['attempts'], 2)
        self.db.append({'role': 'assistant', 'content': 'Compiled and checked.'})
        self.controller.finish({'completed': True, 'failed': False, 'interrupted': False,
                                'final_response': 'Compiled and checked.'})
        self.assertEqual(self.owned.checkpoint.state['status'], 'accepted')
        self.assertEqual(self.owned.checkpoint.prompt, self.spec.prompt)
        self.assertEqual(self.owned.checkpoint.state['deadline_monotonic'], 900.0)
        self.assertEqual((self.owned.checkpoint.state['requests'], self.owned.checkpoint.state['attempts']), (1, 1))
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()), 2)

    def test_changed_authorized_args_refuse_before_effect(self):
        call, args = self.intent()
        result = self.dispatch(call, args, lambda actual: self.controller._handle_compiler(
            {**actual, 'source': 'changed'}, task_id='task', session_id='session'))
        self.assertIn('recovery_required', result)
        self.assertIsNotNone(self.controller.fatal)
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertEqual(self.calls, [])

    def test_completed_native_call_cannot_start_a_second_compiler_effect(self):
        call, args = self.intent()
        result = self.dispatch(call, args); self.flush(call, result)
        before = deepcopy(self.owned.checkpoint.state['tools'])
        refused = self.dispatch(call, args)
        self.assertIn('recovery_required', refused)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.owned.checkpoint.operation)
        self.assertEqual(self.owned.checkpoint.state['tools'], before)
        self.assertEqual(len((self.run/'effect-receipts.jsonl').read_text().splitlines()), 1)

    def test_completed_compiler_receipt_survives_rebased_boot_deadline_without_rewrite(self):
        state = self.controller.state()
        state[BUDGET] = create_budget(boot_id='a'*64, deadline=900.0,
            observation={'utc_ns': 1_000_000_000_000, 'qpc_before': 0.0, 'qpc_after': 0.0})
        self.controller.checkpoint(state)
        call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        original = deepcopy(self.owned.checkpoint.state['tools'])
        original_log = (self.run/'effect-receipts.jsonl').read_bytes()
        state = self.controller.state()
        stopped = tighten_budget(state[BUDGET], boot_id='a'*64,
            observation={'utc_ns': 1_010_000_000_000, 'qpc_before': 10.0, 'qpc_after': 10.0})
        state[BUDGET] = reopen_budget(stopped, boot_id='b'*64,
            observation={'utc_ns': 1_020_000_000_000, 'qpc_before': 2.0, 'qpc_after': 2.0})
        state['deadline_monotonic'] = state[BUDGET]['episode']['deadline']
        self.assertNotEqual(state['deadline_monotonic'], 900.0)
        self.controller.checkpoint(state)
        reopened = CompilerRecovery(self.owned, self.db, self.work, self.run,
            controls=self.controller.controls, compiler_client=self.client,
            host_epoch='host-2', task_id='task', execution_id='task')
        self.assertEqual(len(reopened.compiler_receipts()), 1)
        reopened.control_safe_point()
        self.assertEqual(self.owned.checkpoint.state['tools'], original)
        self.assertEqual((self.run/'effect-receipts.jsonl').read_bytes(), original_log)
        self.assertEqual(len(self.calls), 1)

    def test_missing_compiler_origin_is_not_an_invented_historical_allowance(self):
        call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        state = self.controller.state()
        state['tools'][0]['execution_id'] = 'missing-execution'
        self.controller.checkpoint(state)
        with self.assertRaises(ReconciliationRequired):
            self.controller.compiler_receipts()

    def test_changed_historical_compiler_result_is_refused(self):
        call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        state = self.controller.state()
        changed = json.loads(state['tools'][0]['result'])
        changed['task_deadline'] = 850.0
        state['tools'][0]['result'] = json.dumps(changed, sort_keys=True)
        self.controller.checkpoint(state)
        with self.assertRaises(ReconciliationRequired):
            self.controller.compiler_receipts()

    def test_current_compiler_result_still_requires_current_exact_deadline(self):
        original_client = self.controller.compiler_client
        def changed_deadline(request):
            return {**original_client(request), 'task_deadline': 850.0}
        self.controller.compiler_client = changed_deadline
        call, args = self.intent(); result = self.dispatch(call, args)
        self.assertIn('recovery_required', result)
        self.assertIsNotNone(self.owned.checkpoint.operation)
        self.assertEqual(self.owned.checkpoint.state['tools'], [])
        self.assertEqual(len(self.calls), 1)

    def test_verified_continue_inherits_receipt_origin_without_new_provider_call(self):
        # Real storage authorization, injected compiler client and zero provider
        # rows. This does not qualify the SDK compiler wire/toolset integration.
        from adaptive_inference.control_mailbox import Mailbox, EXECUTION_OUTCOME
        from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration
        from adaptive_inference.desktop.hermes.control_bridge import prepare_task
        from adaptive_inference.desktop.hermes.continuation import ContinuationAuthority
        stamp = '2026-11-02T00:00:00Z'
        self.store = TaskStore(self.run/'continued-task.sqlite3')
        identity = DemandIdentity('initial', 'task', 'host', stamp)
        metadata = {**self.spec.metadata(), 'pre_effect_validator': self.spec.validator_identity(),
                    'deadline_clock': CLOCK_ID, 'sdk_revision': 'fixture',
                    'model': 'iq3_s-fixture', 'quality': {'max_tokens': 10923}}
        cp = prepare_task(self.store, identity, self.spec.prompt, 'session', metadata=metadata)
        registry = DemandRegistry((Registration(self.store, identity),))
        capability = object(); mailbox = Mailbox(registry, 'initial', requester_capability=capability)
        controls = self.controller.controls
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as owned:
            self.owned = owned
            state = deepcopy(owned.checkpoint.state)
            state.update(deadline_monotonic=900.0, native_history=rec.native_history(self.db, 'session'))
            owned.save_checkpoint(state, expected_revision=owned.checkpoint.revision)
            self.controller = CompilerRecovery(owned, self.db, self.work, self.run, controls=controls,
                compiler_client=self.client, host_epoch='host-1', task_id='task', execution_id='task')
            call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
            original = deepcopy(owned.checkpoint.state['tools'])
            mailbox.submit(capability, 'pause-origin', 'pause'); mailbox.consume(owned, updated_at_utc=stamp)
            mailbox.seal_paused_execution(owned, deadline_monotonic=900.0, pause_observed_at_monotonic=899.0,
                observed_pause=mailbox.paused_execution_observation(owned),
                sealed_at_monotonic=1000.0, deadline_clock=CLOCK_ID)
        before = self.store.history('task')
        (self.run/'wire-observations.json').write_text('[]', encoding='utf-8')
        scope = {'plan_sha256': digest(b'fixed-plan'), 'session_id': 'session',
                 'native_db': str(self.run/'native.sqlite3'), 'work_dir': str(self.work),
                 'effect_receipts': str(self.run/'effect-receipts.jsonl'),
                 'wire_observations': str(self.run/'wire-observations.json'), 'gateway': 'http://127.0.0.1:1/v1'}
        authority = ContinuationAuthority(self.store, 'task', scope, host_generation='host-2', clock=lambda: 1100.0)
        old = self.store.load('task')
        payload = authority.request(command_id='continue-1', predecessor_id='task',
            predecessor_revision=old.revision, predecessor_seal_sha256=rec.digest(old.state[EXECUTION_OUTCOME]),
            successor_id='task.run-1', identity=DemandIdentity('next', 'task.run-1', 'host', stamp),
            host_generation='host-2', release_evidence_sha256=digest(b'synthetic-release-only'))
        cp = self.store.load(authority.task_id)
        with self.store.claim(cp.task_id, expected_revision=cp.revision) as authorizer:
            grant = authority.authorize(authorizer, payload)
        with authority.claim_selected(grant, host_generation='host-2') as (_, selected):
            resumed = CompilerRecovery(selected, self.db, self.work, self.run, controls=controls,
                compiler_client=self.client, host_epoch='host-2', task_id='task', execution_id='task.run-1')
            self.assertEqual(len(resumed.compiler_receipts()), 1)
            self.assertEqual(selected.checkpoint.state['tools'], original)
            self.assertEqual(selected.checkpoint.state['deadline_monotonic'], 2000.0)
        self.assertEqual(self.store.history('task'), before)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_outcome_keeps_original_intent_and_never_replays(self):
        self.status = 'outcome_unknown'
        call, args = self.intent()
        result = self.dispatch(call, args)
        original = deepcopy(self.owned.checkpoint.operation)
        self.assertIsNotNone(original)
        self.assertIn('recovery_required', result)
        self.assertEqual(self.owned.checkpoint.state['tools'], [])
        self.dispatch(call, args)
        self.assertEqual(self.owned.checkpoint.operation, original)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(ReconciliationRequired): rec.resumable(self.owned, self.db, self.work)

    def test_known_preparation_failure_has_feedback_but_no_fictitious_artifacts(self):
        self.status = 'preparation_failed'
        call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        self.assertIsNone(self.controller.fatal)
        self.assertEqual(self.controller.compiler_receipts()[0]['status'], 'preparation_failed')
        self.assertEqual(list((self.run/'compiler').iterdir()), [])
        self.assertFalse(self.spec.compiler_completion(self.controller.compiler_receipts())['qualified'])

    def test_tampered_artifact_blocks_next_safe_acknowledgement(self):
        call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        before = len(self.polls)
        (self.recipes[0].build/'program.stdout').write_bytes(b'wrong result')
        with self.assertRaises(ValueError): self.controller.control_safe_point()
        self.assertEqual(len(self.polls), before)

    def test_registration_uses_public_synchronous_exact_capability_and_unbound_handler_refuses(self):
        registered = []
        self.controller.register_tool(SimpleNamespace(register_tool=lambda **entry: registered.append(entry)))
        entry = registered[0]
        self.assertEqual(entry['name'], TOOL_NAME)
        self.assertIs(entry['is_async'], False)
        self.assertIs(entry['override'], False)
        self.assertEqual(entry['schema']['parameters']['required'], ['recipe_id', 'source'])
        self.assertIs(entry['schema']['parameters']['additionalProperties'], False)
        result = entry['handler']({'recipe_id': 'cpp17-stdout.v1', 'source': 'code'}, task_id='task', session_id='session')
        self.assertIn('recovery_required', result)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.owned.checkpoint.operation)

    def test_wrong_native_identity_and_exhausted_allowance_do_not_start_another_operation(self):
        self.status = 'preparation_failed'
        for _ in range(3):
            call, args = self.intent(); result = self.dispatch(call, args); self.flush(call, result)
        call, args = self.intent(); result = self.dispatch(call, args)
        self.assertIn('compiler_proposal_rejected', result)
        self.assertEqual(len(self.calls), 3)
        self.assertIsNone(self.controller.fatal)
        bad = self.controller.tool(TOOL_NAME, args, lambda _: self.fail('dispatched'),
                                   session_id='other-session', tool_call_id=call)
        self.assertIn('recovery_required', bad)
        self.assertIsNone(self.owned.checkpoint.operation)
