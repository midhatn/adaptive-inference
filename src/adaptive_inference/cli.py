import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from . import __version__
from .adapters import list_profiles
from .config import env_secret, load_config
from .context_budget import plan_context_budget
from .demo import run_demo
from .gateway import create_app


async def doctor(config):
    key = env_secret(config.backend_key_env)
    headers = {"Authorization": "Bearer " + key} if key else {}
    async with ClientSession(timeout=ClientTimeout(total=15), trust_env=False) as client:
        async with client.get(config.backend_url + "/models", headers=headers, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError(f"Backend model discovery failed (HTTP {response.status})")
            limit = 1024 * 1024
            if response.content_length is not None and response.content_length > limit:
                raise ValueError("Backend model discovery exceeds 1 MiB")
            data = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                if len(data) + len(chunk) > limit:
                    raise ValueError("Backend model discovery exceeds 1 MiB")
                data.extend(chunk)
            models = json.loads(data)
            if (not isinstance(models, dict) or not isinstance(models.get("data"), list)
                    or any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
                           or not row["id"].strip() for row in models["data"])):
                raise ValueError("Backend model discovery returned an invalid model list")
    return {"reachable": True, "backend": config.backend_kind,
            "models": [row["id"] for row in models["data"]],
            "inference_tested": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Adaptive scheduling for existing inference servers")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "doctor"):
        sub.add_parser(name).add_argument("--config", required=True)
    sub.add_parser("profiles")
    sub.add_parser("demo").add_argument("--output", type=Path)
    desktop = sub.add_parser("desktop", help="Run an explicit Windows IQ3_S file task, initially paused")
    desktop.add_argument("--profile", type=Path, required=True)
    desktop.add_argument("--run", type=Path, required=True, help="Fresh local state directory")
    desktop.add_argument("--task-spec", type=Path, help="TaskSpec JSON; omit to use the retained orders example")
    desktop.add_argument("--task-inputs", type=Path, help="Directory containing only the task's declared input sources")
    prepare = sub.add_parser("prepare-task", help="Prepare an objective and selected files for the desktop host")
    prepare.add_argument("--destination", type=Path, required=True, help="New task folder under an existing parent")
    objective = prepare.add_mutually_exclusive_group(required=True)
    objective.add_argument("--prompt", help="Original task objective")
    objective.add_argument("--prompt-file", type=Path, help="UTF-8 file containing the original objective")
    prepare.add_argument("--input", type=Path, action="append", default=[], help="Selected input file; repeat for each file")
    prepare.add_argument("--output", default="answer.txt", help="Create-only output filename (default: answer.txt)")
    prepare.add_argument("--format", choices=("text", "json"), default="text", help="Output format (default: text)")
    prepare.add_argument("--max-chars", type=int, default=4096, help="Output character limit, at most 4096")
    budget = sub.add_parser("budget", help="Plan output room from a complete rendered prompt token count")
    for name in ("context-tokens", "prompt-tokens", "required-output-tokens"):
        budget.add_argument("--" + name, type=int, required=True)
    for name in ("reasoning-tokens", "answer-tokens"):
        budget.add_argument("--" + name, type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-task":
            from .task_prepare import prepare_task
            result = prepare_task(args.destination, prompt=args.prompt, prompt_file=args.prompt_file,
                                  inputs=args.input, output=args.output, output_format=args.format,
                                  max_chars=args.max_chars)
            print(json.dumps(result, indent=2))
        elif args.command == "desktop":
            from .desktop.composition import execute
            options = {} if args.task_spec is None and args.task_inputs is None else {
                "task_spec":args.task_spec, "task_inputs":args.task_inputs}
            result = execute(args.profile, args.run, **options)
            print(json.dumps({key: result.get(key) for key in
                              ("clean_stop", "task_completed", "worker_outcome",
                               "semantic_validation", "validated_artifacts")}))
            return 0 if result["clean_stop"] else 1
        elif args.command == "budget":
            plan = plan_context_budget(context_tokens=args.context_tokens, prompt_tokens=args.prompt_tokens,
                        required_output_tokens=args.required_output_tokens,
                        reasoning_tokens=args.reasoning_tokens, answer_tokens=args.answer_tokens)
            print(json.dumps(asdict(plan), indent=2))
            return 0 if plan.status == "ready" else 1
        elif args.command == "profiles":
            print(json.dumps([{"id": p.id, "name": p.name, "base_url": p.base_url,
                               "endpoints": sorted(p.endpoints), "documentation": p.docs_url} for p in list_profiles()], indent=2))
        elif args.command == "demo":
            result = asyncio.run(run_demo())
            text = json.dumps(result, indent=2) + "\n"
            if args.output:
                args.output.write_text(text, encoding="utf-8")
            print(text, end="")
        else:
            config = load_config(args.config)
            if args.command == "doctor":
                print(json.dumps(asyncio.run(doctor(config)), indent=2))
            else:
                web.run_app(create_app(config), host=config.host, port=config.port,
                            access_log=None, handler_cancellation=False, shutdown_timeout=30)
    except (ValueError, TypeError, OSError, ClientError, RuntimeError) as exc:
        print(f"adaptive-inference: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("adaptive-inference: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
