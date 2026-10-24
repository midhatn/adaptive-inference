# SPDX-License-Identifier: Apache-2.0
"""Bounded real Hermes/plugin file task. This never starts or stops a model service."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SDK = PYTHON = PLUGIN_SOURCE = None
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


def configure_inputs(sdk, python, plugin, gateway, model):
    """Explicit paths only; keep the measured IQ3_S quality contract fixed."""
    global SDK, PYTHON, PLUGIN_SOURCE, BASE, MODEL
    if model != "qwen3.8-flash-next-iq3_s-adaptive-media-beta":
        raise ValueError("This reproduction permits only the qualified IQ3_S model ID")
    if not isinstance(gateway, str) or any(c.isspace() or ord(c) < 32 or c == "\\" for c in gateway):
        raise ValueError("Invalid gateway URL")
    url = urlsplit(gateway)
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.username is not None
            or url.password is not None or url.path != "/v1" or url.query or url.fragment
            or url.port is None or not 1 <= url.port <= 65535):
        raise ValueError("Gateway must be http://127.0.0.1:PORT/v1")
    SDK, PYTHON, PLUGIN_SOURCE = (Path(p).resolve(strict=True) for p in (sdk, python, plugin))
    if not SDK.is_dir() or not PYTHON.is_file() or not PLUGIN_SOURCE.is_dir():
        raise ValueError("Source/plugin directories and an existing interpreter are required")
    BASE, MODEL = gateway, model


def load_plan(run):
    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    if (plan.get("sdk_revision") != SDK_REV or plan.get("quality") != QUALITY
            or plan.get("max_posts") != 16 or plan.get("max_phase_posts") != 8
            or plan.get("wall_seconds") != 900):
        raise ValueError("Prepared quality, source or bounds changed")
    configure_inputs(plan["sdk"], plan["python"], plan["plugin_source"], plan["gateway"], plan["model"])
    for path, sha in plan["pins"].items():
        if digest(Path(path).read_bytes()) != sha:
            raise RuntimeError("A pinned input changed")
    return plan


def prepare(run):
    if os.name != "nt":
        raise RuntimeError("The owned process watchdog is qualified only on Windows")
    for name, sha in {"__init__.py": "2a65d81edb39bb13623081ae761ab9bd086d43e6db3717bcc9b9bc3c1fbc05aa",
                      "plugin.yaml": "d2f2dcee2463eb4b02d8a15c1712fc4cbf37c47fe174544c8af282ba9c3a60ea"}.items():
        if digest((PLUGIN_SOURCE / name).read_bytes()) != sha:
            raise ValueError("Routing plugin differs from the qualified source")
    if git("rev-parse", "HEAD") != SDK_REV or git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Hermes source pin changed")
    run.mkdir(parents=True, exist_ok=False)
    work = run / "work"; work.mkdir()
    (work / "orders.csv").write_text(CSV, encoding="utf-8", newline="\n")
    (run / "phase.txt").write_text("parent", encoding="utf-8")
    home = run / "home"; home.mkdir()
    plugin = home / "plugins" / PLUGIN
    shutil.copytree(PLUGIN_SOURCE, plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    audit = home / "plugins" / AUDIT; audit.mkdir()
    shutil.copyfile(HERE / "audit_plugin.py", audit / "__init__.py")
    (audit / "plugin.yaml").write_text("name: bounded-file-audit\nversion: '0.1.0'\ndescription: Local bounded task audit.\nprovides_hooks: [pre_tool_call, post_tool_call]\n", encoding="utf-8")
    save(home / "config.yaml", config(work))  # JSON is valid YAML; no serializer dependency.
    prompts = {
        "parent": "Read orders.csv with read_file. Compute quantity times unit_cents for each data row, "
                  "aggregate by item, and write report.json using write_file. The JSON must have exactly "
                  "rows (data row count), units (sum of quantities), total_cents, and by_item (item-to-cents map). "
                  "Use integers. Use only read_file and write_file, do not use shell or other tools. "
                  "Finish only after the write succeeds. Reply briefly describing the created artifact.",
        "child": "Independently read orders.csv and report.json with read_file. Check every count, total and "
                 "item aggregation against the source. If all match, use write_file to create verification.json "
                 "with exactly verified:true, rows, units, total_cents using the independently checked integers. "
                 "If any check fails, do not write verification.json; explain the failure. Use only read_file "
                 "and write_file. Finish after a successful verified write or a clear failure."}
    save(run / "original-task.json", prompts)
    pin_paths = [HERE / "run_task.py", HERE / "audit_plugin.py", HERE / "owned_job_windows.py",
                 run / "original-task.json", home / "config.yaml", work / "orders.csv"]
    pin_paths += sorted(p for p in (home / "plugins").rglob("*") if p.is_file())
    save(run / "plan.json", {"sdk": str(SDK), "sdk_revision": SDK_REV, "python": str(PYTHON),
         "plugin_source": str(PLUGIN_SOURCE), "gateway": BASE, "model": MODEL, "quality": QUALITY, "max_posts": 16, "max_phase_posts": 8,
         "wall_seconds": 900, "pins": {str(p): digest(p.read_bytes()) for p in pin_paths}})
    print(json.dumps({"prepared": str(run), "model_started": False}))


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


def gateway_metrics(run, label, expected_instance, rows):
    import httpx
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get(BASE.removesuffix("/v1") + "/metrics")
        response.raise_for_status(); data = response.json()
    save(run / ("gateway-" + label + ".json"), data)
    scheduler = data.get("scheduler", {})
    if data.get("service") != "adaptive-inference" or not data.get("instance") or data.get("backend") != "strata":
        raise Refused("Unexpected gateway identity")
    if expected_instance is not None and data["instance"] != expected_instance:
        raise Refused("Gateway restarted during the task")
    if scheduler.get("active") or scheduler.get("pending") != 0 or scheduler.get("backend_completion_uncertain") or scheduler.get("closing"):
        raise Refused("Gateway not idle and certain at task boundary")
    history = data.get("history", [])
    if len(history) != len(rows) or scheduler.get("completed") != len(rows):
        raise Refused("Gateway was reused or received unaccounted work")
    for observed, sent in zip(history, rows):
        if observed.get("request_id") != sent.get("gateway_request_id") or observed.get("class") != sent["class"] or observed.get("status") != 200 or observed.get("backend_completion_uncertain") or observed.get("client_disconnected"):
            raise Refused("Gateway history does not match actual SDK responses")
    return data["instance"]


def worker(run, fixture):
    load_plan(run)
    if git("rev-parse", "HEAD") != SDK_REV or git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("SDK source changed")
    sys.path.insert(0, str(SDK))
    import httpx
    boundary = Boundary(run, fixture)
    boundary.original = httpx.Client.send
    httpx.Client.send = lambda client, req, **kw: boundary.send(client, req, **kw)
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_pair, real_resolve = socket.socketpair, socket.getaddrinfo
    local_pair = threading.local()
    def network(sock, address, *, ex=False):
        internal_pair = getattr(local_pair, "active", False) and isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")
        if not internal_pair and (fixture or not isinstance(address, tuple) or address[:2] != ("127.0.0.1", urlsplit(BASE).port)):
            raise OSError("Only declared gateway loopback connections allowed")
        return (real_connect_ex if ex else real_connect)(sock, address)
    def pair(*args, **kw):
        # Windows asyncio uses a loopback socketpair for its own wakeup pipe.
        # Permit only the stdlib socketpair call on this thread, not arbitrary listeners.
        local_pair.active = True
        try: return real_pair(*args, **kw)
        finally: local_pair.active = False
    def resolve(host, *args, **kw):
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise OSError("External DNS disabled for this bounded task")
        return real_resolve(host, *args, **kw)
    socket.socket.connect = lambda sock, address: network(sock, address)
    socket.socket.connect_ex = lambda sock, address: network(sock, address, ex=True)
    socket.socketpair = pair; socket.getaddrinfo = resolve
    parent = child = None
    result = {"passed": False, "fixture": fixture, "model": MODEL, "quality": QUALITY,
              "sdk_revision": SDK_REV, "scope": "actual Hermes file tools and host-created production child; serial routing only"}
    try:
        instance = None if fixture else gateway_metrics(run, "before", None, [])
        from run_agent import AIAgent
        from tools.delegate_tool import _build_child_agent, _run_child_lifecycle
        from hermes_cli.plugins import get_plugin_manager
        prompts = json.loads((run / "original-task.json").read_text(encoding="utf-8"))
        parent = AIAgent(base_url=BASE, api_key="local-no-key", provider="custom:adaptive", model=MODEL,
            api_mode="chat_completions", max_iterations=8, enabled_toolsets=["file"], quiet_mode=True,
            platform="cli", skip_context_files=True, skip_memory=True, skip_background_review=True,
            max_tokens=10923, reasoning_config={"enabled": True, "effort": "high"},
            request_overrides={"extra_body": QUALITY}, cwd=str(run / "work"), session_id="bounded-parent-" + run.name)
        mgr = get_plugin_manager(); info = mgr._plugins[PLUGIN]
        if not info.enabled or info.error: raise Refused("Optional routing plugin did not load")
        result["parent_context"] = snapshot(parent)
        parent_outcome = parent.run_conversation(prompts["parent"])
        result["parent"] = {k: parent_outcome.get(k) for k in ("completed", "failed", "interrupted")}
        if result["parent"].get("completed") is not True or result["parent"].get("failed") or result["parent"].get("interrupted"):
            raise Refused("Parent did not complete naturally")
        if digest(json.loads((run / "work" / "report.json").read_text(encoding="utf-8"))) != digest(REPORT):
            raise Refused("Parent artifact failed exact task acceptance")
        if not fixture: gateway_metrics(run, "parent", instance, boundary.rows)
        (run / "phase.txt").write_text("child", encoding="utf-8")
        child = _build_child_agent(0, prompts["child"], None, ["file"], None, 8, 1, parent)
        result["child_context"] = snapshot(child)
        child_outcome = _run_child_lifecycle(0, prompts["child"], child=child, parent_agent=parent)
        result["child"] = {k: child_outcome.get(k) for k in ("status", "exit_reason")}
        if result["child"].get("status") != "completed" or result["child"].get("exit_reason") != "completed":
            raise Refused("Child did not complete naturally")
        if digest(json.loads((run / "work" / "verification.json").read_text(encoding="utf-8"))) != digest(VERDICT):
            raise Refused("Child artifact failed exact task acceptance")
        if (run / "work" / "orders.csv").read_text(encoding="utf-8") != CSV:
            raise Refused("Original task source changed")
        events = [json.loads(line) for line in (run / "tool-events.jsonl").read_text(encoding="utf-8").splitlines()]
        if any(e["event"] == "before" and not e["allowed"] for e in events): raise Refused("Out-of-scope tool attempted")
        for phase in ("parent", "child"):
            after = [e for e in events if e["event"] == "after" and e["phase"] == phase]
            if any(e["status"] != "ok" for e in after): raise Refused("A tool result was unsuccessful")
            for path in (["orders.csv"] if phase == "parent" else ["orders.csv", "report.json"]):
                reads = [e for e in after if e["name"] == "read_file" and Path(e["args"]["path"]).name == path]
                if not any(json.loads(e["result"]).get("truncated") is False for e in reads):
                    raise Refused("Actual complete source/artifact read missing")
            writes = [e for e in after if e["name"] == "write_file"]
            if not any(json.loads(e["result"]).get("verified") is True for e in writes):
                raise Refused("Actual verified native file write missing")
            if not any(r["phase"] == phase and r["finish_reason"] == "stop" for r in boundary.rows):
                raise Refused("Natural stop missing")
        result.update(passed=True, artifacts={p.name: digest(p.read_bytes()) for p in (run / "work").iterdir() if p.is_file()},
                      wire_count=len(boundary.rows), tool_events=len(events))
        if not fixture:
            result["gateway_instance"] = gateway_metrics(run, "after", instance, boundary.rows)
    except BaseException as exc:
        result.update(passed=False, error=type(exc).__name__ + ": " + str(exc), traceback=traceback.format_exc())
    finally:
        for agent in (child, parent):
            if agent is not None:
                try: agent.close()
                except BaseException as exc:
                    result["passed"] = False
                    result.setdefault("close_errors", []).append(str(exc))
        httpx.Client.send = boundary.original
        socket.socket.connect = real_connect; socket.socket.connect_ex = real_connect_ex
        socket.socketpair = real_pair; socket.getaddrinfo = real_resolve
        save(run / "result.json", result)
    return 0 if result["passed"] else 1


def supervise(run, fixture):
    if os.name != "nt":
        raise RuntimeError("The owned process watchdog is qualified only on Windows")
    load_plan(run)
    (run / "RUN-CLAIM").open("x").close()
    spec = importlib.util.spec_from_file_location("owned_task_job", HERE / "owned_job_windows.py")
    job = importlib.util.module_from_spec(spec); spec.loader.exec_module(job)
    job.contain_current_process()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "OPENAI_", "ANTHROPIC_", "STRATA_")) and k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(HERMES_HOME=str(run / "home"), HERMES_BUNDLED_PLUGINS=str(run / "empty-bundled"),
               ADAPTIVE_TASK_RUN=str(run), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               LITELLM_LOCAL_MODEL_COST_MAP="True")
    command = [str(PYTHON), "-I", "-B", str(HERE / "run_task.py"), "worker", "--run", str(run)]
    if fixture: command.append("--fixture")
    started = time.time(); timed_out = False
    with (run / "stdout.log").open("wb") as out, (run / "stderr.log").open("wb") as err:
        process = subprocess.Popen(command, env=env, cwd=run / "work", stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try: code = process.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timed_out = True; process.kill(); code = process.wait(timeout=10)
    deadline = time.monotonic() + (0 if timed_out else 10)
    while not timed_out and time.monotonic() < deadline and job.active_process_ids() - {os.getpid()}:
        time.sleep(0.1)
    remaining = sorted(job.active_process_ids() - {os.getpid()})
    save(run / "outer-result.json", {"exit_code": code, "timed_out": timed_out, "elapsed_s": time.time() - started,
         "owned_job_remaining": remaining, "owned_children_empty": not remaining,
         "timeout_cleanup": "owned job closes when this supervisor exits; root must separately drain and stop backend"})
    return 1 if timed_out or remaining else code


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("mode", choices=["prepare", "run", "worker"])
    p.add_argument("--run", type=Path, required=True); p.add_argument("--fixture", action="store_true")
    p.add_argument("--hermes-source", type=Path)
    p.add_argument("--python", type=Path)
    p.add_argument("--plugin", type=Path)
    p.add_argument("--gateway-url", default=BASE)
    p.add_argument("--model", default=MODEL)
    a = p.parse_args(); run = a.run.resolve()
    if a.mode == "prepare":
        if any(v is None for v in (a.hermes_source, a.python, a.plugin)):
            p.error("prepare requires --hermes-source, --python and --plugin")
        configure_inputs(a.hermes_source, a.python, a.plugin, a.gateway_url, a.model)
        prepare(run)
    elif a.mode == "worker": raise SystemExit(worker(run, a.fixture))
    else: raise SystemExit(supervise(run, a.fixture))
