"""Color palette, global stylesheet, and small display helpers."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QColor


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


_IFACE_PALETTE = [
    "#58a6ff", "#3fb950", "#e3b341", "#bc8cff", "#f85149",
    "#79c0ff", "#56d364", "#ffa657", "#d2a8ff", "#ff7b72",
    "#39d353", "#f0883e", "#a5d6ff", "#7ee787", "#ffa198",
]

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


def _qc(hex_str: str) -> QColor:
    return QColor(hex_str)


def _iface_color(group_id: int) -> QColor:
    return QColor(_IFACE_PALETTE[group_id % len(_IFACE_PALETTE)])


def _hms(seconds: float) -> str:
    secs = int(max(0.0, seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m:02d}m {s:02d}s"


def _break_label(estimate: Optional[tuple[str, float]]) -> str:
    """Format a DecisionEngine.next_break_estimate tuple for display."""
    if estimate is None:
        return "Next break: —"
    label, eta = estimate
    pretty = label.replace("_", " ").title()
    return f"Next break: ~{pretty} in {_hms(eta)}"


def _fatigue_rate_per_min(history: list[tuple[float, float]]) -> Optional[float]:
    """
    Estimate fatigue's rate of change in %/min from a (timestamp, fatigue)
    history, by comparing the oldest and newest sample in the window.

    Returns None if there isn't enough history yet to measure a trend.
    """
    if len(history) < 2:
        return None
    t0, f0 = history[0]
    t1, f1 = history[-1]
    dt = t1 - t0
    if dt <= 0:
        return None
    return (f1 - f0) / dt * 60.0 * 100.0


def _fatigue_rate_label(rate_per_min: Optional[float]) -> str:
    """Format a _fatigue_rate_per_min() result for display."""
    if rate_per_min is None:
        return "Fatigue trend: —"
    if abs(rate_per_min) < 0.05:
        return "Fatigue trend: steady"
    sign = "+" if rate_per_min > 0 else ""
    return f"Fatigue trend: {sign}{rate_per_min:.1f}%/min"


def _yaw_dir(yaw: int) -> str:
    # OSRS yaw: 0=N, 512=W, 1024=S, 1536=E (counter-clockwise, 8 compass points × 256 units each)
    for threshold, label in [
        (128, "N"), (384, "NW"), (640, "W"), (896, "SW"),
        (1152, "S"), (1408, "SE"), (1664, "E"), (1920, "NE"), (2048, "N"),
    ]:
        if yaw < threshold:
            return label
    return "N"
