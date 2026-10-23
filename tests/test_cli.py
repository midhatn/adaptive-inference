"""Real CLI subprocesses and loopback discovery fixtures; no model needed."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientError, web

from adaptive_inference import cli
from adaptive_inference.config import Config, load_config
from adaptive_inference.demo import start_app


ROOT = Path(__file__).resolve().parents[1]


class ConfigInputTests(unittest.TestCase):
    def test_invalid_url_types_and_ports_are_configuration_errors(self):
        for value in (None, False, 12, [], {}, "http://localhost:0/v1",
                      "http://localhost:70000/v1", "http://localhost:invalid/v1",
                      "http://local host/v1", "http://localhost/v1\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config.from_dict({"backend": {"base_url": value}})

    def test_host_and_credential_references_are_typed(self):
        for value in (None, 1, True, [], {}):
            with self.subTest(host=value), self.assertRaises(ValueError):
                Config.from_dict({"listen": {"host": value}})
        for field in ("listen", "backend"):
            for value in ([], {}, True, "Bearer secret", ""):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Config.from_dict({field: {"api_key_env": value}})

    def test_windows_utf8_bom_and_ipv6_are_supported(self):
        raw = {"listen": {"host": "::1"}, "backend": {"base_url": "http://[::1]:8080/v1/"}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8-sig")
            config = load_config(path)
        self.assertEqual(config.host, "::1")
        self.assertEqual(config.backend_url, "http://[::1]:8080/v1")

    def test_network_error_has_clean_cli_diagnostic(self):
        async def failure(config):
            raise ClientError("fixture network failure")
        with patch.object(cli, "load_config", return_value=Config()), patch.object(cli, "doctor", failure):
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(cli.main(["doctor", "--config", "fixture.json"]), 2)
        self.assertIn("fixture network failure", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())


class CLIProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="adaptive-cli-")
        self.directory = Path(self.temporary.name)
        self.runner = None
        self.requests = []

    async def asyncTearDown(self):
        if self.runner:
            await self.runner.cleanup()
        self.temporary.cleanup()

    async def command(self, *arguments):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-B", "-m", "adaptive_inference.cli", *arguments,
            cwd=self.directory, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), 40)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        return proc.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

    async def server(self, content, *, status=200, chunked=False):
        async def models(request):
            self.requests.append((request.method, request.path))
            response = web.StreamResponse(status=status, headers={"Content-Type": "application/json"})
            if chunked:
                response.enable_chunked_encoding()
            else:
                response.content_length = len(content)
            await response.prepare(request)
            try:
                # Force independent reads. read(n) may return only the first
                # fragment, even though n is much larger than the whole body.
                await response.write(content[:8])
                await asyncio.sleep(.03)
                for begin in range(8, len(content), 64 * 1024):
                    await response.write(content[begin:begin + 64 * 1024])
                await response.write_eof()
            except ConnectionError:
                pass  # Expected when doctor refuses an oversized response.
            return response
        app = web.Application()
        app.router.add_get("/v1/models", models)
        self.runner, url = await start_app(app)
        config = self.directory / "server.json"
        config.write_text(json.dumps({"backend": {"base_url": url + "/v1"}}), encoding="utf-8")
        return config

    async def test_actual_profiles_command_serializes_immutable_profiles(self):
        code, stdout, stderr = await self.command("profiles")
        self.assertEqual(code, 0, stderr)
        profiles = json.loads(stdout)
        self.assertEqual(len(profiles), 8)
        self.assertEqual({row["id"] for row in profiles},
                         {"strata", "llamacpp", "vllm", "sglang", "ollama", "lmstudio", "mlx_lm", "tgi"})
        self.assertTrue(all(isinstance(row["endpoints"], list) for row in profiles))

    async def test_budget_command_has_actionable_exit_codes_and_preserves_ceiling(self):
        for prompt, output, status, expected in ((6545, 4096, 'needs_compaction', 1),
                                                  (3584, 4096, 'ready', 0),
                                                  (0, 9000, 'no_room', 1)):
            with self.subTest(status=status):
                code, stdout, stderr = await self.command('budget', '--context-tokens', '8192',
                        '--prompt-tokens', str(prompt), '--required-output-tokens', str(output))
                self.assertEqual(code, expected, stderr)
                plan = json.loads(stdout)
                self.assertEqual(plan['status'], status)
                self.assertEqual(plan['required_output_tokens'], output)
        code, stdout, stderr = await self.command('budget', '--context-tokens', '8192',
                '--prompt-tokens', '-1', '--required-output-tokens', '4096')
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', stderr)

    async def test_actual_demo_orders_equal_cost_requests_and_writes_receipt(self):
        target = self.directory / "demo.json"
        code, stdout, stderr = await self.command("demo", "--output", str(target))
        self.assertEqual(code, 0, stderr)
        receipt = json.loads(stdout)
        self.assertEqual(receipt, json.loads(target.read_text(encoding="utf-8")))
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["dispatch_order"], ["held", "later normal", "earlier background"])
        self.assertEqual(receipt["task_correction"]["attempts"], 2)
        self.assertEqual(receipt["pending"], 0)
        self.assertFalse(receipt["active"])
        self.assertFalse(receipt["speedup_claim"])

    async def test_actual_doctor_waits_for_entire_chunked_model_list(self):
        content = json.dumps({"data": [{"id": "existing-model"}, {"id": "other-model"}]}).encode()
        config = await self.server(content, chunked=True)
        code, stdout, stderr = await self.command("doctor", "--config", str(config))
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["models"], ["existing-model", "other-model"])
        self.assertFalse(report["inference_tested"])
        self.assertEqual(self.requests, [("GET", "/v1/models")])

    async def test_doctor_refuses_oversized_chunked_body_with_no_traceback(self):
        config = await self.server(b'{"data":' + b" " * (1024 * 1024) + b"[]}", chunked=True)
        code, stdout, stderr = await self.command("doctor", "--config", str(config))
        self.assertEqual(code, 2)
        self.assertIn("exceeds 1 MiB", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.requests, [("GET", "/v1/models")])

    async def test_doctor_refuses_invalid_model_shape_without_traceback(self):
        config = await self.server(b'{"data": {"id":"not-a-list"}}')
        code, stdout, stderr = await self.command("doctor", "--config", str(config))
        self.assertEqual(code, 2)
        self.assertIn("invalid model list", stderr)
        self.assertNotIn("Traceback", stderr)

    async def test_operational_input_and_output_errors_have_no_traceback(self):
        config = self.directory / "invalid.json"
        config.write_text('{"backend":{"base_url":null}}', encoding="utf-8")
        for arguments in (("doctor", "--config", str(config)),
                          ("doctor", "--config", str(self.directory / "missing.json"))):
            code, stdout, stderr = await self.command(*arguments)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", stderr)
            self.assertIn("adaptive-inference:", stderr)


if __name__ == "__main__":
    unittest.main()
