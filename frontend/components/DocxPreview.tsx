"use client";

import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui";

/**
 * Renders a .docx as a real Word page, in the browser, with docx-preview.
 *
 * This is the single preview engine: fast, fully client-side, and it produces a
 * DOM so paragraph highlights + click-to-jump work. The bytes come from
 * `load()`, so the same component serves the template-creation preview, the
 * compliance "expected"/uploaded documents, and the generate preview.
 *
 * Note: docx-preview reflows the document; floating Word shapes (free-anchored
 * text boxes / logos) land inline rather than pixel-exact. The exported .docx is
 * unaffected — this is a preview-fidelity trade-off we accept for a zero-dependency,
 * always-available, interactive preview.
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

  useEffect(() => {
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
          renderFootnotes: true,
          renderEndnotes: true,
          useBase64URL: true,
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
    // refreshKey lets the parent force a re-render after edits.
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`docx-canvas ${fitWidth ? "fit" : ""}`}>
      {loading && (
        <div className="docx-overlay">
          <Spinner label="Rendering Word preview…" />
        </div>
      )}
      {error && (
        <div className="docx-overlay">
          <div className="muted" style={{ textAlign: "center", padding: 24 }}>
            Couldn’t render the preview.
            <div style={{ fontSize: 12, marginTop: 6 }}>{error}</div>
          </div>
        </div>
      )}
      <div ref={hostRef} className="docx-host" />
    </div>
  );
}
