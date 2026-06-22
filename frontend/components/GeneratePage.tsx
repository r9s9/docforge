"use client";

import Link from "next/link";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  FieldDefinition,
  GenerationResult,
  PlacementInstruction,
  PreviewBlock,
  RoutingResult,
  Template,
  TemplateDetail,
} from "@/lib/types";
import { AiBadge, AiStatusBanner, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Download,
  FileText,
  Plus,
  RotateCw,
  Sparkles,
  X,
} from "@/components/icons";
import DocBlocks from "@/components/DocBlocks";
import DocxPreview from "@/components/DocxPreview";
import ProgressBar from "@/components/ProgressBar";

type Mode = "form" | "raw" | "document" | "json";
type FormValues = Record<string, any>;

function blankValue(f: FieldDefinition) {
  if (f.field_type === "table") return [];
  if (f.field_type === "boolean") return f.default ?? true;
  return "";
}

// Image value editor: pick a file -> base64 data URL stored in the form values.
// Leaving it empty keeps the template's original picture (logos/icons).
function ImageInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const r = new FileReader();
    r.onload = () => onChange(String(r.result || ""));
    r.readAsDataURL(file);
  }
  return (
    <div className="img-input">
      {value ? (
        <div className="img-input-preview">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={value} alt="Selected" />
          <button type="button" className="btn secondary small" onClick={() => onChange("")}>
            Remove — keep original
          </button>
        </div>
      ) : (
        <p className="muted" style={{ margin: "0 0 6px" }}>
          No image chosen — the template’s original picture is kept.
        </p>
      )}
      <input ref={ref} type="file" accept="image/*" onChange={pick} />
    </div>
  );
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
                  className="btn secondary small icon"
                  onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
                >
                  <X size={14} strokeWidth={2} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn secondary small" style={{ marginTop: 10 }} onClick={addRow}>
        <Plus size={14} strokeWidth={2} /> Add row
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
  const [previewKey, setPreviewKey] = useState(0); // bump to re-render the Word preview
  const [docMismatch, setDocMismatch] = useState(false); // uploaded doc didn't match this template
  const [docFile, setDocFile] = useState<File | null>(null);
  const [extracted, setExtracted] = useState<PreviewBlock[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Which value cards are expanded (compact list by default; chevron opens one).
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set());
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
    setExtracted(null);
    setDocMismatch(false);
    api
      .getTemplate(selectedId)
      .then((d) => {
        setDetail(d);
        const init: FormValues = {};
        const meta = d.project_metadata || {};
        d.latest?.fields.forEach((f) => {
          init[f.field_name] = blankValue(f);
          // Pre-fill scalar fields from the project's inherited metadata (the
          // user can still override; the server re-applies defaults regardless).
          if (
            meta[f.field_name] !== undefined &&
            f.field_type !== "table" &&
            f.field_type !== "boolean"
          ) {
            init[f.field_name] = meta[f.field_name];
          }
        });
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
      setDocMismatch(false); // pasted text isn't a structural mismatch
      setMode("form");
      setPreviewKey((k) => k + 1);
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
      // Heuristic: if most required fields couldn't be filled, the uploaded doc
      // didn't really match this template — warn the user.
      const flds = detail?.latest?.fields || [];
      const req = flds.filter((f) => f.required);
      const filledReq = req.filter((f) => !r.routing.missing_required.includes(f.field_name)).length;
      setDocMismatch(req.length > 0 && filledReq / req.length < 0.5);
      setMode("form");
      setPreviewKey((k) => k + 1);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
      stopAiTimer();
    }
  }

  function refreshPreview() {
    setPreviewKey((k) => k + 1);
  }

  // --- value-card density (compact list + per-card expand, like FieldCards) ---
  function toggleField(name: string) {
    setExpandedFields((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }
  const allFieldsExpanded = fields.length > 0 && expandedFields.size >= fields.length;
  function setAllFields(on: boolean) {
    setExpandedFields(on ? new Set(fields.map((f) => f.field_name)) : new Set());
    try {
      localStorage.setItem("docforge-fieldcards-expanded", on ? "1" : "0");
    } catch {
      /* ignore */
    }
  }
  // Restore the shared density preference once templates/fields are present.
  useEffect(() => {
    try {
      if (localStorage.getItem("docforge-fieldcards-expanded") === "1" && fields.length) {
        setExpandedFields(new Set(fields.map((f) => f.field_name)));
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  // A short, human-readable preview of a field's current value for compact cards.
  function valuePreview(f: FieldDefinition): string {
    const v = values[f.field_name];
    if (f.field_type === "table") {
      return Array.isArray(v) && v.length ? `${v.length} row(s)` : "no rows yet";
    }
    if (f.field_type === "boolean") return v === false ? "excluded" : "included";
    if (f.field_type === "image") {
      return typeof v === "string" && v.startsWith("data:") ? "new image selected" : "original kept";
    }
    const s = typeof v === "string" ? v.trim() : v != null ? String(v) : "";
    return s || "—";
  }

  // Scroll the Word preview to where a field landed (and flash it). Falls back to
  // flashing the field card when the field has no anchor in the document yet.
  function jumpToField(fieldName: string) {
    setExpandedFields((prev) => (prev.has(fieldName) ? prev : new Set(prev).add(fieldName)));
    const targets = document.querySelectorAll<HTMLElement>(`.review-doc [data-hl="${fieldName}"]`);
    if (targets.length === 0) {
      const card = document.getElementById(`genfield-${fieldName}`);
      if (card) {
        card.classList.add("fc-flash");
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => card.classList.remove("fc-flash"), 1000);
      }
      return;
    }
    targets.forEach((el) => {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("docx-hl-flash");
      setTimeout(() => el.classList.remove("docx-hl-flash"), 1400);
    });
  }

  function valueText(f: FieldDefinition): string {
    const v = values[f.field_name];
    return typeof v === "string" ? v : "";
  }

  // Anchors for click-to-jump: each field's value (preferred) then its label as a
  // fallback, so even unfilled fields can scroll to roughly where they belong.
  const previewHighlights = [
    ...fields
      .map((f) => ({ key: f.field_name, text: valueText(f) }))
      .filter((h) => h.text.length >= 4),
    ...fields
      .map((f) => ({ key: f.field_name, text: f.label || "" }))
      .filter((h) => h.text.length >= 4),
  ];

  function buildBody(): Record<string, unknown> {
    if (mode === "json") return { mode: "structured_json", data: JSON.parse(jsonText) };
    if (mode === "raw") return { mode: "unstructured_text", raw_text: rawText };
    return { mode: "structured_json", data: values };
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
                  {docFile ? (
                    <>
                      <FileText size={15} strokeWidth={1.9} /> {docFile.name}
                    </>
                  ) : (
                    "Choose .docx"
                  )}
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
            <>
              {docMismatch ? (
                <div className="banner warn section">
                  <strong>⚠ The uploaded document didn’t match this template.</strong> Its text was
                  extracted and mapped to this template’s fields as best as possible, so the mapping
                  <strong> may not be 100% accurate</strong>. Review each field below — click a field
                  to jump to it in the preview — and fix anything before generating.
                </div>
              ) : (
                <div className="banner info section">
                  <strong>Review your document.</strong> The panel on the left is the real Word
                  document that will be generated. Click a field to jump to it in the preview, edit
                  anything, hit <strong>↻ Update preview</strong>, then <strong>Generate DOCX</strong>.
                </div>
              )}

              {detail?.project_id &&
                detail.project_metadata &&
                Object.keys(detail.project_metadata).length > 0 && (
                  <div className="banner info section" role="status">
                    Inherited from project{" "}
                    <Link href={`/projects/${detail.project_id}`}>
                      <strong>{detail.project_name}</strong>
                    </Link>
                    : {Object.keys(detail.project_metadata).join(", ")}. Matching fields are
                    pre-filled below — editing a field overrides the project default for this
                    document only.
                  </div>
                )}

              <div className="review-grid">
                <div className="review-doc">
                  <div className="review-head">
                    <h2 className="section-h">Document preview</h2>
                    <button className="btn secondary small" disabled={busy} onClick={refreshPreview}>
                      <RotateCw size={14} strokeWidth={1.9} /> Update preview
                    </button>
                  </div>
                  <DocxPreview
                    load={() =>
                      api.generatePreviewDocx(selectedId, { mode: "structured_json", data: values })
                    }
                    refreshKey={previewKey}
                    fitWidth
                    markPersistent={false}
                    highlights={previewHighlights}
                  />
                </div>

                <div className="review-fields">
                  <div className="review-head">
                    <h2 className="section-h">Fields ({fields.length})</h2>
                    <button className="btn" disabled={busy} onClick={generate}>
                      {busy ? <Spinner label="Generating…" /> : "Generate DOCX"}
                    </button>
                  </div>
                  <p className="muted" style={{ marginTop: 0 }}>
                    Values mapped into your template — edit anything that needs fixing.
                    {routing && routing.missing_required.length > 0 && (
                      <span style={{ color: "var(--red)" }}>
                        {" "}{routing.missing_required.length} required field(s) still need a value.
                      </span>
                    )}
                  </p>
                  <div className="field-cards">
                    <div className="field-cards-toolbar">
                      <span className="fc-density-hint">
                        Compact list — click a card’s arrow to fill it in.
                      </span>
                      <button
                        type="button"
                        className="fc-expand-all"
                        onClick={() => setAllFields(!allFieldsExpanded)}
                        title={allFieldsExpanded ? "Collapse every card" : "Expand every card"}
                      >
                        {allFieldsExpanded ? (
                          <>
                            <ChevronsDownUp size={14} strokeWidth={2} /> Collapse all
                          </>
                        ) : (
                          <>
                            <ChevronsUpDown size={14} strokeWidth={2} /> Expand all
                          </>
                        )}
                      </button>
                    </div>
                    {fields.map((f) => {
                      const placement =
                        routing?.placements.find((p) => p.field_name === f.field_name) || null;
                      const missing = routing?.missing_required.includes(f.field_name);
                      const open = expandedFields.has(f.field_name);
                      return (
                        <div
                          className={`field-card ${open ? "" : "compact"} ${
                            missing ? "needs-value" : ""
                          }`}
                          id={`genfield-${f.field_name}`}
                          key={f.field_name}
                        >
                          <div className="field-card-head">
                            <button
                              type="button"
                              className="field-card-chevron"
                              aria-expanded={open}
                              onClick={() => toggleField(f.field_name)}
                              title={open ? "Show less" : "Fill in this field"}
                            >
                              {open ? (
                                <ChevronDown size={16} strokeWidth={2.2} />
                              ) : (
                                <ChevronRight size={16} strokeWidth={2.2} />
                              )}
                            </button>
                            <button
                              type="button"
                              className="field-card-name fc-jump"
                              onClick={() => jumpToField(f.field_name)}
                              title="Jump to this field in the document preview"
                            >
                              {f.label} {f.required && <span className="req">*</span>}
                              <span className="fc-jump-icon">↦</span>
                            </button>
                            <span className="badge fixed" style={{ fontSize: 11 }}>
                              {f.field_type.replace(/_/g, " ")}
                            </span>
                            {placement && <RoutedChip p={placement} />}
                          </div>
                          {open ? (
                            <div style={{ marginTop: 8 }}>
                              {f.field_type === "table" ? (
                                <TableEditor
                                  field={f}
                                  rows={values[f.field_name] || []}
                                  onChange={(rows) =>
                                    setValues({ ...values, [f.field_name]: rows })
                                  }
                                />
                              ) : f.field_type === "image" ? (
                                <ImageInput
                                  value={values[f.field_name] || ""}
                                  onChange={(v) => setValues({ ...values, [f.field_name]: v })}
                                />
                              ) : f.field_type === "boolean" ? (
                                <label className="row" style={{ gap: 8, fontWeight: 400 }}>
                                  <input
                                    type="checkbox"
                                    style={{ width: "auto" }}
                                    checked={values[f.field_name] ?? true}
                                    onChange={(e) =>
                                      setValues({ ...values, [f.field_name]: e.target.checked })
                                    }
                                  />
                                  <span className="muted">Include this content</span>
                                </label>
                              ) : f.field_type === "multiline_text" ? (
                                <textarea
                                  value={values[f.field_name] || ""}
                                  onChange={(e) =>
                                    setValues({ ...values, [f.field_name]: e.target.value })
                                  }
                                  placeholder={
                                    f.classification === "REPEATABLE_SECTION"
                                      ? "One item per line…"
                                      : ""
                                  }
                                />
                              ) : (
                                <input
                                  value={values[f.field_name] || ""}
                                  onChange={(e) =>
                                    setValues({ ...values, [f.field_name]: e.target.value })
                                  }
                                />
                              )}
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="field-card-summary"
                              onClick={() => toggleField(f.field_name)}
                              title="Fill in this field"
                            >
                              <span
                                className={`fc-sum-value ${
                                  valuePreview(f) === "—" ? "empty" : ""
                                }`}
                              >
                                {valuePreview(f)}
                              </span>
                              {missing && <span className="fc-sum-req">· needs a value</span>}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </>
          )}

          {mode !== "form" && (
            <div className="row">
              <button className="btn" disabled={busy} onClick={generate}>
                {busy ? <Spinner label="Generating…" /> : "Generate DOCX"}
              </button>
            </div>
          )}

          {extracted && (
            <details className="extracted-box section">
              <summary>
                Extracted from your document
                <span className="muted"> · {extracted.length} block(s) — click to expand</span>
              </summary>
              <div className="extracted-scroll">
                <DocBlocks blocks={extracted} />
              </div>
            </details>
          )}
        </>
      )}

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
      <Sparkles size={11} strokeWidth={2} /> {pct}%{p.ambiguous ? " ?" : ""}
    </span>
  );
}

function ResultPanel({ result }: { result: GenerationResult }) {
  const v = result.validation;
  const [pdfMsg, setPdfMsg] = useState("");

  async function downloadPdf() {
    if (!result.download_url) return;
    setPdfMsg("Converting…");
    try {
      await api.download(
        `${result.download_url}.pdf`,
        (result.output_filename || "document.docx").replace(".docx", ".pdf"),
      );
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
          <button
            className="btn"
            onClick={() => api.download(result.download_url!, result.output_filename || undefined)}
          >
            <Download size={15} strokeWidth={1.9} /> Download {result.output_filename}
          </button>
        )}
        {result.download_url && (
          <button className="btn secondary" onClick={downloadPdf}>
            <Download size={15} strokeWidth={1.9} /> Download PDF
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
      {v && v.issues.length === 0 && <div className="muted">No validation issues.</div>}
    </div>
  );
}
