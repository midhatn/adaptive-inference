"""Eight bounded real-model requests through a new gateway; no model management.

The configured backend must already be running and privately owned by the
operator. This checks arithmetic answers and timing engagement, not speed gains,
tool workflows, or general answer quality. It makes no generation retry.
"""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

from aiohttp import ClientSession, ClientTimeout

from adaptive_inference.config import load_config, env_secret
from adaptive_inference.demo import start_app
from adaptive_inference.gateway import GATEWAY, create_app


def require(condition, message):
    if not condition:
        raise ValueError(message)


async def check(config, model, generation, report):
    if not isinstance(generation, dict) or any(key in generation for key in
            ("model", "messages", "prompt", "stream", "adaptive_scheduling", "strata_scheduling")):
        raise ValueError("Generation settings must not override model, prompt, stream or classification")
    app = create_app(replace(config, host="127.0.0.1"))
    runner, url = await start_app(app)
    gateway = app[GATEWAY]
    rows = report["requests"]
    headers = {"Authorization": "Bearer " + env_secret(config.api_key_env)} if config.api_key_env else {}
    try:
        async with ClientSession(timeout=ClientTimeout(total=120), headers=headers) as client:
            async with client.get(url + "/v1/models") as response:
                response.raise_for_status()
                models = await response.json()
                if model not in {row["id"] for row in models["data"]}:
                    raise ValueError("Requested model was not advertised by this backend")
            for work_class, prompt, expected in (
                ("normal", "Calculate 19 times 23. Reply with only the integer answer.", 437),
                ("background", "Calculate 17 times 29. Reply with only the integer answer.", 493),
            ):
                for repetition in range(4):
                    body = {**generation, "model": model, "stream": False,
                            "messages": [{"role": "user", "content": prompt}]}
                    route = "/v1" if work_class == "normal" else "/background/v1"
                    started = time.monotonic()
                    report["generation_attempts"] += 1
                    async with client.post(url + route + "/chat/completions", json=body) as response:
                        if response.status != 200:
                            report["last_http_status"] = response.status
                            report["last_error_body"] = (await response.text())[:2048]
                        response.raise_for_status()
                        answer = await response.json()
                    choices = answer.get("choices", [])
                    report["response_answers"].append(answer)
                    require(not answer.get("error"), "Backend returned an error envelope")
                    require(len(choices) == 1 and choices[0].get("finish_reason") == "stop", "Natural completion required")
                    message = choices[0].get("message", {})
                    content = message.get("content", "")
                    require(isinstance(content, str) and content.strip() == str(expected), "Exact arithmetic answer failed")
                    require(message.get("role") == "assistant" and not message.get("tool_calls") and not message.get("refusal"), "Unexpected role, tool or refusal")
                    require(answer.get("model") == model, "Model identity changed")
                    row = gateway.history[-1]
                    require(row["class"] == work_class and row["trained"] and row["status"] == 200, "Completion was not learned")
                    require(row["prediction"]["samples"] == repetition, "Observation grouping failed")
                    require((row["prediction"]["reason"] == "measured") == (repetition == 3), "Wrong learning threshold")
                    result = {"class": work_class, "repetition": repetition + 1, "correct": True,
                              "finish_reason": "stop", "prediction": row["prediction"],
                              "execution_s": row["execution_s"], "elapsed_s": time.monotonic() - started,
                              "usage": answer.get("usage", {})}
                    rows.append(result)
                    print(json.dumps({"completed": len(rows), "class": work_class,
                                      "prior_samples": repetition}), flush=True)
        status = gateway.scheduler.status()
        require(not status["active"] and status["pending"] == 0 and not status["backend_completion_uncertain"], "Gateway did not drain")
        require(gateway.costs.status()["observations"] == 8, "Missing observations")
        report.update({"passed": True, "scope": "real model through portable gateway; serial arithmetic and timing feedback only",
                "engine_profile": config.backend_kind, "backend_revision": config.backend_revision,
                "model": model, "generation": generation, "requests": rows,
                "scheduler": status, "cost_model": gateway.costs.status(),
                "comparative_performance_qualified": False, "native_resource_controls_qualified": False})
        return report
    finally:
        report["gateway_history"] = list(gateway.history)
        report["final_scheduler"] = gateway.scheduler.status()
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--generation-json", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    generation = json.loads(Path(args.generation_json).read_text(encoding="utf-8"))
    result = {"passed": False, "generation_attempts": 0, "requests": [], "response_answers": []}
    try:
        asyncio.run(asyncio.wait_for(check(config, args.model, generation, result), timeout=600))
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "observations": len(result["requests"])}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
