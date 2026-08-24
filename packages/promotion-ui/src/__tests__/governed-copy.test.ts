import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { canonicalizeGovernedCopy, governedCopyArtifact, governedCopyBody } from "../governed-copy";

const sharedArtifact = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../../configs/copy/governed-copy.json"),
    "utf8"
  )
) as { body: unknown; digest: string };

function allStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(allStrings);
  return [];
}

function sentenceWordCounts(value: string): number[] {
  return value
    .split(/[.!?](?:\s|$)/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .map((sentence) => sentence.split(/\s+/).filter(Boolean).length);
}

const releaseFixtureCopy = [
  "Observed latency exceeded the policy threshold during deterministic replay.",
  "Reduce latency, then rerun the active deterministic evaluation plan.",
  "The registry rejected publication. Existing production selection did not change.",
  "Restore the registry connection, then confirm a stable-token retry."
];

describe("governed critical copy", () => {
  it("matches the shared serializable certification artifact", () => {
    expect(sharedArtifact.body).toEqual(governedCopyBody);
    expect(sharedArtifact.digest).toBe(governedCopyArtifact.digest);
  });

  it("matches its canonical SHA-256 digest", () => {
    const digest = createHash("sha256")
      .update(canonicalizeGovernedCopy(governedCopyBody))
      .digest("hex");
    expect(governedCopyArtifact.digest).toBe(`sha256:${digest}`);
  });

  it("gives every critical screen two opening lines", () => {
    Object.values(governedCopyBody.screens).forEach((screen) => {
      expect(screen.line1.trim()).not.toBe("");
      expect(screen.line2.trim()).not.toBe("");
    });
  });

  it("keeps every governed sentence at sixteen words or fewer", () => {
    allStrings(governedCopyBody).forEach((value) => {
      sentenceWordCounts(value).forEach((count) => expect(count).toBeLessThanOrEqual(16));
    });
  });

  it("states a consequence and undo for every consequential action", () => {
    Object.values(governedCopyBody.actions).forEach((action) => {
      expect(action.consequence.length).toBeGreaterThan(20);
      expect(action.undo.length).toBeGreaterThan(20);
    });
  });

  it("keeps raw identifiers out of primary copy", () => {
    allStrings(governedCopyBody.screens).forEach((value) => {
      expect(value).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i);
      expect(value).not.toMatch(/\b[0-9a-f]{32,}\b/i);
    });
  });

  it("rejects common passive voice and unexplained acronyms", () => {
    [...allStrings(governedCopyBody), ...releaseFixtureCopy].forEach((value) => {
      expect(value).not.toMatch(/\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+ed\b/i);
      expect(value.match(/\b[A-Z]{2,}\b/g) ?? []).toHaveLength(0);
      sentenceWordCounts(value).forEach((count) => expect(count).toBeLessThanOrEqual(16));
    });
  });

  it("supports a strict context-free semantic evaluator contract", async () => {
    const fake = {
      async evaluate(input: { line1: string; line2: string; actions: { label: string; consequence: string; undo: string }[] }) {
        const passed = input.line1.length > 20
          && input.line2.length > 20
          && input.actions.every((action) => action.consequence.length > 20 && action.undo.length > 20);
        return {
          purpose: input.line1,
          event: input.line2,
          buttonEffects: Object.fromEntries(input.actions.map((action) => [action.label, "Explained"])),
          passed,
          certification: passed ? "CERTIFIED" as const : "FAILED" as const,
          provider: "strict-fake"
        };
      }
    };
    const screen = governedCopyBody.screens.registryPending;
    const result = await fake.evaluate({ ...screen, actions: [governedCopyBody.actions.retryRegistry] });
    expect(result.passed).toBe(true);
    expect(result.buttonEffects[governedCopyBody.actions.retryRegistry.label]).toBe("Explained");
    const failure = await fake.evaluate({ line1: "Unclear", line2: "Missing", actions: [] });
    expect(failure.certification).toBe("FAILED");
  });
});
