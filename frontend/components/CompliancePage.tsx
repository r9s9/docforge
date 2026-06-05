"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ComplianceReport, Template } from "@/lib/types";
import { ErrorBox, Spinner } from "@/components/ui";
import DocBlocks from "@/components/DocBlocks";

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
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch((e) => setError(String(e.message || e)));
  }, []);

  async function run() {
    if (!templateId || !file) return;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      setReport(await api.compliance(templateId, file));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
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
          {file ? `📄 ${file.name}` : "Choose .docx"}
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

      {report && <Report report={report} />}
    </div>
  );
}

function Report({ report }: { report: ComplianceReport }) {
  const color = GRADE_COLOR[report.grade] || "var(--muted)";
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
      </div>

      <h2 className="section-h" style={{ marginTop: 28 }}>
        Differences ({report.differences.length})
      </h2>
      {report.differences.length === 0 ? (
        <div className="card empty">Fully compliant — no differences found. 🎉</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Kind</th>
              <th>Field / Node</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {report.differences.map((d, i) => (
              <tr key={i}>
                <td>
                  <span
                    className={`badge ${d.severity === "error" ? "fail" : d.severity === "warning" ? "warning" : "fixed"}`}
                  >
                    {d.severity}
                  </span>
                </td>
                <td className="mono">{d.kind}</td>
                <td className="mono">{d.field_name || d.node_id}</td>
                <td>
                  {d.message}
                  {(d.expected || d.found) && (
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {d.expected && <>expected: “{d.expected}” </>}
                      {d.found && <>· found: “{d.found}”</>}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {report.document_preview.length > 0 && (
        <div className="section" style={{ marginTop: 28 }}>
          <h2 className="section-h">Checked document</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            The content extracted from your upload that was compared to the template.
          </p>
          <DocBlocks blocks={report.document_preview} />
        </div>
      )}
    </div>
  );
}
