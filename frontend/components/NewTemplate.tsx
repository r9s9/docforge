"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AnalysisJob, FieldDefinition } from "@/lib/types";
import { AiBadge, AiStatusBanner, ClassificationBadge, Confidence, ErrorBox, Spinner } from "@/components/ui";
import ProgressBar from "@/components/ProgressBar";
import ReviewElements from "@/components/ReviewElements";

const FIELD_TYPES = ["text", "multiline_text", "date", "person", "number", "enum", "table", "boolean"];

interface EditableField {
  field: FieldDefinition;
  include: boolean;
}

export default function NewTemplate() {
  const router = useRouter();
  const [step, setStep] = useState<"upload" | "review">("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [name, setName] = useState("");
  const [fields, setFields] = useState<EditableField[]>([]);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string | null>(null);
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function selectField(fieldName: string) {
    setSelectedField(fieldName);
    const row = document.getElementById(`fieldrow-${fieldName}`);
    if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list).filter((f) => f.name.toLowerCase().endsWith(".docx"));
    setFiles((prev) => [...prev, ...incoming].slice(0, 5));
  }

  async function analyze() {
    setBusy(true);
    setError("");
    setProgress(0);
    setStage("Uploading…");
    try {
      // Analysis runs in the background (the LLM can be slow); poll for live progress.
      let result = await api.analyze(files);
      setProgress(result.progress || 0);
      setStage(result.stage);
      let tries = 0;
      while ((result.status === "pending" || result.status === "running") && tries < 480) {
        await new Promise((r) => setTimeout(r, 1000));
        result = await api.getAnalysis(result.id);
        setProgress(result.progress || 0);
        setStage(result.stage);
        tries += 1;
      }
      if (result.status === "failed") {
        setError(result.error || "Analysis failed.");
        return;
      }
      if (result.status !== "completed") {
        setError("Analysis is taking too long — try again, or disable AI in Settings to use the fast heuristic engine.");
        return;
      }
      setJob(result);
      setName(result.name || result.document_type_guess || "Untitled Template");
      setFields(result.field_definitions.map((f) => ({ field: { ...f }, include: true })));
      setStep("review");
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  function updateField(i: number, patch: Partial<FieldDefinition>) {
    setFields((prev) =>
      prev.map((ef, idx) => (idx === i ? { ...ef, field: { ...ef.field, ...patch } } : ef))
    );
  }

  function toggleInclude(i: number) {
    setFields((prev) => prev.map((ef, idx) => (idx === i ? { ...ef, include: !ef.include } : ef)));
  }

  async function publish() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const excluded = new Set(fields.filter((e) => !e.include).flatMap((e) => e.field.node_ids));
      const includedByNode = new Map<string, FieldDefinition>();
      fields
        .filter((e) => e.include)
        .forEach((e) => e.field.node_ids.forEach((nid) => includedByNode.set(nid, e.field)));

      const classifications = job.classifications.map((c) => {
        if (excluded.has(c.node_id)) return { ...c, classification: "FIXED", field_name: null };
        const f = includedByNode.get(c.node_id);
        if (f)
          return { ...c, field_name: f.field_name, field_type: f.field_type, required: f.required };
        return c;
      });

      const payload = {
        analysis_job_id: job.id,
        name,
        document_type: job.document_type_guess,
        fields: fields.filter((e) => e.include).map((e) => e.field),
        classifications,
      };
      const res = await api.publish(payload);
      router.push(`/templates/${res.template.id}`);
    } catch (e: any) {
      setError(String(e.message || e));
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">New Template</h1>
      <p className="page-sub">Upload 1–5 filled example documents of the same type.</p>

      <div className="steps">
        <div className={`step ${step === "upload" ? "active" : "done"}`}>1 · Upload examples</div>
        <div className={`step ${step === "review" ? "active" : ""}`}>2 · Review &amp; publish</div>
      </div>

      <AiStatusBanner />

      {error && <ErrorBox message={error} />}

      {step === "upload" && (
        <div className="section">
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              addFiles(e.dataTransfer.files);
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".docx"
              multiple
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
            <strong>Click or drop .docx files here</strong>
            <div>Up to 5 files. More examples → better fixed vs dynamic detection.</div>
          </div>

          {files.length > 0 && (
            <div className="section" style={{ marginTop: 18 }}>
              <table>
                <tbody>
                  {files.map((f, i) => (
                    <tr key={i}>
                      <td>{f.name}</td>
                      <td className="muted">{(f.size / 1024).toFixed(0)} KB</td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          className="btn secondary small"
                          onClick={() => setFiles(files.filter((_, idx) => idx !== i))}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop: 18 }}>
                <button className="btn" disabled={busy || files.length === 0} onClick={analyze}>
                  {busy ? (
                    <Spinner label="Analyzing…" />
                  ) : (
                    <>
                      Analyze {files.length} file(s) <AiBadge />
                    </>
                  )}
                </button>
                {busy && (
                  <div style={{ marginTop: 16 }}>
                    <ProgressBar percent={progress} stage={stage} busy />
                    <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                      Local AI models can take a minute or two — you can watch it work above. It
                      falls back to the fast heuristic engine if the model is too slow.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {step === "review" && job && (
        <div className="section">
          {job.ai_warning && (
            <div className="banner warn section" role="status">
              <strong>⚠ AI was skipped for this document.</strong>{" "}
              {job.ai_warning.replace(/^AI was skipped[^.]*\.\s*/, "")}
              <div className="muted" style={{ marginTop: 4 }}>
                The template below was built with built-in heuristics. Fix the issue
                above and re-run to use AI.
              </div>
            </div>
          )}

          <label className="field" style={{ maxWidth: 440 }}>
            <span>Template name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>

          <div className="row section" style={{ gap: 8 }}>
            <span className="muted">Detected type:</span>
            <strong>{job.document_type_guess}</strong>
            <span className="muted">· {job.source_document_ids.length} doc(s)</span>
            <span className="muted">· engine: {job.model_used || "heuristic"}</span>
          </div>

          {job.diff_summary && (
            <div className="pill-list section">
              {Object.entries(job.diff_summary).map(([k, v]) => (
                <span className="chip" key={k}>
                  {k.replace(/_/g, " ")}: {v}
                </span>
              ))}
            </div>
          )}

          <div className="review-grid">
            <div>
              <h2 className="section-h">Document</h2>
              <p className="muted" style={{ marginTop: 0 }}>
                Your document, color-coded by behaviour. Click a highlighted
                placeholder to jump to its field.
              </p>
              <ReviewElements
                elements={job.elements || []}
                selected={selectedField}
                onSelect={selectField}
              />
            </div>

            <div className="review-fields">
              <h2 className="section-h">Fields ({fields.filter((f) => f.include).length})</h2>
              <p className="muted" style={{ marginTop: 0 }}>
                Edit names, types and requirements. Uncheck a field to keep it fixed.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Use</th>
                    <th>Field name</th>
                    <th>Label</th>
                    <th>Type</th>
                    <th>Req</th>
                    <th>Class</th>
                    <th>Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map((ef, i) => (
                    <tr
                      key={i}
                      id={`fieldrow-${ef.field.field_name}`}
                      className={`${ef.field.confidence < 0.6 ? "low-conf" : ""} ${
                        ef.field.field_name === selectedField ? "row-selected" : ""
                      }`}
                    >
                      <td>
                    <input
                      type="checkbox"
                      style={{ width: "auto" }}
                      checked={ef.include}
                      onChange={() => toggleInclude(i)}
                    />
                  </td>
                  <td>
                    <input
                      className="mono"
                      value={ef.field.field_name}
                      onChange={(e) => updateField(i, { field_name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      value={ef.field.label}
                      onChange={(e) => updateField(i, { label: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      value={ef.field.field_type}
                      onChange={(e) => updateField(i, { field_type: e.target.value })}
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
                      checked={ef.field.required}
                      onChange={(e) => updateField(i, { required: e.target.checked })}
                    />
                  </td>
                  <td>
                    <ClassificationBadge value={ef.field.classification} />
                    {ef.field.columns.length > 0 && (
                      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                        cols: {ef.field.columns.map((c) => c.field_name).join(", ")}
                      </div>
                    )}
                  </td>
                  <td>
                    <Confidence value={ef.field.confidence} />
                  </td>
                </tr>
              ))}
            </tbody>
              </table>
            </div>
          </div>

          <div className="row" style={{ marginTop: 22 }}>
            <button className="btn" disabled={busy} onClick={publish}>
              {busy ? <Spinner label="Publishing…" /> : "Publish Template"}
            </button>
            <button className="btn secondary" onClick={() => setStep("upload")} disabled={busy}>
              Back
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
