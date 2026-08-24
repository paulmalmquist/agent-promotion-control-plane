import { cleanup, render } from "@testing-library/react";
import { canonicalizeGovernedCopy, governedCopyBody } from "../governed-copy";
import { PromotionShell } from "../PromotionShell";
import type { CandidateViewModel, DashboardViewModel } from "../types";
import { fixtureCandidate, fixtureDashboard } from "./fixture";

function governedLines(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-governed-copy='true'] > p")]
    .map((node) => node.textContent?.trim() ?? "")
    .filter(Boolean);
}

function candidateState(overrides: Partial<CandidateViewModel>): DashboardViewModel {
  return { ...fixtureDashboard, candidates: [{ ...fixtureCandidate, ...overrides }] };
}

describe("rendered governed-copy drift", () => {
  it("matches every critical screen's rendered opening lines to the hashed artifact", () => {
    const states: Array<{
      key: keyof typeof governedCopyBody.screens;
      path: string;
      data: DashboardViewModel;
      offset?: number;
    }> = [
      { key: "overview", path: "/", data: fixtureDashboard },
      { key: "candidates", path: "/candidates", data: fixtureDashboard },
      { key: "candidate", path: `/candidates/${fixtureCandidate.id}`, data: fixtureDashboard },
      { key: "promotionRationale", path: `/candidates/${fixtureCandidate.id}`, data: fixtureDashboard, offset: 2 },
      {
        key: "blocker",
        path: `/candidates/${fixtureCandidate.id}`,
        data: candidateState({ status: "BLOCKED", blockerCode: "HARD_GATE_FAILED", blockerSummary: "A hard gate failed" })
      },
      {
        key: "registryPending",
        path: `/candidates/${fixtureCandidate.id}`,
        data: candidateState({ activationState: "PENDING", status: "PROMOTION_PENDING" })
      },
      {
        key: "registryFailure",
        path: `/candidates/${fixtureCandidate.id}`,
        data: candidateState({ activationState: "FAILED", status: "BLOCKED", blockerCode: "REGISTRY_OPERATION_FAILED" })
      },
      { key: "evaluations", path: "/evaluations", data: fixtureDashboard },
      { key: "contract", path: "/contract", data: fixtureDashboard },
      { key: "automation", path: "/automation", data: fixtureDashboard },
      { key: "registry", path: "/registry", data: fixtureDashboard },
      { key: "audit", path: "/audit", data: fixtureDashboard }
    ];
    const renderedScreens: Partial<Record<keyof typeof governedCopyBody.screens, { line1: string; line2: string }>> = {};

    states.forEach(({ key, path, data, offset = 0 }) => {
      const { container, unmount } = render(<PromotionShell initialData={data} currentPath={path} />);
      const expected = governedCopyBody.screens[key];
      const lines = governedLines(container);
      expect(lines[offset]).toBe(expected.line1);
      expect(lines[offset + 1]).toBe(expected.line2);
      renderedScreens[key] = { line1: lines[offset]!, line2: lines[offset + 1]! };
      unmount();
    });

    expect(canonicalizeGovernedCopy(renderedScreens)).toBe(
      canonicalizeGovernedCopy(governedCopyBody.screens)
    );
    expect(canonicalizeGovernedCopy({
      ...renderedScreens,
      candidate: { ...renderedScreens.candidate!, line1: "Changed rendered line" }
    })).not.toBe(canonicalizeGovernedCopy(governedCopyBody.screens));
    cleanup();
  });
});
