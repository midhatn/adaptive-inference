# SPDX-License-Identifier: Apache-2.0
"""Existing bounded report contract and wire audit, extracted for installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

SDK = PYTHON = None

SDK_REV = "14e1e43a23761b369641208e204365cd6cb9399d"

MODEL = "qwen3.8-flash-next-iq3_s-adaptive-media-beta"

BASE = "http://127.0.0.1:18100/v1"

QUALITY = {"max_tokens": 10923, "reasoning_effort": "high", "reasoning_budget_tokens": 8192,
           "experimental_speed_projection": False, "strata_tune": {"pcie_frac": 0.37}}

CSV = "item,quantity,unit_cents\nnotebook,3,450\npen,8,125\nfolder,4,275\nnotebook,2,450\n"

REPORT = {"rows": 4, "units": 17, "total_cents": 4350,
          "by_item": {"folder": 1100, "notebook": 2250, "pen": 1000}}

VERDICT = {"verified": True, "rows": 4, "units": 17, "total_cents": 4350}

PLUGIN = "adaptive-inference-routing"

AUDIT = "bounded-file-audit"

def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()

def save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def git(*args):
    return subprocess.check_output(["git", "-C", str(SDK), *args], text=True).strip()

def config(work):
    return {
        "model": {"default": MODEL, "provider": "custom:adaptive", "base_url": BASE,
                  "api_mode": "chat_completions", "streaming": False, "context_length": 65536},
        "providers": {"adaptive": {"base_url": BASE, "api_key": "local-no-key", "api_mode": "chat_completions",
                       "models": [{"id": MODEL, "context_length": 65536}], "extra_body": QUALITY},
                      "custom": {"request_timeout_seconds": 180, "stale_timeout_seconds": 180}},
        "fallback_providers": [],
        "agent": {"max_turns": 8, "reasoning_effort": "high", "api_max_retries": 1,
                  "auto_recovery_cycles": 0, "environment_probe": False, "verify_on_stop": False},
        "toolsets": ["file"], "platform_toolsets": {"cli": ["file"], "subagent": ["file"]},
        "delegation": {"max_concurrent_children": 1, "max_spawn_depth": 1,
                       "max_iterations": 8, "child_timeout_seconds": 850, "reasoning_effort": "high"},
        "plugins": {"enabled": [PLUGIN, AUDIT], "entries": {PLUGIN: {"settings": {"routing": {
                    "enabled": True, "gateway_url": BASE, "demote_delegated": True}}}}},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "auxiliary": {"title_generation": {"enabled": False, "model_upgrade_enabled": False}},
        "tools": {"tool_search": {"enabled": "off"}}, "lsp": {"enabled": False},
        "compression": {"enabled": True, "threshold": 0.8},
        "terminal": {"backend": "local", "cwd": str(work)}}

def configure_inputs(sdk, python, gateway, model):
    """Explicit paths only; keep the measured IQ3_S quality contract fixed."""
    global SDK, PYTHON, BASE, MODEL
    if model != "qwen3.8-flash-next-iq3_s-adaptive-media-beta":
        raise ValueError("This reproduction permits only the qualified IQ3_S model ID")
    if not isinstance(gateway, str) or any(c.isspace() or ord(c) < 32 or c == "\\" for c in gateway):
        raise ValueError("Invalid gateway URL")
    url = urlsplit(gateway)
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.username is not None
            or url.password is not None or url.path != "/v1" or url.query or url.fragment
            or url.port is None or not 1 <= url.port <= 65535):
        raise ValueError("Gateway must be http://127.0.0.1:PORT/v1")
    SDK, PYTHON = (Path(p).resolve(strict=True) for p in (sdk, python))
    if not SDK.is_dir() or not PYTHON.is_file():
        raise ValueError("An explicit SDK directory and existing interpreter are required")
    BASE, MODEL = gateway, model

class Refused(BaseException):
    pass

class Boundary:
    def __init__(self, run, fixture):
        self.run, self.fixture = run, fixture
        self.rows = []; self.seen = set(); self.steps = {"parent": 0, "child": 0}
        self.original = None

    def send(self, client, req, **kw):
        import httpx
        url = str(req.url)
        if req.method == "GET":
            if url == BASE.removesuffix("/v1") + "/metrics" and not self.fixture:
                return self.original(client, req, **kw)
            if url in (BASE + "/models", BASE + "/models/" + MODEL):
                if self.fixture:
                    return httpx.Response(200, request=req, json={"object": "list", "data": [
                        {"id": MODEL, "object": "model", "context_length": 65536}]})
                return self.original(client, req, **kw)
            raise httpx.ConnectError("Only the declared gateway's model discovery is allowed", request=req)
        if req.method != "POST" or url != BASE + "/chat/completions":
            raise Refused("Unexpected network operation")
        phase = (self.run / "phase.txt").read_text(encoding="utf-8")
        body = json.loads(req.content)
        if phase not in self.steps or len(self.rows) >= 16 or self.steps[phase] >= 8:
            raise Refused("Request/phase bound exceeded")
        if len(req.content) > 512 * 1024 or body.get("model") != MODEL or body.get("stream", False) is not False:
            raise Refused("Model, size or stream contract changed")
        for k, v in QUALITY.items():
            if type(body.get(k)) is not type(v) or body.get(k) != v:
                raise Refused("Quality field changed: " + k)
        if any(k in body for k in ("max_completion_tokens", "thinking", "reasoning", "adaptive_scheduling", "strata_scheduling")):
            raise Refused("Ambiguous quality or manually injected scheduling")
        expected = None if phase == "parent" else "background"
        if req.headers.get("X-Adaptive-Class") != expected:
            raise Refused("Plugin class disagrees with production parent/child identity")
        names = {t.get("function", {}).get("name") for t in body.get("tools", [])}
        if not {"read_file", "write_file"} <= names <= {"read_file", "write_file", "patch", "search_files"}:
            raise Refused("Unexpected tool capabilities")
        key = digest(req.content)
        if key in self.seen:
            raise Refused("Duplicate serialized request; no transport retries permitted")
        self.seen.add(key)
        row = {"phase": phase, "url": url, "method": req.method, "class": expected or "normal",
               "model": MODEL, "quality": QUALITY, "body_sha256": key, "messages_sha256": digest(body["messages"]),
               "tools_sha256": digest(body["tools"]), "tool_names": sorted(names), "started_at": time.time()}
        self.rows.append(row); self.steps[phase] += 1
        save(self.run / "wire-observations.json", self.rows)
        response = self.fake_response(req, phase, self.steps[phase] - 1) if self.fixture else self.original(client, req, **kw)
        response.read()
        if response.status_code != 200 or len(response.content) > 4 * 1024 * 1024:
            raise Refused("Non-success or oversized response; no retry")
        data = response.json(); choices = data.get("choices", [])
        if data.get("model") != MODEL or data.get("error") or len(choices) != 1:
            raise Refused("Unexpected response envelope")
        choice = choices[0]; msg = choice.get("message", {}); usage = data.get("usage", {})
        if not self.fixture and response.headers.get("X-Adaptive-Class") != (expected or "normal"):
            raise Refused("Gateway response class disagrees with audited request")
        if msg.get("role") != "assistant" or msg.get("refusal") or choice.get("finish_reason") not in ("stop", "tool_calls"):
            raise Refused("Incomplete or refused response")
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if type(usage.get(field)) is not int or usage[field] < 0:
                raise Refused("Invalid usage")
        if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"] or usage["completion_tokens"] > 10923 or usage["prompt_tokens"] + 10923 + 8 > 65536:
            raise Refused("Response budget contract violated")
        row.update({"finished_at": time.time(), "finish_reason": choice["finish_reason"], "usage": usage,
                    "gateway_request_id": response.headers.get("X-Adaptive-Request-Id"),
                    "response_sha256": digest(response.content), "assistant_sha256": digest(msg)})
        save(self.run / "wire-observations.json", self.rows)
        return response

    def fake_response(self, req, phase, step):
        import httpx
        def call(n, name, args):
            return {"id": f"call-{phase}-{step}-{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        if step == 0:
            calls = [call(0, "read_file", {"path": "orders.csv"})]
            if phase == "child":
                calls.append(call(1, "read_file", {"path": "report.json"}))
        elif step == 1:
            calls = [call(0, "write_file", {"path": "report.json" if phase == "parent" else "verification.json",
                     "content": json.dumps(REPORT if phase == "parent" else VERDICT)})]
        else:
            calls = []
        message = {"role": "assistant", "content": None if calls else "The requested artifact was written and verified."}
        if calls: message["tool_calls"] = calls
        return httpx.Response(200, request=req, headers={"X-Adaptive-Request-Id": f"fixture-{phase}-{step}"}, json={
            "id": f"fixture-{phase}-{step}", "object": "chat.completion", "created": 0, "model": MODEL,
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 3000, "completion_tokens": 150, "total_tokens": 3150}})

def snapshot(agent):
    cc = agent.context_compressor
    actual = {"context_length": cc.context_length, "threshold": cc.threshold_percent,
              "threshold_tokens": cc.threshold_tokens, "reserved_output": cc.max_tokens, "max_tokens": agent.max_tokens}
    if actual != {"context_length": 65536, "threshold": 0.8, "threshold_tokens": 46421,
                  "reserved_output": 10923, "max_tokens": 10923}:
        raise Refused("Actual compressor contract differs: " + repr(actual))
    return actual

