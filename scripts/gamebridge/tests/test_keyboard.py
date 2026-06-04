"""
Tests for keyboard.py — Key constants and press_key / type_text behaviour.

pynput's Controller is patched out; no real input is produced.

Run with:
    python -m pytest scripts/gamebridge/tests/test_keyboard.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from pynput.keyboard import Key as PKey

from scripts.gamebridge.input.keyboard import (
    Key,
    _PYNPUT_MAP,
    press_key,
    type_text,
)


# ---------------------------------------------------------------------------
# Key constants
# ---------------------------------------------------------------------------

class TestKeyConstants:
    def test_all_constants_are_in_pynput_map(self):
        """Every Key.* value must resolve to a pynput key — no silent typos."""
        constants = {
            k: v for k, v in vars(Key).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        assert constants, "Key class has no string constants"
        for name, value in constants.items():
            assert value in _PYNPUT_MAP, (
                f"Key.{name} = {value!r} has no entry in _PYNPUT_MAP"
            )

    def test_escape(self):
        assert Key.ESCAPE == "escape"
        assert _PYNPUT_MAP["escape"] is PKey.esc

    def test_enter(self):
        assert Key.ENTER == "enter"
        assert _PYNPUT_MAP["enter"] is PKey.enter

    def test_f_keys_defined(self):
        for n in range(1, 13):
            assert hasattr(Key, f"F{n}"), f"Key.F{n} missing"
            assert getattr(Key, f"F{n}") == f"f{n}"
            assert f"f{n}" in _PYNPUT_MAP

    def test_navigation_keys_defined(self):
        for name in ("LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "PAGE_UP", "PAGE_DOWN", "DELETE"):
            assert hasattr(Key, name), f"Key.{name} missing"


# ---------------------------------------------------------------------------
# press_key
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard._ctrl")
class TestPressKey:
    def test_escape_calls_press_and_release(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)
        mock_ctrl.press.assert_called_once_with(PKey.esc)
        mock_ctrl.release.assert_called_once_with(PKey.esc)

    def test_enter_calls_press_and_release(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ENTER)
        mock_ctrl.press.assert_called_once_with(PKey.enter)
        mock_ctrl.release.assert_called_once_with(PKey.enter)

    def test_f1_mapped_correctly(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.F1)
        mock_ctrl.press.assert_called_once_with(PKey.f1)

    def test_single_char_uses_character_directly(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key("a")
        mock_ctrl.press.assert_called_once_with("a")
        mock_ctrl.release.assert_called_once_with("a")

    def test_key_constant_string_accepted(self, mock_ctrl):
        """Key.ESCAPE is just a string — passing it must behave identically."""
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)
        assert mock_ctrl.press.call_count == 1
        assert mock_ctrl.release.call_count == 1

    def test_press_and_release_called_same_key(self, mock_ctrl):
        """The same key object must be passed to both press and release."""
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)
        pressed  = mock_ctrl.press.call_args.args[0]
        released = mock_ctrl.release.call_args.args[0]
        assert pressed is released


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard._ctrl")
class TestTypeText:
    def test_each_char_pressed_and_released(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            type_text("hi")
        assert mock_ctrl.press.call_count == 2
        assert mock_ctrl.release.call_count == 2

    def test_chars_sent_in_order(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            type_text("ab")
        press_calls = [c.args[0] for c in mock_ctrl.press.call_args_list]
        assert press_calls == ["a", "b"]

    def test_empty_string_sends_nothing(self, mock_ctrl):
        with patch("scripts.gamebridge.input.keyboard.time"):
            type_text("")
        mock_ctrl.press.assert_not_called()
