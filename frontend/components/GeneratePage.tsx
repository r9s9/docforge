"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  FieldDefinition,
  GenerationResult,
  PlacementInstruction,
  PreviewBlock,
  PreviewResult,
  RoutingResult,
  Template,
  TemplateDetail,
} from "@/lib/types";
import { AiBadge, AiStatusBanner, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import DocBlocks from "@/components/DocBlocks";
import ProgressBar from "@/components/ProgressBar";

type Mode = "form" | "raw" | "document" | "json";
type FormValues = Record<string, any>;

function blankValue(f: FieldDefinition) {
  if (f.field_type === "table") return [];
  if (f.field_type === "boolean") return f.default ?? true;
  return "";
}

function TableEditor({
  field,
  rows,
  onChange,
}: {
  field: FieldDefinition;
  rows: Record<string, string>[];
  onChange: (rows: Record<string, string>[]) => void;
}) {
  const cols = field.columns;
  const addRow = () => onChange([...rows, Object.fromEntries(cols.map((c) => [c.field_name, ""]))]);
  const update = (i: number, col: string, val: string) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [col]: val } : r)));
  return (
    <div>
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.field_name}>{c.label}</th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c.field_name}>
                  <input
                    value={r[c.field_name] ?? ""}
                    onChange={(e) => update(i, c.field_name, e.target.value)}
                  />
                </td>
              ))}
              <td>
                <button
                  className="btn secondary small"
                  onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn secondary small" style={{ marginTop: 10 }} onClick={addRow}>
        ＋ Add row
      </button>
    </div>
  );
}

export default function GeneratePage({ initialId }: { initialId?: string }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedId, setSelectedId] = useState(initialId || "");
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [mode, setMode] = useState<Mode>("form");
  const [values, setValues] = useState<FormValues>({});
  const [rawText, setRawText] = useState("");
  const [jsonText, setJsonText] = useState("{\n  \n}");
  const [routing, setRouting] = useState<RoutingResult | null>(null);
  const [result, setResult] = useState<GenerationResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [docFile, setDocFile] = useState<File | null>(null);
  const [extracted, setExtracted] = useState<PreviewBlock[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [aiElapsed, setAiElapsed] = useState<number | null>(null);
  const [aiStage, setAiStage] = useState("");
  const docInputRef = useRef<HTMLInputElement>(null);
  const aiTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function startAiTimer(stage: string) {
    setAiStage(stage);
    setAiElapsed(0);
    aiTimerRef.current = setInterval(() => setAiElapsed((e) => (e ?? 0) + 1), 1000);
  }
  function stopAiTimer() {
    if (aiTimerRef.current) clearInterval(aiTimerRef.current);
    aiTimerRef.current = null;
    setAiElapsed(null);
  }

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setDetail(null);
    setResult(null);
    setRouting(null);
    setPreview(null);
    setExtracted(null);
    api
      .getTemplate(selectedId)
      .then((d) => {
        setDetail(d);
        const init: FormValues = {};
        d.latest?.fields.forEach((f) => (init[f.field_name] = blankValue(f)));
        setValues(init);
      })
      .catch((e) => setError(String(e.message || e)));
  }, [selectedId]);

  const fields = detail?.latest?.fields || [];

  async function previewRoute() {
    setBusy(true);
    setError("");
    startAiTimer("Routing your notes with AI…");
    try {
      const r = await api.route(selectedId, { raw_text: rawText });
      setRouting(r);
      const next: FormValues = { ...values };
      r.placements.forEach((p) => (next[p.field_name] = p.value));
      setValues(next);
      setMode("form");
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
      stopAiTimer();
    }
  }

  async function routeFromDocument() {
    if (!docFile) return;
    setBusy(true);
    setError("");
    setExtracted(null);
    startAiTimer("Mapping your document with AI…");
    try {
      const r = await api.routeDocument(selectedId, docFile);
      setRouting(r.routing);
      setExtracted(r.extracted);
      const next: FormValues = { ...values };
      r.routing.placements.forEach((p) => (next[p.field_name] = p.value));
      setValues(next);
      setMode("form");
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
      stopAiTimer();
    }
  }

  function buildBody(): Record<string, unknown> {
    if (mode === "json") return { mode: "structured_json", data: JSON.parse(jsonText) };
    if (mode === "raw") return { mode: "unstructured_text", raw_text: rawText };
    return { mode: "structured_json", data: values };
  }

  async function previewDoc() {
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      setPreview(await api.preview(selectedId, buildBody()));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await api.generate(selectedId, buildBody());
      setResult(r);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Generate Document</h1>
      <p className="page-sub">
        Fill a template from a form, raw notes, an uploaded document, or JSON.
      </p>

      <AiStatusBanner />

      {error && <ErrorBox message={error} />}

      {aiElapsed !== null && (
        <div className="section">
          <ProgressBar indeterminate busy stage={`${aiStage} (${aiElapsed}s)`} />
        </div>
      )}

      <label className="field" style={{ maxWidth: 440 }}>
        <span>Template</span>
        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          <option value="">Select a template…</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} (v{t.latest_version})
            </option>
          ))}
        </select>
      </label>

      {detail && (
        <>
          <div className="tabs">
            <div className={`tab ${mode === "form" ? "active" : ""}`} onClick={() => setMode("form")}>
              Structured form
            </div>
            <div className={`tab ${mode === "raw" ? "active" : ""}`} onClick={() => setMode("raw")}>
              Raw text <AiBadge />
            </div>
            <div
              className={`tab ${mode === "document" ? "active" : ""}`}
              onClick={() => setMode("document")}
            >
              From document <AiBadge />
            </div>
            <div className={`tab ${mode === "json" ? "active" : ""}`} onClick={() => setMode("json")}>
              JSON
            </div>
          </div>

          {mode === "document" && (
            <div className="section">
              <p className="muted" style={{ marginTop: 0 }}>
                Upload a filled .docx — all of its content is extracted and mapped into this
                template&apos;s fields. AI improves the mapping when a provider is connected.
              </p>
              <div className="row">
                <button className="btn secondary" onClick={() => docInputRef.current?.click()}>
                  {docFile ? `📄 ${docFile.name}` : "Choose .docx"}
                </button>
                <input
                  ref={docInputRef}
                  type="file"
                  accept=".docx"
                  hidden
                  onChange={(e) => setDocFile(e.target.files?.[0] || null)}
                />
                <button className="btn" disabled={busy || !docFile} onClick={routeFromDocument}>
                  {busy ? <Spinner label="Mapping…" /> : "Map document → fields"}
                </button>
              </div>
            </div>
          )}

          {extracted && (
            <div className="section">
              <h2 className="section-h">Extracted from your document</h2>
              <DocBlocks blocks={extracted} />
            </div>
          )}

          {mode === "raw" && (
            <div className="section">
              <label className="field">
                <span>Paste notes / bullet points</span>
                <textarea
                  rows={8}
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  placeholder={"Project Name: Orion\nReport Date: 2026-07-01\nSummary text here…"}
                />
              </label>
              <button className="btn secondary" disabled={busy} onClick={previewRoute}>
                {busy ? <Spinner label="Routing…" /> : "Preview placements →"}
              </button>
            </div>
          )}

          {routing && (
            <div className="notice section">
              <strong>Routing ({routing.source})</strong> mapped {routing.placements.length}{" "}
              field(s).
              {routing.missing_required.length > 0 && (
                <div style={{ color: "var(--amber)" }}>
                  Missing required: {routing.missing_required.join(", ")}
                </div>
              )}
              {routing.unmapped_content.length > 0 && (
                <div className="muted">Unmapped: {routing.unmapped_content.join(" · ")}</div>
              )}
              <div className="muted">Values applied to the form below — review and generate.</div>
            </div>
          )}

          {mode === "json" && (
            <div className="section">
              <label className="field">
                <span>JSON data ({"{ field_name: value }"})</span>
                <textarea
                  rows={12}
                  className="mono"
                  value={jsonText}
                  onChange={(e) => setJsonText(e.target.value)}
                />
              </label>
            </div>
          )}

          {mode === "form" && (
            <div className="section">
              {fields.map((f) => {
                const placement = routing?.placements.find((p) => p.field_name === f.field_name) || null;
                return (
                <label className="field" key={f.field_name}>
                  <span>
                    {f.label} {f.required && <span className="req">*</span>}{" "}
                    <span className="muted mono" style={{ fontWeight: 400 }}>
                      ({f.field_type})
                    </span>
                    {placement && <RoutedChip p={placement} />}
                  </span>
                  {f.field_type === "table" ? (
                    <TableEditor
                      field={f}
                      rows={values[f.field_name] || []}
                      onChange={(rows) => setValues({ ...values, [f.field_name]: rows })}
                    />
                  ) : f.field_type === "boolean" ? (
                    <label className="row" style={{ gap: 8, fontWeight: 400 }}>
                      <input
                        type="checkbox"
                        style={{ width: "auto" }}
                        checked={values[f.field_name] ?? true}
                        onChange={(e) => setValues({ ...values, [f.field_name]: e.target.checked })}
                      />
                      <span className="muted">Include this content</span>
                    </label>
                  ) : f.field_type === "multiline_text" ? (
                    <textarea
                      value={values[f.field_name] || ""}
                      onChange={(e) => setValues({ ...values, [f.field_name]: e.target.value })}
                      placeholder={
                        f.classification === "REPEATABLE_SECTION" ? "One item per line…" : ""
                      }
                    />
                  ) : (
                    <input
                      value={values[f.field_name] || ""}
                      onChange={(e) => setValues({ ...values, [f.field_name]: e.target.value })}
                    />
                  )}
                </label>
                );
              })}
            </div>
          )}

          <div className="row">
            <button className="btn secondary" disabled={busy} onClick={previewDoc}>
              {busy ? <Spinner label="Rendering…" /> : "Preview"}
            </button>
            <button className="btn" disabled={busy} onClick={generate}>
              {busy ? <Spinner label="Generating…" /> : "Generate DOCX"}
            </button>
          </div>
        </>
      )}

      {preview && <PreviewPanel preview={preview} />}
      {result && <ResultPanel result={result} />}
    </div>
  );
}

function RoutedChip({ p }: { p: PlacementInstruction }) {
  const pct = Math.round((p.confidence ?? 1) * 100);
  const low = pct < 60 || p.ambiguous;
  return (
    <span
      className="badge"
      style={{
        marginLeft: 6,
        fontSize: 11,
        background: low ? "var(--amber-soft)" : "var(--accent-soft)",
        color: low ? "var(--amber)" : "var(--accent-press)",
      }}
      title={
        p.ambiguous
          ? `Ambiguous${p.alternatives?.length ? " — could be: " + p.alternatives.join(", ") : ""}`
          : `AI-filled · ${pct}% confidence`
      }
    >
      ✦ {pct}%{p.ambiguous ? " ?" : ""}
    </span>
  );
}

function PreviewPanel({ preview }: { preview: PreviewResult }) {
  const v = preview.validation;
  return (
    <div className="section" style={{ marginTop: 28 }}>
      <div className="spread" style={{ marginBottom: 12 }}>
        <h2 className="section-h" style={{ margin: 0 }}>
          Preview
        </h2>
        {v && <StatusBadge value={v.status} />}
      </div>
      <DocBlocks blocks={preview.blocks} />
      {v && v.issues.length > 0 && (
        <div className="muted" style={{ marginTop: 10 }}>
          {v.issues.length} validation note(s) — see the report after generating.
        </div>
      )}
    </div>
  );
}

function ResultPanel({ result }: { result: GenerationResult }) {
  const v = result.validation;
  const [pdfMsg, setPdfMsg] = useState("");

  async function downloadPdf() {
    if (!result.download_url) return;
    setPdfMsg("Converting…");
    try {
      const res = await fetch(`${result.download_url}.pdf`);
      if (!res.ok) {
        let detail = res.status === 501 ? "PDF export needs LibreOffice installed on the server." : `Failed (${res.status})`;
        try {
          detail = (await res.json()).detail || detail;
        } catch {
          /* ignore */
        }
        setPdfMsg(detail);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (result.output_filename || "document.docx").replace(".docx", ".pdf");
      a.click();
      URL.revokeObjectURL(url);
      setPdfMsg("");
    } catch (e: any) {
      setPdfMsg(String(e.message || e));
    }
  }

  const downloadReport = () => {
    const blob = new Blob([JSON.stringify(v, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "validation_report.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card section" style={{ marginTop: 28 }}>
      <div className="spread">
        <h2 className="section-h" style={{ margin: 0 }}>
          Result
        </h2>
        {v && <StatusBadge value={v.status} />}
      </div>

      <div className="row" style={{ margin: "16px 0" }}>
        {result.download_url && (
          <a className="btn" href={result.download_url}>
            ⬇ Download {result.output_filename}
          </a>
        )}
        {result.download_url && (
          <button className="btn secondary" onClick={downloadPdf}>
            ⬇ Download PDF
          </button>
        )}
        {v && (
          <button className="btn secondary" onClick={downloadReport}>
            Download validation report
          </button>
        )}
      </div>
      {pdfMsg && (
        <p className="muted" style={{ marginTop: -6, marginBottom: 12 }}>
          {pdfMsg}
        </p>
      )}

      {v && v.issues.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Field</th>
              <th>Message</th>
              <th>Suggested fix</th>
            </tr>
          </thead>
          <tbody>
            {v.issues.map((iss, i) => (
              <tr key={i}>
                <td>
                  <span className={`badge ${iss.severity === "error" ? "fail" : "warning"}`}>
                    {iss.severity}
                  </span>
                </td>
                <td className="mono">{iss.field_name}</td>
                <td>{iss.message}</td>
                <td className="muted">{iss.suggested_fix}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {v && v.issues.length === 0 && <div className="muted">No validation issues. 🎉</div>}
    </div>
  );
}
