import { useState } from "react";
import { EmptyState, ScreenIntro, StatusMark } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { activationTone, connectionTone, formatPercent, formatUtc, humanize } from "../format.js";
import type { DashboardViewModel, GovernedMutationCallback, PromotionDataSource } from "../types.js";

export function AutomationView({
  data,
  dataSource,
  embedded,
  onGovernedMutation
}: {
  data: DashboardViewModel;
  dataSource?: PromotionDataSource;
  embedded: boolean;
  onGovernedMutation?: GovernedMutationCallback;
}) {
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  const cycleCandidate = data.candidates.find((candidate) => candidate.slug === "change-risk-coordinator")
    ?? data.candidates.find((candidate) => candidate.description.includes("autonomous cycle"));
  const cycleEvents = cycleCandidate?.timeline
    .filter((event) => [
      "CANDIDATE_DISCOVERED",
      "EVALUATION_PLANNED",
      "EVALUATION_STARTED",
      "EVALUATION_COMPLETED",
      "ELIGIBILITY_DECIDED",
      "PROMOTION_APPROVED",
      "PROMOTION_REGISTRY_QUEUED",
      "PROMOTED",
      "POST_PROMOTION_MONITORING_OBSERVED"
    ].includes(event.eventType))
    .sort((left, right) => left.sequence - right.sequence);

  async function runCycle() {
    if (!data.demoMode) return;
    if ((!dataSource && !onGovernedMutation) || (embedded && !onGovernedMutation)) return;
    setRunning(true);
    setMessage("");
    try {
      const mutation = {
        resource: "demo-cycle",
        id: "autonomous-cycle",
        idempotencyKey: globalThis.crypto.randomUUID()
      } as const;
      if (embedded) {
        await onGovernedMutation!(mutation);
      } else {
        await dataSource!.mutate(mutation);
      }
      setMessage(governedCopyBody.runtime.demoCycleDispatched);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : governedCopyBody.runtime.demoCycleFailed);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="AUTOMATION / OBSERVED SCHEDULES"
        title="Trigger ownership"
        line1={governedCopyBody.screens.automation.line1}
        line2={governedCopyBody.screens.automation.line2}
        aside={
          <button
            className="pcp-primary-action"
            type="button"
            onClick={runCycle}
            disabled={!data.demoMode || running || (embedded ? !onGovernedMutation : !dataSource)}
          >
            {!data.demoMode
              ? "Demo cycle unavailable"
              : running
              ? "Dispatching cycle…"
              : embedded && !onGovernedMutation
                ? "Attention callback required"
                : governedCopyBody.actions.runCycle.label}
          </button>
        }
      />
      <div className="pcp-schedule-notice">
        <span className="pcp-drafting-cross" aria-hidden="true" />
        <div>
          <strong>This control plane does not execute cron.</strong>
          <p>{data.demoMode
            ? "The demo command, command-line interface, application programming interface, or named external scheduler triggers each job."
            : "A command-line interface, application programming interface, or named external scheduler triggers each job."}</p>
          {data.demoMode ? (
            <p><b>Consequence:</b> {governedCopyBody.actions.runCycle.consequence} <b>Undo:</b> {governedCopyBody.actions.runCycle.undo}</p>
          ) : (
            <p>Demo mutations are disabled in this environment.</p>
          )}
        </div>
      </div>
      {message ? <p className="pcp-action-result" role="status">{message}</p> : null}
      {cycleCandidate ? (
        <section
          className="pcp-cycle-progress"
          aria-labelledby="live-autonomous-cycle"
          aria-live="polite"
        >
          <header>
            <div>
              <p className="pcp-eyebrow">LIVE WORKER EVIDENCE</p>
              <h2 id="live-autonomous-cycle">Live autonomous cycle</h2>
              <p>The autonomous cycle advances this candidate through durable worker events.</p>
              <p>Follow each event below; no page reload is required.</p>
            </div>
            <StatusMark tone={activationTone(cycleCandidate.activationState)}>
              {humanize(cycleCandidate.stage)}
            </StatusMark>
          </header>
          <div className="pcp-cycle-candidate">
            <div>
              <span>Candidate</span>
              <strong>{cycleCandidate.name}</strong>
            </div>
            <div>
              <span>Evaluation evidence</span>
              <strong>{formatPercent(cycleCandidate.evaluation.readinessPercentage)}</strong>
            </div>
            <div>
              <span>Registry activation</span>
              <strong>{humanize(cycleCandidate.activationState)}</strong>
            </div>
          </div>
          <ol>
            {cycleEvents?.map((event) => (
              <li key={event.id}>
                <span>#{event.sequence}</span>
                <strong>{humanize(event.eventType)}</strong>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {data.schedules.length === 0 ? (
        <EmptyState>No observed schedules are configured.</EmptyState>
      ) : (
        <div className="pcp-schedule-grid">
          {data.schedules.map((job, index) => (
            <article key={job.id} data-connection={job.connectionState.toLowerCase()}>
              <header>
                <span className="pcp-card-index">{String(index + 1).padStart(2, "0")}</span>
                <StatusMark tone={connectionTone(job.connectionState)} compact>{humanize(job.connectionState)}</StatusMark>
              </header>
              <p className="pcp-eyebrow">{job.triggerMode}</p>
              <h2>{job.name}</h2>
              <p>{job.description}</p>
              <dl>
                <div><dt>Job type</dt><dd>{humanize(job.jobType)}</dd></div>
                <div><dt>Dispatch state</dt><dd>{job.enabled === null ? "Not reported" : job.enabled ? "Enabled by owner" : "Disabled by owner"}</dd></div>
                <div><dt>Trigger owner</dt><dd>{job.triggerOwner}</dd></div>
                <div><dt>Owner reference</dt><dd>{job.ownerReference}</dd></div>
                <div><dt>Schedule</dt><dd>{job.scheduleExpression} · {job.timezone}</dd></div>
                <div><dt>Last observed run</dt><dd>{formatUtc(job.lastObservedRunAt)}</dd></div>
                <div><dt>Next expected trigger</dt><dd>{job.nextExpectedTriggerAt ? formatUtc(job.nextExpectedTriggerAt) : "No trigger is expected"}</dd></div>
                <div><dt>Grace window</dt><dd>{job.graceWindowMinutes} minutes</dd></div>
                <div><dt>Observed runs</dt><dd>{job.runCount ?? "Not reported"}</dd></div>
                <div><dt>Observed failures</dt><dd>{job.failureCount ?? "Not reported"}</dd></div>
                <div><dt>Current activity</dt><dd>{job.currentActivity ? humanize(job.currentActivity) : "No active run reported"}</dd></div>
                <div><dt>Last duration</dt><dd>{job.lastDurationSeconds === null ? "Not reported" : `${job.lastDurationSeconds.toFixed(1)} seconds`}</dd></div>
              </dl>
              {job.connectionState === "DISCONNECTED" ? (
                <p className="pcp-inline-blocker"><span aria-hidden="true">!</span> {job.connectionMessage}</p>
              ) : (
                <p className="pcp-quiet-state">Last result: {job.lastRunState ? humanize(job.lastRunState) : "Not reported"}</p>
              )}
              {job.recentRuns.length > 0 ? (
                <ol className="pcp-schedule-history" aria-label={`${job.name} recent runs`}>
                  {job.recentRuns.slice(0, 3).map((run) => (
                    <li key={run.id}>
                      <strong>{humanize(run.state)}</strong>
                      <span>{run.triggeredBy} · {formatUtc(run.observedAt)} · attempt {run.attemptCount}</span>
                    </li>
                  ))}
                </ol>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
