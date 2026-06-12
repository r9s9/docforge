"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health, Template } from "@/lib/types";
import { ErrorBox, Spinner } from "@/components/ui";
import { Plus, Trash2 } from "@/components/icons";

export default function Dashboard() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listTemplates(), api.health()])
      .then(([t, h]) => {
        setTemplates(t);
        setHealth(h);
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  async function remove(t: Template) {
    if (!window.confirm(`Delete "${t.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteTemplate(t.id);
      setTemplates((prev) => (prev ? prev.filter((x) => x.id !== t.id) : prev));
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-sub">
        Reverse-engineer filled DOCX files into reusable, AI-aware templates.
      </p>

      {error && <ErrorBox message={error} />}

      <div className="cards section">
        <div className="card">
          <div className="stat-label">Templates</div>
          <div className="stat">{templates ? templates.length : "—"}</div>
        </div>
        <div className="card">
          <div className="stat-label">Analysis engine</div>
          <div className="stat" style={{ fontSize: 19, marginTop: 10 }}>
            {health ? (health.ai_active ? health.ai_model : "Heuristic") : "—"}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            {health?.ai_active ? "LLM connected" : "offline / private"}
          </div>
        </div>
        <div className="card">
          <div className="stat-label" style={{ marginBottom: 12 }}>
            Get started
          </div>
          <Link className="btn" href="/new">
            <Plus size={15} strokeWidth={2} /> New Template
          </Link>
        </div>
      </div>

      <div className="section">
        <div className="spread" style={{ marginBottom: 14 }}>
          <h2 className="section-h" style={{ margin: 0 }}>
            Templates
          </h2>
          <Link className="btn secondary small" href="/new">
            <Plus size={14} strokeWidth={2} /> New
          </Link>
        </div>
        {!templates ? (
          <Spinner label="Loading templates…" />
        ) : templates.length === 0 ? (
          <div className="card empty">
            No templates yet. <Link href="/new">Create one</Link> by uploading 1–5 example DOCX
            files, or run <span className="mono">docforge seed</span> for demo data.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Version</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link href={`/templates/${t.id}`}>{t.name}</Link>
                  </td>
                  <td className="muted">{t.document_type || "—"}</td>
                  <td>v{t.latest_version}</td>
                  <td className="muted">{new Date(t.created_at).toLocaleDateString()}</td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <Link className="btn secondary small" href={`/generate/${t.id}`}>
                        Generate
                      </Link>
                      <button
                        className="btn secondary small icon"
                        onClick={() => remove(t)}
                        title="Delete template"
                        style={{ color: "var(--red)" }}
                      >
                        <Trash2 size={15} strokeWidth={1.9} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
