"""TestingTab — ad-hoc entity diagnostics panel for the dashboard.

Type an entity name, run one of the buttons below against the nearest matching
object/NPC, and read the result in the output log. Each button delegates to a
`diagnostics.describe_*` helper — to add a new check, write that helper and
add a row to `_ACTIONS`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from .. import diagnostics
from .theme import C
from .components import HDivider

if TYPE_CHECKING:
    from ..controller.controller import GameController
    from ..decision.engine import DecisionEngine


class TestingTab(QWidget):
    def __init__(self, ctrl: "GameController", engine: "DecisionEngine", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._ctrl = ctrl
        self._engine = engine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl = QLabel("Entity name")
        lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. Iron rocks, Mine cart, Man")
        self._name_input.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 5px 10px; color: {C.TEXT};"
        )
        layout.addWidget(self._name_input)

        hint = QLabel(
            "Resolves to the nearest object or NPC matching this name (case-insensitive). "
            "Each button below runs one check against it and appends the result below."
        )
        hint.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(HDivider())

        # To add a new check: write a diagnostics.describe_* helper and add a row here.
        self._ACTIONS = [
            ("Move into view",                self._run_move_into_view),
            ("Move towards",                  self._run_move_towards),
            ("Click minimap to move towards", self._run_click_minimap),
            ("Is occluded?",                  self._run_is_occluded),
            ("Is on screen?",                 self._run_is_on_screen),
            ("Is on minimap?",                self._run_is_on_minimap),
        ]
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (label, handler) in enumerate(self._ACTIONS):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        layout.addWidget(HDivider())

        kb_lbl = QLabel("Keyboard")
        kb_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(kb_lbl)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("Key — e.g. shift, ctrl, enter, f5, a")
        self._key_input.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 5px 10px; color: {C.TEXT};"
        )
        layout.addWidget(self._key_input)

        kb_hint = QLabel(
            "Press/hold/release a key via hardware scan-code injection (the same "
            "path RuneLite's modifier tracking requires). 'Release all keys' is a "
            "safety net for a stuck modifier."
        )
        kb_hint.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
        kb_hint.setWordWrap(True)
        layout.addWidget(kb_hint)

        self._KB_KEY_ACTIONS = [
            ("Press key",        self._run_press_key),
            ("Hold key",         self._run_hold_key),
            ("Release key",      self._run_release_key),
            ("Release all keys", self._run_release_all_keys),
        ]
        kb_grid = QGridLayout()
        kb_grid.setSpacing(8)
        for i, (label, handler) in enumerate(self._KB_KEY_ACTIONS):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            kb_grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(kb_grid)

        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("Text to type")
        self._text_input.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 5px 10px; color: {C.TEXT};"
        )
        layout.addWidget(self._text_input)

        kb_row = QHBoxLayout()
        kb_row.setSpacing(8)
        type_btn = QPushButton("Type text")
        type_btn.clicked.connect(self._run_type_text)
        kb_row.addWidget(type_btn)
        diag_btn = QPushButton("SendInput diagnostics")
        diag_btn.clicked.connect(self._run_sendinput_diagnostics)
        kb_row.addWidget(diag_btn)
        layout.addLayout(kb_row)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._output.document().setMaximumBlockCount(500)
        self._output.setStyleSheet(
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 6px; color: {C.TEXT}; font-size: 12px;"
        )
        layout.addWidget(self._output, stretch=1)

    def _resolve_entity(self) -> Optional[dict]:
        name = self._name_input.text().strip()
        if not name:
            self._log("Enter an entity name first.")
            return None
        entity = diagnostics.find_entity(self._engine.game, name)
        if entity is None:
            self._log(f"No object or NPC named '{name}' found nearby.")
        return entity

    def _log(self, message: str) -> None:
        self._output.append(message)

    def _run_move_into_view(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_move_into_view(self._ctrl, self._engine.game, entity))

    def _run_move_towards(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_move_towards(self._ctrl, entity))

    def _run_click_minimap(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_click_minimap(self._ctrl, self._engine.game, entity))

    def _run_is_occluded(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_is_occluded(self._engine.game, entity))

    def _run_is_on_screen(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_is_on_screen(entity))

    def _run_is_on_minimap(self) -> None:
        entity = self._resolve_entity()
        if entity is not None:
            self._log(diagnostics.describe_is_on_minimap(entity))

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------

    def _run_press_key(self) -> None:
        self._log(diagnostics.describe_press_key(self._ctrl, self._key_input.text()))

    def _run_hold_key(self) -> None:
        self._log(diagnostics.describe_hold_key(self._ctrl, self._key_input.text()))

    def _run_release_key(self) -> None:
        self._log(diagnostics.describe_release_key(self._ctrl, self._key_input.text()))

    def _run_release_all_keys(self) -> None:
        self._log(diagnostics.describe_release_all_keys(self._ctrl))

    def _run_type_text(self) -> None:
        self._log(diagnostics.describe_type_text(self._ctrl, self._text_input.text()))

    def _run_sendinput_diagnostics(self) -> None:
        self._log(diagnostics.describe_sendinput_diagnostics())
