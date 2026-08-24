"use server";

import type { PromotionMutation } from "@promotion-control-plane/ui";
import type { components } from "@/generated/api";

const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

function mutationPath(mutation: PromotionMutation): string {
  const id = encodeURIComponent(mutation.id);
  switch (mutation.resource) {
    case "promotion": return `/api/v1/candidates/${id}/promote`;
    case "promotion-retry": return `/api/v1/promotion-operations/${id}/retry`;
    case "evaluation": return `/api/v1/candidates/${id}/evaluate`;
    case "schedule": return `/api/v1/schedules/${id}/trigger`;
    case "demo-cycle": return "/api/v1/demo/cycle";
  }
}

type ProblemDetails = {
  code?: string;
  detail?: string;
  title?: string;
};

type MutationRequest =
  | components["schemas"]["PromoteRequest"]
  | components["schemas"]["RetryRequest"]
  | components["schemas"]["EvaluateRequest"]
  | components["schemas"]["ScheduleTriggerRequest"]
  | components["schemas"]["ActorRequest"];

function actor(mutation: PromotionMutation): string {
  return typeof mutation.body?.actor === "string" ? mutation.body.actor : "standalone-reviewer";
}

function candidateRevision(mutation: PromotionMutation): number {
  if (mutation.expectedCandidateRevision === undefined) {
    throw new Error("Candidate mutations require the expected candidate revision.");
  }
  return mutation.expectedCandidateRevision;
}

function mutationBody(mutation: PromotionMutation): MutationRequest {
  switch (mutation.resource) {
    case "promotion": {
      const rationale = mutation.body?.rationale;
      if (typeof rationale !== "string") throw new Error("Promotion requires a lifecycle rationale.");
      return {
        actor: actor(mutation),
        expected_candidate_revision: candidateRevision(mutation),
        rationale
      };
    }
    case "promotion-retry":
    case "evaluation":
      return {
        actor: actor(mutation),
        expected_candidate_revision: candidateRevision(mutation)
      };
    case "schedule":
      return {
        actor: actor(mutation),
        trigger_source: typeof mutation.body?.trigger_source === "string"
          ? mutation.body.trigger_source
          : "NEXT_SERVER_ACTION",
        payload: mutation.body?.payload && typeof mutation.body.payload === "object"
          ? mutation.body.payload as Record<string, unknown>
          : {}
      };
    case "demo-cycle":
      return { actor: actor(mutation) };
  }
}

/** Standalone governed mutations cross the Next server boundary before FastAPI. */
export async function runPromotionMutation(mutation: PromotionMutation): Promise<unknown> {
  if (!mutation.idempotencyKey) throw new Error("Every mutation requires an idempotency key.");
  const body = mutationBody(mutation);
  const response = await fetch(`${API_INTERNAL_URL}${mutationPath(mutation)}`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": mutation.idempotencyKey
    },
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => null) as ProblemDetails | unknown;
  if (!response.ok) {
    const problem = payload && typeof payload === "object" ? payload as ProblemDetails : null;
    const message = problem?.detail ?? problem?.title ?? `Control-plane request failed with status ${response.status}.`;
    throw new Error(problem?.code ? `${message} (${problem.code})` : message);
  }
  return payload;
}
