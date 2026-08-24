import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from promotion_control_plane.api.serialization import event_view
from promotion_control_plane.application.errors import bad_request
from promotion_control_plane.infrastructure.database import get_session_factory
from promotion_control_plane.infrastructure.models import PromotionEvent
from promotion_control_plane.settings import get_settings

SessionFactory = Callable[[], Session]


def _read_events(
    after: int,
    candidate_id: UUID | None,
    limit: int = 100,
    session_factory: SessionFactory | None = None,
) -> list[PromotionEvent]:
    factory = session_factory or get_session_factory()
    with factory() as session:
        statement = select(PromotionEvent).where(PromotionEvent.sequence > after)
        if candidate_id is not None:
            statement = statement.where(PromotionEvent.candidate_id == candidate_id)
        return list(session.scalars(statement.order_by(PromotionEvent.sequence).limit(limit)))


def create_sse_router(
    *,
    session_factory: SessionFactory | None = None,
    settings_provider: Callable[[], Any] = get_settings,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/events/stream",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Sequence-backed promotion event stream.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    async def event_stream(
        request: Request,
        candidate_id: UUID | None = Query(default=None),
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            header_cursor = int(last_event_id or 0)
        except ValueError:
            raise bad_request(
                "INVALID_EVENT_CURSOR",
                "Last-Event-ID must be a non-negative event sequence.",
            ) from None
        if header_cursor < 0:
            raise bad_request(
                "INVALID_EVENT_CURSOR",
                "Last-Event-ID must be a non-negative event sequence.",
            )
        cursor = max(after, header_cursor)
        settings = settings_provider()

        async def generate() -> AsyncIterator[str]:
            nonlocal cursor
            last_write = asyncio.get_running_loop().time()
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                events = await asyncio.to_thread(
                    _read_events, cursor, candidate_id, 100, session_factory
                )
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(event_view(event), separators=(",", ":"))
                    yield f"id: {event.sequence}\nevent: promotion_event\ndata: {payload}\n\n"
                    last_write = asyncio.get_running_loop().time()
                now = asyncio.get_running_loop().time()
                if now - last_write >= settings.event_keepalive_seconds:
                    yield ": keepalive\n\n"
                    last_write = now
                await asyncio.sleep(settings.event_poll_seconds)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return router
