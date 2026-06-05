"use client";

import type { PreviewBlock } from "@/lib/types";

// Renders ordered document blocks (paragraphs / headings / tables) in a
// page-like preview. Reused by generation preview, compliance, and the
// from-document extraction view.
export default function DocBlocks({ blocks }: { blocks: PreviewBlock[] }) {
  return (
    <div className="doc-preview">
      {blocks.map((b, i) => {
        if (b.type === "table") {
          return (
            <table key={i} style={{ margin: "12px 0" }}>
              {b.headers && b.headers.length > 0 && (
                <thead>
                  <tr>
                    {b.headers.map((h, j) => (
                      <th key={j}>{h}</th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {(b.rows || []).map((r, ri) => (
                  <tr key={ri}>
                    {r.map((c, ci) => (
                      <td key={ci}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        if (b.type === "heading") {
          return (
            <div key={i} className="pv-h">
              {b.text}
            </div>
          );
        }
        const isTitle = (b.style || "").toLowerCase().includes("title");
        return (
          <div key={i} className={isTitle ? "pv-title" : "pv-p"}>
            {b.text}
          </div>
        );
      })}
    </div>
  );
}
