"""The spark7 client: the house's AI server, OpenAI-compatible (vLLM), behind Cloudflare Access.

This engine's own copy. ``chatbot`` has another; there is no shared import between engines (Engine
Building Guide section 1), so each can move to another model on its own timetable.

What it does, and why each part is there (measured on spark7 and its predecessor spark5):

* **Streams every call** (``stream: true``, server-sent events). The access proxy cuts a response that
  has not started within 125 s (HTTP 524). Streaming means only the first byte has to beat it; the read
  timeout (``first_byte_s``) is also the longest silence tolerated between two chunks, and ``total_s``
  bounds the whole call.
* **Sends the access token as two headers** (``CF-Access-Client-Id``, ``CF-Access-Client-Secret``), read
  from environment variables named in ``config.yaml``, never from the file itself, plus
  ``Cache-Control: no-cache`` so the proxy can never replay someone else's stream. The values are held
  with ``repr=False`` and appear in no message, log line, ``/meta`` or artefact.
* **Refuses a host at start** that is a known external generative-AI provider, and any host that is
  neither loopback nor the house's own (``*.minimind.ch``). The OGD Plattform's rule is a blocklist;
  this one is stricter, a blocklist with a named reason plus a house allowlist (REP-04).
* **Checks the answer came from the configured model**: vLLM echoes the model name, and an answer from
  another model is an error, not a silently different result.
* **Warm-up tick** (:class:`Warmer`): a one-token call on a timer, so a cold load is not a reader's wait.

Errors come in two kinds. :class:`ModelUnavailable`: the service cannot be reached or will not answer now
(connection, timeout, 401/403, 429, 5xx, 524); retrying later may help. :class:`ModelError`: it answered
and the answer is unusable (400/404/422, a broken stream, the wrong model); retrying will not help.
"""

from __future__ import annotations

import ipaddress
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

import httpx

#: Known external generative-AI providers (after the OGD Plattform's ``VERWEIGERTE_HOSTS``). Compared as
#: the exact host or a domain suffix, never as a substring.
REFUSED_HOSTS: frozenset[str] = frozenset({
    "openai.com", "openai.azure.com", "anthropic.com", "claude.ai", "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com", "mistral.ai", "cohere.ai", "cohere.com", "groq.com", "openrouter.ai",
    "together.ai", "together.xyz", "deepseek.com", "x.ai", "perplexity.ai", "replicate.com",
    "huggingface.co", "fireworks.ai", "anyscale.com", "databricks.com",
})

#: The house's own hosts. A host must be loopback or end in one of these.
HOUSE_DOMAINS: tuple[str, ...] = ("minimind.ch",)


class ModelConfigError(ValueError):
    """The model configuration is unusable or breaks the host rule. Raised at start."""


class ModelUnavailable(RuntimeError):
    """The model service cannot answer now. The message says why and what to check."""


class ModelError(RuntimeError):
    """The model service answered, and the answer cannot be used."""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_host(base_url: str) -> str:
    """The host of ``base_url``, or :class:`ModelConfigError` if the house rule refuses it."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host:
        raise ModelConfigError(f"model base_url {base_url!r} is not an http(s) URL with a host")
    hit = next((d for d in REFUSED_HOSTS if host == d or host.endswith("." + d)), None)
    if hit is None and host.startswith("bedrock") and host.endswith("amazonaws.com"):
        hit = host
    if hit:
        raise ModelConfigError(
            f"model base_url {base_url} points at {hit}, a provider of external generative AI. Every model "
            "call of this system runs on the house's own server (spark7) or on this machine; an external "
            "provider is refused, also for a test and also behind a switch.")
    if not (_is_loopback(host) or any(host == d or host.endswith("." + d) for d in HOUSE_DOMAINS)):
        raise ModelConfigError(
            f"model host {host!r} is neither loopback nor one of the house's own hosts "
            f"({', '.join('*.' + d for d in HOUSE_DOMAINS)}); refused")
    if parsed.scheme == "http" and not _is_loopback(host):
        raise ModelConfigError(f"model base_url {base_url} is plain http to a remote host; use https")
    return host


@dataclass(frozen=True)
class ModelSettings:
    service: str
    protocol: str
    base_url: str
    model: str
    stream: bool = True
    connect_timeout_s: float = 10.0
    first_byte_timeout_s: float = 120.0
    total_timeout_s: float = 300.0
    #: Headers without a secret, as the file states them.
    fixed_headers: dict[str, str] = field(default_factory=dict)
    #: Header name -> the NAME of the environment variable holding its value.
    secret_header_env: dict[str, str] = field(default_factory=dict)
    warmup_enabled: bool = True
    warmup_interval_s: float = 240.0
    #: The name readers see for the house's AI (REP-21). ``service`` names the server it runs on (spark7).
    display_name: str = "MiniMind"

    def url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1") and path.startswith("/v1/"):
            path = path[3:]
        return base + path

    def describe(self, env: Mapping[str, str]) -> dict[str, Any]:
        """Safe to publish: header names and variable names, and whether each is set, never a value."""
        return {
            "display_name": self.display_name, "service": self.service, "protocol": self.protocol, "base_url": self.base_url,
            "host": urlparse(self.base_url).hostname, "model": self.model, "stream": self.stream,
            "timeouts": {"connect_s": self.connect_timeout_s, "first_byte_s": self.first_byte_timeout_s,
                         "total_s": self.total_timeout_s},
            "headers": sorted(self.fixed_headers),
            "headers_from_env": {h: {"variable": v, "set": bool(env.get(v))}
                                 for h, v in sorted(self.secret_header_env.items())},
            "warmup": {"enabled": self.warmup_enabled, "interval_s": self.warmup_interval_s},
        }


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    finish_reason: str
    latency_ms: float
    first_byte_ms: Optional[float]
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class Spark7Client:
    """One client per engine process. Thread-safe: httpx.Client may be shared across threads."""

    def __init__(self, settings: ModelSettings, env: Optional[Mapping[str, str]] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        check_host(settings.base_url)
        self.settings = settings
        self._env = dict(env or {})
        timeout = httpx.Timeout(connect=settings.connect_timeout_s, read=settings.first_byte_timeout_s,
                                write=30.0, pool=30.0)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never the headers
        return f"Spark7Client(service={self.settings.service!r}, model={self.settings.model!r})"

    def close(self) -> None:
        self._client.close()

    def missing_secrets(self) -> list[str]:
        return [v for v in self.settings.secret_header_env.values() if not self._env.get(v)]

    def _headers(self) -> dict[str, str]:
        headers = dict(self.settings.fixed_headers)
        for name, variable in self.settings.secret_header_env.items():
            value = self._env.get(variable)
            if value:
                headers[name] = value
        return headers

    # -- calls -------------------------------------------------------------

    def models(self) -> list[str]:
        """``GET /v1/models``: the model names the service serves."""
        try:
            response = self._client.get(self.settings.url("/v1/models"), headers=self._headers())
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(response.status_code, response.text)
        try:
            return [m["id"] for m in response.json()["data"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelError(f"{self.settings.service} /v1/models answered something unreadable") from exc

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float,
                 seed: Optional[int] = None, response_format: Optional[dict[str, Any]] = None) -> Completion:
        """One chat completion. Streams when the configuration says so (it does for spark7)."""
        body: dict[str, Any] = {"model": self.settings.model, "messages": messages,
                                "max_tokens": int(max_tokens), "temperature": float(temperature),
                                "stream": self.settings.stream}
        if seed is not None:
            body["seed"] = int(seed)
        if response_format is not None:
            body["response_format"] = response_format
        if self.settings.stream:
            body["stream_options"] = {"include_usage": True}
            return self._stream(body)
        return self._once(body)

    def touch(self) -> tuple[Optional[str], float]:
        """The warm-up call: one token. ``(None, ms)`` when the model answered, else ``(reason, ms)``."""
        t0 = time.perf_counter()
        try:
            self.complete([{"role": "user", "content": "."}], max_tokens=1, temperature=0.0)
            return None, (time.perf_counter() - t0) * 1000.0
        except (ModelUnavailable, ModelError) as exc:
            return f"{type(exc).__name__}: {exc}", (time.perf_counter() - t0) * 1000.0

    # -- internals ---------------------------------------------------------

    def _unreachable(self, exc: Exception) -> ModelUnavailable:
        kind = type(exc).__name__
        if isinstance(exc, httpx.TimeoutException) and not isinstance(exc, httpx.ConnectTimeout):
            return ModelUnavailable(
                f"{self.settings.service} did not answer in time ({kind}; first byte limit "
                f"{self.settings.first_byte_timeout_s:.0f} s, total {self.settings.total_timeout_s:.0f} s). "
                "A cold model loads for about a minute; the warm-up tick is there to prevent that.")
        return ModelUnavailable(f"{self.settings.service} is unreachable at {self.settings.base_url} ({kind}: "
                                f"{exc}). Is the machine online?")

    def _raise_for_status(self, status: int, text: str) -> None:
        if status == 200:
            return
        excerpt = " ".join((text or "").split())[:300]
        name = self.settings.service
        if status in (401, 403):
            missing = self.missing_secrets()
            hint = (f"the variables {missing} are not set (family .env)" if missing
                    else "the Cloudflare Access service token was refused")
            raise ModelUnavailable(f"{name} refused access (HTTP {status}): {hint}")
        if status == 524:
            raise ModelUnavailable(f"{name}: the access proxy gave up before the first byte (HTTP 524, 125 s)")
        if status == 429 or status >= 500:
            raise ModelUnavailable(f"{name} answered HTTP {status}: {excerpt}")
        raise ModelError(f"{name} answered HTTP {status}: {excerpt}")

    def _check_model(self, echoed: Optional[str]) -> str:
        if echoed and echoed != self.settings.model:
            raise ModelError(f"asked {self.settings.service} for {self.settings.model!r} and the answer came from "
                             f"{echoed!r}; refused rather than recorded under the wrong name")
        return echoed or self.settings.model

    def _once(self, body: dict[str, Any]) -> Completion:
        t0 = time.perf_counter()
        try:
            response = self._client.post(self.settings.url("/v1/chat/completions"), json=body,
                                         headers=self._headers(),
                                         timeout=httpx.Timeout(self.settings.total_timeout_s,
                                                               connect=self.settings.connect_timeout_s))
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        self._raise_for_status(response.status_code, response.text)
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            finish = choice.get("finish_reason") or "unknown"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError(f"{self.settings.service} answered without a readable choice") from exc
        usage = data.get("usage") or {}
        return Completion(text=text, model=self._check_model(data.get("model")), finish_reason=finish,
                          latency_ms=(time.perf_counter() - t0) * 1000.0, first_byte_ms=None,
                          prompt_tokens=usage.get("prompt_tokens"),
                          completion_tokens=usage.get("completion_tokens"))

    def _stream(self, body: dict[str, Any]) -> Completion:
        t0 = time.perf_counter()
        deadline = t0 + self.settings.total_timeout_s
        parts: list[str] = []
        finish: Optional[str] = None
        echoed: Optional[str] = None
        usage: dict[str, Any] = {}
        first_byte: Optional[float] = None
        done = False
        try:
            with self._client.stream("POST", self.settings.url("/v1/chat/completions"), json=body,
                                     headers=self._headers()) as response:
                if response.status_code != 200:
                    response.read()
                    self._raise_for_status(response.status_code, response.text)
                for line in response.iter_lines():
                    now = time.perf_counter()
                    if first_byte is None:
                        first_byte = (now - t0) * 1000.0
                    if now > deadline:
                        raise ModelUnavailable(f"{self.settings.service} streamed for longer than "
                                               f"{self.settings.total_timeout_s:.0f} s; abandoned")
                    line = line.strip()
                    if not line or line.startswith(":") or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        done = True
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError as exc:
                        raise ModelError(f"{self.settings.service} sent an unreadable stream chunk") from exc
                    if chunk.get("error"):
                        raise ModelError(f"{self.settings.service} reported an error mid-stream: "
                                         f"{str(chunk['error'])[:300]}")
                    echoed = chunk.get("model") or echoed
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            parts.append(delta["content"])
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
        if not done and finish is None:
            raise ModelError(f"{self.settings.service}'s stream ended before the answer did")
        return Completion(text="".join(parts), model=self._check_model(echoed), finish_reason=finish or "unknown",
                          latency_ms=(time.perf_counter() - t0) * 1000.0, first_byte_ms=first_byte,
                          prompt_tokens=usage.get("prompt_tokens"),
                          completion_tokens=usage.get("completion_tokens"))


class Warmer:
    """The warm-up tick: :meth:`Spark7Client.touch` every ``interval_s`` on a daemon thread.

    A failed tick is the normal case on a shared server and not an error: the next one tries again. The
    last outcome is kept, with its reason, for ``/meta``.
    """

    def __init__(self, client: Spark7Client, interval_s: float):
        self.client = client
        self.interval_s = max(30.0, float(interval_s))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {"running": False, "ticks": 0, "last_at": None, "last_ok": None,
                                        "last_error": None, "last_ms": None}

    def tick(self) -> dict[str, Any]:
        reason, ms = self.client.touch()
        with self._lock:
            self._status.update(ticks=self._status["ticks"] + 1,
                                last_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                last_ok=reason is None, last_error=reason, last_ms=round(ms, 1))
            return dict(self._status)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="spark7-warmup", daemon=True)
            self._status["running"] = True
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._status["running"] = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)
