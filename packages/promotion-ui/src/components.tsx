import type { ReactNode } from "react";
import { formatPercent, humanize, type VisualTone } from "./format.js";

export function ScreenIntro({
  eyebrow,
  title,
  line1,
  line2,
  aside
}: {
  eyebrow: string;
  title: string;
  line1: string;
  line2: string;
  aside?: ReactNode;
}) {
  return (
    <header className="pcp-screen-intro">
      <div>
        <p className="pcp-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <div className="pcp-cold-read" data-governed-copy="true">
          <p>{line1}</p>
          <p>{line2}</p>
        </div>
      </div>
      {aside ? <div className="pcp-intro-aside">{aside}</div> : null}
    </header>
  );
}

export function StatusMark({
  tone = "neutral",
  children,
  compact = false
}: {
  tone?: VisualTone;
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <span className="pcp-status-mark" data-tone={tone} data-compact={compact || undefined}>
      <span className="pcp-status-shape" aria-hidden="true" />
      <span>{children}</span>
    </span>
  );
}

export function MetricCard({
  label,
  value,
  meaning,
  tone = "neutral",
  progress
}: {
  label: string;
  value: string;
  meaning: string;
  tone?: VisualTone;
  progress?: number;
}) {
  return (
    <article className="pcp-metric-card" data-tone={tone}>
      <p className="pcp-label">{label}</p>
      <strong>{value}</strong>
      {progress === undefined ? null : (
        <div
          className="pcp-progress"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress)}
        >
          <span style={{ inlineSize: formatPercent(Math.max(0, Math.min(100, progress))) }} />
        </div>
      )}
      <p>{meaning}</p>
    </article>
  );
}

export function SectionHeading({
  index,
  title,
  detail,
  action
}: {
  index: string;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="pcp-section-heading">
      <div className="pcp-section-title">
        <span>{index}</span>
        <div>
          <h2>{title}</h2>
          {detail ? <p>{detail}</p> : null}
        </div>
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="pcp-empty">
      <span aria-hidden="true">—</span>
      <p>{children}</p>
    </div>
  );
}

export function DraftLink({
  children,
  onClick,
  ariaLabel
}: {
  children: ReactNode;
  onClick: () => void;
  ariaLabel?: string;
}) {
  return (
    <button className="pcp-draft-link" type="button" onClick={onClick} aria-label={ariaLabel}>
      <span>{children}</span>
      <span aria-hidden="true">→</span>
    </button>
  );
}

export function TechnicalReference({ label, value }: { label: string; value: string }) {
  return (
    <span className="pcp-technical-ref" title={value}>
      {label}: {value.slice(0, 10)}
    </span>
  );
}

export function GateLabel({ value }: { value: string }) {
  return <span className="pcp-gate-label">{humanize(value)}</span>;
}
