import { mapEvaluation, mapPolicy, mapRegistry, mapSchedule, normalizeCandidate } from "./api";

describe("FastAPI DTO normalization", () => {
  it("maps the live snake_case candidate detail without percent inflation", () => {
    const candidate = normalizeCandidate({
      id: "11111111-1111-4111-8111-111111111111",
      slug: "release-notes-agent",
      name: "Release notes agent",
      summary: "Drafts evidence-linked release notes.",
      candidate_type: "WORKFLOW",
      stage: "ELIGIBLE",
      status: "BLOCKED",
      revision: 7,
      proposed_capability: "Prepare release notes from verified merged work.",
      current_policy_version: "production-agent@1",
      updated_at: "2026-08-24T14:20:00Z",
      discovered_by: "workflow-repetition",
      discovery_source: "detector-run-12",
      rationale: "Twelve verified runs completed without manual correction.",
      policy_name: "Production agent policy",
      policy_hash: "a1b2c3d4",
      evaluation_snapshot_hash: "b1c2d3e4",
      lifecycle_approval_state: "APPROVED",
      readiness: {
        evaluation_readiness: 100,
        hard_gate_readiness: 100,
        weighted_score: 94.2,
        weighted_readiness: 100,
        sample_completeness: 75,
        evaluation_completeness: 100,
        promotion_eligible: false,
        registry_activation_state: "FAILED",
        gate_verdicts: { safety_regression: "PASSED" }
      },
      blockers: [{
        code: "REGISTRY_OPERATION_FAILED",
        category: "OPERATIONAL",
        title: "Registry publication failed",
        explanation: "The registry connection rejected publication.",
        recovery: "Restore the connection and retry publication."
      }],
      detector_evidence: [{
        id: "evidence-1",
        signal_type: "REPEATED_SUCCESSFUL_SKILL_USAGE",
        evidence: { successful_runs: 18, source: "demo-fixture" },
        created_at: "2026-08-20T14:20:00Z"
      }],
      registry_operation: { id: "operation-1", activation_state: "FAILED" }
    });

    expect(candidate).toMatchObject({
      component: "WORKFLOW",
      description: "Drafts evidence-linked release notes.",
      surfacedReason: "Twelve verified runs completed without manual correction.",
      detectorLineage: "workflow-repetition",
      blockerSummary: "Registry publication failed",
      registryOperationId: "operation-1",
      activationState: "FAILED",
      policyHash: "a1b2c3d4",
      evaluationSnapshotHash: "b1c2d3e4",
      lifecycleApprovalState: "APPROVED",
      evaluation: {
        readinessPercentage: 100,
        hardGateReadiness: 1,
        weightedReadiness: 1,
        sampleCompleteness: 0.75,
        evaluationCompleteness: 1
      }
    });
    expect(candidate.gates[0]).toMatchObject({ name: "safety regression", verdict: "PASSED" });
    expect(candidate.evidence[0]?.summary).toContain("successful runs: 18");
  });

  it("preserves ratio-shaped readiness components", () => {
    const candidate = normalizeCandidate({
      id: "candidate-ratio",
      name: "Ratio candidate",
      readiness: {
        evaluation_readiness: 75,
        hard_gate_readiness: 1,
        weighted_readiness: 0.5,
        sample_completeness: 0,
        evaluation_completeness: 1
      }
    });
    expect(candidate.evaluation).toMatchObject({
      readinessPercentage: 75,
      hardGateReadiness: 1,
      weightedReadiness: 0.5,
      sampleCompleteness: 0,
      evaluationCompleteness: 1
    });
  });

  it("keeps raw gate measurements separate from normalized scores and artifacts", () => {
    const digest = "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef";
    const candidate = normalizeCandidate({
      id: "candidate-contract",
      name: "Deployment advisor",
      stage: "EVALUATING",
      status: "BLOCKED",
      readiness: {
        evaluation_readiness: "91.667",
        hard_gate_readiness: "66.667",
        weighted_readiness: "100",
        sample_completeness: "100",
        evaluation_completeness: "100",
        weighted_score: "92.5",
        required_weighted_score: "80",
        valid_result_count: 3,
        required_criterion_count: 3
      },
      promotion_eligibility: {
        evidence_eligible: false,
        eligible: false,
        required_lifecycle_approvals: 1,
        available_lifecycle_approvals: 1,
        consumed_lifecycle_approvals: 0,
        active_blocker_count: 1,
        lifecycle_approval_state: "APPROVED",
        registry_activation_state: "NOT_REQUESTED"
      },
      gates: [{
        criterion_id: "criterion-latency",
        criterion_key: "latency",
        name: "Response latency",
        category: "QUALITY",
        hard_gate: true,
        verdict: "FAILED",
        comparison_operator: "lte",
        threshold: 300,
        weight: null,
        measurement_value: 420,
        measurement_unit: "milliseconds",
        normalized_score: 0.2,
        sample_count: 12,
        minimum_samples: 10,
        evidence_codes: ["latency-log"],
        evaluator: "deterministic-rule",
        evaluator_version: "2.1.0",
        last_result_at: "2026-08-24T14:00:00Z"
      }],
      evidence_artifacts: [{
        id: "artifact-latency",
        artifact_type: "TEST_LOG",
        uri: "/api/v1/evidence/artifact-latency",
        sha256: digest,
        media_type: "application/json",
        sanitized: true,
        provider_metadata: { provider: "deterministic-rule" },
        created_at: "2026-08-24T14:00:00Z"
      }],
      detector_evidence: [{
        id: "signal-1",
        signal_type: "REPEATED_SUCCESSFUL_SKILL_USAGE",
        evidence: { successful_runs: 12 },
        created_at: "2026-08-24T12:00:00Z"
      }],
      latest_eligibility_decision: {
        outcome: "BLOCKED",
        rationale: "The latency hard gate failed during deterministic replay.",
        actor: "gate-engine",
        created_at: "2026-08-24T14:01:00Z",
        policy_hash: "policy-hash",
        evaluation_snapshot_hash: "evaluation-hash"
      }
    });

    expect(candidate.evaluation.readinessPercentage).toBeCloseTo(91.667);
    expect(candidate.evaluation.hardGateReadiness).toBeCloseTo(0.66667);
    expect(candidate.gates[0]).toMatchObject({
      measurementValue: 420,
      measurementUnit: "milliseconds",
      normalizedScore: 0.2,
      threshold: 300,
      evaluator: "deterministic-rule · 2.1.0"
    });
    expect(candidate.evidence).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: "ARTIFACT", digest, uri: "/api/v1/evidence/artifact-latency" }),
      expect.objectContaining({ kind: "DETECTOR_SIGNAL", digest: null, uri: null })
    ]));
    expect(candidate.latestDecision).toMatchObject({ outcome: "BLOCKED", actor: "gate-engine" });
    expect(candidate.lifecycleApprovalState).toBe("APPROVED");
    expect(candidate).toMatchObject({
      requiredLifecycleApprovals: 1,
      availableLifecycleApprovals: 1,
      consumedLifecycleApprovals: 0,
      activeBlockerCount: 1
    });
  });

  it("maps enriched evaluation, schedule, registry, and policy DTOs without factual zero defaults", () => {
    const evaluation = mapEvaluation({
      id: "evaluation-42",
      candidate_id: "candidate-42",
      plan_id: "plan-42",
      status: "SUCCEEDED",
      attempt_count: 1,
      max_attempts: 3,
      provider_names: ["openai-rubric"],
      planned_result_count: 1,
      result_count: 1,
      sample_count: 8,
      progress_percentage: 100,
      cost_usd: "0.0031",
      latency_ms: "842",
      correlation_id: "correlation-42",
      heartbeat_at: "2026-08-24T14:01:00Z",
      started_at: "2026-08-24T14:00:00Z",
      completed_at: "2026-08-24T14:01:00Z",
      results: [{
        id: "result-42",
        criterion_id: "criterion-42",
        name: "Cold-read purpose",
        category: "QUALITY",
        kind: "WEIGHTED",
        verdict: "PASSED",
        measurement_value: 0.94,
        measurement_unit: "ratio",
        normalized_score: 0.94,
        comparison_operator: "gte",
        threshold: 0.8,
        sample_count: 8,
        minimum_samples: 8,
        evidence_codes: ["copy-certification"],
        provider: "openai-rubric",
        model: "gpt-5-mini",
        cost_usd: "0.0031",
        latency_ms: "842",
        valid: true,
        stale: false
      }],
      artifacts: []
    }, new Map([["candidate-42", "Cold-read reviewer"]]));
    expect(evaluation).toMatchObject({
      planId: "plan-42",
      provider: "openai-rubric",
      model: "gpt-5-mini",
      costUsd: 0.0031,
      latencyMilliseconds: 842,
      attemptCount: 1,
      maxAttempts: 3
    });
    expect(evaluation.results[0]).toMatchObject({ provider: "openai-rubric", model: "gpt-5-mini", valid: true });

    const schedule = mapSchedule({
      id: "schedule-42",
      key: "nightly-evaluation",
      name: "Nightly evaluation",
      description: "Checks active candidates.",
      job_type: "EVALUATION",
      enabled: true,
      trigger_owner: "GitHub Actions",
      trigger_mode: "EXTERNAL_CRON",
      owner_reference: ".github/workflows/nightly.yml",
      connection_state: "CONNECTED",
      connection_message: "The named owner can trigger this job.",
      timezone: "UTC",
      schedule_expression: "0 5 * * *",
      grace_window_seconds: 1800,
      run_count: 14,
      failure_count: 2,
      last_run_status: "SUCCEEDED",
      current_activity: null,
      last_duration_seconds: 12.4,
      history: [{
        id: "run-42",
        status: "SUCCEEDED",
        triggered_by: "github-actions",
        trigger_source: "EXTERNAL_CRON",
        attempt_count: 1,
        completed_at: "2026-08-24T05:00:00Z",
        correlation_id: "correlation-schedule-42"
      }]
    });
    expect(schedule).toMatchObject({ runCount: 14, failureCount: 2, lastRunState: "SUCCEEDED", lastDurationSeconds: 12.4 });
    expect(schedule.recentRuns[0]).toMatchObject({ state: "SUCCEEDED", attemptCount: 1 });

    const registry = mapRegistry({
      id: "version-42",
      agent_id: "agent-42",
      display_name: "Release reviewer",
      registry_key: "release-reviewer",
      external_version_id: "release-reviewer:3",
      candidate_id: "candidate-42",
      version: 3,
      publication_token: "publication-42",
      promoted_at: "2026-08-24T14:00:00Z",
      stage: "MONITORED",
      status: "SUSPENDED",
      monitoring_state: "SUSPENDED",
      health: "REGRESSION_DETECTED",
      monitoring_run_count: 4,
      recent_monitoring_events: [{
        id: "event-monitor-42",
        sequence: 42,
        event_type: "POST_PROMOTION_REGRESSION_DETECTED",
        occurred_at: "2026-08-24T15:00:00Z",
        actor: "monitoring-worker",
        correlation_id: "correlation-monitor-42",
        causation_id: null,
        payload: { status: "SUSPENDED", code: "QUALITY_REGRESSION" }
      }],
      active: false,
      is_active_version: true,
      policy_hash: "policy-42",
      evaluation_snapshot_hash: "evaluation-42"
    });
    expect(registry).toMatchObject({
      agentId: "agent-42",
      registryKey: "release-reviewer",
      candidateStage: "MONITORED",
      candidateStatus: "SUSPENDED",
      state: "SUSPENDED",
      monitoringState: "SUSPENDED",
      active: false,
      health: "REGRESSION_DETECTED",
      monitoringRunCount: 4
    });
    expect(registry.recentMonitoringEvents[0]).toMatchObject({
      eventType: "POST_PROMOTION_REGRESSION_DETECTED",
      headline: "Post Promotion Regression Detected"
    });

    const policy = mapPolicy({
      id: "policy-42",
      key: "production-agent",
      version: "3.0.0",
      name: "Production agent policy",
      content_hash: "policy-hash-42",
      minimum_weighted_score: 80,
      required_lifecycle_approvals: 1,
      lifecycle_stages: ["DISCOVERED", "ELIGIBLE", "PROMOTED"],
      criteria: [{
        id: "criterion-42",
        version: "2.0.0",
        name: "Safety regression",
        description: "Requires zero safety regressions.",
        proof_meaning: "Zero regressions prove preserved safety behavior.",
        content_hash: "criterion-hash-42",
        category: "SAFETY",
        hard_gate: true,
        evaluator_type: "DETERMINISTIC_RULE",
        evaluator_key: "deterministic-rule",
        evaluator_version: "2.1.0",
        comparison_operator: "lte",
        measurement_unit: "regressions",
        threshold: 0,
        minimum_samples: 10,
        required_evidence: ["safety-replay"],
        aggregation_rule: "maximum"
      }]
    });
    expect(policy.version).toBe("3.0.0");
    expect(policy.criteria[0]).toMatchObject({
      version: "2.0.0",
      proofMeaning: "Zero regressions prove preserved safety behavior.",
      evaluatorType: "DETERMINISTIC_RULE",
      evaluator: "deterministic-rule · 2.1.0",
      measurementUnit: "regressions",
      aggregation: "maximum",
      contentHash: "criterion-hash-42"
    });
  });
});
