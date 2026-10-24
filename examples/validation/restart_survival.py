"""Real process-restart acceptance with deterministic callbacks and a JSON artifact.

Run with a NEW --output directory. No model, network service or GPU is used.
This checks process death, not physical power loss or exactly-once external effects.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from adaptive_inference.feedback import Verdict, resume_with_feedback
from adaptive_inference.task_store import ReconciliationRequired, TaskBusyError, TaskStore


PROMPT = ("Create inventory.json as a UTF-8 JSON object with rows alpha=13, beta=17, "
          "gamma=12 and total equal to the sum of those quantities. Preserve the row "
          "names and quantities exactly. Acceptance requires the independently computed total 42.")
FEEDBACK = "total must equal the sum of row quantities (42), observed 41"
IDENTITY = {"generator": "deterministic-inventory-v1", "validator": "inventory-arithmetic-v1"}
ROWS = [{"name": name, "quantity": amount} for name, amount in
        (("alpha", 13), ("beta", 17), ("gamma", 12))]


def _write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _append(path, value):
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _callbacks(folder):
    def generate(messages):
        _require(messages[0] == {"role": "user", "content": PROMPT}, "Original prompt changed")
        corrected = any(FEEDBACK in row.get("content", "") for row in messages[1:])
        _append(folder / "calls.jsonl", {"kind": "generation", "feedback_seen": corrected,
                "original_prompt_sha256": hashlib.sha256(messages[0]["content"].encode()).hexdigest()})
        return json.dumps({"rows": ROWS, "total": 42 if corrected else 41})

    def validate(output):
        # Writing the real draft artifact is inside the journaled validation
        # operation. A crash here is ambiguous and must not be replayed silently.
        artifact = json.loads(output)
        _write_json(folder / "inventory.json", artifact)
        actual = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
        _require(actual["rows"] == ROWS, "Inventory rows changed")
        accepted = actual["total"] == sum(row["quantity"] for row in actual["rows"])
        _append(folder / "calls.jsonl", {"kind": "validation", "accepted": accepted})
        return Verdict(accepted, "" if accepted else FEEDBACK)

    return generate, validate


async def _worker(folder, mode):
    store = TaskStore(folder / "tasks.sqlite3")
    task_id = "external-effect" if mode.startswith("effect") else "inventory"
    if mode == "lock-probe":
        try:
            with store.claim(task_id, expected_revision=store.load(task_id).revision, owner_id="contender"):
                raise AssertionError("A concurrent owner acquired the task")
        except TaskBusyError:
            _write_json(folder / "lock-probe.json", {"blocked": True})
        return
    if mode == "effect-pause":
        with store.claim(task_id, expected_revision=store.load(task_id).revision, owner_id="effect-owner") as owned:
            checkpoint = owned.begin_operation("effect", details={"action": "append synthetic delivery"},
                                               expected_revision=owned.checkpoint.revision)
            _append(folder / "deliveries.jsonl", {"operation_id": checkpoint.operation["id"],
                    "delivery": "inventory accepted notification"})
            _write_json(folder / "effect-ready.json", {"operation_id": checkpoint.operation["id"],
                        "revision": checkpoint.revision, "effect_written": True})
            threading.Event().wait()
        return
    if mode == "effect-resume":
        def forbidden(*args):
            raise AssertionError("Interrupted external effect was replayed")
        try:
            await resume_with_feedback(store, task_id, forbidden, forbidden, identity=IDENTITY)
        except ReconciliationRequired:
            checkpoint = store.load(task_id)
            _require(checkpoint.requires_reconciliation, "Ambiguity was lost")
            _write_json(folder / "effect-resume.json", {"blocked": True,
                        "operation_id": checkpoint.operation["id"], "revision": checkpoint.revision})
            return
        raise AssertionError("Interrupted effect resumed without reconciliation")

    def on_checkpoint(checkpoint):
        state = checkpoint.state
        if (mode == "safe-pause" and state.get("phase") == "ready"
                and state["attempts"] == 1 and state["feedback"]):
            _require(checkpoint.operation is None, "Pause is not a safe committed boundary")
            _require(state["feedback"] == [FEEDBACK], "Feedback not committed")
            _write_json(folder / "safe-ready.json", {"revision": checkpoint.revision,
                        "attempts": state["attempts"], "feedback": state["feedback"]})
            threading.Event().wait()

    generate, validate = _callbacks(folder)
    if mode == "completed-resume":
        def forbidden(*args):
            raise AssertionError("Completed task invoked a callback again")
        generate = validate = forbidden
    result = await resume_with_feedback(store, task_id, generate, validate,
                                        identity=IDENTITY, on_checkpoint=on_checkpoint)
    _write_json(folder / (mode + ".json"), {"accepted": result.accepted,
                "attempts": result.attempts, "feedback": list(result.feedback)})


def run_restart_demo(output):
    """Return a receipt; fail rather than overwrite an existing output directory."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    children = []
    report = {"passed": False, "scope": "real process termination and restart; deterministic callbacks",
              "physical_power_loss_tested": False, "model_used": False,
              "external_effect_exactly_once_claim": False}
    repository = Path(__file__).resolve().parents[2]

    def launch(mode):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repository / "src") + os.pathsep + env.get("PYTHONPATH", "")
        log = (folder / (mode + ".log")).open("ab")
        # A Windows venv launcher may be a redirector. Retain the actual worker
        # interpreter handle so terminating it releases the advisory owner lock.
        executable = getattr(sys, "_base_executable", None) or sys.executable
        process = subprocess.Popen([executable, "-B", str(Path(__file__).resolve()),
                                    "--worker", mode, "--output", str(folder)],
                                   cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        children.append((process, log, mode))
        return process

    def finish(process):
        code = process.wait(timeout=15)
        _require(code == 0, f"Worker exited with {code}; see its retained log")

    def wait_marker(process, name):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (folder / name).exists():
                return json.loads((folder / name).read_text(encoding="utf-8"))
            _require(process.poll() is None, "Worker exited before its committed readiness marker")
            time.sleep(.02)
        raise TimeoutError("Worker did not reach its committed checkpoint")

    def terminate(process):
        _require(process.poll() is None, "Expected a living paused worker")
        process.kill()
        return process.wait(timeout=10)

    failure = None
    try:
        store = TaskStore(folder / "tasks.sqlite3")
        store.create("inventory", PROMPT, max_attempts=3, metadata=IDENTITY)
        paused = launch("safe-pause")
        marker = wait_marker(paused, "safe-ready.json")
        finish(launch("lock-probe"))
        _require(json.loads((folder / "lock-probe.json").read_text())["blocked"], "Owner lock failed")
        exit_code = terminate(paused)
        interrupted = store.load("inventory")
        _require(interrupted.prompt == PROMPT and interrupted.state["feedback"] == [FEEDBACK],
                 "Prompt or acceptance feedback did not survive")
        _require(interrupted.operation is None, "Safe checkpoint has an in-flight operation")
        finish(launch("safe-resume"))
        finished = store.load("inventory")
        artifact = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
        _require(finished.state["status"] == "accepted" and finished.state["attempts"] == 2,
                 "Corrected task did not finish after exactly two attempts")
        _require(artifact["rows"] == ROWS and artifact["total"] == 42, "Final artifact is incorrect")
        calls = _records(folder / "calls.jsonl")
        _require([row["kind"] for row in calls] == ["generation", "validation"] * 2,
                 "Unexpected callback repetition")
        _require(calls[0]["feedback_seen"] is False and calls[2]["feedback_seen"] is True,
                 "Corrective generation did not consume saved feedback")
        finish(launch("completed-resume"))
        _require(_records(folder / "calls.jsonl") == calls, "Completed task repeated work")
        report["safe_checkpoint"] = {"passed": True, "killed_worker_exit_code": exit_code,
            "saved_revision": marker["revision"], "concurrent_owner_blocked": True,
            "original_prompt_retained": finished.prompt == PROMPT,
            "original_prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "feedback_retained": finished.state["feedback"] == [FEEDBACK], "attempts": 2,
            "artifact_sha256": hashlib.sha256((folder / "inventory.json").read_bytes()).hexdigest(),
            "artifact_total": artifact["total"], "completed_resume_replayed_callbacks": False}

        store.create("external-effect", PROMPT, max_attempts=3, metadata=IDENTITY)
        effect = launch("effect-pause")
        effect_marker = wait_marker(effect, "effect-ready.json")
        effect_exit = terminate(effect)
        before = (folder / "deliveries.jsonl").read_bytes()
        for _ in range(2):
            finish(launch("effect-resume"))
            _require((folder / "deliveries.jsonl").read_bytes() == before, "External effect repeated")
        blocked = store.load("external-effect")
        _require(blocked.requires_reconciliation and blocked.operation["id"] == effect_marker["operation_id"],
                 "Interrupted effect identity or reconciliation requirement changed")
        _require(len(_records(folder / "deliveries.jsonl")) == 1, "Unexpected delivery count")
        report["interrupted_effect"] = {"passed": True, "killed_worker_exit_code": effect_exit,
            "operation_id": effect_marker["operation_id"], "resume_attempts": 2,
            "requires_reconciliation": True, "external_deliveries": 1,
            "automatic_replay": False, "original_prompt_retained": blocked.prompt == PROMPT}
        report["passed"] = True
    except Exception as exc:
        failure = exc
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for process, log, _mode in children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            log.close()
        report["workers"] = [{"mode": mode, "pid": process.pid, "exit_code": process.returncode}
                             for process, _log, mode in children]
        report["all_owned_workers_exited"] = all(process.poll() is not None for process, _, _ in children)
        _write_json(folder / "result.json", report)
    if failure is not None:
        raise RuntimeError(f"Restart acceptance failed; receipt: {folder / 'result.json'}") from failure
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory for the controller")
    parser.add_argument("--worker", choices=("safe-pause", "safe-resume", "completed-resume", "lock-probe",
                                             "effect-pause", "effect-resume"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        asyncio.run(_worker(args.output, args.worker))
    else:
        print(json.dumps(run_restart_demo(args.output), indent=2))


if __name__ == "__main__":
    main()
