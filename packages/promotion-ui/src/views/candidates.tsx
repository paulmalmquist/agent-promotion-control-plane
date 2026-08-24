import { useMemo, useState } from "react";
import { DraftLink, EmptyState, ScreenIntro, StatusMark } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { activationTone, blockerTone, formatUtc, humanize } from "../format.js";
import { candidateRoute } from "../routes.js";
import type { DashboardViewModel } from "../types.js";

function nextAction(candidate: DashboardViewModel["candidates"][number]): string {
  if (candidate.status === "BLOCKED") return "Resolve the blocker, then rerun the active requirement.";
  if (candidate.activationState === "PENDING") return "Wait for the registry worker to complete publication.";
  if (candidate.promotionEligible && candidate.activationState === "NOT_REQUESTED") {
    return "Record the promotion lifecycle decision.";
  }
  if (candidate.stage === "EVALUATING") return "Complete the active evaluation plan.";
  if (candidate.activationState === "SUCCEEDED") return "Review monitoring evidence for the active version.";
  return "Inspect evidence and continue the lifecycle.";
}

export function CandidatesView({
  data,
  navigate
}: {
  data: DashboardViewModel;
  navigate: (path: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("ALL");
  const [source, setSource] = useState("ALL");
  const [disposition, setDisposition] = useState("ALL");
  const stages = useMemo(
    () => [...new Set(data.candidates.map((candidate) => candidate.stage))].sort(),
    [data.candidates]
  );
  const candidateTypes = useMemo(
    () => [...new Set(data.candidates.map((candidate) => candidate.candidateType))].sort(),
    [data.candidates]
  );
  const detectors = useMemo(
    () => [...new Set(data.candidates.map((candidate) => candidate.detectorLineage))].sort(),
    [data.candidates]
  );

  const candidates = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return data.candidates.filter((candidate) => {
      const matchesQuery =
        !normalized ||
        candidate.name.toLowerCase().includes(normalized) ||
        candidate.component.toLowerCase().includes(normalized) ||
        candidate.candidateType.toLowerCase().includes(normalized) ||
        candidate.detectorLineage.toLowerCase().includes(normalized) ||
        candidate.surfacedReason.toLowerCase().includes(normalized);
      const matchesSource = source === "ALL"
        || (source.startsWith("TYPE:") && candidate.candidateType === source.slice(5))
        || (source.startsWith("DETECTOR:") && candidate.detectorLineage === source.slice(9));
      const matchesDisposition = disposition === "ALL"
        || (disposition === "BLOCKED" && candidate.status === "BLOCKED")
        || (disposition === "PROMOTION_READY" && candidate.promotionEligible && candidate.activationState === "NOT_REQUESTED")
        || (disposition === "PROMOTION_PENDING" && candidate.activationState === "PENDING");
      return matchesQuery
        && (stage === "ALL" || candidate.stage === stage)
        && matchesSource
        && matchesDisposition;
    });
  }, [data.candidates, disposition, query, source, stage]);

  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="CANDIDATES / GOVERNED QUEUE"
        title="Candidate inventory"
        line1={governedCopyBody.screens.candidates.line1}
        line2={governedCopyBody.screens.candidates.line2}
      />

      <div className="pcp-filter-bar" role="search">
        <label>
          <span>Search candidates</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Name, component, or reason"
          />
        </label>
        <label>
          <span>Lifecycle stage</span>
          <select value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="ALL">All stages</option>
            {stages.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </select>
        </label>
        <label>
          <span>Candidate type or detector</span>
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="ALL">All sources</option>
            <optgroup label="Candidate types">
              {candidateTypes.map((value) => <option key={value} value={`TYPE:${value}`}>{humanize(value)}</option>)}
            </optgroup>
            <optgroup label="Detectors">
              {detectors.map((value) => <option key={value} value={`DETECTOR:${value}`}>{value}</option>)}
            </optgroup>
          </select>
        </label>
        <label>
          <span>Review state</span>
          <select value={disposition} onChange={(event) => setDisposition(event.target.value)}>
            <option value="ALL">All review states</option>
            <option value="BLOCKED">Blocked</option>
            <option value="PROMOTION_READY">Promotion ready</option>
            <option value="PROMOTION_PENDING">Registry pending</option>
          </select>
        </label>
        <div className="pcp-filter-count" aria-live="polite">
          <strong>{candidates.length}</strong>
          <span>of {data.candidates.length} shown</span>
        </div>
      </div>

      {candidates.length === 0 ? (
        <EmptyState>No candidates match the current filters.</EmptyState>
      ) : (
        <div className="pcp-candidate-grid">
          {candidates.map((candidate, index) => (
            <article className="pcp-candidate-card" key={candidate.id}>
              <div className="pcp-card-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="pcp-card-head">
                <span className="pcp-component-code">{humanize(candidate.candidateType)} · {candidate.discoverySource}</span>
                <StatusMark tone={blockerTone(candidate)} compact>
                  {humanize(candidate.status)}
                </StatusMark>
              </div>
              <h2>{candidate.name}</h2>
              <p>{candidate.surfacedReason}</p>
              <dl className="pcp-card-data">
                <div>
                  <dt>Lifecycle stage</dt>
                  <dd>{humanize(candidate.stage)}</dd>
                </div>
                <div>
                  <dt>Hard gates</dt>
                  <dd>{candidate.hardGatesPassed === null || candidate.hardGatesRequired === null
                    ? "Awaiting gate summary"
                    : `${candidate.hardGatesPassed} of ${candidate.hardGatesRequired} passed`}</dd>
                </div>
                <div>
                  <dt>Weighted score</dt>
                  <dd>{candidate.evaluation.weightedScore === null ? "Not required" : `${candidate.evaluation.weightedScore.toFixed(1)} of 100`}</dd>
                </div>
                <div>
                  <dt>Latest evaluation</dt>
                  <dd>{candidate.latestEvaluationAt ? formatUtc(candidate.latestEvaluationAt) : "No completed evaluation"}</dd>
                </div>
                <div>
                  <dt>Registry activation</dt>
                  <dd><StatusMark tone={activationTone(candidate.activationState)} compact>{humanize(candidate.activationState)}</StatusMark></dd>
                </div>
              </dl>
              {candidate.blockerSummary ? (
                <p className="pcp-inline-blocker" data-tone={blockerTone(candidate)}>
                  <span aria-hidden="true">!</span> {candidate.blockerSummary}
                </p>
              ) : null}
              <p className="pcp-next-action"><strong>Next action:</strong> {nextAction(candidate)}</p>
              <DraftLink
                onClick={() => navigate(candidateRoute(candidate.id))}
                ariaLabel={`Inspect ${candidate.name}`}
              >
                Inspect evidence
              </DraftLink>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
