from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from promotion_control_plane.adapters.detectors import DETERMINISTIC_DETECTORS
from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.readiness import calculate_candidate_readiness
from promotion_control_plane.application.schedules import next_expected_trigger
from promotion_control_plane.application.snapshots import build_evaluation_snapshot
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import (
    AgentVersion,
    Blocker,
    Candidate,
    CandidateComponent,
    Criterion,
    Decision,
    DetectorEvidence,
    DetectorRevision,
    DetectorRun,
    EvaluationPlan,
    EvaluationPlanItem,
    EvaluationResult,
    EvaluationRun,
    EvidenceArtifact,
    IdempotencyReceipt,
    Policy,
    PolicyAssignment,
    PromotedAgent,
    PromotionEvent,
    RegistryOperation,
    ScheduledJob,
    ScheduledJobRun,
)

SEED_NAMESPACE = uuid5(NAMESPACE_URL, "agent-promotion-control-plane:demo:v1")
DEFAULT_STAGES = [
    "DISCOVERED",
    "CANDIDATE",
    "EVALUATING",
    "ELIGIBLE",
    "SHADOW",
    "PROMOTED",
    "MONITORED",
]
DEMO_CLOCK = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def seeded_uuid(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, name)


CRITERIA = (
    {
        "key": "authorization-boundary",
        "name": "Authorization boundary",
        "category": "authorization",
        "hard": True,
        "threshold": Decimal("1"),
        "operator": "eq",
        "weight": None,
        "samples": 0,
        "evidence": ["authority-test"],
    },
    {
        "key": "safety-behavior",
        "name": "Safety behavior",
        "category": "safety",
        "hard": True,
        "threshold": Decimal("0.95"),
        "operator": "gte",
        "weight": None,
        "samples": 20,
        "evidence": ["safety-suite"],
    },
    {
        "key": "p95-latency",
        "name": "95th percentile latency",
        "category": "performance",
        "hard": True,
        "threshold": Decimal("2.5"),
        "operator": "lte",
        "weight": None,
        "samples": 20,
        "evidence": ["latency-trace"],
    },
    {
        "key": "task-quality",
        "name": "Task quality",
        "category": "quality",
        "hard": False,
        "threshold": Decimal("0.85"),
        "operator": "gte",
        "weight": Decimal("0.6"),
        "samples": 20,
        "evidence": ["quality-cases"],
    },
    {
        "key": "operational-reliability",
        "name": "Operational reliability",
        "category": "reliability",
        "hard": False,
        "threshold": Decimal("0.9"),
        "operator": "gte",
        "weight": Decimal("0.4"),
        "samples": 20,
        "evidence": ["reliability-log"],
    },
)


def _policy_payload() -> dict[str, object]:
    return {
        "id": "default-demo-policy",
        "version": "1.0.0",
        "minimum_weighted_score": "85",
        "required_lifecycle_approvals": 0,
        "lifecycle_stages": DEFAULT_STAGES,
        "criteria": CRITERIA,
    }


def _add_evaluation(
    session: Session,
    candidate: Candidate,
    policy: Policy,
    criteria: list[Criterion],
    scores: dict[str, tuple[Decimal, Decimal, int, list[str]]],
    *,
    status: str = "SUCCEEDED",
) -> EvaluationRun:
    plan_snapshot = {
        "candidate": candidate.slug,
        "policy_hash": policy.content_hash,
        "criterion_ids": [str(item.id) for item in criteria],
    }
    plan = EvaluationPlan(
        id=seeded_uuid(f"plan:{candidate.slug}"),
        candidate_id=candidate.id,
        policy_id=policy.id,
        version=1,
        content_hash=content_hash(plan_snapshot),
        active=True,
        snapshot=plan_snapshot,
    )
    session.add(plan)
    session.flush()
    for criterion in criteria:
        raw, normalized, samples, evidence = scores.get(
            criterion.criterion_key, (Decimal("0"), Decimal("0"), 0, [])
        )
        item = EvaluationPlanItem(
            id=seeded_uuid(f"plan-item:{candidate.slug}:{criterion.criterion_key}"),
            plan_id=plan.id,
            criterion_id=criterion.id,
            evaluator_key="deterministic-rule",
            evaluator_version="1.0.0",
            evaluator_hash=content_hash({"provider": "deterministic-rule", "version": "1.0.0"}),
            configuration={
                "inputs": {"value": str(raw), "sample_count": samples},
                "evaluator_configuration": {
                    "field": "value",
                    "normalized_score": str(normalized),
                    "evidence_codes": evidence,
                    "unit": "seconds" if criterion.criterion_key == "p95-latency" else None,
                },
            },
        )
        session.add(item)
    run = EvaluationRun(
        id=seeded_uuid(f"evaluation-run:{candidate.slug}"),
        plan_id=plan.id,
        candidate_id=candidate.id,
        status=status,
        request_idempotency_key=f"seed:{candidate.slug}:evaluation",
        available_at=(DEMO_CLOCK if status == "SUCCEEDED" else DEMO_CLOCK + timedelta(days=3650)),
        started_at=(
            DEMO_CLOCK - timedelta(minutes=9) if status in {"RUNNING", "SUCCEEDED"} else None
        ),
        completed_at=DEMO_CLOCK - timedelta(minutes=8) if status == "SUCCEEDED" else None,
    )
    session.add(run)
    session.flush()
    if status in {"SUCCEEDED", "RUNNING"}:
        for criterion in criteria:
            if criterion.criterion_key not in scores:
                continue
            raw, normalized, samples, evidence = scores[criterion.criterion_key]
            session.add(
                EvaluationResult(
                    id=seeded_uuid(f"result:{candidate.slug}:{criterion.criterion_key}"),
                    evaluation_run_id=run.id,
                    criterion_id=criterion.id,
                    measurement_type="number",
                    measurement_value=raw,
                    measurement_unit="seconds"
                    if criterion.criterion_key == "p95-latency"
                    else None,
                    normalized_score=normalized,
                    cost_usd=Decimal("0"),
                    latency_ms=(
                        raw * Decimal("1000") if criterion.criterion_key == "p95-latency" else None
                    ),
                    sample_count=samples,
                    valid=True,
                    stale=False,
                    evidence_codes=evidence,
                    measurements={"raw_value": str(raw), "normalized_score": str(normalized)},
                    provider_metadata={"provider": "deterministic-demo", "cost": "0"},
                    created_at=DEMO_CLOCK - timedelta(minutes=8),
                )
            )
    if status == "RUNNING":
        run.lease_owner = "demo-evaluation-worker"
        run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        run.heartbeat_at = datetime.now(UTC)
        run.attempt_count = 1
    session.flush()
    _, candidate.current_evaluation_snapshot_hash = build_evaluation_snapshot(session, candidate.id)
    return run


def _passing_scores() -> dict[str, tuple[Decimal, Decimal, int, list[str]]]:
    return {
        "authorization-boundary": (Decimal("1"), Decimal("1"), 0, ["authority-test"]),
        "safety-behavior": (Decimal("0.99"), Decimal("0.99"), 40, ["safety-suite"]),
        "p95-latency": (Decimal("1.8"), Decimal("0.96"), 40, ["latency-trace"]),
        "task-quality": (Decimal("0.94"), Decimal("0.94"), 40, ["quality-cases"]),
        "operational-reliability": (
            Decimal("0.97"),
            Decimal("0.97"),
            40,
            ["reliability-log"],
        ),
    }


def _seed_registry_version(
    session: Session,
    candidate: Candidate,
    policy: Policy,
    snapshot_hash: str,
    correlation_id: UUID,
    causation_id: UUID | None = None,
    monitored: bool = False,
) -> PromotionEvent:
    decision_snapshot = {"seed": True, "candidate": candidate.slug}
    decision = Decision(
        id=seeded_uuid(f"promotion-decision:{candidate.slug}"),
        candidate_id=candidate.id,
        decision_type="PROMOTION",
        outcome="APPROVED",
        actor="demo-seed",
        rationale="Seeded example of a successful registry activation.",
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=snapshot_hash,
        snapshot_hash=content_hash(decision_snapshot),
        snapshot=decision_snapshot,
    )
    session.add(decision)
    session.flush()
    token = content_hash({"seed-version": candidate.slug})
    operation = RegistryOperation(
        id=seeded_uuid(f"registry-operation:{candidate.slug}"),
        candidate_id=candidate.id,
        decision_id=decision.id,
        status="SUCCEEDED",
        publication_token=token,
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=snapshot_hash,
        correlation_id=correlation_id,
        request_snapshot=decision_snapshot,
        attempt_count=1,
        external_version_id=f"demo-{candidate.slug}-v1",
        completed_at=DEMO_CLOCK - timedelta(days=2),
    )
    session.add(operation)
    session.flush()
    agent = PromotedAgent(
        id=seeded_uuid(f"agent:{candidate.slug}"),
        candidate_id=candidate.id,
        registry_key=candidate.slug,
        display_name=candidate.name,
    )
    session.add(agent)
    session.flush()
    version = AgentVersion(
        id=seeded_uuid(f"agent-version:{candidate.slug}:1"),
        promoted_agent_id=agent.id,
        candidate_id=candidate.id,
        registry_operation_id=operation.id,
        publication_token=token,
        version=1,
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=snapshot_hash,
        external_version_id=operation.external_version_id or "",
        snapshot={"seed": True, "monitored": monitored},
    )
    session.add(version)
    session.flush()
    agent.active_version_id = version.id
    approved = emit_event(
        session,
        "PROMOTION_APPROVED",
        "demo-seed",
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        registry_operation_id=operation.id,
        causation_id=causation_id,
        payload={"stage": "ELIGIBLE", "status": "PROMOTION_PENDING"},
    )
    queued = emit_event(
        session,
        "PROMOTION_REGISTRY_QUEUED",
        "demo-seed",
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        causation_id=approved.id,
        registry_operation_id=operation.id,
        payload={"activation_state": "PENDING"},
    )
    return emit_event(
        session,
        "PROMOTED",
        "demo-registry-worker",
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        causation_id=queued.id,
        registry_operation_id=operation.id,
        payload={
            "activation_state": "SUCCEEDED",
            "stage": "PROMOTED",
            "status": "ACTIVE",
            "candidate_revision": candidate.revision,
        },
    )


def seed_if_empty(session: Session, *, commit: bool = True) -> bool:
    if session.scalar(select(Candidate.id).limit(1)) is not None:
        return False
    policy_payload = _policy_payload()
    policy = Policy(
        id=seeded_uuid("policy:default-demo-policy:1.0.0"),
        policy_key="default-demo-policy",
        version="1.0.0",
        name="Portable demo promotion contract",
        content_hash=content_hash(policy_payload),
        minimum_weighted_score=Decimal("85"),
        required_lifecycle_approvals=0,
        lifecycle_stages=DEFAULT_STAGES,
        configuration={
            "demo": True,
            "production_recommendation": {"required_lifecycle_approvals": 1},
        },
    )
    session.add(policy)
    detector_payload = {
        "id": "portfolio-signal-detectors",
        "version": "1.0.0",
        "signals": [
            "REPEATED_SUCCESSFUL_SKILL_USAGE",
            "RECURRING_MULTI_SKILL_WORKFLOW",
            "HIGH_MANUAL_INVOCATION_FREQUENCY",
            "REPEATED_HUMAN_WORKAROUND",
            "STRONG_EVALUATION_HISTORY",
            "CAPABILITY_COVERAGE_GAP",
            "RECURRING_OPERATIONAL_TRIGGER",
            "STABLE_SKILL_BUNDLE_SYNTHESIS",
        ],
    }
    detector = DetectorRevision(
        id=seeded_uuid("detector:portfolio:1.0.0"),
        detector_key="portfolio-signal-detectors",
        version="1.0.0",
        content_hash=content_hash(detector_payload),
        configuration=detector_payload,
    )
    session.add(detector)
    session.flush()
    criteria: list[Criterion] = []
    for ordinal, configured in enumerate(CRITERIA, start=1):
        criterion_payload = {**configured, "policy_hash": policy.content_hash, "version": "1.0.0"}
        criterion = Criterion(
            id=seeded_uuid(f"criterion:{configured['key']}:1.0.0"),
            policy_id=policy.id,
            criterion_key=str(configured["key"]),
            version="1.0.0",
            category=str(configured["category"]),
            evaluator_type="deterministic-rule",
            name=str(configured["name"]),
            description=f"Demo criterion for {configured['name']}.",
            hard_gate=bool(configured["hard"]),
            threshold=configured["threshold"],
            comparison_operator=str(configured["operator"]),
            weight=configured["weight"],
            minimum_samples=int(str(configured["samples"])),
            required_evidence=configured["evidence"],
            aggregation_rule="sample_weighted_mean",
            content_hash=content_hash(criterion_payload),
            ordinal=ordinal,
        )
        session.add(criterion)
        criteria.append(criterion)
    session.flush()

    examples = (
        ("evidence-router", "Evidence Router", "DISCOVERED", "ACTIVE", Decimal("18")),
        ("invoice-reconciliation", "Invoice Reconciliation", "CANDIDATE", "ACTIVE", Decimal("31")),
        ("access-review-drafter", "Access Review Drafter", "EVALUATING", "ACTIVE", Decimal("64")),
        ("support-triage", "Support Triage", "EVALUATING", "BLOCKED", Decimal("73")),
        ("deployment-advisor", "Deployment Advisor", "EVALUATING", "BLOCKED", Decimal("96")),
        ("renewal-briefing", "Renewal Briefing", "ELIGIBLE", "ACTIVE", Decimal("100")),
        ("incident-summarizer", "Incident Summarizer", "PROMOTED", "ACTIVE", Decimal("100")),
        ("vendor-risk-monitor", "Vendor Risk Monitor", "MONITORED", "SUSPENDED", Decimal("100")),
    )
    now = DEMO_CLOCK
    for index, (slug, name, stage, status, readiness) in enumerate(examples):
        candidate = Candidate(
            id=seeded_uuid(f"candidate:{slug}"),
            slug=slug,
            name=name,
            summary=f"Deterministic lifecycle example for {name.lower()}.",
            candidate_type="AUTONOMOUS_AGENT",
            discovered_at=now - timedelta(days=14 - index),
            discovered_by="portfolio-signal-detectors@1.0.0",
            detector_revision_id=detector.id,
            discovery_source="deterministic portfolio telemetry",
            proposed_capability=f"Coordinate the governed {name.lower()} workflow.",
            rationale="Repeated successful work suggests a stable autonomous capability.",
            confidence=Decimal("0.92"),
            stage=stage,
            status=status,
            revision=1,
            active_policy_id=policy.id,
            current_policy_version=policy.version,
            readiness_percentage=readiness,
            source_metadata={"fixture": slug, "credentials_required": False},
        )
        session.add(candidate)
        session.flush()
        correlation_id = seeded_uuid(f"correlation:{slug}")
        last_candidate_event = emit_event(
            session,
            "CANDIDATE_DISCOVERED",
            "demo-seed",
            correlation_id,
            candidate_id=candidate.id,
            policy_hash=policy.content_hash,
            payload={
                "stage": "DISCOVERED",
                "status": "ACTIVE",
                "candidate_revision": candidate.revision,
                "signal": "REPEATED_SUCCESSFUL_SKILL_USAGE",
            },
        )
        session.add(
            CandidateComponent(
                id=seeded_uuid(f"component:{slug}:prompt"),
                candidate_id=candidate.id,
                component_type="PROMPT",
                name=f"{name} operating instructions",
                version="1.0.0",
                content_hash=content_hash({"candidate": slug, "component": "prompt"}),
                configuration={"portable": True},
            )
        )
        session.add(
            PolicyAssignment(
                id=seeded_uuid(f"assignment:{slug}"),
                candidate_id=candidate.id,
                policy_id=policy.id,
                assigned_by="demo-seed",
            )
        )
        detector_run = DetectorRun(
            id=seeded_uuid(f"detector-run:{slug}"),
            detector_revision_id=detector.id,
            status="SUCCEEDED",
            started_at=now - timedelta(days=14 - index, minutes=2),
            completed_at=now - timedelta(days=14 - index, minutes=1),
            signals_snapshot={"candidate": slug, "deterministic": True},
        )
        session.add(detector_run)
        session.flush()
        session.add(
            DetectorEvidence(
                id=seeded_uuid(f"detector-evidence:{slug}"),
                detector_run_id=detector_run.id,
                candidate_id=candidate.id,
                signal_type="REPEATED_SUCCESSFUL_SKILL_USAGE",
                score=Decimal("0.92"),
                evidence={"successful_runs": 18 + index, "source": "demo-fixture"},
                rank=1,
            )
        )
        session.add(
            EvidenceArtifact(
                id=seeded_uuid(f"artifact:{slug}:detector-signal"),
                candidate_id=candidate.id,
                artifact_type="DETECTOR_SIGNAL_SNAPSHOT",
                uri=f"demo://evidence/{slug}/detector-signal.json",
                sha256=content_hash({"candidate": slug, "signal": "successful-skill-usage"}),
                media_type="application/json",
                sanitized=True,
                metadata_snapshot={"detector_run_id": str(detector_run.id), "fixture": True},
            )
        )
        if slug == "invoice-reconciliation":
            waiting_run = _add_evaluation(session, candidate, policy, criteria, {}, status="QUEUED")
            waiting_run.correlation_id = correlation_id
            planned_event = emit_event(
                session,
                "EVALUATION_PLANNED",
                "demo-seed",
                correlation_id,
                candidate_id=candidate.id,
                evaluation_run_id=waiting_run.id,
                policy_hash=policy.content_hash,
                causation_id=last_candidate_event.id,
                payload={"stage": candidate.stage, "status": candidate.status},
            )
            last_candidate_event = emit_event(
                session,
                "EVALUATION_QUEUED",
                "demo-seed",
                correlation_id,
                candidate_id=candidate.id,
                evaluation_run_id=waiting_run.id,
                policy_hash=policy.content_hash,
                causation_id=planned_event.id,
                payload={"stage": candidate.stage, "status": candidate.status},
            )
            waiting_run.causation_event_id = last_candidate_event.id
        if stage not in {"DISCOVERED", "CANDIDATE"}:
            scores = _passing_scores()
            run_status = "SUCCEEDED"
            if slug == "access-review-drafter":
                scores = {
                    key: value
                    for key, value in scores.items()
                    if key in {"authorization-boundary", "safety-behavior"}
                }
                run_status = "RUNNING"
            if slug == "support-triage":
                scores["task-quality"] = (Decimal("0.91"), Decimal("0.91"), 7, [])
            if slug == "deployment-advisor":
                scores["p95-latency"] = (Decimal("4.2"), Decimal("0.2"), 40, ["latency-trace"])
                scores["task-quality"] = (Decimal("0.99"), Decimal("0.99"), 40, ["quality-cases"])
                scores["operational-reliability"] = (
                    Decimal("0.99"),
                    Decimal("0.99"),
                    40,
                    ["reliability-log"],
                )
            run = _add_evaluation(session, candidate, policy, criteria, scores, status=run_status)
            session.flush()
            run.correlation_id = correlation_id
            planned_event = emit_event(
                session,
                "EVALUATION_PLANNED",
                "demo-seed",
                correlation_id,
                candidate_id=candidate.id,
                evaluation_run_id=run.id,
                policy_hash=policy.content_hash,
                causation_id=last_candidate_event.id,
                payload={"stage": "EVALUATING", "status": candidate.status},
            )
            last_candidate_event = emit_event(
                session,
                "EVALUATION_RUNNING" if run_status == "RUNNING" else "EVALUATION_COMPLETED",
                "demo-evaluation-worker",
                correlation_id,
                candidate_id=candidate.id,
                evaluation_run_id=run.id,
                policy_hash=policy.content_hash,
                causation_id=planned_event.id,
                payload={
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                    "readiness_percentage": str(candidate.readiness_percentage),
                },
            )
            run.causation_event_id = last_candidate_event.id
            session.add(
                EvidenceArtifact(
                    id=seeded_uuid(f"artifact:{slug}:evaluation-report"),
                    candidate_id=candidate.id,
                    evaluation_run_id=run.id,
                    artifact_type="EVALUATION_REPORT",
                    uri=f"demo://evidence/{slug}/evaluation-report.json",
                    sha256=content_hash({"candidate": slug, "run": str(run.id), "scores": scores}),
                    media_type="application/json",
                    sanitized=True,
                    metadata_snapshot={"provider": "deterministic-demo", "raw_response": False},
                )
            )
            session.flush()
            evaluation_snapshot, evaluation_snapshot_hash = build_evaluation_snapshot(
                session, candidate.id
            )
            candidate.current_evaluation_snapshot_hash = evaluation_snapshot_hash
            snapshot = {
                "candidate_id": str(candidate.id),
                "evaluation_run_id": str(run.id),
                "policy_hash": policy.content_hash,
                "evaluation_snapshot_hash": candidate.current_evaluation_snapshot_hash,
                "evaluation_snapshot": evaluation_snapshot,
            }
            eligible = slug not in {
                "access-review-drafter",
                "support-triage",
                "deployment-advisor",
            }
            if run_status == "SUCCEEDED":
                decision = Decision(
                    id=seeded_uuid(f"eligibility-decision:{slug}"),
                    candidate_id=candidate.id,
                    decision_type="ELIGIBILITY",
                    outcome="ELIGIBLE" if eligible else "BLOCKED",
                    actor="gate-engine",
                    rationale=(
                        "All active-plan requirements passed."
                        if eligible
                        else "At least one required gate or evidence requirement remains blocked."
                    ),
                    policy_hash=policy.content_hash,
                    evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash or "",
                    snapshot_hash=content_hash(snapshot),
                    snapshot=snapshot,
                )
                session.add(decision)
                session.flush()
                last_candidate_event = emit_event(
                    session,
                    "ELIGIBILITY_DECIDED",
                    "gate-engine",
                    correlation_id,
                    candidate_id=candidate.id,
                    evaluation_run_id=run.id,
                    policy_hash=policy.content_hash,
                    causation_id=last_candidate_event.id,
                    payload={
                        "decision_id": str(decision.id),
                        "outcome": decision.outcome,
                        "stage": candidate.stage,
                        "status": candidate.status,
                        "candidate_revision": candidate.revision,
                        "readiness_percentage": str(candidate.readiness_percentage),
                    },
                )
        if slug == "support-triage":
            session.add(
                Blocker(
                    id=seeded_uuid("blocker:support-triage:samples"),
                    candidate_id=candidate.id,
                    code="EVALUATION_SAMPLES_INCOMPLETE",
                    category="EVIDENCE",
                    title="Run more quality samples",
                    explanation="Seven of twenty required quality samples are valid. Promotion stays unavailable.",
                    recovery="Run thirteen more quality cases. This does not change production selection.",
                    details={"required": 20, "observed": 7},
                )
            )
            last_candidate_event = emit_event(
                session,
                "BLOCKER_ADDED",
                "gate-engine",
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=last_candidate_event.id,
                payload={
                    "code": "EVALUATION_SAMPLES_INCOMPLETE",
                    "stage": candidate.stage,
                    "status": candidate.status,
                },
            )
        if slug == "deployment-advisor":
            session.add(
                Blocker(
                    id=seeded_uuid("blocker:deployment-advisor:latency"),
                    candidate_id=candidate.id,
                    code="HARD_GATE_P95_LATENCY_FAILED",
                    category="PERFORMANCE",
                    title="Latency hard gate failed",
                    explanation="The 4.2-second latency result exceeds the 2.5-second maximum. High quality cannot offset it.",
                    recovery="Reduce latency and rerun the active plan. This retry leaves production selection unchanged.",
                    details={"maximum_seconds": "2.5", "observed_seconds": "4.2"},
                )
            )
            last_candidate_event = emit_event(
                session,
                "BLOCKER_ADDED",
                "gate-engine",
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=last_candidate_event.id,
                payload={
                    "code": "HARD_GATE_P95_LATENCY_FAILED",
                    "stage": candidate.stage,
                    "status": candidate.status,
                },
            )
        if slug == "vendor-risk-monitor":
            session.add(
                Blocker(
                    id=seeded_uuid("blocker:vendor-risk-monitor:regression"),
                    candidate_id=candidate.id,
                    code="POST_PROMOTION_REGRESSION",
                    category="MONITORING",
                    title="Monitoring found a reliability regression",
                    explanation="The control plane suspended new selection after reliability fell below its monitoring floor.",
                    recovery="Investigate the regression before restoring selection. Existing evidence remains available.",
                    details={"observed": "0.81", "floor": "0.90"},
                )
            )
        candidate.readiness_percentage = calculate_candidate_readiness(
            session, candidate.id
        ).readiness_percentage
        promoted_event: PromotionEvent | None = None
        if slug in {"incident-summarizer", "vendor-risk-monitor"}:
            promoted_event = _seed_registry_version(
                session,
                candidate,
                policy,
                candidate.current_evaluation_snapshot_hash or "",
                correlation_id,
                last_candidate_event.id,
                slug == "vendor-risk-monitor",
            )
        if slug == "vendor-risk-monitor":
            assert promoted_event is not None
            regression = emit_event(
                session,
                "POST_PROMOTION_REGRESSION_DETECTED",
                "monitoring-worker",
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=promoted_event.id,
                payload={"code": "POST_PROMOTION_REGRESSION", "stage": "MONITORED"},
            )
            blocker_added = emit_event(
                session,
                "BLOCKER_ADDED",
                "monitoring-worker",
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=regression.id,
                payload={
                    "code": "POST_PROMOTION_REGRESSION",
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            emit_event(
                session,
                "CANDIDATE_SUSPENDED",
                "monitoring-worker",
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=blocker_added.id,
                payload={
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )

    schedule_specs = (
        (
            "nightly-candidate-discovery",
            "Nightly candidate discovery",
            "GitHub Actions",
            "EXTERNAL_SCHEDULE",
            ".github/workflows/discovery.yml",
            "CONNECTED",
            "15 1 * * *",
        ),
        (
            "overnight-comprehensive-evaluation",
            "Overnight comprehensive evaluation",
            "Paul OS scheduler",
            "EXTERNAL_SCHEDULE",
            "agents/promotion/comprehensive",
            "DISCONNECTED",
            "0 2 * * *",
        ),
        (
            "periodic-lightweight-sweep",
            "Periodic lightweight evaluation sweep",
            "Kubernetes CronJob",
            "EXTERNAL_SCHEDULE",
            "promotion-lightweight-sweep",
            "CONNECTED",
            "0 */4 * * *",
        ),
        (
            "regression-scan",
            "Regression scan",
            "Cloud Scheduler",
            "EXTERNAL_SCHEDULE",
            "promotion-regression-scan",
            "CONNECTED",
            "30 */6 * * *",
        ),
        (
            "post-promotion-monitor",
            "Post-promotion monitor",
            "Temporal",
            "EXTERNAL_SCHEDULE",
            "promotion-post-monitor",
            "DISCONNECTED",
            "*/30 * * * *",
        ),
        (
            "promotion-eligibility-scan",
            "Promotion eligibility scan",
            "Paul OS Attention",
            "EVENT_OR_SCHEDULE",
            "attention/promotion-eligibility",
            "CONNECTED",
            "10 * * * *",
        ),
    )
    for offset, (key, name, owner, mode, reference, state, expression) in enumerate(schedule_specs):
        last_run = now - timedelta(hours=offset + 1)
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.job_key == key))
        if job is None:
            job = ScheduledJob(
                id=seeded_uuid(f"schedule:{key}"),
                job_key=key,
                version="1.0.0",
                content_hash=content_hash(
                    {
                        "key": key,
                        "owner": owner,
                        "mode": mode,
                        "reference": reference,
                        "cron": expression,
                    }
                ),
                name=name,
                description=f"Observes externally triggered {name.lower()} work.",
                trigger_owner=owner,
                trigger_mode=mode,
                owner_reference=reference,
                connection_state=state,
                timezone="America/New_York",
                schedule_expression=expression,
                grace_window_seconds=900,
                metadata_snapshot={"seeded_history": True},
            )
            session.add(job)
            session.flush()
        job.last_observed_run_at = last_run
        job.next_expected_trigger_at = next_expected_trigger(
            job.schedule_expression, job.timezone, last_run
        )
        if (
            session.scalar(
                select(ScheduledJobRun.id).where(
                    ScheduledJobRun.job_id == job.id,
                    ScheduledJobRun.trigger_idempotency_key == f"seed-history:{key}",
                )
            )
            is not None
        ):
            continue
        session.add(
            ScheduledJobRun(
                id=seeded_uuid(f"schedule-run:{key}:history"),
                job_id=job.id,
                trigger_idempotency_key=f"seed-history:{key}",
                triggered_by=owner,
                trigger_source=mode,
                status="SUCCEEDED",
                started_at=last_run - timedelta(minutes=2),
                completed_at=last_run,
                payload={"historical": True},
                result={"observed": True},
            )
        )
    if commit:
        session.commit()
    return True


def _queue_autonomous_evaluation(
    session: Session,
    candidate: Candidate,
    policy: Policy,
    criteria: list[Criterion],
    actor: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    scheduled_job_run_id: UUID | None,
    worker_max_attempts: int,
) -> Candidate:
    candidate.stage = "EVALUATING"
    candidate.status = "ACTIVE"
    candidate.revision += 1
    run = _add_evaluation(session, candidate, policy, criteria, _passing_scores(), status="QUEUED")
    run.available_at = datetime.now(UTC)
    run.correlation_id = correlation_id
    run.max_attempts = worker_max_attempts
    planned = emit_event(
        session,
        "EVALUATION_PLANNED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        causation_id=causation_id,
        evaluation_run_id=run.id,
        scheduled_job_run_id=scheduled_job_run_id,
        payload={
            "criteria_count": len(criteria),
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
        },
    )
    queued = emit_event(
        session,
        "EVALUATION_QUEUED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        causation_id=planned.id,
        evaluation_run_id=run.id,
        scheduled_job_run_id=scheduled_job_run_id,
        payload={
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
            "readiness_percentage": str(candidate.readiness_percentage),
        },
    )
    run.causation_event_id = queued.id
    session.commit()
    return candidate


def advance_autonomous_cycle(
    session: Session,
    actor: str = "demo-cycle-worker",
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    scheduled_job_run_id: UUID | None = None,
    worker_max_attempts: int = 3,
) -> Candidate:
    existing = session.scalar(select(Candidate).where(Candidate.slug == "change-risk-coordinator"))
    if existing is not None:
        active_plan = session.scalar(
            select(EvaluationPlan.id).where(
                EvaluationPlan.candidate_id == existing.id,
                EvaluationPlan.active.is_(True),
            )
        )
        if active_plan is not None:
            return existing
        existing_policy = (
            session.get(Policy, existing.active_policy_id) if existing.active_policy_id else None
        )
        if existing_policy is None:
            raise RuntimeError("The autonomous candidate lost its assigned policy")
        existing_criteria = list(
            session.scalars(
                select(Criterion)
                .where(Criterion.policy_id == existing_policy.id)
                .order_by(Criterion.ordinal)
            )
        )
        existing_correlation = UUID(
            str(existing.source_metadata.get("cycle_correlation_id") or correlation_id)
        )
        discovered_event = session.scalar(
            select(PromotionEvent)
            .where(
                PromotionEvent.candidate_id == existing.id,
                PromotionEvent.event_type == "CANDIDATE_DISCOVERED",
            )
            .order_by(PromotionEvent.sequence.desc())
            .limit(1)
        )
        return _queue_autonomous_evaluation(
            session,
            existing,
            existing_policy,
            existing_criteria,
            actor,
            existing_correlation,
            discovered_event.id if discovered_event else causation_id,
            scheduled_job_run_id,
            worker_max_attempts,
        )
    policy = session.scalar(select(Policy).where(Policy.policy_key == "default-demo-policy"))
    detector = session.scalar(
        select(DetectorRevision).where(
            DetectorRevision.detector_key == "portfolio-signal-detectors"
        )
    )
    if policy is None or detector is None:
        raise RuntimeError("Demo seed must exist before running the autonomous cycle")
    criteria = list(
        select_result
        for select_result in session.scalars(
            select(Criterion).where(Criterion.policy_id == policy.id).order_by(Criterion.ordinal)
        )
    )
    correlation_id = correlation_id or seeded_uuid("correlation:change-risk-coordinator")
    signal_source = [
        {
            "id": "demo-change-risk-workflow",
            "multi_skill_runs": 12,
            "successful_skill_uses": 28,
            "evaluation_pass_rate": "0.97",
        }
    ]
    detector_provider = next(
        detector for detector in DETERMINISTIC_DETECTORS if detector.key == "recurring-multi-skill"
    )
    detected = detector_provider.detect(signal_source)
    if not detected:
        raise RuntimeError("The deterministic demo detector did not produce its fixed signal")
    detector_run = DetectorRun(
        id=seeded_uuid("detector-run:change-risk-coordinator"),
        detector_revision_id=detector.id,
        status="SUCCEEDED",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        signals_snapshot={"source": "demo-candidate-source", "signals": signal_source},
    )
    session.add(detector_run)
    candidate = Candidate(
        id=seeded_uuid("candidate:change-risk-coordinator"),
        slug="change-risk-coordinator",
        name="Change Risk Coordinator",
        summary="Coordinates deterministic change-risk checks before governed release work.",
        candidate_type="AUTONOMOUS_AGENT",
        discovered_by="portfolio-signal-detectors@1.0.0",
        detector_revision_id=detector.id,
        discovery_source="manual autonomous demo cycle",
        proposed_capability="Coordinate change evidence, risk checks, and governed handoff.",
        rationale="A stable multi-skill workflow repeatedly completed with strong evaluation history.",
        confidence=Decimal("0.96"),
        stage="DISCOVERED",
        status="ACTIVE",
        revision=1,
        active_policy_id=policy.id,
        current_policy_version=policy.version,
        readiness_percentage=Decimal("0"),
        source_metadata={
            "autonomous_cycle": True,
            "cycle_correlation_id": str(correlation_id),
            "scheduled_job_run_id": str(scheduled_job_run_id) if scheduled_job_run_id else None,
        },
    )
    session.add(candidate)
    session.flush()
    discovered = emit_event(
        session,
        "CANDIDATE_DISCOVERED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        scheduled_job_run_id=scheduled_job_run_id,
        causation_id=causation_id,
        payload={
            "candidate_id": str(candidate.id),
            "slug": candidate.slug,
            "name": candidate.name,
            "summary": candidate.summary,
            "candidate_type": candidate.candidate_type,
            "proposed_capability": candidate.proposed_capability,
            "confidence": str(candidate.confidence),
            "signal": detected[0]["signal_type"],
            "policy_name": policy.name,
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
            "readiness_percentage": str(candidate.readiness_percentage),
        },
    )
    session.add(
        DetectorEvidence(
            id=seeded_uuid("detector-evidence:change-risk-coordinator"),
            detector_run_id=detector_run.id,
            candidate_id=candidate.id,
            signal_type=str(detected[0]["signal_type"]),
            score=Decimal(str(detected[0]["score"])),
            evidence=dict(detected[0]["evidence"]),
            rank=1,
        )
    )
    session.add(
        CandidateComponent(
            id=seeded_uuid("component:change-risk-coordinator:skill-bundle"),
            candidate_id=candidate.id,
            component_type="SKILL_BUNDLE",
            name="Change-risk governed workflow bundle",
            version="1.0.0",
            content_hash=content_hash({"skills": ["evidence", "risk", "handoff"]}),
            configuration={"portable": True, "source": "deterministic-detector"},
        )
    )
    session.add(
        EvidenceArtifact(
            id=seeded_uuid("artifact:change-risk-coordinator:detector-signal"),
            candidate_id=candidate.id,
            artifact_type="DETECTOR_SIGNAL_SNAPSHOT",
            uri="demo://evidence/change-risk-coordinator/detector-signal.json",
            sha256=content_hash({"signals": signal_source, "detected": detected}),
            media_type="application/json",
            sanitized=True,
            metadata_snapshot={
                "provider": detector_provider.key,
                "detector_run_id": str(detector_run.id),
            },
        )
    )
    # Discovery is its own durable phase so subscribers can observe it before
    # planning/evaluation work becomes visible.
    session.commit()
    reloaded_candidate = session.get(Candidate, candidate.id)
    assert reloaded_candidate is not None
    candidate = reloaded_candidate
    return _queue_autonomous_evaluation(
        session,
        candidate,
        policy,
        criteria,
        actor,
        correlation_id,
        discovered.id,
        scheduled_job_run_id,
        worker_max_attempts,
    )


def reset_demo(
    session: Session,
    *,
    commit: bool = True,
    actor: str | None = None,
    correlation_id: UUID | None = None,
) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 8_104_250_001})
    previous_reset = session.scalar(
        select(PromotionEvent)
        .where(PromotionEvent.event_type == "DEMO_RESET_COMPLETED")
        .order_by(PromotionEvent.sequence.desc())
        .limit(1)
    )
    # Reset receipts remain replayable across fixture rebuilds. Receipts for
    # every other mutation may name rows that this reset removes, so retaining
    # them would replay successful responses with dangling resource IDs.
    session.execute(
        delete(IdempotencyReceipt).where(IdempotencyReceipt.scope != "demo:reset")
    )
    session.execute(
        text(
            "TRUNCATE TABLE "
            "external_event_deliveries, agent_versions, promoted_agents, registry_operations, "
            "evidence_artifacts, scheduled_job_runs, scheduled_jobs, blockers, "
            "promotion_lifecycle_approvals, decisions, evaluation_results, evaluation_runs, "
            "evaluation_plan_items, evaluation_plans, policy_assignments, detector_evidence, "
            "detector_runs, candidate_components, candidates, criteria, policies, detector_revisions, "
            "evaluator_revisions RESTART IDENTITY CASCADE"
        )
    )
    from promotion_control_plane.infrastructure.config import import_config_directory
    from promotion_control_plane.settings import get_settings

    config_root = Path(get_settings().config_root)
    if not config_root.is_dir():
        config_root = Path(__file__).resolve().parents[5] / "configs"
    if config_root.is_dir():
        import_config_directory(session, config_root, commit=False)
    seed_if_empty(session, commit=False)
    if actor is not None:
        emit_event(
            session,
            "DEMO_RESET_COMPLETED",
            actor,
            correlation_id or seeded_uuid("correlation:demo-reset"),
            causation_id=previous_reset.id if previous_reset else None,
            payload={
                "candidate_count": 8,
                "event_history_preserved": True,
                "event_sequence_restarted": False,
            },
        )
    if commit:
        session.commit()
