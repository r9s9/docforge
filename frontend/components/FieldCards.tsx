"use client";

import { useEffect, useState } from "react";
import type { FieldDefinition } from "@/lib/types";
import { ClassificationBadge } from "@/components/ui";
import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown } from "@/components/icons";

export const FIELD_TYPES = [
  "text",
  "multiline_text",
  "date",
  "person",
  "number",
  "enum",
  "table",
  "boolean",
];

// Remember the user's preferred density across visits.
const EXPAND_KEY = "docforge-fieldcards-expanded";

export interface EditableField {
  field: FieldDefinition;
  include: boolean;
}

/** Type-based help: what this kind of field is and how the user fills it.
 * (Intentionally ignores the editable `description` — that's shown separately.) */
function describeField(f: FieldDefinition): string {
  const cls = f.classification || "";
  if (f.field_type === "table" || cls === "REPEATABLE_TABLE") {
    const cols = f.columns?.map((c) => c.label || c.field_name).join(", ");
    return `A repeating table — one row per entry${
      cols ? ` (columns: ${cols})` : ""
    }. Add as many rows as you need when generating.`;
  }
  if (cls === "REPEATABLE_SECTION") {
    return "A section that can repeat — provide one entry per occurrence when generating.";
  }
  if (f.field_type === "boolean") {
    return "An optional section — include it or leave it out for each document.";
  }
  switch (f.field_type) {
    case "date":
      return "A date that changes in each document — fill it in when generating.";
    case "person":
      return "A person’s name that varies per document.";
    case "number":
      return "A number that varies per document.";
    case "enum":
      return f.enum_values?.length
        ? `Pick one of: ${f.enum_values.join(", ")}.`
        : "A value chosen from a fixed set of options.";
    case "multiline_text":
      return "A longer block of text that changes per document.";
    default:
      return "Short text that changes in each document — fill it in when generating.";
  }
}

function confidenceLabel(v: number): { text: string; cls: string } {
  const pct = Math.round((v || 0) * 100);
  if (v >= 0.8) return { text: `AI ${pct}% confident · High`, cls: "high" };
  if (v >= 0.5) return { text: `AI ${pct}% confident · Medium`, cls: "med" };
  return { text: `AI ${pct}% confident · Low — please check`, cls: "low" };
}

export default function FieldCards({
  items,
  onUpdate,
  onToggle,
  onJump,
  selected,
}: {
  items: EditableField[];
  onUpdate: (i: number, patch: Partial<FieldDefinition>) => void;
  onToggle: (i: number) => void;
  onJump?: (fieldName: string) => void;
  selected: string | null;
}) {
  // Which cards are expanded. Compact (collapsed) is the default so the whole
  // list is scannable; the chevron on each card opens just that one.
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    // Restore the saved density preference once on mount.
    try {
      if (localStorage.getItem(EXPAND_KEY) === "1") {
        setExpanded(new Set(items.map((_, i) => i)));
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-open the card the user jumped to from the preview, so its detail shows.
  useEffect(() => {
    if (!selected) return;
    const idx = items.findIndex((ef) => ef.field.field_name === selected);
    if (idx >= 0) setExpanded((prev) => (prev.has(idx) ? prev : new Set(prev).add(idx)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const allExpanded = items.length > 0 && expanded.size >= items.length;

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  function setAll(on: boolean) {
    setExpanded(on ? new Set(items.map((_, i) => i)) : new Set());
    try {
      localStorage.setItem(EXPAND_KEY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="field-cards">
      <div className="field-cards-toolbar">
        <span className="fc-density-hint">
          Compact list — click a card’s arrow to see more or less.
        </span>
        <button
          type="button"
          className="fc-expand-all"
          onClick={() => setAll(!allExpanded)}
          title={allExpanded ? "Collapse every card" : "Expand every card"}
        >
          {allExpanded ? (
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

      {items.map((ef, i) => {
        const f = ef.field;
        const conf = confidenceLabel(f.confidence);
        const open = expanded.has(i);
        return (
          <div
            key={i}
            id={`fieldrow-${f.field_name}`}
            className={`field-card ${open ? "" : "compact"} ${ef.include ? "" : "excluded"} ${
              f.field_name === selected ? "selected" : ""
            }`}
          >
            <div className="field-card-head">
              <button
                type="button"
                className="field-card-chevron"
                aria-expanded={open}
                onClick={() => toggle(i)}
                title={open ? "Show less" : "Show more"}
              >
                {open ? (
                  <ChevronDown size={16} strokeWidth={2.2} />
                ) : (
                  <ChevronRight size={16} strokeWidth={2.2} />
                )}
              </button>
              <label className="field-card-toggle" title="Include this as a fillable field">
                <input type="checkbox" checked={ef.include} onChange={() => onToggle(i)} />
                <input
                  className="mono field-card-name"
                  value={f.field_name}
                  onChange={(e) => onUpdate(i, { field_name: e.target.value })}
                  disabled={!ef.include}
                />
              </label>
              <div className="field-card-actions">
                {onJump && ef.include && (
                  <button
                    type="button"
                    className="fc-jump"
                    title="Find this field in the document preview"
                    onClick={() => onJump(f.field_name)}
                  >
                    ⌖ Find
                  </button>
                )}
                <ClassificationBadge value={f.classification} />
              </div>
            </div>

            {open ? (
              <>
                <p className="field-card-desc">{describeField(f)}</p>

                <label className="fc-desc-edit">
                  <span>
                    Description{" "}
                    <span className="fc-desc-hint">— guides the AI when generating from notes</span>
                  </span>
                  <textarea
                    value={f.description || ""}
                    onChange={(e) => onUpdate(i, { description: e.target.value })}
                    disabled={!ef.include}
                    rows={2}
                    placeholder="e.g. Client's full legal entity name, as registered. Used on the cover page."
                  />
                </label>

                <div className="field-card-controls">
                  <label className="fc-ctl">
                    <span>Label</span>
                    <input
                      value={f.label}
                      onChange={(e) => onUpdate(i, { label: e.target.value })}
                      disabled={!ef.include}
                    />
                  </label>
                  <label className="fc-ctl">
                    <span>Type</span>
                    <select
                      value={f.field_type}
                      onChange={(e) => onUpdate(i, { field_type: e.target.value })}
                      disabled={!ef.include}
                    >
                      {FIELD_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="fc-ctl fc-req">
                    <span>Required</span>
                    <input
                      type="checkbox"
                      checked={f.required}
                      onChange={(e) => onUpdate(i, { required: e.target.checked })}
                      disabled={!ef.include}
                    />
                  </label>
                </div>

                <div className={`field-card-conf ${conf.cls}`}>{conf.text}</div>
              </>
            ) : (
              <button
                type="button"
                className="field-card-summary"
                onClick={() => toggle(i)}
                title="Show more"
              >
                <span className="fc-sum-label">{f.label || f.field_name}</span>
                <span className="fc-sum-sep">·</span>
                <span className="fc-sum-type">{f.field_type.replace(/_/g, " ")}</span>
                {f.required && <span className="fc-sum-req">· required</span>}
                <span className={`fc-dot ${conf.cls}`} title={conf.text} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
