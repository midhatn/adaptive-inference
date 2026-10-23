"""Strict, portable configuration. Credentials are environment references only."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import os
import re
from urllib.parse import urlsplit


def finite(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return float(value)


def section(value, allowed, name):
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"Unknown or invalid {name} settings")
    return value


def env_secret(name):
    if name is None:
        return None
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Credential configuration must name an environment variable")
    value = os.environ.get(name)
    if not value or any(c in value for c in "\r\n"):
        raise ValueError(f"Set the credential environment variable {name}")
    return value


def env_name(name):
    """Validate a credential reference without requiring a secret at parse time."""
    if name is not None and (not isinstance(name, str)
                            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)):
        raise ValueError("Credential configuration must name an environment variable")


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 18100
    backend_kind: str = "llamacpp"
    backend_url: str = "http://127.0.0.1:8080/v1"
    backend_key_env: str | None = None
    api_key_env: str | None = None
    backend_revision: str = "operator-managed"
    default_class: str = "normal"
    max_pending: int = 16
    queue_timeout_s: float = 300
    normal_boost_s: float = 10
    max_cost_delay_s: float = 30
    upstream_timeout_s: float = 900
    upstream_read_timeout_s: float = 120
    min_available_ram_gib: float = 0
    max_body_bytes: int = 8 * 1024 * 1024
    max_response_bytes: int = 32 * 1024 * 1024

    @classmethod
    def from_dict(cls, raw):
        section(raw, {"listen", "backend", "scheduler", "resources", "limits", "default_class"}, "root")
        listen = section(raw.get("listen", {}), {"host", "port", "api_key_env"}, "listen")
        backend = section(raw.get("backend", {}), {"kind", "base_url", "api_key_env", "revision"}, "backend")
        scheduler = section(raw.get("scheduler", {}), {"max_pending", "queue_timeout_s", "normal_boost_s", "max_cost_delay_s"}, "scheduler")
        resources = section(raw.get("resources", {}), {"min_available_ram_gib"}, "resources")
        limits = section(raw.get("limits", {}), {"upstream_timeout_s", "upstream_read_timeout_s", "max_body_bytes", "max_response_bytes"}, "limits")
        backend_url = backend.get("base_url", cls.backend_url)
        if not isinstance(backend_url, str):
            raise ValueError("backend.base_url must be an HTTP(S) URL string")
        config = cls(host=listen.get("host", cls.host), port=listen.get("port", cls.port),
                     api_key_env=listen.get("api_key_env"), backend_kind=backend.get("kind", cls.backend_kind),
                     backend_url=backend_url.rstrip("/"),
                     backend_key_env=backend.get("api_key_env"), backend_revision=backend.get("revision", cls.backend_revision),
                     default_class=raw.get("default_class", "normal"), **scheduler, **resources, **limits)
        config.validate()
        return config

    def validate(self):
        from .adapters import engine_profile
        engine_profile(self.backend_kind)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("listen.port must be an integer TCP port")
        if not isinstance(self.host, str):
            raise ValueError("listen.host must be an explicit IPv4 or IPv6 address")
        try:
            loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            raise ValueError("listen.host must be an explicit IPv4 or IPv6 address") from None
        env_name(self.api_key_env)
        env_name(self.backend_key_env)
        if not loopback and not self.api_key_env:
            raise ValueError("A non-loopback listener requires listen.api_key_env")
        if not isinstance(self.backend_url, str) or any(c.isspace() or ord(c) < 32 for c in self.backend_url):
            raise ValueError("backend.base_url must be an HTTP(S) URL string without whitespace")
        url = urlsplit(self.backend_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("backend.base_url must be an HTTP(S) API base without credentials, query or fragment")
        if not url.path.endswith("/v1"):
            raise ValueError("backend.base_url must end in /v1")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("backend.base_url has an invalid TCP port")
        if self.default_class not in ("normal", "background"):
            raise ValueError("default_class must be normal or background")
        if not isinstance(self.backend_revision, str) or not 1 <= len(self.backend_revision) <= 128:
            raise ValueError("backend.revision must be a short operator-defined runtime identity")
        for name, low, high in (("max_pending", 1, 4096), ("max_body_bytes", 1024, 64 * 1024 * 1024),
                                ("max_response_bytes", 1024, 256 * 1024 * 1024)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ValueError(f"Invalid {name}")
        for name, low, high in (("queue_timeout_s", .01, 3600), ("normal_boost_s", 0, 10),
                                ("max_cost_delay_s", 0, 300), ("upstream_timeout_s", .01, 86400),
                                ("upstream_read_timeout_s", .01, 3600), ("min_available_ram_gib", 0, 16384)):
            finite(getattr(self, name), name, low, high)


def load_config(path):
    def invalid(value):
        raise ValueError(f"Non-finite JSON value {value}")
    # PowerShell and several Windows editors emit a UTF-8 BOM by default.
    with open(path, encoding="utf-8-sig") as handle:
        return Config.from_dict(json.load(handle, parse_constant=invalid))
