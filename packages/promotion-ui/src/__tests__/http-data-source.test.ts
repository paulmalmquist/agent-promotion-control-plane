import { createHttpPromotionDataSource } from "../http-data-source";

class FakeEventSource {
  static current: FakeEventSource | null = null;
  listeners = new Map<string, EventListener>();
  closed = false;
  onopen: EventListener | null = null;
  onerror: EventListener | null = null;

  constructor(public readonly url: string) {
    FakeEventSource.current = this;
  }

  addEventListener(name: string, listener: EventListener) {
    this.listeners.set(name, listener);
  }

  close() {
    this.closed = true;
  }

  dispatch(name: string, data: string, lastEventId: string) {
    this.listeners.get(name)?.({ data, lastEventId } as unknown as Event);
  }
}

describe("HTTP promotion data source", () => {
  it("normalizes real snake_case server-sent event envelopes", () => {
    const source = createHttpPromotionDataSource({
      eventStreamUrl: "/api/events/stream",
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    });
    const listener = vi.fn();
    const connectionListener = vi.fn();
    const unsubscribe = source.subscribe(listener, {
      candidateId: "candidate-1",
      lastEventId: "40",
      onConnectionChange: connectionListener
    });
    FakeEventSource.current!.onopen?.({} as Event);
    FakeEventSource.current!.dispatch("promotion_event", JSON.stringify({
      id: "event-41",
      sequence: 41,
      schema_version: 1,
      event_type: "PROMOTION_REGISTRY_QUEUED",
      occurred_at: "2026-08-24T14:30:00Z",
      actor: "reviewer@example.test",
      candidate_id: "candidate-1",
      evaluation_run_id: null,
      scheduled_job_run_id: null,
      registry_operation_id: "operation-1",
      policy_hash: "policy-hash-1",
      correlation_id: "correlation-1",
      causation_id: "event-40",
      payload: { stage: "ELIGIBLE", status: "PROMOTION_PENDING", candidate_revision: 8 }
    }), "41");

    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      sequence: 41,
      schemaVersion: 1,
      eventType: "PROMOTION_REGISTRY_QUEUED",
      occurredAt: "2026-08-24T14:30:00Z",
      candidateId: "candidate-1",
      registryOperationId: "operation-1",
      policyHash: "policy-hash-1",
      payload: expect.objectContaining({ status: "PROMOTION_PENDING" })
    }));
    expect(FakeEventSource.current!.url).toContain("candidate_id=candidate-1");
    expect(FakeEventSource.current!.url).toContain("after=40");
    expect(connectionListener).toHaveBeenCalledWith(true);
    FakeEventSource.current!.onerror?.({} as Event);
    expect(connectionListener).toHaveBeenLastCalledWith(false);
    unsubscribe();
    expect(FakeEventSource.current!.closed).toBe(true);
  });

  it("maps public mutations to the stable versioned API", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ operation_id: "operation-1" }), {
      status: 202,
      headers: { "Content-Type": "application/json" }
    }));
    const source = createHttpPromotionDataSource({ fetchImplementation: request });
    await source.mutate({
      resource: "promotion-retry",
      id: "operation-1",
      expectedCandidateRevision: 8,
      idempotencyKey: "retry-request-1"
    });
    expect(request.mock.calls[0]?.[0]).toBe("/api/control/api/v1/promotion-operations/operation-1/retry");
    expect(JSON.parse(request.mock.calls[0]?.[1]?.body as string)).toEqual({
      actor: "standalone-reviewer",
      expected_candidate_revision: 8
    });
  });
});
