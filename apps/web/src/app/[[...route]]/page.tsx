import type { Metadata } from "next";
import { loadDashboard } from "@/lib/api";
import { PromotionClient } from "./promotion-client";

export const dynamic = "force-dynamic";

type PageProps = { params: Promise<{ route?: string[] }> };

function pathFromRoute(route: string[] | undefined): string {
  return route && route.length > 0 ? `/${route.join("/")}` : "/";
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { route } = await params;
  if (!route || route.length === 0) return { title: "Overview" };
  const routeTitles: Record<string, string> = {
    candidates: route.length > 1 ? "Candidate" : "Candidates",
    evaluations: route.length > 1 ? "Evaluation" : "Evaluations",
    registry: route.length > 1 ? "Registry agent" : "Registry",
    contract: "Promotion contract",
    automation: "Automation",
    audit: "Audit"
  };
  return { title: routeTitles[route[0]!] ?? "Promotion control plane" };
}

export default async function PromotionPage({ params }: PageProps) {
  const { route } = await params;
  const path = pathFromRoute(route);
  const candidateId = route?.[0] === "candidates" ? route[1] : undefined;
  const evaluationId = route?.[0] === "evaluations" ? route[1] : undefined;
  const registryAgentId = route?.[0] === "registry" ? route[1] : undefined;
  const initialData = await loadDashboard(candidateId, evaluationId, registryAgentId);
  return (
    <PromotionClient
      initialData={initialData}
      initialPath={path}
      liveEnabled={process.env.PROMOTION_UI_FIXTURE_FALLBACK !== "1"}
    />
  );
}
