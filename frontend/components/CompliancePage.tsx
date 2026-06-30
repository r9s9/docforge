"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ComplianceReport, Template } from "@/lib/types";
import { ErrorBox, Spinner, TokenUsageLine } from "@/components/ui";
import { FileText, Sparkles } from "@/components/icons";
import DocxPreview from "@/components/DocxPreview";

const GRADE_COLOR: Record<string, string> = {
  pass: "var(--green)",
  warning: "var(--amber)",
  fail: "var(--red)",
};

export default function CompliancePage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ComplianceReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fixBusy, setFixBusy] = useState(false);
  const [fixMsg, setFixMsg] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch((e) => setError(String(e.message || e)));
  }, []);

  async function run() {
    if (!templateId || !file) return;
    setBusy(true);
    setError("");
    setReport(null);
    setFixMsg("");
    try {
      setReport(await api.compliance(templateId, file));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function fixDoc() {
    if (!templateId || !file || !report) return;
    setFixBusy(true);
    setFixMsg("");
    setError("");
    try {
      const { blob, fixed, filename } = await api.complianceFix(templateId, file, report.version);
      if (fixed > 0) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        setFixMsg(`Applied ${fixed} fix${fixed === 1 ? "" : "es"} — downloaded ${filename}.`);
      } else {
        setFixMsg("No fixed-text (boilerplate) issues to repair in this document.");
      }
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setFixBusy(false);
    }
  }

  return (
    <div>
      <h1 className="page-title">Compliance Check</h1>
      <p className="page-sub">
        Compare a document against a template to get a compliance score and a list of differences.
      </p>

      {error && <ErrorBox message={error} />}

      <div className="row section" style={{ alignItems: "flex-end" }}>
        <label className="field" style={{ marginBottom: 0, minWidth: 280 }}>
          <span>Template</span>
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">Select a template…</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} (v{t.latest_version})
              </option>
            ))}
          </select>
        </label>
        <button className="btn secondary" onClick={() => inputRef.current?.click()}>
          {file ? (
            <>
              <FileText size={15} strokeWidth={1.9} /> {file.name}
            </>
          ) : (
            "Choose .docx"
          )}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".docx"
          hidden
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <button className="btn" onClick={run} disabled={busy || !templateId || !file}>
          {busy ? <Spinner label="Checking…" /> : "Check compliance"}
        </button>
      </div>

      {report && file && (
        <Report
          report={report}
          file={file}
          templateId={templateId}
          onFix={fixDoc}
          fixBusy={fixBusy}
          fixMsg={fixMsg}
        />
      )}
    </div>
  );
}

function Report({
  report,
  file,
  templateId,
  onFix,
  fixBusy,
  fixMsg,
}: {
  report: ComplianceReport;
  file: File;
  templateId: string;
  onFix: () => void;
  fixBusy: boolean;
  fixMsg: string;
}) {
  const color = GRADE_COLOR[report.grade] || "var(--muted)";
  const [selected, setSelected] = useState<string | null>(null);
  // Keyed (by template node id) highlights so clicking a difference can scroll
  // the matching paragraph in either Word page into view.
  const actionable = report.alignment.filter(
    (p) => p.status === "changed" || p.status === "missing" || p.status === "field_missing",
  );
  const leftHighlights = actionable
    .filter((p) => p.template_text)
    .map((p) => ({ key: p.node_id, text: p.template_text }));
  const rightHighlights = actionable
    .filter((p) => p.status === "changed" && p.document_text)
    .map((p) => ({ key: p.node_id, text: p.document_text }));

  function jumpTo(nodeId: string | null) {
    if (!nodeId) return;
    setSelected(nodeId);
    // Clear the previously-selected paragraphs (back to the default yellow), then
    // mark the chosen difference's paragraphs mellow red on both pages.
    document
      .querySelectorAll<HTMLElement>(".docx-hl-selected")
      .forEach((el) => el.classList.remove("docx-hl-selected"));
    const matches = document.querySelectorAll<HTMLElement>(`[data-hl="${nodeId}"]`);
    matches.forEach((el, i) => {
      el.classList.add("docx-hl-selected");
      if (i === 0) el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  return (
    <div className="section">
      <div className="card" style={{ display: "flex", gap: 32, alignItems: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 56, fontWeight: 600, color }}>
            {Math.round(report.score)}
          </div>
          <span className={`badge ${report.grade}`}>{report.grade}</span>
        </div>
        <div style={{ flex: 1 }}>
          <div className="muted" style={{ marginBottom: 10 }}>
            {report.document_name} · {report.matched_fields.length} fields matched
            {report.missing_fields.length > 0 && `, ${report.missing_fields.length} missing`}
          </div>
          {report.dimensions.map((d) => (
            <div key={d.name} className="row" style={{ gap: 12, marginBottom: 8 }}>
              <span style={{ width: 90, textTransform: "capitalize" }}>{d.name}</span>
              <span className="conf-bar" style={{ flex: 1, maxWidth: 320 }}>
                <i style={{ width: `${d.score}%` }} />
              </span>
              <span className="muted">{Math.round(d.score)}%</span>
            </div>
          ))}
        </div>
        <div style={{ textAlign: "right" }}>
          <button
            className="btn"
            onClick={onFix}
            disabled={fixBusy || !report.fixable}
            title={
              report.fixable
                ? "Restore changed/missing boilerplate to match the template"
                : "No fixed-text issues to repair"
            }
          >
            {fixBusy ? (
              <Spinner label="Fixing…" />
            ) : (
              <>
                <Sparkles size={14} strokeWidth={2} /> Fix to match template
              </>
            )}
          </button>
          <div className="muted" style={{ fontSize: 12, marginTop: 6, maxWidth: 220 }}>
            Restores boilerplate text; keeps your field values &amp; extra content.
          </div>
        </div>
      </div>

      {report.token_usage ? (
        <div className="section" style={{ marginTop: 10 }}>
          <TokenUsageLine usage={report.token_usage} />
        </div>
      ) : null}

      {fixMsg && (
        <div className="banner info section" role="status">
          {fixMsg}
        </div>
      )}

      <div className="section" style={{ marginTop: 28 }}>
        <h2 className="section-h">Side-by-side comparison</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          The template&apos;s example (left) and your document (right) as full A4 pages, with the
          differences listed between them. All differing lines are highlighted in{" "}
          <span className="cmp-hl-key">yellow</span>; click a difference to jump to it and mark that
          line in <span className="cmp-hl-sel">red</span>.
        </p>
        <div className="cmp-3col">
          <div className="cmp-doc-col">
            <div className="cmp-docx-head">Template (expected)</div>
            <DocxPreview
              load={() => api.representativeDocx(templateId, report.version)}
              highlights={leftHighlights}
              fitWidth
            />
          </div>

          <div className="cmp-diff-mid">
            <div className="cmp-docx-head">Differences ({report.differences.length})</div>
            {report.differences.length === 0 ? (
              <div className="card empty" style={{ padding: 18 }}>
                Fully compliant — no differences.
              </div>
            ) : (
              <div className="cmp-diff-list">
                {report.differences.map((d, i) => (
                  <button
                    key={i}
                    className={`cmp-diff-item sev-${d.severity} ${
                      selected && d.node_id === selected ? "active" : ""
                    }`}
                    onClick={() => jumpTo(d.node_id)}
                    title="Jump to this difference in the documents"
                  >
                    <div className="cmp-diff-row1">
                      <span
                        className={`badge ${d.severity === "error" ? "fail" : d.severity === "warning" ? "warning" : "fixed"}`}
                      >
                        {d.severity}
                      </span>
                      <span className="mono cmp-diff-field">
                        {d.field_name || d.kind.replace(/_/g, " ")}
                      </span>
                      <span className="cmp-diff-jump">↦</span>
                    </div>
                    <div className="cmp-diff-msg">{d.message}</div>
                    {(d.expected || d.found) && (
                      <div className="muted cmp-diff-ef">
                        {d.expected && <div>expected: “{d.expected}”</div>}
                        {d.found && <div>found: “{d.found}”</div>}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="cmp-doc-col">
            <div className="cmp-docx-head">Your document</div>
            <DocxPreview load={() => file.arrayBuffer()} highlights={rightHighlights} fitWidth />
          </div>
        </div>
      </div>
    </div>
  );
}
