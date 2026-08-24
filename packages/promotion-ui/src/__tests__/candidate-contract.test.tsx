import { fireEvent, render, screen } from "@testing-library/react";
import { PromotionShell } from "../PromotionShell";
import type { CandidateViewModel } from "../types";
import { fixtureCandidate, fixtureDashboard } from "./fixture";

function renderCandidate(candidate: CandidateViewModel) {
  return render(
    <PromotionShell
      initialData={{ ...fixtureDashboard, candidates: [candidate] }}
      currentPath={`/candidates/${candidate.id}`}
    />
  );
}

describe("candidate review contract", () => {
  it("filters by lifecycle, type, detector, blocker, and promotion readiness", () => {
    const blocked = {
      ...fixtureCandidate,
      id: "candidate-blocked",
      slug: "candidate-blocked",
      name: "Blocked candidate",
      stage: "EVALUATING" as const,
      status: "BLOCKED" as const,
      promotionEligible: false,
      blockerCode: "HARD_GATE_FAILED",
      blockerSummary: "Latency exceeded the required threshold.",
      candidateType: "WORKFLOW_AGENT",
      detectorLineage: "latency-detector / revision 2"
    };
    render(
      <PromotionShell
        initialData={{ ...fixtureDashboard, candidates: [fixtureCandidate, blocked] }}
        currentPath="/candidates"
      />
    );
    expect(screen.getAllByText("1 of 1 passed")).toHaveLength(2);
    expect(screen.getAllByText("94.2 of 100")).toHaveLength(2);
    expect(screen.getByText(/Record the promotion lifecycle decision/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Review state"), { target: { value: "BLOCKED" } });
    expect(screen.getByRole("heading", { name: "Blocked candidate" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: fixtureCandidate.name })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Review state"), { target: { value: "ALL" } });
    fireEvent.change(screen.getByLabelText("Lifecycle stage"), { target: { value: "ELIGIBLE" } });
    fireEvent.change(screen.getByLabelText("Candidate type or detector"), {
      target: { value: `DETECTOR:${fixtureCandidate.detectorLineage}` }
    });
    expect(screen.getByRole("heading", { name: fixtureCandidate.name })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Blocked candidate" })).not.toBeInTheDocument();
  });

  it("renders the exact gate measurement contract and real artifact reference", () => {
    renderCandidate(fixtureCandidate);
    expect(screen.getByText(/Safety · No safety regression/i)).toBeInTheDocument();
    expect(screen.getByText("Weight: Not applicable")).toBeInTheDocument();
    expect(screen.getByText("0 regressions ≤ 0 regressions")).toBeInTheDocument();
    expect(screen.getByText("Deterministic rule evaluator")).toBeInTheDocument();
    const digest = screen
      .getAllByText(/SHA-256:/i)
      .find((element) => element.getAttribute("title") === fixtureCandidate.evidence[0]!.digest);
    expect(digest).toBeDefined();
    expect(digest).toHaveAttribute("title", fixtureCandidate.evidence[0]!.digest);
    expect(fixtureCandidate.evidence[0]!.digest).toMatch(/^[a-f\d]{64}$/i);
    expect(screen.getByRole("link", { name: "Inspect artifact" })).toHaveAttribute(
      "href",
      fixtureCandidate.evidence[0]!.uri
    );
    expect(screen.getByText(/Eligibility · Eligible/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Every hard gate passed/i)).toHaveLength(2);
  });

  it.each([
    {
      label: "hard-gate",
      code: "HARD_GATE_FAILED",
      category: "SAFETY",
      title: "Latency hard gate failed",
      explanation: "Observed latency exceeded the policy threshold during deterministic replay.",
      recovery: "Reduce latency, then rerun the active deterministic evaluation plan.",
      details: { current_measurement: "420 milliseconds", threshold: "300 milliseconds" }
    },
    {
      label: "registry",
      code: "REGISTRY_OPERATION_FAILED",
      category: "ACTIVATION",
      title: "Registry activation failed",
      explanation: "The registry rejected publication. Existing production selection did not change.",
      recovery: "Restore the registry connection, then confirm a stable-token retry.",
      details: { current_measurement: "Connection unavailable", threshold: "Registry accepts publication" }
    }
  ])("renders $label blocker explanation and recovery", (blocker) => {
    const candidate = {
      ...fixtureCandidate,
      status: "BLOCKED" as const,
      activationState: blocker.code === "REGISTRY_OPERATION_FAILED" ? "FAILED" as const : "NOT_REQUESTED" as const,
      blockerCode: blocker.code,
      blockerSummary: blocker.title,
      blockers: [{ id: `blocker-${blocker.label}`, ...blocker }]
    };
    renderCandidate(candidate);
    expect(screen.getByRole("heading", { name: blocker.title })).toBeInTheDocument();
    expect(screen.getByText(blocker.explanation)).toBeInTheDocument();
    expect(screen.getByText(blocker.recovery)).toBeInTheDocument();
    expect(screen.getByText(String(blocker.details.current_measurement))).toBeInTheDocument();
    expect(screen.getByText(String(blocker.details.threshold))).toBeInTheDocument();
  });
});
