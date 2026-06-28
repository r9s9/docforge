"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";
import type { AISettings, AIUsage } from "@/lib/types";
import { ErrorBox, Spinner } from "@/components/ui";
import { AlertTriangle, Check, KeyRound, Sparkles, Trash2 } from "@/components/icons";
import LogsPage from "@/components/LogsPage";

type Tab = "ai" | "profile" | "logs";
type UiProvider = "openai" | "anthropic" | "gemini" | "deepseek" | "local";

// Gemini and DeepSeek both speak the OpenAI-compatible Chat Completions API, so
// they ride the backend's "openai" provider path with a different base URL.
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai";
const DEEPSEEK_BASE = "https://api.deepseek.com";

const PROVIDER_DEFAULTS: Record<UiProvider, { base_url: string; model: string }> = {
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  anthropic: { base_url: "https://api.anthropic.com", model: "claude-sonnet-4-6" },
  gemini: { base_url: GEMINI_BASE, model: "gemini-2.5-flash" },
  deepseek: { base_url: DEEPSEEK_BASE, model: "deepseek-chat" },
  local: { base_url: "http://localhost:11434/v1", model: "llama3.1" },
};

// Selectable models per cloud provider (the user picks one instead of typing it).
// Local servers expose arbitrary model names, so that path keeps a free-text box.
const MODEL_OPTIONS: Record<"openai" | "anthropic" | "gemini" | "deepseek", string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
  anthropic: ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
};

// Map a UI provider to the backend provider value it routes through.
function backendProvider(p: UiProvider): "openai" | "anthropic" {
  return p === "anthropic" ? "anthropic" : "openai";
}

function deriveUiProvider(s: AISettings): UiProvider {
  if (s.provider === "anthropic") return "anthropic";
  if (/generativelanguage\.googleapis\.com/.test(s.base_url)) return "gemini";
  if (/deepseek\.com/.test(s.base_url)) return "deepseek";
  if (/localhost|127\.0\.0\.1/.test(s.base_url)) return "local";
  return "openai";
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("ai");

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">AI provider and account management.</p>

      <div className="tabs">
        <div className={`tab ${tab === "ai" ? "active" : ""}`} onClick={() => setTab("ai")}>
          LLM Settings
        </div>
        <div className={`tab ${tab === "logs" ? "active" : ""}`} onClick={() => setTab("logs")}>
          Logs
        </div>
        <div className={`tab ${tab === "profile" ? "active" : ""}`} onClick={() => setTab("profile")}>
          Profile
        </div>
      </div>

      {tab === "ai" && <AISettingsForm />}
      {tab === "logs" && <LogsPage />}
      {tab === "profile" && <ProfileSettings />}
    </div>
  );
}

function ProfileSettings() {
  const { user, signOut } = useAuth();
  const router = useRouter();

  // change password
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // delete account
  const [confirm, setConfirm] = useState("");
  const [delBusy, setDelBusy] = useState(false);
  const [delErr, setDelErr] = useState("");

  async function changePassword() {
    setPwMsg(null);
    if (pw.length < 8) {
      setPwMsg({ ok: false, text: "Password must be at least 8 characters." });
      return;
    }
    if (pw !== pw2) {
      setPwMsg({ ok: false, text: "The two passwords don't match." });
      return;
    }
    setPwBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: pw });
      if (error) throw new Error(error.message);
      setPw("");
      setPw2("");
      setPwMsg({ ok: true, text: "Password updated." });
    } catch (e: any) {
      setPwMsg({ ok: false, text: String(e.message || e) });
    } finally {
      setPwBusy(false);
    }
  }

  async function deleteAccount() {
    setDelErr("");
    setDelBusy(true);
    try {
      await api.deleteAccount();
      await signOut();
      router.replace("/login");
    } catch (e: any) {
      setDelErr(String(e.message || e));
      setDelBusy(false);
    }
  }

  return (
    <div className="section" style={{ maxWidth: 560 }}>
      <h2 className="section-h">Account</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Signed in as <strong>{user?.email || "this device (local mode)"}</strong>.
      </p>

      {/* Change password */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3 style={{ margin: "0 0 4px", display: "inline-flex", alignItems: "center", gap: 8 }}>
          <KeyRound size={16} strokeWidth={1.9} /> Change password
        </h3>
        {!user ? (
          <p className="muted" style={{ marginBottom: 0 }}>
            Password management is handled by your identity provider in local mode.
          </p>
        ) : (
          <>
            <label className="field">
              <span>New password</span>
              <input
                type="password"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                placeholder="At least 8 characters"
                autoComplete="new-password"
              />
            </label>
            <label className="field">
              <span>Confirm new password</span>
              <input
                type="password"
                value={pw2}
                onChange={(e) => setPw2(e.target.value)}
                autoComplete="new-password"
              />
            </label>
            <div className="row">
              <button className="btn" onClick={changePassword} disabled={pwBusy}>
                {pwBusy ? <Spinner /> : "Update password"}
              </button>
              {pwMsg && (
                <span
                  style={{
                    color: pwMsg.ok ? "var(--green)" : "var(--red)",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  {pwMsg.ok && <Check size={15} strokeWidth={2.4} />} {pwMsg.text}
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {/* Danger zone */}
      <div className="card" style={{ marginTop: 16, borderColor: "var(--red)" }}>
        <h3 style={{ margin: "0 0 4px", color: "var(--red)", display: "inline-flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={16} strokeWidth={2} /> Delete account
        </h3>
        <p className="muted" style={{ marginTop: 4 }}>
          Permanently deletes your account and <strong>everything</strong> in it — all
          templates, projects, generated documents, and uploaded files. This cannot be
          undone.
        </p>
        {delErr && <ErrorBox message={delErr} />}
        <label className="field">
          <span>
            Type <span className="mono">DELETE</span> to confirm
          </span>
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="DELETE" />
        </label>
        <button
          className="btn"
          onClick={deleteAccount}
          disabled={delBusy || confirm.trim() !== "DELETE"}
          style={{ background: "var(--red)", borderColor: "var(--red)", color: "#fff" }}
        >
          {delBusy ? <Spinner label="Deleting…" /> : (
            <>
              <Trash2 size={15} strokeWidth={1.9} /> Delete my account &amp; all files
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function FreeTierBanner({ usage }: { usage: AIUsage }) {
  // Nothing to show when the platform free tier isn't offered.
  if (!usage.free_enabled) return null;

  // Once the user has their own key, the free allowance no longer applies.
  if (usage.has_own_key) {
    return (
      <div className="notice section" style={{ borderColor: "var(--green)", marginTop: 0 }}>
        <strong style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Check size={15} strokeWidth={2.4} /> Using your own API key
        </strong>{" "}
        — unlimited AI. The free allowance no longer applies.
      </div>
    );
  }

  const { free_remaining, free_limit, free_used } = usage;
  const out = free_remaining <= 0;
  return (
    <div
      className="notice section"
      style={{ borderColor: out ? "var(--amber)" : "var(--accent)", marginTop: 0 }}
    >
      <strong style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <Sparkles size={15} strokeWidth={2} />
        {out
          ? "You've used all your free AI actions"
          : `${free_remaining} of ${free_limit} free AI actions left`}
      </strong>
      <div className="muted" style={{ marginTop: 6 }}>
        {out ? (
          <>
            Add your own API key below to keep using AI. Without one, DocForge
            switches to its offline heuristic engine (no AI). Used {free_used}/
            {free_limit}.
          </>
        ) : (
          <>
            Every account gets {free_limit} free AI actions (template analysis and
            document generation), powered by the platform. After that, add your own
            API key below for unlimited use.
          </>
        )}
      </div>
      <div className="conf-bar" style={{ marginTop: 10, maxWidth: 320 }}>
        <i style={{ width: `${Math.min(100, (free_used / Math.max(1, free_limit)) * 100)}%` }} />
      </div>
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
  const [usage, setUsage] = useState<AIUsage | null>(null);

  useEffect(() => {
    api
      .getAISettings()
      .then(({ ai, usage }) => {
        setProvider(deriveUiProvider(ai));
        setBaseUrl(ai.base_url);
        setModel(ai.model);
        setEnabled(ai.enabled);
        setNoThink(ai.no_think ?? false);
        setHasKey(ai.has_key);
        setUsage(usage);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  function changeProvider(p: UiProvider) {
    setProvider(p);
    setBaseUrl(PROVIDER_DEFAULTS[p].base_url);
    // Default to the first selectable model for cloud providers.
    setModel(p === "local" ? PROVIDER_DEFAULTS.local.model : MODEL_OPTIONS[p][0]);
    setTestResult(null);
  }

  // Model dropdown options for the current cloud provider, always including the
  // currently-stored model so an existing/custom value still shows up.
  const modelChoices =
    provider === "local" ? [] : Array.from(new Set([...MODEL_OPTIONS[provider], model].filter(Boolean)));

  function payload() {
    const body: Record<string, unknown> = {
      provider: backendProvider(provider),
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
      const { ai, usage } = await api.updateAISettings(payload());
      setHasKey(ai.has_key);
      setUsage(usage);
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
      {usage && <FreeTierBanner usage={usage} />}
      <h2 className="section-h">Your AI Provider</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Pick a provider and paste your API key — that&apos;s all you need. Leave
        disabled to use the free allowance (if any) or the offline heuristic
        engine. Your key is stored server-side and never returned.
      </p>

      <label className="field">
        <span>Provider</span>
        <select value={provider} onChange={(e) => changeProvider(e.target.value as UiProvider)}>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Google Gemini</option>
          <option value="deepseek">DeepSeek</option>
          <option value="local">Local (OpenAI-compatible: Ollama, LM Studio…)</option>
        </select>
      </label>

      <label className="field">
        <span>
          API Key {hasKey && <span className="muted">(stored — leave blank to keep)</span>}
        </span>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            hasKey
              ? "••••••••"
              : provider === "anthropic"
                ? "sk-ant-…"
                : provider === "gemini"
                  ? "AIza…"
                  : provider === "local"
                    ? "ollama"
                    : "sk-…"
          }
        />
      </label>

      {provider === "local" ? (
        <>
          <label className="field">
            <span>Base URL</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </label>
          <label className="field">
            <span>Model</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} />
          </label>
        </>
      ) : (
        <label className="field">
          <span>Model</span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {modelChoices.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="field" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input
          type="checkbox"
          style={{ width: "auto" }}
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span style={{ margin: 0 }}>Enable AI (use the model instead of heuristics)</span>
      </label>

      {provider === "local" && (
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
      )}

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
