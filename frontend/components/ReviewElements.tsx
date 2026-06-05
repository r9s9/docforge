"use client";

import type { ReviewElement } from "@/lib/types";

function colorFor(cls: string): string {
  if (cls.startsWith("REPEATABLE")) return "var(--green)";
  if (cls.startsWith("DYNAMIC")) return "var(--accent)";
  if (cls === "AUTO_FIELD") return "var(--amber)";
  return "var(--border-strong)";
}

export default function ReviewElements({
  elements,
  selected,
  onSelect,
}: {
  elements: ReviewElement[];
  selected: string | null;
  onSelect: (field: string) => void;
}) {
  return (
    <div className="doc-preview" style={{ maxHeight: 580, overflow: "auto", padding: "24px 28px" }}>
      {elements.map((el) => {
        const isDynamic = el.classification.startsWith("DYNAMIC");
        const isRepeat = el.classification.startsWith("REPEATABLE");
        const clickable = !!el.field_name && (isDynamic || isRepeat);
        const active = clickable && el.field_name === selected;
        const color = colorFor(el.classification);

        const body = isRepeat ? (
          <span>
            <span className="muted">▦ repeatable: </span>
            <span className="placeholder">{el.field_name}</span>
            {el.headers && el.headers.length > 0 && (
              <span className="muted"> [{el.headers.join(", ")}]</span>
            )}
          </span>
        ) : isDynamic ? (
          <span>
            {el.static_prefix && <span>{el.static_prefix}</span>}
            <span className="placeholder">{`{{ ${el.field_name} }}`}</span>
          </span>
        ) : (
          <span className={el.type === "heading" ? "pv-h" : "muted"} style={{ margin: 0 }}>
            {el.text || "·"}
          </span>
        );

        return (
          <div
            key={el.node_id}
            onClick={clickable ? () => onSelect(el.field_name as string) : undefined}
            style={{
              borderLeft: `3px solid ${active ? "var(--accent-press)" : color}`,
              background: active ? "var(--accent-soft)" : "transparent",
              padding: "4px 10px",
              margin: "2px 0",
              borderRadius: 6,
              cursor: clickable ? "pointer" : "default",
            }}
            title={clickable ? `Edit field "${el.field_name}"` : el.classification.toLowerCase()}
          >
            {body}
            {el.optional && (
              <span className="badge auto" style={{ marginLeft: 8, fontSize: 10 }}>
                optional
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
