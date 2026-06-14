from __future__ import annotations

import os
import sys
import time

import pytest

from scripts.gamebridge.controller.controller import GameController
from scripts.gamebridge.input import keyboard as kb_input
from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.tests.integration.harness_client import HarnessProcess

pytestmark = pytest.mark.skipif(
    os.environ.get("GAMEBRIDGE_INTEGRATION") != "1" or sys.platform != "win32",
    reason="Windows-only integration test gated by GAMEBRIDGE_INTEGRATION=1",
)


def test_press_key_a_enters_character_a() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        kb_input.press_key("a")
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "key" and ev["phase"] == "down" and ev["keysym"].lower() == "a",
            timeout=2.0,
        )
        assert event["char"] == "a"


def test_press_key_enter_reports_return_keysym() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        kb_input.press_key(Key.ENTER)
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "key" and ev["phase"] == "down" and ev["keysym"] == "Return",
            timeout=2.0,
        )
        assert event["char"] == "\r" or event["keysym"] == "Return"


def test_type_text_updates_entry_text_in_order() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        kb_input.type_text("hello")
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "key" and ev["phase"] == "up" and ev.get("text") == "hello",
            timeout=5.0,
        )
        assert event["text"] == "hello"


def test_hold_shift_and_press_a_produces_uppercase_a() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        kb_input.key_down(Key.SHIFT)
        try:
            kb_input.press_key("a")
            event = harness.wait_for_event(
                lambda ev: ev["type"] == "key" and ev["phase"] == "down" and ev["keysym"] == "A",
                timeout=2.0,
            )
            assert event["char"] == "A"
        finally:
            kb_input.key_up(Key.SHIFT)


def test_release_all_keys_clears_stuck_shift_and_allows_lowercase_a() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        ctrl = GameController()
        ctrl.hold_key(Key.SHIFT)
        try:
            ctrl.release_all_keys()
            kb_input.press_key("a")
            event = harness.wait_for_event(
                lambda ev: ev["type"] == "key" and ev["phase"] == "down" and ev["keysym"].lower() == "a",
                timeout=2.0,
            )
            assert event["char"] == "a"
        finally:
            ctrl.release_all_keys()


def test_unknown_key_name_produces_no_key_event() -> None:
    with HarnessProcess() as harness:
        harness.focus_entry()
        kb_input.press_key("notakey")
        events = harness.read_events(lambda ev: ev["type"] == "key", timeout=1.0)
        assert events == []
