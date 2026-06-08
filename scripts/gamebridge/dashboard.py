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
import os
import sys
import time
from typing import Optional, Type

log = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import diagnostics
from .human.emulator import HumanEmulator
from .controller.controller import GameController, _find_window_by_prefix
from .decision.engine import DecisionEngine
from .routines.base import Routine
from .routines.examples.iron_mining import IronMiningRoutine
from .routines.examples.gold_mining import GoldMiningRoutine
from .routines.examples.melee_fighter import MeleeFighterRoutine
from . import settings as _settings

from .ui.theme import C, STYLESHEET, _qc, _iface_color, _hms, _yaw_dir
from .ui.components import Card, HDivider, StatBar, ConnectionDot
from .ui.minimap import MinimapWidget
from .ui.inventory import InventoryWidget
from .hotkeys import start_hotkey_monitor, HOTKEY_STOP, HOTKEY_KILL
from .bridge_ticker import BridgeTicker, RoutineRunner

# ---------------------------------------------------------------------------
# Routine registry — add entries here to expose them in the dropdown
# ---------------------------------------------------------------------------

ROUTINES: dict[str, Type[Routine]] = {
    "Iron Mining": IronMiningRoutine,
    "Gold Mining": GoldMiningRoutine,
    "Melee Fighter": MeleeFighterRoutine,
}

from .widget_ids import BankDepositBox, Bankmain, Inventory, Wornitems

KNOWN_INTERFACE_GROUPS: frozenset[int] = frozenset({
    BankDepositBox.GROUP, Bankmain.GROUP, Inventory.GROUP, Wornitems.GROUP,
})

# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------


class _ClickableLabel(QLabel):
    """QLabel that emits double_clicked when double-clicked."""
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class _FullscreenViewer(QDialog):
    """Full-screen pixmap viewer — double-click or Escape to close."""

    def __init__(self, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Hull Debug — Fullscreen  (double-click or Esc to close)")
        self.setStyleSheet("background: black;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("background: black;")
        layout.addWidget(self._lbl)

        self._update_pixmap(pixmap)
        self.showMaximized()

    def _update_pixmap(self, pixmap: QPixmap) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            sr = screen.availableGeometry()
            scaled = pixmap.scaled(
                sr.width(), sr.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = pixmap
        self._lbl.setPixmap(scaled)

    def mouseDoubleClickEvent(self, event) -> None:
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


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
        self._hull_raw_pixmap: Optional[QPixmap] = None

        self._build_ui()
        self._start_ticker()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_session_panel)
        self._timer.start(1000)

        start_hotkey_monitor(
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

        left.addWidget(self._make_player_card())

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

        right.addWidget(self._make_status_bar_widget())
        right.addWidget(self._make_routine_card())

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

        log_card = Card("Event Log")
        log_card.setFixedHeight(152)
        self._debug_log = QTextEdit()
        self._debug_log.setReadOnly(True)
        self._debug_log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._debug_log.document().setMaximumBlockCount(1000)
        log_card.layout().addWidget(self._debug_log)
        right.addWidget(log_card)

        root.addLayout(right, stretch=1)

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
    # Testing tab
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

        # To add a new check: write a diagnostics.describe_* helper and add a row here.
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

    # ------------------------------------------------------------------
    # Settings tab
    # ------------------------------------------------------------------

    def _make_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

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

    # ------------------------------------------------------------------
    # Hull debug tab
    # ------------------------------------------------------------------

    def _make_hull_debug_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for row_idx, (lbl_text, attr) in enumerate([
            ("NPC",         "_hull_npc_combo"),
            ("Object",      "_hull_obj_combo"),
            ("Widget",      "_hull_widget_combo"),
            ("Interface",   "_hull_iface_combo"),
            ("Other Iface", "_hull_other_iface_combo"),
        ]):
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet(
                f"color: {C.TEXT_MUTED}; font-size: 12px; min-width: 72px;")
            combo = QComboBox()
            combo.addItem("— none —", None)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(combo, row_idx, 1)
            setattr(self, attr, combo)
        layout.addLayout(grid)
        layout.addWidget(HDivider())

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        btn_capture = QPushButton("📷  Capture Hull")
        btn_capture.setFixedWidth(130)
        btn_capture.clicked.connect(self._capture_hull_debug)

        self._hull_freeze_btn = QPushButton("❄  Freeze")
        self._hull_freeze_btn.setCheckable(True)
        self._hull_freeze_btn.setFixedWidth(90)
        self._hull_freeze_btn.toggled.connect(self._on_hull_freeze_toggled)

        self._hull_show_widgets_btn = QPushButton("☐  Show all widgets")
        self._hull_show_widgets_btn.setCheckable(True)
        self._hull_show_widgets_btn.setFixedWidth(160)
        self._hull_show_widgets_btn.toggled.connect(
            self._on_hull_show_all_widgets_toggled)

        self._hull_show_known_ifaces_btn = QPushButton("☐  Show known ifaces")
        self._hull_show_known_ifaces_btn.setCheckable(True)
        self._hull_show_known_ifaces_btn.setFixedWidth(170)
        self._hull_show_known_ifaces_btn.toggled.connect(
            self._on_hull_show_all_known_ifaces_toggled)

        self._hull_status = QLabel("")
        self._hull_status.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 11px;")

        ctrl_row.addWidget(btn_capture)
        ctrl_row.addWidget(self._hull_freeze_btn)
        ctrl_row.addWidget(self._hull_show_widgets_btn)
        ctrl_row.addWidget(self._hull_show_known_ifaces_btn)
        ctrl_row.addWidget(self._hull_status, stretch=1)
        layout.addLayout(ctrl_row)

        self._hull_preview = _ClickableLabel()
        self._hull_preview.double_clicked.connect(self._open_hull_fullscreen)
        self._hull_preview.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._hull_preview.setStyleSheet(
            f"background: {C.BG}; border: 1px solid {C.BORDER};")
        self._hull_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hull_preview.setMinimumHeight(200)
        self._hull_preview.setToolTip("Double-click to open fullscreen")
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

    def _on_hull_show_all_widgets_toggled(self, checked: bool) -> None:
        if checked:
            self._hull_show_widgets_btn.setText("☑  Show all widgets")
            self._hull_show_widgets_btn.setStyleSheet(
                f"background-color: {C.ACCENT_DIM}; "
                f"border-color: {C.ACCENT}; color: {C.ACCENT};"
            )
        else:
            self._hull_show_widgets_btn.setText("☐  Show all widgets")
            self._hull_show_widgets_btn.setStyleSheet("")

    def _on_hull_show_all_known_ifaces_toggled(self, checked: bool) -> None:
        if checked:
            self._hull_show_known_ifaces_btn.setText("☑  Show known ifaces")
            self._hull_show_known_ifaces_btn.setStyleSheet(
                f"background-color: {C.ACCENT_DIM}; "
                f"border-color: {C.ACCENT}; color: {C.ACCENT};"
            )
        else:
            self._hull_show_known_ifaces_btn.setText("☐  Show known ifaces")
            self._hull_show_known_ifaces_btn.setStyleSheet("")

    def _open_hull_fullscreen(self) -> None:
        if self._hull_raw_pixmap is not None and not self._hull_raw_pixmap.isNull():
            viewer = _FullscreenViewer(self._hull_raw_pixmap, parent=self)
            viewer.exec()

    def _refresh_hull_combos(self, g, widgets: list[dict], interfaces: list[dict]) -> None:
        """Repopulate all five hull-debug dropdowns, preserving the current selection."""
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

        def _widget_label(wg: dict) -> str:
            gid = wg.get("groupId", "?")
            cid = wg.get("childId", "?")
            item_id = wg.get("itemId", -1)
            txt = wg.get("text", "")
            b = wg.get("bounds") or {}
            bounds_hint = f"  ({b.get('x',0)},{b.get('y',0)})" if b else ""
            return f"G{gid}:{cid}{bounds_hint}  item={item_id}" + (
                f"  '{txt[:16]}'" if txt else "")

        widget_items = [
            (_widget_label(wg), wg)
            for wg in sorted(widgets, key=lambda x: (x.get("groupId", 0), x.get("childId", 0)))
        ]
        _update(self._hull_widget_combo, widget_items)

        known_iface_items = []
        other_iface_items = []
        for wg in sorted(interfaces, key=lambda x: (x.get("groupId", 0), x.get("childId", 0))):
            label = _widget_label(wg)
            if wg.get("groupId", 0) in KNOWN_INTERFACE_GROUPS:
                known_iface_items.append((label, wg))
            else:
                other_iface_items.append((label, wg))
        _update(self._hull_iface_combo, known_iface_items)
        _update(self._hull_other_iface_combo, other_iface_items)

    def _capture_hull_debug(self) -> None:
        y_off = int(_settings.get("hull_y_offset") or 0)
        g = self._engine.game

        target_widget = self._hull_widget_combo.currentData(Qt.ItemDataRole.UserRole)
        target_iface  = self._hull_iface_combo.currentData(Qt.ItemDataRole.UserRole)
        target_other  = self._hull_other_iface_combo.currentData(Qt.ItemDataRole.UserRole)
        target_obj    = self._hull_obj_combo.currentData(Qt.ItemDataRole.UserRole)
        target_npc    = self._hull_npc_combo.currentData(Qt.ItemDataRole.UserRole)
        show_all_widgets  = self._hull_show_widgets_btn.isChecked()
        show_known_ifaces = self._hull_show_known_ifaces_btn.isChecked()

        any_selection = any([
            target_widget, target_iface, target_other,
            target_obj, target_npc, show_all_widgets, show_known_ifaces,
        ])
        if not any_selection:
            on_objs = [o for o in g.objects if o.get("onScreen") and o.get("hull")]
            if on_objs:
                target_obj = min(on_objs, key=g.distance_to)
            else:
                on_npcs = [n for n in g.npcs if n.get("onScreen") and n.get("hull")]
                if on_npcs:
                    target_npc = min(on_npcs, key=g.distance_to)

        window_name = _settings.get("window_name") or "RuneLite"
        hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
        if not hwnd:
            hwnd = _find_window_by_prefix(window_name)
        if not hwnd:
            self._hull_status.setText(
                "⚠  RuneLite window not found — launch the client first.")
            return

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

        if show_all_widgets:
            self._draw_bounds_overlay(painter, self._hull_last_widgets, y_off,
                                      highlight=target_widget)

        if show_known_ifaces:
            known = [
                wg for wg in self._hull_last_interfaces
                if wg.get("groupId", 0) in KNOWN_INTERFACE_GROUPS
            ]
            self._draw_bounds_overlay(painter, known, y_off, highlight=target_iface)

        status_parts: list[str] = []

        if target_widget is not None:
            b = target_widget.get("bounds")
            if b and b.get("width", 0) > 0 and b.get("height", 0) > 0:
                self._draw_rect_focus(painter, b, y_off, "#58a6ff")
                gid = target_widget.get("groupId", "?")
                cid = target_widget.get("childId", "?")
                txt = target_widget.get("text", "")
                status_parts.append(
                    f"Widget G{gid}:{cid}  text='{txt}'  "
                    f"({int(b['x'])},{int(b['y'])}) "
                    f"{int(b['width'])}×{int(b['height'])}"
                )
            else:
                status_parts.append("Widget: no bounds data.")

        if target_iface is not None:
            b = target_iface.get("bounds")
            if b and b.get("width", 0) > 0 and b.get("height", 0) > 0:
                self._draw_rect_focus(painter, b, y_off, "#f0a500")
                gid = target_iface.get("groupId", "?")
                cid = target_iface.get("childId", "?")
                status_parts.append(
                    f"Iface G{gid}:{cid}  "
                    f"({int(b['x'])},{int(b['y'])}) "
                    f"{int(b['width'])}×{int(b['height'])}"
                )
            else:
                status_parts.append("Iface: no bounds data.")

        if target_other is not None:
            b = target_other.get("bounds")
            if b and b.get("width", 0) > 0 and b.get("height", 0) > 0:
                self._draw_rect_focus(painter, b, y_off, "#bc8cff")
                gid = target_other.get("groupId", "?")
                cid = target_other.get("childId", "?")
                status_parts.append(
                    f"Other G{gid}:{cid}  "
                    f"({int(b['x'])},{int(b['y'])}) "
                    f"{int(b['width'])}×{int(b['height'])}"
                )
            else:
                status_parts.append("Other: no bounds data.")

        if target_obj is not None:
            hull = target_obj.get("hull")
            if hull:
                cx, cy = self._draw_hull_focus(painter, hull, y_off, "#ff6b6b")
                name_str = target_obj.get("name", "?")
                status_parts.append(
                    f"Object '{name_str}'  {len(hull)} pts  "
                    f"centroid ({cx:.0f},{cy:.0f})"
                )
            else:
                status_parts.append(
                    f"Object '{target_obj.get('name','?')}' has no hull "
                    f"(off-screen or hull-filtered).")

        if target_npc is not None:
            hull = target_npc.get("hull")
            if hull:
                cx, cy = self._draw_hull_focus(painter, hull, y_off, "#3fb950")
                name_str = target_npc.get("name", "?")
                status_parts.append(
                    f"NPC '{name_str}'  {len(hull)} pts  "
                    f"centroid ({cx:.0f},{cy:.0f})"
                )
            else:
                status_parts.append(
                    f"NPC '{target_npc.get('name','?')}' has no hull "
                    f"(off-screen or hull-filtered).")

        if not status_parts:
            if show_all_widgets:
                status_parts.append(f"Showing {len(self._hull_last_widgets)} widgets.")
            if show_known_ifaces:
                known_count = sum(
                    1 for wg in self._hull_last_interfaces
                    if wg.get("groupId", 0) in KNOWN_INTERFACE_GROUPS
                )
                status_parts.append(f"Showing {known_count} known interface widgets.")
        if not status_parts:
            status_parts.append(
                "No selection — choose an entity from a dropdown, "
                "or move on-screen entities into view.")

        painter.end()
        self._hull_status.setText("  ·  ".join(status_parts))
        self._hull_raw_pixmap = raw

        scaled = raw.scaled(
            self._hull_preview.width() or 800,
            self._hull_preview.height() or 500,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hull_preview.setPixmap(scaled)

    def _draw_bounds_overlay(
        self,
        painter: QPainter,
        items: list[dict],
        y_off: int,
        highlight: Optional[dict] = None,
    ) -> None:
        sel_gid = highlight.get("groupId") if highlight else None
        sel_cid = highlight.get("childId") if highlight else None
        for wg in items:
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
            painter.setPen(QPen(QColor(color), 2 if is_sel else 1))
            painter.fillRect(QRectF(rx, ry, rw, rh), fill)
            painter.drawRect(QRectF(rx, ry, rw, rh))
            font = QFont("Segoe UI", 7)
            font.setBold(is_sel)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(QPointF(rx + 2, ry + 9), f"G{gid}:{cid}")

    def _draw_rect_focus(
        self,
        painter: QPainter,
        b: dict,
        y_off: int,
        color_hex: str,
    ) -> None:
        rx = float(b["x"])
        ry = float(b["y"]) - y_off
        rw = float(b["width"])
        rh = float(b["height"])
        color = QColor(color_hex)
        fill = QColor(color_hex)
        fill.setAlpha(55)
        painter.setPen(QPen(color, 2))
        painter.fillRect(QRectF(rx, ry, rw, rh), fill)
        painter.drawRect(QRectF(rx, ry, rw, rh))
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(rx + rw / 2, ry + rh / 2), 5, 5)

    def _draw_hull_focus(
        self,
        painter: QPainter,
        hull: list,
        y_off: int,
        color_hex: str,
    ) -> tuple[float, float]:
        path = QPainterPath()
        path.moveTo(hull[0][0], hull[0][1] - y_off)
        for pt in hull[1:]:
            path.lineTo(pt[0], pt[1] - y_off)
        path.closeSubpath()
        color = QColor(color_hex)
        fill = QColor(color_hex)
        fill.setAlpha(55)
        painter.setPen(QPen(color, 2))
        painter.fillPath(path, fill)
        painter.drawPath(path)
        cx = sum(p[0] for p in hull) / len(hull)
        cy = sum(p[1] for p in hull) / len(hull) - y_off
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
        return cx, cy

    # ------------------------------------------------------------------
    # Thread setup
    # ------------------------------------------------------------------

    def _start_ticker(self) -> None:
        self._ticker = BridgeTicker(ingest=self._engine.ingest, host=self._host, port=self._port)
        self._ticker.tick_received.connect(self._on_tick)
        self._ticker.start()

        self._routine_runner = RoutineRunner(self._engine)
        self._routine_runner.start()

    # ------------------------------------------------------------------
    # Tick handler (runs on main thread via Qt signal)
    #
    # BridgeTicker has already ingested this tick — self._engine.game is the
    # published snapshot for it — by the time this slot fires. This handler
    # only refreshes the display; it never drives the routine (RoutineRunner
    # does that, on its own thread, off the latest snapshot).
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

        g = self._engine.game
        tick = g.tick
        self._tick_lbl.setText(f"Tick {tick:,}")
        self.setWindowTitle(f"GameBridge  —  tick {tick:,}")

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

        self._minimap.update_state(g)

        if g.camera:
            yaw = g.camera.get("yaw", 0)
            self._cam_yaw.setText(f"Yaw: {yaw}  ({_yaw_dir(yaw)})")
            self._cam_pitch.setText(f"Pitch: {g.camera.get('pitch', '—')}")
            cx, cy, cz = (g.camera.get(k, "—") for k in ("x", "y", "z"))
            self._cam_pos.setText(f"Pos: ({cx}, {cy}, {cz})")

        self._inv_widget.set_inventory(g.inventory)
        if g.inventory:
            used = g.inventory_used_slots()
            self._inv_slots_lbl.setText(f"{used}/28 slots used")
        else:
            self._inv_slots_lbl.setText("—")

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
                    item.setForeground(QBrush(_iface_color(w.get("groupId", 0))))
                    item.setData(Qt.ItemDataRole.UserRole, w)
                self._iface_table.setItem(r, col, item)
        self._iface_table.setUpdatesEnabled(True)

        self._hull_last_widgets = widgets
        self._hull_last_interfaces = interfaces
        if not self._hull_freeze_btn.isChecked():
            self._refresh_hull_combos(g, widgets, interfaces)

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

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Stop RoutineRunner before the window closes.

        Otherwise it keeps calling engine.drive() against a controller whose
        window has gone away, and Qt warns about a QThread being destroyed
        while still running. BridgeTicker has no equivalent stop — it blocks
        in a socket read with no clean way to interrupt it — so it's left to
        exit with the process, as it always has.
        """
        self._routine_runner.stop()
        self._routine_runner.wait(2000)
        super().closeEvent(event)


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
