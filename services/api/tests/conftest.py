import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from promotion_control_plane.infrastructure.database import (
    get_session_factory,
    reset_database_connections,
)
from promotion_control_plane.infrastructure.seed import reset_demo
from promotion_control_plane.settings import get_settings


@pytest.fixture(scope="session")
def postgres_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    reset_database_connections()
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(config, "head")
    return url


@pytest.fixture()
def db_session(postgres_url: str) -> Iterator[Session]:
    del postgres_url
    with get_session_factory()() as session:
        reset_demo(session)
    with get_session_factory()() as session:
        yield session
