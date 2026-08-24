export type PromotionRouteName =
  | "overview"
  | "candidates"
  | "candidate"
  | "evaluations"
  | "evaluation"
  | "contract"
  | "automation"
  | "registry"
  | "registry-agent"
  | "audit";

export interface PromotionRoute {
  name: PromotionRouteName;
  id?: string;
}

export const promotionNavigation = [
  { index: "01", label: "Overview", path: "/" },
  { index: "02", label: "Candidates", path: "/candidates" },
  { index: "03", label: "Evaluations", path: "/evaluations" },
  { index: "04", label: "Promotion contract", path: "/contract" },
  { index: "05", label: "Automation", path: "/automation" },
  { index: "06", label: "Registry", path: "/registry" },
  { index: "07", label: "Audit", path: "/audit" }
] as const;

export function parsePromotionRoute(pathname: string): PromotionRoute {
  const path = pathname.split("?")[0]?.replace(/\/+$/, "") || "/";
  const parts = path.split("/").filter(Boolean);

  if (parts[0] === "agents" && parts[1] === "promotion") {
    parts.splice(0, 2);
  }

  if (parts.length === 0) return { name: "overview" };
  if (parts[0] === "candidates" && parts[1]) return { name: "candidate", id: parts[1] };
  if (parts[0] === "candidates") return { name: "candidates" };
  if (parts[0] === "evaluations" && parts[1]) return { name: "evaluation", id: parts[1] };
  if (parts[0] === "evaluations") return { name: "evaluations" };
  if (parts[0] === "contract") return { name: "contract" };
  if (parts[0] === "automation") return { name: "automation" };
  if (parts[0] === "registry" && parts[1]) return { name: "registry-agent", id: parts[1] };
  if (parts[0] === "registry") return { name: "registry" };
  if (parts[0] === "audit") return { name: "audit" };
  return { name: "overview" };
}

export function candidateRoute(id: string): string {
  return `/candidates/${encodeURIComponent(id)}`;
}

export function evaluationRoute(id: string): string {
  return `/evaluations/${encodeURIComponent(id)}`;
}

export function registryAgentRoute(id: string): string {
  return `/registry/${encodeURIComponent(id)}`;
}
