import { render, screen } from "@testing-library/react";
import { PromotionShell } from "../PromotionShell";
import type { DashboardViewModel } from "../types";
import { fixtureDashboard } from "./fixture";

const dashboard: DashboardViewModel = {
  ...fixtureDashboard,
  policies: [{
    id: "policy-1",
    key: "production-agent",
    name: "Production agent policy",
    version: "3.0.0",
    hash: "d1e2f3a4b5c60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
    minimumWeightedScore: 80,
    lifecycleStages: ["DISCOVERED", "CANDIDATE", "EVALUATING", "ELIGIBLE", "SHADOW", "PROMOTED", "MONITORED"],
    requiredLifecycleApprovals: 1,
    criteria: [{
      id: "criterion-1",
      version: "1.0.0",
      name: "Safety regression",
      description: "Proves the candidate introduces no safety regression.",
      proofMeaning: "Zero regressions prove the candidate preserves established safety behavior.",
      contentHash: "f1e2d3c4b5a60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
      category: "SAFETY",
      kind: "HARD_GATE",
      evaluatorType: "DETERMINISTIC_RULE",
      evaluator: "Deterministic rule evaluator",
      comparisonOperator: "lte",
      measurementUnit: "regressions",
      threshold: 0,
      weight: null,
      minimumSamples: 10,
      evidenceRequirements: ["safety replay"],
      aggregation: "sample_weighted_mean"
    }]
  }],
  schedules: [{
    id: "schedule-1",
    key: "nightly-regression-replay",
    name: "Nightly regression replay",
    description: "Replays promoted versions against the fixed regression corpus.",
    jobType: "REGRESSION_REPLAY",
    enabled: true,
    triggerOwner: "GitHub Actions",
    triggerMode: "EXTERNAL_CRON",
    ownerReference: ".github/workflows/nightly.yml",
    connectionState: "DISCONNECTED",
    connectionMessage: "The named trigger owner must reconnect before automatic dispatch resumes.",
    timezone: "UTC",
    scheduleExpression: "0 5 * * *",
    lastObservedRunAt: "2026-08-23T05:00:00Z",
    nextExpectedTriggerAt: "2026-08-25T05:00:00Z",
    graceWindowMinutes: 30,
    lastRunState: "SUCCEEDED",
    runCount: 14,
    failureCount: 1,
    currentActivity: null,
    lastDurationSeconds: 42.5,
    recentRuns: [{
      id: "schedule-run-1",
      state: "SUCCEEDED",
      triggeredBy: "github-actions",
      triggerSource: "EXTERNAL_CRON",
      observedAt: "2026-08-23T05:00:00Z",
      attemptCount: 1,
      correlationId: "correlation-schedule-run-1"
    }]
  }],
  registryAgents: [{
    id: "agent-version-1",
    agentId: "agent-1",
    registryKey: "release-notes-agent",
    externalVersionId: "release-notes-agent:2",
    name: "Release notes agent",
    candidateId: fixtureDashboard.candidates[0]!.id,
    version: 2,
    publicationToken: "publication-token-1",
    promotedAt: "2026-08-23T10:00:00Z",
    state: "ACTIVE",
    candidateStage: "MONITORED",
    candidateStatus: "ACTIVE",
    active: true,
    isActiveVersion: true,
    policyHash: "d1e2f3a4b5c60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
    evaluationSnapshotHash: "e1f2a3b4c5d60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
    health: "NOMINAL",
    monitoringState: "MONITORED",
    monitoringRunCount: 6,
    recentMonitoringEvents: [{
      id: "monitoring-event-1",
      sequence: 90,
      eventType: "POST_PROMOTION_MONITORING_OBSERVED",
      occurredAt: "2026-08-24T10:00:00Z",
      actor: "monitoring-worker",
      headline: "Monitoring observation recorded",
      detail: "The worker observed nominal post-promotion behavior.",
      correlationId: "correlation-monitoring-1"
    }]
  }]
};

describe("secondary control-plane views", () => {
  it.each([
    ["/candidates", "Candidate inventory"],
    ["/evaluations", "Evaluation runs"],
    ["/registry", "Promoted agents"],
    ["/audit", "Control-plane timeline"]
  ])("renders %s through the browser-neutral shell", (path, heading) => {
    render(<PromotionShell initialData={dashboard} currentPath={path} />);
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("renders immutable policy criteria and empty-set semantics", () => {
    render(<PromotionShell initialData={dashboard} currentPath="/contract" />);
    expect(screen.getByRole("heading", { name: "Criteria and policies" })).toBeInTheDocument();
    expect(screen.getByText("Safety regression")).toBeInTheDocument();
    expect(screen.getByText("10 samples required")).toBeInTheDocument();
    expect(screen.getByText("Deterministic rule evaluator")).toBeInTheDocument();
    expect(screen.getByText("≤ 0 regressions")).toBeInTheDocument();
    expect(screen.getByText("Proves the candidate introduces no safety regression.")).toBeInTheDocument();
    expect(screen.getByText(/Zero regressions prove the candidate preserves established safety behavior/i)).toBeInTheDocument();
    expect(screen.getByText("Deterministic Rule")).toBeInTheDocument();
    expect(screen.getByText(/Criterion SHA-256/i)).toHaveAttribute("title", dashboard.policies[0]!.criteria[0]!.contentHash);
  });

  it("names the external trigger owner and disconnected consequence", () => {
    render(<PromotionShell initialData={dashboard} currentPath="/automation" />);
    expect(screen.getByRole("heading", { name: "Trigger ownership" })).toBeInTheDocument();
    expect(screen.getByText("This control plane does not execute cron.")).toBeInTheDocument();
    expect(screen.getByText("GitHub Actions")).toBeInTheDocument();
    expect(screen.getByText(/must reconnect before automatic dispatch resumes/i)).toBeInTheDocument();
    expect(screen.getByText(/Next expected trigger/i)).toBeInTheDocument();
    expect(screen.getByText("Regression Replay")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("42.5 seconds")).toBeInTheDocument();
  });

  it("disables demo-cycle controls when the host reports integrated mode", () => {
    render(
      <PromotionShell
        initialData={{ ...dashboard, demoMode: false }}
        currentPath="/automation"
      />
    );
    expect(screen.getByRole("button", { name: "Demo cycle unavailable" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Run autonomous cycle" })).not.toBeInTheDocument();
    expect(screen.getByText("Demo mutations are disabled in this environment.")).toBeInTheDocument();
  });

  it("shows promotion activity and named automation health on the overview", () => {
    render(<PromotionShell initialData={dashboard} currentPath="/" />);
    expect(screen.getByText("Promotion velocity")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recently promoted" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Named automation owners" })).toBeInTheDocument();
    expect(screen.getByText(/GitHub Actions · Next expected:/i)).toBeInTheDocument();
  });

  it("renders evaluation provider measurements and immutable references", () => {
    render(<PromotionShell initialData={dashboard} currentPath="/evaluations/evaluation-1" />);
    expect(screen.getAllByText("rule-engine-v1")).toHaveLength(2);
    expect(screen.getByText("0 regressions")).toBeInTheDocument();
    expect(screen.getByText("≤ 0 regressions")).toBeInTheDocument();
    expect(screen.getByText("Valid result")).toBeInTheDocument();
    expect(screen.getByText(/Plan:/i)).toHaveAttribute("title", "plan-production-readiness");
    expect(screen.getByText(/Correlation:/i)).toHaveAttribute("title", "correlation-evaluation-1");
  });

  it("renders real registry activation and monitoring state", () => {
    render(<PromotionShell initialData={dashboard} currentPath="/registry/agent-1" />);
    expect(screen.getByText("release-notes-agent")).toBeInTheDocument();
    expect(screen.getByText("release-notes-agent:2")).toBeInTheDocument();
    expect(screen.getAllByText("Monitored")).toHaveLength(2);
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent monitoring activity" })).toBeInTheDocument();
    expect(screen.getByText("The worker observed nominal post-promotion behavior.")).toBeInTheDocument();
  });
});
