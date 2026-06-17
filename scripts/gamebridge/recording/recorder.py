"""SessionRecorder — capture a manual-play session to a replayable JSONL log.

While recording, every tick's raw message and every resolved mouse click is
appended to `~/.gamebridge/recordings/recording-<timestamp>.jsonl`. Each line
is a self-contained JSON object tagged by "type":

    {"type": "session_start", "startedAt": ..., "playerName": ...}
    {"type": "tick", "wallTime": ..., "msg": {...raw tick message, verbatim...}}
    {"type": "click", "wallTime": ..., "button": "left"|"right",
     "screenX": ..., "screenY": ..., "canvasX": ..., "canvasY": ..., "tick": ...,
     "playerWorldX": ..., "playerWorldY": ..., "playerAnimation": ...,
     "interactingWith": ..., "resolved": {...resolve_click() result...}}
    {"type": "session_end", "endedAt": ..., "durationSeconds": ..., "ticks": ..., "clicks": ...}

Reading the file top-to-bottom interleaves both streams in chronological
order: every tick's full game state (objects, animations, xp/chat/container
events, inventory, ...) plus, exactly where they occurred, annotated clicks
naming precisely what was under the cursor — "object 'Iron rocks' (id=11364)
at world (3185,3304)", "menu entry \"Attack Goblin (level-2)\"", "widget
G149:3 \"Bronze pickaxe\"". That's enough to transcribe a manual play session
into a routine's state machine without replaying it or guessing at pixels.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .resolver import resolve_click
from .summariser import summarise

if TYPE_CHECKING:
    from ..state.game_state import GameState

log = logging.getLogger(__name__)

RECORDINGS_DIR = Path.home() / ".gamebridge" / "recordings"


@dataclass
class ClickRecord:
    """Summary of one resolved click, handed back to the UI for live display."""
    button: str
    canvas_x: float
    canvas_y: float
    summary: str


class SessionRecorder:
    """Owns the recording file and running tallies. One session at a time.

    Thread-safety: `record_tick` is called from the GUI thread (via
    BridgeTicker's queued signal, alongside `start`/`stop`), while
    `record_click` is called from the click-monitor daemon thread. All four
    serialise their file access through `_lock` — see `_write_locked`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._file = None
        self._path: Optional[Path] = None
        self._started_at: Optional[float] = None
        self._tick_count = 0
        self._click_count = 0

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def click_count(self) -> int:
        return self._click_count

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.time() - self._started_at

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, player_name: str = "") -> Path:
        """Open a new recording file, write the session header, return its path."""
        with self._lock:
            if self._file is not None:
                raise RuntimeError("SessionRecorder is already recording")

            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            self._started_at = time.time()
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._started_at))
            self._path = RECORDINGS_DIR / f"recording-{stamp}.jsonl"
            self._tick_count = 0
            self._click_count = 0
            self._file = open(self._path, "w", encoding="utf-8")
            self._write_locked({
                "type": "session_start",
                "startedAt": self._started_at,
                "playerName": player_name,
            })

        log.info("Recording started: %s", self._path)
        return self._path

    def stop(self) -> dict:
        """Write the session footer, close the file, and return a summary dict."""
        with self._lock:
            if self._file is None:
                raise RuntimeError("SessionRecorder is not recording")

            ended_at = time.time()
            summary = {
                "type": "session_end",
                "endedAt": ended_at,
                "durationSeconds": ended_at - self._started_at,
                "ticks": self._tick_count,
                "clicks": self._click_count,
            }
            self._write_locked(summary)
            self._file.close()
            path = self._path
            self._file = None
            self._started_at = None

        log.info("Recording stopped: %s (%d ticks, %d clicks, %.0fs)",
                 path, summary["ticks"], summary["clicks"], summary["durationSeconds"])

        summary_path = None
        try:
            summary_path = summarise(path)
        except Exception:
            log.exception("Failed to summarise %s — raw recording is intact", path)

        return {"path": path, "summaryPath": summary_path, **summary}

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def record_tick(self, raw_msg: dict) -> None:
        """Append the raw tick message verbatim — the full per-tick game-state stream."""
        with self._lock:
            if self._file is None:
                return
            self._write_locked({
                "type": "tick",
                "wallTime": time.time(),
                "msg": raw_msg,
            })
            self._tick_count += 1

    def record_click(self, button: str, screen_x: int, screen_y: int,
                     canvas_x: float, canvas_y: float,
                     game: "GameState") -> Optional[ClickRecord]:
        """Resolve the click against `game` and append an annotated click record.

        Returns a `ClickRecord` summary for the UI's live log, or None if a
        recording isn't currently active (e.g. the user clicked just as
        "End Recording" was pressed — the click is simply dropped).
        """
        resolved = resolve_click(canvas_x, canvas_y, game)
        player = game.player or {}
        record = {
            "type": "click",
            "wallTime": time.time(),
            "button": button,
            "screenX": screen_x,
            "screenY": screen_y,
            "canvasX": canvas_x,
            "canvasY": canvas_y,
            "tick": game.tick,
            "playerWorldX": player.get("worldX"),
            "playerWorldY": player.get("worldY"),
            "playerAnimation": player.get("animation", -1),
            "interactingWith": game.interacting_with,
            "resolved": resolved,
        }

        with self._lock:
            if self._file is None:
                return None
            self._write_locked(record)
            self._click_count += 1

        return ClickRecord(button=button, canvas_x=canvas_x, canvas_y=canvas_y,
                           summary=resolved["summary"])

    # ------------------------------------------------------------------
    # Internal — caller must hold `_lock` and have verified `_file` is open.
    # ------------------------------------------------------------------

    def _write_locked(self, record: dict) -> None:
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()
