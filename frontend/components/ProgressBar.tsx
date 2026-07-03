"use client";

export interface ProgressStep {
  code: string;
  label: string;
}

export default function ProgressBar({
  percent,
  stage,
  busy,
  indeterminate,
  steps,
  currentCode,
}: {
  percent?: number;
  stage?: string | null;
  busy?: boolean;
  indeterminate?: boolean;
  /** Optional phase checklist rendered under the track (✓ done / ⟳ current / · pending). */
  steps?: ProgressStep[];
  currentCode?: string | null;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
  const currentIdx = steps && currentCode ? steps.findIndex((s) => s.code === currentCode) : -1;
  return (
    <div className="progress-card">
      <div className="progress-head">
        <span className="progress-stage">
          {busy && pct < 100 && <span className="spinner" />}
          {stage || "Working…"}
        </span>
        {!indeterminate && <span className="progress-pct">{pct}%</span>}
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${indeterminate ? "indeterminate" : ""}`}
          style={indeterminate ? undefined : { width: `${pct}%` }}
        />
      </div>
      {steps && currentIdx >= 0 && (
        <div className="progress-steps" aria-label="Analysis phases">
          {steps.map((s, i) => {
            const state = i < currentIdx ? "done" : i === currentIdx ? "current" : "todo";
            return (
              <span className={`progress-step ${state}`} key={s.code}>
                <span className="progress-step-mark">
                  {state === "done" ? "✓" : state === "current" ? <span className="spinner" /> : "·"}
                </span>
                {s.label}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
