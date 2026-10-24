"""Private qualification of the actual SDK example with released gateway 0.2.0."""
import asyncio
from contextlib import asynccontextmanager
import runpy
from pathlib import Path

from aiohttp import web
import pytest

from adaptive_inference.config import Config
from adaptive_inference.gateway import GATEWAY, create_app
from openhands.sdk.llm.exceptions import LLMServiceUnavailableError

EXAMPLE_TESTS = runpy.run_path(str(Path(__file__).resolve().parent / 'test_example.py'))


@asynccontextmanager
async def composed():
    fixture = EXAMPLE_TESTS['endpoint'].__wrapped__()
    backend_root, requests, status = next(fixture)
    app = create_app(Config.from_dict({'listen': {'host': '127.0.0.1', 'port': 18100},
        'backend': {'kind': 'strata', 'base_url': backend_root + '/v1'}}))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f'http://127.0.0.1:{port}', requests, status, app[GATEWAY]
    finally:
        await runner.cleanup()
        try:
            next(fixture)
        except StopIteration:
            pass


@pytest.mark.asyncio
async def test_actual_sdk_gateway_classes_and_quality():
    async with composed() as (root, requests, status, gateway):
        for background in (False, True):
            llm = EXAMPLE_TESTS['admission_llm'](EXAMPLE_TESTS['config'].__wrapped__(),
                root, background=background, api_key='fixture')
            result = await asyncio.wait_for(asyncio.to_thread(
                llm.completion, messages=EXAMPLE_TESTS['messages']()), 15)
            assert result.message.content[0].text == '42'
            body = requests[-1]['body']
            assert requests[-1]['path'] == '/proxy/v1/chat/completions'
            assert body['model'] == 'fixture-model'
            assert body['max_completion_tokens'] == 10923
            assert body['reasoning_budget_tokens'] == 8192
            assert body['reasoning_effort'] == 'high'
            assert body['experimental_speed_projection'] is False
            assert body['temperature'] == 0.4 and body['top_p'] == 0.9
            assert gateway.history[-1]['class'] == ('background' if background else 'normal')
        assert len(requests) == len(gateway.history) == 2


@pytest.mark.asyncio
async def test_actual_sdk_gateway_does_not_retry_503():
    async with composed() as (root, requests, status, gateway):
        status[0] = 503
        llm = EXAMPLE_TESTS['admission_llm'](EXAMPLE_TESTS['config'].__wrapped__(),
            root, background=True, api_key='fixture')
        with pytest.raises(LLMServiceUnavailableError):
            await asyncio.wait_for(asyncio.to_thread(
                llm.completion, messages=EXAMPLE_TESTS['messages']()), 15)
        assert len(requests) == len(gateway.history) == 1
