import type {
  PromotionDataSource,
  PromotionMutation,
  PromotionQuery
} from "./types.js";

export interface HttpPromotionDataSourceOptions {
  apiBase?: string;
  eventStreamUrl?: string;
  fetchImplementation?: typeof fetch;
  eventSourceFactory?: (url: string) => EventSource;
}

function queryPath(query: PromotionQuery): string {
  const params = new URLSearchParams();
  if (query.cursor) params.set("after", query.cursor);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  switch (query.resource) {
    case "dashboard": return `/api/v1/dashboard${suffix}`;
    case "candidate": return query.id ? `/api/v1/candidates/${encodeURIComponent(query.id)}` : `/api/v1/candidates${suffix}`;
    case "evaluation": return query.id ? `/api/v1/evaluations/${encodeURIComponent(query.id)}` : `/api/v1/evaluations${suffix}`;
    case "events": return `/api/v1/events${suffix}`;
    case "policies": return `/api/v1/policies${suffix}`;
    case "schedules": return `/api/v1/schedules${suffix}`;
    case "registry": return query.id ? `/api/v1/registry/agents/${encodeURIComponent(query.id)}` : `/api/v1/registry/agents${suffix}`;
  }
}

function mutationPath(mutation: PromotionMutation): string {
  switch (mutation.resource) {
    case "promotion": return `/api/v1/candidates/${encodeURIComponent(mutation.id)}/promote`;
    case "promotion-retry": return `/api/v1/promotion-operations/${encodeURIComponent(mutation.id)}/retry`;
    case "evaluation": return `/api/v1/candidates/${encodeURIComponent(mutation.id)}/evaluate`;
    case "schedule": return `/api/v1/schedules/${encodeURIComponent(mutation.id)}/trigger`;
    case "demo-cycle": return "/api/v1/demo/cycle";
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const problem = await response.json().catch(() => null) as { detail?: string; title?: string; code?: string } | null;
  const message = problem?.detail ?? problem?.title ?? `Control-plane request failed with status ${response.status}.`;
  throw new Error(problem?.code ? `${message} (${problem.code})` : message);
}

export function createHttpPromotionDataSource(options: HttpPromotionDataSourceOptions = {}): PromotionDataSource {
  const apiBase = (options.apiBase ?? "/api/control").replace(/\/$/, "");
  const eventStreamUrl = options.eventStreamUrl ?? "/api/events/stream";
  const request = options.fetchImplementation ?? fetch;
  const createEvents = options.eventSourceFactory ?? ((url: string) => new EventSource(url));

  return {
    async query<T>(query: PromotionQuery): Promise<T> {
      const response = await request(`${apiBase}${queryPath(query)}`, {
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      return parseResponse<T>(response);
    },
    async mutate<T>(mutation: PromotionMutation): Promise<T> {
      const body = {
        ...(mutation.body ?? {}),
        actor: typeof mutation.body?.actor === "string" ? mutation.body.actor : "standalone-reviewer",
        ...(mutation.expectedCandidateRevision === undefined
          ? {}
          : { expected_candidate_revision: mutation.expectedCandidateRevision })
      };
      const response = await request(`${apiBase}${mutationPath(mutation)}`, {
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": mutation.idempotencyKey
        },
        body: JSON.stringify(body)
      });
      return parseResponse<T>(response);
    },
    subscribe(listener, subscriptionOptions) {
      const url = new URL(eventStreamUrl, globalThis.location?.origin ?? "http://localhost");
      if (subscriptionOptions?.candidateId) url.searchParams.set("candidate_id", subscriptionOptions.candidateId);
      if (subscriptionOptions?.lastEventId) url.searchParams.set("after", subscriptionOptions.lastEventId);
      const source = createEvents(url.pathname + url.search);
      source.onopen = () => subscriptionOptions?.onConnectionChange?.(true);
      source.onerror = () => subscriptionOptions?.onConnectionChange?.(false);
      const handleEvent = (message: MessageEvent<string>) => {
        try {
          const raw = JSON.parse(message.data) as Record<string, unknown>;
          const payload = raw.payload && typeof raw.payload === "object"
            ? raw.payload as Record<string, unknown>
            : {};
          subscriptionOptions?.onConnectionChange?.(true);
          listener({
            id: String(raw.id ?? message.lastEventId),
            sequence: Number(raw.sequence ?? message.lastEventId),
            schemaVersion: Number(raw.schema_version ?? raw.schemaVersion ?? 1),
            eventType: String(raw.event_type ?? raw.eventType ?? "PROMOTION_EVENT"),
            occurredAt: String(raw.occurred_at ?? raw.occurredAt ?? new Date().toISOString()),
            actor: String(raw.actor ?? "system"),
            candidateId: typeof (raw.candidate_id ?? raw.candidateId) === "string"
              ? String(raw.candidate_id ?? raw.candidateId)
              : null,
            evaluationRunId: typeof (raw.evaluation_run_id ?? raw.evaluationRunId) === "string"
              ? String(raw.evaluation_run_id ?? raw.evaluationRunId)
              : null,
            scheduleRunId: typeof (raw.scheduled_job_run_id ?? raw.scheduleRunId) === "string"
              ? String(raw.scheduled_job_run_id ?? raw.scheduleRunId)
              : null,
            registryOperationId: typeof (raw.registry_operation_id ?? raw.registryOperationId) === "string"
              ? String(raw.registry_operation_id ?? raw.registryOperationId)
              : null,
            correlationId: String(raw.correlation_id ?? raw.correlationId ?? ""),
            causationId: typeof (raw.causation_id ?? raw.causationId) === "string"
              ? String(raw.causation_id ?? raw.causationId)
              : null,
            policyHash: typeof (raw.policy_hash ?? raw.policyHash) === "string"
              ? String(raw.policy_hash ?? raw.policyHash)
              : null,
            payload
          });
        } catch {
          // A malformed frame is ignored. PostgreSQL replay remains authoritative.
        }
      };
      source.addEventListener("promotion_event", handleEvent as EventListener);
      return () => source.close();
    }
  };
}
