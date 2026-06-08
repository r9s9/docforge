"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  FieldDefinition,
  Project,
  TemplateDetail as TDetail,
  TemplateElement,
  TemplateVersion,
} from "@/lib/types";
import { ClassificationBadge, ErrorBox, Spinner } from "@/components/ui";

type Tab = "elements" | "fields" | "rules" | "sections" | "versions" | "sources";

const FIELD_TYPES = ["text", "multiline_text", "date", "person", "number", "enum", "table", "boolean"];

export default function TemplateDetail({ id }: { id: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<TDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("elements");
  const [editFields, setEditFields] = useState<FieldDefinition[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [pickProject, setPickProject] = useState("");

  useEffect(() => {
    if (!id) return;
    api.getTemplate(id).then(setDetail).catch((e) => setError(String(e.message || e)));
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, [id]);

  async function assignToProject() {
    if (!detail || !pickProject) return;
    try {
      await api.assignTemplate(pickProject, detail.id);
      setPickProject("");
      setDetail(await api.getTemplate(detail.id));
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function unassignFromProject() {
    if (!detail || !detail.project_id) return;
    try {
      await api.unassignTemplate(detail.project_id, detail.id);
      setDetail(await api.getTemplate(detail.id));
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function rename() {
    if (!detail) return;
    const next = window.prompt("Rename template:", detail.name);
    if (!next || next.trim() === detail.name) return;
    try {
      const t = await api.renameTemplate(detail.id, next.trim());
      setDetail({ ...detail, name: t.name });
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function remove() {
    if (!detail) return;
    if (!window.confirm(`Delete "${detail.name}"? This permanently removes the template and its versions.`))
      return;
    try {
      await api.deleteTemplate(detail.id);
      router.push("/");
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  function startEdit() {
    if (!detail?.latest) return;
    setEditFields(detail.latest.fields.map((f) => ({ ...f })));
    setTab("fields");
  }

  function patchEditField(i: number, patch: Partial<FieldDefinition>) {
    setEditFields((prev) => (prev ? prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)) : prev));
  }

  async function saveVersion() {
    if (!detail || !editFields) return;
    setSaving(true);
    setError("");
    try {
      await api.createVersion(detail.id, editFields);
      const fresh = await api.getTemplate(detail.id);
      setDetail(fresh);
      setEditFields(null);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  if (error) return <ErrorBox message={error} />;
  if (!detail) return <Spinner label="Loading template…" />;

  const latest = detail.latest;
  const sections = ((latest?.intelligence?.sections as any[]) || []) as any[];

  return (
    <div>
      <div className="spread" style={{ marginBottom: 22 }}>
        <div>
          <h1 className="page-title">{detail.name}</h1>
          <p className="page-sub" style={{ margin: 0 }}>
            {detail.document_type || "Document"} · v{detail.latest_version} ·{" "}
            {latest?.fields.length ?? 0} fields
          </p>
        </div>
        <div className="row">
          <Link className="btn" href={`/generate/${detail.id}`}>
            Generate Document
          </Link>
          <button
            className="btn secondary"
            onClick={() =>
              api.download(
                api.templateDownloadUrl(detail.id, detail.latest_version),
                `template_v${detail.latest_version}.docx`,
              )
            }
          >
            Download template.docx
          </button>
          <button className="btn secondary" onClick={startEdit}>
            ✎ Edit fields
          </button>
          <button className="btn secondary" onClick={rename}>
            Rename
          </button>
          <button
            className="btn secondary"
            onClick={remove}
            style={{ color: "var(--red)", borderColor: "var(--red)" }}
          >
            🗑 Delete
          </button>
        </div>
      </div>

      {detail.project_id ? (
        <div className="banner info section" role="status">
          <div className="spread" style={{ alignItems: "center" }}>
            <span>
              Part of project{" "}
              <Link href={`/projects/${detail.project_id}`}>
                <strong>{detail.project_name}</strong>
              </Link>
            </span>
            <button className="btn secondary small" onClick={unassignFromProject}>
              Unassign
            </button>
          </div>
          {detail.project_metadata && Object.keys(detail.project_metadata).length > 0 && (
            <>
              <p style={{ margin: "10px 0 6px", fontSize: 13 }}>
                Inherited defaults — these pre-fill this template’s fields at generation (you can
                override any value per document):
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                {Object.entries(detail.project_metadata).map(([k, v]) => (
                  <li key={k}>
                    <span className="mono">{k}</span> = {v}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : (
        projects.length > 0 && (
          <div className="banner info section" role="status">
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 13 }}>Assign to a project to inherit shared metadata:</span>
              <select
                value={pickProject}
                onChange={(e) => setPickProject(e.target.value)}
                style={{ maxWidth: 280 }}
              >
                <option value="">Choose a project…</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <button className="btn secondary small" onClick={assignToProject} disabled={!pickProject}>
                Assign
              </button>
            </div>
          </div>
        )
      )}

      <div className="tabs">
        {(["elements", "fields", "rules", "sections", "versions", "sources"] as Tab[]).map((t) => (
          <div key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </div>
        ))}
      </div>

      {tab === "elements" && latest && (
        <div>
          <p className="muted" style={{ marginTop: 0 }}>
            Every element of the template, color-coded by how it behaves. Highlighted
            placeholders and repeatable tables are the parts that change per document.
          </p>
          <div className="pill-list" style={{ marginBottom: 16 }}>
            <ClassificationBadge value="FIXED" />
            <ClassificationBadge value="DYNAMIC_TEXT" />
            <ClassificationBadge value="REPEATABLE_TABLE" />
            <ClassificationBadge value="AUTO_FIELD" />
          </div>
          <div className="doc-elements">
            {latest.elements.map((el) => (
              <ElementRow key={el.node_id} el={el} />
            ))}
          </div>
        </div>
      )}

      {tab === "fields" && editFields && (
        <div>
          <div className="notice" style={{ marginBottom: 14 }}>
            Editing fields → will publish <strong>v{detail.latest_version + 1}</strong>. The layout
            is rebuilt from the original document; renamed/removed fields update the placeholders.
          </div>
          <table>
            <thead>
              <tr>
                <th>Field name</th>
                <th>Label</th>
                <th>Type</th>
                <th>Req</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {editFields.map((f, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="mono"
                      value={f.field_name}
                      onChange={(e) => patchEditField(i, { field_name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input value={f.label} onChange={(e) => patchEditField(i, { label: e.target.value })} />
                  </td>
                  <td>
                    <select
                      value={f.field_type}
                      onChange={(e) => patchEditField(i, { field_type: e.target.value })}
                    >
                      {FIELD_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      style={{ width: "auto" }}
                      checked={f.required}
                      onChange={(e) => patchEditField(i, { required: e.target.checked })}
                    />
                  </td>
                  <td>
                    {f.field_type !== "boolean" && (
                      <button
                        className="btn secondary small"
                        title="Remove field (content becomes fixed)"
                        onClick={() => setEditFields(editFields.filter((_, idx) => idx !== i))}
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn" onClick={saveVersion} disabled={saving}>
              {saving ? <Spinner label="Saving…" /> : `Save as v${detail.latest_version + 1}`}
            </button>
            <button className="btn secondary" onClick={() => setEditFields(null)} disabled={saving}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {tab === "fields" && !editFields && latest && (
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Label</th>
              <th>Type</th>
              <th>Required</th>
              <th>Classification</th>
            </tr>
          </thead>
          <tbody>
            {latest.fields.map((f) => (
              <tr key={f.field_name}>
                <td className="mono">{f.field_name}</td>
                <td>{f.label}</td>
                <td>
                  {f.field_type}
                  {f.columns.length > 0 && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      [{f.columns.map((c) => `${c.field_name}:${c.field_type}`).join(", ")}]
                    </div>
                  )}
                </td>
                <td>{f.required ? "yes" : "no"}</td>
                <td>
                  <ClassificationBadge value={f.classification} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "rules" && latest && (
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th>Field</th>
              <th>Type</th>
              <th>Severity</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {latest.rules.map((r) => (
              <tr key={r.rule_id}>
                <td className="mono">{r.rule_id}</td>
                <td className="mono">{r.field_name}</td>
                <td>{r.rule_type}</td>
                <td>
                  <span className={`badge ${r.severity === "error" ? "fail" : "warning"}`}>
                    {r.severity}
                  </span>
                </td>
                <td className="muted">{r.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "sections" && (
        <table>
          <thead>
            <tr>
              <th>Section</th>
              <th>Purpose</th>
              <th>Fields</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((s) => (
              <tr key={s.section_key}>
                <td>{s.title}</td>
                <td className="muted">{s.purpose}</td>
                <td className="mono">{(s.field_names || []).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "versions" && (
        <table>
          <thead>
            <tr>
              <th>Version</th>
              <th>Fields</th>
              <th>Renderer</th>
              <th>Changelog</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {detail.versions.map((v) => (
              <tr key={v.id}>
                <td>v{v.version}</td>
                <td>{v.n_fields}</td>
                <td>{v.renderer}</td>
                <td className="muted">{v.changelog}</td>
                <td className="muted">{new Date(v.created_at).toLocaleString()}</td>
                <td>
                  <button
                    className="btn secondary small"
                    onClick={() =>
                      api.download(
                        api.templateDownloadUrl(detail.id, v.version),
                        `template_v${v.version}.docx`,
                      )
                    }
                  >
                    .docx
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "versions" && (
        <div style={{ marginTop: 22 }}>
          <h2 className="section-h">Compare versions</h2>
          <VersionDiff templateId={detail.id} versions={detail.versions} />
        </div>
      )}

      {tab === "sources" && latest && (
        <div className="card">
          <p className="muted" style={{ marginTop: 0 }}>
            Original example documents this template was reverse-engineered from:
          </p>
          <ul style={{ margin: 0 }}>
            {latest.source_examples.map((s) => (
              <li key={s} className="mono">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function VersionDiff({ templateId, versions }: { templateId: string; versions: TemplateVersion[] }) {
  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const [from, setFrom] = useState(sorted[1]?.version ?? sorted[0]?.version);
  const [to, setTo] = useState(sorted[0]?.version);
  const [diff, setDiff] = useState<{ added: string[]; removed: string[]; changed: string[] } | null>(
    null
  );
  const [busy, setBusy] = useState(false);

  if (versions.length < 2) {
    return <p className="muted">Publish a new version (Edit fields) to compare changes.</p>;
  }

  async function run() {
    setBusy(true);
    try {
      const [a, b] = await Promise.all([
        api.getVersion(templateId, from),
        api.getVersion(templateId, to),
      ]);
      const am = new Map(a.fields.map((f) => [f.field_name, f]));
      const bm = new Map(b.fields.map((f) => [f.field_name, f]));
      const added = [...bm.keys()].filter((k) => !am.has(k));
      const removed = [...am.keys()].filter((k) => !bm.has(k));
      const changed = [...bm.keys()].filter(
        (k) =>
          am.has(k) &&
          (am.get(k)!.field_type !== bm.get(k)!.field_type ||
            am.get(k)!.required !== bm.get(k)!.required)
      );
      setDiff({ added, removed, changed });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: 14 }}>
        <select value={from} onChange={(e) => setFrom(Number(e.target.value))} style={{ width: "auto" }}>
          {sorted.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        <span className="muted">→</span>
        <select value={to} onChange={(e) => setTo(Number(e.target.value))} style={{ width: "auto" }}>
          {sorted.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        <button className="btn secondary small" onClick={run} disabled={busy}>
          {busy ? "Comparing…" : "Compare"}
        </button>
      </div>
      {diff && (
        <div className="card">
          <DiffList label="Added fields" items={diff.added} color="var(--green)" />
          <DiffList label="Removed fields" items={diff.removed} color="var(--red)" />
          <DiffList label="Changed (type/required)" items={diff.changed} color="var(--amber)" />
          {diff.added.length + diff.removed.length + diff.changed.length === 0 && (
            <span className="muted">No field-level differences.</span>
          )}
        </div>
      )}
    </div>
  );
}

function DiffList({ label, items, color }: { label: string; items: string[]; color: string }) {
  if (items.length === 0) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <strong style={{ color }}>{label}:</strong>{" "}
      <span className="mono">{items.join(", ")}</span>
    </div>
  );
}

function ElementRow({ el }: { el: TemplateElement }) {
  const cls = el.classification;
  const isDynamic = cls.startsWith("DYNAMIC");
  const isRepeatable = cls.startsWith("REPEATABLE");
  const color = isRepeatable
    ? "var(--green)"
    : isDynamic
      ? "var(--accent)"
      : cls === "AUTO_FIELD"
        ? "var(--amber)"
        : "var(--border-strong)";

  return (
    <div className="el-row" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="spread">
        <span className="muted mono" style={{ fontSize: 11 }}>
          {el.type}
          {el.scope ? ` · ${el.scope}` : ""}
        </span>
        <ClassificationBadge value={cls} />
      </div>
      <div style={{ marginTop: 6 }}>
        {isRepeatable ? (
          <div>
            <span className="muted">repeatable rows → </span>
            <span className="placeholder">{el.field_name}</span>
            <div className="pill-list" style={{ marginTop: 6 }}>
              {(el.headers || []).map((h) => (
                <span key={h} className="chip">
                  {h}
                </span>
              ))}
            </div>
          </div>
        ) : isDynamic ? (
          <div>
            {el.static_prefix && <span>{el.static_prefix}</span>}
            <span className="placeholder">{`{{ ${el.field_name} }}`}</span>
          </div>
        ) : (
          <div className={cls === "FIXED" ? "" : "muted"}>
            {el.text || <span className="muted">(empty)</span>}
          </div>
        )}
      </div>
    </div>
  );
}
