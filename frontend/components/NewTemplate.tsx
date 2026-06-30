"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AnalysisJob, FieldDefinition, Project } from "@/lib/types";
import { AiBadge, AiStatusBanner, ErrorBox, Spinner, TokenUsageLine } from "@/components/ui";
import { RotateCw } from "@/components/icons";
import ProgressBar from "@/components/ProgressBar";
import DocxPreview from "@/components/DocxPreview";
import FieldCards, { type EditableField } from "@/components/FieldCards";

/** Mirror of the backend slugify so promoted-field names look consistent. */
function slugify(s: string): string {
  return (
    (s || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 40) || "field"
  );
}

function uniqueName(base: string, used: Set<string>): string {
  if (!used.has(base)) return base;
  let i = 2;
  while (used.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
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
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [fields, setFields] = useState<EditableField[]>([]);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string | null>(null);
  // Retained for field-card highlighting; click-to-jump was tied to the removed
  // color-coded view, so there is no setter wired up right now.
  const [selectedField] = useState<string | null>(null);
  const [previewMode, setPreviewMode] = useState<"filled" | "tags">("filled");
  // Snapshot of the fields the Word preview was last rendered from; bumping the
  // key (on toggle / "Update preview") re-renders against the current edits.
  const [previewKey, setPreviewKey] = useState(0);
  const [previewFields, setPreviewFields] = useState<FieldDefinition[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  // Track the in-flight analysis so we can stop the model when the user cancels
  // or navigates away (otherwise the local LLM keeps generating in LM Studio).
  const activeJobId = useRef<string | null>(null);
  const cancelledRef = useRef(false);

  // Cancel the running job if the user leaves the page mid-analysis.
  useEffect(() => {
    return () => {
      if (activeJobId.current) {
        api.cancelAnalysisBeacon(activeJobId.current);
        activeJobId.current = null;
      }
    };
  }, []);

  // Load the user's projects so a new template can be assigned to one on publish.
  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  // Re-render the Word preview from the user's current (included) edits.
  function updatePreview() {
    setPreviewFields(fields.filter((e) => e.include).map((e) => ({ ...e.field })));
    setPreviewKey((k) => k + 1);
  }

  function setMode(mode: "filled" | "tags") {
    if (mode === previewMode) return;
    setPreviewMode(mode);
    setPreviewFields(fields.filter((e) => e.include).map((e) => ({ ...e.field })));
    setPreviewKey((k) => k + 1);
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
    cancelledRef.current = false;
    try {
      // Analysis runs in the background (the LLM can be slow); poll for live progress.
      let result = await api.analyze(files);
      activeJobId.current = result.id;
      setProgress(result.progress || 0);
      setStage(result.stage);
      let tries = 0;
      while ((result.status === "pending" || result.status === "running") && tries < 480) {
        if (cancelledRef.current) break;
        await new Promise((r) => setTimeout(r, 1000));
        if (cancelledRef.current) break;
        result = await api.getAnalysis(result.id);
        setProgress(result.progress || 0);
        setStage(result.stage);
        tries += 1;
      }
      if (cancelledRef.current || result.status === "cancelled") {
        setStage("Cancelled");
        setError("Analysis cancelled — the model was stopped.");
        return;
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
      // Image fields default to "keep original" (excluded) so logos/icons are
      // never lost — the user opts a picture into being replaceable. All other
      // fields are included by default.
      setFields(
        result.field_definitions.map((f) => ({
          field: { ...f },
          include: f.field_type !== "image",
        })),
      );
      setPreviewFields(
        result.field_definitions.filter((f) => f.field_type !== "image").map((f) => ({ ...f })),
      );
      setPreviewKey((k) => k + 1);
      setStep("review");
    } catch (e: any) {
      if (!cancelledRef.current) setError(String(e.message || e));
    } finally {
      activeJobId.current = null;
      setBusy(false);
    }
  }

  async function cancelAnalysis() {
    cancelledRef.current = true;
    setStage("Cancelling…");
    const id = activeJobId.current;
    if (id) {
      try {
        await api.cancelAnalysis(id);
      } catch {
        /* the polling loop already stopped; ignore */
      }
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

  // Promote a fixed document element into a fillable field. Its whole paragraph
  // becomes the field value at generation; on publish we send a DYNAMIC_TEXT
  // classification override for that node so the builder templatizes it.
  function promoteToField(el: { node_id: string; text: string }) {
    setFields((prev) => {
      const used = new Set(prev.map((e) => e.field.field_name));
      const name = uniqueName(slugify(el.text), used);
      const fd: FieldDefinition = {
        field_name: name,
        label: el.text.trim().slice(0, 48) || name,
        field_type: "text",
        classification: "DYNAMIC_TEXT",
        description: "",
        required: true,
        enum_values: [],
        default: null,
        node_ids: [el.node_id],
        section_key: null,
        columns: [],
        confidence: 1,
      };
      return [...prev, { field: fd, include: true }];
    });
    // Reflect the new field in the Word preview immediately.
    setTimeout(updatePreview, 0);
  }

  // Click a field card → highlight + scroll to its element in the Word preview.
  function jumpTo(fieldName: string) {
    document
      .querySelectorAll<HTMLElement>(".docx-hl-selected")
      .forEach((el) => el.classList.remove("docx-hl-selected"));
    const matches = document.querySelectorAll<HTMLElement>(`[data-hl="${fieldName}"]`);
    matches.forEach((el, i) => {
      el.classList.add("docx-hl-selected");
      if (i === 0) el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
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
          // Carry the field's classification too, so a promoted FIXED element
          // actually becomes dynamic (and the builder templatizes its node).
          return {
            ...c,
            classification: f.classification,
            field_name: f.field_name,
            field_type: f.field_type,
            required: f.required,
          };
        return c;
      });

      const payload = {
        analysis_job_id: job.id,
        name,
        document_type: job.document_type_guess,
        project_id: projectId || undefined,
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
                  <button
                    className="btn secondary"
                    style={{ marginLeft: 10 }}
                    onClick={cancelAnalysis}
                  >
                    Cancel
                  </button>
                )}
                {busy && (
                  <div style={{ marginTop: 16 }}>
                    <ProgressBar percent={progress} stage={stage} busy />
                    <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                      Local AI models can take a minute or two — you can watch it work above. It
                      falls back to the fast heuristic engine if the model is too slow.
                      Cancelling stops the model immediately.
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

          <label className="field" style={{ maxWidth: 440 }}>
            <span>Project (optional)</span>
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">No project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {projectId && (
              <span className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                This template will inherit the project’s metadata at generation.
              </span>
            )}
          </label>

          <div className="row section" style={{ gap: 8 }}>
            <span className="muted">Detected type:</span>
            <strong>{job.document_type_guess}</strong>
            <span className="muted">· {job.source_document_ids.length} doc(s)</span>
            <span className="muted">· engine: {job.model_used || "heuristic"}</span>
            {job.token_usage ? <TokenUsageLine usage={job.token_usage} /> : null}
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

          <div className="banner info section">
            <strong>Here’s your reusable template.</strong> DocForge turned your example
            into a Word template — each <em>variable</em> part becomes a fillable field.
            Check the document preview on the left and the fields on the right; adjust any
            names or types, then <strong>Publish</strong>.
          </div>

          <div className="review-grid">
            <div className="review-doc">
              <div className="review-head">
                <h2 className="section-h">Document preview</h2>
                <div className="seg-toggle" role="tablist" aria-label="Preview mode">
                  <button
                    className={previewMode === "filled" ? "active" : ""}
                    onClick={() => setMode("filled")}
                  >
                    Sample-filled
                  </button>
                  <button
                    className={previewMode === "tags" ? "active" : ""}
                    onClick={() => setMode("tags")}
                  >
                    Template tags
                  </button>
                </div>
              </div>
              <p className="muted" style={{ marginTop: 0 }}>
                {previewMode === "filled"
                  ? "A real Word page with each variable shown as «Label». This is how the document is structured."
                  : "The raw template with {{ placeholders }} and loop tags — what the engine fills in."}
              </p>
              <DocxPreview
                load={() => api.analysisPreviewDocx(job.id, previewMode, previewFields)}
                refreshKey={previewKey}
                markPersistent={false}
                highlights={previewFields.flatMap((f) => [
                  { key: f.field_name, text: f.field_name },
                  { key: f.field_name, text: f.label },
                ])}
              />
            </div>

            <div className="review-fields">
              <div className="review-head">
                <h2 className="section-h">
                  Fields ({fields.filter((f) => f.include).length})
                </h2>
                <button className="btn secondary small" onClick={updatePreview}>
                  <RotateCw size={14} strokeWidth={1.9} /> Update preview
                </button>
              </div>
              <p className="muted" style={{ marginTop: 0 }}>
                Each card is one fillable field. Edit its name or type, or untick it to keep
                that text fixed. Then refresh the preview to see your changes.
              </p>
              <div className="banner info" style={{ marginBottom: 14 }}>
                <strong>Tip — write a description for each field.</strong> A clear description
                (e.g. “Invoice total in EUR, numbers only”) is read by the AI when generating a
                document from plain notes, so the more specific you are, the more accurately your
                content is mapped to the right field.
              </div>
              <FieldCards
                items={fields}
                onUpdate={updateField}
                onToggle={toggleInclude}
                onJump={jumpTo}
                selected={selectedField}
              />

              {(() => {
                const usedNodes = new Set(fields.flatMap((e) => e.field.node_ids));
                const candidates = (job.elements || []).filter(
                  (el) =>
                    el.classification === "FIXED" &&
                    (el.type === "paragraph" || el.type === "heading") &&
                    !el.headers &&
                    (el.text || "").trim().length > 1 &&
                    !usedNodes.has(el.node_id),
                );
                if (candidates.length === 0) return null;
                return (
                  <details className="promote-box section">
                    <summary>
                      Missing a field? Make one from fixed text ({candidates.length})
                    </summary>
                    <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 10px" }}>
                      Anything DocForge kept as fixed is listed here. Click{" "}
                      <strong>Make field</strong> to turn that text into a fillable field.
                    </p>
                    <div className="promote-list">
                      {candidates.map((el) => (
                        <div className="promote-row" key={el.node_id}>
                          <span className="promote-text" title={el.text}>
                            {el.text.trim().slice(0, 90)}
                          </span>
                          <button
                            className="btn secondary small"
                            onClick={() => promoteToField(el)}
                          >
                            Make field
                          </button>
                        </div>
                      ))}
                    </div>
                  </details>
                );
              })()}
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
