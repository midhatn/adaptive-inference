"""Runtime partitions: actual aiohttp/Scheduler with CPU-only fake backends."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

from aiohttp import ClientConnectorError, web
from aiohttp.test_utils import TestClient, TestServer
from multidict import CIMultiDict

from adaptive_inference.config import Config
from adaptive_inference.costs import RequestCostModel
from adaptive_inference.gateway import (GATEWAY, Gateway, RuntimeTimingContext,
    RuntimeTimingError, cost_key, create_app)
from adaptive_inference.demand import DemandIdentity, DemandRegistry, Registration, NAMESPACE
from adaptive_inference.handoff import ForegroundPolicy, HandoffController, ToolRequirements
from adaptive_inference.task_store import TaskStore
from test_handoff import Adapter, sample


BODY = {"model": "cpu-fixture-only", "messages": [{"role": "user", "content": "unchanged"}],
        "temperature": .7, "max_tokens": 123, "seed": 9}
COMPLETE = {"choices": [{"index": 0, "message": {"content": "fixture"}, "finish_reason": "stop"}]}


def owner(name):
    return {"owner_id": name, "ready": True, "loaded": True}


def warm(learner, key, duration=2):
    for _ in range(3):
        learner.observe(key, duration, now=time.monotonic())


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.allowed = False
        self.seen = []
        self.reply_hook = None

        async def reply(request):
            self.seen.append(await request.json())
            if self.reply_hook is not None:
                return await self.reply_hook(request)
            return web.json_response(COMPLETE)

        app = web.Application()
        app.router.add_post('/v1/chat/completions', reply)
        self.backend = TestServer(app)
        await self.backend.start_server()
        config = Config(backend_url=str(self.backend.make_url('/v1')),
                        queue_timeout_s=2, upstream_timeout_s=2)
        self.app = create_app(config, capacity=lambda: self.allowed, runtime_timing=True)
        self.gateway = self.app[GATEWAY]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.key = cost_key(config, '/chat/completions', BODY, 'normal')

    async def asyncTearDown(self):
        await self.client.close()
        await self.backend.close()

    def activate(self, name='private-owner-A'):
        self.allowed = False
        self.gateway.activate_runtime(owner(name))
        self.allowed = True

    async def request(self, **kwargs):
        response = await self.client.post('/v1/chat/completions', json=BODY, **kwargs)
        await response.read()
        return response

    async def test_real_http_samples_reset_only_for_distinct_verified_owner(self):
        self.activate()
        for count in range(1, 4):
            self.assertEqual((await self.request()).status, 200)
            prediction, generation = self.gateway._prediction(self.key)
            self.assertEqual((prediction['samples'], generation), (count, 1))
            self.assertEqual(prediction['estimate_s'] is None, count < 3)
        first = self.gateway.costs
        self.allowed = False
        self.gateway.activate_runtime(owner('private-owner-A'))
        self.assertIs(first, self.gateway.costs)
        self.gateway.activate_runtime(owner('private-owner-B'))
        self.assertIsNot(first, self.gateway.costs)
        self.allowed = True
        self.assertEqual(self.gateway._prediction(self.key)[0]['reason'], 'cold')
        for count in range(1, 4):
            await self.request()
            prediction, generation = self.gateway._prediction(self.key)
            self.assertEqual((prediction['samples'], generation), (count, 2))
        self.assertEqual(self.seen, [BODY] * 6)

    async def test_unbound_unavailable_unknown_are_explicitly_cold(self):
        self.assertEqual(self.gateway._prediction(self.key)[0]['reason'], 'runtime_unbound')
        self.activate()
        warm(self.gateway.costs, self.key)
        self.assertIsNotNone(self.gateway._prediction(self.key)[0]['estimate_s'])
        self.allowed = False
        unavailable = self.gateway._prediction(self.key)[0]
        self.assertEqual((unavailable['reason'], unavailable['samples'], unavailable['estimate_s']),
                         ('runtime_unavailable', 0, None))
        self.allowed = True
        self.assertEqual(self.gateway._prediction(self.key)[0]['samples'], 3)
        self.gateway.scheduler.uncertain = True
        unknown = self.gateway._prediction(self.key)[0]
        self.assertEqual((unknown['reason'], unknown['samples'], unknown['estimate_s']),
                         ('runtime_unknown', 0, None))

    async def test_queued_rank_age_and_body_survive_owner_rotation(self):
        self.activate()
        original = self.gateway.costs
        warm(original, self.key)
        blocker = await self.gateway.scheduler.acquire('normal', None)
        request = asyncio.create_task(self.request())
        try:
            for _ in range(100):
                if self.gateway.scheduler.pending:
                    break
                await asyncio.sleep(.005)
            self.assertEqual(len(self.gateway.scheduler.pending), 1)
            queued = next(iter(self.gateway.scheduler.pending.values()))
            signature = (queued.sequence, queued.arrival, queued.rank)
            self.allowed = False
            await self.gateway.scheduler.release(blocker)
            self.gateway.activate_runtime(owner('private-owner-B'))
            self.assertIs(next(iter(self.gateway.scheduler.pending.values())), queued)
            await asyncio.sleep(.08)
            self.assertEqual((queued.sequence, queued.arrival, queued.rank), signature)
            observed = []

            async def reply(request):
                observed.append(self.gateway.scheduler.active)
                return web.json_response(COMPLETE)

            self.reply_hook = reply
            self.allowed = True
            response = await request
            self.assertEqual(response.status, 200)
            self.assertEqual(observed, [queued])
            self.assertEqual(self.seen, [BODY])
            row = self.gateway.history[-1]
            self.assertEqual((row['prediction_runtime_generation'], row['execution_runtime_generation']), (1, 2))
            self.assertFalse(row['prediction_matches_execution_runtime'])
            self.assertEqual(row['prediction']['samples'], 3)
            self.assertGreater(row['queue_s'], .07)
            self.assertEqual(original.predict(self.key, now=time.monotonic())['samples'], 3)
            self.assertEqual(self.gateway.costs.predict(self.key, now=time.monotonic())['samples'], 1)
            self.assertLess(row['execution_s'], row['queue_s'])
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
            if self.gateway.scheduler.active is blocker:
                await self.gateway.scheduler.release(blocker)

    async def test_delayed_old_success_and_invalid_response_touch_only_captured_learner(self):
        for complete in (True, False):
            with self.subTest(complete=complete):
                self.activate('owner-' + str(complete))
                first_context = self.gateway._runtime_context
                warm(first_context.learner, self.key)
                entered, finish = asyncio.Event(), asyncio.Event()

                async def reply(request):
                    entered.set()
                    await finish.wait()
                    return web.json_response(COMPLETE if complete else {'incomplete': True})

                self.reply_hook = reply
                request = asyncio.create_task(self.request())
                await asyncio.wait_for(entered.wait(), 1)
                second = RequestCostModel()
                warm(second, self.key, 7)
                second_before = second.status()
                # Deliberately bypass trusted activation (which rejects active
                # dispatch): adversarial completion-reference test only.
                injected = RuntimeTimingContext(first_context.generation + 1, b'fixture', second)
                self.gateway._runtime_context = injected
                self.gateway.costs = second
                finish.set()
                self.assertEqual((await request).status, 200)
                self.assertEqual(second.status(), second_before)
                self.assertEqual(first_context.learner.predict(self.key, now=time.monotonic())['samples'],
                                 4 if complete else 0)
                self.assertEqual(self.gateway.history[-1]['execution_runtime_generation'], first_context.generation)

    async def test_connector_and_timeout_failure_use_captured_learner(self):
        self.activate()
        for failure in (ClientConnectorError(None, OSError('fixture')), TimeoutError('fixture')):
            with self.subTest(failure=type(failure).__name__):
                context = self.gateway._runtime_context
                warm(context.learner, self.key)
                second = RequestCostModel()
                warm(second, self.key, 7)
                before = second.status()

                def fail(*args, **kwargs):
                    self.gateway._runtime_context = RuntimeTimingContext(context.generation + 1, b'injected', second)
                    self.gateway.costs = second
                    raise failure

                with patch.object(self.gateway.client, 'post', side_effect=fail):
                    response = await self.request()
                self.assertEqual(response.status, 502)
                self.assertEqual(context.learner.predict(self.key, now=time.monotonic())['samples'], 0)
                self.assertEqual(second.status(), before)
                self.assertEqual(self.gateway.history[-1]['execution_runtime_generation'], context.generation)
                self.assertEqual(self.gateway.scheduler.uncertain, isinstance(failure, TimeoutError))
        self.assertEqual(self.seen, [])

    async def test_partial_stream_invalidates_only_captured_runtime(self):
        self.activate()
        previous = self.gateway._runtime_context
        warm(previous.learner, self.key)
        replacement = RequestCostModel()
        warm(replacement, self.key, 7)
        before = replacement.status()

        async def partial(request):
            self.gateway._runtime_context = RuntimeTimingContext(previous.generation + 1, b'injected', replacement)
            self.gateway.costs = replacement
            return web.Response(text='data: {"choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n',
                                content_type='text/event-stream')

        self.reply_hook = partial
        response = await self.request()
        self.assertEqual(response.status, 200)
        self.assertEqual(previous.learner.predict(self.key, now=time.monotonic())['samples'], 0)
        self.assertEqual(replacement.status(), before)
        self.assertFalse(self.gateway.history[-1]['trained'])
        self.assertEqual(self.gateway.history[-1]['execution_runtime_generation'], previous.generation)

    async def test_unbound_after_admission_never_posts_trains_or_forges_deferred_proof(self):
        self.allowed = True  # Misconfigured host; guard is defensive, not retry.
        before = self.gateway.costs.status()
        response = await self.request(headers={'X-Adaptive-Admission': 'immediate',
                                              'X-Adaptive-Attempt-Id': 'fixture-unbound'})
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())['error']['code'], 'runtime_timing_unavailable')
        self.assertNotIn('X-Adaptive-Dispatch', response.headers)
        self.assertEqual(self.seen, [])
        self.assertIsNone(self.gateway.scheduler.active)
        self.assertFalse(self.gateway.scheduler.uncertain)
        self.assertEqual(self.gateway.costs.status(), before)
        self.assertEqual(self.gateway._runtime_error, 'runtime_execution_unbound')

    async def test_unknown_context_does_not_hide_exact_ticket_release_failure(self):
        self.allowed = True
        request = SimpleNamespace(match_info={'endpoint': 'chat/completions'}, query={},
            headers=CIMultiDict(), path='/v1/chat/completions',
            transport=SimpleNamespace(is_closing=lambda: False))

        async def read():
            return json.dumps(BODY).encode()

        request.read = read
        original_release = self.gateway.scheduler.release

        async def fail_release(ticket, *, uncertain=False):
            self.assertIs(ticket, self.gateway.scheduler.active)
            raise RuntimeError('exact release failure')

        with patch.object(self.gateway.scheduler, 'release', side_effect=fail_release):
            with self.assertRaisesRegex(RuntimeError, 'exact release failure'):
                await self.gateway.inference(request)
        self.assertIsNotNone(self.gateway.scheduler.active)
        self.assertFalse(self.seen)
        await original_release(self.gateway.scheduler.active)

    async def test_uncertainty_detected_after_admission_is_preserved_on_known_unstarted_release(self):
        self.activate()
        original = self.gateway.scheduler.acquire

        async def inject_uncertainty(*args, **kwargs):
            ticket = await original(*args, **kwargs)
            self.gateway.scheduler.uncertain = True
            return ticket

        with patch.object(self.gateway.scheduler, 'acquire', side_effect=inject_uncertainty):
            response = await self.request()
        self.assertEqual(response.status, 503)
        self.assertTrue(self.gateway.scheduler.uncertain)
        self.assertIsNone(self.gateway.scheduler.active)
        self.assertEqual(self.seen, [])
        self.assertFalse(self.gateway.history[-1]['trained'])

    async def test_immediate_deferral_is_original_scheduler_receipt(self):
        response = await self.request(headers={'X-Adaptive-Admission': 'immediate',
                                              'X-Adaptive-Attempt-Id': 'fixture-closed'})
        self.assertEqual(response.status, 503)
        body = await response.json()
        self.assertEqual(body['error']['code'], 'admission_deferred')
        self.assertIs(body['admission']['dispatched'], False)
        self.assertEqual(response.headers['X-Adaptive-Dispatch'], 'not-dispatched')
        self.assertFalse(self.seen)
        self.assertFalse(self.gateway.history)
        self.assertIsNone(self.gateway._runtime_error)

    async def test_activation_rejects_active_without_releasing_or_replacing_it(self):
        self.activate()
        context = self.gateway._runtime_context
        ticket = await self.gateway.scheduler.acquire('normal', None)
        self.allowed = False
        try:
            with self.assertRaisesRegex(RuntimeTimingError, 'runtime_dispatch_active'):
                self.gateway.activate_runtime(owner('B'))
            self.assertIs(self.gateway.scheduler.active, ticket)
            self.assertIs(self.gateway._runtime_context, context)
            self.assertEqual(self.gateway._runtime_error, 'runtime_dispatch_active')
        finally:
            await self.gateway.scheduler.release(ticket)

    async def test_activation_guards_and_wrong_loop_do_not_change_ownership(self):
        for condition in ('uncertain', 'closing', 'open', 'malformed', 'invalid_unicode'):
            with self.subTest(condition=condition):
                gate = Gateway(self.gateway.config, capacity=lambda: condition == 'open', runtime_timing=True)
                gate._runtime_loop = asyncio.get_running_loop()
                gate.scheduler.uncertain = condition == 'uncertain'
                gate.scheduler.closing = condition == 'closing'
                before = gate.scheduler.status()
                with self.assertRaises(RuntimeTimingError):
                    gate.activate_runtime({} if condition == 'malformed' else
                                          owner('\ud800' if condition == 'invalid_unicode' else 'A'))
                self.assertEqual(gate.scheduler.status(), before)
                self.assertIsNone(gate._runtime_context)
                self.assertIsNotNone(gate._runtime_error)
        with self.assertRaisesRegex(RuntimeTimingError, 'runtime_wrong_loop'):
            await asyncio.to_thread(self.gateway.activate_runtime, owner('A'))
        self.assertIsNone(self.gateway._runtime_error)
        self.assertIsNone(self.gateway._runtime_context)

    async def test_model_limits_history_and_status_are_bounded_and_private(self):
        self.gateway.costs = RequestCostModel(decay_s=4, ttl_s=8, min_samples=3, max_groups=2, max_samples=4)
        refs = []
        for number in range(30):
            self.activate('secret-owner-private-path-' + str(number))
            refs.append(weakref.ref(self.gateway.costs))
        self.assertEqual(sum(ref() is not None for ref in refs), 1)
        current = self.gateway.costs
        self.assertEqual((current.decay_s, current.ttl_s, current.min_samples,
                          current.max_groups, current.max_samples), (4, 8, 3, 2, 4))
        for number in range(140):
            self.gateway.history.append({'sequence': number})
        response = await self.client.get('/metrics')
        metrics = await response.json()
        self.assertEqual(len(metrics['history']), 128)
        self.assertEqual(metrics['runtime_timing']['generation'], 30)
        self.assertEqual(metrics['runtime_timing']['cost_model_scope'], 'current_verified_runtime')
        text = json.dumps(metrics)
        self.assertNotIn('secret-owner', text)
        self.assertNotIn('owner_digest', text)


class HostHookTests(unittest.IsolatedAsyncioTestCase):
    async def make_host(self, callback=None):
        adapter = Adapter()
        control = HandoffController(adapter, ForegroundPolicy(recovery_s=0, engage_samples=1),
                                    clock=time.perf_counter, on_verified_owner=callback)
        gateway = Gateway(Config(), capacity=control, runtime_timing=True)
        await gateway.startup(None)
        self.addAsyncCleanup(gateway.cleanup, None)
        control.bind_scheduler(gateway.scheduler)
        if callback is None:
            control.on_verified_owner = gateway.activate_runtime
        return adapter, control, gateway

    async def test_activation_occurs_before_eager_and_restored_ready(self):
        adapter, control, gateway = await self.make_host()
        observations = []

        def activate(identity):
            observations.append((control.state, control(), gateway.scheduler.active, identity['owner_id']))
            gateway.activate_runtime(identity)

        control.on_verified_owner = activate
        await control.initialize()
        self.assertEqual(gateway._runtime_context.generation, 1)
        control.observe(sample(time.perf_counter(), idle=0))
        await control.step()
        self.assertEqual(control.state, 'parked')
        control.observe(sample(time.perf_counter()))
        await control.step()
        self.assertEqual(control.state, 'ready')
        self.assertEqual(gateway._runtime_context.generation, 2)
        self.assertEqual(observations, [('uninitialized', False, None, 'first'),
                                        ('restoring', False, None, 'next')])
        self.assertIs(gateway.scheduler.capacity, control)

    async def test_activation_failure_retains_new_owner_and_latches_fault(self):
        adapter, control, gateway = await self.make_host()
        await control.initialize()
        control.observe(sample(time.perf_counter(), idle=0))
        await control.step()

        def broken(identity):
            raise RuntimeTimingError('fixture binding failed')

        control.on_verified_owner = broken
        control.observe(sample(time.perf_counter()))
        with self.assertRaises(RuntimeTimingError):
            await control.step()
        self.assertEqual(control.identity, owner('next'))
        self.assertEqual(control.fault, 'runtime_timing_activation_failed')
        self.assertEqual(control.state, 'fault')
        self.assertFalse(control())
        self.assertEqual(gateway._runtime_context.generation, 1)

    async def test_shutdown_during_restore_does_not_activate_or_open_admission(self):
        adapter, control, gateway = await self.make_host()
        await control.initialize()
        control.observe(sample(time.perf_counter(), idle=0))
        await control.step()

        async def close_during_start():
            await gateway.scheduler.close()
            return owner('new-retained-owner')

        adapter.on_start = close_during_start
        control.observe(sample(time.perf_counter()))
        await control.step()
        self.assertEqual(control.identity, owner('new-retained-owner'))
        self.assertEqual(gateway._runtime_context.generation, 1)
        self.assertFalse(control())
        self.assertIsNone(control.fault)

    async def test_wrong_callback_shape_faults_and_keeps_identity(self):
        async def async_callback(identity):
            pass

        with self.assertRaises(TypeError):
            HandoffController(Adapter(), on_verified_owner=async_callback)
        adapter, control, gateway = await self.make_host(lambda identity: async_callback(identity))
        with self.assertRaises(TypeError):
            await control.initialize()
        self.assertEqual(control.identity, owner('first'))
        self.assertEqual(control.fault, 'runtime_timing_activation_failed')
        self.assertFalse(control())

    async def test_disabled_gateway_preserves_status_and_history_shape(self):
        app = create_app(Config(), capacity=lambda: False)
        self.assertFalse(app[GATEWAY].runtime_timing)
        with self.assertRaisesRegex(RuntimeTimingError, 'disabled'):
            app[GATEWAY].activate_runtime(owner('A'))
        response = await app[GATEWAY].status(SimpleNamespace(path='/metrics'))
        self.assertNotIn('runtime_timing', json.loads(response.body))
        self.assertIsNone(app[GATEWAY]._runtime_error)


class DemandHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_no_activation_and_post_start_demand_refresh_precedes_binding(self):
        from test_handoff_demand import Adapter as DemandAdapter, Clock
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            identity = DemandIdentity('r1', 'task1', 'trusted-worker', '2026-10-24T12:00:00Z')
            store.create('task1', 'Keep original goal', max_attempts=3,
                         metadata={NAMESPACE: identity.metadata()})
            registry = DemandRegistry((Registration(store, identity),))
            with store.claim('task1', expected_revision=store.load('task1').revision) as owned:
                clock = Clock()
                adapter = DemandAdapter(clock)
                control = HandoffController(adapter, ForegroundPolicy(recovery_s=0, engage_samples=1),
                    clock=clock, demand=registry, restore_requirements=ToolRequirements(8, 10, 2000))
                gateway = Gateway(Config(), capacity=control, runtime_timing=True)
                await gateway.startup(None)
                try:
                    control.bind_scheduler(gateway.scheduler)
                    observed = []

                    def bind(runtime):
                        observed.append((control.state, control._demand_state(), control()))
                        gateway.activate_runtime(runtime)

                    control.on_verified_owner = bind
                    control.observe(sample(clock()))
                    await control.initialize(parked=True)
                    self.assertEqual(observed, [])
                    self.assertIsNone(gateway._runtime_context)
                    registry.transition('r1', owned, 'waiting', expected_revision=owned.checkpoint.revision,
                        updated_at_utc='2026-10-24T12:01:00Z', reason='fixture safe point')
                    await control.refresh_demand()

                    async def cancelled_during_start():
                        registry.transition('r1', owned, 'cancelled', expected_revision=owned.checkpoint.revision,
                            updated_at_utc='2026-10-24T12:02:00Z', reason='fixture safe point')
                        return owner('returned-owner')

                    adapter.on_start = cancelled_during_start
                    await control.step()
                    self.assertEqual(observed, [('restoring', 'absent', False)])
                    self.assertEqual(control.state, 'awaiting_demand')
                    self.assertFalse(control())
                    self.assertEqual(gateway._runtime_context.generation, 1)
                    self.assertEqual(gateway._prediction('fixture')[0]['reason'], 'runtime_unavailable')
                    self.assertEqual(control.identity, owner('returned-owner'))
                finally:
                    await gateway.cleanup(None)


if __name__ == '__main__':
    unittest.main()
