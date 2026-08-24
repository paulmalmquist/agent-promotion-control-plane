from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from promotion_control_plane.application.errors import conflict
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import IdempotencyReceipt


def prior_response(
    session: Session, scope: str, key: str, request: dict[str, Any]
) -> tuple[int, dict[str, Any], UUID] | None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"{scope}\u001f{key}"},
    )
    request_hash = content_hash(request)
    receipt = session.scalar(
        select(IdempotencyReceipt).where(
            IdempotencyReceipt.scope == scope, IdempotencyReceipt.idempotency_key == key
        )
    )
    if receipt is None:
        return None
    if receipt.request_hash != request_hash:
        raise conflict(
            "IDEMPOTENCY_KEY_REUSED",
            "This idempotency key was already used with a different request body.",
        )
    return receipt.response_status, receipt.response_body, receipt.correlation_id


def record_response(
    session: Session,
    scope: str,
    key: str,
    request: dict[str, Any],
    status: int,
    body: dict[str, Any],
    correlation_id: UUID,
) -> None:
    session.add(
        IdempotencyReceipt(
            scope=scope,
            idempotency_key=key,
            request_hash=content_hash(request),
            response_status=status,
            response_body=body,
            correlation_id=correlation_id,
        )
    )
