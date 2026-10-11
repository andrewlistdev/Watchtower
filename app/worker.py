"""Background sync loop. Waits quietly until the required settings exist, then polls.

Settings are re-read before every cycle, so changes saved in the GUI take effect on
the next check without a restart. `wake()` triggers a check immediately.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config, ConfigMissing
from .runtime import build_syncer, short_error
from .settings_store import SettingsStore
from .state import State

log = logging.getLogger("worker")


@dataclass
class WorkerStatus:
    phase: str = "starting"  # starting | needs_settings | running | error | stopped
    missing: list[str] = field(default_factory=list)
    dry_run: bool = True
    last_check_at: datetime | None = None
    last_check_ok: bool | None = None
    last_error: str | None = None
    checks: int = 0


class Worker(threading.Thread):
    def __init__(self, store: SettingsStore, db_path: str):
        super().__init__(name="sync-worker", daemon=True)
        self.store = store
        self.db_path = db_path
        self.status = WorkerStatus()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._syncer = None
        self._cfg_signature: str | None = None

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _wait(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def run(self) -> None:
        state = State(self.db_path)  # SQLite connection owned by this thread
        while not self._stop.is_set():
            try:
                cfg = Config.load(self.store.resolved)
            except ConfigMissing as exc:
                if self.status.phase != "needs_settings":
                    log.warning("Waiting for settings in the admin page: %s", ", ".join(exc.missing))
                self.status.phase = "needs_settings"
                self.status.missing = exc.missing
                self._wait(15)
                continue

            signature = repr(cfg)
            if signature != self._cfg_signature:
                self._syncer = build_syncer(cfg, state, {})
                self._cfg_signature = signature
                log.info("Settings loaded: dry_run=%s poll=%ss handoff=%smin close_on=%s",
                         cfg.dry_run, cfg.poll_seconds, cfg.handoff_minutes, cfg.sdp_close_statuses)
            self._syncer.people = self.store.people_map()
            self.status.dry_run = cfg.dry_run
            self.status.missing = []

            try:
                self._syncer.run_cycle()
                self.status.phase = "running"
                self.status.last_check_ok = True
                self.status.last_error = None
            except Exception as exc:
                log.exception("Sync check failed; will retry")
                self.status.phase = "error"
                self.status.last_check_ok = False
                self.status.last_error = short_error(exc)
            self.status.last_check_at = datetime.now(timezone.utc)
            self.status.checks += 1
            self._wait(cfg.poll_seconds)
        self.status.phase = "stopped"
