import { useMemo, useState } from "react";
import { EmptyState, ScreenIntro, TechnicalReference } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { formatUtc } from "../format.js";
import type { DashboardViewModel } from "../types.js";

export function AuditView({ data }: { data: DashboardViewModel }) {
  const [filter, setFilter] = useState("");
  const events = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return query
      ? data.recentEvents.filter((event) => `${event.eventType} ${event.headline} ${event.detail} ${event.actor}`.toLowerCase().includes(query))
      : data.recentEvents;
  }, [data.recentEvents, filter]);

  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="AUDIT / APPEND-ONLY EVENTS"
        title="Control-plane timeline"
        line1={governedCopyBody.screens.audit.line1}
        line2={governedCopyBody.screens.audit.line2}
      />
      <div className="pcp-filter-bar">
        <label><span>Filter durable events</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Event, actor, or explanation" /></label>
        <div className="pcp-filter-count"><strong>{events.length}</strong><span>events shown</span></div>
      </div>
      {events.length === 0 ? (
        <EmptyState>No durable events match the current filter.</EmptyState>
      ) : (
        <ol className="pcp-audit-line">
          {events.map((event) => (
            <li key={event.id}>
              <div className="pcp-audit-sequence"><span>SEQ</span><strong>{event.sequence}</strong></div>
              <div className="pcp-audit-copy">
                <p className="pcp-eyebrow">{event.eventType}</p>
                <h2>{event.headline}</h2>
                <p>{event.detail}</p>
              </div>
              <dl>
                <div><dt>Recorded</dt><dd>{formatUtc(event.occurredAt)}</dd></div>
                <div><dt>Actor</dt><dd>{event.actor}</dd></div>
                {event.correlationId ? <div><dt>Correlation</dt><dd><TechnicalReference label="ID" value={event.correlationId} /></dd></div> : null}
                {event.causationId ? <div><dt>Causation</dt><dd><TechnicalReference label="ID" value={event.causationId} /></dd></div> : null}
              </dl>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
