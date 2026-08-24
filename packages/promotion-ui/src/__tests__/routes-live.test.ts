import { applyPromotionEvent } from "../live";
import { promotionEventCopy } from "../event-copy";
import { parsePromotionRoute } from "../routes";
import { fixtureDashboard } from "./fixture";

describe("promotion route helpers", () => {
  it.each([
    ["/", "overview", undefined],
    ["/candidates", "candidates", undefined],
    ["/candidates/candidate-1", "candidate", "candidate-1"],
    ["/agents/promotion/automation", "automation", undefined],
    ["/registry/agent-1", "registry-agent", "agent-1"]
  ])("parses %s", (path, name, id) => {
    expect(parsePromotionRoute(path)).toEqual(id ? { name, id } : { name });
  });
});

describe("live event reducer", () => {
  const event = {
    id: "event-13",
    sequence: 13,
    schemaVersion: 1,
    eventType: "PROMOTION_REGISTRY_QUEUED",
    occurredAt: "2026-08-24T14:22:00.000Z",
    actor: "reviewer@example.test",
    candidateId: fixtureDashboard.candidates[0]!.id,
    evaluationRunId: null,
    scheduleRunId: null,
    registryOperationId: "operation-13",
    correlationId: "correlation-13",
    causationId: "event-12",
    payload: {
      headline: "Registry publication queued",
      detail: "The candidate remains eligible while the worker claims publication.",
      status: "PROMOTION_PENDING",
      stage: "ELIGIBLE",
      activation_state: "PENDING",
      candidate_revision: 8
    }
  } as const;

  it("updates pending activation without inventing a promoted stage", () => {
    const result = applyPromotionEvent(fixtureDashboard, event);
    expect(result.candidates[0]).toMatchObject({
      stage: "ELIGIBLE",
      status: "PROMOTION_PENDING",
      activationState: "PENDING",
      revision: 8,
      registryOperationId: "operation-13"
    });
    expect(result.recentEvents[0]?.eventType).toBe("PROMOTION_REGISTRY_QUEUED");
  });

  it("deduplicates sequence-backed event replay", () => {
    const first = applyPromotionEvent(fixtureDashboard, event);
    const replayed = applyPromotionEvent(first, event);
    expect(replayed.recentEvents.filter((item) => item.sequence === 13)).toHaveLength(1);
  });

  it("adds a discovered candidate and advances string readiness without reloading", () => {
    const discovered = applyPromotionEvent(fixtureDashboard, {
      ...event,
      id: "event-20",
      sequence: 20,
      eventType: "CANDIDATE_DISCOVERED",
      candidateId: "candidate-new",
      registryOperationId: null,
      policyHash: "policy-new",
      payload: {
        candidate: {
          slug: "change-risk-coordinator",
          name: "Change Risk Coordinator",
          summary: "Coordinates deterministic change-risk checks.",
          candidate_type: "AUTONOMOUS_AGENT"
        },
        signal: "RECURRING_MULTI_SKILL_WORKFLOW",
        stage: "DISCOVERED",
        status: "ACTIVE",
        candidate_revision: "1",
        readiness_percentage: "0.000"
      }
    });
    expect(discovered.candidates[0]).toMatchObject({
      id: "candidate-new",
      name: "Change Risk Coordinator",
      stage: "DISCOVERED",
      revision: 1,
      evaluation: {
        readinessPercentage: 0,
        hardGateReadiness: 0,
        weightedReadiness: 0,
        sampleCompleteness: 0,
        evaluationCompleteness: 0
      }
    });

    const evaluated = applyPromotionEvent(discovered, {
      ...event,
      id: "event-21",
      sequence: 21,
      eventType: "EVALUATION_COMPLETED",
      candidateId: "candidate-new",
      payload: {
        stage: "ELIGIBLE",
        candidate_revision: "2",
        readiness: {
          evaluation_readiness: "91.667",
          hard_gate_readiness: "66.667",
          weighted_readiness: "1.0",
          sample_completeness: "100.000",
          evaluation_completeness: "1"
        }
      }
    });
    expect(evaluated.candidates[0]).toMatchObject({
      stage: "ELIGIBLE",
      revision: 2,
      evaluation: {
        readinessPercentage: 91.667,
        hardGateReadiness: 0.66667,
        weightedReadiness: 1,
        sampleCompleteness: 1,
        evaluationCompleteness: 1
      }
    });
    expect(evaluated.candidates[0]?.timeline.map((item) => item.sequence)).toEqual([21, 20]);
  });
});

describe("typed event copy", () => {
  it("explains promotion and blocker outcomes from snake_case payloads", () => {
    expect(promotionEventCopy("PROMOTED", {
      stage: "PROMOTED",
      status: "ACTIVE",
      registry_activation_state: "SUCCEEDED"
    })).toEqual({
      headline: "Registry activation succeeded",
      detail: "The worker promoted the tested candidate and activated its immutable version."
    });
    expect(promotionEventCopy("BLOCKER_ADDED", {
      code: "HARD_GATE_FAILED",
      title: "Latency hard gate failed"
    })).toEqual({
      headline: "Promotion blocker added",
      detail: "Hard Gate Failed now stops promotion until its recovery action completes."
    });
  });

  it("surfaces provider, schedule, and registry failure detail for core events", () => {
    expect(promotionEventCopy("EVALUATION_RETRY_SCHEDULED", {
      provider: "deterministic evaluator",
      status: "QUEUED"
    }).detail).toContain("deterministic evaluator");
    expect(promotionEventCopy("SCHEDULE_RUN_FAILED", {
      trigger_owner: "GitHub Actions",
      job_key: "nightly_replay",
      status: "FAILED"
    }).detail).toContain("Nightly Replay");
    expect(promotionEventCopy("PROMOTION_REGISTRY_DEAD_LETTERED", {
      failure_message: "The registry connection refused publication."
    }).detail).toContain("registry connection refused");
  });
});
