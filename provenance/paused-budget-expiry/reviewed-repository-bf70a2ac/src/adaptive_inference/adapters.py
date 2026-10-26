"""Documented OpenAI-compatible routes, without model or quality translation.

Profiles describe a server API family, not a guarantee about a loaded model.
The gateway resolves request class before calling ``prepare_request``. Model
loading, chat templates, native resource leases and cancellation remain owned
by each server; these profiles do not pretend to implement native plugins.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EngineProfile:
    id: str
    name: str
    base_url: str
    endpoints: frozenset[str]
    extensions: frozenset[str]
    docs_url: str


_CHAT = frozenset({"/v1/chat/completions", "/v1/models"})
_TEXT = _CHAT | {"/v1/completions"}
_EMBED = _TEXT | {"/v1/embeddings"}
# These controls have project-specific semantics. Refuse a cross-engine leak
# rather than silently deleting a requested budget, routing or quality choice.
STRATA_EXTENSIONS = frozenset({
    "experimental_speed_projection", "strata_checkpoint", "pcie_frac",
    "reasoning_budget_tokens",
})


def _profile(key: str, name: str, port: int, endpoints: frozenset[str],
             docs: str, extensions: frozenset[str] = frozenset()) -> EngineProfile:
    return EngineProfile(key, name, f"http://127.0.0.1:{port}/v1", endpoints,
                         extensions, docs)


ENGINE_PROFILES: Mapping[str, EngineProfile] = MappingProxyType({
    p.id: p for p in (
        _profile("strata", "Strata", 8080, _CHAT,
                 "https://github.com/Niko1221/Strata", STRATA_EXTENSIONS),
        _profile("llamacpp", "llama.cpp", 8080, _EMBED,
                 "https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md"),
        _profile("vllm", "vLLM", 8000, _EMBED,
                 "https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/"),
        _profile("sglang", "SGLang", 30000, _EMBED,
                 "https://docs.sglang.io/docs/basic_usage/openai_api"),
        _profile("ollama", "Ollama", 11434, _EMBED,
                 "https://docs.ollama.com/api/openai-compatibility"),
        _profile("lmstudio", "LM Studio", 1234, _EMBED,
                 "https://lmstudio.ai/docs/developer/openai-compat"),
        _profile("mlx_lm", "MLX-LM", 8080, _TEXT,
                 "https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/server.py"),
        _profile("tgi", "Text Generation Inference", 3000, _TEXT,
                 "https://huggingface.co/docs/text-generation-inference/en/messages_api"),
    )
})
_ALIASES = MappingProxyType({
    "llama.cpp": "llamacpp", "llama-cpp": "llamacpp",
    "lm-studio": "lmstudio", "mlx-lm": "mlx_lm",
    "text-generation-inference": "tgi",
})


def engine_profile(name: str) -> EngineProfile:
    """Resolve a documented profile; never infer support from a model name."""
    if not isinstance(name, str):
        raise ValueError("engine must be a supported profile name")
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return ENGINE_PROFILES[key]
    except KeyError:
        raise ValueError(f"unsupported engine profile: {name!r}") from None


def list_profiles() -> tuple[EngineProfile, ...]:
    return tuple(ENGINE_PROFILES.values())


def prepare_request(engine: str, body: dict) -> dict:
    """Copy a parsed wire body and remove gateway-owned scheduling metadata.

    Call the gateway's class resolver first: it validates both metadata fields
    and rejects conflicts. This function does not select a class or interpret
    text, nested tool arguments or messages. The finite extension guard is not
    a replacement for the upstream API's validation. Unsupported known controls
    fail explicitly; no request cap, message, model or tool is synthesized.
    """
    profile = engine_profile(engine)
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    controls = set(body) & STRATA_EXTENSIONS
    unsupported = controls - profile.extensions
    if profile.id != "strata":
        unsupported |= {key for key in body if isinstance(key, str)
                        and key.startswith("strata_") and key != "strata_scheduling"}
    if unsupported:
        fields = ", ".join(sorted(unsupported))
        raise ValueError(f"{profile.name} profile does not support Strata controls: {fields}")
    prepared = deepcopy(body)
    prepared.pop("adaptive_scheduling", None)
    prepared.pop("strata_scheduling", None)
    return prepared
