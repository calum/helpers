"""MinimapWidget — QPainter tile-grid minimap centred on the player."""
from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QColor
from PyQt6.QtWidgets import QWidget

from ..state.game_state import GameState
from .theme import C, _qc


class MinimapWidget(QWidget):
    _RADIUS = 8    # tiles from centre → 17×17 grid
    _CELL   = 13   # pixels per tile

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

        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, w, h), 6, 6)
        p.fillPath(bg, _qc("#080c14"))

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

        # FOV ellipse fitted to visible entity bounds; falls back to pitch-based circle.
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
            a_t = b_t = 10.0 - _t * 5.0

        cx_s = pad + (r + cx_t + 0.5) * cell
        cy_s = pad + (r - cy_t + 0.5) * cell
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

        p.setBrush(_qc("#0d3020"))
        p.setPen(Qt.PenStyle.NoPen)
        halo_r = cell * 0.72
        p.drawEllipse(QPointF(cx_p, cy_p), halo_r, halo_r)

        dot_r = max(3.5, cell * 0.42)
        p.setBrush(_qc(C.PLAYER_COLOR))
        p.setPen(QPen(_qc("#c0ffd0"), 0.7))
        p.drawEllipse(QPointF(cx_p, cy_p), dot_r, dot_r)

        tick = cell * 0.8
        dx = math.sin(angle) * tick
        dy = -math.cos(angle) * tick
        p.setPen(QPen(_qc(C.PLAYER_COLOR), 1.8,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx_p, cy_p), QPointF(cx_p + dx, cy_p + dy))

        p.end()
