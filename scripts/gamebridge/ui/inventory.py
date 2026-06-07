"""InventoryWidget — 4×7 painted slot grid with hover tooltips."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from .theme import C, _qc


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
            return -1
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
        by_slot = {s["slot"]: s for s in self._slots}

        for i in range(28):
            col = i % self._COLS
            row = i // self._COLS
            x = col * (sz + gap)
            y = row * (sz + gap)
            rect = QRectF(x, y, sz, sz)

            slot = by_slot.get(i)
            occupied = slot is not None and slot.get("itemId", -1) != -1

            slot_path = QPainterPath()
            slot_path.addRoundedRect(rect, 5, 5)
            p.fillPath(slot_path, _qc("#1a2030" if occupied else "#10141c"))
            p.setPen(QPen(_qc(C.ACCENT if occupied else C.BORDER_SUBTLE), 1.0))
            p.drawPath(slot_path)

            if occupied:
                item_id = slot["itemId"]
                qty     = slot.get("qty", 1)

                p.setPen(_qc(C.TEXT_MUTED))
                p.setFont(QFont("Segoe UI", 7))
                p.drawText(
                    int(x), int(y) + 2, sz, 14,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    str(item_id),
                )

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
