"use client";

import type { FieldDefinition } from "@/lib/types";
import { ClassificationBadge } from "@/components/ui";

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
  return (
    <div className="field-cards">
      {items.map((ef, i) => {
        const f = ef.field;
        const conf = confidenceLabel(f.confidence);
        return (
          <div
            key={i}
            id={`fieldrow-${f.field_name}`}
            className={`field-card ${ef.include ? "" : "excluded"} ${
              f.field_name === selected ? "selected" : ""
            }`}
          >
            <div className="field-card-head">
              <label className="field-card-toggle" title="Include this as a fillable field">
                <input
                  type="checkbox"
                  checked={ef.include}
                  onChange={() => onToggle(i)}
                />
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
          </div>
        );
      })}
    </div>
  );
}
