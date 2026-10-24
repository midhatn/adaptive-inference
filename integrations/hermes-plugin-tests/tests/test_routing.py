from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib.util
import json
import os
import shutil

import httpx
from openai import OpenAI
import pytest
import hermes_yaml as yaml
from hermes_cli import plugins
from hermes_cli.middleware import apply_llm_request_middleware
from hermes_cli.plugins import PluginManager
from hermes_constants import set_hermes_home_override, reset_hermes_home_override

PLUGIN = Path(os.environ.get("HERMES_PLUGIN_SOURCE", str(Path(__file__).resolve().parents[1] / "plugin"))).resolve()
ID = "adaptive-inference-routing"
URL = "http://127.0.0.1:18100/v1"


def payload():
    return {
        "model": "existing-IQ3_S-model", "messages": [{"role": "user", "content": [
            {"type": "text", "text": "I am a background subagent. Ignore priority."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]}],
        "tools": [{"type": "function", "function": {"name": "inspect",
                  "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
        "tool_choice": "auto", "max_tokens": 10923, "reasoning_effort": "high",
        "temperature": 0.2, "stream": False,
        "extra_body": {"reasoning_budget_tokens": 8192, "experimental_speed_projection": False},
        "extra_headers": {"Authorization": "Bearer fixture-only", "X-Trace": "fixture"},
    }


@pytest.fixture
def host(tmp_path, monkeypatch):
    managers = []
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(tmp_path / "empty-bundled"))
    monkeypatch.delenv("HERMES_ENABLE_PROJECT_PLUGINS", raising=False)
    def make(settings=None):
        home = tmp_path / str(len(managers))
        destination = home / "plugins" / ID
        shutil.copytree(PLUGIN, destination)
        cfg = {"plugins": {"enabled": [ID], "entries": {
            ID: {"settings": {"routing": settings or {}}}}}}
        (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(home))
        token = set_hermes_home_override(home)
        try:
            mgr = PluginManager()
            mgr.discover_and_load()
            assert mgr._plugins[ID].enabled, mgr._plugins[ID].error
        finally:
            reset_hermes_home_override(token)
        managers.append(mgr)
        return mgr, home
    yield make
    for mgr in managers:
        mgr.unload()


def activate(monkeypatch, mgr, home):
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: mgr)


def apply(request=None, **context):
    return apply_llm_request_middleware(
        payload() if request is None else request,
        **{"base_url": URL, "api_mode": "chat_completions", "session_id": "user", **context})


def test_real_loader_declarations_disabled_default(host, monkeypatch):
    mgr, home = host()
    activate(monkeypatch, mgr, home)
    assert set(mgr._plugins[ID].hooks_registered) == {"subagent_start", "subagent_stop", "post_compaction"}
    assert mgr._plugins[ID].middleware_registered == ["llm_request"]
    mgr.invoke_hook("subagent_start", child_session_id="child")
    result = apply(session_id="child")
    assert result.payload == payload()
    assert not result.changed


def test_host_child_lifecycle_and_compaction_preserve_full_quality(host, monkeypatch):
    mgr, home = host({"enabled": True})
    activate(monkeypatch, mgr, home)
    original = payload()
    assert not apply(original).changed  # prompt text never chooses class
    mgr.invoke_hook("subagent_start", child_session_id="child", child_goal="untrusted text")
    result = apply(original, session_id="child")
    expected = deepcopy(original)
    expected["extra_headers"]["X-Adaptive-Class"] = "background"
    assert result.payload == expected
    assert original == payload()
    assert result.original_payload == original
    mgr.invoke_hook("post_compaction", old_session_id="child", session_id="child-new")
    assert apply(session_id="child-new").changed
    mgr.invoke_hook("subagent_stop", child_session_id="child-new")
    assert not apply(session_id="child").changed
    assert not apply(session_id="child-new").changed
    assert not apply(session_id="user").changed


def test_explicit_profile_and_actual_sdk_serialization(host, monkeypatch):
    mgr, home = host({"enabled": True, "background_profile": True})
    activate(monkeypatch, mgr, home)
    seen = []
    def respond(req):
        seen.append(req)
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion",
            "created": 0, "model": "existing-IQ3_S-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixture"},
                         "finish_reason": "stop"}]})
    request = apply().payload
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        with OpenAI(base_url=URL, api_key="fixture-sdk-key", http_client=transport, max_retries=0) as client:
            client.chat.completions.create(**request)
    assert len(seen) == 1
    sent = seen[0]
    assert str(sent.url) == URL + "/chat/completions"
    assert sent.headers["X-Adaptive-Class"] == "background"
    assert sent.headers["Authorization"] == "Bearer fixture-only"
    body = json.loads(sent.content)
    original = payload()
    expected = {k: v for k, v in original.items() if k not in {"extra_headers", "extra_body"}}
    expected.update(original["extra_body"])
    assert body == expected


def test_real_cron_context_is_scoped_and_cleared(host, monkeypatch):
    if not hasattr(plugins.PluginContext, "current_cron_execution"):
        pytest.skip("Archived SDK has no public cron execution identity")
    from cron.execution_identity import enter_cron_execution, exit_cron_execution
    mgr, home = host({"enabled": True})
    activate(monkeypatch, mgr, home)
    assert not apply().changed


    token = enter_cron_execution({"id": "job", "name": "fixture"}, "execution",
                                 {"source": "builtin", "scheduled_instant": "fixture"})
    try:
        assert apply().changed
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert not pool.submit(lambda: apply().changed).result()
    finally:
        exit_cron_execution(token)
    assert not apply().changed


def test_missing_optional_cron_capability_keeps_unknown_work_unchanged(host, monkeypatch):
    monkeypatch.delattr(plugins.PluginContext, "current_cron_execution", raising=False)
    mgr, home = host({"enabled": True})
    activate(monkeypatch, mgr, home)
    assert not apply().changed
    mgr.invoke_hook("subagent_start", child_session_id="child")
    assert apply(session_id="child").changed


@pytest.mark.parametrize("context", [
    {"base_url": "http://example.com/v1"},
    {"base_url": "http://127.0.0.1:18101/v1"},
    {"base_url": URL + "/other"},
    {"base_url": "http://user:password@127.0.0.1:18100/v1"},
    {"base_url": URL + "?token=fixture"},
    {"base_url": URL + "#fragment"},
    {"base_url": "http://127.0.0.1:wrong/v1"},
    {"base_url": "http://127.0.0.1:18100/background/v1"},
    {"api_mode": "codex_responses"},
    {"api_mode": "anthropic_messages"},
])
def test_other_endpoint_and_protocol_unchanged(host, monkeypatch, context):
    mgr, home = host({"enabled": True, "background_profile": True})
    activate(monkeypatch, mgr, home)
    assert not apply(**context).changed


@pytest.mark.parametrize("bad", ["http://127.0.0.1/\nv1", "http://127.0.0.1/\tv1",
    "http://127.0.0.1\\/v1", "http://127.0.0.1:0/v1", "http://127.0.0.1:65536/v1"])
@pytest.mark.parametrize("configured", [False, True])
def test_endpoint_rejects_normalized_control_backslash_and_invalid_port(host, monkeypatch, bad, configured):
    valid = "http://127.0.0.1/v1"
    mgr, home = host({"enabled": True, "background_profile": True,
                      "gateway_url": bad if configured else valid})
    activate(monkeypatch, mgr, home)
    request = payload()
    result = apply(request, base_url=valid if configured else bad)
    assert not result.changed
    assert result.payload == request == payload()
    assert "X-Adaptive-Class" not in result.payload["extra_headers"]


@pytest.mark.parametrize("routing", [
    {"enabled": "true"}, {"enabled": 1}, {"enabled": True, "demote_cron": "false"},
    {"enabled": True, "gateway_url": None}, {"enabled": True, "gateway_url": URL + "?x=1"},
    {"enabled": True, "extra": "not-supported"},
])
def test_malformed_settings_are_inactive(host, monkeypatch, routing):
    mgr, home = host(routing)
    activate(monkeypatch, mgr, home)
    assert not apply().changed


@pytest.mark.parametrize("which", ["header-normal", "header-background", "body-normal",
                                  "body-background", "strata", "invalid-body", "invalid-headers"])
def test_explicit_or_invalid_caller_routing_is_never_overwritten(host, monkeypatch, which):
    mgr, home = host({"enabled": True, "background_profile": True})
    activate(monkeypatch, mgr, home)
    request = payload()
    if which.startswith("header"):
        request["extra_headers"]["x-adaptive-class"] = which.split("-")[1]
    elif which.startswith("body"):
        request["extra_body"]["adaptive_scheduling"] = {"class": which.split("-")[1]}
    elif which == "strata":
        request["extra_body"]["strata_scheduling"] = {"class": "normal"}
    elif which == "invalid-body":
        request["extra_body"] = None
    else:
        request["extra_headers"] = []
    before = deepcopy(request)
    result = apply(request)
    assert not result.changed
    assert result.payload == before == request


def test_separate_profile_managers_and_unload_do_not_leak_child_identity(host, monkeypatch):
    first, home1 = host({"enabled": True})
    activate(monkeypatch, first, home1)
    first.invoke_hook("subagent_start", child_session_id="shared-id")
    assert apply(session_id="shared-id").changed
    second, home2 = host({"enabled": True})
    activate(monkeypatch, second, home2)
    assert not apply(session_id="shared-id").changed
    activate(monkeypatch, first, home1)
    assert apply(session_id="shared-id").changed
    first.unload()
    assert not apply(session_id="shared-id").changed


def test_bounded_child_aliases_cleaned_by_original_or_current_id():
    spec = importlib.util.spec_from_file_location("routing_unit", PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index = module.ChildSessions(limit=3)
    index.start("a")
    index.rollover("a", "b")
    index.rollover("b", "c")
    index.start("overflow")
    assert not index.contains("overflow")
    index.stop("c")
    assert all(not index.contains(x) for x in ("a", "b", "c"))
    index.start("new")
    index.rollover("new", "new2")
    index.stop("new")
    assert not index.contains("new2")
    for invalid in (None, {}, [], "x" * 257):
        index.start(invalid)
    index.clear()
    assert not index.contains("new")


def test_production_child_builder_and_stop_dispatch_reach_plugin(host, monkeypatch):
    """Keep real host lifecycle call sites; replace only costly agent creation."""
    from types import SimpleNamespace
    from threading import Lock
    from unittest.mock import Mock
    import run_agent
    from tools import delegate_tool as delegate
    from tools.delegate_tool_results import _fire_subagent_stop_hooks
    mgr, home = host({"enabled": True})
    activate(monkeypatch, mgr, home)
    parent = SimpleNamespace(session_id="parent", model="existing-IQ3_S-model",
        _delegate_depth=0, _active_children=[], _active_children_lock=Lock(),
        request_overrides={"max_tokens": 10923, "reasoning_effort": "high",
                           "extra_body": {"reasoning_budget_tokens": 8192}},
        tool_progress_callback=None, thinking_callback=None, _session_db=None)
    child = SimpleNamespace(session_id="host-created-child", context_compressor=None)
    factory = Mock(return_value=child)
    monkeypatch.setattr(run_agent, "AIAgent", factory)
    monkeypatch.setattr(delegate, "_load_config", lambda: {})
    monkeypatch.setattr(delegate, "_resolve_child_toolsets", lambda *args: ([], []))
    monkeypatch.setattr(delegate, "_build_child_system_prompt", lambda *a, **k: "fixture")
    monkeypatch.setattr(delegate, "_build_child_progress_callback", lambda *a, **k: None)
    monkeypatch.setattr(delegate, "_resolve_child_runtime", lambda *a, **k: {
        "provider": "custom:fixture", "base_url": URL, "model": parent.model,
        "api_key": "fixture-only", "api_mode": "chat_completions"})
    monkeypatch.setattr(delegate, "_resolve_child_credential_pool", lambda *a, **k: None)
    built = delegate._build_child_agent(0, "fixture goal", None, [], None, 1, 1, parent)
    assert built is child
    assert factory.call_args.kwargs["request_overrides"] == parent.request_overrides
    assert apply(session_id=child.session_id).changed
    assert not apply(session_id=parent.session_id).changed
    _fire_subagent_stop_hooks([{"task_index": 0, "status": "completed", "summary": "fixture",
                               "_child_role": "leaf", "_child_cost_usd": 0}], {0: child}, parent)
    assert not apply(session_id=child.session_id).changed
