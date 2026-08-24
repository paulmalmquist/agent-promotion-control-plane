import type { CandidateViewModel, DashboardViewModel } from "@promotion-control-plane/ui";

const now = "2026-08-24T14:20:00.000Z";
const stages = ["DISCOVERED", "CANDIDATE", "EVALUATING", "ELIGIBLE", "SHADOW", "PROMOTED", "MONITORED"] as const;

function candidate(index: number, overrides: Partial<CandidateViewModel> = {}): CandidateViewModel {
  const id = `00000000-0000-4000-8000-00000000000${index}`;
  return {
    id,
    slug: `fixture-candidate-${index}`,
    name: `Fixture candidate ${String(index).padStart(2, "0")}`,
    component: `DETECTOR / ${String(index).padStart(2, "0")}`,
    candidateType: "AUTONOMOUS_AGENT",
    discoverySource: `Fixture detector ${index}`,
    description: "An explicit test fixture shown only when fixture fallback is enabled.",
    surfacedReason: "Repeated verified completions suggest this workflow can be promoted.",
    detectorLineage: `workflow-repetition / revision ${index}`,
    stage: stages[Math.min(index - 1, stages.length - 1)]!,
    status: "ACTIVE",
    revision: index,
    policyName: "Reference promotion policy",
    policyId: "fixture-policy",
    policyKey: "reference-promotion",
    policyHash: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef",
    evaluationSnapshotHash: "b1c2d3e4f5a60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
    evaluation: {
      readinessPercentage: index * 12,
      hardGateReadiness: 1,
      weightedReadiness: Math.min(index / 7, 1),
      sampleCompleteness: Math.min(index / 7, 1),
      evaluationCompleteness: Math.min(index / 7, 1),
      weightedScore: Math.min(index * 13, 96),
      requiredWeightedScore: 80,
      validResultCount: index,
      requiredResultCount: 7
    },
    promotionEligible: false,
    lifecycleApprovalState: "REQUIRED",
    requiredLifecycleApprovals: 1,
    availableLifecycleApprovals: 0,
    consumedLifecycleApprovals: 0,
    activeBlockerCount: 0,
    activationState: "NOT_REQUESTED",
    blockerCode: null,
    blockerSummary: null,
    blockers: [],
    latestDecision: null,
    registryOperationId: null,
    updatedAt: now,
    latestEvaluationAt: index > 2 ? now : null,
    hardGatesPassed: index > 2 ? 2 : 0,
    hardGatesRequired: 2,
    journey: [...stages],
    gates: [],
    evidence: [],
    timeline: [],
    ...overrides
  };
}

export const fixtureDashboard: DashboardViewModel = {
  generatedAt: now,
  candidates: [
    candidate(1),
    candidate(2),
    candidate(3, {
      status: "BLOCKED",
      blockerCode: "QUALITY_REGRESSION",
      blockerSummary: "Regression tolerance exceeded the policy threshold.",
      evaluation: {
        readinessPercentage: 81,
        hardGateReadiness: 0,
        weightedReadiness: 1,
        sampleCompleteness: 1,
        evaluationCompleteness: 1,
        weightedScore: 96,
        requiredWeightedScore: 80,
        validResultCount: 7,
        requiredResultCount: 7
      }
    }),
    candidate(4, { status: "PROMOTION_PENDING", activationState: "PENDING", promotionEligible: true }),
    candidate(5),
    candidate(6, { stage: "PROMOTED", activationState: "SUCCEEDED" }),
    candidate(7, { stage: "MONITORED", activationState: "SUCCEEDED" }),
    candidate(8, { status: "SUSPENDED", blockerCode: "MONITORING_REGRESSION", blockerSummary: "Production monitoring detected a material regression." })
  ],
  evaluations: [],
  policies: [],
  schedules: [],
  registryAgents: [],
  recentEvents: [],
  liveConnected: false,
  demoMode: true
};
