"""Where a user's provider API keys live.

One person routinely holds several: an OpenRouter key, a Gemini key, a local
server's placeholder. Switching model in the Settings page must not cost them
the key for the endpoint they just left, so keys are stored **per endpoint**
rather than one at a time.

The map lives in the existing ``user_ai_configs.api_key`` TEXT column, JSON
encoded. That column also still accepts a bare string, which is what every row
written before this module holds. Keeping the map in place rather than adding a
column is deliberate: ``user_ai_configs`` is absent from the Alembic migration
and ``init_db`` is skipped on serverless hosts, so a new column would simply be
missing in production until someone remembered to run DDL by hand.

Nothing here ever returns a key to a client. The settings endpoint exposes only
which endpoints have one.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit


def normalize_endpoint(base_url: str | None) -> str:
    """Canonical form of a base URL, so one endpoint means one key.

    Trailing slashes and letter case differ between what a preset writes and
    what someone pastes; without normalizing, the same endpoint would hold two
    keys and which one applied would depend on how it happened to be typed.
    """
    text = (base_url or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.lower()
    if not parts.scheme or not parts.netloc:
        return text.lower()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _as_map(raw: str) -> dict | None:
    """The stored value parsed as an endpoint map, or None if it is a bare key."""
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def stored_keys(raw: str | None, legacy_base: str | None = None) -> dict[str, str]:
    """endpoint -> key.

    A value written before this module is a bare key; it belongs to
    ``legacy_base``, the base URL the row was pointing at when it was saved.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    data = _as_map(text)
    if data is None:
        endpoint = normalize_endpoint(legacy_base)
        return {endpoint: text} if endpoint else {}
    out: dict[str, str] = {}
    for endpoint, key in data.items():
        ep = normalize_endpoint(str(endpoint))
        val = str(key or "").strip()
        if ep and val:
            out[ep] = val
    return out


def key_for(raw: str | None, base_url: str | None) -> str:
    """The key to use when talking to ``base_url`` — empty when there is none.

    A bare legacy value answers for every endpoint: it is the only key the row
    has ever held, and refusing it would log the user out of their own AI the
    moment they upgraded.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if _as_map(text) is None:
        return text
    return stored_keys(text).get(normalize_endpoint(base_url), "")


def with_key(
    raw: str | None, base_url: str | None, key: str, *, legacy_base: str | None = None
) -> str:
    """The new column value after saving ``key`` for ``base_url``.

    ``legacy_base`` is the row's base URL *before* this save, so a bare legacy
    key keeps the endpoint it actually belongs to even when the same request
    also repoints the row somewhere else.
    """
    keys = stored_keys(raw, legacy_base if legacy_base is not None else base_url)
    endpoint = normalize_endpoint(base_url)
    value = (key or "").strip()
    if endpoint and value:
        keys[endpoint] = value
    return json.dumps(keys, separators=(",", ":")) if keys else ""


def forget_key(raw: str | None, base_url: str | None, *, legacy_base: str | None = None) -> str:
    """The new column value with the key for ``base_url`` removed."""
    keys = stored_keys(raw, legacy_base if legacy_base is not None else base_url)
    keys.pop(normalize_endpoint(base_url), None)
    return json.dumps(keys, separators=(",", ":")) if keys else ""


# Host -> (required prefix, what to tell the user). Only endpoints with a
# published, stable key prefix appear here.
_KEY_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("openrouter.ai", "sk-or-", "OpenRouter keys start with “sk-or-”"),
    ("api.anthropic.com", "sk-ant-", "Anthropic keys start with “sk-ant-”"),
    ("generativelanguage.googleapis.com", "AIza", "Gemini keys start with “AIza”"),
    ("api.openai.com", "sk-", "OpenAI keys start with “sk-”"),
)


def key_shape_error(base_url: str | None, key: str) -> str | None:
    """Why ``key`` cannot be a key for ``base_url``, or None if it might be.

    This is not validation — a well-formed key can still be revoked, and only
    the provider can say. It exists to refuse the *specific* accident that has
    cost users their key twice now: a browser password manager autofilling an
    unrelated saved credential into a masked field, which the next save then
    writes over the real key. An endpoint whose key format we do not know is
    accepted exactly as typed.
    """
    value = (key or "").strip()
    if not value:
        return None
    host = ""
    try:
        host = (urlsplit((base_url or "").strip()).netloc or "").lower()
    except ValueError:
        host = ""
    for known_host, prefix, advice in _KEY_PREFIXES:
        if host.endswith(known_host):
            if value.startswith(prefix):
                return None
            return (
                f"That does not look like a key for {known_host} — {advice}. "
                "If your browser filled this in for you, clear the box and paste the key yourself."
            )
    return None
