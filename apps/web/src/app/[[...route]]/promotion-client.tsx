"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  createHttpPromotionDataSource,
  PromotionShell,
  type DashboardViewModel,
  type PromotionDataSource,
  type PromotionMutation
} from "@promotion-control-plane/ui";
import { runPromotionMutation } from "./actions";

export function PromotionClient({
  initialData,
  initialPath,
  liveEnabled
}: {
  initialData: DashboardViewModel;
  initialPath: string;
  liveEnabled: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname() || initialPath;
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const httpDataSource = useMemo(
    () => createHttpPromotionDataSource({
      apiBase: "/api/control",
      eventStreamUrl: "/api/events/stream"
    }),
    []
  );
  const dataSource = useMemo<PromotionDataSource>(() => ({
    query: httpDataSource.query,
    subscribe: httpDataSource.subscribe,
    async mutate<T>(mutation: PromotionMutation) {
      return runPromotionMutation(mutation) as Promise<T>;
    }
  }), [httpDataSource]);
  const refreshMaterialState = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => router.refresh(), 150);
  }, [router]);

  useEffect(() => () => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
  }, []);

  return (
    <PromotionShell
      initialData={initialData}
      currentPath={pathname}
      {...(liveEnabled ? { dataSource } : {})}
      onMaterialEvent={refreshMaterialState}
      navigate={(path) => router.push(path)}
      evidenceLink={(candidateId) => `/evidence?candidate=${encodeURIComponent(candidateId)}`}
      {...(!liveEnabled
        ? { headerSlot: <span className="pcp-demo-label">TEST FIXTURE · LIVE DATA DISABLED</span> }
        : {})}
    />
  );
}
