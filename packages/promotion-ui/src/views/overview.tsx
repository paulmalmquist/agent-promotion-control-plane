import { governedCopyBody } from "../governed-copy.js";
import { activationTone, blockerTone, connectionTone, formatPercent, formatUtc, humanize } from "../format.js";
import { DraftLink, EmptyState, MetricCard, ScreenIntro, SectionHeading, StatusMark } from "../components.js";
import { candidateRoute } from "../routes.js";
import type { DashboardViewModel, LifecycleStage } from "../types.js";

const lifecycleStages: LifecycleStage[] = [
  "DISCOVERED",
  "CANDIDATE",
  "EVALUATING",
  "ELIGIBLE",
  "SHADOW",
  "PROMOTED",
  "MONITORED"
];

export function OverviewView({
  data,
  navigate
}: {
  data: DashboardViewModel;
  navigate: (path: string) => void;
}) {
  const blocked = data.candidates.filter((candidate) => candidate.status === "BLOCKED").length;
  const awaitingDecision = data.candidates.filter(
    (candidate) => candidate.promotionEligible && candidate.activationState === "NOT_REQUESTED"
  ).length;
  const running = data.evaluations.filter((run) => run.state === "RUNNING" || run.state === "QUEUED").length;
  const recentPromotions = data.recentEvents.filter((event) => event.eventType === "PROMOTED");
  const connectedSchedules = data.schedules.filter((job) => job.connectionState === "CONNECTED").length;
  const queue = [...data.candidates]
    .sort((left, right) => {
      const priority = (candidate: (typeof data.candidates)[number]) =>
        candidate.status === "BLOCKED" ? 0 : candidate.status === "PROMOTION_PENDING" ? 1 : 2;
      return priority(left) - priority(right) || right.updatedAt.localeCompare(left.updatedAt);
    })
    .slice(0, 6);

  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="OVERVIEW / EVIDENCE TO ACTIVATION"
        title="Promotion control plane"
        line1={governedCopyBody.screens.overview.line1}
        line2={governedCopyBody.screens.overview.line2}
        aside={
          <div className="pcp-as-of">
            <span>SNAPSHOT / UTC</span>
            <strong>{formatUtc(data.generatedAt)}</strong>
          </div>
        }
      />

      <div className="pcp-metric-grid pcp-metric-grid-three">
        <MetricCard
          label="Awaiting lifecycle decision"
          value={String(awaitingDecision).padStart(2, "0")}
          meaning="Eligible candidates with complete evidence."
          tone="decision"
        />
        <MetricCard
          label="Blocked candidates"
          value={String(blocked).padStart(2, "0")}
          meaning="A failed or remaining requirement stops promotion."
          tone={blocked > 0 ? "degraded" : "neutral"}
        />
        <MetricCard
          label="Worker queue"
          value={String(running).padStart(2, "0")}
          meaning="Evaluation and publication work awaiting leases."
          tone={running > 0 ? "comparison" : "neutral"}
        />
        <MetricCard
          label="Immutable versions"
          value={String(data.registryAgents.length).padStart(2, "0")}
          meaning="Registry activations completed by the worker."
        />
        <MetricCard
          label="Promotion velocity"
          value={String(recentPromotions.length).padStart(2, "0")}
          meaning={recentPromotions[0]
            ? `Latest visible activation: ${formatUtc(recentPromotions[0].occurredAt)}.`
            : "No activation appears in the current event window."}
          tone="comparison"
        />
        <MetricCard
          label="Automation health"
          value={`${connectedSchedules}/${data.schedules.length}`}
          meaning="Named schedule owners currently connected."
          tone={connectedSchedules === data.schedules.length ? "neutral" : "degraded"}
        />
      </div>

      <section className="pcp-section" aria-labelledby="lifecycle-funnel">
        <SectionHeading
          index="01"
          title="Lifecycle position"
          detail="Candidate stage and operational status remain separate."
        />
        <div className="pcp-funnel" id="lifecycle-funnel">
          {lifecycleStages.map((stage, index) => {
            const stageCandidates = data.candidates.filter((candidate) => candidate.stage === stage);
            return (
              <div className="pcp-funnel-step" key={stage}>
                <span className="pcp-funnel-index">{String(index + 1).padStart(2, "0")}</span>
                <strong>{stageCandidates.length}</strong>
                <span>{humanize(stage)}</span>
                {index < lifecycleStages.length - 1 ? <i aria-hidden="true" /> : null}
              </div>
            );
          })}
        </div>
      </section>

      <div className="pcp-dashboard-columns">
        <section className="pcp-section" aria-labelledby="review-queue">
          <SectionHeading
            index="02"
            title="Review queue"
            detail="Blocked and pending candidates appear first."
            action={<DraftLink onClick={() => navigate("/candidates")}>All candidates</DraftLink>}
          />
          {queue.length === 0 ? (
            <EmptyState>No candidates are available for review.</EmptyState>
          ) : (
            <div className="pcp-candidate-list" id="review-queue">
              {queue.map((candidate) => (
                <article className="pcp-candidate-row" key={candidate.id}>
                  <div className="pcp-row-main">
                    <span className="pcp-component-code">{candidate.component}</span>
                    <h3>{candidate.name}</h3>
                    <p>{candidate.surfacedReason}</p>
                  </div>
                  <div className="pcp-row-state">
                    <StatusMark tone={blockerTone(candidate)} compact>
                      {humanize(candidate.status)}
                    </StatusMark>
                    <span>{formatPercent(candidate.evaluation.readinessPercentage)} evidence ready</span>
                    <StatusMark tone={activationTone(candidate.activationState)} compact>
                      {humanize(candidate.activationState)}
                    </StatusMark>
                  </div>
                  <DraftLink
                    onClick={() => navigate(candidateRoute(candidate.id))}
                    ariaLabel={`Open ${candidate.name}`}
                  >
                    Inspect
                  </DraftLink>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="pcp-section" aria-labelledby="recent-events">
          <SectionHeading
            index="03"
            title="Durable event line"
            detail="Sequence-backed events remain authoritative after reconnects."
            action={<DraftLink onClick={() => navigate("/audit")}>Full audit</DraftLink>}
          />
          {data.recentEvents.length === 0 ? (
            <EmptyState>No promotion events have been recorded.</EmptyState>
          ) : (
            <ol className="pcp-event-list" id="recent-events">
              {data.recentEvents.slice(0, 7).map((event) => (
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
      </div>

      <div className="pcp-overview-operations">
        <section className="pcp-section">
          <SectionHeading
            index="04"
            title="Recently promoted"
            detail="Only worker-activated immutable versions appear here."
            action={<DraftLink onClick={() => navigate("/registry")}>Open registry</DraftLink>}
          />
          {data.registryAgents.length === 0 ? (
            <EmptyState>No recent registry activation is visible.</EmptyState>
          ) : (
            <ol className="pcp-compact-operations">
              {data.registryAgents.slice(0, 4).map((agent) => (
                <li key={agent.id}>
                  <div><strong>{agent.name}</strong><span>Version {agent.version} · {formatUtc(agent.promotedAt)}</span></div>
                  <StatusMark tone={agent.state === "SUSPENDED" ? "degraded" : "neutral"} compact>{agent.state ? humanize(agent.state) : "State not reported"}</StatusMark>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className="pcp-section">
          <SectionHeading
            index="05"
            title="Named automation owners"
            detail="Next expected times describe external triggers, not internal cron."
            action={<DraftLink onClick={() => navigate("/automation")}>Open automation</DraftLink>}
          />
          {data.schedules.length === 0 ? (
            <EmptyState>No observed schedules are configured.</EmptyState>
          ) : (
            <ol className="pcp-compact-operations">
              {data.schedules.slice(0, 4).map((job) => (
                <li key={job.id}>
                  <div>
                    <strong>{job.name}</strong>
                    <span>{job.triggerOwner} · Next expected: {job.nextExpectedTriggerAt ? formatUtc(job.nextExpectedTriggerAt) : "No trigger expected"}</span>
                  </div>
                  <StatusMark tone={connectionTone(job.connectionState)} compact>{humanize(job.connectionState)}</StatusMark>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
