"""RecordingTab — capture a manual-play session for reverse-engineering into a routine.

Click "Start Recording", play normally, then "End Recording". Every tick's raw
game-state message and every resolved mouse click (left/right, annotated with
exactly what was under the cursor — an NPC, object, menu entry, UI slot, ...)
is appended to a JSONL file under `~/.gamebridge/recordings/`. See
`recording.recorder.SessionRecorder` for the file format and the rationale for
resolving clicks against live game state instead of logging bare pixels.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from ..recording.click_monitor import start_click_monitor
from ..recording.recorder import ClickRecord, SessionRecorder
from .theme import C
from .components import HDivider

if TYPE_CHECKING:
    from ..controller.controller import GameController
    from ..decision.engine import DecisionEngine


class RecordingTab(QWidget):
    # Emitted from the click-monitor daemon thread; Qt marshals it onto the
    # GUI thread automatically since this widget lives there (queued connection).
    _click_recorded = pyqtSignal(object)  # ClickRecord

    def __init__(self, ctrl: "GameController", engine: "DecisionEngine",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._ctrl = ctrl
        self._engine = engine
        self._recorder = SessionRecorder()
        self._click_stop_event: Optional[threading.Event] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel(
            "Records the full per-tick game-state stream plus every mouse click you make "
            "in-game, annotated with exactly what was under the cursor at that moment "
            "(NPC, object, menu entry, inventory slot, ...). Play through whatever you "
            "want turned into a routine, then click End Recording — the saved .jsonl file "
            "interleaves both streams in order, ready to transcribe into a state machine."
        )
        hint.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(HDivider())

        row = QHBoxLayout()
        row.setSpacing(8)
        self._btn = QPushButton("●  Start Recording")
        self._btn.setObjectName("btn-start")
        self._btn.setFixedWidth(160)
        self._btn.clicked.connect(self._toggle)
        row.addWidget(self._btn)

        self._status_lbl = QLabel("Idle")
        self._status_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px;")
        row.addWidget(self._status_lbl)
        row.addStretch()
        layout.addLayout(row)

        self._path_lbl = QLabel("")
        self._path_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
        self._path_lbl.setWordWrap(True)
        layout.addWidget(self._path_lbl)

        layout.addWidget(HDivider())

        log_lbl = QLabel("Resolved clicks")
        log_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(log_lbl)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._output.document().setMaximumBlockCount(1000)
        self._output.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 6px; color: {C.TEXT}; font-size: 12px;"
        )
        layout.addWidget(self._output, stretch=1)

        self._click_recorded.connect(self._on_click_recorded)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        if self._recorder.is_recording:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        if not self._ctrl.refresh_window():
            self._log("RuneLite window not found — launch the game first, then try again.")
            return

        player = self._engine.game.player or {}
        path = self._recorder.start(player_name=player.get("name", ""))

        self._click_stop_event = threading.Event()
        start_click_monitor(self._handle_click, self._click_stop_event)

        self._btn.setText("■  End Recording")
        self._btn.setObjectName("btn-stop")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)
        self._path_lbl.setText(f"→ {path}")
        self._output.clear()
        self._log(f"Recording started — play through the actions you want as a routine, "
                  f"then click End Recording. Saving to {path.name}")
        self._refresh_status()

    def _stop(self) -> None:
        if self._click_stop_event is not None:
            self._click_stop_event.set()
            self._click_stop_event = None

        summary = self._recorder.stop()
        self._btn.setText("●  Start Recording")
        self._btn.setObjectName("btn-start")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)
        self._log(f"Recording saved → {summary['path']}  "
                  f"({summary['ticks']} ticks, {summary['clicks']} clicks, "
                  f"{summary['durationSeconds']:.0f}s)")
        self._refresh_status()

    def stop_if_recording(self) -> None:
        """Cleanly finalise an in-progress recording — call before the window closes
        so the file gets its session_end footer instead of being left truncated."""
        if self._recorder.is_recording:
            self._stop()

    # ------------------------------------------------------------------
    # Capture — feeds from the dashboard's tick handler and the click monitor
    # ------------------------------------------------------------------

    def on_tick(self, raw_msg: dict) -> None:
        """Called once per tick from the dashboard (already on the GUI thread)."""
        self._recorder.record_tick(raw_msg)

    def _handle_click(self, button: str, screen_x: int, screen_y: int, _timestamp: float) -> None:
        """Runs on the click-monitor daemon thread — must not touch Qt widgets directly."""
        if not self._ctrl.is_screen_point_in_window(screen_x, screen_y):
            return
        canvas = self._ctrl.screen_to_canvas(screen_x, screen_y)
        if canvas is None:
            return
        canvas_x, canvas_y = canvas
        record = self._recorder.record_click(button, screen_x, screen_y, canvas_x, canvas_y,
                                              self._engine.game)
        if record is not None:
            self._click_recorded.emit(record)

    @pyqtSlot(object)
    def _on_click_recorded(self, record: ClickRecord) -> None:
        self._log(f"{record.button.upper()}-click → {record.summary}")
        self._refresh_status()

    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        if not self._recorder.is_recording:
            self._status_lbl.setText("Idle")
            self._status_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px;")
            return
        m, s = divmod(int(self._recorder.elapsed_seconds), 60)
        self._status_lbl.setText(
            f"●  Recording — {m:02d}:{s:02d}  ·  "
            f"{self._recorder.tick_count} ticks  ·  {self._recorder.click_count} clicks"
        )
        self._status_lbl.setStyleSheet(f"color: {C.DANGER}; font-weight: 600; font-size: 12px;")

    def _log(self, message: str) -> None:
        self._output.append(message)
