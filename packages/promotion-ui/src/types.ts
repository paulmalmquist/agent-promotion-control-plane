import type { CSSProperties, ReactNode } from "react";

export type LifecycleStage =
  | "DISCOVERED"
  | "CANDIDATE"
  | "EVALUATING"
  | "ELIGIBLE"
  | "SHADOW"
  | "PROMOTED"
  | "MONITORED"
  | (string & {});

export type CandidateStatus =
  | "ACTIVE"
  | "BLOCKED"
  | "PROMOTION_PENDING"
  | "REJECTED"
  | "SUSPENDED"
  | "RETIRED";

export type RegistryActivationState =
  | "NOT_REQUESTED"
  | "PENDING"
  | "SUCCEEDED"
  | "FAILED";

export type GateVerdict = "PASSED" | "FAILED" | "REMAINING" | "NOT_APPLICABLE";

export interface GateViewModel {
  id: string;
  name: string;
  category: string;
  kind: "HARD_GATE" | "WEIGHTED";
  weight: number | null;
  verdict: GateVerdict;
  score: number | null;
  normalizedScore: number | null;
  measurementValue: number | null;
  measurementUnit: string | null;
  comparisonOperator: string;
  threshold: number | null;
  samples: number;
  minimumSamples: number;
  evidenceCount: number;
  requiredEvidenceCount: number;
  evaluator: string;
  lastRunAt: string | null;
  meaning: string;
}

export interface EvaluationSummaryViewModel {
  readinessPercentage: number;
  hardGateReadiness: number;
  weightedReadiness: number;
  sampleCompleteness: number;
  evaluationCompleteness: number;
  weightedScore: number | null;
  requiredWeightedScore: number;
  validResultCount: number;
  requiredResultCount: number;
}

export interface TimelineEventViewModel {
  id: string;
  sequence: number;
  eventType: string;
  occurredAt: string;
  actor: string;
  headline: string;
  detail: string;
  correlationId?: string;
  causationId?: string;
}

export interface EvidenceViewModel {
  id: string;
  kind: "ARTIFACT" | "DETECTOR_SIGNAL";
  title: string;
  source: string;
  recordedAt: string;
  digest: string | null;
  uri: string | null;
  summary: string;
  signalType: string;
}

export interface BlockerViewModel {
  id: string;
  code: string;
  category: string;
  title: string;
  explanation: string;
  recovery: string;
  details: Record<string, unknown>;
}

export interface DecisionViewModel {
  type: string;
  outcome: string;
  rationale: string;
  actor: string;
  decidedAt: string;
  policyHash: string;
  evaluationSnapshotHash: string;
}

export interface CandidateViewModel {
  id: string;
  slug: string;
  name: string;
  component: string;
  candidateType: string;
  discoverySource: string;
  description: string;
  surfacedReason: string;
  detectorLineage: string;
  stage: LifecycleStage;
  status: CandidateStatus;
  revision: number;
  policyName: string;
  policyId: string | null;
  policyKey: string | null;
  policyHash: string;
  evaluationSnapshotHash: string;
  evaluation: EvaluationSummaryViewModel;
  promotionEligible: boolean;
  lifecycleApprovalState: "NOT_REQUIRED" | "REQUIRED" | "APPROVED" | "CONSUMED";
  requiredLifecycleApprovals: number;
  availableLifecycleApprovals: number;
  consumedLifecycleApprovals: number;
  activeBlockerCount: number;
  activationState: RegistryActivationState;
  blockerCode: string | null;
  blockerSummary: string | null;
  blockers: BlockerViewModel[];
  latestDecision: DecisionViewModel | null;
  registryOperationId: string | null;
  updatedAt: string;
  latestEvaluationAt: string | null;
  hardGatesPassed: number | null;
  hardGatesRequired: number | null;
  journey: LifecycleStage[];
  gates: GateViewModel[];
  evidence: EvidenceViewModel[];
  timeline: TimelineEventViewModel[];
}

export interface EvaluationRunViewModel {
  id: string;
  candidateId: string;
  candidateName: string;
  planId: string;
  planName: string;
  state: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progressPercentage: number;
  startedAt: string | null;
  finishedAt: string | null;
  provider: string;
  model: string | null;
  attemptCount: number;
  maxAttempts: number;
  plannedResultCount: number;
  heartbeatAt: string | null;
  correlationId: string | null;
  resultCount: number | null;
  sampleCount: number | null;
  durationMilliseconds: number | null;
  latencyMilliseconds: number | null;
  costUsd: number | null;
  errorMessage: string | null;
  results: EvaluationMeasurementViewModel[];
  artifacts: EvidenceViewModel[];
}

export interface EvaluationMeasurementViewModel extends GateViewModel {
  provider: string | null;
  model: string | null;
  costUsd: number | null;
  latencyMilliseconds: number | null;
  valid: boolean | null;
  stale: boolean | null;
}

export interface PolicyCriterionViewModel {
  id: string;
  version: string;
  name: string;
  description: string | null;
  proofMeaning: string | null;
  contentHash: string | null;
  category: string;
  kind: "HARD_GATE" | "WEIGHTED";
  evaluatorType: string | null;
  evaluator: string;
  comparisonOperator: string;
  measurementUnit: string | null;
  threshold: number;
  weight: number | null;
  minimumSamples: number;
  evidenceRequirements: string[];
  aggregation: string;
}

export interface PolicyViewModel {
  id: string;
  key: string;
  name: string;
  version: string;
  hash: string;
  minimumWeightedScore: number;
  lifecycleStages: LifecycleStage[];
  requiredLifecycleApprovals: number;
  criteria: PolicyCriterionViewModel[];
}

export type ScheduleConnectionState = "CONNECTED" | "DISCONNECTED" | "DEGRADED";

export interface ScheduledRunViewModel {
  id: string;
  state: string;
  triggeredBy: string;
  triggerSource: string;
  observedAt: string;
  attemptCount: number;
  correlationId: string | null;
}

export interface ScheduledJobViewModel {
  id: string;
  key: string;
  name: string;
  description: string;
  jobType: string;
  enabled: boolean | null;
  triggerOwner: string;
  triggerMode: string;
  ownerReference: string;
  connectionState: ScheduleConnectionState;
  connectionMessage: string;
  timezone: string;
  scheduleExpression: string;
  lastObservedRunAt: string | null;
  nextExpectedTriggerAt: string | null;
  graceWindowMinutes: number;
  lastRunState: "SUCCEEDED" | "FAILED" | "RUNNING" | "NEVER" | null;
  runCount: number | null;
  failureCount: number | null;
  currentActivity: string | null;
  lastDurationSeconds: number | null;
  recentRuns: ScheduledRunViewModel[];
}

export interface RegistryAgentViewModel {
  id: string;
  agentId: string | null;
  registryKey: string | null;
  externalVersionId: string | null;
  name: string;
  candidateId: string;
  version: number;
  publicationToken: string | null;
  promotedAt: string;
  state: "ACTIVE" | "SUSPENDED" | "RETIRED" | null;
  candidateStage: string | null;
  candidateStatus: string | null;
  active: boolean | null;
  isActiveVersion: boolean | null;
  policyHash: string;
  evaluationSnapshotHash: string;
  health: string | null;
  monitoringState: string | null;
  monitoringRunCount: number | null;
  recentMonitoringEvents: TimelineEventViewModel[];
}

export interface DashboardViewModel {
  generatedAt: string;
  candidates: CandidateViewModel[];
  evaluations: EvaluationRunViewModel[];
  policies: PolicyViewModel[];
  schedules: ScheduledJobViewModel[];
  registryAgents: RegistryAgentViewModel[];
  recentEvents: TimelineEventViewModel[];
  liveConnected: boolean;
  demoMode: boolean;
}

export interface PromotionEventEnvelope {
  id: string;
  sequence: number;
  schemaVersion: number;
  eventType: string;
  occurredAt: string;
  actor: string;
  candidateId: string | null;
  evaluationRunId: string | null;
  scheduleRunId: string | null;
  registryOperationId: string | null;
  correlationId: string;
  causationId: string | null;
  policyHash?: string | null;
  payload: Record<string, unknown>;
}

export interface PromotionQuery {
  resource:
    | "dashboard"
    | "candidate"
    | "evaluation"
    | "events"
    | "policies"
    | "schedules"
    | "registry";
  id?: string;
  cursor?: string;
}

export interface PromotionMutation {
  resource: "promotion" | "promotion-retry" | "evaluation" | "schedule" | "demo-cycle";
  id: string;
  expectedCandidateRevision?: number;
  body?: Record<string, unknown>;
  idempotencyKey: string;
}

export type GovernedMutationCallback = (
  mutation: PromotionMutation
) => Promise<LifecycleDecisionResult>;

export interface PromotionDataSource {
  query<T>(query: PromotionQuery): Promise<T>;
  mutate<T>(mutation: PromotionMutation): Promise<T>;
  subscribe(
    listener: (event: PromotionEventEnvelope) => void,
    options?: {
      candidateId?: string;
      lastEventId?: string;
      onConnectionChange?: (connected: boolean) => void;
    }
  ): () => void;
}

export interface LifecycleDecisionRequest {
  candidate: CandidateViewModel;
  targetStage: "PROMOTED";
  policyHash: string;
  evaluationSnapshotHash: string;
  rationale: string;
  expectedCandidateRevision: number;
}

export interface LifecycleDecisionResult {
  accepted: boolean;
  operationId?: string;
  candidateRevision?: number;
  message: string;
}

export interface PromotionThemeTokens {
  background: string;
  surface: string;
  surfaceRaised: string;
  text: string;
  textMuted: string;
  line: string;
  lineStrong: string;
  decision: string;
  comparison: string;
  degraded: string;
  stop: string;
  focus: string;
  fontSans: string;
  fontMono: string;
  radiusSmall: string;
  radiusLarge: string;
}

export interface PromotionShellProps {
  initialData: DashboardViewModel;
  currentPath?: string;
  dataSource?: PromotionDataSource;
  navigate?: (path: string) => void;
  onLifecycleDecision?: (
    request: LifecycleDecisionRequest
  ) => Promise<LifecycleDecisionResult>;
  onGovernedMutation?: GovernedMutationCallback;
  onMaterialEvent?: (event: PromotionEventEnvelope) => void | Promise<void>;
  tokens?: Partial<PromotionThemeTokens>;
  embedded?: boolean;
  evidenceLink?: (candidateId: string) => string;
  attentionLink?: string;
  headerSlot?: ReactNode;
  className?: string;
  style?: CSSProperties;
}
