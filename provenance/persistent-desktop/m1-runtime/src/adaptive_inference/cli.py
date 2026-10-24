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
    budget = sub.add_parser("budget", help="Plan output room from a complete rendered prompt token count")
    for name in ("context-tokens", "prompt-tokens", "required-output-tokens"):
        budget.add_argument("--" + name, type=int, required=True)
    for name in ("reasoning-tokens", "answer-tokens"):
        budget.add_argument("--" + name, type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "budget":
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
