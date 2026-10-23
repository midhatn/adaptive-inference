"""OpenAI-compatible transport with bounded queueing and measured feedback.

No generation retries, prompt logging, model replacement or quality rewriting.
An active disconnected request is drained, retaining admission until upstream
finishes. An ambiguous timeout/failure blocks further dispatch until restart.
"""
from __future__ import annotations

from collections import deque
import hashlib
import hmac
import json
import time
import uuid

from aiohttp import ClientSession, ClientTimeout, ClientConnectorError, ClientError, web

from . import __version__
from .adapters import engine_profile, prepare_request
from .config import Config, env_secret
from .costs import RequestCostModel
from .resources import Capacity
from .scheduler import Scheduler, AdmissionError


def parse_json(raw):
    def invalid(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    return json.loads(raw, parse_constant=invalid)


def request_class(body, header, default, forced_background=False):
    classes = []
    for field in ("adaptive_scheduling", "strata_scheduling"):
        if field in body:
            value = body[field]
            if not isinstance(value, dict) or set(value) != {"class"}:
                raise ValueError(f"{field} accepts only a class field")
            classes.append(value["class"])
    if header is not None:
        classes.append(header)
    if any(value not in ("normal", "background") for value in classes) or len(set(classes)) > 1:
        raise ValueError("Conflicting or invalid scheduling classes")
    selected = classes[0] if classes else default
    return "background" if forced_background or default == "background" else selected


def cost_key(config, path, body, work_class):
    # Seed changes RNG realizations, not the timing population. Never mutate
    # the outgoing body. Payload byte buckets are approximate, not token counts.
    content = {key: body.get(key) for key in ("messages", "prompt", "input", "tools", "functions") if key in body}
    size = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    controls = {key: value for key, value in body.items()
                if key not in {*content, "seed", "user", "metadata", "adaptive_scheduling", "strata_scheduling"}}
    identity = [config.backend_kind, config.backend_url, config.backend_revision, path,
                work_class, max(1, size).bit_length(), controls]
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "function_call"})


def expected_choice_count(body, endpoint):
    """Bound learning bookkeeping, without rejecting or changing upstream input."""
    count = body.get("n", 1)
    if type(count) is not int or not 1 <= count <= 1024:
        return 0
    prompt = body.get("prompt")
    if endpoint == "/completions" and isinstance(prompt, list):
        if not prompt:
            return 0
        if all(isinstance(row, (str, list)) for row in prompt):
            count *= len(prompt)
        elif not all(type(row) is int for row in prompt):
            return 0
    return count if count <= 1024 else 0


def complete_json(raw, endpoint, expected_choices=None):
    try:
        body = parse_json(raw)
        if not isinstance(body, dict) or body.get("error"):
            return False
        if endpoint == "/embeddings":
            return isinstance(body.get("data"), list) and bool(body["data"]) and all(isinstance(row, dict) and isinstance(row.get("embedding"), list) for row in body["data"])
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or expected_choices == 0:
            return False
        if expected_choices is not None and len(choices) != expected_choices:
            return False
        indexes = set()
        for row in choices:
            if not isinstance(row, dict) or row.get("finish_reason") not in FINISH_REASONS:
                return False
            index = row.get("index", 0 if len(choices) == 1 else None)
            if type(index) is not int or index < 0 or index in indexes:
                return False
            indexes.add(index)
        return indexes == set(range(len(choices)))
    except (ValueError, UnicodeError, TypeError):
        return False


class StreamCompletion:
    """Bounded completion detector; forwarded SSE bytes are never rewritten."""
    def __init__(self, expected_choices=None):
        self.buffer = b""
        self.done = self.invalid = False
        self.seen, self.finished = set(), set()
        self.expected_choices = expected_choices

    def feed(self, chunk):
        if self.invalid:
            return
        self.buffer += chunk
        if len(self.buffer) > 256 * 1024:
            self.invalid = True
            self.buffer = b""
            return
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                self.done = True
                continue
            try:
                event = parse_json(data)
                if event.get("error"):
                    self.invalid = True
                for row in event.get("choices", []):
                    index = row.get("index", 0 if self.expected_choices in (None, 1) else None)
                    if type(index) is not int or not 0 <= index < 1024:
                        self.invalid = True
                        break
                    self.seen.add(index)
                    if row.get("finish_reason") in FINISH_REASONS:
                        self.finished.add(index)
            except (ValueError, UnicodeError, TypeError, AttributeError):
                self.invalid = True

    @property
    def complete(self):
        expected = (set(range(self.expected_choices)) if self.expected_choices is not None else self.seen)
        return self.done and bool(expected) and self.seen == self.finished == expected and not self.invalid


class Gateway:
    def __init__(self, config, capacity=None):
        config.validate()
        self.config = config
        self.profile = engine_profile(config.backend_kind)
        self.api_key = env_secret(config.api_key_env)
        self.backend_key = env_secret(config.backend_key_env)
        self.capacity = capacity if capacity is not None else Capacity(config.min_available_ram_gib)
        self.scheduler = Scheduler(config, self.capacity)
        self.costs = RequestCostModel()
        self.history = deque(maxlen=128)
        self.instance = uuid.uuid4().hex
        self.client = None

    async def startup(self, app):
        self.client = ClientSession(timeout=ClientTimeout(total=self.config.upstream_timeout_s,
                                    connect=10, sock_read=self.config.upstream_read_timeout_s),
                                    auto_decompress=False, trust_env=False)

    async def shutdown(self, app):
        await self.scheduler.close()

    async def cleanup(self, app):
        if self.client is not None:
            await self.client.close()

    @web.middleware
    async def authorization(self, request, handler):
        if self.api_key:
            supplied = request.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + self.api_key):
                return self.error(401, "unauthorized", "A valid gateway bearer token is required")
        # No CORS wildcard: browser origins require a deliberately configured
        # same-origin reverse proxy. This is an API, not an unauthenticated web app.
        if request.headers.get("Origin"):
            return self.error(403, "origin_not_allowed", "Use a same-origin authenticated application server")
        return await handler(request)

    @staticmethod
    def error(status, code, message):
        return web.json_response({"error": {"type": "adaptive_inference_error", "code": code, "message": message}}, status=status)

    def headers(self):
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        if self.backend_key:
            headers["Authorization"] = "Bearer " + self.backend_key
        return headers

    async def status(self, request):
        return web.json_response({"service": "adaptive-inference", "version": __version__,
                                  "instance": self.instance, "backend": self.config.backend_kind,
                                  "scheduler": self.scheduler.status(), "cost_model": self.costs.status(),
                                  "resources": self.capacity.status() if hasattr(self.capacity, "status") else {},
                                  "history": list(self.history) if request.path == "/metrics" else []})

    async def models(self, request):
        try:
            async with self.client.get(self.config.backend_url + "/models", headers=self.headers(), allow_redirects=False) as response:
                chunks, total = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > self.config.max_response_bytes:
                        return self.error(502, "response_too_large", "Backend model list exceeds limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
                return web.Response(body=data, status=response.status, headers={"Content-Type": response.headers.get("Content-Type", "application/json")})
        except (ClientError, TimeoutError):
            return self.error(502, "backend_unavailable", "Could not read the configured backend model list")

    async def inference(self, request):
        endpoint = "/" + request.match_info["endpoint"]
        if "/v1" + endpoint not in self.profile.endpoints:
            return self.error(404, "unsupported_endpoint", "This backend profile does not advertise this endpoint")
        if request.query:
            return self.error(400, "unsupported_query", "Request parameters belong in the JSON body")
        try:
            body = parse_json(await request.read())
            if not isinstance(body, dict) or not isinstance(body.get("model"), str) or not body["model"]:
                raise ValueError("A JSON object with a model name is required")
            work_class = request_class(body, request.headers.get("X-Adaptive-Class"), self.config.default_class,
                                       request.path.startswith("/background/"))
            outgoing = prepare_request(self.config.backend_kind, body)
            key = cost_key(self.config, endpoint, outgoing, work_class)
            prediction = self.costs.predict(key, now=time.monotonic())
        except (ValueError, TypeError, UnicodeError) as exc:
            return self.error(400, "invalid_request", str(exc))
        try:
            ticket = await self.scheduler.acquire(work_class, prediction["estimate_s"],
                          lambda: request.transport is None or request.transport.is_closing())
        except AdmissionError as exc:
            return self.error(exc.status, exc.code, str(exc))
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        status, uncertain, trained, client_gone = 502, False, False, False
        result = None
        try:
            async with self.client.post(self.config.backend_url + endpoint, json=outgoing,
                                        headers=self.headers(), allow_redirects=False) as response:
                status = response.status
                headers = {key: value for key, value in response.headers.items()
                           if key.lower() in ("content-type", "content-encoding", "cache-control", "retry-after")}
                headers["X-Adaptive-Request-Id"] = request_id
                headers["X-Adaptive-Class"] = work_class
                streaming = "text/event-stream" in response.headers.get("Content-Type", "")
                if streaming:
                    result = web.StreamResponse(status=status, headers=headers)
                    detector = StreamCompletion(expected_choice_count(outgoing, endpoint))
                    try:
                        await result.prepare(request)
                    except (ConnectionError, OSError):
                        client_gone = True
                    total = 0
                    async for chunk in response.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > self.config.max_response_bytes:
                            uncertain = True
                            raise ValueError("response_too_large")
                        detector.feed(chunk)
                        if not client_gone:
                            try:
                                await result.write(chunk)
                            except (ConnectionError, OSError):
                                client_gone = True
                    complete = detector.complete
                    if not client_gone:
                        try:
                            await result.write_eof()
                        except (ConnectionError, OSError):
                            client_gone = True
                else:
                    chunks, total = [], 0
                    async for chunk in response.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > self.config.max_response_bytes:
                            uncertain = True
                            raise ValueError("response_too_large")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    complete = complete_json(raw, endpoint, expected_choice_count(outgoing, endpoint))
                    result = web.Response(body=raw, status=status, headers=headers)
                    client_gone = request.transport is None or request.transport.is_closing()
                success = 200 <= status < 300 and complete and not client_gone
                trained = self.costs.observe(key, max(1e-9, time.monotonic() - started),
                                             now=time.monotonic(), success=success)
                return result
        except ClientConnectorError:
            # Connection was never established: no backend dispatch to drain.
            self.costs.observe(key, max(1e-9, time.monotonic() - started), now=time.monotonic(), success=False)
            return self.error(502, "backend_unavailable", "Cannot connect to the configured backend")
        except (ClientError, TimeoutError, ValueError):
            uncertain = True
            self.costs.observe(key, max(1e-9, time.monotonic() - started), now=time.monotonic(), success=False)
            if result is not None and result.prepared:
                request.transport.close() if request.transport is not None else None
                return result
            return self.error(502, "backend_completion_uncertain", "Upstream response did not complete; check backend and restart gateway before more work")
        finally:
            self.history.append({"request_id": request_id, "sequence": ticket.sequence, "class": work_class,
                                 "status": status, "prediction": prediction, "execution_s": time.monotonic() - started,
                                 "queue_s": started - ticket.arrival, "trained": trained,
                                 "client_disconnected": client_gone, "backend_completion_uncertain": uncertain})
            await self.scheduler.release(ticket, uncertain=uncertain)


GATEWAY = web.AppKey("gateway", Gateway)


def create_app(config: Config, *, capacity=None):
    gateway = Gateway(config, capacity)
    app = web.Application(client_max_size=config.max_body_bytes, middlewares=[gateway.authorization])
    app[GATEWAY] = gateway
    app.on_startup.append(gateway.startup)
    app.on_shutdown.append(gateway.shutdown)
    app.on_cleanup.append(gateway.cleanup)
    for route in ("/", "/health", "/status", "/metrics"):
        app.router.add_get(route, gateway.status)
    for prefix in ("/v1", "/background/v1"):
        app.router.add_get(prefix + "/models", gateway.models)
        app.router.add_post(prefix + "/{endpoint:chat/completions|completions|embeddings}", gateway.inference)
    return app
