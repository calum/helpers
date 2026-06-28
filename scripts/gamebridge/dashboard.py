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

import logging
import os
import sys
import time
from collections import deque
from typing import Type

log = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QBrush, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from .human.emulator import HumanEmulator
from .controller.controller import GameController
from .decision.engine import DecisionEngine
from .routines.base import Routine
from .routines.examples.iron_mining import IronMiningRoutine
from .routines.examples.gold_mining import GoldMiningRoutine
from .routines.examples.ore_mining import OreMiningRoutine
from .routines.examples.melee_fighter import MeleeFighterRoutine
from .routines.examples.fish_and_cook import FishAndCookRoutine
from .routines.examples.smelting_bars import SmeltingBarsRoutine
from .routines.examples.smithing_helms import SmithingHelmsRoutine
from .routines.examples.rod_fishing import RodFishingRoutine
from .routines.examples.brutus_fighter import BrutusFighterRoutine

from .ui.theme import (
    C, STYLESHEET, _qc, _iface_color, _hms, _yaw_dir,
    _break_label, _fatigue_rate_label, _fatigue_rate_per_min,
)
from .ui.components import Card, HDivider, StatBar, ConnectionDot
from .ui.minimap import MinimapWidget
from .ui.inventory import InventoryWidget
from .ui.hull_debug import HullDebugTab
from .ui.testing_tab import TestingTab
from .ui.recording_tab import RecordingTab
from .ui.antiban_tab import AntiBanTab
from .ui.settings_tab import SettingsTab
from .ui.log_tab import LogTab
from .hotkeys import start_hotkey_monitor, HOTKEY_STOP, HOTKEY_KILL
from .bridge_ticker import BridgeTicker, RoutineRunner

# ---------------------------------------------------------------------------
# Routine registry — add entries here to expose them in the dropdown
# ---------------------------------------------------------------------------

ROUTINES: dict[str, Type[Routine]] = {
    "Iron Mining": IronMiningRoutine,
    "Gold Mining": GoldMiningRoutine,
    "Ore Mining": OreMiningRoutine,
    "Melee Fighter": MeleeFighterRoutine,
    "FishAndCook": FishAndCookRoutine,
    "Smelting Bars": SmeltingBarsRoutine,
    "Smithing Helms": SmithingHelmsRoutine,
    "Rod Fishing": RodFishingRoutine,
    "Brutus": BrutusFighterRoutine,
}

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
        # Rolling (timestamp, fatigue) window used to estimate the fatigue
        # trend shown in the routine card — see _tick_session_panel.
        self._fatigue_history: deque[tuple[float, float]] = deque(maxlen=30)

        self._build_ui()
        self._start_ticker()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_session_panel)
        self._timer.start(1000)

        # Refreshes the tooltip label from ctrl.tooltip() far more often than
        # the ~600ms game-tick rate — hullUpdate (and therefore the tooltip)
        # is pushed at ~20ms cadence, so this lets the dashboard show how
        # fresh/stale it really is at click time.
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.timeout.connect(self._tick_tooltip_label)
        self._tooltip_timer.start(100)

        start_hotkey_monitor(
            stop_cb=self._stop_routine,
            kill_cb=lambda: os._exit(0),
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("GameBridge")
        self.setMinimumSize(860, 560)
        self.resize(1300, 820)

        # A QSplitter (rather than a fixed-width sidebar) lets the user drag
        # the boundary between panels, so the layout actually adapts to the
        # window size instead of clipping/wasting space when resized.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(12, 12, 12, 12)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
        self.setCentralWidget(splitter)

        # ── Left sidebar ─────────────────────────────────────────────

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(220)
        left_scroll.setMaximumWidth(420)

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
        splitter.addWidget(left_scroll)

        # ── Right panel ───────────────────────────────────────────────

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
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

        self._hull_tab = HullDebugTab(engine=self._engine)
        self._testing_tab = TestingTab(ctrl=self._ctrl, engine=self._engine)
        self._recording_tab = RecordingTab(ctrl=self._ctrl, engine=self._engine)
        self._antiban_tab = AntiBanTab(ctrl=self._ctrl)
        self._settings_tab = SettingsTab(on_status=lambda msg: self._status_msg.setText(msg))
        self._log_tab = LogTab()
        self._tabs.addTab(self._hull_tab, "Hull Debug")
        self._tabs.addTab(self._testing_tab, "Testing")
        self._tabs.addTab(self._recording_tab, "Recording")
        self._tabs.addTab(self._antiban_tab, "Anti-Ban")
        self._tabs.addTab(self._settings_tab, "Settings")
        self._tabs.addTab(self._log_tab, "Logs")
        self._log_tab.attach()

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

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([274, 1000])

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

        self._player_tooltip_lbl = QLabel("Tooltip: —")
        self._player_tooltip_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        self._player_tooltip_lbl.setWordWrap(True)
        fm = self._player_tooltip_lbl.fontMetrics()
        self._player_tooltip_lbl.setFixedHeight(fm.lineSpacing() * 2)
        self._player_tooltip_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        card.layout().addWidget(self._player_tooltip_lbl)

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

        row3 = QHBoxLayout()
        self._fatigue_rate_lbl = QLabel("Fatigue trend: —")
        self._fatigue_rate_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        self._next_break_lbl = QLabel("Next break: —")
        self._next_break_lbl.setStyleSheet(
            f"color: {C.TEXT_MUTED}; font-size: 12px;")
        row3.addWidget(self._fatigue_rate_lbl)
        row3.addStretch()
        row3.addWidget(self._next_break_lbl)
        card.layout().addLayout(row3)

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
    # Thread setup
    # ------------------------------------------------------------------

    def _start_ticker(self) -> None:
        self._ticker = BridgeTicker(ingest=self._engine.ingest, host=self._host, port=self._port)
        self._ticker.tick_received.connect(self._on_tick)
        self._ticker.connection_changed.connect(self._ctrl.set_connection)
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

        self._recording_tab.on_tick(msg)

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

        self._hull_tab.update_state(g, widgets, interfaces)

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

        self._fatigue_history.append((time.monotonic(), f))
        rate = _fatigue_rate_per_min(list(self._fatigue_history))
        self._fatigue_rate_lbl.setText(_fatigue_rate_label(rate))

        self._next_break_lbl.setText(_break_label(self._engine.next_break_estimate))

    def _tick_tooltip_label(self) -> None:
        tooltip = self._ctrl.tooltip()
        age = self._ctrl.tooltip_age()
        age_str = f" ({age * 1000:.0f}ms)" if age is not None else ""
        self._player_tooltip_lbl.setText(f"Tooltip: {tooltip or '—'}{age_str}")

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
        self._recording_tab.stop_if_recording()
        self._log_tab.detach()
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
