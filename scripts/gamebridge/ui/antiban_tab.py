"""
AntiBanTab — rolling graphs of click timing, mouse-down/up duration, cursor
speed, and click accuracy, sourced from GameController.stats
(human.stats.AntiBanStats). Purely observational — a sanity check that the
HumanEmulator's timing/accuracy model still looks organic, not a robotic
fixed cadence.

No charting dependency is in requirements.txt (only PyQt6), so Sparkline is
a small QPainter widget in the same style as MinimapWidget/StatBar.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from .theme import C, _qc
from .components import Card, HDivider

if TYPE_CHECKING:
    from ..controller.controller import GameController

_POLL_INTERVAL_MS = 500


class Sparkline(QWidget):
    """Borderless line graph of a rolling float series, with a title and a
    "latest (mean)" readout — no axes, just shape and trend."""

    def __init__(self, title: str, color: str, unit: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title
        self._color = _qc(color)
        self._unit = unit
        self._values: list[float] = []
        self.setFixedHeight(70)
        self.setMinimumWidth(160)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_values(self, values: list[float]) -> None:
        self._values = values
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(_qc(C.TEXT_MUTED))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.drawText(0, 2, w, 14, Qt.AlignmentFlag.AlignLeft, self._title.upper())

        if not self._values:
            p.setPen(_qc(C.TEXT_DIM))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(0, 14, w, h - 14, Qt.AlignmentFlag.AlignCenter, "No data yet")
            p.end()
            return

        plot_top = 18
        plot_h = max(1.0, h - plot_top - 14)
        lo, hi = min(self._values), max(self._values)
        span = max(1e-9, hi - lo)

        n = len(self._values)
        path = QPainterPath()
        for i, v in enumerate(self._values):
            x = (i / max(1, n - 1)) * w
            y = plot_top + plot_h - (v - lo) / span * plot_h
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(self._color, 1.6))
        p.drawPath(path)

        latest = self._values[-1]
        mean = sum(self._values) / n
        p.setPen(_qc(C.TEXT))
        p.setFont(QFont("Segoe UI", 9))
        label = f"{latest:.1f}{self._unit}  (μ {mean:.1f}{self._unit})"
        p.drawText(0, h - 14, w, 14, Qt.AlignmentFlag.AlignRight, label)
        p.end()


class AntiBanTab(QWidget):
    """Polls ctrl.stats on a timer and refreshes four Sparkline graphs."""

    def __init__(self, ctrl: "GameController", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._ctrl = ctrl

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel(
            "Rolling telemetry from the clicks the controller has actually issued "
            "(click_at/click_entity and their right-click equivalents) — a sanity "
            "check that the human emulator's timing and accuracy still look "
            "organic rather than a robotic fixed cadence."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(hint)

        self._summary_lbl = QLabel("No clicks recorded yet.")
        self._summary_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self._summary_lbl)

        layout.addWidget(HDivider())

        self._interval_graph = Sparkline("Inter-click interval", C.ACCENT, unit="s")
        self._down_up_graph = Sparkline("Mouse down → up", C.ACCENT2, unit="ms")
        self._speed_graph = Sparkline("Mouse speed", C.SUCCESS, unit="px/s")
        self._accuracy_graph = Sparkline("Click accuracy (error)", C.WARNING, unit="px")

        grid = QGridLayout()
        grid.setSpacing(10)
        for i, graph in enumerate([
            self._interval_graph, self._down_up_graph,
            self._speed_graph, self._accuracy_graph,
        ]):
            card = Card()
            card.layout().addWidget(graph)
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(_POLL_INTERVAL_MS)

    def _refresh(self) -> None:
        samples = self._ctrl.stats.samples()
        summary = self._ctrl.stats.summary()

        if summary["count"] == 0:
            self._summary_lbl.setText("No clicks recorded yet.")
        else:
            self._summary_lbl.setText(
                f"{summary['count']} clicks  ·  "
                f"accuracy {summary['error_px_mean']:.1f}±{summary['error_px_std']:.1f}px  ·  "
                f"down→up {summary['down_up_ms_mean']:.0f}±{summary['down_up_ms_std']:.0f}ms  ·  "
                f"double-clicks {summary['double_click_rate'] * 100:.1f}%"
            )

        self._interval_graph.set_values(
            [s.inter_click_s for s in samples if s.inter_click_s is not None])
        self._down_up_graph.set_values([s.down_up_ms for s in samples])
        self._speed_graph.set_values([s.move_speed_px_s for s in samples])
        self._accuracy_graph.set_values([s.error_px for s in samples])
