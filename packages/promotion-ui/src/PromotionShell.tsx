"use client";

import { useEffect, useMemo, useState } from "react";
import { applyPromotionEvent } from "./live.js";
import { humanize } from "./format.js";
import { governedCopyArtifact } from "./governed-copy.js";
import { parsePromotionRoute, promotionNavigation } from "./routes.js";
import { themeTokenStyle } from "./theme.js";
import type { PromotionShellProps } from "./types.js";
import { OverviewView } from "./views/overview.js";
import { CandidatesView } from "./views/candidates.js";
import { CandidateDetailView } from "./views/candidate-detail.js";
import { EvaluationDetailView, EvaluationsView } from "./views/evaluations.js";
import { ContractView } from "./views/contract.js";
import { AutomationView } from "./views/automation.js";
import { RegistryAgentDetailView, RegistryView } from "./views/registry.js";
import { AuditView } from "./views/audit.js";

export function PromotionShell({
  initialData,
  currentPath,
  dataSource,
  navigate,
  onLifecycleDecision,
  onGovernedMutation,
  onMaterialEvent,
  tokens,
  embedded = false,
  evidenceLink = (candidateId) => `/evidence?candidate=${encodeURIComponent(candidateId)}`,
  attentionLink,
  headerSlot,
  className,
  style
}: PromotionShellProps) {
  const [data, setData] = useState(initialData);
  const [previousInitialData, setPreviousInitialData] = useState(initialData);
  const [internalPath, setInternalPath] = useState(currentPath ?? "/");
  const [connectedDataSource, setConnectedDataSource] = useState<PromotionShellProps["dataSource"]>();
  if (initialData !== previousInitialData) {
    setPreviousInitialData(initialData);
    setData(initialData);
  }
  const streamConnected = Boolean(dataSource && connectedDataSource === dataSource);
  const path = currentPath ?? internalPath;
  const route = parsePromotionRoute(path);
  const activeRoot = route.name === "candidate"
    ? "candidates"
    : route.name === "evaluation"
      ? "evaluations"
      : route.name === "registry-agent"
        ? "registry"
        : route.name;

  useEffect(() => {
    if (!dataSource) return;
    const lastEvent = initialData.recentEvents.reduce((largest, event) => Math.max(largest, event.sequence), 0);
    return dataSource.subscribe(
      (event) => {
        setData((snapshot) => applyPromotionEvent(snapshot, event));
        void onMaterialEvent?.(event);
      },
      {
        ...(lastEvent > 0 ? { lastEventId: String(lastEvent) } : {}),
        onConnectionChange: (connected) => setConnectedDataSource(connected ? dataSource : undefined)
      }
    );
  }, [dataSource, initialData, onMaterialEvent]);

  const go = useMemo(() => navigate ?? ((nextPath: string) => {
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", nextPath);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
    setInternalPath(nextPath);
  }), [navigate]);

  useEffect(() => {
    if (currentPath !== undefined || typeof window === "undefined") return;
    const syncPath = () => setInternalPath(window.location.pathname);
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, [currentPath]);

  const view = (() => {
    switch (route.name) {
      case "overview": return <OverviewView data={data} navigate={go} />;
      case "candidates": return <CandidatesView data={data} navigate={go} />;
      case "candidate": return (
        <CandidateDetailView
          candidate={data.candidates.find((candidate) => candidate.id === route.id || candidate.slug === route.id)}
          navigate={go}
          evidenceLink={evidenceLink}
          embedded={embedded}
          {...(dataSource ? { dataSource } : {})}
          {...(onLifecycleDecision ? { onLifecycleDecision } : {})}
          {...(onGovernedMutation ? { onGovernedMutation } : {})}
          {...(attentionLink ? { attentionLink } : {})}
        />
      );
      case "evaluations": return <EvaluationsView data={data} navigate={go} />;
      case "evaluation": return <EvaluationDetailView run={data.evaluations.find((run) => run.id === route.id)} navigate={go} />;
      case "contract": return <ContractView data={data} />;
      case "automation": return (
        <AutomationView
          data={data}
          embedded={embedded}
          {...(dataSource ? { dataSource } : {})}
          {...(onGovernedMutation ? { onGovernedMutation } : {})}
        />
      );
      case "registry": return <RegistryView data={data} navigate={go} />;
      case "registry-agent": return (
        <RegistryAgentDetailView
          agent={data.registryAgents.find((agent) => agent.id === route.id || agent.agentId === route.id)}
          navigate={go}
        />
      );
      case "audit": return <AuditView data={data} />;
    }
  })();

  return (
    <div
      data-promotion-control-plane=""
      data-governed-copy-digest={governedCopyArtifact.digest}
      data-embedded={embedded || undefined}
      className={["pcp-shell", className].filter(Boolean).join(" ")}
      style={{ ...themeTokenStyle(tokens), ...style }}
    >
      <a className="pcp-skip-link" href="#promotion-main">Skip to promotion content</a>
      <aside className="pcp-rail" aria-label="Promotion control plane">
        <div className="pcp-wordmark">
          <span className="pcp-wordmark-mark" aria-hidden="true"><i /><i /><i /></span>
          <div><strong>AP</strong><span>CONTROL</span></div>
        </div>
        <nav aria-label="Promotion sections">
          <ol>
            {promotionNavigation.map((item) => {
              const itemName = item.path === "/" ? "overview" : item.path.slice(1).replace("contract", "contract");
              const active = activeRoot === itemName;
              return (
                <li key={item.path}>
                  <button type="button" onClick={() => go(item.path)} aria-current={active ? "page" : undefined}>
                    <span>{item.index}</span><strong>{item.label}</strong><i aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="pcp-rail-foot">
          <span>REFERENCE / 01</span>
          <p>Evidence governs promotion. Authority governs every run.</p>
        </div>
      </aside>

      <div className="pcp-workspace">
        <header className="pcp-topbar">
          <div>
            <span className="pcp-topbar-index">AGENT PROMOTION</span>
            <span className="pcp-topbar-rule" aria-hidden="true" />
            <strong>{humanize(activeRoot).toUpperCase()}</strong>
          </div>
          <div className="pcp-topbar-state">
            {headerSlot}
            {data.demoMode ? <span className="pcp-demo-label">DETERMINISTIC DEMO</span> : null}
            <span className="pcp-stream-state" data-connected={streamConnected || undefined}>
              <i aria-hidden="true" />{streamConnected ? "Event stream connected" : "Snapshot only"}
            </span>
          </div>
        </header>
        <main id="promotion-main" tabIndex={-1}>{view}</main>
      </div>
    </div>
  );
}
