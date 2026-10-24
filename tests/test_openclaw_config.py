from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("openclaw_config", ROOT / "examples" / "agents" / "openclaw_config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inputs():
    provider = {"api": "openai-completions", "baseUrl": "http://127.0.0.1:18100/v1",
        "apiKey": {"source": "env", "provider": "default", "id": "FIXTURE_GATEWAY_KEY"},
        "headers": {"X-Tenant": "fixture"}, "request": {"headers": {"X-Trace": "fixture"}},
        "models": [{"id": "existing-IQ3_S", "name": "Existing model", "reasoning": True,
                    "input": ["text", "image"], "contextWindow": 65536, "maxTokens": 10923,
                    "compat": {"maxTokensField": "max_tokens", "supportsReasoningEffort": True}}]}
    defaults = {"model": {"primary": "adaptive/existing-IQ3_S", "fallbacks": ["other/retained"]},
        "thinkingDefault": "high", "params": {"temperature": 0.2},
        "models": {"adaptive/existing-IQ3_S": {"params": {"maxTokens": 10923,
                      "reasoning_budget_tokens": 8192, "experimental_speed_projection": False}}},
        "subagents": {"maxConcurrent": 2, "thinking": "high"}}
    return provider, defaults


def compose(provider, defaults):
    return module.build_config(provider, defaults, provider_id="adaptive", model_id="existing-IQ3_S",
                               background_provider_id="adaptive-background")


def test_preserves_declared_provider_quality_auth_fallbacks_and_input():
    provider, defaults = inputs()
    before = deepcopy((provider, defaults))
    result = compose(provider, defaults)
    assert (provider, defaults) == before
    normal, background = (result["models"]["providers"][x] for x in ("adaptive", "adaptive-background"))
    assert normal == provider
    expected = deepcopy(provider)
    expected["baseUrl"] = "http://127.0.0.1:18100/background/v1"
    assert background == expected
    actual = result["agents"]["defaults"]
    assert actual["model"] == defaults["model"]
    assert actual["subagents"]["model"] == {"primary": "adaptive-background/existing-IQ3_S",
                                            "fallbacks": ["other/retained"]}
    assert actual["models"]["adaptive-background/existing-IQ3_S"] == defaults["models"]["adaptive/existing-IQ3_S"]
    assert actual["thinkingDefault"] == "high"
    assert actual["subagents"]["thinking"] == "high"
    background["models"][0]["maxTokens"] = 1
    assert normal == provider == before[0]


def test_explicit_child_fallbacks_are_retained_and_proxy_prefix_supported():
    provider, defaults = inputs()
    provider["baseUrl"] = "https://gateway.example/proxy/v1"
    defaults["subagents"]["model"] = {"primary": "adaptive/existing-IQ3_S", "fallbacks": []}
    result = compose(provider, defaults)
    assert result["models"]["providers"]["adaptive-background"]["baseUrl"] == "https://gateway.example/proxy/background/v1"
    assert result["agents"]["defaults"]["subagents"]["model"]["fallbacks"] == []


def test_ambiguous_existing_choices_refuse_without_mutation(case):
    provider, defaults = inputs()
    if case == "other-child": defaults["subagents"]["model"] = "other/explicit"
    elif case == "restricted": defaults["modelPolicy"] = {"allow": ["adaptive/existing-IQ3_S"]}
    elif case == "existing-settings": defaults["models"]["adaptive-background/existing-IQ3_S"] = {}
    elif case == "wrong-api": provider["api"] = "openai-responses"
    elif case == "header": provider["request"]["headers"]["x-adaptive-class"] = "normal"
    elif case == "background": provider["baseUrl"] += "/background/v1"
    elif case == "missing-model": provider["models"] = []
    elif case == "nan": provider["models"][0]["maxTokens"] = float("nan")
    elif case == "malformed-request": provider["request"] = []
    before = json.dumps((provider, defaults), sort_keys=True)
    with unittest.TestCase().assertRaises(ValueError): compose(provider, defaults)
    assert json.dumps((provider, defaults), sort_keys=True) == before


def test_explicitly_allowed_background_route_and_string_model():
    provider, defaults = inputs()
    defaults["model"] = "adaptive/existing-IQ3_S"
    defaults["modelPolicy"] = {"allow": ["adaptive/existing-IQ3_S", "adaptive-background/existing-IQ3_S"]}
    result = compose(provider, defaults)
    assert result["agents"]["defaults"]["subagents"]["model"] == "adaptive-background/existing-IQ3_S"


def test_picker_alias_not_duplicated_but_generation_settings_preserved():
    provider, defaults = inputs()
    original = defaults["models"]["adaptive/existing-IQ3_S"]
    original["alias"] = "my-model"
    result = compose(provider, defaults)
    actual = result["agents"]["defaults"]["models"]
    assert actual["adaptive/existing-IQ3_S"] == original
    assert actual["adaptive-background/existing-IQ3_S"] == {"params": original["params"]}


def test_cli_new_output_and_collision_refusal(tmp_path):
    import subprocess
    provider, defaults = inputs()
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"models": {"providers": {"adaptive": provider}},
                                  "agents": {"defaults": defaults}}), encoding="utf-8")
    output = tmp_path / "fragment.json"
    command = [sys.executable, str(ROOT / "examples" / "agents" / "openclaw_config.py"),
               "--input", str(source), "--provider", "adaptive", "--model", "existing-IQ3_S",
               "--background-provider", "adaptive-background", "--output", str(output)]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    before = output.read_bytes()
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == before


class OpenClawConfigTests(unittest.TestCase):
    def test_preservation(self):
        test_preserves_declared_provider_quality_auth_fallbacks_and_input()
    def test_fallbacks_and_proxy(self):
        test_explicit_child_fallbacks_are_retained_and_proxy_prefix_supported()
    def test_refusals(self):
        for case in ("other-child", "restricted", "existing-settings", "wrong-api", "header",
                     "background", "missing-model", "nan", "malformed-request"):
            with self.subTest(case=case):
                test_ambiguous_existing_choices_refuse_without_mutation(case)
    def test_allowlist(self):
        test_explicitly_allowed_background_route_and_string_model()
    def test_alias(self):
        test_picker_alias_not_duplicated_but_generation_settings_preserved()
    def test_command(self):
        with TemporaryDirectory() as tmp:
            test_cli_new_output_and_collision_refusal(Path(tmp))

if __name__ == "__main__":
    unittest.main()
