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


# Endpoints that rejected response_format=json_object (e.g. LM Studio expects
# json_schema/text). Cached per-process so we stop re-sending the rejected field.
_JSON_MODE_UNSUPPORTED: set[tuple[str, str]] = set()

# Endpoints that rejected a tool-calling request (no function-calling support).
# Cached so agentic calls transparently fall back to single-shot JSON for them.
_TOOLS_UNSUPPORTED: set[tuple[str, str]] = set()


def _capability_key(base: str, model: str) -> tuple[str, str]:
    """What a learned capability applies to: one model at one endpoint.

    Keying on the base URL alone is right for a single-vendor endpoint and wrong
    for a gateway — OpenRouter serves hundreds of models from one base, so one
    model that cannot do tools would otherwise disable tools for every model in
    the process until it restarted.
    """
    return (base, model or "")


# Transient server-side conditions worth retrying: rate limits, overload, and the
# timeouts a slow reasoning model draws from proxies in front of it (Cloudflare
# answers 524 when the origin is still thinking).
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 524, 529}

# How an endpoint says "I cannot do what you asked for". A single-vendor server
# validates the field and answers 400 (or 422); a gateway asked to route only to
# upstreams supporting it answers 404 "no endpoints found". Treating 404 as fatal
# is what turned "this model has no tool support" into "AI failed entirely".
_CAPABILITY_REJECTED = {400, 404, 422}
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


# Reasoning wrappers seen in the wild. Servers that surface the chain of thought
# inline use one of these; the ones that return it as a separate response field
# are handled in _message_text instead.
_THINK_TAGS = ("think", "thinking", "reasoning")
_THINK_BLOCK = re.compile(
    r"<(" + "|".join(_THINK_TAGS) + r")>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_THINK_OPEN = re.compile(r"<(" + "|".join(_THINK_TAGS) + r")>", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove reasoning blocks emitted by models like Qwen3 or Nemotron.

    Handles both the closed ``<think>…</think>`` form and the *unclosed* form
    (an opening tag with no matching close — common when generation is truncated
    mid-thought), where everything from the tag onward is reasoning that
    contains no JSON.
    """
    text = _THINK_BLOCK.sub("", text)
    opened = _THINK_OPEN.search(text)
    if opened:
        text = text[: opened.start()]
    return text.strip()


def _payload_candidates(text: str) -> list[str]:
    """The plausible answer payloads in ``text``, best first.

    Normally that is just "everything outside the reasoning block". But a model
    can open a reasoning tag and never close it *and still answer* — dropping
    everything from the tag onward is right when the generation was cut off
    mid-thought and wrong when it was not, and only trying to parse both tells
    them apart.
    """
    out = [_strip_thinking(text)]
    opened = _THINK_OPEN.search(_THINK_BLOCK.sub("", text))
    if opened:
        remainder = _THINK_BLOCK.sub("", text)[opened.end():].strip()
        if remainder:
            out.append(remainder)
    return [c for c in out if c]


def _relax_json(text: str) -> str:
    """Drop comments and trailing commas — outside string literals.

    Both are things a model emits and ``json.loads`` refuses. Comments are partly
    learned behaviour: our own prompts show the response schema as pseudo-JSON
    annotated with ``//`` notes, and smaller open models mirror that style back.
    Scanning for string state is what keeps a ``//`` inside a URL intact.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                nl = text.find("\n", i)
                i = n if nl == -1 else nl
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            # A comma before a closer is trailing; one at the very end of a
            # truncated document is not — the repair pass wants to see it.
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


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


def _parse_json_payload(cleaned: str) -> dict | list | None:
    """Parse one candidate payload, forgiving the ways models get JSON wrong.

    Order matters: try a clean parse, then relax comments and trailing commas,
    then narrow using the document's *own* first structural bracket (so a
    truncated object never gets mis-read as one of its inner arrays), then
    attempt a structural repair of a truncated document, and only as a last
    resort fall back to any-bracket narrowing.
    """
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    for candidate in (cleaned, _relax_json(cleaned)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    cleaned = _relax_json(cleaned)

    # The FIRST structural bracket is the document's own, wherever the model put
    # it — a model that thinks out loud before answering prefixes prose, and
    # requiring the bracket to lead the string threw that response away.
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if starts:
        start = min(starts)
        close = "}" if cleaned[start] == "{" else "]"
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


def _extract_json(text: str) -> dict | list | None:
    """Best-effort extraction of a JSON object/array from a model response."""
    if not text:
        return None
    for cleaned in _payload_candidates(text):
        obj = _parse_json_payload(cleaned)
        if obj is not None:
            return obj
    return None


def _message_text(msg: dict) -> str:
    """The answer in an assistant message.

    Normally ``content``. A reasoning model served through a gateway returns its
    chain of thought in a separate ``reasoning`` (or ``reasoning_content``) field
    — and when it spends its whole budget thinking, ``content`` comes back empty
    while the only thing resembling an answer sits in there. Reading it as a
    fallback turns "no JSON after three retries" into a usable response; reading
    it *first* would feed the model's own deliberation to the parser, so it is
    strictly a fallback.
    """
    content = (msg.get("content") or "").strip()
    if content:
        return content
    for key in ("reasoning", "reasoning_content"):
        value = msg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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

    # ----- request shaping (OpenAI-compatible) ---------------------------
    def _endpoint(self) -> str:
        return self.config.base_url.rstrip("/") + "/"

    def _cap_key(self) -> tuple[str, str]:
        return _capability_key(self._endpoint(), self.config.model)

    def _is_gateway(self) -> bool:
        """Whether the endpoint routes one request across several providers.

        A gateway picks the upstream per request, so a capability the *model*
        advertises is not necessarily one the chosen upstream implements — the
        request has to say it needs it.
        """
        return "openrouter.ai" in _host(self.config.base_url).lower()

    def _headers(self) -> dict:
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if self._is_gateway():
            # OpenRouter attributes usage to the app that sent it. Neither header
            # is required, and neither carries anything about the user.
            headers["HTTP-Referer"] = "https://docforge.app"
            headers["X-Title"] = "DocForge"
        return headers

    def _base_payload(self, messages: list[dict], temperature: float) -> dict:
        payload: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.config.max_output_tokens,
        }
        effort = (self.config.tier_reasoning_effort or "").strip()
        if effort:
            payload["reasoning"] = {"effort": effort}
        return payload

    def _with_json_mode(self, payload: dict) -> dict:
        """Ask for JSON, and on a gateway insist the upstream can actually do it.

        Without ``require_parameters`` a gateway silently drops an unsupported
        ``response_format`` and answers in prose — the request succeeds, so
        nothing is ever added to the unsupported cache, and every response has to
        be salvaged by the parser instead.
        """
        payload["response_format"] = {"type": "json_object"}
        if self._is_gateway():
            provider = dict(payload.get("provider") or {})
            provider["require_parameters"] = True
            payload["provider"] = provider
        return payload

    def _json_mode_ok(self, json_mode: bool) -> bool:
        return json_mode and self._cap_key() not in _JSON_MODE_UNSUPPORTED

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
        self,
        messages: list[dict],
        *,
        on_delta=None,
        temperature: float | None = None,
        cancel_event=None,
        json_mode: bool = False,
    ) -> str:
        """Stream an OpenAI-compatible completion for live progress.

        Calls ``on_delta(chunk, accumulated)`` per content chunk and returns the
        full text. Used so the UI can show the model working token-by-token.

        When ``cancel_event`` is set mid-stream we break out of the read loop;
        exiting the ``with client.stream(...)`` block closes the TCP connection,
        which signals the model server to **stop generating** rather than run to
        completion. We then raise ``LLMCancelled``.
        """
        temperature = self.config.temperature if temperature is None else temperature
        messages = self._apply_no_think(messages)
        if not self.active:
            raise LLMError("LLM client is not active")
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled before request")
        base = self._endpoint()
        payload = self._base_payload(messages, temperature)
        payload["stream"] = True
        # Ask for a final usage chunk so streamed calls still report tokens.
        payload["stream_options"] = {"include_usage": True}
        # This is the *cancellable* path, which is the one every analysis job
        # takes — so leaving JSON mode off here meant the app's largest and most
        # schema-sensitive calls were the ones asking for JSON by prose alone.
        use_json = self._json_mode_ok(json_mode)
        if use_json:
            self._with_json_mode(payload)
        headers = self._headers()
        acc: list[str] = []
        # A reasoning model streams its chain of thought in a separate field.
        # Kept aside rather than mixed into the answer, and used only if the
        # model finished without emitting any content at all.
        thinking: list[str] = []
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
                        chunk = choices[0].get("delta") or {}
                        delta = chunk.get("content")
                        if delta:
                            acc.append(delta)
                            if on_delta is not None:
                                on_delta(delta, "".join(acc))
                            continue
                        for key in ("reasoning", "reasoning_content"):
                            part = chunk.get(key)
                            if isinstance(part, str) and part:
                                thinking.append(part)
                                break
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
        if not acc and thinking:
            log_event(
                logger, "ai.answer_from_reasoning", level=logging.WARNING,
                model=self.config.model, chars=sum(len(t) for t in thinking),
            )
            return "".join(thinking)
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
                if resp.status_code in _CAPABILITY_REJECTED and "response_format" in payload:
                    # The endpoint cannot guarantee JSON. Drop the ask, remember
                    # it for this model, and let the next attempt run as prose —
                    # the parser handles that, an exception does not.
                    resp.read()
                    _JSON_MODE_UNSUPPORTED.add(self._cap_key())
                    payload.pop("response_format", None)
                    payload.pop("provider", None)
                    log_event(
                        logger, "ai.json_mode_unsupported", level=logging.WARNING,
                        host=_host(self.config.base_url), model=self.config.model,
                        status=resp.status_code, streaming=True,
                    )
                    continue
                if resp.status_code >= 400:
                    resp.read()
                    raise LLMError(_explain_http_error(resp))
                yield resp
                return
        assert last is not None
        raise LLMUnavailable(_explain_http_error(last))

    # ----- transport ------------------------------------------------------
    def complete(
        self, messages: list[dict], *, temperature: float | None = None, json_mode: bool = True
    ) -> str:
        if not self.active:
            raise LLMError("LLM client is not active (configure a provider + API key)")
        temperature = self.config.temperature if temperature is None else temperature
        messages = self._apply_no_think(messages)
        if self.config.provider == "anthropic":
            return self._complete_anthropic(messages, temperature)
        return self._complete_openai(messages, temperature, json_mode)

    def _complete_openai(self, messages: list[dict], temperature: float, json_mode: bool) -> str:
        base = self._endpoint()
        use_json = self._json_mode_ok(json_mode)
        payload = self._base_payload(messages, temperature)
        if use_json:
            self._with_json_mode(payload)
        headers = self._headers()
        log_event(
            logger, "ai.call", provider="openai", host=_host(base), model=self.config.model,
            messages=len(messages), prompt_chars=_msg_chars(messages), json_mode=use_json,
        )
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                resp = _post_with_retry(client, "chat/completions", payload, headers)
                # Some servers (LM Studio) reject json_object outright; a gateway
                # asked to guarantee it answers 404 when no upstream can. Either
                # way: retry as plain text and stop asking this model for it.
                if use_json and resp.status_code in _CAPABILITY_REJECTED:
                    _JSON_MODE_UNSUPPORTED.add(self._cap_key())
                    payload.pop("response_format", None)
                    payload.pop("provider", None)
                    log_event(
                        logger, "ai.json_mode_unsupported", level=logging.WARNING,
                        host=_host(base), model=self.config.model, status=resp.status_code,
                    )
                    resp = _post_with_retry(client, "chat/completions", payload, headers)
                if resp.status_code >= 400:
                    raise LLMError(_explain_http_error(resp))
                data = resp.json()
            text = _message_text((data.get("choices") or [{}])[0].get("message") or {})
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
                return self.stream_openai(msgs, cancel_event=cancel_event, json_mode=True)
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

        Returns ``self`` when nothing about the tier differs, else a shallow
        clone — so callers can escalate the hard steps to the reasoning model,
        and let the cheap ones skip thinking, without rebuilding the key/base
        config.
        """
        model = self.config.model_for_tier(tier)
        effort = self.config.reasoning_effort_for_tier(tier)
        if model == self.config.model and effort == self.config.tier_reasoning_effort:
            return self
        return LLMClient(replace(self.config, model=model, tier_reasoning_effort=effort))

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
        if not tools or client.provider == "anthropic" or client._cap_key() in _TOOLS_UNSUPPORTED:
            return client.complete_json(
                system=system, developer=developer, user=user, schema=schema, cancel_event=cancel_event
            )
        try:
            return client._agentic_openai(
                system=system, developer=developer, user=user,
                schema=schema, tools=tools, max_steps=max_steps, cancel_event=cancel_event,
            )
        except _ToolsUnsupported as exc:
            _TOOLS_UNSUPPORTED.add(client._cap_key())
            log_event(
                logger, "ai.tools_unsupported", level=logging.WARNING,
                host=_host(client.config.base_url), model=client.config.model, reason=str(exc)[:120],
            )
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
        # _apply_no_think reached complete() and stream_openai() but not here — so
        # the tool-using calls, which are most of the app's AI work, never got the
        # directive the setting exists to send.
        messages: list[dict] = self._apply_no_think([
            {"role": "system", "content": system},
            {"role": "system", "content": f"[developer instructions]\n{dev}"},
            {"role": "user", "content": user},
        ])
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
            data = _extract_json(_message_text(msg))
            if data is not None:
                try:
                    result = schema.model_validate(data)
                    log_event(logger, "ai.agent_done", schema=schema.__name__, steps=step + 1)
                    return result
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.errors()[:2]}"
            else:
                last_error = "response was not valid JSON"
            messages.append({"role": "assistant", "content": _message_text(msg)})
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
        base = self._endpoint()
        payload = self._base_payload(messages, self.config.temperature)
        payload["tools"] = tool_specs
        payload["tool_choice"] = "auto"
        if self._is_gateway():
            # Route only to upstreams that implement tool calling — otherwise the
            # gateway may pick one that ignores `tools` and answers in prose,
            # burning a step on a repair nudge every time.
            payload["provider"] = {"require_parameters": True}
        headers = self._headers()
        log_event(
            logger, "ai.call", provider="openai", host=_host(base), model=self.config.model,
            messages=len(messages), prompt_chars=_msg_chars(messages), tools=len(tool_specs),
        )
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                resp = _post_with_retry(client, "chat/completions", payload, headers)
                # A single-vendor server validates the field and says 400; a
                # gateway with no tool-capable upstream says 404. Both mean "no
                # tools here", and both must degrade to single-shot rather than
                # abandoning AI for the whole action.
                if resp.status_code in _CAPABILITY_REJECTED:
                    body = (resp.text or "").lower()
                    tool_words = ("tool", "function", "not supported", "unsupported", "unrecognized")
                    if resp.status_code == 404 or any(k in body for k in tool_words):
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
