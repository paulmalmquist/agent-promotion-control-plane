import type { CandidateViewModel, DashboardViewModel } from "../types";

export const fixtureCandidate: CandidateViewModel = {
  id: "11111111-1111-4111-8111-111111111111",
  slug: "release-notes-agent",
  name: "Release notes agent",
  component: "WORKFLOW / RELEASES",
  candidateType: "AUTONOMOUS_AGENT",
  discoverySource: "workflow repetition detector",
  description: "Drafts verified release notes from merged work and linked evidence.",
  surfacedReason: "Twelve repeated runs completed with verified evidence and no manual corrections.",
  detectorLineage: "workflow-repetition / revision 3",
  stage: "ELIGIBLE",
  status: "ACTIVE",
  revision: 7,
  policyName: "Production agent policy",
  policyId: "policy-1",
  policyKey: "production-agent",
  policyHash: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef",
  evaluationSnapshotHash: "b1c2d3e4f5a60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  evaluation: {
    readinessPercentage: 100,
    hardGateReadiness: 1,
    weightedReadiness: 1,
    sampleCompleteness: 1,
    evaluationCompleteness: 1,
    weightedScore: 94.2,
    requiredWeightedScore: 80,
    validResultCount: 4,
    requiredResultCount: 4
  },
  promotionEligible: true,
  lifecycleApprovalState: "APPROVED",
  requiredLifecycleApprovals: 1,
  availableLifecycleApprovals: 1,
  consumedLifecycleApprovals: 0,
  activeBlockerCount: 0,
  activationState: "NOT_REQUESTED",
  blockerCode: null,
  blockerSummary: null,
  blockers: [],
  latestDecision: {
    type: "ELIGIBILITY",
    outcome: "ELIGIBLE",
    rationale: "Every hard gate passed and the weighted score exceeds the policy.",
    actor: "gate-engine",
    decidedAt: "2026-08-24T14:20:00.000Z",
    policyHash: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef",
    evaluationSnapshotHash: "b1c2d3e4f5a60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0"
  },
  registryOperationId: null,
  updatedAt: "2026-08-24T14:20:00.000Z",
  latestEvaluationAt: "2026-08-24T14:10:00.000Z",
  hardGatesPassed: 1,
  hardGatesRequired: 1,
  journey: ["DISCOVERED", "CANDIDATE", "EVALUATING", "ELIGIBLE", "SHADOW", "PROMOTED", "MONITORED"],
  gates: [
    {
      id: "gate-1",
      name: "Safety regression",
      category: "SAFETY",
      kind: "HARD_GATE",
      weight: null,
      verdict: "PASSED",
      score: 0,
      normalizedScore: 1,
      measurementValue: 0,
      measurementUnit: "regressions",
      comparisonOperator: "lte",
      threshold: 0,
      samples: 12,
      minimumSamples: 10,
      evidenceCount: 2,
      requiredEvidenceCount: 2,
      evaluator: "Deterministic rule evaluator",
      lastRunAt: "2026-08-24T14:10:00.000Z",
      meaning: "No safety regression appeared in deterministic replay."
    }
  ],
  evidence: [
    {
      id: "evidence-1",
      kind: "ARTIFACT",
      title: "Deterministic replay report",
      source: "Test suite evaluator",
      recordedAt: "2026-08-24T13:10:00.000Z",
      digest: "c1d2e3f4a5b60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
      uri: "/api/control/api/v1/evidence/evidence-1",
      summary: "All allow-listed release workflows completed with linked sources.",
      signalType: "TEST SUITE"
    }
  ],
  timeline: [
    {
      id: "event-12",
      sequence: 12,
      eventType: "CANDIDATE_ELIGIBLE",
      occurredAt: "2026-08-24T14:20:00.000Z",
      actor: "gate-engine",
      headline: "Candidate became eligible",
      detail: "Every hard gate passed and evaluation evidence is complete.",
      correlationId: "correlation-12"
    }
  ]
};

export const fixtureDashboard: DashboardViewModel = {
  generatedAt: "2026-08-24T14:20:00.000Z",
  candidates: [fixtureCandidate],
  evaluations: [
    {
      id: "evaluation-1",
      candidateId: fixtureCandidate.id,
      candidateName: fixtureCandidate.name,
      planId: "plan-production-readiness",
      planName: "Production readiness plan",
      state: "SUCCEEDED",
      progressPercentage: 100,
      startedAt: "2026-08-24T13:00:00.000Z",
      finishedAt: "2026-08-24T13:15:00.000Z",
      provider: "Deterministic rule evaluator",
      model: "rule-engine-v1",
      attemptCount: 1,
      maxAttempts: 3,
      plannedResultCount: 2,
      heartbeatAt: "2026-08-24T13:14:00.000Z",
      correlationId: "correlation-evaluation-1",
      resultCount: 4,
      sampleCount: 12,
      durationMilliseconds: 900000,
      latencyMilliseconds: 12,
      costUsd: 0,
      errorMessage: null,
      results: fixtureCandidate.gates.map((gate) => ({
        ...gate,
        provider: "deterministic",
        model: "rule-engine-v1",
        costUsd: 0,
        latencyMilliseconds: 12,
        valid: true,
        stale: false
      })),
      artifacts: fixtureCandidate.evidence
    }
  ],
  policies: [],
  schedules: [],
  registryAgents: [],
  recentEvents: fixtureCandidate.timeline,
  liveConnected: true,
  demoMode: true
};
