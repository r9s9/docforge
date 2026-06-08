"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProjectDetail as ProjectDetailT, Template } from "@/lib/types";
import { ErrorBox, Spinner } from "@/components/ui";
import { Plus, X } from "@/components/icons";

type Row = { key: string; value: string };

export default function ProjectDetail({ id }: { id: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<ProjectDetailT | null>(null);
  const [error, setError] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [savingMeta, setSavingMeta] = useState(false);
  const [allTemplates, setAllTemplates] = useState<Template[]>([]);
  const [pick, setPick] = useState("");

  async function load() {
    const [p, all] = await Promise.all([api.getProject(id), api.listTemplates()]);
    setDetail(p);
    setRows(Object.entries(p.metadata || {}).map(([key, value]) => ({ key, value })));
    setAllTemplates(all);
  }

  useEffect(() => {
    load().catch((e) => setError(String(e.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function saveMeta() {
    setSavingMeta(true);
    setError("");
    try {
      const metadata: Record<string, string> = {};
      for (const r of rows) {
        const k = r.key.trim();
        if (k) metadata[k] = r.value;
      }
      await api.updateProject(id, { metadata });
      await load();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSavingMeta(false);
    }
  }

  async function rename() {
    const next = window.prompt("Project name", detail?.name);
    if (!next || !next.trim()) return;
    try {
      await api.updateProject(id, { name: next.trim() });
      await load();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function remove() {
    if (!window.confirm("Delete this project? Its templates are kept (just unassigned).")) return;
    try {
      await api.deleteProject(id);
      router.push("/projects");
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function assign() {
    if (!pick) return;
    try {
      await api.assignTemplate(id, pick);
      setPick("");
      await load();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function unassign(t: Template) {
    try {
      await api.unassignTemplate(id, t.id);
      await load();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  if (error && !detail) return <ErrorBox message={error} />;
  if (!detail) return <Spinner label="Loading project…" />;

  const assignable = allTemplates.filter((t) => t.project_id !== id);

  return (
    <div>
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 4 }}>
            {detail.name}
          </h1>
          <p className="page-sub" style={{ margin: 0 }}>
            {detail.description || "No description."}
          </p>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn secondary small" onClick={rename}>
            Rename
          </button>
          <button className="btn secondary small" onClick={remove} style={{ color: "var(--red)" }}>
            Delete
          </button>
        </div>
      </div>

      {error && <ErrorBox message={error} />}

      {/* Metadata editor */}
      <div className="section">
        <h2 className="section-h" style={{ marginBottom: 6 }}>
          Inherited metadata
        </h2>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          Free-form key/value pairs. At generation, a key that matches a template field pre-fills
          that field; any other key is available as a <span className="mono">{"{{ key }}"}</span>{" "}
          variable. A value typed per document always overrides the project default.
        </p>
        <table>
          <thead>
            <tr>
              <th style={{ width: "35%" }}>Key</th>
              <th>Value</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <input
                    value={r.key}
                    placeholder="e.g. prepared_by"
                    onChange={(e) =>
                      setRows((prev) => prev.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))
                    }
                  />
                </td>
                <td>
                  <input
                    value={r.value}
                    placeholder="value"
                    onChange={(e) =>
                      setRows((prev) => prev.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                    }
                  />
                </td>
                <td>
                  <button
                    className="btn secondary small icon"
                    onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <X size={14} strokeWidth={2} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button
            className="btn secondary small"
            onClick={() => setRows((prev) => [...prev, { key: "", value: "" }])}
          >
            <Plus size={14} strokeWidth={2} /> Add field
          </button>
          <button className="btn" onClick={saveMeta} disabled={savingMeta}>
            {savingMeta ? "Saving…" : "Save metadata"}
          </button>
        </div>
      </div>

      {/* Assigned templates */}
      <div className="section">
        <h2 className="section-h" style={{ marginBottom: 14 }}>
          Templates in this project
        </h2>
        {detail.templates.length === 0 ? (
          <div className="card empty">No templates assigned yet. Add one below.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {detail.templates.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link href={`/templates/${t.id}`}>{t.name}</Link>
                  </td>
                  <td className="muted">{t.document_type || "—"}</td>
                  <td>
                    <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                      <Link className="btn secondary small" href={`/generate/${t.id}`}>
                        Generate
                      </Link>
                      <button className="btn secondary small" onClick={() => unassign(t)}>
                        Unassign
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="row" style={{ gap: 8, marginTop: 14, alignItems: "center" }}>
          <select value={pick} onChange={(e) => setPick(e.target.value)} style={{ maxWidth: 320 }}>
            <option value="">Assign a template…</option>
            {assignable.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.project_id ? " (in another project)" : ""}
              </option>
            ))}
          </select>
          <button className="btn secondary small" onClick={assign} disabled={!pick}>
            Assign
          </button>
        </div>
      </div>
    </div>
  );
}
