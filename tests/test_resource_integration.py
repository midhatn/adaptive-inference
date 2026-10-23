"""Dispatch ownership under simulated headroom; real loopback HTTP, no model."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from adaptive_inference.config import Config
from adaptive_inference.gateway import GATEWAY, Gateway, create_app
from adaptive_inference.resources import Capacity


class CapacityTests(unittest.TestCase):
    def test_disabled_floor_does_not_sample(self):
        with patch('adaptive_inference.resources.available_gib', side_effect=AssertionError('sampled')):
            capacity = Capacity(0)
            self.assertTrue(capacity())
            self.assertIsNone(capacity.policy)

    def test_existing_floor_recovers_immediately_when_adaptive_mode_is_off(self):
        with patch('adaptive_inference.resources.available_gib', side_effect=[3, 4]):
            capacity = Capacity(4)
            self.assertFalse(capacity())
            self.assertTrue(capacity())

    def test_sensor_failure_requires_new_recovery_observations(self):
        clock = [10.0]
        capacity = Capacity(4, adaptive=True, recovery_seconds=2)
        with patch('adaptive_inference.resources.time', SimpleNamespace(monotonic=lambda: clock[0])), \
             patch('adaptive_inference.resources.available_gib', side_effect=[6, OSError('sensor'), 6, 6, 6]):
            self.assertTrue(capacity())
            clock[0] = 11
            self.assertFalse(capacity())
            self.assertEqual(capacity.status()['error'], 'memory_observation_unavailable')
            for stamp in (12, 13):
                clock[0] = stamp
                self.assertFalse(capacity())
            clock[0] = 14
            self.assertTrue(capacity())
            self.assertIsNone(capacity.status()['error'])

    def test_resource_configuration_is_explicit_and_typed(self):
        config = Config.from_dict({'resources': {'adaptive_headroom': True, 'min_available_ram_gib': 4,
                                  'recovery_seconds': 12, 'recovery_margin_gib': 2}})
        self.assertTrue(config.adaptive_headroom)
        for resources in ({'adaptive_headroom': True}, {'adaptive_headroom': 1},
                          {'recovery_seconds': -1}, {'recovery_margin_gib': float('nan')},
                          {'max_sample_age_s': 0}, {'max_sample_age_s': True},
                          {'recovery_seconds': 10 ** 1000}):
            with self.subTest(resources=resources), self.assertRaises(ValueError):
                Config.from_dict({'resources': resources})


class HeadroomGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_sampler_fault_cannot_skip_connection_pool_cleanup(self):
        gateway = Gateway(Config(min_available_ram_gib=4, adaptive_headroom=True))
        with patch('adaptive_inference.resources.available_gib', side_effect=ValueError('unexpected sensor fault')):
            await gateway.startup(None)
            await asyncio.sleep(0)
            self.assertTrue(gateway.capacity_task.done())
            with self.assertRaisesRegex(ValueError, 'unexpected sensor fault'):
                await gateway.cleanup(None)
            self.assertTrue(gateway.client.closed)

    async def wait_until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 5)

    async def test_pressure_preserves_active_owner_and_delays_follower_until_recovery(self):
        free = [6.0]
        received = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def backend_reply(request):
            body = await request.json()
            received.append(body)
            if len(received) == 1:
                entered.set()
                await release.wait()
            return web.json_response({'choices': [{'index': 0, 'finish_reason': 'stop',
                                                   'message': {'role': 'assistant', 'content': 'ok'}}]})

        backend_app = web.Application()
        backend_app.router.add_post('/v1/chat/completions', backend_reply)
        backend = TestServer(backend_app)
        await backend.start_server()
        app = create_app(Config(backend_url=str(backend.make_url('/v1')), min_available_ram_gib=4,
                               adaptive_headroom=True, recovery_margin_gib=1, recovery_seconds=.15,
                               max_sample_age_s=1, queue_timeout_s=5, upstream_timeout_s=5))
        gateway = app[GATEWAY]
        gateway.capacity.sample_interval_s = .02
        client = TestClient(TestServer(app))
        tasks = []
        body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'unchanged task'}],
                'max_tokens': 700, 'temperature': .7, 'reasoning_effort': 'high',
                'tools': [{'type': 'function', 'function': {'name': 'check'}}]}
        with patch('adaptive_inference.resources.available_gib', side_effect=lambda: free[0]):
            try:
                await client.start_server()
                # The monitor samples even without a queued request.
                await self.wait_until(lambda: gateway.capacity.policy.allowed)
                first_stamp = gateway.capacity.policy.last_sample
                await self.wait_until(lambda: gateway.capacity.policy.last_sample > first_stamp)
                first = asyncio.create_task(client.post('/v1/chat/completions', json=body))
                tasks.append(first)
                await asyncio.wait_for(entered.wait(), 5)
                free[0] = 2
                await self.wait_until(lambda: not gateway.capacity.policy.allowed)
                self.assertIsNotNone(gateway.scheduler.active)
                second = asyncio.create_task(client.post('/v1/chat/completions', json=body))
                tasks.append(second)
                await self.wait_until(lambda: len(gateway.scheduler.pending) == 1)
                release.set()
                response = await asyncio.wait_for(first, 5)
                self.assertEqual(response.status, 200)
                await response.read()
                free[0] = 4.5  # Above the floor, below the recovery margin.
                await self.wait_until(lambda: gateway.capacity.policy.reason == 'recovery_margin')
                self.assertEqual(len(received), 1)
                self.assertFalse(second.done())
                free[0] = 6
                response = await asyncio.wait_for(second, 5)
                self.assertEqual(response.status, 200)
                await response.read()
                self.assertEqual(received, [body, body])
                self.assertIsNone(gateway.scheduler.active)
                self.assertEqual(len(gateway.scheduler.pending), 0)
                status = await (await client.get('/status')).json()
                self.assertFalse(status['resources']['adaptive_headroom']['resource_reservation'])
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await client.close()
                await backend.close()
        self.assertTrue(gateway.capacity_task.cancelled())

    async def test_no_background_sampler_for_disabled_or_floor_only_mode(self):
        for minimum in (0, 4):
            with self.subTest(minimum=minimum), patch('adaptive_inference.resources.available_gib') as sensor:
                app = create_app(Config(min_available_ram_gib=minimum))
                client = TestClient(TestServer(app))
                try:
                    await client.start_server()
                    await asyncio.sleep(.02)
                    self.assertIsNone(app[GATEWAY].capacity_task)
                    sensor.assert_not_called()
                finally:
                    await client.close()
