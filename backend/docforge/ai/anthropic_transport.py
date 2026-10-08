"""Claude, through the official Anthropic SDK.

The OpenAI-compatible transport in ``client.py`` serves every other provider.
This module exists because Claude's request surface is its own: sampling
parameters are rejected by current models, thinking and effort replace them,
tool use and structured outputs have their own shapes, and prompt caching pays
for itself on this app's repeated instructions.

Every request streams. That keeps long writer and analysis calls clear of HTTP
timeouts, lets a cancelled job stop the model mid-answer (leaving the stream
closes the connection), and gives the UI live progress.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlparse

import anthropic

from ..logging_setup import log_event
from ..settings_store import AIConfig
from .errors import LLMCancelled, LLMError, LLMRefused, LLMUnavailable
from .usage import record_usage

logger = logging.getLogger("docforge.ai.anthropic")

# Thinking counts against max_tokens, so a cap sized for the answer alone can be
# spent before the answer starts. Streaming keeps a larger cap safe.
MIN_MAX_TOKENS = 16_000
# The SDK retries 408/409/429/5xx and connection errors with backoff itself.
SDK_MAX_RETRIES = 2
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class ModelProfile:
    """What a Claude model accepts, from the API's per-model rules."""

    effort: bool  # accepts output_config.effort
    adaptive_explicit: bool  # thinks only when {"type": "adaptive"} is sent
    sampling: bool  # accepts temperature


# Prefix match, longest first. Current models reject sampling parameters and
# think adaptively by default; the 4.6/4.7/4.8 models think only when asked,
# and the 4.6s accept a temperature only while thinking is off, so with the
# adaptive thinking this app sends they get none; Haiku 4.5 predates effort and
# adaptive thinking altogether, and is the one model still sent a temperature.
_PROFILES: tuple[tuple[str, ModelProfile], ...] = (
    ("claude-haiku-5", ModelProfile(effort=True, adaptive_explicit=False, sampling=False)),
    ("claude-sonnet-5", ModelProfile(effort=True, adaptive_explicit=False, sampling=False)),
    ("claude-opus-5", ModelProfile(effort=True, adaptive_explicit=False, sampling=False)),
    ("claude-fable-5", ModelProfile(effort=True, adaptive_explicit=False, sampling=False)),
    ("claude-mythos-5", ModelProfile(effort=True, adaptive_explicit=False, sampling=False)),
    ("claude-opus-4-8", ModelProfile(effort=True, adaptive_explicit=True, sampling=False)),
    ("claude-opus-4-7", ModelProfile(effort=True, adaptive_explicit=True, sampling=False)),
    ("claude-opus-4-6", ModelProfile(effort=True, adaptive_explicit=True, sampling=False)),
    ("claude-sonnet-4-6", ModelProfile(effort=True, adaptive_explicit=True, sampling=False)),
    ("claude-haiku-4-5", ModelProfile(effort=False, adaptive_explicit=False, sampling=True)),
)
# An unrecognised model gets the request every current model accepts: no
# sampling, no effort, no thinking field. Nothing it could reject.
_UNKNOWN = ModelProfile(effort=False, adaptive_explicit=False, sampling=False)


def profile_for(model: str) -> ModelProfile:
    key = (model or "").strip().lower()
    for prefix, profile in _PROFILES:
        if key.startswith(prefix):
            return profile
    return _UNKNOWN


# Request fields an endpoint has refused for a model, learned from its 400s and
# remembered for the process — the same idea as the OpenAI path's capability
# caches. Keyed by (endpoint, model); "format" is further keyed by schema name,
# since the API compiles each schema and could reject one but not another.
_DROPPED: dict[tuple[str, str], set[str]] = {}
_DROPPED_LOCK = threading.Lock()

# What a 400's message names -> the field to stop sending.
_REJECTION_HINTS: tuple[tuple[str, str], ...] = (
    ("eager_input_streaming", "eager"),
    ("output_config.format", "format"),
    ("json_schema", "format"),
    ("temperature", "sampling"),  # before "thinking": its 400s mention both
    ("effort", "effort"),
    ("thinking", "thinking"),
    ("cache_control", "cache"),
)


def _base(url: str) -> str:
    """The SDK wants the API root; tolerate a pasted ``…/v1``."""
    text = (url or "").strip().rstrip("/")
    if text.endswith("/v1"):
        text = text[: -len("/v1")]
    return text or "https://api.anthropic.com"


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except ValueError:
        return "?"


# A few clients per process, so a request reuses a warm connection instead of
# paying a TLS handshake. Keyed by everything that shapes the client.
_CLIENTS: OrderedDict[tuple, anthropic.Anthropic] = OrderedDict()
_CLIENTS_LOCK = threading.Lock()
_MAX_CLIENTS = 32


def _client_for(config: AIConfig) -> anthropic.Anthropic:
    key = (config.api_key, _base(config.base_url), float(config.timeout_seconds))
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = anthropic.Anthropic(
                api_key=config.api_key,
                base_url=_base(config.base_url),
                timeout=float(config.timeout_seconds),
                max_retries=SDK_MAX_RETRIES,
            )
            _CLIENTS[key] = client
            while len(_CLIENTS) > _MAX_CLIENTS:
                _CLIENTS.popitem(last=False)
        else:
            _CLIENTS.move_to_end(key)
        return client


@dataclass
class Turn:
    """One assistant turn: its answer text and the blocks to send back verbatim."""

    text: str
    content: list = field(default_factory=list)
    stop_reason: str | None = None
    tool_uses: list = field(default_factory=list)


class AnthropicTransport:
    """Streams one request at a time for an ``AIConfig`` bound to a Claude model."""

    def __init__(self, config: AIConfig):
        self.config = config
        self.profile = profile_for(config.model)

    # ----- capability memory ---------------------------------------------
    def _key(self) -> tuple[str, str]:
        return (_base(self.config.base_url), self.config.model or "")

    def _dropped(self) -> set[str]:
        with _DROPPED_LOCK:
            return set(_DROPPED.get(self._key(), set()))

    def _drop(self, what: str) -> None:
        with _DROPPED_LOCK:
            _DROPPED.setdefault(self._key(), set()).add(what)

    # ----- request shape --------------------------------------------------
    def effort(self) -> str:
        level = (self.config.tier_effort or self.config.effort_workhorse or "").strip().lower()
        return level if level in _EFFORT_LEVELS else ""

    def build(
        self,
        *,
        system: list[str],
        messages: list,
        schema: dict | None = None,
        schema_name: str = "",
        tools: list[dict] | None = None,
    ) -> dict:
        dropped = self._dropped()
        cache = "cache" not in dropped
        params: dict = {
            "model": self.config.model,
            "max_tokens": max(int(self.config.max_output_tokens or 0), MIN_MAX_TOKENS),
            "messages": messages,
        }
        blocks = [{"type": "text", "text": text} for text in system if text]
        if blocks and cache:
            # The instructions are identical for every call of a kind (every
            # classify batch, every tool step), so they are read from the cache
            # after the first one.
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        if blocks:
            params["system"] = blocks
        if cache and tools:
            # Caches the conversation as it grows across the tool loop's steps.
            # A one-shot call has no later step to read it back, so there it
            # would only pay the cache-write surcharge on the user's content.
            params["cache_control"] = {"type": "ephemeral"}

        output_config: dict = {}
        effort = self.effort()
        if effort and self.profile.effort and "effort" not in dropped:
            output_config["effort"] = effort
        if schema is not None and f"format:{schema_name}" not in dropped and "format" not in dropped:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            params["output_config"] = output_config

        if self.profile.adaptive_explicit and "thinking" not in dropped:
            params["thinking"] = {"type": "adaptive"}
        if tools:
            if "eager" in dropped:
                tools = [{k: v for k, v in t.items() if k != "eager_input_streaming"} for t in tools]
            params["tools"] = tools
            params["tool_choice"] = {"type": "auto"}
        if (
            self.profile.sampling
            and "sampling" not in dropped
            and self.config.temperature is not None
        ):
            # The SDK no longer exposes sampling parameters, because current
            # models reject them; the few that still take one get it this way.
            params["extra_body"] = {"temperature": self.config.temperature}
        return params

    # ----- the call ---------------------------------------------------------
    def turn(
        self,
        *,
        system: list[str],
        messages: list,
        schema: dict | None = None,
        schema_name: str = "",
        tools: list[dict] | None = None,
        cancel_event=None,
        on_delta=None,
    ) -> Turn:
        """Run one request, relearning and retrying when a field is refused."""
        for _ in range(len(_REJECTION_HINTS) + 1):
            params = self.build(
                system=system, messages=messages, schema=schema,
                schema_name=schema_name, tools=tools,
            )
            try:
                return self._stream(params, cancel_event=cancel_event, on_delta=on_delta)
            except anthropic.BadRequestError as exc:
                field_name = self._refused_field(exc, params)
                if field_name is None:
                    log_event(
                        logger, "ai.error", level=logging.ERROR, provider="anthropic",
                        model=self.config.model, error=f"BadRequestError: {_message(exc)[:160]}",
                    )
                    raise LLMError(_explain(exc)) from exc
                self._drop(f"format:{schema_name}" if field_name == "format" else field_name)
                log_event(
                    logger, "ai.anthropic_field_dropped", level=logging.WARNING,
                    model=self.config.model, field=field_name, reason=_message(exc)[:160],
                )
        raise LLMError("Claude kept rejecting the request shape")

    def _refused_field(self, exc: Exception, params: dict) -> str | None:
        """Which optional field a 400 is about, if it is one we can drop."""
        text = _message(exc).lower()
        sent = {
            "eager": any("eager_input_streaming" in t for t in params.get("tools") or []),
            "format": "format" in (params.get("output_config") or {}),
            "effort": "effort" in (params.get("output_config") or {}),
            "thinking": "thinking" in params,
            "sampling": "temperature" in (params.get("extra_body") or {}),
            "cache": "cache_control" in params,
        }
        for hint, name in _REJECTION_HINTS:
            if hint in text and sent.get(name):
                return name
        return None

    def _stream(self, params: dict, *, cancel_event=None, on_delta=None) -> Turn:
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled before request")
        client = _client_for(self.config)
        log_event(
            logger, "ai.call", provider="anthropic", host=_host(self.config.base_url),
            model=self.config.model, messages=len(params["messages"]),
            effort=(params.get("output_config") or {}).get("effort"),
            structured="format" in (params.get("output_config") or {}),
            tools=len(params.get("tools") or []),
        )
        t0 = time.perf_counter()
        try:
            with client.messages.stream(**params) as stream:
                for event in stream:
                    if cancel_event is not None and cancel_event.is_set():
                        # Leaving the block closes the connection, which is
                        # what makes the server stop generating.
                        raise LLMCancelled("cancelled mid-stream")
                    if on_delta is not None and event.type == "text":
                        on_delta(event.text, event.snapshot)
                message = stream.get_final_message()
        except LLMCancelled:
            raise
        except anthropic.BadRequestError:
            raise  # turn() decides whether a field can be dropped
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            self._log_error(t0, exc)
            raise LLMError(
                "Anthropic rejected the API key. Check it in Settings (keys start with sk-ant-)."
            ) from exc
        except anthropic.NotFoundError as exc:
            self._log_error(t0, exc)
            raise LLMError(f"Anthropic does not recognise the model {self.config.model!r}.") from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            self._log_error(t0, exc)
            raise LLMUnavailable(f"Could not reach Anthropic: {exc}") from exc
        except anthropic.APIStatusError as exc:
            self._log_error(t0, exc)
            if exc.status_code == 429 or exc.status_code >= 500:
                raise LLMUnavailable(_explain(exc)) from exc
            raise LLMError(_explain(exc)) from exc

        usage = message.usage
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        record_usage(
            self.config.model, usage.input_tokens, usage.output_tokens,
            cache_read=cache_read, cache_write=cache_write,
        )
        log_event(
            logger, "ai.done", provider="anthropic", model=self.config.model,
            served_by=message.model, ms=round((time.perf_counter() - t0) * 1000, 1),
            finish=message.stop_reason, prompt_tokens=usage.input_tokens,
            cache_read=cache_read, cache_write=cache_write,
            completion_tokens=usage.output_tokens,
        )

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            log_event(
                logger, "ai.refusal", level=logging.WARNING,
                model=self.config.model, category=category,
            )
            raise LLMRefused(category)
        if message.stop_reason == "model_context_window_exceeded":
            raise LLMError("The content is larger than the model's context window.")

        text = "".join(b.text for b in message.content if b.type == "text")
        tool_uses = [b for b in message.content if b.type == "tool_use"]
        if message.stop_reason == "max_tokens":
            log_event(
                logger, "ai.truncated", level=logging.WARNING,
                model=self.config.model, completion_tokens=usage.output_tokens,
            )
        return Turn(
            text=text, content=list(message.content),
            stop_reason=message.stop_reason, tool_uses=tool_uses,
        )

    def _log_error(self, t0: float, exc: Exception) -> None:
        log_event(
            logger, "ai.error", level=logging.ERROR, provider="anthropic",
            model=self.config.model, ms=round((time.perf_counter() - t0) * 1000, 1),
            error=f"{type(exc).__name__}: {_message(exc)[:160]}",
        )

    # ----- other endpoints ------------------------------------------------
    def check_model(self, model: str) -> None:
        """Confirm the API knows ``model`` (the Models API: no tokens spent)."""
        try:
            _client_for(self.config).models.retrieve(model)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMError("Anthropic rejected the API key.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Anthropic does not recognise the model {model!r}.") from exc
        except anthropic.APIError as exc:
            raise LLMError(f"Could not check the model with Anthropic: {_message(exc)}") from exc


def _message(exc: Exception) -> str:
    return str(getattr(exc, "message", "") or exc)


def _explain(exc: Exception) -> str:
    text = _message(exc)
    low = text.lower()
    if "anthropic-workspace-id" in low:
        # A personal or service-account key that spans several workspaces needs
        # the workspace named on every request; DocForge has nowhere to set one.
        return (
            "This Anthropic key is not tied to a single workspace. In the Claude Console, "
            "create a key scoped to one workspace (Settings, API keys) and paste that one."
        )
    if "prompt is too long" in low or "context window" in low:
        return "The content is larger than the model's context window. " + text[:200]
    status = getattr(exc, "status_code", None)
    return f"HTTP {status} from Anthropic: {text[:240]}" if status else text[:240]


def to_anthropic_messages(messages: list[dict]) -> tuple[list[str], list[dict]]:
    """Split the app's OpenAI-style message list into (system texts, turns).

    Claude takes system instructions as a separate field; every other turn keeps
    its order. Consecutive turns of one role are merged, since the API expects
    the conversation to alternate.
    """
    system: list[str] = []
    turns: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            if content:
                system.append(content)
            continue
        if role not in ("user", "assistant"):
            continue
        if turns and turns[-1]["role"] == role and isinstance(turns[-1]["content"], str) and isinstance(content, str):
            turns[-1]["content"] += "\n\n" + content
        else:
            turns.append({"role": role, "content": content})
    return system, turns
