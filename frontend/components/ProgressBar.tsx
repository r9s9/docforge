"use client";

export default function ProgressBar({
  percent,
  stage,
  busy,
  indeterminate,
}: {
  percent?: number;
  stage?: string | null;
  busy?: boolean;
  indeterminate?: boolean;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
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
    </div>
  );
}
