"""Host-selected gateway routes for existing OpenAI-compatible clients.

This module configures a client; it does not send requests, interpret prompts,
translate generation options, grant priority, or control native resources.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit

from .config import env_secret


def generation_options_for_route(value, *, reserved=()):
    """Copy generation settings without SDK identity or transport overrides.

    SDKs merge ``extra_body`` over the selected model and custom headers over
    bearer authentication. Validate those actual merge surfaces as well as
    LangChain's ``model_kwargs`` envelope; do not scan arbitrary tool schemas
    or provider-specific nested data for similarly named fields.
    """
    protected = {
        "model", "model_name", "model_id", "model_info", "base_url", "api_key",
        "openai_api_base", "openai_api_key", "client", "async_client",
        "root_client", "root_async_client", "http_client", "http_async_client",
        "max_retries", "default_query", "extra_query", *reserved,
    }
    protected_headers = {
        "authorization", "proxy-authorization", "api-key", "x-api-key",
        "host", "x-adaptive-class",
    }

    def validate(options, *, body=False):
        if not isinstance(options, Mapping) or any(not isinstance(k, str) for k in options):
            raise ValueError("Generation options and SDK envelopes must be mappings with string keys")
        if set(options) & protected:
            raise ValueError("Generation options cannot override the selected client route or identity")
        if body:
            return
        for name in ("default_headers", "extra_headers"):
            if name in options and options[name] is not None:
                headers = options[name]
                if (not isinstance(headers, Mapping)
                        or any(not isinstance(k, str) or k.strip().lower() in protected_headers
                               for k in headers)):
                    raise ValueError("Generation headers cannot override the selected client route or identity")
        for name in ("model_kwargs", "extra_body"):
            if name in options and options[name] is not None:
                validate(options[name], body=name == "extra_body")

    if value is None:
        return {}
    validate(value)
    return deepcopy(dict(value))


def gateway_client_options(*, base_url: str = "http://127.0.0.1:18100/v1",
                           background: bool = False,
                           api_key_env: str | None = None) -> dict[str, str]:
    """Return ``base_url`` and ``api_key`` for an explicitly selected gateway.

    ``base_url`` is the normal API base, including an optional reverse-proxy
    prefix, or an already-background API base. An already-background route is
    never promoted by ``background=False``. The operator must configure any
    reverse proxy to preserve the two routes. An omitted credential uses the
    harmless ``local`` placeholder accepted by unauthenticated local listeners;
    an explicit missing/empty environment reference fails rather than falling
    back. The returned credential must be treated as secret by the caller.
    """
    if type(background) is not bool:
        raise ValueError("background must be a boolean selected by the host")
    if (not isinstance(base_url, str) or not base_url
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in base_url)
            or "\\" in base_url):
        raise ValueError("base_url must be an HTTP(S) API base without whitespace")
    url = urlsplit(base_url)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username is not None or url.password is not None
            or url.query or url.fragment):
        raise ValueError("base_url must not contain credentials, a query or a fragment")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("base_url has an invalid TCP port")
    path = url.path.rstrip("/")
    if (not path.endswith("/v1") or "%" in path or "//" in path
            or any(part in {".", ".."} for part in path.split("/"))):
        raise ValueError("base_url must end in /v1 with an unambiguous path")
    if background and not path.endswith("/background/v1"):
        path = path[:-3] + "/background/v1"
    key = env_secret(api_key_env) if api_key_env is not None else "local"
    return {"base_url": urlunsplit((url.scheme, url.netloc, path, "", "")),
            "api_key": key}
