"use client";

import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useHealth } from "@/lib/useHealth";
import type { AISettings, AIUsage, TokenUsage } from "@/lib/types";
import { AlertTriangle, Sparkles } from "@/components/icons";

/** Abbreviate a token count: 1234 -> "1.2K", 56000 -> "56K". */
export function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K`;
  return String(n);
}

/** Best-effort cost label, or null when the model price is unknown. */
export function formatCost(c: number | null | undefined): string | null {
  if (c == null) return null;
  return c < 0.01 ? `~$${c.toFixed(4)}` : `~$${c.toFixed(2)}`;
}

/** Compact "AI used 12.3K in / 1.1K out · ~$0.004 · model" line for a result. */
export function TokenUsageLine({ usage }: { usage?: TokenUsage | null }) {
  if (!usage || !usage.calls) return null;
  const models = Object.keys(usage.by_model || {});
  const modelLabel = models.length === 1 ? models[0] : models.length > 1 ? `${models.length} models` : null;
  const cost = formatCost(usage.cost_usd);
  return (
    <div
      className="token-usage muted"
      style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
      title={`${usage.in} input + ${usage.out} output tokens across ${usage.calls} AI call(s)`}
    >
      <Sparkles size={12} strokeWidth={2} />
      <span>
        AI used <strong>{formatTokens(usage.in)}</strong> in / <strong>{formatTokens(usage.out)}</strong> out
        {cost && <> · {cost}</>}
        {modelLabel && <> · {modelLabel}</>}
      </span>
    </div>
  );
}

/** Small chip marking an AI-powered action. */
export function AiBadge({ title }: { title?: string }) {
  return (
    <span className="ai-badge" title={title || "Enhanced by AI when a provider is connected"}>
      <Sparkles size={12} strokeWidth={2} /> AI
    </span>
  );
}

/** App-wide AI connection status + degraded-mode message.
 *
 * AI can come from three places (resolved per user, server-side): the user's own
 * key, a shared free-tier allowance, or the legacy global key. `health.ai_active`
 * only reflects the *global* key, so on a free-tier/own-key deployment it reads
 * false even though AI works — we must also consult the per-user settings/usage. */
export function AiStatusBanner() {
  const health = useHealth();
  const [ai, setAi] = useState<AISettings | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);

  useEffect(() => {
    api
      .getAISettings()
      .then(({ ai, usage }) => {
        setAi(ai);
        setUsage(usage);
      })
      .catch(() => {
        /* needs auth; ignore (falls back to global health below) */
      });
  }, []);

  if (!health) return null;

  // 1) The user's own key (unlimited) — or, in local/no-auth dev, the local key.
  if (ai?.active) {
    return (
      <div className="ai-status on">
        <span className="dot" /> AI connected — <strong>{ai.provider}/{ai.model}</strong>.
        Smart classification, unstructured-text routing and document mapping are enabled.
      </div>
    );
  }
  // 2) Shared free-tier allowance still available.
  if (usage?.free_enabled && !usage.has_own_key && usage.free_remaining > 0) {
    return (
      <div className="ai-status on">
        <span className="dot" /> AI connected — <strong>{usage.free_remaining} free AI action(s)</strong>{" "}
        remaining. Smart classification and document mapping are enabled.{" "}
        <a href="/settings">Add your own key →</a>
      </div>
    );
  }
  // 3) Legacy global shared key.
  if (health.ai_active) {
    return (
      <div className="ai-status on">
        <span className="dot" /> AI connected — <strong>{health.ai_provider}/{health.ai_model}</strong>.
        Smart classification, unstructured-text routing and document mapping are enabled.
      </div>
    );
  }
  // 4) Free tier configured but used up, no own key.
  if (usage?.free_enabled && !usage.has_own_key && usage.free_remaining <= 0) {
    return (
      <div className="ai-status off">
        <AlertTriangle size={15} strokeWidth={2} /> Your free AI actions are used up — running the
        offline heuristic engine. <a href="/settings">Add your own API key →</a> to re-enable smart
        classification and mapping.
      </div>
    );
  }
  // 5) No AI at all.
  return (
    <div className="ai-status off">
      <AlertTriangle size={15} strokeWidth={2} /> AI is off — running the offline heuristic engine.
      Without a connected provider, <strong>“Raw text”</strong> and <strong>“From document”</strong>{" "}
      mapping use basic heuristics and field classification is less accurate.{" "}
      <a href="/settings">Connect a provider →</a>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="spinner" /> {label && <span className="muted">{label}</span>}
    </span>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">{message}</div>;
}

const CLASS_STYLE: Record<string, string> = {
  FIXED: "fixed",
  AUTO_FIELD: "auto",
  REPEATABLE_TABLE: "repeatable",
  REPEATABLE_SECTION: "repeatable",
  UNKNOWN: "unknown",
};

export function ClassificationBadge({ value }: { value: string }) {
  const cls = CLASS_STYLE[value] || (value.startsWith("DYNAMIC") ? "dynamic" : "fixed");
  const label = value.replace(/_/g, " ").toLowerCase();
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{value}</span>;
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <span className="conf" title={`${pct}% confidence`}>
      <span className="conf-bar">
        <i style={{ width: `${pct}%` }} />
      </span>
      <span className="muted">{pct}%</span>
    </span>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return <div className="card">{children}</div>;
}
