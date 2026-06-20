"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Spinner } from "@/components/ui";

/**
 * Renders a .docx as a real Word page. Two modes:
 *  - "live": docx-preview in the browser — fast, gives a DOM so paragraph
 *    highlights + click-to-jump work. Cannot faithfully place floating Word
 *    shapes (text boxes, anchored logos).
 *  - "faithful": the server renders the exact Word layout to PDF (LibreOffice)
 *    and we show it in an <iframe>. Pixel-perfect, but no in-document highlights.
 *
 * The bytes come from `load()`, so the same component serves the template-creation
 * preview, the compliance "expected"/uploaded documents, and the generate preview.
 */
function norm(s: string): string {
  return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
}

export interface DocxHighlight {
  key: string;
  text: string;
}

export default function DocxPreview({
  load,
  refreshKey = 0,
  highlights,
  fitWidth = false,
  markPersistent = true,
}: {
  load: () => Promise<ArrayBuffer>;
  refreshKey?: number;
  highlights?: DocxHighlight[];
  fitWidth?: boolean;
  // When false, paragraphs are tagged with data-hl (for click-to-jump) but NOT
  // given the persistent highlight background — used by the Generate preview.
  markPersistent?: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // "Faithful" (server PDF) mode — opt-in, remembered across refreshes.
  const [faithful, setFaithful] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState("");

  // ---- live docx-preview render ----
  useEffect(() => {
    if (faithful) return; // live render is paused while showing the PDF
    let cancelled = false;
    setLoading(true);
    setError("");

    (async () => {
      try {
        const [{ renderAsync }, buf] = await Promise.all([import("docx-preview"), load()]);
        if (cancelled || !hostRef.current) return;
        const host = hostRef.current;
        host.style.removeProperty("zoom");
        host.innerHTML = "";
        await renderAsync(buf, host, undefined, {
          className: "docx",
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          experimental: true,
          renderHeaders: true,
          renderFooters: true,
        });
        if (cancelled) return;

        if (highlights && highlights.length) {
          const used = new Set<HTMLElement>();
          const taggedKeys = new Set<string>();
          const paras = [...host.querySelectorAll<HTMLElement>(".docx p")];
          for (const h of highlights) {
            if (taggedKeys.has(h.key)) continue;
            const t = norm(h.text);
            if (t.length < 4) continue;
            const p = paras.find(
              (el) => !used.has(el) && norm(el.textContent || "").includes(t),
            );
            if (p) {
              used.add(p);
              taggedKeys.add(h.key);
              p.dataset.hl = h.key;
              if (markPersistent) p.classList.add("docx-hl");
            }
          }
        }

        if (fitWidth) {
          const page = host.querySelector<HTMLElement>("section.docx");
          if (page) {
            const avail = host.clientWidth;
            const pageW = page.getBoundingClientRect().width;
            if (avail > 0 && pageW > 0) {
              host.style.setProperty("zoom", String(Math.min(1, avail / pageW)));
            }
          }
        }
      } catch (e: any) {
        if (!cancelled) setError(String(e?.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // refreshKey lets the parent force a re-render after edits / toggle.
  }, [refreshKey, faithful]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- faithful (server PDF) render ----
  useEffect(() => {
    if (!faithful) return;
    let cancelled = false;
    let url = "";
    setPdfLoading(true);
    setPdfError("");
    setPdfUrl("");

    (async () => {
      try {
        const buf = await load();
        const blob = await api.renderPdf(buf);
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setPdfUrl(url);
      } catch (e: any) {
        if (!cancelled) setPdfError(String(e?.message || e));
      } finally {
        if (!cancelled) setPdfLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [refreshKey, faithful]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`docx-canvas ${fitWidth ? "fit" : ""} ${faithful ? "is-pdf" : ""}`}>
      <div className="docx-modes">
        <button
          className={!faithful ? "active" : ""}
          onClick={() => setFaithful(false)}
          type="button"
          title="Fast in-browser preview with clickable fields"
        >
          Live
        </button>
        <button
          className={faithful ? "active" : ""}
          onClick={() => setFaithful(true)}
          type="button"
          title="Exact Word layout, rendered on the server"
        >
          Faithful view
        </button>
      </div>

      {!faithful && loading && (
        <div className="docx-overlay">
          <Spinner label="Rendering Word preview…" />
        </div>
      )}
      {!faithful && error && (
        <div className="docx-overlay">
          <div className="muted" style={{ textAlign: "center", padding: 24 }}>
            Couldn’t render the preview.
            <div style={{ fontSize: 12, marginTop: 6 }}>{error}</div>
          </div>
        </div>
      )}

      {faithful && pdfLoading && (
        <div className="docx-overlay">
          <Spinner label="Rendering exact Word layout…" />
        </div>
      )}
      {faithful && pdfError && (
        <div className="docx-overlay">
          <div className="muted" style={{ textAlign: "center", padding: 24, maxWidth: 360 }}>
            Faithful view isn’t available here.
            <div style={{ fontSize: 12, marginTop: 6 }}>{pdfError}</div>
            <button
              className="btn secondary small"
              style={{ marginTop: 12 }}
              onClick={() => setFaithful(false)}
            >
              Back to live preview
            </button>
          </div>
        </div>
      )}

      {faithful ? (
        pdfUrl ? (
          <iframe className="docx-pdf" src={pdfUrl} title="Faithful document preview" />
        ) : null
      ) : (
        <div ref={hostRef} className="docx-host" />
      )}
    </div>
  );
}
