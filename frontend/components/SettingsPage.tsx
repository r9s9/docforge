"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AISettings } from "@/lib/types";
import { applyTheme, getStoredTheme, type Theme } from "@/lib/theme";
import { ErrorBox, Spinner } from "@/components/ui";
import { Check } from "@/components/icons";

type Tab = "appearance" | "ai";
type UiProvider = "openai" | "anthropic" | "local";

const PROVIDER_DEFAULTS: Record<UiProvider, { base_url: string; model: string }> = {
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  anthropic: { base_url: "https://api.anthropic.com", model: "claude-3-5-sonnet-latest" },
  local: { base_url: "http://localhost:11434/v1", model: "llama3.1" },
};

function deriveUiProvider(s: AISettings): UiProvider {
  if (s.provider === "anthropic") return "anthropic";
  if (/localhost|127\.0\.0\.1/.test(s.base_url)) return "local";
  return "openai";
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("appearance");
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => setTheme(getStoredTheme()), []);

  function chooseTheme(t: Theme) {
    setTheme(t);
    applyTheme(t);
  }

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Appearance and AI provider configuration.</p>

      <div className="tabs">
        <div className={`tab ${tab === "appearance" ? "active" : ""}`} onClick={() => setTab("appearance")}>
          Appearance
        </div>
        <div className={`tab ${tab === "ai" ? "active" : ""}`} onClick={() => setTab("ai")}>
          AI Provider
        </div>
      </div>

      {tab === "appearance" && (
        <div className="section">
          <h2 className="section-h">Theme</h2>
          <div className="row" style={{ gap: 14 }}>
            {(["light", "dark"] as Theme[]).map((t) => (
              <button
                key={t}
                className={`card ${theme === t ? "" : "secondary"}`}
                onClick={() => chooseTheme(t)}
                style={{
                  cursor: "pointer",
                  width: 180,
                  textAlign: "left",
                  borderColor: theme === t ? "var(--accent)" : "var(--border)",
                  borderWidth: 2,
                  background: t === "dark" ? "#0c0c0d" : "#ffffff",
                  color: t === "dark" ? "#f4f4f5" : "#0a0a0b",
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    marginBottom: 6,
                    textTransform: "capitalize",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  {t} mode {theme === t && <Check size={15} strokeWidth={2.4} />}
                </div>
                <div style={{ fontSize: 12, opacity: 0.7 }}>
                  {t === "dark" ? "Charcoal" : "Paper"}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {tab === "ai" && <AISettingsForm />}
    </div>
  );
}

function AISettingsForm() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [provider, setProvider] = useState<UiProvider>("openai");
  const [baseUrl, setBaseUrl] = useState(PROVIDER_DEFAULTS.openai.base_url);
  const [model, setModel] = useState(PROVIDER_DEFAULTS.openai.model);
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [noThink, setNoThink] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getAISettings()
      .then(({ ai }) => {
        setProvider(deriveUiProvider(ai));
        setBaseUrl(ai.base_url);
        setModel(ai.model);
        setEnabled(ai.enabled);
        setNoThink(ai.no_think ?? false);
        setHasKey(ai.has_key);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  function changeProvider(p: UiProvider) {
    setProvider(p);
    setBaseUrl(PROVIDER_DEFAULTS[p].base_url);
    setModel(PROVIDER_DEFAULTS[p].model);
    setTestResult(null);
  }

  function payload() {
    const body: Record<string, unknown> = {
      provider: provider === "local" ? "openai" : provider,
      base_url: baseUrl,
      model,
      enabled,
      no_think: noThink,
    };
    if (apiKey) body.api_key = apiKey;
    return body;
  }

  async function test() {
    setBusy(true);
    setTestResult(null);
    try {
      setTestResult(await api.testAI(payload()));
    } catch (e: any) {
      setTestResult({ ok: false, message: String(e.message || e) });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setSaved(false);
    setError("");
    try {
      const { ai } = await api.updateAISettings(payload());
      setHasKey(ai.has_key);
      setApiKey("");
      setSaved(true);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading settings…" />;

  return (
    <div className="section" style={{ maxWidth: 560 }}>
      {error && <ErrorBox message={error} />}
      <h2 className="section-h">AI Provider</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Leave disabled to use the offline heuristic engine. The API key is stored
        server-side and never returned.
      </p>

      <label className="field">
        <span>Provider</span>
        <select value={provider} onChange={(e) => changeProvider(e.target.value as UiProvider)}>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="local">Local (OpenAI-compatible: Ollama, LM Studio…)</option>
        </select>
      </label>

      <label className="field">
        <span>Base URL</span>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </label>

      <label className="field">
        <span>Model</span>
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </label>

      <label className="field">
        <span>API Key {hasKey && <span className="muted">(stored — leave blank to keep)</span>}</span>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={hasKey ? "••••••••" : "sk-…  (or 'ollama' for local)"}
        />
      </label>

      <label className="field" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input
          type="checkbox"
          style={{ width: "auto" }}
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span style={{ margin: 0 }}>Enable AI (use the model instead of heuristics)</span>
      </label>

      <label className="field" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input
          type="checkbox"
          style={{ width: "auto" }}
          checked={noThink}
          onChange={(e) => setNoThink(e.target.checked)}
        />
        <span style={{ margin: 0 }}>
          Disable thinking{" "}
          <span className="muted">
            — prepends <span className="mono">/no_think</span> for Qwen3 and strips{" "}
            <span className="mono">&lt;think&gt;</span> blocks from all models.
            Recommended for Qwen3.
          </span>
        </span>
      </label>

      <div className="row">
        <button className="btn" onClick={save} disabled={busy}>
          {busy ? <Spinner /> : "Save"}
        </button>
        <button className="btn secondary" onClick={test} disabled={busy}>
          Test connection
        </button>
        {saved && (
          <span style={{ color: "var(--green)", display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Check size={15} strokeWidth={2.4} /> Saved
          </span>
        )}
      </div>

      {testResult && (
        <div className="notice" style={{ marginTop: 16, borderColor: testResult.ok ? "var(--green)" : "var(--red)" }}>
          <strong style={{ color: testResult.ok ? "var(--green)" : "var(--red)" }}>
            {testResult.ok ? "Success" : "Failed"}
          </strong>{" "}
          {testResult.message}
        </div>
      )}
    </div>
  );
}
