import json
from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy import select, text

from alembic import command
from alembic.config import Config
from promotion_control_plane.application.demo import enqueue_demo_cycle
from promotion_control_plane.application.errors import ApplicationError
from promotion_control_plane.application.schedules import enqueue_schedule_trigger
from promotion_control_plane.infrastructure.config import import_config_directory
from promotion_control_plane.infrastructure.database import get_engine, get_session_factory
from promotion_control_plane.infrastructure.models import ScheduledJob
from promotion_control_plane.infrastructure.seed import seed_if_empty
from promotion_control_plane.settings import get_settings
from promotion_control_plane.worker.service import read_worker_heartbeat

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
demo_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(demo_app, name="demo")
API_ROOT = Path(__file__).resolve().parents[3]


def alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


@app.command()
def migrate() -> None:
    """Upgrade the database to the single current Alembic head."""
    command.upgrade(alembic_config(), "head")


@app.command()
def seed() -> None:
    """Seed deterministic examples only when the candidate table is empty."""
    with get_session_factory()() as session:
        configured_root = Path(get_settings().config_root)
        if not configured_root.is_dir():
            configured_root = API_ROOT.parents[1] / "configs"
        if configured_root.is_dir():
            import_config_directory(session, configured_root)
        changed = seed_if_empty(session)
    typer.echo("seeded" if changed else "already-seeded")


@app.command()
def bootstrap() -> None:
    """Serialize demo migrations and seed, then return so Uvicorn can start."""
    engine = get_engine()
    with engine.connect() as lock_connection:
        lock_connection.execute(
            text("SELECT pg_advisory_lock(hashtext('agent-promotion-bootstrap'))")
        )
        try:
            migrate()
            seed()
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtext('agent-promotion-bootstrap'))")
            )
            lock_connection.commit()


@app.command("trigger-schedule")
def trigger_schedule(
    job_key: str,
    idempotency_key: str = typer.Option(..., "--idempotency-key"),
    actor: str = typer.Option("promotion-cli", "--actor"),
    autonomous_cycle: bool = typer.Option(False, "--autonomous-cycle"),
) -> None:
    """Idempotently enqueue externally owned schedule work."""
    if not 1 <= len(idempotency_key) <= 160:
        raise typer.BadParameter("Idempotency keys must contain 1 to 160 characters.")
    with get_session_factory()() as session:
        job = session.scalar(select(ScheduledJob).where(ScheduledJob.job_key == job_key))
        if job is None:
            raise typer.BadParameter(f"Unknown job: {job_key}")
        try:
            response, _ = enqueue_schedule_trigger(
                session,
                job,
                idempotency_key=idempotency_key,
                actor=actor,
                trigger_source="CLI",
                payload={"autonomous_cycle": autonomous_cycle},
                max_attempts=get_settings().worker_max_attempts,
            )
            session.commit()
        except ApplicationError as error:
            typer.echo(f"{error.code}: {error.detail}", err=True)
            raise typer.Exit(2) from None
        typer.echo(response["job_run_id"])


@app.command("run-demo-cycle")
def run_demo_cycle(
    idempotency_key: str = typer.Option("demo-cycle-v1", "--idempotency-key"),
) -> None:
    """Queue all six observed jobs and the credential-free autonomous lifecycle."""
    if not 1 <= len(idempotency_key) <= 160:
        raise typer.BadParameter("Idempotency keys must contain 1 to 160 characters.")
    if not get_settings().demo_mode:
        typer.echo(
            "DEMO_MODE_DISABLED: Demo cycle is disabled in this environment.",
            err=True,
        )
        raise typer.Exit(2)
    with get_session_factory()() as session:
        runs = enqueue_demo_cycle(session, idempotency_key, "demo-cli")
        session.commit()
        typer.echo(json.dumps([str(run.id) for run in runs]))


@demo_app.command("cycle")
def demo_cycle(
    idempotency_key: str = typer.Option("demo-cycle-v1", "--idempotency-key"),
) -> None:
    """Alias for run-demo-cycle, matching the human-facing command grammar."""
    run_demo_cycle(idempotency_key)


@app.command("openapi")
def write_openapi(output: Path = typer.Option(..., "--output")) -> None:
    """Write deterministic OpenAPI JSON for drift checks and frontend type generation."""
    from promotion_control_plane.api.app import create_app

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    typer.echo(str(output))


@app.command("worker-health")
def worker_health(
    path: Path = typer.Option(Path("/tmp/promotion-worker-health"), "--path"),
    max_age_seconds: int = typer.Option(30, "--max-age-seconds", min=1),
) -> None:
    """Fail when the worker heartbeat file is absent, invalid, or stale."""
    try:
        heartbeat = read_worker_heartbeat(path)
    except (OSError, ValueError):
        raise typer.Exit(1) from None
    if (
        heartbeat.tzinfo is None
        or (datetime.now(UTC) - heartbeat).total_seconds() > max_age_seconds
    ):
        raise typer.Exit(1)
    typer.echo("healthy")


if __name__ == "__main__":
    app()
