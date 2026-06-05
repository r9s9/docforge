"use client";

import type { ReactNode } from "react";
import { useHealth } from "@/lib/useHealth";

/** Small chip marking an AI-powered action. */
export function AiBadge({ title }: { title?: string }) {
  return (
    <span className="ai-badge" title={title || "Enhanced by AI when a provider is connected"}>
      ✦ AI
    </span>
  );
}

/** App-wide AI connection status + degraded-mode message. */
export function AiStatusBanner() {
  const health = useHealth();
  if (!health) return null;
  if (health.ai_active) {
    return (
      <div className="ai-status on">
        <span className="dot" /> AI connected — <strong>{health.ai_provider}/{health.ai_model}</strong>.
        Smart classification, unstructured-text routing and document mapping are enabled.
      </div>
    );
  }
  return (
    <div className="ai-status off">
      <span className="dot off" /> AI is off — running the offline heuristic engine. Without a
      connected provider, <strong>“Raw text”</strong> and <strong>“From document”</strong> mapping
      use basic heuristics and field classification is less accurate.{" "}
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
