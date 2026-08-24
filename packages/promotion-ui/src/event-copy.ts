import { humanize } from "./format.js";

function value(payload: Record<string, unknown>, key: string): string | null {
  const item = payload[key];
  return typeof item === "string" && item.length > 0 ? item : null;
}

export function promotionEventCopy(
  eventType: string,
  payload: Record<string, unknown>
): { headline: string; detail: string } {
  const explicitHeadline = value(payload, "headline");
  const explicitDetail = value(payload, "detail");
  if (explicitHeadline && explicitDetail) return { headline: explicitHeadline, detail: explicitDetail };

  const stage = value(payload, "stage");
  const status = value(payload, "status");
  const outcome = value(payload, "outcome");
  const code = value(payload, "code");
  const owner = value(payload, "trigger_owner");
  const provider = value(payload, "provider") ?? value(payload, "evaluator");
  const model = value(payload, "model");
  const failure = value(payload, "failure_message") ?? value(payload, "error");
  const job = value(payload, "job_key") ?? value(payload, "job_name");
  const known: Record<string, { headline: string; detail: string }> = {
    CANDIDATE_DISCOVERED: {
      headline: "Candidate discovered",
      detail: "A deterministic signal created a candidate for governed evaluation."
    },
    EVALUATION_PLANNED: {
      headline: "Evaluation planned",
      detail: "The immutable plan now binds every required criterion and evaluator."
    },
    EVALUATION_RUNNING: {
      headline: "Evaluation running",
      detail: "A leased worker is collecting typed measurements for the active plan."
    },
    EVALUATION_COMPLETED: {
      headline: "Evaluation completed",
      detail: `The worker completed evidence collection${stage ? ` and advanced the candidate to ${humanize(stage)}` : ""}.`
    },
    ELIGIBILITY_DECIDED: {
      headline: "Eligibility decided",
      detail: outcome
        ? `The gate engine recorded ${humanize(outcome)} from the exact evidence snapshot.`
        : "The gate engine recorded an outcome from the exact evidence snapshot."
    },
    PROMOTION_APPROVED: {
      headline: "Promotion lifecycle decision recorded",
      detail: "The exact approval snapshot now permits queued registry publication."
    },
    PROMOTION_REGISTRY_QUEUED: {
      headline: "Registry publication queued",
      detail: "The candidate remains eligible while the worker claims registry publication."
    },
    PROMOTION_REGISTRY_RETRY_QUEUED: {
      headline: "Registry retry queued",
      detail: "The worker will reuse the stable publication token for recovery."
    },
    PROMOTION_REGISTRY_FAILED: {
      headline: "Registry activation failed",
      detail: "Publication failed; the prior production selection remains unchanged."
    },
    PROMOTED: {
      headline: "Registry activation succeeded",
      detail: "The worker promoted the tested candidate and activated its immutable version."
    },
    BLOCKER_ADDED: {
      headline: "Promotion blocker added",
      detail: code
        ? `${humanize(code)} now stops promotion until its recovery action completes.`
        : "A policy blocker now stops promotion until its recovery action completes."
    },
    BLOCKER_CLEARED: {
      headline: "Promotion blocker cleared",
      detail: code ? `${humanize(code)} no longer stops this lifecycle decision.` : "The resolved blocker no longer stops this lifecycle decision."
    },
    SCHEDULE_TRIGGER_QUEUED: {
      headline: "External schedule work queued",
      detail: owner ? `${owner} triggered work for a leased worker.` : "The named external owner triggered work for a leased worker."
    },
    SCHEDULE_RUN_OBSERVED: {
      headline: "External schedule run observed",
      detail: owner ? `${owner} completed an observed schedule run.` : "The control plane observed an externally triggered schedule run."
    }
  };
  let fallback = known[eventType];
  if (!fallback && eventType.startsWith("EVALUATION_")) {
    fallback = {
      headline: humanize(eventType),
      detail: failure
        ? `Evaluation work stopped: ${failure}`
        : provider
          ? `${provider}${model ? ` using ${model}` : ""} reported ${humanize(status ?? outcome ?? "progress")}.`
          : `The leased worker reported ${humanize(status ?? outcome ?? "evaluation progress")}.`
    };
  }
  if (!fallback && eventType.startsWith("PROMOTION_REGISTRY_")) {
    fallback = {
      headline: humanize(eventType),
      detail: failure
        ? `Registry publication stopped: ${failure}`
        : `Registry publication reported ${humanize(status ?? outcome ?? "progress")} with the stable token.`
    };
  }
  if (!fallback && (eventType.startsWith("SCHEDULE_RUN_") || eventType.startsWith("SCHEDULE_TRIGGER_"))) {
    fallback = {
      headline: humanize(eventType),
      detail: `${owner ?? "The named external owner"} reported ${humanize(status ?? outcome ?? "progress")}${job ? ` for ${humanize(job)}` : ""}.`
    };
  }
  if (!fallback && eventType.startsWith("PROMOTION_LIFECYCLE_APPROVAL_")) {
    fallback = {
      headline: humanize(eventType),
      detail: outcome
        ? `The reviewer recorded ${humanize(outcome)} against the exact lifecycle snapshot.`
        : "The reviewer changed the lifecycle approval bound to the exact snapshot."
    };
  }
  if (!fallback && (eventType.startsWith("POST_PROMOTION_") || eventType === "CANDIDATE_SUSPENDED")) {
    fallback = {
      headline: humanize(eventType),
      detail: code
        ? `${humanize(code)} changed monitoring state to ${humanize(status ?? stage ?? "review required")}.`
        : `Post-promotion monitoring reported ${humanize(status ?? outcome ?? "a lifecycle change")}.`
    };
  }
  fallback ??= {
    headline: humanize(eventType),
    detail: stage || status || outcome || code
      ? [
          stage ? `Lifecycle stage: ${humanize(stage)}.` : "",
          status ? `Operational status: ${humanize(status)}.` : "",
          outcome ? `Outcome: ${humanize(outcome)}.` : "",
          code ? `Reason: ${humanize(code)}.` : ""
        ].filter(Boolean).join(" ")
      : `${humanize(eventType)} changed the durable promotion record.`
  };
  return {
    headline: explicitHeadline ?? fallback.headline,
    detail: explicitDetail ?? fallback.detail
  };
}
