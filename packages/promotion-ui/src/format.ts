import type {
  CandidateViewModel,
  GateVerdict,
  RegistryActivationState,
  ScheduleConnectionState
} from "./types.js";

export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatScore(value: number | null): string {
  return value === null ? "Not required" : `${value.toFixed(1)} of 100`;
}

export function formatUtc(value: string | null): string {
  if (!value) return "Never observed";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown time";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short"
  }).format(date);
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export type VisualTone = "neutral" | "decision" | "comparison" | "degraded" | "stop";

export function blockerTone(candidate: CandidateViewModel): VisualTone {
  const code = candidate.blockerCode?.toUpperCase() ?? "";
  if (code.includes("SAFETY") || code.includes("AUTHORIZATION")) return "stop";
  return candidate.status === "BLOCKED" || candidate.status === "SUSPENDED"
    ? "degraded"
    : "neutral";
}

export function gateTone(verdict: GateVerdict): VisualTone {
  if (verdict === "FAILED") return "degraded";
  if (verdict === "REMAINING") return "degraded";
  return "neutral";
}

export function activationTone(state: RegistryActivationState): VisualTone {
  if (state === "PENDING") return "decision";
  if (state === "FAILED") return "degraded";
  return "neutral";
}

export function connectionTone(state: ScheduleConnectionState): VisualTone {
  if (state === "DISCONNECTED" || state === "DEGRADED") return "degraded";
  return "neutral";
}
