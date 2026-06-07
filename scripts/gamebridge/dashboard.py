"""
GameBridge Qt Dashboard — PyQt6 native UI.

A live desktop window that shows game state streamed from the GameBridge
RuneLite plugin, with routine control and a debug event log.

Usage
-----
    python -m scripts.gamebridge.dashboard
    python -m scripts.gamebridge.main --dashboard
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import math
import os
import sys
import threading
import time
from typing import Optional, Type

log = logging.getLogger(__name__)

from PyQt6.QtCore import (
    Qt, QThread, QTimer, QRectF, QPointF, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QToolTip, QVBoxLayout, QWidget,
)

from . import diagnostics
from .client import stream as tcp_stream
from .state.game_state import GameState
from .human.emulator import HumanEmulator
from .controller.controller import GameController, _find_window_by_prefix
from .decision.engine import DecisionEngine
from .routines.base import Routine
from .routines.examples.iron_mining import IronMiningRoutine
from .routines.examples.gold_mining import GoldMiningRoutine
from . import settings as _settings

# ---------------------------------------------------------------------------
# Routine registry — add entries here to expose them in the dropdown
# ---------------------------------------------------------------------------

ROUTINES: dict[str, Type[Routine]] = {
    "Iron Mining": IronMiningRoutine,
    "Gold Mining": GoldMiningRoutine,
}

# ---------------------------------------------------------------------------
# Color palette (GitHub dark-inspired)
# ---------------------------------------------------------------------------

class C:
    BG            = "#0d1117"
    SURFACE       = "#161b22"
    SURFACE_HOVER = "#1c2128"
    BORDER        = "#30363d"
    BORDER_SUBTLE = "#21262d"

    ACCENT        = "#58a6ff"
    ACCENT_DIM    = "#1c3554"
    ACCENT2       = "#bc8cff"

    HP            = "#f85149"
    HP_DIM        = "#4a1919"
    PRAYER        = "#58a6ff"
    PRAYER_DIM    = "#1c3554"
    FATIGUE       = "#e3b341"
    FATIGUE_DIM   = "#3d2f0e"

    SUCCESS       = "#3fb950"
    SUCCESS_DIM   = "#0d3d1e"
    WARNING       = "#e3b341"
    DANGER        = "#f85149"

    TEXT          = "#e6edf3"
    TEXT_MUTED    = "#8b949e"
    TEXT_DIM      = "#484f58"

    NPC_VIS       = "#f85149"
    NPC_HIDDEN    = "#6b2828"
    OBJ_VIS       = "#e3b341"
    OBJ_HIDDEN    = "#5a4810"
    PLAYER_COLOR  = "#3fb950"

# ---------------------------------------------------------------------------
# Global stylesheet
# ---------------------------------------------------------------------------

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
    font-size: 13px;
    color: {C.TEXT};
}}

QMainWindow, QWidget {{
    background-color: {C.BG};
}}

QLabel {{ background: transparent; }}

QPushButton {{
    background-color: {C.SURFACE};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 14px;
    font-weight: 500;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {C.SURFACE_HOVER};
    border-color: {C.ACCENT};
}}
QPushButton:pressed {{ background-color: {C.ACCENT_DIM}; }}

QPushButton#btn-start {{
    background-color: {C.SUCCESS_DIM};
    border-color: {C.SUCCESS};
    color: {C.SUCCESS};
}}
QPushButton#btn-start:hover {{ background-color: #164a28; }}

QPushButton#btn-stop {{
    background-color: #3a1414;
    border-color: {C.DANGER};
    color: {C.DANGER};
}}
QPushButton#btn-stop:hover {{ background-color: #5a1e1e; }}

QComboBox {{
    background-color: {C.SURFACE};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 28px;
}}
QComboBox::drop-down {{ border: none; padding-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {C.SURFACE};
    border: 1px solid {C.BORDER};
    selection-background-color: {C.ACCENT_DIM};
    selection-color: {C.ACCENT};
    outline: none;
}}

QTabWidget::pane {{
    border: none;
    background-color: {C.SURFACE};
}}
QTabBar::tab {{
    background: transparent;
    color: {C.TEXT_MUTED};
    border: none;
    padding: 7px 18px;
    font-size: 12px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {C.ACCENT};
    border-bottom: 2px solid {C.ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {C.TEXT};
    border-bottom: 2px solid {C.BORDER};
}}

QTableWidget {{
    background-color: {C.SURFACE};
    border: none;
    gridline-color: {C.BORDER_SUBTLE};
    font-size: 12px;
    selection-background-color: {C.ACCENT_DIM};
    alternate-background-color: #0f1419;
    outline: none;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {C.ACCENT_DIM};
}}
QHeaderView::section {{
    background-color: {C.BG};
    color: {C.TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {C.BORDER};
    padding: 5px 8px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
    text-transform: uppercase;
}}

QTextEdit {{
    background-color: {C.BG};
    border: none;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 11px;
    color: {C.TEXT_MUTED};
}}

QScrollBar:vertical {{
    background: {C.BG};
    width: 6px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {C.BORDER};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {C.TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C.BG};
    height: 6px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {C.BORDER};
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QStatusBar {{
    background-color: {C.BG};
    color: {C.TEXT_MUTED};
    border-top: 1px solid {C.BORDER};
    font-size: 12px;
}}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-group-ID colour for interface overlays
# Deterministic: same group always gets the same colour across frames.
# ---------------------------------------------------------------------------

_IFACE_PALETTE = [
    "#58a6ff", "#3fb950", "#e3b341", "#bc8cff", "#f85149",
    "#79c0ff", "#56d364", "#ffa657", "#d2a8ff", "#ff7b72",
    "#39d353", "#f0883e", "#a5d6ff", "#7ee787", "#ffa198",
]


def _iface_color(group_id: int) -> QColor:
    return QColor(_IFACE_PALETTE[group_id % len(_IFACE_PALETTE)])


def _hms(seconds: float) -> str:
    secs = int(max(0.0, seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m:02d}m {s:02d}s"


def _yaw_dir(yaw: int) -> str:
    # OSRS yaw: 0=N, 512=W, 1024=S, 1536=E (counter-clockwise, 8 compass points × 256 units each)
    for threshold, label in [
        (128, "N"), (384, "NW"), (640, "W"), (896, "SW"),
        (1152, "S"), (1408, "SE"), (1664, "E"), (1920, "NE"), (2048, "N"),
    ]:
        if yaw < threshold:
            return label
    return "N"


def _qc(hex_str: str) -> QColor:
    return QColor(hex_str)


# ---------------------------------------------------------------------------
# Card — rounded dark panel with optional title
# ---------------------------------------------------------------------------

class Card(QWidget):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._inner = QVBoxLayout(self)
        self._inner.setContentsMargins(14, 12, 14, 12)
        self._inner.setSpacing(8)

        if title:
            lbl = QLabel(title.upper())
            lbl.setStyleSheet(
                f"color: {C.TEXT_MUTED}; font-size: 10px; font-weight: 600;"
                " letter-spacing: 1px; background: transparent;"
            )
            self._inner.addWidget(lbl)

    # expose layout directly so callers can do card.layout().addWidget(...)
    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._inner

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)
        p.fillPath(path, _qc(C.SURFACE))
        pen = QPen(_qc(C.BORDER))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


# ---------------------------------------------------------------------------
# Divider
# ---------------------------------------------------------------------------

class HDivider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {C.BORDER}; border: none;")


# ---------------------------------------------------------------------------
# StatBar — colored labeled progress bar
# ---------------------------------------------------------------------------

class StatBar(QWidget):
    """
    A pill-shaped progress bar with a short label on the left and
    the numeric value on the right.  Drawn entirely with QPainter.
    """
    _LABEL_W = 48
    _VAL_W   = 36
    _BAR_H   = 7

    def __init__(
        self, label: str, color: str, dim: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._label = label
        self._color = _qc(color)
        self._dim   = _qc(dim)
        self._value = 0
        self._max   = 99
        self.setFixedHeight(22)
        self.setMinimumWidth(120)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_value(self, value: int, maximum: int = 99) -> None:
        self._value = value
        self._max = max(1, maximum)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_x = self._LABEL_W
        bar_w = w - self._LABEL_W - self._VAL_W - 4
        bar_y = (h - self._BAR_H) // 2

        # Label
        p.setPen(_qc(C.TEXT_MUTED))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(0, 0, self._LABEL_W, h, Qt.AlignmentFlag.AlignVCenter, self._label)

        # Background track
        tr = QRectF(bar_x, bar_y, bar_w, self._BAR_H)
        tp = QPainterPath()
        tp.addRoundedRect(tr, self._BAR_H / 2, self._BAR_H / 2)
        p.fillPath(tp, self._dim)

        # Fill
        frac = self._value / self._max
        fill_w = max(0.0, min(float(bar_w), bar_w * frac))
        if fill_w >= self._BAR_H:          # only draw when wide enough to round
            fp = QPainterPath()
            fp.addRoundedRect(QRectF(bar_x, bar_y, fill_w, self._BAR_H),
                              self._BAR_H / 2, self._BAR_H / 2)
            p.fillPath(fp, self._color)
        elif fill_w > 0:
            p.fillRect(QRectF(bar_x, bar_y, fill_w, self._BAR_H), self._color)

        # Numeric value
        p.setPen(_qc(C.TEXT))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        p.drawText(
            w - self._VAL_W, 0, self._VAL_W, h,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            str(self._value),
        )
        p.end()


# ---------------------------------------------------------------------------
# MinimapWidget — QPainter tile grid centred on the player
# ---------------------------------------------------------------------------

class MinimapWidget(QWidget):
    _RADIUS  = 8    # tiles from centre → 17×17 grid
    _CELL    = 13   # pixels per tile

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._game: Optional[GameState] = None
        side = (self._RADIUS * 2 + 1) * self._CELL + 4
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def update_state(self, game: GameState) -> None:
        self._game = game
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = self._RADIUS
        n = r * 2 + 1
        cell = self._CELL
        pad = 2.0

        # Background
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, w, h), 6, 6)
        p.fillPath(bg, _qc("#080c14"))

        # Grid lines
        p.setPen(QPen(_qc("#111928"), 1))
        for i in range(n + 1):
            x = pad + i * cell
            y = pad + i * cell
            p.drawLine(int(x), int(pad), int(x), int(h - pad))
            p.drawLine(int(pad), int(y), int(w - pad), int(y))

        def to_screen(wx: int, wy: int) -> tuple[float, float]:
            dc = wx - px
            dr = py - wy
            cx = pad + (r + dc + 0.5) * cell
            cy = pad + (r + dr + 0.5) * cell
            return cx, cy

        if not self._game or not self._game.player:
            p.setPen(_qc(C.TEXT_DIM))
            p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, "No data")
            p.end()
            return

        px, py = self._game.player_pos

        # FOV ellipse — fitted to the bounding box of all onScreen entities.
        # Shrunk by 1 tile so "just barely visible" outliers don't inflate the shape.
        # Falls back to a pitch-based circle if no entities are visible.
        visible_dxdy = [
            (obj["worldX"] - px, obj["worldY"] - py)
            for obj in self._game.objects if obj.get("onScreen")
        ] + [
            (npc["worldX"] - px, npc["worldY"] - py)
            for npc in self._game.npcs if npc.get("onScreen")
        ]
        if visible_dxdy:
            min_dx = min(d[0] for d in visible_dxdy)
            max_dx = max(d[0] for d in visible_dxdy)
            min_dy = min(d[1] for d in visible_dxdy)
            max_dy = max(d[1] for d in visible_dxdy)
            cx_t = (min_dx + max_dx) / 2.0
            cy_t = (min_dy + max_dy) / 2.0
            a_t = max(0.5, (max_dx - min_dx) / 2.0 - 1.0)
            b_t = max(0.5, (max_dy - min_dy) / 2.0 - 1.0)
        else:
            _cam = self._game.camera
            _pitch = _cam.get("pitch", 300) if _cam else 300
            _t = max(0.0, min(1.0, (_pitch - 229) / (450 - 229)))
            cx_t = cy_t = 0.0
            a_t = b_t = 10.0 - _t * 5.0   # 10 tiles at low pitch, 5 at high

        cx_s = pad + (r + cx_t + 0.5) * cell
        cy_s = pad + (r - cy_t + 0.5) * cell   # y inverted: north = up on minimap
        a_s, b_s = a_t * cell, b_t * cell
        p.setPen(QPen(_qc("#58a6ff70"), 1, Qt.PenStyle.DashLine))
        p.setBrush(_qc("#58a6ff15"))
        p.drawEllipse(QRectF(cx_s - a_s, cy_s - b_s, a_s * 2, b_s * 2))

        # Objects — small squares
        p.setPen(Qt.PenStyle.NoPen)
        for obj in self._game.objects:
            dc = obj["worldX"] - px
            dr = py - obj["worldY"]
            if -r <= dc <= r and -r <= dr <= r:
                cx, cy = to_screen(obj["worldX"], obj["worldY"])
                on = obj.get("onScreen", False)
                sz = cell * 0.45
                p.setBrush(_qc(C.OBJ_VIS if on else C.OBJ_HIDDEN))
                p.drawRect(QRectF(cx - sz / 2, cy - sz / 2, sz, sz))

        # NPCs — circles
        for npc in self._game.npcs:
            dc = npc["worldX"] - px
            dr = py - npc["worldY"]
            if -r <= dc <= r and -r <= dr <= r:
                cx, cy = to_screen(npc["worldX"], npc["worldY"])
                on = npc.get("onScreen", False)
                rad = max(2.5, cell * 0.35)
                p.setBrush(_qc(C.NPC_VIS if on else C.NPC_HIDDEN))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(cx, cy), rad, rad)

        # Player — green dot with camera direction tick
        cx_p, cy_p = to_screen(px, py)
        cam = self._game.camera
        yaw = cam.get("yaw", 0) if cam else 0
        angle = -(yaw / 2048.0) * 2 * math.pi

        # Soft halo
        p.setBrush(_qc("#0d3020"))
        p.setPen(Qt.PenStyle.NoPen)
        halo_r = cell * 0.72
        p.drawEllipse(QPointF(cx_p, cy_p), halo_r, halo_r)

        # Core dot
        dot_r = max(3.5, cell * 0.42)
        p.setBrush(_qc(C.PLAYER_COLOR))
        p.setPen(QPen(_qc("#c0ffd0"), 0.7))
        p.drawEllipse(QPointF(cx_p, cy_p), dot_r, dot_r)

        # Direction tick
        tick = cell * 0.8
        dx = math.sin(angle) * tick
        dy = -math.cos(angle) * tick
        p.setPen(QPen(_qc(C.PLAYER_COLOR), 1.8,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx_p, cy_p), QPointF(cx_p + dx, cy_p + dy))

        p.end()


# ---------------------------------------------------------------------------
# InventoryWidget — 4×7 painted slot grid
# ---------------------------------------------------------------------------

class InventoryWidget(QWidget):
    _COLS = 4
    _ROWS = 7
    _SZ   = 38
    _GAP  = 3

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._slots: list[dict] = []
        tw = self._COLS * self._SZ + (self._COLS - 1) * self._GAP
        th = self._ROWS * self._SZ + (self._ROWS - 1) * self._GAP
        self.setFixedSize(tw, th)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)

    def _slot_at(self, pos) -> int:
        """Return the slot index (0-27) under pos, or -1 if in a gap."""
        sz, gap = self._SZ, self._GAP
        step = sz + gap
        col = pos.x() // step
        row = pos.y() // step
        if not (0 <= col < self._COLS and 0 <= row < self._ROWS):
            return -1
        if pos.x() % step >= sz or pos.y() % step >= sz:
            return -1  # in the gap between cells
        return row * self._COLS + col

    def mouseMoveEvent(self, event) -> None:
        slot_idx = self._slot_at(event.pos())
        if slot_idx < 0:
            QToolTip.hideText()
            return
        by_slot = {s["slot"]: s for s in self._slots}
        slot = by_slot.get(slot_idx)
        if slot is None or slot.get("itemId", -1) == -1:
            tip = f"Slot {slot_idx}:  Empty"
        else:
            item_id = slot["itemId"]
            qty = slot.get("qty", 1)
            tip = f"Slot {slot_idx}\nItem ID:  {item_id}\nQuantity:  {qty:,}"
        QToolTip.showText(event.globalPosition().toPoint(), tip, self)

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()

    def set_inventory(self, items: list[dict]) -> None:
        self._slots = items
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sz, gap = self._SZ, self._GAP

        # Build a slot-index → item lookup
        by_slot = {s["slot"]: s for s in self._slots}

        for i in range(28):
            col = i % self._COLS
            row = i // self._COLS
            x = col * (sz + gap)
            y = row * (sz + gap)
            rect = QRectF(x, y, sz, sz)

            slot = by_slot.get(i)
            occupied = slot is not None and slot.get("itemId", -1) != -1

            # Slot background
            slot_path = QPainterPath()
            slot_path.addRoundedRect(rect, 5, 5)
            p.fillPath(slot_path, _qc("#1a2030" if occupied else "#10141c"))
            pen = QPen(_qc(C.ACCENT if occupied else C.BORDER_SUBTLE), 1.0)
            p.setPen(pen)
            p.drawPath(slot_path)

            if occupied:
                item_id = slot["itemId"]
                qty     = slot.get("qty", 1)

                # Item ID (small, centered top)
                p.setPen(_qc(C.TEXT_MUTED))
                p.setFont(QFont("Segoe UI", 7))
                p.drawText(
                    int(x), int(y) + 2, sz, 14,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    str(item_id),
                )

                # Quantity badge (bottom-right)
                if qty > 1:
                    qty_str = (
                        f"{qty // 1_000_000}m" if qty >= 1_000_000
                        else f"{qty // 1_000}k" if qty >= 10_000
                        else f"×{qty}"
                    )
                    p.setPen(_qc(C.WARNING))
                    p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                    p.drawText(
                        int(x), int(y) + sz - 14, sz - 2, 14,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                        qty_str,
                    )

        p.end()


# ---------------------------------------------------------------------------
# Connection indicator dot
# ---------------------------------------------------------------------------

class ConnectionDot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._connected = False
        self.setFixedSize(10, 10)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_connected(self, v: bool) -> None:
        self._connected = v
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self._connected:
            p.setBrush(_qc(C.SUCCESS_DIM))
            p.drawEllipse(0, 0, 10, 10)
            p.setBrush(_qc(C.SUCCESS))
        else:
            p.setBrush(_qc("#3a1414"))
            p.drawEllipse(0, 0, 10, 10)
            p.setBrush(_qc(C.DANGER))
        p.drawEllipse(2, 2, 6, 6)
        p.end()


# ---------------------------------------------------------------------------
# Global hotkey monitor (polls GetAsyncKeyState in a daemon thread)
# F10            → stop the running routine cleanly
# Ctrl+Shift+Q   → hard-kill the entire dashboard process
# ---------------------------------------------------------------------------

_VK_F10    = 0x79
_VK_CTRL   = 0x11
_VK_SHIFT  = 0x10
_VK_Q      = 0x51

HOTKEY_STOP      = "F10"
HOTKEY_KILL      = "Ctrl+Shift+Q"


def _start_hotkey_monitor(stop_cb, kill_cb) -> threading.Thread:
    """
    Start a daemon thread that polls for global hotkeys.
    stop_cb is called when F10 is pressed.
    kill_cb is called when Ctrl+Shift+Q is pressed.
    """
    def _loop():
        active: set[str] = set()
        while True:
            f10    = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_F10)  & 0x8000)
            q      = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_Q)    & 0x8000)
            ctrl   = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_CTRL) & 0x8000)
            shift  = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_SHIFT)& 0x8000)

            if f10 and "f10" not in active:
                active.add("f10")
                try:
                    stop_cb()
                except Exception:
                    pass
            elif not f10:
                active.discard("f10")

            if ctrl and shift and q and "csq" not in active:
                active.add("csq")
                try:
                    kill_cb()
                except Exception:
                    pass
            elif not (ctrl and shift and q):
                active.discard("csq")

            time.sleep(0.05)

    t = threading.Thread(target=_loop, daemon=True, name="hotkey-monitor")
    t.start()
    return t


# ---------------------------------------------------------------------------
# Background TCP thread
# ---------------------------------------------------------------------------

class BridgeTicker(QThread):
    """Reads the GameBridge stream and emits one signal per tick."""
    tick_received: pyqtSignal = pyqtSignal(dict)

    def __init__(self, host: str = "127.0.0.1", port: int = 7070):
        super().__init__()
        self.host = host
        self.port = port

    def run(self) -> None:
        for msg in tcp_stream(host=self.host, port=self.port):
            self.tick_received.emit(dict(msg))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class GameBridgeWindow(QMainWindow):
    def __init__(self, host: str = "127.0.0.1", port: int = 7070):
        super().__init__()
        self._host = host
        self._port = port

        self._human  = HumanEmulator()
        self._ctrl   = GameController(human=self._human)
        self._engine = DecisionEngine(ctrl=self._ctrl, human=self._human)
        self._session_start = time.monotonic()
        self._connected     = False
        self._hull_last_widgets: list[dict] = []
        self._hull_last_interfaces: list[dict] = []

        self._build_ui()
        self._start_ticker()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_session_panel)
        self._timer.start(1000)

        # Global hotkeys — work even when the game window has focus
        _start_hotkey_monitor(
            stop_cb=self._stop_routine,
            kill_cb=lambda: os._exit(0),
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("GameBridge")
        self.setMinimumSize(1080, 680)
        self.resize(1300, 820)

        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root = QHBoxLayout(root_widget)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Left sidebar ─────────────────────────────────────────────

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFixedWidth(274)

        left_host = QWidget()
        left_host.setStyleSheet("background: transparent;")
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 4, 0)
        left.setSpacing(10)

        # Player card
        left.addWidget(self._make_player_card())

        # Minimap card
        mm_card = Card("Minimap")
        self._minimap = MinimapWidget()
        mm_row = QHBoxLayout()
        mm_row.addStretch()
        mm_row.addWidget(self._minimap)
        mm_row.addStretch()
        mm_card.layout().addLayout(mm_row)
        legend = QHBoxLayout()
        legend.setSpacing(6)
        for color, text in [
            (C.PLAYER_COLOR, "You"), (C.NPC_VIS, "NPC"), (C.OBJ_VIS, "Object"),
        ]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 9px;")
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
            legend.addWidget(dot)
            legend.addWidget(lbl)
        legend.addStretch()
        mm_card.layout().addLayout(legend)
        left.addWidget(mm_card)

        # Inventory card
        inv_card = Card("Inventory")
        self._inv_widget = InventoryWidget()
        inv_row = QHBoxLayout()
        inv_row.addStretch()
        inv_row.addWidget(self._inv_widget)
        inv_row.addStretch()
        inv_card.layout().addLayout(inv_row)
        self._inv_slots_lbl = QLabel("—")
        self._inv_slots_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inv_slots_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 11px;")
        inv_card.layout().addWidget(self._inv_slots_lbl)
        left.addWidget(inv_card)

        # Camera card
        cam_card = Card("Camera")
        self._cam_yaw   = QLabel("Yaw: —")
        self._cam_pitch = QLabel("Pitch: —")
        self._cam_pos   = QLabel("Pos: —")
        for lbl in (self._cam_yaw, self._cam_pitch, self._cam_pos):
            lbl.setStyleSheet(f"color: {C.TEXT}; font-size: 12px;")
            cam_card.layout().addWidget(lbl)
        left.addWidget(cam_card)

        left.addStretch()
        left_scroll.setWidget(left_host)
        root.addWidget(left_scroll)

        # ── Right panel ───────────────────────────────────────────────

        right = QVBoxLayout()
        right.setSpacing(10)

        # Top status bar
        right.addWidget(self._make_status_bar_widget())

        # Routine control
        right.addWidget(self._make_routine_card())

        # Nearby tabs (expandable)
        nearby = Card("Nearby Entities")
        nearby.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        self._tabs = QTabWidget()

        self._npc_table = self._make_table(["Name", "Lvl", "Pos", "Dist", "●"])
        self._tabs.addTab(self._npc_table, "NPCs")

        self._obj_table = self._make_table(["Name", "Pos", "Dist", "●"])
        self._tabs.addTab(self._obj_table, "Objects")

        self._widget_table = self._make_table(["Group", "Child", "Item ID", "Text", "Bounds"])
        self._tabs.addTab(self._widget_table, "Widgets")

        self._iface_table = self._make_table(["Group", "Child", "Bounds", "Item ID", "Text"])
        self._tabs.addTab(self._iface_table, "Interfaces")

        self._xp_table = self._make_table(["Skill", "Level", "Boosted", "Total XP"])
        self._tabs.addTab(self._xp_table, "Skills / XP")

        self._tabs.addTab(self._make_hull_debug_tab(), "Hull Debug")
        self._tabs.addTab(self._make_testing_tab(), "Testing")
        self._tabs.addTab(self._make_settings_tab(), "Settings")

        nearby.layout().addWidget(self._tabs)
        right.addWidget(nearby, stretch=1)

        # Debug log
        log_card = Card("Event Log")
        log_card.setFixedHeight(152)
        self._debug_log = QTextEdit()
        self._debug_log.setReadOnly(True)
        self._debug_log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._debug_log.document().setMaximumBlockCount(1000)
        log_card.layout().addWidget(self._debug_log)
        right.addWidget(log_card)

        root.addLayout(right, stretch=1)

        # Qt status bar (bottom)
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_msg = QLabel("Waiting for connection…")
        self._status_msg.setStyleSheet(
            f"color: {C.TEXT_MUTED}; padding: 0 8px;")
        status_bar.addWidget(self._status_msg)
        hk_hint = QLabel(f"{HOTKEY_STOP} stop  ·  {HOTKEY_KILL} kill")
        hk_hint.setStyleSheet(
            f"color: {C.TEXT_DIM}; font-size: 11px; padding: 0 8px;")
        status_bar.addPermanentWidget(hk_hint)

    def _make_player_card(self) -> Card:
        card = Card("Player")

        self._player_name = QLabel("—")
        self._player_name.setStyleSheet(
            f"color: {C.TEXT}; font-size: 18px; font-weight: 700;")
        card.layout().addWidget(self._player_name)

        self._player_pos_lbl = QLabel("Position: —")
        self._player_pos_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        card.layout().addWidget(self._player_pos_lbl)

        self._player_anim_lbl = QLabel("Animation: idle")
        self._player_anim_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        card.layout().addWidget(self._player_anim_lbl)

        self._player_target_lbl = QLabel("")
        self._player_target_lbl.setStyleSheet(
            f"color: {C.ACCENT}; font-size: 12px;")
        card.layout().addWidget(self._player_target_lbl)

        card.layout().addWidget(HDivider())

        self._hp_bar     = StatBar("HP",     C.HP,     C.HP_DIM)
        self._prayer_bar = StatBar("Prayer", C.PRAYER, C.PRAYER_DIM)
        card.layout().addWidget(self._hp_bar)
        card.layout().addWidget(self._prayer_bar)

        return card

    def _make_status_bar_widget(self) -> Card:
        card = Card()
        card.setFixedHeight(52)
        row = QHBoxLayout()
        row.setSpacing(10)

        self._conn_dot = ConnectionDot()
        self._conn_lbl = QLabel("Disconnected")
        self._conn_lbl.setStyleSheet(
            f"color: {C.DANGER}; font-weight: 600; font-size: 13px;")

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        sep.setFixedWidth(1)

        self._tick_lbl = QLabel("Tick —")
        self._tick_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")

        row.addWidget(self._conn_dot)
        row.addWidget(self._conn_lbl)
        row.addWidget(sep)
        row.addWidget(self._tick_lbl)
        row.addStretch()
        card.layout().addLayout(row)
        return card

    def _make_routine_card(self) -> Card:
        card = Card("Routine Control")

        # Row 1 — dropdown + buttons
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._routine_combo = QComboBox()
        for name in ROUTINES:
            self._routine_combo.addItem(name)
        row1.addWidget(self._routine_combo, stretch=1)

        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setObjectName("btn-start")
        self._btn_start.setFixedWidth(88)
        self._btn_start.clicked.connect(self._start_routine)

        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setObjectName("btn-stop")
        self._btn_stop.setFixedWidth(88)
        self._btn_stop.clicked.connect(self._stop_routine)

        self._btn_reset = QPushButton("↺  Reset")
        self._btn_reset.setFixedWidth(78)
        self._btn_reset.clicked.connect(self._reset_routine)

        row1.addWidget(self._btn_start)
        row1.addWidget(self._btn_stop)
        row1.addWidget(self._btn_reset)
        card.layout().addLayout(row1)

        # Row 2 — state + session
        row2 = QHBoxLayout()
        self._routine_state_lbl = QLabel("State: —")
        self._routine_state_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        self._session_lbl = QLabel("Session: 00m 00s")
        self._session_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        row2.addWidget(self._routine_state_lbl)
        row2.addStretch()
        row2.addWidget(self._session_lbl)
        card.layout().addLayout(row2)

        # Row 3 — fatigue bar
        fat_row = QHBoxLayout()
        fat_lbl = QLabel("Fatigue")
        fat_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px; min-width: 52px;")
        self._fatigue_bar = StatBar("", C.FATIGUE, C.FATIGUE_DIM)
        self._fatigue_bar.set_value(0, 100)
        fat_row.addWidget(fat_lbl)
        fat_row.addWidget(self._fatigue_bar, stretch=1)
        card.layout().addLayout(fat_row)

        return card

    # ------------------------------------------------------------------
    # Testing tab — ad-hoc checks against a named entity.
    #
    # To add a new check: write a `diagnostics.describe_*` helper (so the
    # logic stays unit-testable without Qt) and append a
    # (label, handler) pair to _TEST_ACTIONS below — no layout work needed.
    # ------------------------------------------------------------------

    def _make_testing_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl = QLabel("Entity name")
        lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl)

        self._test_name_input = QLineEdit()
        self._test_name_input.setPlaceholderText("e.g. Iron rocks, Mine cart, Man")
        self._test_name_input.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 5px 10px; color: {C.TEXT};"
        )
        layout.addWidget(self._test_name_input)

        hint = QLabel(
            "Resolves to the nearest object or NPC matching this name (case-insensitive). "
            "Each button below runs one check against it and appends the result below."
        )
        hint.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(HDivider())

        self._TEST_ACTIONS = [
            ("Move into view",                self._run_test_move_into_view),
            ("Move towards",                  self._run_test_move_towards),
            ("Click minimap to move towards", self._run_test_click_minimap),
            ("Is occluded?",                  self._run_test_is_occluded),
            ("Is on screen?",                 self._run_test_is_on_screen),
            ("Is on minimap?",                self._run_test_is_on_minimap),
        ]
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (label, handler) in enumerate(self._TEST_ACTIONS):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        self._test_output = QTextEdit()
        self._test_output.setReadOnly(True)
        self._test_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._test_output.document().setMaximumBlockCount(500)
        self._test_output.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 6px; color: {C.TEXT}; font-size: 12px;"
        )
        layout.addWidget(self._test_output, stretch=1)

        return w

    def _resolve_test_entity(self) -> Optional[dict]:
        name = self._test_name_input.text().strip()
        if not name:
            self._log_test("Enter an entity name first.")
            return None
        entity = diagnostics.find_entity(self._engine.game, name)
        if entity is None:
            self._log_test(f"No object or NPC named '{name}' found nearby.")
        return entity

    def _log_test(self, message: str) -> None:
        self._test_output.append(message)

    def _run_test_move_into_view(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_move_into_view(self._ctrl, self._engine.game, entity))

    def _run_test_move_towards(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_move_towards(self._ctrl, entity))

    def _run_test_click_minimap(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_click_minimap(self._ctrl, self._engine.game, entity))

    def _run_test_is_occluded(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_is_occluded(self._engine.game, entity))

    def _run_test_is_on_screen(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_is_on_screen(entity))

    def _run_test_is_on_minimap(self) -> None:
        entity = self._resolve_test_entity()
        if entity is not None:
            self._log_test(diagnostics.describe_is_on_minimap(entity))

    def _make_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Window name
        lbl_wn = QLabel("RuneLite window title")
        lbl_wn.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl_wn)

        wn_row = QHBoxLayout()
        self._wn_input = QLineEdit(_settings.get("window_name") or "")
        self._wn_input.setPlaceholderText("e.g. RuneLite - PlayerName")
        self._wn_input.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 5px 10px; color: {C.TEXT};"
        )
        btn_save = QPushButton("Save")
        btn_save.setFixedWidth(70)
        btn_save.clicked.connect(self._save_window_name)
        wn_row.addWidget(self._wn_input, stretch=1)
        wn_row.addWidget(btn_save)
        layout.addLayout(wn_row)

        hint_wn = QLabel(
            "The exact window title shown in the title bar of the RuneLite client.\n"
            "A prefix is also accepted — e.g. 'RuneLite' matches 'RuneLite - Any Name'."
        )
        hint_wn.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        hint_wn.setWordWrap(True)
        layout.addWidget(hint_wn)

        layout.addWidget(HDivider())

        # Hull Y offset
        lbl_hull = QLabel("Hull debug Y offset (px)")
        lbl_hull.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl_hull)

        hull_row = QHBoxLayout()
        self._hull_y_spin = QSpinBox()
        self._hull_y_spin.setRange(-200, 200)
        self._hull_y_spin.setValue(int(_settings.get("hull_y_offset") or 0))
        self._hull_y_spin.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 4px 8px; color: {C.TEXT};"
        )
        btn_hull_save = QPushButton("Save")
        btn_hull_save.setFixedWidth(70)
        btn_hull_save.clicked.connect(self._save_hull_y_offset)
        hull_row.addWidget(self._hull_y_spin)
        hull_row.addWidget(btn_hull_save)
        hull_row.addStretch()
        layout.addLayout(hull_row)

        hint_hull = QLabel(
            "Pixels subtracted from every hull point's Y coordinate before drawing.\n"
            "Increase if the hull appears too high; decrease (negative) if too low."
        )
        hint_hull.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        hint_hull.setWordWrap(True)
        layout.addWidget(hint_hull)

        layout.addWidget(HDivider())

        # Hotkey reference
        hk_lbl = QLabel("Global hotkeys")
        hk_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(hk_lbl)

        for key, desc in [
            (HOTKEY_STOP, "Stop the running routine cleanly"),
            (HOTKEY_KILL, "Hard-kill the dashboard (use if frozen)"),
            ("S / X / R", "Start / Stop / Reset (dashboard window must have focus)"),
        ]:
            row = QHBoxLayout()
            k = QLabel(key)
            k.setStyleSheet(
                f"color: {C.ACCENT}; font-family: 'Cascadia Code', monospace; "
                f"font-size: 12px; font-weight: 600; min-width: 140px;"
            )
            d = QLabel(desc)
            d.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px;")
            row.addWidget(k)
            row.addWidget(d)
            row.addStretch()
            layout.addLayout(row)

        layout.addStretch()
        return w

    def _save_window_name(self) -> None:
        name = self._wn_input.text().strip()
        if name:
            _settings.set("window_name", name)
            self._status_msg.setText(f"✓ Window name saved: {name}")

    def _save_hull_y_offset(self) -> None:
        val = self._hull_y_spin.value()
        _settings.set("hull_y_offset", val)
        self._status_msg.setText(f"✓ Hull Y offset saved: {val:+d} px")

    def _make_hull_debug_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Dropdowns — one row per entity type
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for row_idx, (lbl_text, attr) in enumerate([
            ("NPC",    "_hull_npc_combo"),
            ("Object", "_hull_obj_combo"),
            ("Widget", "_hull_widget_combo"),
        ]):
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet(
                f"color: {C.TEXT_MUTED}; font-size: 12px; min-width: 48px;")
            combo = QComboBox()
            combo.addItem("— none —", None)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(combo, row_idx, 1)
            setattr(self, attr, combo)
        layout.addLayout(grid)
        layout.addWidget(HDivider())

        # Controls row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        btn_capture = QPushButton("📷  Capture Hull")
        btn_capture.setFixedWidth(130)
        btn_capture.clicked.connect(self._capture_hull_debug)

        self._hull_freeze_btn = QPushButton("❄  Freeze")
        self._hull_freeze_btn.setCheckable(True)
        self._hull_freeze_btn.setFixedWidth(90)
        self._hull_freeze_btn.toggled.connect(self._on_hull_freeze_toggled)

        self._hull_show_all_btn = QPushButton("☐  Show Interfaces")
        self._hull_show_all_btn.setCheckable(True)
        self._hull_show_all_btn.setFixedWidth(150)
        self._hull_show_all_btn.toggled.connect(self._on_hull_show_all_toggled)

        self._hull_status = QLabel("")
        self._hull_status.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 11px;")

        ctrl_row.addWidget(btn_capture)
        ctrl_row.addWidget(self._hull_freeze_btn)
        ctrl_row.addWidget(self._hull_show_all_btn)
        ctrl_row.addWidget(self._hull_status, stretch=1)
        layout.addLayout(ctrl_row)

        # Preview image
        self._hull_preview = QLabel()
        self._hull_preview.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._hull_preview.setStyleSheet(
            f"background: {C.BG}; border: 1px solid {C.BORDER};")
        self._hull_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hull_preview.setMinimumHeight(200)
        layout.addWidget(self._hull_preview, stretch=1)

        return w

    def _on_hull_freeze_toggled(self, checked: bool) -> None:
        if checked:
            self._hull_freeze_btn.setText("▶  Live")
            self._hull_freeze_btn.setStyleSheet(
                f"background-color: {C.FATIGUE_DIM}; "
                f"border-color: {C.WARNING}; color: {C.WARNING};"
            )
        else:
            self._hull_freeze_btn.setText("❄  Freeze")
            self._hull_freeze_btn.setStyleSheet("")

    def _on_hull_show_all_toggled(self, checked: bool) -> None:
        if checked:
            self._hull_show_all_btn.setText("☑  Show Interfaces")
            self._hull_show_all_btn.setStyleSheet(
                f"background-color: {C.ACCENT_DIM}; "
                f"border-color: {C.ACCENT}; color: {C.ACCENT};"
            )
        else:
            self._hull_show_all_btn.setText("☐  Show Interfaces")
            self._hull_show_all_btn.setStyleSheet("")

    def _refresh_hull_combos(self, g, interfaces: list[dict]) -> None:
        """Repopulate the three hull-debug dropdowns, preserving the current selection."""
        def _update(combo: QComboBox, items: list[tuple[str, dict]]) -> None:
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— none —", None)
            for text, data in items:
                combo.addItem(text, data)
            idx = combo.findText(current_text)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

        px, py = g.player_pos if g.player else (0, 0)

        def dist(e: dict) -> int:
            return abs(e.get("worldX", 0) - px) + abs(e.get("worldY", 0) - py)

        npc_items = []
        for npc in sorted(g.npcs, key=dist)[:40]:
            on = npc.get("onScreen", False)
            label = (
                f"{npc.get('name','?')}  "
                f"lvl {npc.get('combatLevel','?')}  "
                f"dist {dist(npc)}  {'●' if on else '○'}"
            )
            npc_items.append((label, npc))
        _update(self._hull_npc_combo, npc_items)

        obj_items = []
        for obj in sorted(g.objects, key=dist)[:40]:
            on = obj.get("onScreen", False)
            label = (
                f"{obj.get('name','?')}  "
                f"dist {dist(obj)}  {'●' if on else '○'}"
            )
            obj_items.append((label, obj))
        _update(self._hull_obj_combo, obj_items)

        # Widget dropdown is sourced from the full interfaces list — a superset
        # of the old exposeWidgets data covering every active UI group.
        widget_items = []
        for wg in sorted(
            interfaces, key=lambda x: (x.get("groupId", 0), x.get("childId", 0))
        ):
            gid = wg.get("groupId", "?")
            cid = wg.get("childId", "?")
            item_id = wg.get("itemId", -1)
            txt = wg.get("text", "")
            b = wg.get("bounds") or {}
            bounds_hint = f"  ({b.get('x',0)},{b.get('y',0)})" if b else ""
            label = f"G{gid}:{cid}{bounds_hint}  item={item_id}" + (
                f"  '{txt[:16]}'" if txt else "")
            widget_items.append((label, wg))
        _update(self._hull_widget_combo, widget_items)

    def _capture_hull_debug(self) -> None:
        y_off = int(_settings.get("hull_y_offset") or 0)
        g = self._engine.game

        target_widget: Optional[dict] = self._hull_widget_combo.currentData(
            Qt.ItemDataRole.UserRole)
        target_obj:    Optional[dict] = self._hull_obj_combo.currentData(
            Qt.ItemDataRole.UserRole)
        target_npc:    Optional[dict] = self._hull_npc_combo.currentData(
            Qt.ItemDataRole.UserRole)
        show_all = self._hull_show_all_btn.isChecked()

        # Auto-fallback when nothing is explicitly selected
        if target_widget is None and target_obj is None and target_npc is None and not show_all:
            on_objs = [o for o in g.objects if o.get("onScreen") and o.get("hull")]
            if on_objs:
                target_obj = min(on_objs, key=g.distance_to)
            else:
                on_npcs = [n for n in g.npcs if n.get("onScreen") and n.get("hull")]
                if on_npcs:
                    target_npc = min(on_npcs, key=g.distance_to)

        # Find the game window HWND
        window_name = _settings.get("window_name") or "RuneLite"
        hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
        if not hwnd:
            hwnd = _find_window_by_prefix(window_name)
        if not hwnd:
            self._hull_status.setText(
                "⚠  RuneLite window not found — launch the client first.")
            return

        # Crop captured image to the client area so canvas coordinates align.
        win_rc = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(win_rc))
        cli_rc = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(cli_rc))
        cli_origin = ctypes.wintypes.POINT()
        cli_origin.x = 0
        cli_origin.y = 0
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(cli_origin))
        chrome_x = cli_origin.x - win_rc.left
        chrome_y = cli_origin.y - win_rc.top
        client_w = cli_rc.right - cli_rc.left
        client_h = cli_rc.bottom - cli_rc.top

        screen = QApplication.primaryScreen()
        if screen is None:
            self._hull_status.setText("⚠  No screen available.")
            return
        raw: QPixmap = screen.grabWindow(hwnd)
        if raw.isNull():
            self._hull_status.setText("⚠  Screenshot capture failed.")
            return
        if client_w > 0 and client_h > 0:
            raw = raw.copy(chrome_x, chrome_y, client_w, client_h)

        painter = QPainter(raw)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- Layer 1: interface overlay (all active UI panels) ---
        if show_all:
            sel_gid = target_widget.get("groupId") if target_widget else None
            sel_cid = target_widget.get("childId") if target_widget else None
            for wg in self._hull_last_interfaces:
                b = wg.get("bounds")
                if not b or b.get("width", 0) <= 0 or b.get("height", 0) <= 0:
                    continue
                gid = wg.get("groupId", 0)
                cid = wg.get("childId", "?")
                is_sel = (gid == sel_gid and wg.get("childId") == sel_cid)
                rx = float(b["x"])
                ry = float(b["y"]) - y_off
                rw = float(b["width"])
                rh = float(b["height"])
                color = _iface_color(gid)
                fill = QColor(color)
                fill.setAlpha(100 if is_sel else 28)
                painter.setPen(QPen(color, 2 if is_sel else 1))
                painter.fillRect(QRectF(rx, ry, rw, rh), fill)
                painter.drawRect(QRectF(rx, ry, rw, rh))
                font = QFont("Segoe UI", 7)
                font.setBold(is_sel)
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(QPointF(rx + 2, ry + 9), f"G{gid}:{cid}")

        # --- Layer 2: focused entity ---
        status_text = ""
        if target_widget is not None and not show_all:
            b = target_widget.get("bounds")
            if b:
                rx = float(b["x"])
                ry = float(b["y"]) - y_off
                rw = float(b["width"])
                rh = float(b["height"])
                painter.setPen(QPen(QColor("#58a6ff"), 2))
                painter.fillRect(QRectF(rx, ry, rw, rh), QColor(88, 166, 255, 55))
                painter.drawRect(QRectF(rx, ry, rw, rh))
                painter.setBrush(QColor("#58a6ff"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(rx + rw / 2, ry + rh / 2), 5, 5)
                gid = target_widget.get("groupId", "?")
                cid = target_widget.get("childId", "?")
                txt = target_widget.get("text", "")
                status_text = (
                    f"Widget G{gid}:{cid}  text='{txt}'  "
                    f"bounds ({int(b['x'])}, {int(b['y'])}) {int(rw)}×{int(rh)}"
                )
            else:
                status_text = "No bounds data for selected widget."

        elif target_obj is not None:
            hull = target_obj.get("hull")
            if hull:
                path = QPainterPath()
                path.moveTo(hull[0][0], hull[0][1] - y_off)
                for pt in hull[1:]:
                    path.lineTo(pt[0], pt[1] - y_off)
                path.closeSubpath()
                painter.setPen(QPen(QColor("#ff6b6b"), 2))
                painter.fillPath(path, QColor(255, 107, 107, 55))
                painter.drawPath(path)
                cx = sum(p[0] for p in hull) / len(hull)
                cy = sum(p[1] for p in hull) / len(hull) - y_off
                painter.setBrush(QColor("#ff6b6b"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy), 5, 5)
                name_str = target_obj.get("name", "?")
                status_text = (
                    f"Object '{name_str}'  {len(hull)} pts  "
                    f"centroid ({cx:.0f}, {cy:.0f})"
                )
            else:
                status_text = (
                    f"Object '{target_obj.get('name','?')}' has no hull "
                    f"(off-screen or hull-filtered)."
                )

        elif target_npc is not None:
            hull = target_npc.get("hull")
            if hull:
                path = QPainterPath()
                path.moveTo(hull[0][0], hull[0][1] - y_off)
                for pt in hull[1:]:
                    path.lineTo(pt[0], pt[1] - y_off)
                path.closeSubpath()
                painter.setPen(QPen(QColor("#3fb950"), 2))
                painter.fillPath(path, QColor(63, 185, 80, 55))
                painter.drawPath(path)
                cx = sum(p[0] for p in hull) / len(hull)
                cy = sum(p[1] for p in hull) / len(hull) - y_off
                painter.setBrush(QColor("#3fb950"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy), 5, 5)
                name_str = target_npc.get("name", "?")
                status_text = (
                    f"NPC '{name_str}'  {len(hull)} pts  "
                    f"centroid ({cx:.0f}, {cy:.0f})"
                )
            else:
                status_text = (
                    f"NPC '{target_npc.get('name','?')}' has no hull "
                    f"(off-screen or hull-filtered)."
                )

        elif show_all:
            status_text = f"Showing all {len(self._hull_last_interfaces)} interface widgets."
        else:
            status_text = (
                "No selection — choose an entity from a dropdown, "
                "or move on-screen entities into view."
            )

        painter.end()
        self._hull_status.setText(status_text)

        scaled = raw.scaled(
            self._hull_preview.width() or 800,
            self._hull_preview.height() or 500,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hull_preview.setPixmap(scaled)

    def _make_table(self, columns: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(columns))
        t.setHorizontalHeaderLabels(columns)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        t.setShowGrid(False)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return t

    # ------------------------------------------------------------------
    # Thread setup
    # ------------------------------------------------------------------

    def _start_ticker(self) -> None:
        self._ticker = BridgeTicker(host=self._host, port=self._port)
        self._ticker.tick_received.connect(self._on_tick)
        self._ticker.start()

    # ------------------------------------------------------------------
    # Tick handler (runs on main thread via Qt signal)
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def _on_tick(self, msg: dict) -> None:
        if not self._connected:
            self._connected = True
            self._conn_lbl.setText("Connected")
            self._conn_lbl.setStyleSheet(
                f"color: {C.SUCCESS}; font-weight: 600; font-size: 13px;")
            self._conn_dot.set_connected(True)
            self._status_msg.setText("Connected to RuneLite")

        try:
            self._engine.process_tick(msg)
        except Exception:
            log.exception("Error processing tick %s", msg.get("tick", "?"))

        g = self._engine.game
        tick = g.tick
        self._tick_lbl.setText(f"Tick {tick:,}")
        self.setWindowTitle(f"GameBridge  —  tick {tick:,}")

        # Player
        if g.player:
            px, py = g.player_pos
            anim   = g.player.get("animation", -1)
            self._player_name.setText(g.player.get("name", "—"))
            self._player_pos_lbl.setText(
                f"({px}, {py})   plane {g.plane}")
            self._player_anim_lbl.setText(
                f"Animation: {'idle' if anim == -1 else anim}")
            self._player_target_lbl.setText(
                f"→ {g.interacting_with}" if g.interacting_with else "")
            self._hp_bar.set_value(g.player.get("hp", 0))
            self._prayer_bar.set_value(g.player.get("prayer", 0))

        # Minimap
        self._minimap.update_state(g)

        # Camera
        if g.camera:
            yaw = g.camera.get("yaw", 0)
            self._cam_yaw.setText(f"Yaw: {yaw}  ({_yaw_dir(yaw)})")
            self._cam_pitch.setText(f"Pitch: {g.camera.get('pitch', '—')}")
            cx, cy, cz = (g.camera.get(k, "—") for k in ("x", "y", "z"))
            self._cam_pos.setText(f"Pos: ({cx}, {cy}, {cz})")

        # Inventory
        self._inv_widget.set_inventory(g.inventory)
        if g.inventory:
            used = g.inventory_used_slots()
            self._inv_slots_lbl.setText(f"{used}/28 slots used")
        else:
            self._inv_slots_lbl.setText("—")

        # Routine state label
        rout = self._engine.routine
        if rout:
            if self._engine.on_break:
                remain = _hms(self._engine.break_remaining)
                self._routine_state_lbl.setText(f"⏸ Break — {remain} remaining")
                self._routine_state_lbl.setStyleSheet(
                    f"color: {C.WARNING}; font-size: 12px;")
            else:
                self._routine_state_lbl.setText(f"State: {rout.current_state}")
                self._routine_state_lbl.setStyleSheet(
                    f"color: {C.SUCCESS}; font-size: 12px;")

        # NPC table
        self._npc_table.setUpdatesEnabled(False)
        self._npc_table.setRowCount(0)
        for npc in sorted(g.npcs, key=g.distance_to)[:40]:
            r = self._npc_table.rowCount()
            self._npc_table.insertRow(r)
            vis = npc.get("onScreen", False)
            vals = [
                npc.get("name", "?"),
                str(npc.get("combatLevel", "—")),
                f"{npc['worldX']}, {npc['worldY']}",
                str(g.distance_to(npc)),
                "●" if vis else "○",
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 4:
                    item.setForeground(
                        QBrush(_qc(C.SUCCESS if vis else C.TEXT_DIM)))
                self._npc_table.setItem(r, col, item)
        self._npc_table.setUpdatesEnabled(True)

        # Object table
        self._obj_table.setUpdatesEnabled(False)
        self._obj_table.setRowCount(0)
        for obj in sorted(g.objects, key=g.distance_to)[:40]:
            r = self._obj_table.rowCount()
            self._obj_table.insertRow(r)
            vis = obj.get("onScreen", False)
            vals = [
                obj.get("name", "?"),
                f"{obj['worldX']}, {obj['worldY']}",
                str(g.distance_to(obj)),
                "●" if vis else "○",
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 3:
                    item.setForeground(
                        QBrush(_qc(C.SUCCESS if vis else C.TEXT_DIM)))
                self._obj_table.setItem(r, col, item)
        self._obj_table.setUpdatesEnabled(True)

        # Widget table (exposeWidgets legacy data — usually empty unless that config is on)
        widgets = msg.get("widgets", [])
        self._widget_table.setUpdatesEnabled(False)
        self._widget_table.setRowCount(0)
        for w in sorted(widgets, key=lambda x: (x.get("groupId", 0), x.get("childId", 0))):
            r = self._widget_table.rowCount()
            self._widget_table.insertRow(r)
            b = w.get("bounds") or {}
            bounds_str = (
                f"({b.get('x',0)}, {b.get('y',0)})  {b.get('width',0)}×{b.get('height',0)}"
                if b else "—"
            )
            vals = [
                str(w.get("groupId", "?")),
                str(w.get("childId", "?")),
                str(w.get("itemId", -1)),
                w.get("text", ""),
                bounds_str,
            ]
            for col, val in enumerate(vals):
                self._widget_table.setItem(r, col, QTableWidgetItem(val))
            self._widget_table.item(r, 0).setData(Qt.ItemDataRole.UserRole, w)
        self._widget_table.setUpdatesEnabled(True)

        # Interfaces table (exposeInterfaces — all active UI panels, default on)
        interfaces = msg.get("interfaces", [])
        self._iface_table.setUpdatesEnabled(False)
        self._iface_table.setRowCount(0)
        for w in sorted(interfaces, key=lambda x: (x.get("groupId", 0), x.get("childId", 0))):
            r = self._iface_table.rowCount()
            self._iface_table.insertRow(r)
            b = w.get("bounds") or {}
            bounds_str = (
                f"({b.get('x',0)}, {b.get('y',0)})  {b.get('width',0)}×{b.get('height',0)}"
                if b else "—"
            )
            vals = [
                str(w.get("groupId", "?")),
                str(w.get("childId", "?")),
                bounds_str,
                str(w.get("itemId", -1)),
                w.get("text", ""),
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == 0:
                    # Colour the group cell with the per-group interface colour
                    item.setForeground(QBrush(_iface_color(w.get("groupId", 0))))
                    item.setData(Qt.ItemDataRole.UserRole, w)
                self._iface_table.setItem(r, col, item)
        self._iface_table.setUpdatesEnabled(True)

        # Hull debug: update interface store and refresh dropdowns when not frozen
        self._hull_last_widgets = widgets
        self._hull_last_interfaces = interfaces
        if not self._hull_freeze_btn.isChecked():
            self._refresh_hull_combos(g, interfaces)

        # XP table (only rebuild on xp events to avoid flicker)
        xp_events = [e for e in msg.get("events", []) if e["type"] == "xp"]
        if xp_events and g.xp:
            self._xp_table.setUpdatesEnabled(False)
            self._xp_table.setRowCount(0)
            for skill in sorted(g.xp):
                r = self._xp_table.rowCount()
                self._xp_table.insertRow(r)
                for col, val in enumerate([
                    skill.title(),
                    str(g.levels.get(skill, "—")),
                    str(g.boosted_levels.get(skill, "—")),
                    f"{g.xp[skill]:,}",
                ]):
                    self._xp_table.setItem(r, col, QTableWidgetItem(val))
            self._xp_table.setUpdatesEnabled(True)

        # Event log
        events = msg.get("events", [])
        if events:
            parts: list[str] = []
            for e in events:
                t = e["type"]
                if t == "xp":
                    parts.append(
                        f'<span style="color:{C.ACCENT}">{t}</span>'
                        f':<span style="color:{C.TEXT}">{e["skill"]}</span>')
                elif t == "chat":
                    safe = (e.get("message", "")[:40]
                            .replace("&", "&amp;").replace("<", "&lt;"))
                    parts.append(
                        f'<span style="color:{C.WARNING}">{t}</span>'
                        f':<span style="color:{C.TEXT_MUTED}">{safe}</span>')
                elif t == "container":
                    parts.append(
                        f'<span style="color:{C.ACCENT2}">{t}</span>'
                        f':<span style="color:{C.TEXT_MUTED}">'
                        f'{e.get("containerId")}</span>')
                elif t == "animation":
                    parts.append(
                        f'<span style="color:{C.TEXT_DIM}">{t}</span>'
                        f':<span style="color:{C.TEXT_DIM}">'
                        f'{e.get("animId")}</span>')
                else:
                    parts.append(
                        f'<span style="color:{C.TEXT_DIM}">{t}</span>')

            px2, py2 = g.player_pos
            line = (
                f'<span style="color:{C.TEXT_DIM}">{tick:7,}</span>&nbsp;'
                f'<span style="color:{C.TEXT_MUTED}">({px2},{py2})</span>'
                f'&nbsp;&nbsp;{"&nbsp;&nbsp;".join(parts)}'
            )
            self._debug_log.append(line)
            self._debug_log.moveCursor(QTextCursor.MoveOperation.End)

    # ------------------------------------------------------------------
    # Per-second timer — session stats
    # ------------------------------------------------------------------

    def _tick_session_panel(self) -> None:
        elapsed = time.monotonic() - self._session_start
        self._session_lbl.setText(f"Session: {_hms(elapsed)}")
        f = self._human.fatigue
        self._fatigue_bar.set_value(int(f * 100), 100)

    # ------------------------------------------------------------------
    # Routine button handlers
    # ------------------------------------------------------------------

    def _start_routine(self) -> None:
        name = self._routine_combo.currentText()
        if name not in ROUTINES:
            return
        if not self._ctrl.refresh_window():
            self._status_msg.setText(
                "⚠  RuneLite window not found — launch the client first.")
            return
        self._engine.set_routine(ROUTINES[name]())
        self._status_msg.setText(f"▶  Running: {name}")

    def _stop_routine(self) -> None:
        self._engine.stop()
        self._routine_state_lbl.setText("State: —")
        self._routine_state_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        self._status_msg.setText("■  Routine stopped.")

    def _reset_routine(self) -> None:
        if self._engine.routine:
            self._engine.routine.reset()
            self._status_msg.setText("↺  Routine reset to initial state.")

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        k = event.key()
        if k == Qt.Key.Key_S:
            self._start_routine()
        elif k == Qt.Key.Key_X:
            self._stop_routine()
        elif k == Qt.Key.Key_R:
            self._reset_routine()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(host: str = "127.0.0.1", port: int = 7070) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("GameBridge")
    window = GameBridgeWindow(host=host, port=port)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
