"""Compose an explicit OpenClaw main/subagent gateway configuration fragment.

No installed configuration is read or written. The caller supplies the existing
provider and agent defaults, including their chosen quality and fallback policy.
"""
from copy import deepcopy
import json
import re

from adaptive_inference.client_routing import gateway_client_options


def build_config(provider: dict, agent_defaults: dict, *, provider_id: str,
                 model_id: str, background_provider_id: str) -> dict:
    """Clone one configured gateway provider and route default children to it.

    This returns a reviewable fragment, not an in-place merger. Per-agent and
    per-spawn choices still take precedence. An already different child model,
    alias collision, restrictive unapproved model policy or ambiguous transport
    is refused instead of silently replaced.
    """
    if not isinstance(provider, dict) or not isinstance(agent_defaults, dict):
        raise ValueError("provider and agent_defaults must be dictionaries")
    for name in (provider_id, background_provider_id):
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise ValueError("Provider IDs must be explicit lowercase identifiers")
    if provider_id == background_provider_id:
        raise ValueError("Normal and background provider IDs must differ")
    if (not isinstance(model_id, str) or not model_id or model_id != model_id.strip()
            or len(model_id) > 512 or "@" in model_id
            or any(ord(c) < 32 or ord(c) == 127 for c in model_id)):
        raise ValueError("model_id must be an explicit unambiguous existing model ID")
    # Reject non-JSON values/NaNs before constructing a partial result.
    try:
        json.dumps([provider, agent_defaults], allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Configuration must contain finite JSON values") from exc
    if provider.get("api") != "openai-completions":
        raise ValueError("The gateway integration requires explicit openai-completions")
    models = provider.get("models")
    if (not isinstance(models, list)
            or sum(isinstance(row, dict) and row.get("id") == model_id for row in models) != 1):
        raise ValueError("model_id must identify exactly one supplied provider model row")
    base = provider.get("baseUrl")
    normal_url = gateway_client_options(base_url=base)["base_url"]
    background_url = gateway_client_options(base_url=base, background=True)["base_url"]
    if normal_url == background_url:
        raise ValueError("The supplied provider is already a background route")
    request = provider.get("request", {})
    if not isinstance(request, dict):
        raise ValueError("provider.request must be an object")
    for headers in (provider.get("headers", {}), request.get("headers", {})):
        if not isinstance(headers, dict) or any(
                isinstance(k, str) and k.lower() == "x-adaptive-class" for k in headers):
            raise ValueError("Explicit routing headers require manual configuration review")
    normal_ref = provider_id + "/" + model_id
    background_ref = background_provider_id + "/" + model_id
    primary = agent_defaults.get("model")
    primary_ref = primary.get("primary") if isinstance(primary, dict) else primary
    if primary_ref != normal_ref:
        raise ValueError("Supplied default model must select the supplied normal provider/model")
    children = agent_defaults.get("subagents", {})
    if not isinstance(children, dict):
        raise ValueError("subagents must be an object")
    selected = children.get("model", primary)
    selected_ref = selected.get("primary") if isinstance(selected, dict) else selected
    if selected_ref != normal_ref:
        raise ValueError("An explicit different or incomplete child model must be reviewed")
    model_settings = agent_defaults.get("models", {})
    if not isinstance(model_settings, dict) or background_ref in model_settings:
        raise ValueError("Existing background model settings must be reviewed rather than overwritten")
    policy = agent_defaults.get("modelPolicy", {})
    if not isinstance(policy, dict):
        raise ValueError("modelPolicy must be an object")
    allowed = policy.get("allow", [])
    if not isinstance(allowed, list) or (allowed and background_ref not in allowed):
        raise ValueError("An existing restrictive model policy must explicitly allow the background route")

    defaults = deepcopy(agent_defaults)
    defaults.setdefault("subagents", {})["model"] = (
        {**deepcopy(selected), "primary": background_ref}
        if isinstance(selected, dict) else background_ref)
    if normal_ref in model_settings:
        entry = deepcopy(model_settings[normal_ref])
        if not isinstance(entry, dict):
            raise ValueError("Existing model settings must be an object")
        # Copy generation/runtime settings without creating an ambiguous picker
        # alias that names two distinct routes. The new exact ref remains usable.
        entry.pop("alias", None)
        defaults.setdefault("models", {})[background_ref] = entry
    background = deepcopy(provider)
    background["baseUrl"] = background_url
    return {"models": {"providers": {provider_id: deepcopy(provider),
                                     background_provider_id: background}},
            "agents": {"defaults": defaults}}


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Existing JSON config to inspect")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--background-provider", required=True)
    parser.add_argument("--output", type=Path, required=True, help="NEW JSON fragment file")
    args = parser.parse_args()
    try:
        config = json.loads(args.input.read_text(encoding="utf-8"))
        providers = config["models"]["providers"]
        if args.background_provider in providers:
            raise ValueError("The background provider ID already exists; select a new ID")
        fragment = build_config(providers[args.provider], config["agents"]["defaults"],
            provider_id=args.provider, model_id=args.model, background_provider_id=args.background_provider)
        content = json.dumps(fragment, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Configuration preparation refused: {type(exc).__name__}. Check inputs and output path.\n")
    print("Prepared configuration fragment; review and merge it using OpenClaw's supported config tools.")


if __name__ == "__main__":
    main()
