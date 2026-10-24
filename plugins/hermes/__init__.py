"""Opt-in host-known background routing through Adaptive Inference.

Only documented PluginContext registration, configuration and cron interfaces
are used. The plugin never dispatches a request or changes provider credentials.
"""
from __future__ import annotations

import logging
from threading import Lock
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)
PLUGIN_ID = "adaptive-inference-routing"
HEADER = "X-Adaptive-Class"
MAX_IDENTITIES = 2048
DEFAULTS = {
    "enabled": False,
    "gateway_url": "http://127.0.0.1:18100/v1",
    "background_profile": False,
    "demote_delegated": True,
    "demote_cron": True,
}


def _endpoint(value):
    """Compare the complete configured endpoint, never a hostname substring."""
    if (not isinstance(value, str) or not value or "\\" in value
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username is not None or url.password is not None
                or url.query or url.fragment
                or url.path.rstrip("/") not in {"/v1", "/background/v1"}):
            return None
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            return None
        return (url.scheme, url.hostname.lower(),
                port if port is not None else (443 if url.scheme == "https" else 80),
                url.path.rstrip("/"))
    except ValueError:
        return None


def _identity(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


class ChildSessions:
    """Bounded, per-plugin-instance aliases from host lifecycle events only."""

    def __init__(self, limit=MAX_IDENTITIES):
        self.limit = limit
        self._aliases = {}
        self._lock = Lock()

    def start(self, session_id):
        key = _identity(session_id)
        if key is None:
            return
        with self._lock:
            if key not in self._aliases and len(self._aliases) >= self.limit:
                LOGGER.warning("Adaptive routing child identity limit reached; new child is unchanged")
                return
            self._aliases[key] = key

    def rollover(self, old, new):
        old, new = _identity(old), _identity(new)
        with self._lock:
            if old not in self._aliases or new is None:
                return
            if new not in self._aliases and len(self._aliases) >= self.limit:
                LOGGER.warning("Adaptive routing alias limit reached; new session is unchanged")
                return
            self._aliases[new] = self._aliases[old]

    def contains(self, session_id):
        key = _identity(session_id)
        with self._lock:
            return key is not None and key in self._aliases

    def stop(self, session_id):
        key = _identity(session_id)
        with self._lock:
            root = self._aliases.get(key)
            if root is not None:
                self._aliases = {alias: owner for alias, owner in self._aliases.items()
                                 if owner != root}

    def clear(self):
        with self._lock:
            self._aliases.clear()


class Routing:
    def __init__(self, context):
        self.context = context
        self.children = ChildSessions()

    def settings(self):
        raw = self.context.get_config("routing", {})
        if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
            return None
        cfg = {**DEFAULTS, **raw}
        if any(type(cfg[key]) is not bool for key in
               ("enabled", "background_profile", "demote_delegated", "demote_cron")):
            return None
        if _endpoint(cfg["gateway_url"]) is None:
            return None
        return cfg

    def child_start(self, *, child_session_id=None, **kwargs):
        cfg = self.settings()
        if cfg and cfg["enabled"] and cfg["demote_delegated"]:
            self.children.start(child_session_id)

    def child_stop(self, *, child_session_id=None, **kwargs):
        self.children.stop(child_session_id)

    def compaction(self, *, old_session_id=None, session_id=None, **kwargs):
        self.children.rollover(old_session_id, session_id)

    def request(self, *, request, base_url="", api_mode="", session_id="", **kwargs):
        cfg = self.settings()
        if (not cfg or not cfg["enabled"] or api_mode != "chat_completions"
                or _endpoint(base_url) != _endpoint(cfg["gateway_url"])
                or not isinstance(request, dict)):
            return None
        headers = request.get("extra_headers", {})
        body = request.get("extra_body", {})
        if not isinstance(headers, dict) or not isinstance(body, dict):
            return None
        # Explicit caller routing wins, including malformed metadata that the
        # gateway will reject. Never create a conflicting header/body pair.
        if (any(isinstance(key, str) and key.lower() == HEADER.lower() for key in headers)
                or any(key in mapping for mapping in (request, body)
                       for key in ("adaptive_scheduling", "strata_scheduling"))):
            return None
        reason = None
        if cfg["background_profile"]:
            reason = "explicit background profile"
        elif cfg["demote_delegated"] and self.children.contains(session_id):
            reason = "host-announced delegated session"
        elif cfg["demote_cron"]:
            # The archived 0.21.5 SDK has middleware/child hooks but not this
            # newer public capability. Its absence is not permission to infer
            # cron identity from prompts, environment or private host modules.
            current_cron = getattr(self.context, "current_cron_execution", None)
            if callable(current_cron) and current_cron() is not None:
                reason = "host cron execution"
        if reason is None:
            return None
        return {
            "request": {**request, "extra_headers": {**headers, HEADER: "background"}},
            "source": PLUGIN_ID,
            "reason": reason,
        }


def register(ctx):
    routing = Routing(ctx)
    ctx.register_hook("subagent_start", routing.child_start)
    ctx.register_hook("subagent_stop", routing.child_stop)
    ctx.register_hook("post_compaction", routing.compaction)
    ctx.register_middleware("llm_request", routing.request)
    ctx.on_unload(routing.children.clear)
