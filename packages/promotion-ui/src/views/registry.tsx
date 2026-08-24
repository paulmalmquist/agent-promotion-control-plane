import { DraftLink, EmptyState, ScreenIntro, SectionHeading, StatusMark, TechnicalReference } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { formatUtc, humanize } from "../format.js";
import { registryAgentRoute } from "../routes.js";
import type { DashboardViewModel, RegistryAgentViewModel } from "../types.js";

export function RegistryView({ data, navigate }: { data: DashboardViewModel; navigate: (path: string) => void }) {
  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="REGISTRY / ACTIVATED VERSIONS"
        title="Promoted agents"
        line1={governedCopyBody.screens.registry.line1}
        line2={governedCopyBody.screens.registry.line2}
      />
      {data.registryAgents.length === 0 ? (
        <EmptyState>No immutable agent versions have been activated.</EmptyState>
      ) : (
        <div className="pcp-registry-list">
          {data.registryAgents.map((agent, index) => (
            <article key={agent.id}>
              <span className="pcp-card-index">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <p className="pcp-eyebrow">VERSION {agent.version}</p>
                <h2>{agent.name}</h2>
                <p>Published {formatUtc(agent.promotedAt)} · Health: {agent.health ? humanize(agent.health) : "Not reported"}</p>
              </div>
              <StatusMark tone={agent.state === "SUSPENDED" ? "degraded" : "neutral"}>{agent.state ? humanize(agent.state) : "State not reported"}</StatusMark>
              <TechnicalReference label="Policy" value={agent.policyHash} />
              <DraftLink onClick={() => navigate(registryAgentRoute(agent.agentId ?? agent.id))}>Inspect version</DraftLink>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export function RegistryAgentDetailView({ agent, navigate }: { agent: RegistryAgentViewModel | undefined; navigate: (path: string) => void }) {
  if (!agent) {
    return (
      <div className="pcp-view">
        <ScreenIntro eyebrow="REGISTRY / NOT FOUND" title="Agent version unavailable" line1="This registry version is not present in the current control-plane snapshot." line2="Return to the registry and select an available immutable version." />
        <DraftLink onClick={() => navigate("/registry")}>Return to registry</DraftLink>
      </div>
    );
  }
  return (
    <div className="pcp-view">
      <div className="pcp-breadcrumbs"><button type="button" onClick={() => navigate("/registry")}>Registry</button><span>/</span><span>{agent.name}</span></div>
      <ScreenIntro
        eyebrow={`REGISTRY / VERSION ${agent.version}`}
        title={agent.name}
        line1="This immutable version exists because registry publication completed successfully."
        line2="Verify its policy and publication token before downstream production selection."
        aside={<StatusMark tone={agent.state === "SUSPENDED" ? "degraded" : "neutral"}>{agent.state ? humanize(agent.state) : "State not reported"}</StatusMark>}
      />
      <section className="pcp-run-sheet">
        <div><span>Registry key</span><strong>{agent.registryKey ?? "Not reported"}</strong></div>
        <div><span>External version</span><strong>{agent.externalVersionId ?? "Not reported"}</strong></div>
        <div><span>Activated</span><strong>{formatUtc(agent.promotedAt)}</strong></div>
        <div><span>Version</span><strong>{agent.version}</strong></div>
        <div><span>Policy snapshot</span><TechnicalReference label="SHA-256" value={agent.policyHash} /></div>
        <div><span>Evaluation snapshot</span><TechnicalReference label="SHA-256" value={agent.evaluationSnapshotHash} /></div>
        <div><span>Stable publication token</span>{agent.publicationToken ? <TechnicalReference label="Token" value={agent.publicationToken} /> : <strong>Not reported</strong>}</div>
        <div><span>Candidate stage</span><strong>{agent.candidateStage ? humanize(agent.candidateStage) : "Not reported"}</strong></div>
        <div><span>Candidate status</span><strong>{agent.candidateStatus ? humanize(agent.candidateStatus) : "Not reported"}</strong></div>
        <div><span>Current health</span><strong>{agent.health ? humanize(agent.health) : "Registry does not report health"}</strong></div>
        <div><span>Monitoring state</span><strong>{agent.monitoringState ? humanize(agent.monitoringState) : "Not reported"}</strong></div>
        <div><span>Monitoring runs</span><strong>{agent.monitoringRunCount ?? "Count not reported"}</strong></div>
        <div><span>Active registry version</span><strong>{agent.isActiveVersion === null ? "Not reported" : agent.isActiveVersion ? "Yes" : "No"}</strong></div>
      </section>
      {agent.recentMonitoringEvents.length > 0 ? (
        <section className="pcp-section">
          <SectionHeading index="01" title="Recent monitoring activity" detail="Durable events describe post-promotion observation." />
          <ol className="pcp-event-list">
            {agent.recentMonitoringEvents.map((event) => (
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
        </section>
      ) : null}
      <p className="pcp-authority-notice">{governedCopyBody.authorityNotice}</p>
    </div>
  );
}
