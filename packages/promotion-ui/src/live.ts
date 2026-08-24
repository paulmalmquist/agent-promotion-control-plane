import { humanize } from "./format.js";
import { promotionEventCopy } from "./event-copy.js";
import type {
  CandidateViewModel,
  DashboardViewModel,
  PromotionEventEnvelope
} from "./types.js";

const lifecycleJourney: CandidateViewModel["journey"] = [
  "DISCOVERED",
  "CANDIDATE",
  "EVALUATING",
  "ELIGIBLE",
  "SHADOW",
  "PROMOTED",
  "MONITORED"
];

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === "string" ? value : undefined;
}

function numericValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function number(payload: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const parsed = numericValue(payload[key]);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

function ratio(payload: Record<string, unknown>, ...keys: string[]): number | undefined {
  const parsed = number(payload, ...keys);
  return parsed === undefined ? undefined : parsed > 1 ? parsed / 100 : parsed;
}

function boolean(payload: Record<string, unknown>, ...keys: string[]): boolean | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "boolean") return value;
    if (value === "true") return true;
    if (value === "false") return false;
  }
  return undefined;
}

function createDiscoveredCandidate(
  event: PromotionEventEnvelope,
  recentEvent: DashboardViewModel["recentEvents"][number]
): CandidateViewModel {
  const nestedCandidate = record(event.payload.candidate);
  const payload = { ...nestedCandidate, ...event.payload };
  const slug = text(payload, "slug") ?? text(payload, "candidate_slug");
  const signal = text(payload, "signal") ?? "deterministic discovery signal";
  const readiness = record(payload.readiness ?? payload.evaluation);
  const readinessPercentage = number(
    readiness,
    "evaluation_readiness",
    "readiness_percentage"
  ) ?? number(payload, "evaluation_readiness", "readiness_percentage") ?? 0;
  const stage = text(payload, "stage") ?? "DISCOVERED";
  const status = text(payload, "status") ?? "ACTIVE";
  const activationState = text(payload, "activation_state")
    ?? text(payload, "registry_activation_state")
    ?? "NOT_REQUESTED";

  return {
    id: event.candidateId!,
    slug: slug ?? event.candidateId!,
    name: text(payload, "name") ?? text(payload, "candidate_name") ?? (slug ? humanize(slug) : "Discovered candidate"),
    component: text(payload, "component") ?? text(payload, "candidate_type") ?? "DISCOVERY / SIGNAL",
    candidateType: text(payload, "candidate_type") ?? "AUTONOMOUS_AGENT",
    discoverySource: text(payload, "discovery_source") ?? text(payload, "discovered_by") ?? "Deterministic discovery event",
    description: text(payload, "summary") ?? text(payload, "description") ?? "A detector surfaced this candidate during the autonomous cycle.",
    surfacedReason: text(payload, "rationale") ?? text(payload, "surfaced_reason") ?? humanize(signal),
    detectorLineage: text(payload, "discovered_by") ?? text(payload, "detector_lineage") ?? `${event.actor} / deterministic event`,
    stage,
    status: status as CandidateViewModel["status"],
    revision: number(payload, "candidate_revision", "revision") ?? 1,
    policyName: text(payload, "policy_name") ?? "Policy assignment pending",
    policyId: text(payload, "policy_id") ?? null,
    policyKey: text(payload, "policy_key") ?? null,
    policyHash: event.policyHash ?? text(payload, "policy_hash") ?? "policy hash pending",
    evaluationSnapshotHash: text(payload, "evaluation_snapshot_hash") ?? "evaluation snapshot pending",
    evaluation: {
      readinessPercentage,
      hardGateReadiness: ratio(readiness, "hard_gate_readiness") ?? ratio(payload, "hard_gate_readiness") ?? 0,
      weightedReadiness: ratio(readiness, "weighted_readiness") ?? ratio(payload, "weighted_readiness") ?? 0,
      sampleCompleteness: ratio(readiness, "sample_completeness") ?? ratio(payload, "sample_completeness") ?? 0,
      evaluationCompleteness: ratio(readiness, "evaluation_completeness") ?? ratio(payload, "evaluation_completeness") ?? 0,
      weightedScore: number(readiness, "weighted_score") ?? number(payload, "weighted_score") ?? null,
      requiredWeightedScore: number(readiness, "required_weighted_score", "minimum_weighted_score")
        ?? number(payload, "required_weighted_score", "minimum_weighted_score")
        ?? 0,
      validResultCount: number(readiness, "valid_result_count") ?? 0,
      requiredResultCount: number(readiness, "required_result_count") ?? 0
    },
    promotionEligible: boolean(payload, "promotion_eligible") ?? false,
    lifecycleApprovalState: "NOT_REQUIRED",
    requiredLifecycleApprovals: 0,
    availableLifecycleApprovals: 0,
    consumedLifecycleApprovals: 0,
    activeBlockerCount: 0,
    activationState: activationState as CandidateViewModel["activationState"],
    blockerCode: null,
    blockerSummary: null,
    blockers: [],
    latestDecision: null,
    registryOperationId: event.registryOperationId,
    updatedAt: event.occurredAt,
    latestEvaluationAt: null,
    hardGatesPassed: null,
    hardGatesRequired: null,
    journey: lifecycleJourney,
    gates: [],
    evidence: [],
    timeline: [recentEvent]
  };
}

export function applyPromotionEvent(
  dashboard: DashboardViewModel,
  event: PromotionEventEnvelope
): DashboardViewModel {
  const matchingIndex = dashboard.recentEvents.findIndex((item) => item.sequence === event.sequence);
  const eventCopy = promotionEventCopy(event.eventType, event.payload);
  const recentEvent = {
    id: event.id,
    sequence: event.sequence,
    eventType: event.eventType,
    occurredAt: event.occurredAt,
    actor: event.actor,
    headline: eventCopy.headline,
    detail: eventCopy.detail,
    correlationId: event.correlationId,
    ...(event.causationId ? { causationId: event.causationId } : {})
  };

  const recentEvents = matchingIndex >= 0
    ? dashboard.recentEvents
    : [recentEvent, ...dashboard.recentEvents].sort((a, b) => b.sequence - a.sequence).slice(0, 40);

  if (!event.candidateId) {
    return { ...dashboard, generatedAt: event.occurredAt, recentEvents };
  }

  const candidateExists = dashboard.candidates.some((candidate) => candidate.id === event.candidateId);
  const candidates = dashboard.candidates.map((candidate) => {
    if (candidate.id !== event.candidateId) return candidate;

    const promotionEligibility = record(event.payload.promotion_eligibility);
    const stage = text(event.payload, "stage") ?? candidate.stage;
    const status = text(event.payload, "status") ?? candidate.status;
    const activationState = text(promotionEligibility, "registry_activation_state")
      ?? text(event.payload, "activation_state")
      ?? text(event.payload, "registry_activation_state")
      ?? candidate.activationState;
    const approvalState = text(promotionEligibility, "lifecycle_approval_state")
      ?? text(event.payload, "lifecycle_approval_state");
    const normalizedApprovalState = approvalState === "SATISFIED"
      ? "APPROVED"
      : approvalState === "LOCKED"
        ? "CONSUMED"
        : approvalState;
    const readinessPayload = record(event.payload.readiness ?? event.payload.evaluation);
    const readiness = number(
      readinessPayload,
      "evaluation_readiness",
      "readiness_percentage"
    ) ?? number(event.payload, "evaluation_readiness", "readiness_percentage");
    const hardGateReadiness = ratio(readinessPayload, "hard_gate_readiness")
      ?? ratio(event.payload, "hard_gate_readiness");
    const weightedReadiness = ratio(readinessPayload, "weighted_readiness")
      ?? ratio(event.payload, "weighted_readiness");
    const sampleCompleteness = ratio(readinessPayload, "sample_completeness")
      ?? ratio(event.payload, "sample_completeness");
    const evaluationCompleteness = ratio(readinessPayload, "evaluation_completeness")
      ?? ratio(event.payload, "evaluation_completeness");
    const weightedScore = number(readinessPayload, "weighted_score")
      ?? number(event.payload, "weighted_score");
    const candidateTimeline = candidate.timeline.some((item) => item.sequence === event.sequence)
      ? candidate.timeline
      : [recentEvent, ...candidate.timeline].sort((a, b) => b.sequence - a.sequence);

    return {
      ...candidate,
      stage: stage as typeof candidate.stage,
      status: status as typeof candidate.status,
      activationState: activationState as typeof candidate.activationState,
      registryOperationId: event.registryOperationId ?? candidate.registryOperationId,
      revision: number(event.payload, "candidate_revision", "revision") ?? candidate.revision,
      promotionEligible: boolean(promotionEligibility, "eligible")
        ?? boolean(event.payload, "promotion_eligible")
        ?? candidate.promotionEligible,
      lifecycleApprovalState: (normalizedApprovalState ?? candidate.lifecycleApprovalState) as CandidateViewModel["lifecycleApprovalState"],
      requiredLifecycleApprovals: number(promotionEligibility, "required_lifecycle_approvals")
        ?? candidate.requiredLifecycleApprovals,
      availableLifecycleApprovals: number(promotionEligibility, "available_lifecycle_approvals")
        ?? candidate.availableLifecycleApprovals,
      consumedLifecycleApprovals: number(promotionEligibility, "consumed_lifecycle_approvals")
        ?? candidate.consumedLifecycleApprovals,
      activeBlockerCount: number(promotionEligibility, "active_blocker_count")
        ?? candidate.activeBlockerCount,
      updatedAt: event.occurredAt,
      timeline: candidateTimeline,
      evaluation: {
        ...candidate.evaluation,
        ...(readiness === undefined ? {} : { readinessPercentage: readiness }),
        ...(hardGateReadiness === undefined ? {} : { hardGateReadiness }),
        ...(weightedReadiness === undefined ? {} : { weightedReadiness }),
        ...(sampleCompleteness === undefined ? {} : { sampleCompleteness }),
        ...(evaluationCompleteness === undefined ? {} : { evaluationCompleteness }),
        ...(weightedScore === undefined ? {} : { weightedScore })
      }
    };
  });

  if (!candidateExists && event.eventType === "CANDIDATE_DISCOVERED") {
    candidates.unshift(createDiscoveredCandidate(event, recentEvent));
  }

  return { ...dashboard, generatedAt: event.occurredAt, candidates, recentEvents };
}
