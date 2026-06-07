"""Reusable Qt widgets: Card, HDivider, StatBar, ConnectionDot."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .theme import C, _qc


class Card(QWidget):
    """Rounded dark panel with an optional uppercase title label."""

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


class HDivider(QFrame):
    """Single-pixel horizontal rule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {C.BORDER}; border: none;")


class StatBar(QWidget):
    """
    Pill-shaped progress bar with a label on the left and numeric value on the right.
    Drawn entirely with QPainter — no sub-widgets.
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

        p.setPen(_qc(C.TEXT_MUTED))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(0, 0, self._LABEL_W, h, Qt.AlignmentFlag.AlignVCenter, self._label)

        tr = QRectF(bar_x, bar_y, bar_w, self._BAR_H)
        tp = QPainterPath()
        tp.addRoundedRect(tr, self._BAR_H / 2, self._BAR_H / 2)
        p.fillPath(tp, self._dim)

        frac = self._value / self._max
        fill_w = max(0.0, min(float(bar_w), bar_w * frac))
        if fill_w >= self._BAR_H:
            fp = QPainterPath()
            fp.addRoundedRect(QRectF(bar_x, bar_y, fill_w, self._BAR_H),
                              self._BAR_H / 2, self._BAR_H / 2)
            p.fillPath(fp, self._color)
        elif fill_w > 0:
            p.fillRect(QRectF(bar_x, bar_y, fill_w, self._BAR_H), self._color)

        p.setPen(_qc(C.TEXT))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        p.drawText(
            w - self._VAL_W, 0, self._VAL_W, h,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            str(self._value),
        )
        p.end()


class ConnectionDot(QWidget):
    """Small coloured indicator dot — green when connected, red when not."""

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
