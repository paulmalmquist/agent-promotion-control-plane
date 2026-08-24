import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PromotionShell } from "../PromotionShell";
import { governedCopyArtifact, governedCopyBody } from "../governed-copy";
import { fixtureCandidate, fixtureDashboard } from "./fixture";
import type { PromotionEventEnvelope } from "../types";

describe("PromotionShell", () => {
  it("renders governed overview copy and numbered navigation", () => {
    render(<PromotionShell initialData={fixtureDashboard} />);
    expect(screen.getByRole("heading", { name: "Promotion control plane" })).toBeInTheDocument();
    expect(screen.getByText(governedCopyBody.screens.overview.line1)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /02Candidates/i })).toBeInTheDocument();
    expect(document.querySelector("[data-promotion-control-plane]")).toHaveAttribute(
      "data-governed-copy-digest",
      governedCopyArtifact.digest
    );
  });

  it("uses host-overridable semantic tokens", () => {
    const { container } = render(
      <PromotionShell initialData={fixtureDashboard} tokens={{ decision: "rgb(149, 120, 255)" }} />
    );
    expect(container.firstElementChild).toHaveStyle("--pcp-decision: rgb(149, 120, 255)");
  });

  it("separates readiness, eligibility, and registry activation", () => {
    render(
      <PromotionShell
        initialData={fixtureDashboard}
        currentPath={`/candidates/${fixtureCandidate.id}`}
      />
    );
    expect(screen.getByText("Evaluation readiness")).toBeInTheDocument();
    expect(screen.getByText("Promotion eligibility")).toBeInTheDocument();
    expect(screen.getByText("Registry activation")).toBeInTheDocument();
    expect(screen.getByText(governedCopyBody.authorityNotice)).toBeInTheDocument();
  });

  it("routes lifecycle decisions through the injected callback", async () => {
    const decide = vi.fn().mockResolvedValue({ accepted: true, message: "Attention recorded the decision." });
    render(
      <PromotionShell
        initialData={fixtureDashboard}
        currentPath={`/candidates/${fixtureCandidate.id}`}
        onLifecycleDecision={decide}
        embedded
        attentionLink="/attention/promotion"
      />
    );
    fireEvent.click(screen.getByRole("button", { name: governedCopyBody.actions.promote.label }));
    fireEvent.change(screen.getByLabelText("Decision rationale"), {
      target: { value: "The evidence is complete and every required hard gate passed." }
    });
    fireEvent.click(screen.getAllByRole("button", { name: governedCopyBody.actions.promote.label }).at(-1)!);
    await waitFor(() => expect(decide).toHaveBeenCalledTimes(1));
    expect(decide.mock.calls[0]?.[0]).toMatchObject({
      targetStage: "PROMOTED",
      expectedCandidateRevision: 7,
      policyHash: fixtureCandidate.policyHash
    });
  });

  it("never falls back to direct mutation when embedded without an Attention callback", () => {
    const mutate = vi.fn();
    const dataSource = {
      query: vi.fn(),
      mutate,
      subscribe: vi.fn(() => () => undefined)
    };
    render(
      <PromotionShell
        initialData={fixtureDashboard}
        currentPath={`/agents/promotion/candidates/${fixtureCandidate.id}`}
        dataSource={dataSource}
        embedded
      />
    );
    expect(screen.getByRole("button", { name: "Attention callback required" })).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("keeps embedded retry behind a governed callback", () => {
    const mutate = vi.fn();
    const failedCandidate = {
      ...fixtureCandidate,
      activationState: "FAILED" as const,
      status: "BLOCKED" as const,
      registryOperationId: "operation-failed",
      blockerCode: "REGISTRY_OPERATION_FAILED",
      blockerSummary: "Registry activation failed"
    };
    render(
      <PromotionShell
        initialData={{ ...fixtureDashboard, candidates: [failedCandidate] }}
        currentPath={`/agents/promotion/candidates/${failedCandidate.id}`}
        dataSource={{ query: vi.fn(), mutate, subscribe: vi.fn(() => () => undefined) }}
        embedded
      />
    );
    expect(screen.getByRole("button", { name: "Attention callback required" })).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("confirms standalone retry and supports keyboard dismissal before mutation", async () => {
    const mutate = vi.fn().mockResolvedValue({});
    const failedCandidate = {
      ...fixtureCandidate,
      activationState: "FAILED" as const,
      status: "BLOCKED" as const,
      registryOperationId: "operation-failed",
      blockerCode: "REGISTRY_OPERATION_FAILED",
      blockerSummary: "Registry activation failed"
    };
    render(
      <PromotionShell
        initialData={{ ...fixtureDashboard, candidates: [failedCandidate] }}
        currentPath={`/candidates/${failedCandidate.id}`}
        dataSource={{ query: vi.fn(), mutate, subscribe: vi.fn(() => () => undefined) }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: governedCopyBody.actions.retryRegistry.label }));
    expect(screen.getByRole("dialog", { name: "Retry registry publication" })).toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Retry registry publication" })).not.toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: governedCopyBody.actions.retryRegistry.label }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm registry retry" }));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  });

  it("keeps embedded autonomous cycles behind a governed callback", () => {
    const mutate = vi.fn();
    render(
      <PromotionShell
        initialData={fixtureDashboard}
        currentPath="/agents/promotion/automation"
        dataSource={{ query: vi.fn(), mutate, subscribe: vi.fn(() => () => undefined) }}
        embedded
      />
    );
    expect(screen.getByRole("button", { name: "Attention callback required" })).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("shows autonomous-cycle progress from live discovery without reloading", () => {
    let emit: ((event: PromotionEventEnvelope) => void) | undefined;
    const dataSource = {
      query: vi.fn(),
      mutate: vi.fn(),
      subscribe: vi.fn((listener: (event: PromotionEventEnvelope) => void) => {
        emit = listener;
        return () => undefined;
      })
    };
    render(
      <PromotionShell
        initialData={fixtureDashboard}
        currentPath="/automation"
        dataSource={dataSource}
      />
    );
    act(() => emit?.({
      id: "event-live-1",
      sequence: 100,
      schemaVersion: 1,
      eventType: "CANDIDATE_DISCOVERED",
      occurredAt: "2026-08-24T14:30:00Z",
      actor: "demo-cycle",
      candidateId: "candidate-live",
      evaluationRunId: null,
      scheduleRunId: null,
      registryOperationId: null,
      correlationId: "cycle-1",
      causationId: null,
      payload: { signal: "RECURRING_MULTI_SKILL_WORKFLOW", stage: "DISCOVERED" }
    }));
    expect(screen.getByRole("region", { name: "Live autonomous cycle" })).toBeInTheDocument();
    expect(screen.getByText("Discovered candidate")).toBeInTheDocument();
    expect(screen.getAllByText("Discovered").length).toBeGreaterThan(0);

    act(() => emit?.({
      id: "event-live-2",
      sequence: 101,
      schemaVersion: 1,
      eventType: "EVALUATION_COMPLETED",
      occurredAt: "2026-08-24T14:31:00Z",
      actor: "demo-worker",
      candidateId: "candidate-live",
      evaluationRunId: "evaluation-live",
      scheduleRunId: null,
      registryOperationId: null,
      correlationId: "cycle-1",
      causationId: "event-live-1",
      payload: { stage: "ELIGIBLE", readiness_percentage: "100.000" }
    }));
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText(/Evaluation completed/i)).toBeInTheDocument();
  });
});
