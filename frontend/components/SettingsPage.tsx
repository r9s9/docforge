"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { publishAiStatus } from "@/lib/useAiStatus";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";
import type { AISettings, AIUsage, TokenTotals } from "@/lib/types";
import { ErrorBox, formatCost, formatTokens, Spinner } from "@/components/ui";
import { AlertTriangle, Check, KeyRound, Sparkles, Trash2 } from "@/components/icons";
import LogsPage from "@/components/LogsPage";

type Tab = "ai" | "profile" | "logs";
type UiProvider = "openrouter" | "openai" | "anthropic" | "gemini" | "deepseek" | "local";

// OpenRouter, Gemini and DeepSeek all speak the OpenAI-compatible Chat
// Completions API, so they ride the backend's "openai" provider path with a
// different base URL.
const OPENROUTER_BASE = "https://openrouter.ai/api/v1";
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai";
const DEEPSEEK_BASE = "https://api.deepseek.com";

const PROVIDER_DEFAULTS: Record<UiProvider, { base_url: string; model: string }> = {
  openrouter: { base_url: OPENROUTER_BASE, model: "nvidia/nemotron-3-super-120b-a12b" },
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  anthropic: { base_url: "https://api.anthropic.com", model: "claude-sonnet-4-6" },
  gemini: { base_url: GEMINI_BASE, model: "gemini-3.1-flash-lite" },
  deepseek: { base_url: DEEPSEEK_BASE, model: "deepseek-chat" },
  local: { base_url: "http://localhost:11434/v1", model: "llama3.1" },
};

// Selectable models per cloud provider (the user picks one instead of typing it).
// Local servers expose arbitrary model names, so that path keeps a free-text box.
const MODEL_OPTIONS: Record<Exclude<UiProvider, "local">, string[]> = {
  // NVIDIA Nemotron 3: Ultra for the agentic steps, Super for the volume.
  openrouter: [
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning",
    "nvidia/nemotron-3-nano-30b-a3b",
  ],
  openai: ["gpt-5-nano", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini", "gpt-4o"],
  anthropic: ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"],
  // Newest first: the list is a menu, and the top of it is what people pick.
  gemini: [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
  ],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
};

// What a key for each provider looks like, so a wrong paste is obvious before
// saving. The backend refuses a key with the wrong shape for its endpoint.
const KEY_PLACEHOLDERS: Record<UiProvider, string> = {
  openrouter: "sk-or-…",
  openai: "sk-…",
  anthropic: "sk-ant-…",
  gemini: "AIza…",
  deepseek: "sk-…",
  local: "ollama",
};

// Recommended "reasoning" model per provider — used only for the harder agentic
// steps (document understanding, self-critique, value composition, compliance).
const REASONING_DEFAULTS: Record<Exclude<UiProvider, "local">, string> = {
  openrouter: "nvidia/nemotron-3-ultra-550b-a55b",
  openai: "gpt-5-mini",
  anthropic: "claude-sonnet-4-6",
  gemini: "gemini-3.5-flash",
  deepseek: "deepseek-reasoner",
};

// The shipped recommendation: Nemotron 3 Super for the volume of mechanical
// calls, Nemotron 3 Ultra for the agentic steps that decide what the document
// says. Same family, so the two tiers behave alike.
const RECOMMENDED = {
  provider: "openrouter" as UiProvider,
  base_url: OPENROUTER_BASE,
  model: "nvidia/nemotron-3-super-120b-a12b",
  reasoning_model: "nvidia/nemotron-3-ultra-550b-a55b",
};

// Map a UI provider to the backend provider value it routes through.
function backendProvider(p: UiProvider): "openai" | "anthropic" {
  return p === "anthropic" ? "anthropic" : "openai";
}

// Two base URLs naming the same endpoint (mirrors ai_keys.normalize_endpoint on
// the server, which is what decides where a key is filed).
function sameEndpoint(a: string, b: string): boolean {
  const norm = (s: string) => (s || "").trim().replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

function deriveUiProvider(s: AISettings): UiProvider {
  if (s.provider === "anthropic") return "anthropic";
  if (/openrouter\.ai/.test(s.base_url)) return "openrouter";
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
          Permanently deletes your account and <strong>everything</strong> in it: all
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
        gives unlimited AI. The free allowance no longer applies.
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

function TokenTotalsPanel({ tokens }: { tokens: TokenTotals }) {
  const cost = formatCost(tokens.cost_usd);
  return (
    <div className="notice section" style={{ marginTop: 0 }}>
      <strong style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <Sparkles size={15} strokeWidth={2} /> AI usage so far
      </strong>
      <div className="muted" style={{ marginTop: 6 }}>
        {formatTokens(tokens.in)} input + {formatTokens(tokens.out)} output tokens across{" "}
        {tokens.actions} action{tokens.actions === 1 ? "" : "s"}
        {cost ? <> · estimated {cost}</> : null}.
      </div>
    </div>
  );
}

function AISettingsForm() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [provider, setProvider] = useState<UiProvider>("gemini");
  const [baseUrl, setBaseUrl] = useState(PROVIDER_DEFAULTS.gemini.base_url);
  const [model, setModel] = useState(RECOMMENDED.model);
  const [reasoningModel, setReasoningModel] = useState(RECOMMENDED.reasoning_model);
  const [apiKey, setApiKey] = useState("");
  // Set only by a real typing/paste gesture. A password manager writes .value
  // directly, which fires onChange but never onBeforeInput — so this is what
  // separates "the user entered a key" from "something filled the box in".
  const [keyTyped, setKeyTyped] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [noThink, setNoThink] = useState(false);
  const [savedEndpoints, setSavedEndpoints] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saved, setSaved] = useState(false);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [tokens, setTokens] = useState<TokenTotals | null>(null);

  useEffect(() => {
    api
      .getAISettings()
      .then(({ ai, usage, tokens }) => {
        setProvider(deriveUiProvider(ai));
        setBaseUrl(ai.base_url);
        setModel(ai.model);
        setReasoningModel(ai.reasoning_model || "");
        setEnabled(ai.enabled);
        setNoThink(ai.no_think ?? false);
        setSavedEndpoints(ai.saved_endpoints ?? []);
        setUsage(usage);
        setTokens(tokens ?? null);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  function changeProvider(p: UiProvider) {
    setProvider(p);
    setBaseUrl(PROVIDER_DEFAULTS[p].base_url);
    // Default to the first selectable model for cloud providers.
    setModel(p === "local" ? PROVIDER_DEFAULTS.local.model : MODEL_OPTIONS[p][0]);
    setReasoningModel(p === "local" ? "" : REASONING_DEFAULTS[p]);
    // A key typed for the provider being left is not a key for this one. The
    // one already stored for this endpoint (if any) stays where it is.
    setApiKey("");
    setKeyTyped(false);
    setTestResult(null);
  }

  // One-click "recommended": the cheap-but-capable Gemini tiered setup.
  function applyRecommended() {
    setProvider(RECOMMENDED.provider);
    setBaseUrl(RECOMMENDED.base_url);
    setModel(RECOMMENDED.model);
    setReasoningModel(RECOMMENDED.reasoning_model);
    setEnabled(true);
    setTestResult(null);
  }

  // Model dropdown options for the current cloud provider, always including the
  // currently-stored model so an existing/custom value still shows up.
  const modelChoices =
    provider === "local" ? [] : Array.from(new Set([...MODEL_OPTIONS[provider], model].filter(Boolean)));
  const reasoningChoices =
    provider === "local"
      ? []
      : Array.from(new Set([...MODEL_OPTIONS[provider], reasoningModel].filter(Boolean)));

  // Keys are stored per endpoint, so "do I have a key?" has to be asked of the
  // endpoint currently selected — otherwise switching provider leaves the form
  // claiming a key that belongs to the provider just left.
  const hasKeyHere = savedEndpoints.some((e) => sameEndpoint(e, baseUrl));
  const savedElsewhere = savedEndpoints.filter((e) => !sameEndpoint(e, baseUrl));

  function payload() {
    const body: Record<string, unknown> = {
      provider: backendProvider(provider),
      base_url: baseUrl,
      model,
      reasoning_model: reasoningModel,
      enabled,
      no_think: noThink,
    };
    // Only a key the user actually entered is sent. A blank box means "keep what
    // is stored", and an autofilled one means nothing at all.
    if (apiKey && keyTyped) body.api_key = apiKey;
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
      const { ai, usage, tokens } = await api.updateAISettings(payload());
      setSavedEndpoints(ai.saved_endpoints ?? []);
      setUsage(usage);
      // The sidebar and the page banners read a shared snapshot; without this
      // they keep naming the old model until a full page reload.
      publishAiStatus({ ai, usage });
      setTokens(tokens ?? null);
      setApiKey("");
      setKeyTyped(false);
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
      {tokens && tokens.actions > 0 && <TokenTotalsPanel tokens={tokens} />}
      <h2 className="section-h">Your AI Provider</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        DocForge uses <strong>your own</strong> provider key for every AI step. The
        recommended setup is <strong>NVIDIA Nemotron 3</strong> on OpenRouter, tiered:
        a cheap workhorse model for routine work plus a stronger reasoning model for
        the harder agent steps. Your key is stored server-side and never returned,
        and each provider keeps its own, so switching between them never loses one.
      </p>

      <div className="notice section" style={{ marginTop: 0 }}>
        <strong style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Sparkles size={15} strokeWidth={2} /> Recommended: Nemotron 3 (tiered)
        </strong>
        <div className="muted" style={{ margin: "6px 0 10px" }}>
          <span className="mono">nemotron-3-super</span> for routine steps +{" "}
          <span className="mono">nemotron-3-ultra</span> for reasoning. Ultra is built
          for tool use across long documents, which is what the harder steps here do;
          Super costs about a sixth as much and handles the volume.{" "}
          <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">
            Get an OpenRouter API key →
          </a>
        </div>
        <button type="button" className="btn secondary small" onClick={applyRecommended}>
          Use recommended setup
        </button>
      </div>

      <label className="field">
        <span>Provider</span>
        <select value={provider} onChange={(e) => changeProvider(e.target.value as UiProvider)}>
          <option value="openrouter">OpenRouter (NVIDIA Nemotron, and most others)</option>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Google Gemini</option>
          <option value="deepseek">DeepSeek</option>
          <option value="local">Local (OpenAI-compatible: Ollama, LM Studio…)</option>
        </select>
      </label>

      <label className="field">
        <span>
          API Key {hasKeyHere && <span className="muted">(stored, leave blank to keep)</span>}
        </span>
        <input
          // Deliberately NOT type="password". This is a provider API key, and a
          // password manager filling it with an unrelated saved credential used
          // to overwrite the real key on the next save — invisibly, because the
          // field was masked. Chrome and Edge ignore autoComplete="off" on
          // password inputs, so the only reliable fix is to stop being one:
          // masking is done in CSS instead (.masked-input), which keeps the
          // value hidden while leaving the field outside password-manager scope.
          type="text"
          className="masked-input"
          name="docforge-ai-provider-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          // Autofill sets .value without an input gesture, so a key is only sent
          // when this fires. See payload().
          onBeforeInput={() => setKeyTyped(true)}
          onPaste={() => setKeyTyped(true)}
          autoComplete="new-password"
          spellCheck={false}
          autoCorrect="off"
          autoCapitalize="off"
          data-1p-ignore
          data-lpignore="true"
          data-bwignore="true"
          placeholder={hasKeyHere ? "••••••••" : KEY_PLACEHOLDERS[provider]}
        />
        {savedElsewhere.length > 0 && !hasKeyHere && (
          <span className="muted small">
            You already have a key saved for {savedElsewhere.join(", ")}. Switching back there
            will reuse it.
          </span>
        )}
      </label>

      <label className="field">
        <span>
          Base URL{" "}
          <span className="muted">(the preset for your provider; change it for any
          other OpenAI compatible endpoint)</span>
        </span>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </label>

      {provider === "local" ? (
        <label className="field">
          <span>Model</span>
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
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

      {provider === "local" ? (
        <label className="field">
          <span>
            Reasoning model <span className="muted">(optional, used for harder steps)</span>
          </span>
          <input
            value={reasoningModel}
            onChange={(e) => setReasoningModel(e.target.value)}
            placeholder="Leave blank to reuse the model above"
          />
        </label>
      ) : (
        <label className="field">
          <span>
            Reasoning model{" "}
            <span className="muted">(harder steps: understanding, critique, composition)</span>
          </span>
          <select value={reasoningModel} onChange={(e) => setReasoningModel(e.target.value)}>
            <option value="">Same as model above</option>
            {reasoningChoices.map((m) => (
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
              prepends <span className="mono">/no_think</span> for Qwen3 and strips{" "}
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
