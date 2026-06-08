"""SettingsTab — persisted dashboard settings (window name, hull Y offset, hotkey reference)."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import settings as _settings
from ..hotkeys import HOTKEY_STOP, HOTKEY_KILL
from .theme import C
from .components import HDivider


class SettingsTab(QWidget):
    def __init__(self, on_status: Callable[[str], None], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._on_status = on_status

        layout = QVBoxLayout(self)
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

    def _save_window_name(self) -> None:
        name = self._wn_input.text().strip()
        if name:
            _settings.set("window_name", name)
            self._on_status(f"✓ Window name saved: {name}")

    def _save_hull_y_offset(self) -> None:
        val = self._hull_y_spin.value()
        _settings.set("hull_y_offset", val)
        self._on_status(f"✓ Hull Y offset saved: {val:+d} px")
