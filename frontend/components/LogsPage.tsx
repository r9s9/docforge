"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { LogEntry } from "@/lib/types";
import { ErrorBox } from "@/components/ui";
import { RotateCw } from "@/components/icons";

const LEVELS = ["ALL", "INFO", "WARNING", "ERROR"] as const;
type LevelFilter = (typeof LEVELS)[number];

export default function LogsPage() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [error, setError] = useState("");
  const [level, setLevel] = useState<LevelFilter>("ALL");
  const [query, setQuery] = useState("");
  const [auto, setAuto] = useState(true);
  const [loading, setLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function refresh() {
    try {
      const { entries } = await api.getLogs(500);
      setEntries(entries);
      setError("");
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    if (!auto) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [auto]);

  // Keep the newest line in view as logs stream in.
  useEffect(() => {
    if (auto && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries, auto]);

  const shown = entries.filter((e) => {
    if (level !== "ALL" && e.level !== level) return false;
    if (query) {
      const q = query.toLowerCase();
      if (!(e.message.toLowerCase().includes(q) || e.logger.toLowerCase().includes(q))) return false;
    }
    return true;
  });

  return (
    <div>
      <h1 className="page-title">Logs</h1>
      <p className="page-sub">
        Recent activity for your session — actions, AI calls, and errors. Newest at the
        bottom. Server-side and ephemeral (cleared when the service restarts).
      </p>

      {error && <ErrorBox message={error} />}

      <div className="row logs-toolbar">
        <div className="seg-toggle" role="tablist" aria-label="Level filter">
          {LEVELS.map((l) => (
            <button key={l} className={level === l ? "active" : ""} onClick={() => setLevel(l)}>
              {l}
            </button>
          ))}
        </div>
        <input
          className="logs-search"
          placeholder="Filter… (e.g. ai., analysis, error)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="row" style={{ gap: 6, margin: 0 }}>
          <input
            type="checkbox"
            style={{ width: "auto" }}
            checked={auto}
            onChange={(e) => setAuto(e.target.checked)}
          />
          <span className="muted" style={{ fontSize: 13 }}>
            Auto-refresh
          </span>
        </label>
        <button className="btn secondary small" onClick={refresh}>
          <RotateCw size={14} strokeWidth={1.9} /> Refresh
        </button>
        <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
          {shown.length} / {entries.length}
        </span>
      </div>

      <div className="logs-view" ref={scrollRef}>
        {loading ? (
          <div className="muted" style={{ padding: 16 }}>
            Loading…
          </div>
        ) : shown.length === 0 ? (
          <div className="muted" style={{ padding: 16 }}>
            No log entries yet. Run an action (create a template, generate a document) and
            they’ll appear here.
          </div>
        ) : (
          shown.map((e, i) => (
            <div key={i} className={`log-line lvl-${e.level.toLowerCase()}`}>
              <span className="log-time">{e.time}</span>
              <span className={`log-level lvl-${e.level.toLowerCase()}`}>{e.level}</span>
              <span className="log-logger">{e.logger.replace(/^docforge\./, "")}</span>
              <span className="log-msg">{e.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
