"""Execute the actual documentation clients against the released gateway and HTTP fixtures."""
import asyncio
from contextlib import asynccontextmanager, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
import openai

ROOT = Path(__file__).resolve().parent
from adaptive_inference.config import Config
from adaptive_inference.gateway import GATEWAY, create_app

DOCS = {
    'sglang': ROOT / 'sglang.md',
    'ollama': ROOT / 'ollama.md',
}


def blocks(engine):
    text = DOCS[engine].read_text(encoding='utf-8')
    client = re.findall(r'```python admitted_chat.py\n(.*?)\n```', text, re.S)
    config = re.findall(r'```json adaptive.json\n(.*?)\n```', text, re.S)
    assert len(client) == len(config) == 1
    namespace = {'__name__': 'reviewed_documentation_client'}
    exec(compile(client[0], str(DOCS[engine]), 'exec'), namespace)
    return namespace['run_request'], json.loads(config[0])


async def serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    return runner, 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])


@asynccontextmanager
async def fixture(engine, status=200):
    client, raw_config = blocks(engine)
    Config.from_dict(raw_config)  # Validate the unmodified published example first.
    received = []

    async def generate(request):
        body = await request.json()
        received.append({'path': request.path, 'body': body})
        if status != 200:
            return web.json_response({'error': {'message': 'fixture refusal'}}, status=status)
        base = {'id': 'fixture-id', 'created': 0, 'model': body['model']}
        if body.get('stream'):
            first = {**base, 'object': 'chat.completion.chunk', 'choices': [
                {'index': 0, 'delta': {'role': 'assistant', 'content': 'fixture',
                                      'reasoning_content': 'retained reasoning'}, 'finish_reason': None}]}
            end = {**base, 'object': 'chat.completion.chunk', 'choices': [
                {'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
            data = ''.join('data: ' + json.dumps(row) + '\n\n' for row in (first, end)) + 'data: [DONE]\n\n'
            return web.Response(body=data.encode(), content_type='text/event-stream')
        return web.json_response({**base, 'object': 'chat.completion', 'choices': [
            {'index': 0, 'message': {'role': 'assistant', 'content': 'fixture',
                                    'reasoning_content': 'retained reasoning'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 1, 'total_tokens': 11}})

    upstream = web.Application()
    upstream.router.add_post('/nested/v1/chat/completions', generate)
    backend_runner, address = await serve(upstream)
    raw_config['backend']['base_url'] = address + '/nested/v1'
    app = create_app(Config.from_dict(raw_config))
    gateway_runner, gateway_address = await serve(app)
    try:
        with patch.dict(os.environ, {'ADAPTIVE_BASE_URL': gateway_address,
                                     'ADAPTIVE_API_KEY': 'fixture-only'}):
            yield client, received, app[GATEWAY]
    finally:
        await gateway_runner.cleanup()
        await backend_runner.cleanup()


class EngineRecipes(unittest.IsolatedAsyncioTestCase):
    def request(self, *, stream=False):
        # Synthetic transport values, not a model/quality qualification.
        return {'model': 'fixture-model', 'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Fixture request'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,fixture'}}]}],
            'max_tokens': 127, 'temperature': 0.4, 'top_p': 0.91, 'seed': 43,
            'tools': [{'type': 'function', 'function': {'name': 'fixture_tool',
                'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}},
                               'required': ['text']}}}], 'stream': stream}

    async def invoke(self, client, request, background=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            path.write_text(json.dumps(request), encoding='utf-8')
            original = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                await asyncio.wait_for(asyncio.to_thread(client, path, background), timeout=10)
            self.assertEqual(path.read_bytes(), original)
            return [json.loads(line) for line in output.getvalue().splitlines()]

    async def check_requests(self, engine):
        async with fixture(engine) as (client, received, gateway):
            for background, stream in ((False, False), (True, False), (True, True)):
                request = self.request(stream=stream)
                request['extra_body'] = {'adaptive_scheduling': {'class': 'normal'}}
                if engine == 'sglang':
                    request['extra_body'].update(chat_template_kwargs={'enable_thinking': True},
                                                 separate_reasoning=True)
                before = deepcopy(request)
                output = await self.invoke(client, request, background)
                self.assertEqual(request, before)
                expected = {k: v for k, v in request.items() if k != 'extra_body'}
                expected.update({k: v for k, v in request['extra_body'].items() if k != 'adaptive_scheduling'})
                self.assertEqual(received[-1], {'path': '/nested/v1/chat/completions', 'body': expected})
                self.assertEqual(output[-1]['choices'][0]['finish_reason'], 'stop')
                message = output[0]['choices'][0]['delta' if stream else 'message']
                self.assertEqual(message['reasoning_content'], 'retained reasoning')
                self.assertEqual(gateway.history[-1]['class'], 'background' if background else 'normal')
            self.assertEqual(len(received), 3)
            self.assertEqual(len(gateway.history), 3)

    async def check_no_retry(self, engine):
        async with fixture(engine, status=503) as (client, received, _gateway):
            with self.assertRaises(openai.InternalServerError):
                await self.invoke(client, self.request(), True)
            self.assertEqual(len(received), 1)

    async def check_unsupported_budget(self, engine):
        async with fixture(engine) as (client, received, _gateway):
            request = self.request()
            request['extra_body'] = {'reasoning_budget_tokens': 8192}
            with self.assertRaises(openai.BadRequestError):
                await self.invoke(client, request)
            self.assertEqual(received, [])

    async def test_sglang_request_and_stream_preservation(self):
        await self.check_requests('sglang')

    async def test_ollama_request_and_stream_preservation(self):
        await self.check_requests('ollama')

    async def test_sglang_does_not_replay_backend_refusal(self):
        await self.check_no_retry('sglang')

    async def test_ollama_does_not_replay_backend_refusal(self):
        await self.check_no_retry('ollama')

    async def test_sglang_rejects_foreign_budget_without_forwarding(self):
        await self.check_unsupported_budget('sglang')

    async def test_ollama_rejects_foreign_budget_without_forwarding(self):
        await self.check_unsupported_budget('ollama')


if __name__ == '__main__':
    unittest.main()
