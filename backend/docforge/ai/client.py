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
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..settings_store import AIConfig, get_ai_config

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the model cannot be reached or cannot produce valid output."""


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
    """Remove <think>…</think> blocks emitted by reasoning models (Qwen3, etc.)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict | list | None:
    """Best-effort extraction of a JSON object/array from a model response."""
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

    def stream_openai(self, messages: list[dict], *, on_delta=None, temperature: float = 0.0) -> str:
        """Stream an OpenAI-compatible completion for live progress.

        Calls ``on_delta(chunk, accumulated)`` per content chunk and returns the
        full text. Used so the UI can show the model working token-by-token.
        """
        messages = self._apply_no_think(messages)
        if not self.active:
            raise LLMError("LLM client is not active")
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
        try:
            with httpx.Client(base_url=base, timeout=self.config.timeout_seconds) as client:
                with client.stream("POST", "chat/completions", json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        raise LLMError(_explain_http_error(resp))
                    for line in resp.iter_lines():
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
            return "".join(acc)
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"streaming request failed: {exc}") from exc

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
    def complete_json(self, *, system: str, developer: str, user: str, schema: type[T]) -> T:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"[developer instructions]\n{developer}"},
            {"role": "user", "content": user},
        ]
        last_error = "unknown error"
        for _ in range(self.config.max_retries + 1):
            raw = self.complete(messages)
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
