"""HullDebugTab — visual overlay for inspecting hulls, widgets and interfaces.

Captures a screenshot of the RuneLite client and draws coloured overlays for
the selected NPC/object hull, widget bounds, or interface bounds, so that
hull-detection and interface-filter logic can be debugged visually.

Selecting an on-screen object or NPC also marks its `canvasX`/`canvasY` —
the exact point `GameState.is_occluded` tests, which can sit somewhere
visually surprising relative to the hull outline — with a crosshair, and
outlines whichever registered panel (if any) is found sitting on it. That's
the live, visual answer to "why does is_occluded say this is blocked?".
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import settings as _settings
from ..state import interfaces as iface_registry
from ..controller.controller import _find_window_by_prefix
from ..widget_ids import BankDepositBox, Bankmain, Inventory, Wornitems
from .theme import C, _iface_color
from .components import HDivider

if TYPE_CHECKING:
    from ..decision.engine import DecisionEngine

KNOWN_INTERFACE_GROUPS: frozenset[int] = frozenset({
    BankDepositBox.GROUP, Bankmain.GROUP, Inventory.GROUP, Wornitems.GROUP,
})


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


class HullDebugTab(QWidget):
    def __init__(self, engine: "DecisionEngine", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._engine = engine
        self._hull_last_widgets: list[dict] = []
        self._hull_last_interfaces: list[dict] = []
        self._hull_raw_pixmap: Optional[QPixmap] = None

        layout = QVBoxLayout(self)
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

    # ------------------------------------------------------------------
    # Public entry point — called once per tick from the dashboard
    # ------------------------------------------------------------------

    def update_state(self, g, widgets: list[dict], interfaces: list[dict]) -> None:
        self._hull_last_widgets = widgets
        self._hull_last_interfaces = interfaces
        if not self._hull_freeze_btn.isChecked():
            self._refresh_hull_combos(g, widgets, interfaces)

    # ------------------------------------------------------------------
    # Toggle handlers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Combo population
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Capture & overlay drawing
    # ------------------------------------------------------------------

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

        # The point `is_occluded` actually tests is canvasX/canvasY — the
        # game's reported click point, not the hull centroid drawn above (the
        # two can differ). Marking it — and outlining whatever panel is found
        # sitting on it — is what turns a confusing "occluded" verdict into
        # something visible: a real panel in the way, or a registry entry
        # whose bounds/group don't mean what we think.
        for target, kind in ((target_obj, "Object"), (target_npc, "NPC")):
            if target is None:
                continue
            cx, cy = target.get("canvasX"), target.get("canvasY")
            if cx is None or cy is None:
                continue
            blocker = g.occluding_widget_at(cx, cy)
            self._draw_crosshair(painter, cx, cy - y_off, "#ff3b3b" if blocker else "#3fb950")
            if blocker is None:
                status_parts.append(f"{kind} click point ({cx:.0f},{cy:.0f}) is clear.")
                continue
            b = blocker.get("bounds") or {}
            if b.get("width", 0) > 0 and b.get("height", 0) > 0:
                self._draw_rect_focus(painter, b, y_off, "#ff3b3b")
            gid = blocker.get("groupId", "?")
            cid = blocker.get("childId", "?")
            bname = iface_registry.name_for(gid)
            label = f"{bname} (G{gid}:{cid})" if bname else f"G{gid}:{cid}"
            status_parts.append(f"{kind} click point ({cx:.0f},{cy:.0f}) is blocked by {label}.")

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

    def _draw_crosshair(
        self,
        painter: QPainter,
        x: float,
        y: float,
        color_hex: str,
        size: float = 8.0,
    ) -> None:
        """Mark one exact canvas point — the spot `is_occluded` tests, which
        (unlike a hull's centroid) is the game's own reported click point and
        can land somewhere visually surprising relative to the hull outline."""
        color = QColor(color_hex)
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(x - size, y), QPointF(x + size, y))
        painter.drawLine(QPointF(x, y - size), QPointF(x, y + size))
        painter.drawEllipse(QPointF(x, y), size * 0.6, size * 0.6)

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
