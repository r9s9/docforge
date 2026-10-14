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

// Text that stands in for a value: a {{ tag }}, a {% control %} tag, or a «Label».
const STAND_IN = /\{\{|\{%|«/;
// A paragraph that is nothing but control tags ({%p if %}, {%tr for … %}).
const CONTROL_ONLY = /^\s*(\{%[^%]*%\}\s*)+$/;
// Never shrink below this share of the original size: still readable.
const MIN_SCALE = 0.5;

/** Lines a paragraph's text occupies, as laid out. */
function lineCount(p: HTMLElement): number {
  const range = document.createRange();
  range.selectNodeContents(p);
  const tops: number[] = [];
  for (const r of range.getClientRects()) {
    if (r.width > 0 && !tops.some((t) => Math.abs(t - r.top) < 3)) tops.push(r.top);
  }
  return tops.length;
}

/** Scale a paragraph's text (and every run in it) from its original sizes. */
function scaler(p: HTMLElement): (scale: number) => void {
  const els = [p, ...p.querySelectorAll<HTMLElement>("span")];
  const base = els.map((el) => parseFloat(getComputedStyle(el).fontSize) || 0);
  return (scale) =>
    els.forEach((el, i) => {
      if (base[i]) el.style.fontSize = `${base[i] * scale}px`;
    });
}

/**
 * For viewing only: keep a template's tables looking like the document.
 *
 * A tag is often longer than the word it replaced, so in a narrow column it
 * wraps and stretches the row. Each wrapping stand-in shrinks just enough to
 * sit on one line (down to MIN_SCALE). A loop's control row ({%tr for … %})
 * has nothing else in it, so its tag runs across the row on one line instead
 * of wrapping in the first cell, and control lines are greyed: instructions,
 * not content. Only this rendered preview changes; the template file, its
 * downloads and generated documents keep the original sizes.
 */
function fitStandIns(host: HTMLElement) {
  // Lay each table out at the document's own column widths. Sized by their
  // content, the columns stretch around a long tag (the very distortion this
  // removes) and narrow again as it shrinks, so nothing would ever fit.
  for (const table of host.querySelectorAll<HTMLElement>(".docx table")) {
    if (table.querySelector("colgroup col")) table.style.tableLayout = "fixed";
  }

  const standIns = [...host.querySelectorAll<HTMLElement>(".docx p")].filter((p) =>
    STAND_IN.test(p.textContent || ""),
  );
  const controls = standIns.filter((p) => CONTROL_ONLY.test(p.textContent || ""));
  controls.forEach((p) => p.classList.add("docx-ctl"));

  // Control rows first: taking their tags out of the column widths changes
  // the widths every other cell is measured against.
  const inCells = controls.filter((p) => p.closest("td"));
  for (const p of inCells) {
    // A loop's control row holds its tag in the first cell and nothing else:
    // shown as one cell across the row, the tag reads on one line instead of
    // down a narrow first column. No wrapping either way.
    for (const el of [p, ...p.querySelectorAll<HTMLElement>("span")]) el.style.whiteSpace = "nowrap";
    const cell = p.closest("td") as HTMLTableCellElement;
    const others = [...(cell.parentElement?.children || [])].filter(
      (c): c is HTMLTableCellElement => c !== cell && c instanceof HTMLTableCellElement,
    );
    if (others.length && others.every((c) => !(c.textContent || "").trim())) {
      cell.colSpan = others.reduce((n, c) => n + c.colSpan, cell.colSpan);
      others.forEach((c) => c.remove());
    } else {
      cell.style.overflow = "hidden";
    }
  }
  for (const p of inCells) {
    const cell = p.closest("td") as HTMLElement;
    const room = cell.clientWidth - parseFloat(getComputedStyle(cell).paddingLeft || "0")
      - parseFloat(getComputedStyle(cell).paddingRight || "0");
    const range = document.createRange();
    range.selectNodeContents(p);
    const width = range.getBoundingClientRect().width;
    if (room > 0 && width > room) scaler(p)(Math.max(MIN_SCALE, (room / width) * 0.98));
  }

  for (const p of standIns) {
    if (controls.includes(p) || !p.closest("td")) continue; // body text wraps normally
    if (lineCount(p) <= 1) continue;
    const scale = scaler(p);
    let s = 1;
    while (s > MIN_SCALE && lineCount(p) > 1) {
      s = Math.max(MIN_SCALE, s * 0.92);
      scale(s);
    }
    // Still too long at the smallest size (a column a few points wide): keep
    // the row's height and cut the tag short; hovering shows all of it.
    if (lineCount(p) > 1) {
      for (const el of [p, ...p.querySelectorAll<HTMLElement>("span")]) el.style.whiteSpace = "nowrap";
      p.style.overflow = "hidden";
      p.style.textOverflow = "ellipsis";
      p.title = (p.textContent || "").trim();
    }
  }
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
  fitTags = false,
}: {
  load: () => Promise<ArrayBuffer>;
  refreshKey?: number;
  highlights?: DocxHighlight[];
  fitWidth?: boolean;
  // When false, paragraphs are tagged with data-hl (for click-to-jump) but NOT
  // given the persistent highlight background — used by the Generate preview.
  markPersistent?: boolean;
  // Viewing a template: shrink tags/«Labels» that overflow their table cell.
  fitTags?: boolean;
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

        // Before fitWidth's zoom, so the cells are measured at page size.
        if (fitTags) fitStandIns(host);

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
