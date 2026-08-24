import { EmptyState, ScreenIntro, StatusMark, TechnicalReference } from "../components.js";
import { governedCopyBody } from "../governed-copy.js";
import { humanize } from "../format.js";
import type { DashboardViewModel } from "../types.js";

const comparisonSymbols: Record<string, string> = {
  eq: "=", equals: "=", gt: ">", gte: "≥", lt: "<", lte: "≤"
};

export function ContractView({ data }: { data: DashboardViewModel }) {
  return (
    <div className="pcp-view">
      <ScreenIntro
        eyebrow="CONTRACT / IMMUTABLE POLICY"
        title="Criteria and policies"
        line1={governedCopyBody.screens.contract.line1}
        line2={governedCopyBody.screens.contract.line2}
      />
      {data.policies.length === 0 ? (
        <EmptyState>No promotion policies are assigned in this snapshot.</EmptyState>
      ) : data.policies.map((policy, policyIndex) => (
        <section className="pcp-policy-sheet" key={policy.id}>
          <header>
            <span className="pcp-card-index">{String(policyIndex + 1).padStart(2, "0")}</span>
            <div>
              <p className="pcp-eyebrow">POLICY VERSION {policy.version}</p>
              <h2>{policy.name}</h2>
              <TechnicalReference label="SHA-256" value={policy.hash} />
            </div>
            <dl>
              <div><dt>Required weighted score</dt><dd>{policy.minimumWeightedScore === 0 ? "Not required" : `${policy.minimumWeightedScore} of 100`}</dd></div>
              <div><dt>Lifecycle approvals</dt><dd>{policy.requiredLifecycleApprovals === 0 ? "Not required" : policy.requiredLifecycleApprovals}</dd></div>
            </dl>
          </header>
          <ol className="pcp-policy-stages" aria-label={`${policy.name} lifecycle stages`}>
            {policy.lifecycleStages.map((stage, index) => (
              <li key={`${stage}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span>{humanize(stage)}</li>
            ))}
          </ol>
          {policy.criteria.length === 0 ? (
            <EmptyState>Nothing is required. All empty requirement sets evaluate as satisfied.</EmptyState>
          ) : (
            <div className="pcp-table-wrap">
              <table className="pcp-table">
                <thead><tr><th>Criterion</th><th>Role</th><th>Proof contract</th><th>Evaluator</th></tr></thead>
                <tbody>
                  {policy.criteria.map((criterion) => (
                    <tr key={criterion.id}>
                      <th scope="row" data-label="Criterion">
                        <strong>{criterion.name}</strong>
                        <span>{humanize(criterion.category)} · Version {criterion.version}</span>
                        {criterion.description ? <span>{criterion.description}</span> : null}
                        {criterion.proofMeaning ? <span>Proof: {criterion.proofMeaning}</span> : null}
                        {criterion.contentHash ? <TechnicalReference label="Criterion SHA-256" value={criterion.contentHash} /> : null}
                      </th>
                      <td data-label="Role">
                        <StatusMark tone={criterion.kind === "HARD_GATE" ? "decision" : "comparison"} compact>{criterion.kind === "HARD_GATE" ? "Hard gate" : "Weighted"}</StatusMark>
                        <span>Weight: {criterion.weight === null ? "Not applicable" : criterion.weight.toFixed(2)}</span>
                      </td>
                      <td data-label="Proof contract">
                        <strong>{comparisonSymbols[criterion.comparisonOperator] ?? criterion.comparisonOperator} {criterion.threshold}{criterion.measurementUnit ? ` ${criterion.measurementUnit}` : " · unit not reported"}</strong>
                        <span>{criterion.minimumSamples === 0 ? "No samples required" : `${criterion.minimumSamples} samples required`}</span>
                        <span>{criterion.evidenceRequirements.length === 0 ? "No evidence artifact required" : criterion.evidenceRequirements.join(", ")}</span>
                      </td>
                      <td data-label="Evaluator">
                        <strong>{criterion.evaluator}</strong>
                        {criterion.evaluatorType ? <span>{humanize(criterion.evaluatorType)}</span> : null}
                        <span>{humanize(criterion.aggregation)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
