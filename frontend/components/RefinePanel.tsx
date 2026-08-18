"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { FieldDefinition, RefineMessage, RefineResult } from "@/lib/types";
import { MessageSquare, RotateCw, Sparkles, X } from "@/components/icons";
import { ErrorBox, Spinner, TokenUsageLine } from "@/components/ui";

/**
 * Refine the draft by asking for changes in words.
 *
 * The conversation lives here rather than on the server: each turn sends the
 * transcript and the current values, and gets back a patch of only what
 * changed. That keeps the user in control — nothing is applied that they can't
 * see listed and undo — and means a turn can be retried or abandoned freely.
 */
export default function RefinePanel({
  templateId,
  version,
  fields,
  values,
  sourceContext,
  onApply,
  onUndo,
  canUndo,
  onJumpToField,
  onClose,
}: {
  templateId: string;
  version?: number;
  fields: FieldDefinition[];
  values: Record<string, any>;
  sourceContext?: string;
  onApply: (result: RefineResult) => void;
  onUndo: () => void;
  canUndo: boolean;
  onJumpToField: (name: string) => void;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<RefineMessage[]>([]);
  const [changes, setChanges] = useState<Record<number, string[]>>({});
  const [usage, setUsage] = useState<RefineResult["token_usage"]>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const labelFor = (name: string) =>
    fields.find((f) => f.field_name === name)?.label || name;

  async function send(e: FormEvent) {
    e.preventDefault();
    const ask = input.trim();
    if (!ask || busy) return;
    const history: RefineMessage[] = [...messages, { role: "user", content: ask }];
    setMessages(history);
    setInput("");
    setError("");
    setBusy(true);
    try {
      const result = await api.refine(templateId, {
        version,
        messages: history,
        current_values: values,
        source_context: sourceContext || null,
      });
      const changed = [...result.updates.map((u) => u.field_name), ...result.removed];
      setMessages([
        ...history,
        { role: "assistant", content: result.reply || "Done." },
      ]);
      setChanges((prev) => ({ ...prev, [history.length]: changed }));
      setUsage(result.token_usage ?? null);
      if (changed.length) onApply(result);
    } catch (err: any) {
      setError(String(err?.message || err));
      setMessages(history);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="refine-panel">
      <div className="refine-head">
        <h2 className="section-h" style={{ margin: 0 }}>
          <MessageSquare size={15} strokeWidth={2} /> Refine
        </h2>
        <div className="row" style={{ gap: 6 }}>
          {canUndo && (
            <button className="btn secondary small" onClick={onUndo} title="Undo the last applied change">
              <RotateCw size={13} strokeWidth={2} /> Undo
            </button>
          )}
          <button className="btn secondary small icon" onClick={onClose} title="Close Refine">
            <X size={14} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="refine-log">
        {messages.length === 0 && !busy ? (
          <div className="refine-empty">
            <p>Ask for changes in your own words. For example:</p>
            <ul>
              <li>&ldquo;Shorten the summary to two sentences.&rdquo;</li>
              <li>&ldquo;Make the tone more formal.&rdquo;</li>
              <li>&ldquo;Move the vendor risk into scope.&rdquo;</li>
            </ul>
            <p className="muted">
              Each change is listed so you can see what moved, and undone with one click.
            </p>
          </div>
        ) : null}

        {messages.map((m, i) => (
          <div key={i} className={`refine-msg ${m.role}`}>
            <div className="refine-bubble">{m.content}</div>
            {changes[i]?.length ? (
              <div className="refine-changed">
                {changes[i].map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="chip refine-chip"
                    onClick={() => onJumpToField(name)}
                    title="Show this field"
                  >
                    <Sparkles size={10} strokeWidth={2} /> {labelFor(name)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ))}

        {busy && (
          <div className="refine-msg assistant">
            <div className="refine-bubble">
              <Spinner label="Thinking…" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <ErrorBox message={error} />}
      {usage ? (
        <div className="refine-usage">
          <TokenUsageLine usage={usage} />
        </div>
      ) : null}

      <form className="refine-input" onSubmit={send}>
        <textarea
          rows={2}
          value={input}
          placeholder="What should change?"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(e as unknown as FormEvent);
            }
          }}
        />
        <button className="btn" type="submit" disabled={busy || !input.trim()}>
          {busy ? <Spinner /> : "Send"}
        </button>
      </form>
      <p className="refine-hint muted">Enter to send · Shift+Enter for a new line</p>
    </div>
  );
}
