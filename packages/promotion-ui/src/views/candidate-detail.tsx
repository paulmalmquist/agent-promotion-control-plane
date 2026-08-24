import { useEffect, useId, useRef, useState } from "react";
import {
  DraftLink,
  EmptyState,
  MetricCard,
  ScreenIntro,
  SectionHeading,
  StatusMark,
  TechnicalReference
} from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import {
  activationTone,
  blockerTone,
  formatPercent,
  formatScore,
  formatUtc,
  gateTone,
  humanize
} from "../format.js";
import type {
  CandidateViewModel,
  GovernedMutationCallback,
  LifecycleDecisionRequest,
  LifecycleDecisionResult,
  PromotionDataSource
} from "../types.js";

interface CandidateDetailViewProps {
  candidate: CandidateViewModel | undefined;
  navigate: (path: string) => void;
  dataSource?: PromotionDataSource;
  onLifecycleDecision?: (request: LifecycleDecisionRequest) => Promise<LifecycleDecisionResult>;
  onGovernedMutation?: GovernedMutationCallback;
  evidenceLink: (candidateId: string) => string;
  attentionLink?: string;
  embedded: boolean;
}

const comparisonSymbols: Record<string, string> = {
  eq: "=",
  gte: "≥",
  gt: ">",
  lte: "≤",
  lt: "<"
};

function formatMeasurement(gate: CandidateViewModel["gates"][number]): string {
  if (gate.measurementValue === null) return "Pending";
  const unit = gate.measurementUnit ? ` ${gate.measurementUnit}` : "";
  const contract = gate.threshold === null
    ? ""
    : ` ${comparisonSymbols[gate.comparisonOperator] ?? gate.comparisonOperator} ${gate.threshold}${unit}`;
  return `${gate.measurementValue}${unit}${contract}`;
}

function isSha256(value: string | null): value is string {
  return Boolean(value && /^[a-f\d]{64}$/i.test(value));
}

function detailValue(details: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = details[key];
    if (typeof value === "string" || typeof value === "number") return String(value);
  }
  return null;
}

export function CandidateDetailView({
  candidate,
  navigate,
  dataSource,
  onLifecycleDecision,
  onGovernedMutation,
  evidenceLink,
  attentionLink,
  embedded
}: CandidateDetailViewProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [retryDialogOpen, setRetryDialogOpen] = useState(false);
  const [rationale, setRationale] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<LifecycleDecisionResult | null>(null);
  const rationaleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const submittingRef = useRef(submitting);

  useEffect(() => {
    submittingRef.current = submitting;
  }, [submitting]);

  useEffect(() => {
    if (!dialogOpen && !retryDialogOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    const dismiss = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || submittingRef.current) return;
      setDialogOpen(false);
      setRetryDialogOpen(false);
    };
    document.addEventListener("keydown", dismiss);
    return () => {
      document.removeEventListener("keydown", dismiss);
      previousFocus?.focus();
    };
  }, [dialogOpen, retryDialogOpen]);

  if (!candidate) {
    return (
      <div className="pcp-view">
        <ScreenIntro
          eyebrow="CANDIDATE / NOT FOUND"
          title="Candidate unavailable"
          line1="This candidate record is not present in the current control-plane snapshot."
          line2="Return to the inventory and select an available candidate for review."
        />
        <DraftLink onClick={() => navigate("/candidates")}>Return to candidates</DraftLink>
      </div>
    );
  }

  const isPending = candidate.activationState === "PENDING";
  const activationFailed = candidate.activationState === "FAILED";
  const hasBlocker = Boolean(candidate.blockerCode || candidate.blockerSummary);
  const primaryBlocker = candidate.blockers[0];
  const evidenceArtifacts = candidate.evidence.filter((evidence) => evidence.kind === "ARTIFACT");
  const detectorSignals = candidate.evidence.filter((evidence) => evidence.kind === "DETECTOR_SIGNAL");
  const approvalsSatisfied = candidate.lifecycleApprovalState === "NOT_REQUIRED"
    || candidate.lifecycleApprovalState === "APPROVED";
  const canPromote = candidate.promotionEligible
    && approvalsSatisfied
    && !hasBlocker
    && candidate.activationState === "NOT_REQUESTED";
  const activeCopy = isPending
    ? governedCopyBody.screens.registryPending
    : activationFailed
      ? governedCopyBody.screens.registryFailure
      : hasBlocker
        ? governedCopyBody.screens.blocker
        : governedCopyBody.screens.candidate;

  async function submitDecision() {
    if (!candidate || rationale.trim().length < 20) return;
    setSubmitting(true);
    setResult(null);
    const request: LifecycleDecisionRequest = {
      candidate,
      targetStage: "PROMOTED",
      policyHash: candidate.policyHash,
      evaluationSnapshotHash: candidate.evaluationSnapshotHash,
      rationale: rationale.trim(),
      expectedCandidateRevision: candidate.revision
    };

    try {
      if (onLifecycleDecision) {
        setResult(await onLifecycleDecision(request));
      } else if (dataSource) {
        const response = await dataSource.mutate<{
          operationId?: string;
          operation_id?: string;
          candidateRevision?: number;
          candidate_revision?: number;
        }>({
          resource: "promotion",
          id: candidate.id,
          expectedCandidateRevision: candidate.revision,
          idempotencyKey: globalThis.crypto.randomUUID(),
          body: { actor: "standalone-reviewer", rationale: request.rationale }
        });
        const operationId = response.operationId ?? response.operation_id;
        const candidateRevision = response.candidateRevision ?? response.candidate_revision;
        setResult({
          accepted: true,
          message: governedCopyBody.runtime.lifecycleDecisionQueued,
          ...(operationId ? { operationId } : {}),
          ...(candidateRevision ? { candidateRevision } : {})
        });
      } else {
        setResult({
          accepted: false,
          message: governedCopyBody.runtime.lifecycleDecisionUnavailable
        });
      }
    } catch (error) {
      setResult({
        accepted: false,
        message: error instanceof Error ? error.message : governedCopyBody.runtime.lifecycleDecisionFailed
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function retryRegistry() {
    if (!candidate || (!dataSource && !onGovernedMutation) || (embedded && !onGovernedMutation)) return;
    setSubmitting(true);
    setResult(null);
    try {
      const mutation = {
        resource: "promotion-retry",
        id: candidate.registryOperationId ?? candidate.id,
        expectedCandidateRevision: candidate.revision,
        idempotencyKey: globalThis.crypto.randomUUID(),
        body: { actor: "standalone-reviewer" }
      } as const;
      let governedResult: LifecycleDecisionResult | null = null;
      if (embedded) {
        governedResult = await onGovernedMutation!(mutation);
      } else {
        await dataSource!.mutate(mutation);
      }
      setResult(governedResult ?? {
        accepted: true,
        message: governedCopyBody.runtime.registryRetryQueued
      });
      setRetryDialogOpen(false);
    } catch (error) {
      setResult({ accepted: false, message: error instanceof Error ? error.message : governedCopyBody.runtime.registryRetryFailed });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="pcp-view">
      <div className="pcp-breadcrumbs">
        <button type="button" onClick={() => navigate("/candidates")}>Candidates</button>
        <span aria-hidden="true">/</span>
        <span>{candidate.name}</span>
      </div>
      <ScreenIntro
        eyebrow={`${candidate.component} / ${humanize(candidate.stage).toUpperCase()}`}
        title={candidate.name}
        line1={activeCopy.line1}
        line2={activeCopy.line2}
        aside={
          <div className="pcp-intro-status">
            <StatusMark tone={blockerTone(candidate)}>{humanize(candidate.status)}</StatusMark>
            <span>Revision {candidate.revision}</span>
          </div>
        }
      />

      <section className="pcp-candidate-origin">
        <div>
          <p className="pcp-label">WHY THIS CANDIDATE SURFACED</p>
          <h2>{candidate.surfacedReason}</h2>
          <p>{candidate.description}</p>
        </div>
        <dl>
          <div>
            <dt>Detector lineage</dt>
            <dd>{candidate.detectorLineage}</dd>
          </div>
          <div>
            <dt>Policy</dt>
            <dd>{candidate.policyName}</dd>
          </div>
          <div>
            <dt>Last material change</dt>
            <dd>{formatUtc(candidate.updatedAt)}</dd>
          </div>
        </dl>
      </section>

      <div className="pcp-metric-grid pcp-metric-grid-three">
        <MetricCard
          label="Evaluation readiness"
          value={formatPercent(candidate.evaluation.readinessPercentage)}
          meaning="Evidence completeness only. Approval and activation are separate."
          progress={candidate.evaluation.readinessPercentage}
          tone="comparison"
        />
        <MetricCard
          label="Promotion eligibility"
          value={candidate.promotionEligible ? "Eligible" : "Not eligible"}
          meaning={candidate.promotionEligible
            ? "Evidence and lifecycle requirements permit a decision."
            : "A required gate, sample, result, or approval remains."}
          tone={candidate.promotionEligible ? "neutral" : "degraded"}
        />
        <MetricCard
          label="Registry activation"
          value={humanize(candidate.activationState)}
          meaning={candidate.activationState === "SUCCEEDED"
            ? "The worker published an immutable agent version."
            : candidate.activationState === "PENDING"
              ? "The worker must succeed before promotion completes."
              : candidate.activationState === "FAILED"
                ? "Publication failed. The candidate remains eligible but blocked."
                : "No registry publication request exists."}
          tone={activationTone(candidate.activationState)}
        />
      </div>

      <section className="pcp-section">
        <SectionHeading index="01" title="Lifecycle journey" detail="The current stage has a solid drafting mark." />
        <ol className="pcp-journey">
          {candidate.journey.map((stage, index) => {
            const current = stage === candidate.stage;
            const currentIndex = candidate.journey.indexOf(candidate.stage);
            const complete = currentIndex >= 0 && index < currentIndex;
            return (
              <li key={`${stage}-${index}`} data-current={current || undefined} data-complete={complete || undefined}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{humanize(stage)}</strong>
              </li>
            );
          })}
        </ol>
      </section>

      {hasBlocker ? (
        <section className="pcp-blocker" data-tone={blockerTone(candidate)} aria-labelledby="candidate-blocker">
          <span className="pcp-blocker-mark" aria-hidden="true">!</span>
          <div>
            <p className="pcp-label">REQUIRED ACTION</p>
            <h2 id="candidate-blocker">{primaryBlocker?.title ?? candidate.blockerSummary ?? "A required promotion condition remains unresolved."}</h2>
            <p>{primaryBlocker?.explanation ?? governedCopyBody.screens.blocker.line2}</p>
            {primaryBlocker ? (
              <dl className="pcp-blocker-facts">
                {detailValue(primaryBlocker.details, "current_measurement", "current_value", "observed") ? (
                  <div><dt>Current measurement</dt><dd>{detailValue(primaryBlocker.details, "current_measurement", "current_value", "observed")}</dd></div>
                ) : null}
                {detailValue(primaryBlocker.details, "threshold", "required_threshold", "limit") ? (
                  <div><dt>Required threshold</dt><dd>{detailValue(primaryBlocker.details, "threshold", "required_threshold", "limit")}</dd></div>
                ) : null}
                <div><dt>Recovery action</dt><dd>{primaryBlocker.recovery}</dd></div>
              </dl>
            ) : null}
            {candidate.blockerCode ? <TechnicalReference label="Blocker code" value={candidate.blockerCode} /> : null}
          </div>
        </section>
      ) : null}

      <div className="pcp-detail-columns">
        <section className="pcp-section">
          <SectionHeading
            index="02"
            title="Gate and evidence matrix"
            detail="Incomplete weighted criteria contribute zero. Failed hard gates always block."
          />
          {candidate.gates.length === 0 ? (
            <EmptyState>The policy requires no criteria. Evaluation completeness is 100%.</EmptyState>
          ) : (
            <div className="pcp-table-wrap">
              <table className="pcp-table">
                <thead>
                  <tr>
                    <th scope="col">Criterion</th>
                    <th scope="col">Contract</th>
                    <th scope="col">Verdict</th>
                    <th scope="col">Measurement</th>
                    <th scope="col">Coverage</th>
                    <th scope="col">Evaluator</th>
                  </tr>
                </thead>
                <tbody>
                  {candidate.gates.map((gate) => (
                    <tr key={gate.id}>
                      <th scope="row" data-label="Criterion">
                        <strong>{gate.name}</strong>
                        <span>{humanize(gate.category)} · {gate.meaning}</span>
                      </th>
                      <td data-label="Contract">
                        <strong>{gate.kind === "HARD_GATE" ? "Hard gate" : "Weighted"}</strong>
                        <span>Weight: {gate.kind === "WEIGHTED" && gate.weight !== null ? formatPercent(gate.weight * 100) : "Not applicable"}</span>
                      </td>
                      <td data-label="Verdict"><StatusMark tone={gateTone(gate.verdict)} compact>{humanize(gate.verdict)}</StatusMark></td>
                      <td data-label="Measurement">
                        <strong>{formatMeasurement(gate)}</strong>
                        <span>{gate.normalizedScore === null ? "No normalized score" : `${formatPercent(gate.normalizedScore * 100)} normalized`}</span>
                      </td>
                      <td data-label="Coverage">
                        <span>{gate.samples} of {gate.minimumSamples} samples</span>
                        <span>{gate.evidenceCount} of {gate.requiredEvidenceCount} evidence items</span>
                      </td>
                      <td data-label="Evaluator">
                        <strong>{gate.evaluator}</strong>
                        <span>{gate.lastRunAt ? formatUtc(gate.lastRunAt) : "No completed run"}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="pcp-readiness-breakdown">
            <div><span>Hard gates</span><strong>{formatPercent(candidate.evaluation.hardGateReadiness * 100)}</strong></div>
            <div><span>Weighted score</span><strong>{formatScore(candidate.evaluation.weightedScore)}</strong></div>
            <div><span>Samples</span><strong>{formatPercent(candidate.evaluation.sampleCompleteness * 100)}</strong></div>
            <div><span>Evaluations</span><strong>{formatPercent(candidate.evaluation.evaluationCompleteness * 100)}</strong></div>
          </div>
        </section>

        <aside className="pcp-section pcp-decision-panel">
          <SectionHeading index="03" title="Lifecycle decision" />
          <div className="pcp-cold-read" data-governed-copy="true">
            <p>{governedCopyBody.screens.promotionRationale.line1}</p>
            <p>{governedCopyBody.screens.promotionRationale.line2}</p>
          </div>
          <p className="pcp-authority-notice">{governedCopyBody.authorityNotice}</p>
          <dl className="pcp-decision-facts">
            <div><dt>Evidence snapshot</dt><dd><TechnicalReference label="SHA-256" value={candidate.evaluationSnapshotHash} /></dd></div>
            <div><dt>Policy snapshot</dt><dd><TechnicalReference label="SHA-256" value={candidate.policyHash} /></dd></div>
            <div><dt>Lifecycle approval</dt><dd>{humanize(candidate.lifecycleApprovalState)}</dd></div>
            <div><dt>Approval coverage</dt><dd>{candidate.availableLifecycleApprovals + candidate.consumedLifecycleApprovals} of {candidate.requiredLifecycleApprovals} required</dd></div>
            <div><dt>Consumed approvals</dt><dd>{candidate.consumedLifecycleApprovals}</dd></div>
            <div><dt>Active blockers</dt><dd>{candidate.activeBlockerCount}</dd></div>
          </dl>
          {candidate.latestDecision ? (
            <div className="pcp-recorded-decision">
              <p className="pcp-label">LATEST RECORDED DECISION</p>
              <strong>{humanize(candidate.latestDecision.type)} · {humanize(candidate.latestDecision.outcome)}</strong>
              <p>{candidate.latestDecision.rationale}</p>
              <span>{candidate.latestDecision.actor} · {formatUtc(candidate.latestDecision.decidedAt)}</span>
              <div>
                <TechnicalReference label="Policy" value={candidate.latestDecision.policyHash} />
                <TechnicalReference label="Evidence" value={candidate.latestDecision.evaluationSnapshotHash} />
              </div>
            </div>
          ) : null}
          {embedded && attentionLink ? (
            <a className="pcp-secondary-action" href={attentionLink}>Open Attention decision surface</a>
          ) : null}
          {canPromote && (!embedded || Boolean(onLifecycleDecision)) ? (
            <button className="pcp-primary-action" type="button" onClick={() => setDialogOpen(true)}>
              {governedCopyBody.actions.promote.label}
            </button>
          ) : activationFailed ? (
            <button
              className="pcp-primary-action"
              type="button"
              onClick={() => setRetryDialogOpen(true)}
              disabled={submitting || (embedded ? !onGovernedMutation : !dataSource)}
            >
              {embedded && !onGovernedMutation
                ? "Attention callback required"
                : governedCopyBody.actions.retryRegistry.label}
            </button>
          ) : (
            <button className="pcp-primary-action" type="button" disabled>
              {isPending
                ? "Registry publication pending"
                : embedded && !onLifecycleDecision
                  ? "Attention callback required"
                  : "Promotion unavailable"}
            </button>
          )}
          {result ? <p className="pcp-action-result" role="status" data-accepted={result.accepted}>{result.message}</p> : null}
        </aside>
      </div>

      <section className="pcp-section">
        <SectionHeading
          index="04"
          title="Persisted evidence"
          detail="Every artifact carries its source, recorded time, and immutable digest."
          action={<a className="pcp-draft-link" href={evidenceLink(candidate.id)}><span>Open Evidence</span><span aria-hidden="true">→</span></a>}
        />
        {evidenceArtifacts.length === 0 ? (
          <EmptyState>This candidate has no linked evidence artifacts.</EmptyState>
        ) : (
          <div className="pcp-evidence-grid">
            {evidenceArtifacts.map((evidence, index) => (
              <article key={evidence.id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <p className="pcp-label">{evidence.signalType}</p>
                  <h3>{evidence.title}</h3>
                  <p>{evidence.summary}</p>
                  <small>{evidence.source} · {formatUtc(evidence.recordedAt)}</small>
                  {isSha256(evidence.digest) ? <TechnicalReference label="SHA-256" value={evidence.digest} /> : null}
                  {evidence.uri ? (
                    <div className="pcp-evidence-reference">
                      <TechnicalReference label="URI" value={evidence.uri} />
                      <a className="pcp-evidence-link" href={evidence.uri}>Inspect artifact</a>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="pcp-section">
        <SectionHeading
          index="04B"
          title="Detector signals"
          detail="Signals explain discovery. They are not promoted as evidence artifacts."
        />
        {detectorSignals.length === 0 ? (
          <EmptyState>This candidate has no linked detector signals.</EmptyState>
        ) : (
          <div className="pcp-evidence-grid">
            {detectorSignals.map((evidence, index) => (
              <article key={evidence.id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <p className="pcp-label">{evidence.signalType}</p>
                  <h3>{evidence.title}</h3>
                  <p>{evidence.summary}</p>
                  <small>{evidence.source} · {formatUtc(evidence.recordedAt)}</small>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="pcp-section">
        <SectionHeading index="05" title="Candidate event history" detail="Newest durable event appears first." />
        {candidate.timeline.length === 0 ? (
          <EmptyState>This candidate has no linked events.</EmptyState>
        ) : (
          <ol className="pcp-event-list pcp-event-list-wide">
            {candidate.timeline.map((event) => (
              <li key={event.id}>
                <span className="pcp-event-sequence">#{event.sequence}</span>
                <div>
                  <strong>{event.headline}</strong>
                  <p>{event.detail}</p>
                  <span>{formatUtc(event.occurredAt)} · {event.actor}</span>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {dialogOpen ? (
        <div className="pcp-dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.currentTarget === event.target && !submitting) setDialogOpen(false);
        }}>
          <section ref={dialogRef} tabIndex={-1} className="pcp-dialog" role="dialog" aria-modal="true" aria-labelledby="promotion-dialog-title">
            <p className="pcp-eyebrow">PROMOTION LIFECYCLE APPROVAL</p>
            <h2 id="promotion-dialog-title">Queue {candidate.name} for registry publication</h2>
            <div className="pcp-cold-read" data-governed-copy="true">
              <p>{governedCopyBody.screens.promotionRationale.line1}</p>
              <p>{governedCopyBody.screens.promotionRationale.line2}</p>
            </div>
            <p className="pcp-authority-notice">{governedCopyBody.authorityNotice}</p>
            <label htmlFor={rationaleId}>
              <span>Decision rationale</span>
              <textarea
                id={rationaleId}
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                rows={5}
                placeholder="Explain why this exact tested version should enter the registry."
              />
            </label>
            <p className="pcp-action-consequence">
              <strong>Consequence:</strong> {governedCopyBody.actions.promote.consequence}<br />
              <strong>Undo:</strong> {governedCopyBody.actions.promote.undo}
            </p>
            {result ? <p className="pcp-action-result" role="status" data-accepted={result.accepted}>{result.message}</p> : null}
            <div className="pcp-dialog-actions">
              <button className="pcp-secondary-action" type="button" onClick={() => setDialogOpen(false)} disabled={submitting}>Cancel without changes</button>
              <button className="pcp-primary-action" type="button" onClick={submitDecision} disabled={submitting || rationale.trim().length < 20}>
                {submitting ? "Recording decision…" : governedCopyBody.actions.promote.label}
              </button>
            </div>
          </section>
        </div>
      ) : null}
      {retryDialogOpen ? (
        <div className="pcp-dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.currentTarget === event.target && !submitting) setRetryDialogOpen(false);
        }}>
          <section ref={dialogRef} tabIndex={-1} className="pcp-dialog" role="dialog" aria-modal="true" aria-labelledby="retry-dialog-title">
            <p className="pcp-eyebrow">REGISTRY RECOVERY</p>
            <h2 id="retry-dialog-title">Retry registry publication</h2>
            <div className="pcp-cold-read" data-governed-copy="true">
              <p>{governedCopyBody.screens.registryFailure.line1}</p>
              <p>{governedCopyBody.screens.registryFailure.line2}</p>
            </div>
            <p className="pcp-action-consequence">
              <strong>Consequence:</strong> {governedCopyBody.actions.retryRegistry.consequence}<br />
              <strong>Undo:</strong> {governedCopyBody.actions.retryRegistry.undo}
            </p>
            <div className="pcp-dialog-actions">
              <button className="pcp-secondary-action" type="button" onClick={() => setRetryDialogOpen(false)} disabled={submitting}>Cancel without changes</button>
              <button className="pcp-primary-action" type="button" onClick={retryRegistry} disabled={submitting}>
                {submitting ? "Queuing retry…" : "Confirm registry retry"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
