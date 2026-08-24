from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from promotion_control_plane.infrastructure.database import get_session_factory


def database_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SessionDependency = Annotated[Session, Depends(database_session)]


def required_idempotency_key(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)],
) -> str:
    return idempotency_key


IdempotencyKey = Annotated[str, Depends(required_idempotency_key)]
