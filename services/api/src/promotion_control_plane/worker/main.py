import signal
import time
from pathlib import Path
from threading import Event, Thread

import structlog

from promotion_control_plane.infrastructure.database import get_session_factory
from promotion_control_plane.logging import configure_logging
from promotion_control_plane.settings import get_settings
from promotion_control_plane.worker.service import (
    DeterministicPromotionRegistry,
    dead_letter_exhausted_work,
    process_evaluation_once,
    process_registry_once,
    process_schedule_once,
    touch_worker_heartbeat,
)

logger = structlog.get_logger()
running = True


class ProcessHealthHeartbeat:
    """Keep container health current even while a provider call is in progress."""

    def __init__(self, path: Path, interval_seconds: float = 5.0) -> None:
        self.path = path
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            touch_worker_heartbeat(self.path)
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "ProcessHealthHeartbeat":
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


def _stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    heartbeat_path = Path("/tmp/promotion-worker-health")
    factory = get_session_factory()
    registry = DeterministicPromotionRegistry()
    logger.info("worker_started", worker_id=settings.worker_id)
    with ProcessHealthHeartbeat(heartbeat_path):
        while running:
            worked = False
            try:
                worked |= bool(dead_letter_exhausted_work(factory, settings.worker_id))
                worked |= process_evaluation_once(
                    factory, settings.worker_id, settings.worker_lease_seconds
                )
                worked |= process_schedule_once(
                    factory, settings.worker_id, settings.worker_lease_seconds
                )
                worked |= process_registry_once(
                    factory, registry, settings.worker_id, settings.worker_lease_seconds
                )
            except Exception:
                logger.exception("worker_iteration_failed")
            if not worked:
                time.sleep(settings.worker_poll_seconds)
    logger.info("worker_stopped", worker_id=settings.worker_id)


if __name__ == "__main__":
    main()
