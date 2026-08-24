import type {
  CandidateViewModel,
  DashboardViewModel,
  EvaluationMeasurementViewModel,
  EvaluationRunViewModel,
  GateViewModel,
  PolicyViewModel,
  RegistryAgentViewModel,
  ScheduledJobViewModel,
  TimelineEventViewModel
} from "@promotion-control-plane/ui";
import { promotionEventCopy } from "@promotion-control-plane/ui";
import type { paths } from "@/generated/api";
import { fixtureDashboard } from "./fixture-dashboard";

const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

type JsonRecord = Record<string, unknown>;
type GetResponse<Path extends keyof paths> = paths[Path] extends {
  get: { responses: { 200: { content: { "application/json": infer Response } } } };
} ? Response : never;

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function records(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function items(value: unknown): JsonRecord[] {
  const body = record(value);
  return records(body.items ?? body.results ?? value);
}

function string(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function number(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = typeof value === "string" ? Number(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function ratio(value: unknown, fallback = 1): number {
  const parsed = number(value, fallback);
  return parsed > 1 ? parsed / 100 : parsed;
}

function boolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

async function getJson<Response>(path: string, required = true): Promise<Response> {
  const response = await fetch(`${API_INTERNAL_URL}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    if (!required && response.status === 404) return { items: [] } as Response;
    throw new Error(`FastAPI returned ${response.status} for ${path}.`);
  }
  return response.json() as Promise<Response>;
}

function mapEvent(value: unknown): TimelineEventViewModel {
  const source = record(value);
  const payload = record(source.payload);
  const eventType = string(source.event_type ?? source.type, "CONTROL_PLANE_EVENT");
  const copy = promotionEventCopy(eventType, payload);
  return {
    id: string(source.id, `event-${number(source.sequence)}`),
    sequence: number(source.sequence),
    eventType,
    occurredAt: string(source.occurred_at ?? source.created_at, new Date(0).toISOString()),
    actor: string(source.actor ?? source.actor_id, "system"),
    headline: string(source.headline, copy.headline),
    detail: string(source.detail, copy.detail),
    correlationId: string(source.correlation_id),
    causationId: nullableString(source.causation_id) ?? undefined
  };
}

function mapGate(value: unknown): GateViewModel {
  const source = record(value);
  const criterion = record(source.criterion);
  const providerMetadata = record(source.provider_metadata);
  const verdict = string(source.verdict ?? source.gate_verdict, "REMAINING");
  const kind = string(
    source.kind ?? criterion.kind,
    (source.hard_gate ?? criterion.hard_gate) === false ? "WEIGHTED" : "HARD_GATE"
  );
  const evidenceCodes = Array.isArray(source.evidence_codes) ? source.evidence_codes : [];
  const requiredEvidence = Array.isArray(criterion.required_evidence) ? criterion.required_evidence : [];
  const normalizedScore = source.normalized_score === null || source.normalized_score === undefined
    ? source.score === null || source.score === undefined ? null : number(source.score)
    : number(source.normalized_score);
  const measurementValue = source.measurement_value === null || source.measurement_value === undefined
    ? null
    : number(source.measurement_value);
  const weight = source.weight === null || source.weight === undefined
    ? criterion.weight === null || criterion.weight === undefined ? null : number(criterion.weight)
    : number(source.weight);
  return {
    id: string(source.id ?? criterion.id, globalThis.crypto.randomUUID()),
    name: string(source.name ?? criterion.name, "Unnamed criterion"),
    category: string(source.category ?? criterion.category, "GENERAL"),
    kind: kind === "WEIGHTED" ? "WEIGHTED" : "HARD_GATE",
    weight,
    verdict: verdict === "PASSED" || verdict === "FAILED" || verdict === "NOT_APPLICABLE"
      ? verdict
      : "REMAINING",
    score: normalizedScore,
    normalizedScore,
    measurementValue,
    measurementUnit: nullableString(source.measurement_unit ?? source.unit),
    comparisonOperator: string(source.comparison_operator ?? criterion.comparison_operator, "gte"),
    threshold: (source.threshold ?? criterion.threshold) === null
      || (source.threshold ?? criterion.threshold) === undefined
      ? null
      : number(source.threshold ?? criterion.threshold),
    samples: number(source.samples ?? source.sample_count),
    minimumSamples: number(source.minimum_samples ?? criterion.minimum_samples),
    evidenceCount: number(source.evidence_count, evidenceCodes.length),
    requiredEvidenceCount: number(
      source.required_evidence_count,
      Array.isArray(criterion.evidence_requirements) ? criterion.evidence_requirements.length : requiredEvidence.length
    ),
    evaluator: [
      string(source.evaluator ?? source.evaluator_key ?? source.provider ?? providerMetadata.provider),
      string(source.evaluator_version)
    ].filter(Boolean).join(" · ") || "Evaluator unavailable",
    lastRunAt: nullableString(source.last_run_at ?? source.completed_at ?? source.recorded_at),
    meaning: string(source.meaning ?? criterion.description, "Central gate verdict from typed measurements.")
  };
}

export function normalizeCandidate(value: unknown, linkedEvents: TimelineEventViewModel[] = []): CandidateViewModel {
  const source = record(value);
  const readiness = record(source.readiness ?? source.evaluation);
  const id = string(source.id, `candidate-${string(source.slug, "unknown")}`);
  const blockerList = records(source.blockers ?? source.active_blockers);
  const primaryBlocker = blockerList.find((item) => string(item.state, "ACTIVE") === "ACTIVE") ?? blockerList[0];
  const blocker = record(primaryBlocker);
  const decision = record(
    source.latest_eligibility_decision
    ?? source.latest_decision
    ?? records(source.decisions)[0]
  );
  const blockers = blockerList.map((item, index) => ({
    id: string(item.id, `${id}-blocker-${index}`),
    code: string(item.code, "PROMOTION_BLOCKED"),
    category: string(item.category, "EVIDENCE"),
    title: string(item.title ?? item.summary, "A promotion condition remains unresolved"),
    explanation: string(item.explanation ?? item.message, "The active policy requirement is not satisfied."),
    recovery: string(item.recovery, "Review the requirement, then rerun the active evaluation plan."),
    details: record(item.details)
  }));
  const stage = string(source.lifecycle_stage ?? source.stage, "DISCOVERED");
  const status = string(source.status, "ACTIVE");
  const registryOperation = record(source.registry_operation);
  const promotionEligibility = record(source.promotion_eligibility);
  const activationState = string(
    promotionEligibility.registry_activation_state
    ?? readiness.registry_activation_state
    ?? source.registry_activation_state
    ?? registryOperation.activation_state,
    "NOT_REQUESTED"
  );
  const policy = record(source.policy);
  const policyHash = string(source.policy_hash ?? policy.hash, "unassigned-policy");
  const evidenceSnapshotHash = string(source.evaluation_snapshot_hash ?? source.evidence_snapshot_hash, "unavailable-snapshot");
  const rawApprovalState = string(
    promotionEligibility.lifecycle_approval_state ?? source.lifecycle_approval_state,
    "NOT_REQUIRED"
  );
  const lifecycleApprovalState = rawApprovalState === "SATISFIED"
    ? "APPROVED"
    : rawApprovalState === "LOCKED"
      ? "CONSUMED"
      : rawApprovalState;
  const explicitResults = records(source.gates ?? source.results ?? source.criteria_results ?? source.gate_results);
  const verdicts = record(readiness.gate_verdicts);
  const results = explicitResults.length > 0
    ? explicitResults
    : Object.entries(verdicts).map(([code, verdict]) => ({
        id: code,
        name: code.toLowerCase().replaceAll("_", " ").replaceAll("-", " "),
        kind: "HARD_GATE",
        verdict,
        meaning: "The central gate engine evaluated this required criterion."
      }));
  const artifactEvidence = records(source.evidence_artifacts ?? source.artifacts ?? source.evidence);
  const detectorEvidence = records(source.detector_evidence);
  const detectorLineage = record(source.detector_lineage);
  const timeline = records(source.timeline ?? source.events).map(mapEvent);
  const journey = records(source.lifecycle_stages).map((item) => string(item.name)).filter(Boolean);
  const fallbackJourney = ["DISCOVERED", "CANDIDATE", "EVALUATING", "ELIGIBLE", "SHADOW", "PROMOTED", "MONITORED"];
  const readinessPercentage = number(
    readiness.evaluation_readiness ?? readiness.readiness_percentage ?? source.evaluation_readiness ?? source.readiness_percentage
  );
  const gates = results.map(mapGate);
  const computedHardGates = gates.filter((gate) => gate.kind === "HARD_GATE");
  const weightedScore = readiness.weighted_score ?? source.weighted_score;

  return {
    id,
    slug: string(source.slug, id),
    name: string(source.name ?? source.display_name, "Unnamed candidate"),
    component: string(source.component ?? source.component_name ?? source.source_component ?? source.candidate_type, "AGENT"),
    candidateType: string(source.candidate_type, "AGENT"),
    discoverySource: string(source.discovery_source ?? source.discovered_by, "Deterministic detector"),
    description: string(source.description ?? source.summary, "No candidate description is available."),
    surfacedReason: string(
      source.surfaced_reason ?? source.discovery_reason ?? source.rationale ?? source.proposed_capability,
      "A deterministic detector surfaced this candidate for review."
    ),
    detectorLineage: string(
      source.detector_revision ?? detectorLineage.revision_id,
      source.detector_key
        ? `${string(source.detector_key)} / revision ${string(source.detector_version, "1")}`
        : [
            string(detectorLineage.discovered_by ?? source.discovered_by),
            string(detectorLineage.revision_id)
          ].filter(Boolean).join(" / revision ")
          || string(source.discovery_source, "Deterministic detector / revision unavailable")
    ),
    stage,
    status: status as CandidateViewModel["status"],
    revision: number(source.revision ?? source.candidate_revision, 1),
    policyName: string(source.policy_name ?? policy.name, source.current_policy_version ? `Policy version ${string(source.current_policy_version)}` : "Unassigned policy"),
    policyId: nullableString(source.active_policy_id ?? source.policy_id ?? policy.id),
    policyKey: nullableString(source.current_policy_key ?? source.policy_key ?? policy.key),
    policyHash,
    evaluationSnapshotHash: evidenceSnapshotHash,
    evaluation: {
      readinessPercentage,
      hardGateReadiness: ratio(readiness.hard_gate_readiness ?? source.hard_gate_readiness, 0),
      weightedReadiness: ratio(readiness.weighted_readiness ?? source.weighted_readiness, 0),
      sampleCompleteness: ratio(readiness.sample_completeness ?? source.sample_completeness, 0),
      evaluationCompleteness: ratio(readiness.evaluation_completeness ?? source.evaluation_completeness, 0),
      weightedScore: weightedScore === null || weightedScore === undefined
        ? null
        : number(weightedScore),
      requiredWeightedScore: number(readiness.required_weighted_score ?? readiness.minimum_weighted_score ?? source.required_weighted_score),
      validResultCount: number(readiness.valid_result_count ?? results.length),
      requiredResultCount: number(
        readiness.required_criterion_count ?? readiness.required_result_count ?? results.length
      )
    },
    promotionEligible: boolean(
      promotionEligibility.eligible ?? source.promotion_eligible ?? readiness.promotion_eligible
    ),
    lifecycleApprovalState: lifecycleApprovalState as CandidateViewModel["lifecycleApprovalState"],
    requiredLifecycleApprovals: number(promotionEligibility.required_lifecycle_approvals),
    availableLifecycleApprovals: number(promotionEligibility.available_lifecycle_approvals),
    consumedLifecycleApprovals: number(promotionEligibility.consumed_lifecycle_approvals),
    activeBlockerCount: number(promotionEligibility.active_blocker_count, blockerList.length),
    activationState: activationState as CandidateViewModel["activationState"],
    blockerCode: nullableString(source.blocker_code ?? blocker.code),
    blockerSummary: nullableString(source.blocker_summary ?? blocker.summary ?? blocker.message ?? blocker.title ?? blocker.explanation),
    blockers,
    latestDecision: Object.keys(decision).length === 0 ? null : {
      type: string(decision.decision_type ?? decision.type, "LIFECYCLE"),
      outcome: string(decision.outcome, "UNKNOWN"),
      rationale: string(decision.rationale, "No decision rationale is available."),
      actor: string(decision.actor, "unknown actor"),
      decidedAt: string(decision.decided_at ?? decision.created_at, new Date(0).toISOString()),
      policyHash: string(decision.policy_hash, policyHash),
      evaluationSnapshotHash: string(decision.evaluation_snapshot_hash, evidenceSnapshotHash)
    },
    registryOperationId: nullableString(source.registry_operation_id ?? registryOperation.id),
    updatedAt: string(source.updated_at ?? source.created_at, new Date(0).toISOString()),
    latestEvaluationAt: nullableString(source.latest_evaluation_at ?? source.latest_evaluation_completed_at),
    hardGatesPassed: source.hard_gates_passed === null || source.hard_gates_passed === undefined
      ? computedHardGates.length > 0 ? computedHardGates.filter((gate) => gate.verdict === "PASSED").length : null
      : number(source.hard_gates_passed),
    hardGatesRequired: source.hard_gates_required === null || source.hard_gates_required === undefined
      ? computedHardGates.length > 0 ? computedHardGates.length : null
      : number(source.hard_gates_required),
    journey: (journey.length > 0 ? journey : fallbackJourney) as CandidateViewModel["journey"],
    gates,
    evidence: [
      ...artifactEvidence.map((entry, index) => {
      const details = record(entry.evidence);
      const providerMetadata = record(entry.provider_metadata);
      return {
      id: string(entry.id, `${id}-evidence-${index}`),
      kind: "ARTIFACT" as const,
      title: string(
        entry.title ?? entry.name,
        `${string(entry.artifact_type ?? entry.signal_type, "Evaluation")} artifact`
      ),
      source: string(
        entry.source ?? entry.provider ?? providerMetadata.provider ?? details.source,
        "Artifact store"
      ),
      recordedAt: string(entry.recorded_at ?? entry.created_at, new Date(0).toISOString()),
      digest: nullableString(entry.digest ?? entry.sha256 ?? details.digest),
      uri: nullableString(entry.uri ?? entry.artifact_uri ?? details.uri),
      summary: string(
        entry.summary ?? entry.description ?? details.summary,
        Object.entries(details).map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`).join(" · ") || "Persisted evidence linked to this candidate."
      ),
      signalType: string(entry.artifact_type ?? entry.signal_type ?? entry.type, "EVIDENCE ARTIFACT")
    };}),
      ...detectorEvidence.map((entry, index) => {
        const details = record(entry.evidence);
        return {
          id: string(entry.id, `${id}-signal-${index}`),
          kind: "DETECTOR_SIGNAL" as const,
          title: string(entry.title ?? entry.name, `${string(entry.signal_type, "Detector")} signal`),
          source: string(entry.source ?? entry.provider ?? details.source, "deterministic detector"),
          recordedAt: string(entry.recorded_at ?? entry.created_at, new Date(0).toISOString()),
          digest: null,
          uri: null,
          summary: string(
            entry.summary ?? entry.description ?? details.summary,
            Object.entries(details).map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`).join(" · ") || "Persisted deterministic signal."
          ),
          signalType: string(entry.signal_type ?? entry.type, "DETECTOR SIGNAL")
        };
      })
    ],
    timeline: [...timeline, ...linkedEvents].sort((left, right) => right.sequence - left.sequence)
  };
}

function mapEvaluationMeasurement(value: unknown): EvaluationMeasurementViewModel {
  const source = record(value);
  return {
    ...mapGate(source),
    provider: nullableString(source.provider),
    model: nullableString(source.model),
    costUsd: source.cost_usd === null || source.cost_usd === undefined
      ? null
      : number(source.cost_usd),
    latencyMilliseconds: source.latency_ms === null || source.latency_ms === undefined
      ? null
      : number(source.latency_ms),
    valid: typeof source.valid === "boolean" ? source.valid : null,
    stale: typeof source.stale === "boolean" ? source.stale : null
  };
}

export function mapEvaluation(value: unknown, candidateNames: Map<string, string>): EvaluationRunViewModel {
  const source = record(value);
  const candidateId = string(source.candidate_id);
  const rawResults = records(source.results ?? source.measurements);
  const rawArtifacts = records(source.evidence_artifacts ?? source.artifacts);
  const providerNames = Array.isArray(source.provider_names)
    ? source.provider_names.map((provider) => string(provider)).filter(Boolean)
    : [];
  const resultModels = [...new Set(rawResults.map((result) => string(result.model)).filter(Boolean))];
  const error = record(source.error);
  const startedAt = nullableString(source.started_at);
  const finishedAt = nullableString(source.finished_at ?? source.completed_at);
  const computedDuration = startedAt && finishedAt
    ? Math.max(0, new Date(finishedAt).valueOf() - new Date(startedAt).valueOf())
    : null;
  return {
    id: string(source.id, `evaluation-${candidateId || "unknown"}`),
    candidateId,
    candidateName: string(source.candidate_name, candidateNames.get(candidateId) ?? "Unknown candidate"),
    planId: string(source.plan_id),
    planName: string(source.plan_name ?? source.name, "Active evaluation plan"),
    state: string(source.state ?? source.status, "QUEUED") as EvaluationRunViewModel["state"],
    progressPercentage: number(source.progress_percentage, string(source.state ?? source.status) === "SUCCEEDED" ? 100 : 0),
    startedAt,
    finishedAt,
    provider: string(
      source.provider ?? source.evaluator_provider,
      providerNames.join(", ") || "Provider not reported"
    ),
    model: nullableString(source.model ?? source.model_name) ?? (resultModels.length > 0 ? resultModels.join(", ") : null),
    attemptCount: number(source.attempt_count),
    maxAttempts: number(source.max_attempts),
    plannedResultCount: number(source.planned_result_count),
    heartbeatAt: nullableString(source.heartbeat_at),
    correlationId: nullableString(source.correlation_id),
    resultCount: source.result_count === null || source.result_count === undefined
      ? rawResults.length > 0 ? rawResults.length : null
      : number(source.result_count),
    sampleCount: source.sample_count === null || source.sample_count === undefined
      ? rawResults.length > 0
        ? rawResults.reduce((total, result) => total + number(result.sample_count), 0)
        : null
      : number(source.sample_count),
    durationMilliseconds: (source.duration_ms ?? source.duration_milliseconds) === undefined
      ? computedDuration
      : number(source.duration_ms ?? source.duration_milliseconds),
    latencyMilliseconds: (source.latency_ms ?? source.latency_milliseconds) === undefined
      ? null
      : number(source.latency_ms ?? source.latency_milliseconds),
    costUsd: source.cost_usd === null || source.cost_usd === undefined ? null : number(source.cost_usd),
    errorMessage: nullableString(source.error_message)
      ?? nullableString(error.message ?? error.detail ?? error.code)
      ?? (Object.keys(error).length > 0 ? JSON.stringify(error) : null),
    results: rawResults.map(mapEvaluationMeasurement),
    artifacts: rawArtifacts.map((artifact, index) => ({
      id: string(artifact.id, `${string(source.id)}-artifact-${index}`),
      kind: "ARTIFACT" as const,
      title: string(artifact.title ?? artifact.name, "Evaluation evidence artifact"),
      source: string(
        artifact.source ?? artifact.provider ?? record(artifact.provider_metadata).provider,
        "Artifact store"
      ),
      recordedAt: string(artifact.recorded_at ?? artifact.created_at, finishedAt ?? new Date(0).toISOString()),
      digest: nullableString(artifact.sha256 ?? artifact.digest),
      uri: nullableString(artifact.uri ?? artifact.artifact_uri),
      summary: string(
        artifact.summary ?? artifact.description,
        `${string(artifact.media_type, "Stored output")} · ${artifact.sanitized === true ? "sanitized" : "original"}`
      ),
      signalType: string(artifact.artifact_type ?? artifact.type, "EVALUATION ARTIFACT")
    }))
  };
}

export function mapPolicy(value: unknown): PolicyViewModel {
  const source = record(value);
  const stages = records(source.lifecycle_stages).map((stage) => string(stage.name)).filter(Boolean);
  const rawStages = Array.isArray(source.lifecycle_stages) ? source.lifecycle_stages.filter((stage): stage is string => typeof stage === "string") : [];
  return {
    id: string(source.id, `policy-${string(source.key, "unknown")}-${string(source.version, "unversioned")}`),
    key: string(source.key ?? source.policy_key, "unknown-policy"),
    name: string(source.name, "Promotion policy"),
    version: string(source.version, "unversioned"),
    hash: string(source.hash ?? source.content_hash, "policy-hash-unavailable"),
    minimumWeightedScore: number(source.minimum_weighted_score),
    lifecycleStages: (rawStages.length > 0 ? rawStages : stages) as PolicyViewModel["lifecycleStages"],
    requiredLifecycleApprovals: number(source.required_lifecycle_approvals),
    criteria: records(source.criteria).map((entry, index) => {
      const rawRequirements = entry.evidence_requirements ?? entry.required_evidence;
      const evidenceRequirements = Array.isArray(rawRequirements)
        ? rawRequirements.map((item: unknown) => string(item)).filter(Boolean)
        : [];
      return {
        id: string(entry.id, `criterion-${index}`),
        version: string(entry.version, "unversioned"),
        name: string(entry.name, "Unnamed criterion"),
        description: nullableString(entry.description),
        proofMeaning: nullableString(entry.proof_meaning),
        contentHash: nullableString(entry.content_hash ?? entry.hash),
        category: string(entry.category, "GENERAL"),
        kind: string(entry.kind) === "WEIGHTED" || entry.hard_gate === false ? "WEIGHTED" : "HARD_GATE",
        evaluatorType: nullableString(entry.evaluator_type),
        evaluator: [
          string(entry.evaluator ?? entry.evaluator_key ?? entry.evaluator_type ?? entry.evaluator_revision),
          string(entry.evaluator_version)
        ].filter(Boolean).join(" · ") || "Evaluator not reported",
        comparisonOperator: string(entry.comparison_operator, "gte"),
        measurementUnit: nullableString(entry.measurement_unit ?? entry.unit ?? entry.measurement_type),
        threshold: number(entry.threshold),
        weight: entry.weight === null || entry.weight === undefined ? null : number(entry.weight),
        minimumSamples: number(entry.minimum_samples),
        evidenceRequirements,
        aggregation: string(entry.aggregation ?? entry.aggregation_rule, "Not reported")
      };
    })
  };
}

export function mapSchedule(value: unknown): ScheduledJobViewModel {
  const source = record(value);
  const recentRuns = records(source.history ?? source.recent_runs ?? source.runs ?? source.run_history);
  return {
    id: string(source.id, `schedule-${string(source.key, "unknown")}`),
    key: string(source.key, "unknown-schedule"),
    name: string(source.name ?? source.key, "Observed job"),
    description: string(source.description, "External automation dispatches this job."),
    jobType: string(source.job_type, "Not reported"),
    enabled: typeof source.enabled === "boolean" ? source.enabled : null,
    triggerOwner: string(source.trigger_owner, "Unassigned owner"),
    triggerMode: string(source.trigger_mode, "EXTERNAL"),
    ownerReference: string(source.owner_reference, "Not connected"),
    connectionState: string(source.connection_state, "DISCONNECTED") as ScheduledJobViewModel["connectionState"],
    connectionMessage: string(source.connection_message, "This job will not run automatically until its named owner reconnects."),
    timezone: string(source.timezone, "UTC"),
    scheduleExpression: string(source.schedule_expression, "External trigger"),
    lastObservedRunAt: nullableString(source.last_observed_run_at),
    nextExpectedTriggerAt: nullableString(source.next_expected_trigger_at),
    graceWindowMinutes: Math.round(number(source.grace_window_minutes, number(source.grace_window_seconds) / 60)),
    lastRunState: (source.last_run_status ?? source.last_run_state) === null
      || (source.last_run_status ?? source.last_run_state) === undefined
      ? null
      : string(source.last_run_status ?? source.last_run_state) as ScheduledJobViewModel["lastRunState"],
    runCount: source.run_count === null || source.run_count === undefined ? null : number(source.run_count),
    failureCount: source.failure_count === null || source.failure_count === undefined
      ? null
      : number(source.failure_count),
    currentActivity: nullableString(source.current_activity),
    lastDurationSeconds: source.last_duration_seconds === null || source.last_duration_seconds === undefined
      ? null
      : number(source.last_duration_seconds),
    recentRuns: recentRuns.map((run, index) => ({
      id: string(run.id, `${string(source.id)}-run-${index}`),
      state: string(run.state ?? run.status, "UNKNOWN"),
      triggeredBy: string(run.triggered_by ?? run.actor, "Trigger owner not reported"),
      triggerSource: string(run.trigger_source, "Source not reported"),
      observedAt: string(run.observed_at ?? run.completed_at ?? run.started_at, new Date(0).toISOString()),
      attemptCount: number(run.attempt_count),
      correlationId: nullableString(run.correlation_id)
    }))
  };
}

export function mapRegistry(value: unknown): RegistryAgentViewModel {
  const source = record(value);
  return {
    id: string(source.id, `agent-version-${string(source.candidate_id, "unknown")}-${number(source.version, 1)}`),
    agentId: nullableString(source.agent_id),
    registryKey: nullableString(source.registry_key),
    externalVersionId: nullableString(source.external_version_id),
    name: string(
      source.display_name ?? source.candidate_name ?? source.name ?? source.agent_name ?? source.external_version_id,
      `Promoted agent version ${number(source.version, 1)}`
    ),
    candidateId: string(source.candidate_id),
    version: number(source.version, 1),
    publicationToken: nullableString(source.publication_token),
    promotedAt: string(source.promoted_at ?? source.created_at, new Date(0).toISOString()),
    state: nullableString(source.status ?? source.state) as RegistryAgentViewModel["state"],
    candidateStage: nullableString(source.stage),
    candidateStatus: nullableString(source.status),
    active: typeof source.active === "boolean" ? source.active : null,
    isActiveVersion: typeof source.is_active_version === "boolean" ? source.is_active_version : null,
    policyHash: string(source.policy_hash, "policy-hash-unavailable"),
    evaluationSnapshotHash: string(source.evaluation_snapshot_hash, "evaluation-snapshot-unavailable"),
    health: nullableString(source.health ?? source.current_health),
    monitoringState: nullableString(source.monitoring_state),
    monitoringRunCount: source.monitoring_run_count === null || source.monitoring_run_count === undefined
      ? null
      : number(source.monitoring_run_count),
    recentMonitoringEvents: records(source.recent_monitoring_events).map(mapEvent)
  };
}

export async function loadDashboard(
  detailCandidateId?: string,
  detailEvaluationId?: string,
  detailRegistryAgentId?: string
): Promise<DashboardViewModel> {
  try {
    const [dashboardBody, candidatesBody, schedulesBody, eventsBody, registryBody, evaluationsBody, policiesBody, criteriaBody] = await Promise.all([
      getJson<GetResponse<"/api/v1/dashboard">>("/api/v1/dashboard"),
      getJson<GetResponse<"/api/v1/candidates">>("/api/v1/candidates"),
      getJson<GetResponse<"/api/v1/schedules">>("/api/v1/schedules"),
      getJson<GetResponse<"/api/v1/events">>("/api/v1/events?limit=80"),
      getJson<GetResponse<"/api/v1/registry/agents">>("/api/v1/registry/agents", false),
      getJson<GetResponse<"/api/v1/evaluations">>("/api/v1/evaluations", false),
      getJson<GetResponse<"/api/v1/policies">>("/api/v1/policies", false),
      getJson<GetResponse<"/api/v1/criteria">>("/api/v1/criteria", false)
    ]);
    const dashboard = record(dashboardBody);
    const rawEvents = items(eventsBody).length > 0 ? items(eventsBody) : records(dashboard.recent_events);
    const events = rawEvents.map(mapEvent);
    const eventCandidates = new Map<string, TimelineEventViewModel[]>();
    rawEvents.forEach((raw, index) => {
      const candidateId = string(record(raw).candidate_id);
      if (!candidateId) return;
      const existing = eventCandidates.get(candidateId) ?? [];
      existing.push(events[index]!);
      eventCandidates.set(candidateId, existing);
    });
    const rawCriteria = items(criteriaBody);
    const policies = items(policiesBody).map((policy) => {
      const policyId = string(policy.id);
      const matchingCriteria = rawCriteria.filter((criterion) => string(criterion.policy_id) === policyId);
      return mapPolicy({
        ...policy,
        criteria: matchingCriteria.length > 0 ? matchingCriteria : records(policy.criteria)
      });
    });
    let rawCandidates = items(candidatesBody);
    if (detailCandidateId) {
      const detail = await getJson<GetResponse<"/api/v1/candidates/{candidate_id}">>(`/api/v1/candidates/${encodeURIComponent(detailCandidateId)}`, false);
      if (Object.keys(record(detail)).length > 0) {
        let detailed = record(detail);
        const detailId = string(detailed.id, detailCandidateId);
        detailed = {
          ...detailed,
          gates: records(detailed.gates).map((gate) => {
            const criterion = rawCriteria.find((item) => string(item.id) === string(gate.criterion_id));
            const evidenceRequirements = Array.isArray(criterion?.required_evidence)
              ? criterion.required_evidence
              : [];
            return {
              ...gate,
              criterion,
              required_evidence_count: evidenceRequirements.length,
              meaning: criterion?.description
            };
          })
        };
        const candidateRuns = items(evaluationsBody).filter((run) => string(run.candidate_id) === detailId);
        const latestRun = candidateRuns[0];
        if (latestRun) {
          const runDetail = record(await getJson<GetResponse<"/api/v1/evaluations/{run_id}">>(`/api/v1/evaluations/${encodeURIComponent(string(latestRun.id))}`, false));
          const gateVerdicts = record(record(detailed.readiness).gate_verdicts);
          const enrichedResults = records(runDetail.results).map((result) => {
            const criterion = rawCriteria.find((item) => string(item.id) === string(result.criterion_id));
            return {
              ...result,
              criterion,
              name: string(criterion?.name),
              kind: criterion?.hard_gate === false ? "WEIGHTED" : "HARD_GATE",
              verdict: gateVerdicts[string(criterion?.key)],
              evaluator: result.evaluator ?? runDetail.evaluator ?? latestRun.evaluator ?? latestRun.provider,
              last_run_at: runDetail.completed_at ?? latestRun.completed_at
            };
          });
          detailed = { ...detailed, results: enrichedResults };
        }
        rawCandidates = [detailed, ...rawCandidates.filter((candidate) => string(candidate.id) !== detailId)];
      }
    }
    const candidates = rawCandidates.map((candidate) => {
      const id = string(candidate.id);
      const mapped = normalizeCandidate(candidate, eventCandidates.get(id) ?? []);
      const requestedVersion = string(candidate.current_policy_version);
      const requestedPolicyId = string(candidate.active_policy_id ?? candidate.policy_id);
      const requestedPolicyKey = string(candidate.current_policy_key ?? candidate.policy_key);
      const requestedPolicyHash = string(candidate.policy_hash);
      const assignedPolicy = policies.find((policy) =>
        (requestedPolicyId.length > 0 && policy.id === requestedPolicyId)
        || (requestedPolicyHash.length > 0 && policy.hash === requestedPolicyHash)
        || (
          requestedPolicyKey.length > 0
          && policy.key === requestedPolicyKey
          && requestedVersion === policy.version
        )
      );
      return assignedPolicy
        ? {
            ...mapped,
            policyName: string(candidate.policy_name, assignedPolicy.name),
            policyId: assignedPolicy.id,
            policyKey: assignedPolicy.key,
            policyHash: string(candidate.policy_hash, assignedPolicy.hash),
            lifecycleApprovalState: mapped.lifecycleApprovalState === "REQUIRED" && assignedPolicy.requiredLifecycleApprovals === 0
              ? "NOT_REQUIRED"
              : mapped.lifecycleApprovalState
          }
        : mapped;
    });
    const candidateNames = new Map(candidates.map((candidate) => [candidate.id, candidate.name]));
    let rawEvaluations = items(evaluationsBody);
    if (detailEvaluationId) {
      const detail = record(await getJson<GetResponse<"/api/v1/evaluations/{run_id}">>(`/api/v1/evaluations/${encodeURIComponent(detailEvaluationId)}`, false));
      if (Object.keys(detail).length > 0) {
        const collectionRun = rawEvaluations.find((run) => string(run.id) === detailEvaluationId) ?? {};
        const evaluationCandidateId = string(detail.candidate_id ?? collectionRun.candidate_id);
        const candidateDetail = evaluationCandidateId
          ? record(await getJson<GetResponse<"/api/v1/candidates/{candidate_id}">>(`/api/v1/candidates/${encodeURIComponent(evaluationCandidateId)}`, false))
          : {};
        const candidateGates = records(candidateDetail.gates);
        const enrichedResults = records(detail.results).map((result) => {
          const criterion = rawCriteria.find((item) => string(item.id) === string(result.criterion_id));
          const gate = candidateGates.find((item) => string(item.criterion_id) === string(result.criterion_id));
          return {
            ...result,
            criterion,
            name: string(gate?.name ?? criterion?.name),
            category: gate?.category ?? criterion?.category,
            kind: gate?.hard_gate === false || criterion?.hard_gate === false ? "WEIGHTED" : "HARD_GATE",
            verdict: gate?.verdict,
            comparison_operator: gate?.comparison_operator ?? criterion?.comparison_operator,
            threshold: gate?.threshold ?? criterion?.threshold,
            weight: gate?.weight ?? criterion?.weight,
            minimum_samples: gate?.minimum_samples ?? criterion?.minimum_samples,
            evaluator: gate?.evaluator ?? result.provider,
            evaluator_version: gate?.evaluator_version,
            last_run_at: gate?.last_result_at ?? detail.completed_at ?? collectionRun.completed_at
          };
        });
        const enriched = { ...collectionRun, ...detail, results: enrichedResults };
        rawEvaluations = [enriched, ...rawEvaluations.filter((run) => string(run.id) !== detailEvaluationId)];
      }
    }
    let rawRegistryAgents = items(registryBody).length > 0
      ? items(registryBody)
      : records(dashboard.registry_versions);
    if (detailRegistryAgentId) {
      const agentDetail = record(await getJson<GetResponse<"/api/v1/registry/agents/{agent_id}">>(
        `/api/v1/registry/agents/${encodeURIComponent(detailRegistryAgentId)}`,
        false
      ));
      if (Object.keys(agentDetail).length > 0) {
        const detailVersions: JsonRecord[] = records(agentDetail.versions).map((version) => ({
          ...version,
          agent_id: agentDetail.id,
          display_name: agentDetail.display_name,
          registry_key: agentDetail.registry_key,
          stage: agentDetail.stage,
          status: agentDetail.status,
          monitoring_state: agentDetail.monitoring_state,
          health: agentDetail.health,
          monitoring_run_count: agentDetail.monitoring_run_count,
          recent_monitoring_events: agentDetail.recent_monitoring_events,
          active: agentDetail.active,
          is_active_version: string(version.id) === string(agentDetail.active_version_id)
        }));
        const detailVersionIds = new Set(detailVersions.map((version) => string(version.id)));
        rawRegistryAgents = [
          ...detailVersions,
          ...rawRegistryAgents.filter((version) => !detailVersionIds.has(string(version.id)))
        ];
      }
    }
    return {
      generatedAt: string(dashboard.generated_at, new Date().toISOString()),
      candidates,
      evaluations: rawEvaluations.map((run) => mapEvaluation(run, candidateNames)),
      policies,
      schedules: (items(schedulesBody).length > 0 ? items(schedulesBody) : records(dashboard.jobs)).map(mapSchedule),
      registryAgents: rawRegistryAgents.map(mapRegistry),
      recentEvents: events.sort((left, right) => right.sequence - left.sequence),
      liveConnected: true,
      demoMode: boolean(dashboard.demo_mode, false)
    };
  } catch (error) {
    if (process.env.PROMOTION_UI_FIXTURE_FALLBACK === "1") return fixtureDashboard;
    throw error;
  }
}
