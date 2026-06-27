"""
LogTab — live view of the Python logging output inside the dashboard.

``QtLogHandler`` is a ``logging.Handler`` that forwards every formatted
record to the GUI thread via a Qt signal (safe even when the record is
emitted from BridgeTicker's or RoutineRunner's worker thread — Qt queues
the signal across threads automatically). It carries the same formatter
used for ``~/.gamebridge/gamebridge.log`` (see ``main.py``), so what you see
here is the same content that ends up in the log file when ``--debug`` is
passed, without needing to tail the file from disk.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from .theme import C

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

_LEVEL_COLORS = {
    logging.DEBUG:    C.TEXT_DIM,
    logging.INFO:     C.TEXT,
    logging.WARNING:  C.WARNING,
    logging.ERROR:    C.DANGER,
    logging.CRITICAL: C.DANGER,
}

_LEVEL_NAMES = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
_MAX_ENTRIES = 2000


class QtLogHandler(QObject, logging.Handler):
    """Logging handler that forwards formatted records to the dashboard."""

    log_emitted = pyqtSignal(str, int)

    def __init__(self) -> None:
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.log_emitted.emit(msg, record.levelno)


class LogTab(QWidget):
    """Displays log records streamed from the root logger, with level filtering."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: deque[tuple[str, int]] = deque(maxlen=_MAX_ENTRIES)
        self._autoscroll = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lvl_lbl = QLabel("Level:")
        lvl_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px;")
        self._level_combo = QComboBox()
        self._level_combo.addItems(_LEVEL_NAMES)
        self._level_combo.setCurrentText("INFO")
        self._level_combo.currentTextChanged.connect(self._render)

        self._autoscroll_chk = QCheckBox("Autoscroll")
        self._autoscroll_chk.setChecked(True)
        self._autoscroll_chk.toggled.connect(self._set_autoscroll)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(70)
        clear_btn.clicked.connect(self._clear)

        toolbar.addWidget(lvl_lbl)
        toolbar.addWidget(self._level_combo)
        toolbar.addWidget(self._autoscroll_chk)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)
        layout.addLayout(toolbar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.document().setMaximumBlockCount(_MAX_ENTRIES)
        layout.addWidget(self._text)

        self._handler = QtLogHandler()
        self._handler.log_emitted.connect(self._on_log)

    # ------------------------------------------------------------------
    # Handler lifecycle
    # ------------------------------------------------------------------

    def attach(self, level: int = logging.DEBUG) -> None:
        """Register the handler against the root logger."""
        self._handler.setLevel(level)
        logging.getLogger().addHandler(self._handler)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self._handler)

    # ------------------------------------------------------------------
    # Record handling
    # ------------------------------------------------------------------

    def _min_level(self) -> int:
        name = self._level_combo.currentText()
        return 0 if name == "ALL" else getattr(logging, name)

    def _on_log(self, msg: str, levelno: int) -> None:
        self._entries.append((msg, levelno))
        if levelno >= self._min_level():
            self._append_line(msg, levelno)

    def _append_line(self, msg: str, levelno: int) -> None:
        color = _LEVEL_COLORS.get(levelno, C.TEXT)
        safe = msg.replace("&", "&amp;").replace("<", "&lt;")
        self._text.append(f'<span style="color:{color};">{safe}</span>')
        if self._autoscroll:
            self._text.moveCursor(QTextCursor.MoveOperation.End)

    def _render(self) -> None:
        self._text.clear()
        min_level = self._min_level()
        for msg, levelno in self._entries:
            if levelno >= min_level:
                self._append_line(msg, levelno)

    def _set_autoscroll(self, checked: bool) -> None:
        self._autoscroll = checked

    def _clear(self) -> None:
        self._entries.clear()
        self._text.clear()
