import { DraftLink, EmptyState, ScreenIntro, SectionHeading, StatusMark, TechnicalReference } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { formatPercent, formatUtc, gateTone, humanize } from "../format.js";
import { evaluationRoute } from "../routes.js";
import type { DashboardViewModel, EvaluationRunViewModel } from "../types.js";

function runTone(state: EvaluationRunViewModel["state"]) {
  if (state === "FAILED") return "degraded" as const;
  if (state === "RUNNING" || state === "QUEUED") return "comparison" as const;
  return "neutral" as const;
}

function formatDuration(value: number | null): string {
  if (value === null) return "Not observed";
  if (value < 1000) return `${value} milliseconds`;
  return `${(value / 1000).toFixed(1)} seconds`;
}

const comparisonSymbols: Record<string, string> = {
  eq: "=", equals: "=", gt: ">", gte: "≥", lt: "<", lte: "≤"
};

export function EvaluationsView({ data, navigate }: { data: DashboardViewModel; navigate: (path: string) => void }) {
  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="EVALUATIONS / MEASUREMENTS"
        title="Evaluation runs"
        line1={governedCopyBody.screens.evaluations.line1}
        line2={governedCopyBody.screens.evaluations.line2}
      />
      {data.evaluations.length === 0 ? (
        <EmptyState>No evaluation runs are present in this snapshot.</EmptyState>
      ) : (
        <div className="pcp-run-list">
          <div className="pcp-run-list-head" aria-hidden="true">
            <span>Run</span><span>Candidate</span><span>Provider</span><span>Progress</span><span>Timing</span><span />
          </div>
          {data.evaluations.map((run) => (
            <article key={run.id}>
              <div>
                <StatusMark tone={runTone(run.state)} compact>{humanize(run.state)}</StatusMark>
                <strong>{run.planName}</strong>
              </div>
              <div><span className="pcp-mobile-label">Candidate</span><strong>{run.candidateName}</strong></div>
              <div><span className="pcp-mobile-label">Provider</span><span>{run.provider}</span></div>
              <div className="pcp-run-progress">
                <span>{formatPercent(run.progressPercentage)}</span>
                <div className="pcp-progress" role="progressbar" aria-label={`${run.candidateName} evaluation progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(run.progressPercentage)}>
                  <i style={{ inlineSize: formatPercent(run.progressPercentage) }} />
                </div>
                <small>{run.resultCount ?? "Not reported"} results · {run.sampleCount ?? "Not reported"} samples</small>
              </div>
              <div>
                <span className="pcp-mobile-label">Timing</span>
                <span>{run.finishedAt ? `Finished ${formatUtc(run.finishedAt)}` : run.startedAt ? `Started ${formatUtc(run.startedAt)}` : "Awaiting worker lease"}</span>
              </div>
              <DraftLink onClick={() => navigate(evaluationRoute(run.id))} ariaLabel={`Inspect ${run.planName}`}>Inspect</DraftLink>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export function EvaluationDetailView({ run, navigate }: { run: EvaluationRunViewModel | undefined; navigate: (path: string) => void }) {
  if (!run) {
    return (
      <div className="pcp-view">
        <ScreenIntro
          eyebrow="EVALUATION / NOT FOUND"
          title="Evaluation unavailable"
          line1="This evaluation run is not present in the current control-plane snapshot."
          line2="Return to the run list and select an available evaluation for review."
        />
        <DraftLink onClick={() => navigate("/evaluations")}>Return to evaluations</DraftLink>
      </div>
    );
  }
  return (
    <div className="pcp-view">
      <div className="pcp-breadcrumbs">
        <button type="button" onClick={() => navigate("/evaluations")}>Evaluations</button>
        <span aria-hidden="true">/</span><span>{run.planName}</span>
      </div>
      <ScreenIntro
        eyebrow={`EVALUATION / ${humanize(run.state).toUpperCase()}`}
        title={run.planName}
        line1="This run records typed measurements from one immutable evaluation plan."
        line2="Review provider output and sample coverage before interpreting the central gate verdict."
        aside={<StatusMark tone={runTone(run.state)}>{humanize(run.state)}</StatusMark>}
      />
      <div className="pcp-metric-grid pcp-metric-grid-three">
        <article className="pcp-metric-card"><p className="pcp-label">CANDIDATE</p><strong>{run.candidateName}</strong><p>The candidate bound to this immutable run.</p></article>
        <article className="pcp-metric-card"><p className="pcp-label">MEASUREMENTS</p><strong>{run.resultCount ?? "Not reported"}</strong><p>Typed results available to the central gate engine.</p></article>
        <article className="pcp-metric-card"><p className="pcp-label">SAMPLES</p><strong>{run.sampleCount ?? "Not reported"}</strong><p>Samples aggregated by each criterion's declared rule.</p></article>
      </div>
      <section className="pcp-section pcp-run-sheet">
        <div><span>Plan reference</span>{run.planId ? <TechnicalReference label="Plan" value={run.planId} /> : <strong>Not reported</strong>}</div>
        <div><span>Provider</span><strong>{run.provider}</strong></div>
        <div><span>Model</span><strong>{run.model ?? "Not used"}</strong></div>
        <div><span>Progress</span><strong>{formatPercent(run.progressPercentage)}</strong></div>
        <div><span>Started</span><strong>{formatUtc(run.startedAt)}</strong></div>
        <div><span>Finished</span><strong>{formatUtc(run.finishedAt)}</strong></div>
        <div><span>Duration</span><strong>{formatDuration(run.durationMilliseconds)}</strong></div>
        <div><span>Provider latency</span><strong>{formatDuration(run.latencyMilliseconds)}</strong></div>
        <div><span>Cost</span><strong>{run.costUsd === null ? "Not reported" : `$${run.costUsd.toFixed(4)}`}</strong></div>
        <div><span>Attempt</span><strong>{run.attemptCount} of {run.maxAttempts}</strong></div>
        <div><span>Planned criteria</span><strong>{run.plannedResultCount}</strong></div>
        <div><span>Last heartbeat</span><strong>{formatUtc(run.heartbeatAt)}</strong></div>
        <div><span>Correlation</span>{run.correlationId ? <TechnicalReference label="Correlation" value={run.correlationId} /> : <strong>Not reported</strong>}</div>
      </section>
      {run.errorMessage ? <p className="pcp-inline-blocker"><span aria-hidden="true">!</span> {run.errorMessage}</p> : null}
      <section className="pcp-section">
        <SectionHeading index="01" title="Typed measurements" detail="The central gate engine assigns every threshold verdict." />
        {run.results.length === 0 ? (
          <EmptyState>No typed measurements are available for this run.</EmptyState>
        ) : (
          <div className="pcp-table-wrap">
            <table className="pcp-table">
              <thead><tr><th>Criterion</th><th>Measurement</th><th>Provider</th><th>Normalized score</th><th>Verdict</th><th>Coverage</th></tr></thead>
              <tbody>
                {run.results.map((result) => (
                  <tr key={result.id}>
                    <th scope="row" data-label="Criterion"><strong>{result.name}</strong><span>{humanize(result.category)} · {result.evaluator}</span></th>
                    <td data-label="Measurement"><strong>{result.measurementValue ?? "Pending"}{result.measurementUnit ? ` ${result.measurementUnit}` : ""}</strong><span>{comparisonSymbols[result.comparisonOperator] ?? result.comparisonOperator} {result.threshold ?? "No threshold"}{result.measurementUnit ? ` ${result.measurementUnit}` : ""}</span></td>
                    <td data-label="Provider">
                      <strong>{result.provider ?? "Not reported"}</strong>
                      <span>{result.model ?? "No model"}</span>
                      <span>{formatDuration(result.latencyMilliseconds)} · {result.costUsd === null ? "Cost not reported" : `$${result.costUsd.toFixed(4)}`}</span>
                    </td>
                    <td data-label="Normalized score">{result.normalizedScore === null ? "Not reported" : formatPercent(result.normalizedScore * 100)}</td>
                    <td data-label="Verdict"><StatusMark tone={gateTone(result.verdict)} compact>{humanize(result.verdict)}</StatusMark></td>
                    <td data-label="Coverage"><span>{result.samples} samples</span><span>{result.evidenceCount} evidence items</span><span>{result.valid === null ? "Validity not reported" : result.valid ? "Valid result" : "Invalid result"}{result.stale ? " · Stale" : ""}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="pcp-section">
        <SectionHeading index="02" title="Evidence and logs" detail="Persisted outputs keep provider responses inspectable." />
        {run.artifacts.length === 0 ? (
          <EmptyState>No evidence artifact or log reference is linked to this run.</EmptyState>
        ) : (
          <div className="pcp-evidence-grid">
            {run.artifacts.map((artifact, index) => (
              <article key={artifact.id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <p className="pcp-label">{artifact.signalType}</p>
                  <h3>{artifact.title}</h3>
                  <p>{artifact.summary}</p>
                  <small>{artifact.source} · {formatUtc(artifact.recordedAt)}</small>
                  {artifact.digest && /^[a-f\d]{64}$/i.test(artifact.digest) ? <TechnicalReference label="SHA-256" value={artifact.digest} /> : null}
                  {artifact.uri ? (
                    <div className="pcp-evidence-reference">
                      <TechnicalReference label="URI" value={artifact.uri} />
                      <a className="pcp-evidence-link" href={artifact.uri}>Inspect output</a>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
