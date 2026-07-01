"""LLM client supporting OpenAI-compatible *and* Anthropic providers.

OpenAI-compatible covers OpenAI, Azure OpenAI, and local servers (Ollama,
LM Studio, vLLM, llama.cpp). Anthropic uses the native Messages API.

Design rules (spec §10, §19):
  * JSON-only responses, validated against a strict Pydantic schema.
  * Malformed responses are rejected and retried with a *repair* prompt.
  * No call is ever made unless the client is ``active`` (key + base configured).
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from ..logging_setup import log_event
from ..settings_store import AIConfig, get_ai_config
from .usage import record_usage

logger = logging.getLogger("docforge.ai")


def _host(url: str) -> str:
    """Host of a base URL (no path/creds) — safe to log."""
    try:
        return urlparse(url).netloc or url
    except ValueError:
        return "?"


def _msg_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the model cannot be reached or cannot produce valid output."""


class LLMCancelled(LLMError):
    """Raised when an in-flight LLM call is aborted via its cancellation Event.

    Distinct from LLMError so callers can mark the job *cancelled* rather than
    silently fall back to heuristics (which would defeat the cancel).
    """


class LLMUnavailable(LLMError):
    """Raised when the model server is transiently overloaded (429/5xx) and
    retries were exhausted. Distinct from LLMError so callers can try a
    different model (e.g. reasoning tier -> workhorse) before giving up.
    """


class _ToolsUnsupported(Exception):
    """Internal: the endpoint rejected a tools request — fall back to single-shot."""


# Bases that 400'd on response_format=json_object (e.g. LM Studio expects
# json_schema/text). Cached per-process so we stop re-sending the rejected field.
_JSON_MODE_UNSUPPORTED: set[str] = set()

# Bases that 400'd on a tool-calling request (no function-calling support).
# Cached so agentic calls transparently fall back to single-shot JSON for them.
_TOOLS_UNSUPPORTED: set[str] = set()

# Transient server-side conditions worth retrying: rate limits and overload.
# Gemini in particular returns 503 UNAVAILABLE ("high demand") in short spikes.
_RETRYABLE_STATUS = {429, 500, 502, 503, 529}
_TRANSIENT_ATTEMPTS = 3  # initial call + 2 retries
_BACKOFF_BASE_SECONDS = 2.0


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Delay before retrying a transient failure — honors Retry-After if sane."""
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            secs = float(ra)
            if 0 < secs <= 30:
                return secs
        except ValueError:
            pass
    return _BACKOFF_BASE_SECONDS * (2**attempt)  # 2s, 4s


def _post_with_retry(
    client: httpx.Client, path: str, payload: dict, headers: dict, *, cancel_event=None
) -> httpx.Response:
    """POST with bounded retry on transient 429/5xx overload responses.

    Returns the first non-transient response (success or a real 4xx the caller
    handles). Raises LLMUnavailable when every attempt hit a transient status,
    so callers can distinguish "overloaded right now" from a permanent error.
    """
    resp: httpx.Response | None = None
    for attempt in range(_TRANSIENT_ATTEMPTS):
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled")
        resp = client.post(path, json=payload, headers=headers)
        if resp.status_code not in _RETRYABLE_STATUS:
            return resp
        if attempt < _TRANSIENT_ATTEMPTS - 1:
            delay = _retry_delay(resp, attempt)
            log_event(
                logger, "ai.transient_retry", level=logging.WARNING,
                status=resp.status_code, attempt=attempt + 1, delay_s=delay,
            )
            time.sleep(delay)
    assert resp is not None
    raise LLMUnavailable(_explain_http_error(resp))


def _explain_http_error(resp: httpx.Response) -> str:
    """Turn a 4xx/5xx LLM response into an actionable message.

    Local servers (LM Studio, llama.cpp) put the real reason in the JSON body —
    most importantly context-window overflow, which otherwise surfaces to the
    user as an opaque "channel error". We detect that case and tell them exactly
    what to change (raise the model's context length).
    """
    body = ""
    try:
        data = resp.json()
        body = data.get("error", {}).get("message", "") if isinstance(data.get("error"), dict) else data.get("error", "")
        body = body or resp.text
    except (ValueError, AttributeError):
        body = resp.text
    body = (body or "").strip()
    low = body.lower()
    if "context length" in low or "n_ctx" in low or "context window" in low:
        return (
            "The document is larger than the model's context window. Increase the "
            "context length when loading the model (LM Studio → model settings → "
            "Context Length, e.g. 16384 or 32768), then reload. "
            f"Server said: {body[:200]}"
        )
    if "response_format" in low:
        return f"Server rejected the JSON response format: {body[:200]}"
    return f"HTTP {resp.status_code} from model server: {body[:240] or resp.reason_phrase}"


def _strip_thinking(text: str) -> str:
    """Remove reasoning blocks emitted by models like Qwen3.

    Handles both the closed ``<think>…</think>`` form and the *unclosed* form
    (an opening ``<think>`` with no matching close — common when generation is
    truncated mid-thought), where everything from the tag onward is reasoning
    that contains no JSON.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "<think>" in text and "</think>" not in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


_PRIMITIVE_CHARS = set("0123456789truefalsen-+.eEnul")  # number/bool/null body chars


def _repair_truncated_json(s: str) -> str | None:
    """Best-effort close of a JSON document truncated mid-output (finish=length).

    Walks the text tracking string state and bracket depth, recording the last
    structurally-complete position, then closes the still-open brackets/braces.
    Fully-formed elements survive (e.g. 30 of 42 classifications) instead of the
    whole response being discarded.

    A *complete* trailing primitive is retained symmetrically with strings: a
    value is "complete" once a delimiter or whitespace follows it. Only a bare
    primitive at the very end with no following character is dropped — there it
    is genuinely ambiguous whether ``7`` was final or about to become ``78``.
    """
    depth: list[str] = []
    in_str = False
    escaped = False
    last_safe = -1  # index (exclusive) of the last structurally-complete point
    prim_start = -1  # start index of an in-progress primitive run, else -1

    def _commit_primitive(end: int) -> None:
        nonlocal last_safe, prim_start
        if prim_start != -1:
            last_safe = max(last_safe, end)
            prim_start = -1

    for i, ch in enumerate(s):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
                # A closed string is a complete value only when NOT directly
                # inside an object — inside ``{}`` it may be a key still awaiting
                # its ``: value``, so committing here would yield ``{"k"}``.
                if not (depth and depth[-1] == "{"):
                    last_safe = i + 1
            continue
        if ch == '"':
            _commit_primitive(i)
            in_str = True
        elif ch in "{[":
            _commit_primitive(i)
            depth.append(ch)
        elif ch in "}]":
            _commit_primitive(i)
            if depth:
                depth.pop()
            last_safe = i + 1
        elif ch == ",":
            _commit_primitive(i)
            last_safe = i  # complete element boundary (drop the comma itself)
        elif ch in ": \t\r\n":
            _commit_primitive(i)  # whitespace/colon terminates a primitive
        elif ch in _PRIMITIVE_CHARS:
            if prim_start == -1:
                prim_start = i
        else:
            prim_start = -1  # unexpected char — abandon any primitive run
    if last_safe <= 0:
        return None
    head = s[:last_safe].rstrip().rstrip(",").rstrip()
    # Re-derive open brackets over the trimmed head and close them in reverse.
    depth = []
    in_str = False
    escaped = False
    for ch in head:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth.append(ch)
        elif ch in "}]" and depth:
            depth.pop()
    if in_str:
        head += '"'
    closers = "".join("}" if b == "{" else "]" for b in reversed(depth))
    return head + closers


def _extract_json(text: str) -> dict | list | None:
    """Best-effort extraction of a JSON object/array from a model response.

    Order matters: try a clean parse, then narrow using the document's *own*
    leading bracket type (so a truncated object never gets mis-read as one of
    its inner arrays), then attempt a structural repair of a truncated document,
    and only as a last resort fall back to any-bracket narrowing.
    """
    if not text:
        return None
    cleaned = _strip_thinking(text)
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Identify the document's leading structural bracket and prefer it, so a
    # truncated object isn't salvaged as one of its inner arrays (and vice versa).
    lead = next((ch for ch in cleaned if ch in "{[" or not ch.isspace()), None)
    if lead in ("{", "["):
        start = cleaned.find(lead)
        close = "}" if lead == "{" else "]"
        end = cleaned.rfind(close)
        if end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        repaired = _repair_truncated_json(cleaned[start:])
        if repaired:
            try:
                obj = json.loads(repaired)
                logger.debug("recovered JSON from a truncated model response")
                return obj
            except json.JSONDecodeError:
                pass

    # Last resort: any-bracket narrowing (handles junk-prefixed / mixed output).
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = cleaned.find(open_ch)
        end = cleaned.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _parse_tool_args(raw) -> dict:
    """Tool-call arguments come as a JSON string (OpenAI) or already a dict."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return val if isinstance(val, dict) else {"value": val}


class LLMClient:
    def __init__(self, config: AIConfig | None = None):
        self.config = config or get_ai_config()

    @property
    def active(self) -> bool:
        return self.config.active

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def supports_streaming(self) -> bool:
        return self.config.provider == "openai"

    def _apply_no_think(self, messages: list[dict]) -> list[dict]:
        """Prepend /no_think to the first system message for Qwen3 models.

        Qwen3 interprets the /no_think token in the first system turn and skips
        its chain-of-thought prefix, making responses faster and avoiding the
        <think>...</think> block that our JSON parser has to strip around.
        """
        if not self.config.no_think:
            return messages
        out = []
        patched = False
        for m in messages:
            if not patched and m.get("role") == "system":
                out.append({**m, "content": "/no_think\n\n" + m["content"]})
                patched = True
            else:
                out.append(m)
        return out

    def stream_openai(
        self, messages: list[dict], *, on_delta=None, temperature: float = 0.0, cancel_event=None
    ) -> str:
        """Stream an OpenAI-compatible completion for live progress.

        Calls ``on_delta(chunk, accumulated)`` per content chunk and returns the
        full text. Used so the UI can show the model working token-by-token.

        When ``cancel_event`` is set mid-stream we break out of the read loop;
        exiting the ``with client.stream(...)`` block closes the TCP connection,
        which signals the model server to **stop generating** rather than run to
        completion. We then raise ``LLMCancelled``.
        """
        messages = self._apply_no_think(messages)
        if not self.active:
            raise LLMError("LLM client is not active")
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled before request")
        base = self.config.base_url.rstrip("/") + "/"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": True,
            # Ask for a final usage chunk so streamed calls still report tokens.
            "stream_options": {"include_usage": True},
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        acc: list[str] = []
        cancelled = False
        stream_usage: dict = {}
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                with self._stream_with_retry(client, payload, headers, cancel_event) as resp:
                    for line in resp.iter_lines():
                        if cancel_event is not None and cancel_event.is_set():
                            cancelled = True
                            break  # closes the connection -> server stops generating
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            break
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            stream_usage = obj["usage"]  # final include_usage chunk
                        choices = obj.get("choices") or [{}]
                        delta = (choices[0].get("delta") or {}).get("content")
                        if delta:
                            acc.append(delta)
                            if on_delta is not None:
                                on_delta(delta, "".join(acc))
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"streaming request failed: {exc}") from exc
        if cancelled:
            raise LLMCancelled("cancelled mid-stream")
        if stream_usage:
            record_usage(
                self.config.model,
                stream_usage.get("prompt_tokens"),
                stream_usage.get("completion_tokens"),
            )
        return "".join(acc)

    @contextmanager
    def _stream_with_retry(self, client: httpx.Client, payload: dict, headers: dict, cancel_event):
        """Open a streaming completion, retrying transient overload statuses.

        Retry is safe here because nothing has been consumed yet when the
        status line says 429/503 — we close that response and try again.
        Yields a response guaranteed to be < 400.
        """
        last: httpx.Response | None = None
        for attempt in range(_TRANSIENT_ATTEMPTS):
            if cancel_event is not None and cancel_event.is_set():
                raise LLMCancelled("cancelled")
            with client.stream("POST", "chat/completions", json=payload, headers=headers) as resp:
                if resp.status_code in _RETRYABLE_STATUS:
                    resp.read()
                    last = resp
                    if attempt < _TRANSIENT_ATTEMPTS - 1:
                        delay = _retry_delay(resp, attempt)
                        log_event(
                            logger, "ai.transient_retry", level=logging.WARNING,
                            status=resp.status_code, attempt=attempt + 1, delay_s=delay,
                        )
                        time.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    resp.read()
                    raise LLMError(_explain_http_error(resp))
                yield resp
                return
        assert last is not None
        raise LLMUnavailable(_explain_http_error(last))

    # ----- transport ------------------------------------------------------
    def complete(self, messages: list[dict], *, temperature: float = 0.0, json_mode: bool = True) -> str:
        if not self.active:
            raise LLMError("LLM client is not active (configure a provider + API key)")
        messages = self._apply_no_think(messages)
        if self.config.provider == "anthropic":
            return self._complete_anthropic(messages, temperature)
        return self._complete_openai(messages, temperature, json_mode)

    def _complete_openai(self, messages: list[dict], temperature: float, json_mode: bool) -> str:
        base = self.config.base_url.rstrip("/") + "/"
        use_json = json_mode and base not in _JSON_MODE_UNSUPPORTED
        payload: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.config.max_output_tokens,
        }
        if use_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        log_event(
            logger, "ai.call", provider="openai", host=_host(base), model=self.config.model,
            messages=len(messages), prompt_chars=_msg_chars(messages), json_mode=use_json,
        )
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                resp = _post_with_retry(client, "chat/completions", payload, headers)
                # Some servers (e.g. LM Studio) reject json_object -> retry as plain
                # text and remember not to send it again to this base.
                if resp.status_code == 400 and use_json:
                    _JSON_MODE_UNSUPPORTED.add(base)
                    payload.pop("response_format", None)
                    log_event(logger, "ai.json_mode_unsupported", level=logging.WARNING, host=_host(base))
                    resp = _post_with_retry(client, "chat/completions", payload, headers)
                if resp.status_code >= 400:
                    raise LLMError(_explain_http_error(resp))
                data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
            finish = (data.get("choices") or [{}])[0].get("finish_reason")
            record_usage(self.config.model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
            log_event(
                logger, "ai.done", provider="openai", model=self.config.model,
                ms=round((time.perf_counter() - t0) * 1000, 1), resp_chars=len(text),
                finish=finish, prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
            return text
        except LLMError as exc:
            log_event(logger, "ai.error", level=logging.ERROR, provider="openai",
                      model=self.config.model, ms=round((time.perf_counter() - t0) * 1000, 1),
                      error=str(exc)[:200])
            raise
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            log_event(logger, "ai.error", level=logging.ERROR, provider="openai",
                      model=self.config.model, ms=round((time.perf_counter() - t0) * 1000, 1),
                      error=f"{type(exc).__name__}: {str(exc)[:160]}")
            raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc

    def _complete_anthropic(self, messages: list[dict], temperature: float) -> str:
        base = self.config.base_url.rstrip("/")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        conv = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": temperature,
            "system": system,
            "messages": conv,
        }
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        log_event(
            logger, "ai.call", provider="anthropic", host=_host(base), model=self.config.model,
            messages=len(messages), prompt_chars=_msg_chars(messages),
        )
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                resp = _post_with_retry(client, f"{base}/v1/messages", payload, headers)
                resp.raise_for_status()
                data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage") or {}
            record_usage(self.config.model, usage.get("input_tokens"), usage.get("output_tokens"))
            log_event(
                logger, "ai.done", provider="anthropic", model=self.config.model,
                ms=round((time.perf_counter() - t0) * 1000, 1), resp_chars=len(text),
                finish=data.get("stop_reason"), prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
            )
            return text
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            log_event(logger, "ai.error", level=logging.ERROR, provider="anthropic",
                      model=self.config.model, ms=round((time.perf_counter() - t0) * 1000, 1),
                      error=f"{type(exc).__name__}: {str(exc)[:160]}")
            raise LLMError(f"Anthropic request failed: {exc}") from exc

    # ----- validated JSON -------------------------------------------------
    def complete_json(
        self, *, system: str, developer: str, user: str, schema: type[T], cancel_event=None
    ) -> T:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"[developer instructions]\n{developer}"},
            {"role": "user", "content": user},
        ]
        # When cancellable, route through the streaming transport so the request
        # can be aborted between chunks (and the model server stops generating).
        stream_ok = cancel_event is not None and self.supports_streaming

        def _raw(msgs: list[dict]) -> str:
            if cancel_event is not None and cancel_event.is_set():
                raise LLMCancelled("cancelled")
            if stream_ok:
                return self.stream_openai(msgs, cancel_event=cancel_event)
            return self.complete(msgs)

        last_error = "unknown error"
        for attempt in range(self.config.max_retries + 1):
            raw = _raw(messages)
            data = _extract_json(raw)
            if data is not None:
                try:
                    result = schema.model_validate(data)
                    if attempt:
                        log_event(logger, "ai.json_ok_after_retry", schema=schema.__name__, attempt=attempt + 1)
                    return result
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.errors()[:3]}"
            else:
                last_error = "response was not valid JSON"
            log_event(
                logger, "ai.json_retry", level=logging.WARNING, schema=schema.__name__,
                attempt=attempt + 1, of=self.config.max_retries + 1, reason=str(last_error)[:120],
            )
            messages += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"Your previous response was invalid ({last_error}). "
                        "Respond again with ONLY a valid JSON object matching the "
                        "required schema. No prose, no markdown, no code fences."
                    ),
                },
            ]
        log_event(logger, "ai.json_failed", level=logging.ERROR, schema=schema.__name__, reason=str(last_error)[:160])
        raise LLMError(f"LLM did not return valid JSON after retries: {last_error}")

    # ----- agentic tool-use loop -----------------------------------------
    def for_tier(self, tier: str) -> LLMClient:
        """A client bound to the model for ``tier`` ("workhorse" | "reasoning").

        Returns ``self`` when the tier resolves to the same model, else a shallow
        clone with the model swapped — so callers can escalate the hard steps to
        the reasoning model without rebuilding the key/base config.
        """
        model = self.config.model_for_tier(tier)
        if model == self.config.model:
            return self
        return LLMClient(replace(self.config, model=model))

    def complete_agentic(
        self,
        *,
        system: str,
        developer: str,
        user: str,
        schema: type[T],
        tools: list | None = None,
        tier: str = "workhorse",
        max_steps: int | None = None,
        cancel_event=None,
    ) -> T:
        """Bounded tool-use loop returning a schema-validated final answer.

        The model may call any provided tool (OpenAI-compatible function calling);
        each result is fed back until it returns a final JSON answer or the step
        budget is exhausted. With no tools, an Anthropic provider, or an endpoint
        that rejects tools, this degrades to single-shot ``complete_json`` —
        today's behaviour — so nothing regresses offline.

        When the reasoning-tier model is transiently unavailable (e.g. Gemini
        503 "high demand" spikes) after retries, the call is re-run once on the
        workhorse model instead of abandoning AI for the whole action.
        """
        try:
            return self._complete_agentic_tiered(
                system=system, developer=developer, user=user, schema=schema,
                tools=tools, tier=tier, max_steps=max_steps, cancel_event=cancel_event,
            )
        except LLMUnavailable:
            from ..settings_store import REASONING_TIER, WORKHORSE_TIER

            if tier != REASONING_TIER or self.config.model_for_tier(tier) == self.config.model_for_tier(WORKHORSE_TIER):
                raise
            log_event(
                logger, "ai.tier_fallback", level=logging.WARNING,
                from_model=self.config.model_for_tier(tier),
                to_model=self.config.model_for_tier(WORKHORSE_TIER),
            )
            return self._complete_agentic_tiered(
                system=system, developer=developer, user=user, schema=schema,
                tools=tools, tier=WORKHORSE_TIER, max_steps=max_steps, cancel_event=cancel_event,
            )

    def _complete_agentic_tiered(
        self, *, system, developer, user, schema: type[T], tools, tier, max_steps, cancel_event
    ) -> T:
        client = self.for_tier(tier)
        base = client.config.base_url.rstrip("/") + "/"
        if not tools or client.provider == "anthropic" or base in _TOOLS_UNSUPPORTED:
            return client.complete_json(
                system=system, developer=developer, user=user, schema=schema, cancel_event=cancel_event
            )
        try:
            return client._agentic_openai(
                system=system, developer=developer, user=user,
                schema=schema, tools=tools, max_steps=max_steps, cancel_event=cancel_event,
            )
        except _ToolsUnsupported as exc:
            _TOOLS_UNSUPPORTED.add(base)
            log_event(logger, "ai.tools_unsupported", level=logging.WARNING, host=_host(base), reason=str(exc)[:120])
            return client.complete_json(
                system=system, developer=developer, user=user, schema=schema, cancel_event=cancel_event
            )

    def _agentic_openai(self, *, system, developer, user, schema: type[T], tools, max_steps, cancel_event) -> T:
        from ..config import get_settings

        max_steps = max_steps or get_settings().ai_agent_max_steps
        by_name = {t.name: t for t in tools}
        tool_specs = [t.openai_schema() for t in tools]
        dev = (
            developer
            + "\n\nYou may call the provided tools to gather evidence before "
            "answering. When you have enough information, reply with ONLY the final "
            "JSON object for the required schema and make no further tool calls."
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"[developer instructions]\n{dev}"},
            {"role": "user", "content": user},
        ]
        last_error = "no final answer produced"
        for step in range(max_steps):
            if cancel_event is not None and cancel_event.is_set():
                raise LLMCancelled("cancelled")
            msg = self._chat_step(messages, tool_specs)
            calls = msg.get("tool_calls") or []
            if calls:
                messages.append(
                    {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
                )
                for tc in calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    spec = by_name.get(name)
                    try:
                        tool_result = spec.run(_parse_tool_args(fn.get("arguments"))) if spec else {
                            "error": f"unknown tool '{name}'"
                        }
                    except Exception as exc:  # tools must never crash the loop
                        tool_result = {"error": f"{type(exc).__name__}: {exc}"}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": name,
                            "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:8000],
                        }
                    )
                log_event(
                    logger, "ai.agent_step", step=step + 1,
                    tools=[(c.get("function") or {}).get("name") for c in calls],
                )
                continue
            # No tool call -> treat the message as the final answer.
            data = _extract_json(msg.get("content") or "")
            if data is not None:
                try:
                    result = schema.model_validate(data)
                    log_event(logger, "ai.agent_done", schema=schema.__name__, steps=step + 1)
                    return result
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.errors()[:2]}"
            else:
                last_error = "response was not valid JSON"
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous response was invalid ({last_error}). Reply with "
                        "ONLY a valid JSON object matching the required schema — no prose, "
                        "no markdown, no tool calls."
                    ),
                }
            )
        # Step budget exhausted -> one clean single-shot as a last resort.
        log_event(
            logger, "ai.agent_exhausted", level=logging.WARNING,
            schema=schema.__name__, reason=str(last_error)[:120],
        )
        return self.complete_json(system=system, developer=developer, user=user, schema=schema, cancel_event=cancel_event)

    def _chat_step(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        """One non-streaming chat turn with tools; returns the assistant message."""
        base = self.config.base_url.rstrip("/") + "/"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": self.config.max_output_tokens,
            "tools": tool_specs,
            "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        log_event(
            logger, "ai.call", provider="openai", host=_host(base), model=self.config.model,
            messages=len(messages), prompt_chars=_msg_chars(messages), tools=len(tool_specs),
        )
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                resp = _post_with_retry(client, "chat/completions", payload, headers)
                if resp.status_code == 400:
                    body = (resp.text or "").lower()
                    if any(k in body for k in ("tool", "function", "not supported", "unsupported", "unrecognized")):
                        raise _ToolsUnsupported(_explain_http_error(resp))
                    raise LLMError(_explain_http_error(resp))
                if resp.status_code >= 400:
                    raise LLMError(_explain_http_error(resp))
                data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            usage = data.get("usage") or {}
            record_usage(self.config.model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
            log_event(
                logger, "ai.done", provider="openai", model=self.config.model,
                ms=round((time.perf_counter() - t0) * 1000, 1), finish=choice.get("finish_reason"),
                prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                tool_calls=len(msg.get("tool_calls") or []),
            )
            return msg
        except (_ToolsUnsupported, LLMError):
            raise
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"agentic request failed: {exc}") from exc
