"""
Tests for the dashboard's Logs tab (scripts.gamebridge.ui.log_tab).

QtLogHandler forwards formatted logging.LogRecords to LogTab via a Qt
signal; LogTab stores every record it receives and only renders the ones
at-or-above the level selected in its combo box. A QApplication (not just
QCoreApplication) is required here since LogTab constructs real widgets
(QTextEdit, QComboBox, ...).

Run with:
    python -m pytest scripts/gamebridge/tests/test_log_tab.py -v
"""
from __future__ import annotations

import logging

import pytest
from PyQt6.QtWidgets import QApplication

from scripts.gamebridge.ui.log_tab import LogTab, QtLogHandler


@pytest.fixture(scope="module", autouse=True)
def _qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_record(msg: str, level: int = logging.INFO, name: str = "test") -> logging.LogRecord:
    return logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


# ---------------------------------------------------------------------------
# QtLogHandler
# ---------------------------------------------------------------------------

def test_handler_emits_formatted_message_and_levelno():
    handler = QtLogHandler()
    received = []
    handler.log_emitted.connect(lambda msg, levelno: received.append((msg, levelno)))

    handler.emit(_make_record("hello world", level=logging.WARNING, name="my.module"))

    assert len(received) == 1
    msg, levelno = received[0]
    assert levelno == logging.WARNING
    assert "hello world" in msg
    assert "my.module" in msg
    assert "WARNING" in msg


def test_handler_swallows_formatting_errors_without_emitting():
    handler = QtLogHandler()
    received = []
    handler.log_emitted.connect(lambda msg, levelno: received.append((msg, levelno)))

    # %d with a string arg raises inside Formatter.format — emit() must not
    # propagate that into the logging call site or the Qt signal.
    bad_record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="%d", args=("not a number",), exc_info=None,
    )
    handler.emit(bad_record)

    assert received == []


# ---------------------------------------------------------------------------
# LogTab
# ---------------------------------------------------------------------------

def test_default_filter_shows_info_and_above_but_not_debug():
    tab = LogTab()

    tab._on_log("debug line", logging.DEBUG)
    tab._on_log("info line", logging.INFO)
    tab._on_log("error line", logging.ERROR)

    text = tab._text.toPlainText()
    assert "debug line" not in text
    assert "info line" in text
    assert "error line" in text


def test_changing_level_filter_rerenders_stored_entries():
    tab = LogTab()
    tab._on_log("debug line", logging.DEBUG)
    tab._on_log("info line", logging.INFO)

    assert "debug line" not in tab._text.toPlainText()

    tab._level_combo.setCurrentText("DEBUG")

    assert "debug line" in tab._text.toPlainText()
    assert "info line" in tab._text.toPlainText()


def test_all_filter_shows_every_stored_entry():
    tab = LogTab()
    tab._on_log("debug line", logging.DEBUG)
    tab._level_combo.setCurrentText("ALL")
    assert "debug line" in tab._text.toPlainText()


def test_clear_empties_text_and_stored_entries():
    tab = LogTab()
    tab._on_log("info line", logging.INFO)
    assert tab._entries

    tab._clear()

    assert not tab._entries
    assert tab._text.toPlainText() == ""


def test_attach_and_detach_register_and_remove_handler_from_root_logger():
    tab = LogTab()
    root = logging.getLogger()

    tab.attach(level=logging.DEBUG)
    assert tab._handler in root.handlers

    tab.detach()
    assert tab._handler not in root.handlers


def test_attached_handler_delivers_real_log_records_to_the_tab():
    tab = LogTab()
    tab.attach(level=logging.DEBUG)
    logger = logging.getLogger("scripts.gamebridge.tests.fake")

    try:
        logger.warning("something happened")
    finally:
        tab.detach()

    assert "something happened" in tab._text.toPlainText()
