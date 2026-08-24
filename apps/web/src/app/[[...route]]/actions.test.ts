import { afterEach, describe, expect, it, vi } from "vitest";
import { runPromotionMutation } from "./actions";

afterEach(() => vi.unstubAllGlobals());

describe("standalone promotion Server Action", () => {
  it("forwards a typed governed mutation with actor, revision, and idempotency", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ operation_id: "operation-1" }), {
      status: 202,
      headers: { "Content-Type": "application/json" }
    }));
    vi.stubGlobal("fetch", request);

    await expect(runPromotionMutation({
      resource: "promotion",
      id: "candidate 1",
      expectedCandidateRevision: 7,
      idempotencyKey: "request-1",
      body: { rationale: "Every required gate passed with inspectable evidence." }
    })).resolves.toEqual({ operation_id: "operation-1" });

    const [url, init] = request.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/candidates/candidate%201/promote");
    expect(init.headers).toMatchObject({ "Idempotency-Key": "request-1" });
    expect(JSON.parse(String(init.body))).toEqual({
      actor: "standalone-reviewer",
      expected_candidate_revision: 7,
      rationale: "Every required gate passed with inspectable evidence."
    });
  });

  it("preserves typed problem codes in action failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: "STALE_CANDIDATE_REVISION",
      detail: "The candidate changed after this screen loaded."
    }), { status: 409, headers: { "Content-Type": "application/problem+json" } })));

    await expect(runPromotionMutation({
      resource: "evaluation",
      id: "candidate-1",
      expectedCandidateRevision: 2,
      idempotencyKey: "request-2"
    })).rejects.toThrow(/STALE_CANDIDATE_REVISION/);
  });
});
