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
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..settings_store import AIConfig, get_ai_config

logger = logging.getLogger("docforge.ai")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the model cannot be reached or cannot produce valid output."""


class LLMCancelled(LLMError):
    """Raised when an in-flight LLM call is aborted via its cancellation Event.

    Distinct from LLMError so callers can mark the job *cancelled* rather than
    silently fall back to heuristics (which would defeat the cancel).
    """


# Bases that 400'd on response_format=json_object (e.g. LM Studio expects
# json_schema/text). Cached per-process so we stop re-sending the rejected field.
_JSON_MODE_UNSUPPORTED: set[str] = set()


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
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        acc: list[str] = []
        cancelled = False
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                with client.stream("POST", "chat/completions", json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise LLMError(_explain_http_error(resp))
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
        return "".join(acc)

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
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                resp = client.post("chat/completions", json=payload, headers=headers)
                # Some servers (e.g. LM Studio) reject json_object -> retry as plain
                # text and remember not to send it again to this base.
                if resp.status_code == 400 and use_json:
                    _JSON_MODE_UNSUPPORTED.add(base)
                    payload.pop("response_format", None)
                    resp = client.post("chat/completions", json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise LLMError(_explain_http_error(resp))
                data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError) as exc:
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
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                resp = client.post(f"{base}/v1/messages", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except (httpx.HTTPError, KeyError, IndexError) as exc:
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
        for _ in range(self.config.max_retries + 1):
            raw = _raw(messages)
            data = _extract_json(raw)
            if data is not None:
                try:
                    return schema.model_validate(data)
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.errors()[:3]}"
            else:
                last_error = "response was not valid JSON"
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
        raise LLMError(f"LLM did not return valid JSON after retries: {last_error}")
