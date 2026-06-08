"""BridgeTicker / RoutineRunner — the dashboard's two engine-driving QThreads.

These run independently so a routine's blocking, human-timed actions (mouse
movement, click pauses, scheduled breaks) can never stall game-state
ingestion — see DecisionEngine's module docstring for the full rationale.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QThread, pyqtSignal

from .client import stream as tcp_stream

if TYPE_CHECKING:
    from .decision.engine import DecisionEngine

log = logging.getLogger(__name__)


class BridgeTicker(QThread):
    """Reads the GameBridge stream, ingests each tick, and signals the UI.

    Ingestion (turning a tick message into a published GameState snapshot)
    happens here, on this thread, before the signal is emitted — never on the
    GUI or routine threads — so it can never be delayed by UI work or by a
    routine mid-action. The signal exists purely to let the UI refresh; by
    the time it fires, DecisionEngine.game already reflects the new tick.
    """
    tick_received: pyqtSignal = pyqtSignal(dict)

    def __init__(self, ingest: Callable[[dict], None], host: str = "127.0.0.1", port: int = 7070):
        super().__init__()
        self._ingest = ingest
        self.host = host
        self.port = port

    def run(self) -> None:
        for msg in tcp_stream(host=self.host, port=self.port):
            msg = dict(msg)
            self._ingest(msg)
            self.tick_received.emit(msg)


class RoutineRunner(QThread):
    """Drives the active routine against the latest published GameState snapshot.

    Loops on DecisionEngine.wait_for_snapshot() rather than a fixed-interval
    poll, so it wakes exactly when there's fresh state and always acts on the
    most recent snapshot — never a stale one, and never one queued behind a
    backlog (if drive() is busy with a multi-tick action when several new
    snapshots arrive, it simply picks up the latest on its next pass).
    """

    def __init__(self, engine: "DecisionEngine"):
        super().__init__()
        self._engine = engine
        self._running = True

    def run(self) -> None:
        while self._running:
            if self._engine.wait_for_snapshot(timeout=1.0) and self._running:
                try:
                    self._engine.drive()
                except Exception:
                    log.exception("Error driving routine")

    def stop(self) -> None:
        """Request the loop to exit. Returns promptly (within ~1s) — see run()."""
        self._running = False
