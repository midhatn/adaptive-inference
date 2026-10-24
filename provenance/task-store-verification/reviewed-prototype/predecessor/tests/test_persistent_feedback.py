"""Durable generation/validation boundaries; callbacks are deterministic fixtures."""
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest

from adaptive_inference.feedback import Verdict, resume_with_feedback
from adaptive_inference.task_store import ReconciliationRequired, TaskBusyError, TaskStore


IDENTITY = {'generator': 'fixture-v1', 'validator': 'exact-answer-v1'}


class Pause(Exception):
    pass


class PersistentFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'tasks.sqlite3'
        self.store = TaskStore(self.path)
        self.store.create('task', 'Original objective', max_attempts=2, metadata=IDENTITY)

    async def run_task(self, generate, validate, **kwargs):
        return await resume_with_feedback(self.store, 'task', generate, validate,
                                           identity=IDENTITY, **kwargs)

    async def test_saved_output_resumes_validation_without_generating_again(self):
        def pause(checkpoint):
            if checkpoint.state.get('phase') == 'awaiting_validation':
                raise Pause()
        with self.assertRaises(Pause):
            await self.run_task(lambda messages: 'correct', lambda output: self.fail('early validation'),
                                on_checkpoint=pause)
        self.store = TaskStore(self.path)
        result = await self.run_task(lambda messages: self.fail('generation replayed'),
                                    lambda output: Verdict(output == 'correct'))
        self.assertTrue(result.accepted)
        self.assertEqual(result.attempts, 1)

    async def test_rejected_feedback_and_original_task_survive_reopen(self):
        def pause(checkpoint):
            if checkpoint.state.get('phase') == 'ready' and checkpoint.state['feedback']:
                raise Pause()
        with self.assertRaises(Pause):
            await self.run_task(lambda messages: 'wrong', lambda output: Verdict(False, 'use exact answer'),
                                on_checkpoint=pause)
        self.store = TaskStore(self.path)
        def corrected(messages):
            self.assertEqual(messages[0], {'role': 'user', 'content': 'Original objective'})
            self.assertEqual(messages[1], {'role': 'assistant', 'content': 'wrong'})
            self.assertIn('use exact answer', messages[2]['content'])
            return 'correct'
        result = await self.run_task(corrected, lambda output: Verdict(output == 'correct'))
        self.assertTrue(result.accepted)
        self.assertEqual(result.feedback, ('use exact answer',))
        self.assertEqual(result.attempts, 2)
        terminal = await self.run_task(lambda _: self.fail('terminal generate'), lambda _: self.fail('terminal validate'))
        self.assertEqual(terminal, result)

    async def test_unknown_generation_requires_explicit_retry_and_consumes_attempt(self):
        def interrupted(messages):
            raise Pause()
        with self.assertRaises(Pause):
            await self.run_task(interrupted, lambda _: Verdict(True))
        with self.assertRaises(ReconciliationRequired):
            await self.run_task(lambda _: self.fail('implicit retry'), lambda _: Verdict(True))
        result = await self.run_task(lambda _: 'known pure generation', lambda _: Verdict(True),
                                    retry_interrupted_generation=True)
        self.assertTrue(result.accepted)
        self.assertEqual(result.attempts, 2)
        self.assertIn('generation_retry_authorized', [r['event'] for r in self.store.history('task')])

    async def test_validation_needs_reconciliation_even_with_generation_retry_opt_in(self):
        def interrupted(output):
            raise Pause()
        with self.assertRaises(Pause):
            await self.run_task(lambda _: 'saved output', interrupted)
        with self.assertRaises(ReconciliationRequired):
            await self.run_task(lambda _: self.fail('replay'), lambda _: self.fail('replay'),
                                retry_interrupted_generation=True)
        snapshot = self.store.load('task')
        with self.store.claim('task', expected_revision=snapshot.revision) as owned:
            checkpoint = owned.checkpoint
            state = copy.deepcopy(checkpoint.state)
            state['phase'] = 'awaiting_validation'
            owned.reconcile_operation(checkpoint.operation['id'], resolution='not_performed',
                    result={'evidence': 'Fixture validation performed no action or acceptance check before interruption'},
                    state=state, expected_revision=checkpoint.revision)
        result = await self.run_task(lambda _: self.fail('saved generation repeated'),
                                    lambda text: Verdict(text == 'saved output'))
        self.assertTrue(result.accepted)
        self.assertEqual(result.attempts, 1)

    async def test_changed_identity_refuses_without_mutating_task(self):
        before = self.store.load('task')
        with self.assertRaises(ValueError):
            await resume_with_feedback(self.store, 'task', lambda _: self.fail('dispatched'),
                    lambda _: Verdict(True), identity={**IDENTITY, 'validator': 'changed'})
        self.assertEqual(self.store.load('task'), before)

    async def test_exhaustion_is_durable_and_observer_cannot_mutate_working_state(self):
        def observer(checkpoint):
            checkpoint.state['messages'].clear()
            checkpoint.state['feedback'].clear()
        result = await self.run_task(lambda messages: messages[0]['content'],
                                    lambda _: Verdict(False, 'still rejected'), on_checkpoint=observer)
        self.assertFalse(result.accepted)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.feedback, ('still rejected', 'still rejected'))
        self.assertEqual(self.store.load('task').state['status'], 'exhausted')
        again = await self.run_task(lambda _: self.fail('exhausted generate'), lambda _: self.fail('exhausted validate'))
        self.assertEqual(result, again)

    async def test_two_live_runners_cannot_generate_for_same_task(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def held(messages):
            entered.set()
            await release.wait()
            return 'correct'
        first = asyncio.create_task(self.run_task(held, lambda _: Verdict(True)))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.assertRaises(TaskBusyError):
                await self.run_task(lambda _: self.fail('second runner'), lambda _: Verdict(True))
        finally:
            release.set()
        self.assertTrue((await asyncio.wait_for(first, 5)).accepted)
