import ast
import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from adaptive_inference.adapters import (
    ENGINE_PROFILES, STRATA_EXTENSIONS, engine_profile, list_profiles, prepare_request,
)
from adaptive_inference.config import Config


ROOT = Path(__file__).resolve().parents[1]


class AdapterContractTests(unittest.TestCase):
    def test_preserves_full_tool_and_multimodal_request_for_every_profile(self):
        body = {
            "model": "existing/server-model", "max_tokens": 10923,
            "max_completion_tokens": 10923, "temperature": 0.73,
            "reasoning_effort": "high", "seed": 0, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "adaptive_scheduling is literal user text"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                ]},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {
                        "name": "read_file", "arguments": '{"strata_scheduling":{"class":"normal"}}'
                    }}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "exact\nresult"},
            ],
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {
                "type": "object", "properties": {"adaptive_scheduling": {"type": "string"}},
                "additionalProperties": False,
            }}}],
            "tool_choice": "auto", "parallel_tool_calls": False,
            "vendor_extension": {"values": [1, None, False]},
            "adaptive_scheduling": {"class": "background"},
            "strata_scheduling": {"class": "background"},
        }
        before = copy.deepcopy(body)
        expected = {k: v for k, v in body.items()
                    if k not in {"adaptive_scheduling", "strata_scheduling"}}
        for engine in ENGINE_PROFILES:
            with self.subTest(engine=engine):
                result = prepare_request(engine, body)
                self.assertEqual(result, expected)
                result["messages"][0]["content"][0]["text"] = "changed copy"
                result["vendor_extension"]["values"].append(5)
                self.assertEqual(body, before)

    def test_does_not_add_defaults_to_chat_completion_or_embedding(self):
        bodies = [{"messages": []}, {"prompt": "exact prompt"},
                  {"input": ["one", "two"], "dimensions": 17, "encoding_format": "float"}]
        for engine in ENGINE_PROFILES:
            for body in bodies:
                with self.subTest(engine=engine, body=body):
                    self.assertEqual(prepare_request(engine, body), body)

    def test_known_strata_controls_rejected_without_mutation_elsewhere(self):
        for engine in set(ENGINE_PROFILES) - {"strata"}:
            for key in STRATA_EXTENSIONS | {"strata_future_control"}:
                body = {"model": "existing", key: False, "adaptive_scheduling": {"class": "background"}}
                before = copy.deepcopy(body)
                with self.subTest(engine=engine, key=key), self.assertRaisesRegex(ValueError, "Strata controls"):
                    prepare_request(engine, body)
                self.assertEqual(body, before)

    def test_strata_controls_are_not_downgraded_or_converted(self):
        body = {"model": "existing", "max_tokens": 10923, "reasoning_effort": "high",
                "reasoning_budget_tokens": 8192, "experimental_speed_projection": False,
                "pcie_frac": .37, "strata_checkpoint": {"opaque": ["keep", 1]}}
        self.assertEqual(prepare_request("strata", body), body)

    def test_unknown_engine_and_non_object_refuse(self):
        for name in ("made-up", "", None, 3):
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_request(name, {})
        for body in (None, [], "{}", 1):
            with self.subTest(body=body), self.assertRaises(ValueError):
                prepare_request("ollama", body)

    def test_registry_and_nested_profile_metadata_are_immutable(self):
        with self.assertRaises(TypeError):
            ENGINE_PROFILES["new"] = ENGINE_PROFILES["strata"]
        with self.assertRaises(FrozenInstanceError):
            ENGINE_PROFILES["strata"].id = "other"
        self.assertIsInstance(ENGINE_PROFILES["strata"].endpoints, frozenset)
        self.assertIsInstance(ENGINE_PROFILES["strata"].extensions, frozenset)
        self.assertEqual(len(list_profiles()), 8)

    def test_explicit_aliases_do_not_infer_model_capabilities(self):
        self.assertIs(engine_profile("llama.cpp"), engine_profile("llamacpp"))
        self.assertIs(engine_profile("MLX-LM"), engine_profile("mlx_lm"))
        self.assertIs(engine_profile("lm-studio"), engine_profile("lmstudio"))
        self.assertNotIn("/v1/embeddings", engine_profile("strata").endpoints)
        self.assertNotIn("/v1/completions", engine_profile("strata").endpoints)
        self.assertNotIn("/v1/embeddings", engine_profile("mlx_lm").endpoints)
        self.assertNotIn("/v1/embeddings", engine_profile("tgi").endpoints)

    def test_engine_configs_have_exact_profile_route_and_one_shared_listener(self):
        configs = list((ROOT / "examples/engines").glob("*.json"))
        self.assertEqual({p.stem for p in configs}, set(ENGINE_PROFILES))
        for path in configs:
            with self.subTest(path=path.name):
                config = json.loads(path.read_text(encoding="utf-8"))
                parsed = Config.from_dict(config)
                self.assertEqual(parsed.backend_kind, path.stem)
                self.assertEqual(set(config), {"listen", "backend", "scheduler", "default_class"})
                self.assertEqual(config["listen"], {"host": "127.0.0.1", "port": 18100})
                self.assertEqual(config["backend"], {"kind": path.stem,
                    "base_url": engine_profile(path.stem).base_url, "api_key_env": None})
                self.assertEqual(config["default_class"], "normal")
                self.assertEqual(config["scheduler"], {"max_pending": 16, "queue_timeout_s": 300,
                    "normal_boost_s": 10, "max_cost_delay_s": 30})

    def test_agent_python_examples_are_import_inert(self):
        # Compile and import using no third-party packages. Imports inside the
        # factories cannot dispatch or load a model merely by reading examples.
        for name in ("langgraph", "autogen", "crewai"):
            path = ROOT / "examples/agents" / (name + "_client.py")
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            namespace = {"__name__": "example_contract", "__file__": str(path)}
            exec(compile(text, str(path), "exec"), namespace)
            factory = "build_graph" if name == "langgraph" else "build_client" if name == "autogen" else "build_llm"
            self.assertTrue(callable(namespace[factory]))

    def test_client_factories_keep_explicit_quality_and_share_background_route(self):
        # These are constructor/graph wiring fixtures, not real SDK/app tests.
        seen = []
        def client(**kwargs):
            seen.append(kwargs)
            return types.SimpleNamespace(invoke=lambda messages: {"content": "done"})
        class Graph:
            def __init__(self, state): pass
            def add_node(self, name, call): self.call = call
            def add_edge(self, *args): pass
            def compile(self): return self
        modules = {
            "langchain_openai": types.SimpleNamespace(ChatOpenAI=client),
            "langgraph.graph": types.SimpleNamespace(END="end", START="start", MessagesState=dict, StateGraph=Graph),
            "autogen_ext.models.openai": types.SimpleNamespace(OpenAIChatCompletionClient=client),
            "crewai": types.SimpleNamespace(LLM=client),
        }
        info = {"vision": False, "function_calling": True, "json_output": False,
                "family": "unknown", "structured_output": False}
        options = {"max_tokens": 10923, "temperature": .73}
        with patch.dict(sys.modules, modules):
            for name, factory in (("langgraph", "build_graph"), ("autogen", "build_client"), ("crewai", "build_llm")):
                path = ROOT / "examples/agents" / (name + "_client.py")
                namespace = {"__name__": "example_contract", "__file__": str(path)}
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
                for background in (False, True):
                    kwargs = {"background": background, "generation_options": options}
                    if name == "autogen": kwargs["model_info"] = info
                    namespace[factory]("existing/model-id", **kwargs)
                    observed = seen[-1]
                    self.assertEqual(observed["model"], "existing/model-id")
                    self.assertEqual(observed["max_tokens"], 10923)
                    self.assertEqual(observed["temperature"], .73)
                    self.assertEqual(observed["max_retries"], 0)
                    suffix = "/background/v1" if background else "/v1"
                    self.assertEqual(observed["base_url"], "http://127.0.0.1:18100" + suffix)
                kwargs["generation_options"] = {"base_url": "https://unexpected.example/v1"}
                count = len(seen)
                with self.assertRaisesRegex(ValueError, "selected client route"):
                    namespace[factory]("existing/model-id", **kwargs)
                self.assertEqual(len(seen), count)
        self.assertEqual(options, {"max_tokens": 10923, "temperature": .73})


if __name__ == "__main__":
    unittest.main()
