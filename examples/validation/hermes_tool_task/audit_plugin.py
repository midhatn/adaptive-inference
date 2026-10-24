# SPDX-License-Identifier: Apache-2.0
"""Fixture-only public hooks: limit file effects and record actual tool outcomes."""
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()


def register(ctx):
    root = Path(os.environ["ADAPTIVE_TASK_RUN"]).resolve()
    work = root / "work"

    def record(event, data):
        with _lock:
            with (root / "tool-events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"event": event, **data}, ensure_ascii=False, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def before(tool_name="", args=None, session_id="", tool_call_id="", **kw):
        phase = (root / "phase.txt").read_text(encoding="utf-8")
        args = args if isinstance(args, dict) else {}
        raw = args.get("path", "")
        try:
            path = (work / raw).resolve() if isinstance(raw, str) else None
        except (ValueError, OSError):
            path = None
        reads = {work / "orders.csv"}
        if phase == "child":
            reads.add(work / "report.json")
        target = work / ("report.json" if phase == "parent" else "verification.json")
        allowed = phase in {"parent", "child"} and ((tool_name == "read_file" and path in reads) or (
            tool_name == "write_file" and path == target
            and isinstance(args.get("content"), str) and len(args["content"]) <= 4096))
        record("before", {"phase": phase, "name": tool_name, "args": args,
                          "session_id": session_id, "tool_call_id": tool_call_id, "allowed": allowed})
        if not allowed:
            return {"action": "block", "message": "This bounded task permits only its declared file reads and output write."}

    def after(tool_name="", args=None, result=None, session_id="", tool_call_id="", **kw):
        record("after", {"phase": (root / "phase.txt").read_text(encoding="utf-8"),
                         "name": tool_name, "args": args, "result": result,
                         "session_id": session_id, "tool_call_id": tool_call_id,
                         "status": kw.get("status"), "error_type": kw.get("error_type")})

    ctx.register_hook("pre_tool_call", before)
    ctx.register_hook("post_tool_call", after)
