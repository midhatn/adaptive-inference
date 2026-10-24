"""Protect explicit client identity at the SDK's actual merge surfaces."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from adaptive_inference.client_routing import generation_options_for_route

ROOT = Path(__file__).resolve().parents[1]


class GenerationOptionTests(unittest.TestCase):
    def test_reserved_identity_and_transport_at_actual_sdk_envelopes(self):
        for option in (
            {"extra_body": {"model": "different"}},
            {"model_kwargs": {"extra_body": {"model": "different"}}},
            {"model_kwargs": {"model": "different"}},
            {"model_name": "different"},
            {"root_client": object()},
            {"root_async_client": object()},
            {"default_query": {"api_key": "different"}},
        ):
            with self.subTest(option=list(option)), self.assertRaises(ValueError):
                generation_options_for_route(option)

    def test_header_names_are_case_insensitive_in_both_sdk_envelopes(self):
        for envelope in ("default_headers", "extra_headers"):
            for name in ("Authorization", "aUtHoRiZaTiOn", "X-Api-Key", "Host", "X-Adaptive-Class"):
                value = {envelope: {name: "different"}}
                with self.subTest(envelope=envelope, name=name):
                    with self.assertRaises(ValueError):
                        generation_options_for_route(value)
                    with self.assertRaises(ValueError):
                        generation_options_for_route({"model_kwargs": value})

    def test_quality_tracing_and_tool_schema_are_preserved_without_aliasing(self):
        value = {
            "max_tokens": 10923, "reasoning_effort": "high",
            "extra_body": {"reasoning_budget_tokens": 8192,
                           "experimental_speed_projection": False,
                           "vendor": {"model": "literal-data"}},
            "default_headers": {"X-Trace": "fixture"},
            "model_kwargs": {"extra_headers": {"X-Trace-Extra": "fixture"},
                             "stream_options": {"include_usage": True}},
            "tools": [{"type": "function", "function": {"name": "inspect", "parameters": {
                "type": "object", "properties": {"model": {"type": "string"}}}}}],
        }
        before = deepcopy(value)
        result = generation_options_for_route(value)
        self.assertEqual(result, value)
        result["extra_body"]["reasoning_budget_tokens"] = 1
        result["default_headers"]["X-Trace"] = "changed"
        self.assertEqual(value, before)

    def test_none_and_malformed_envelopes(self):
        self.assertEqual(generation_options_for_route(None), {})
        for value in ([], False, "bad", {1: "bad"}, {"extra_body": []},
                      {"model_kwargs": []}, {"default_headers": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generation_options_for_route(value)

    def test_all_factories_refuse_before_constructing_a_client(self):
        def unexpected(**kwargs):
            self.fail("Client constructor reached before conflicting options were refused")
        modules = {
            "langchain_openai": types.SimpleNamespace(ChatOpenAI=unexpected),
            "langgraph.graph": types.SimpleNamespace(END="end", START="start", MessagesState=dict, StateGraph=unexpected),
            "crewai": types.SimpleNamespace(LLM=unexpected),
            "autogen_ext.models.openai": types.SimpleNamespace(OpenAIChatCompletionClient=unexpected),
        }
        info = dict(vision=False, function_calling=True, json_output=False,
                    family="unknown", structured_output=False)
        with patch.dict(sys.modules, modules):
            for name, factory in (("langgraph", "build_graph"), ("crewai", "build_llm"), ("autogen", "build_client")):
                spec = importlib.util.spec_from_file_location(name, ROOT / "examples/agents" / f"{name}_client.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for options in ({"extra_body": {"model": "different"}},
                                {"default_headers": {"Authorization": "Bearer different"}}):
                    kwargs = {"generation_options": options}
                    if name == "autogen":
                        kwargs["model_info"] = info
                    with self.subTest(client=name, option=list(options)), self.assertRaises(ValueError):
                        getattr(module, factory)("fixture-model", **kwargs)


if __name__ == "__main__":
    unittest.main()
