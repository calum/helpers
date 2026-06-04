"""
Tests for keyboard.py — Key constants, VK lookup, and extended-key flag.

Hardware calls (ctypes.windll) are patched out; no real input is produced.

Run with:
    python -m pytest scripts/gamebridge/tests/test_keyboard.py -v
"""
from __future__ import annotations

from unittest.mock import call, patch, MagicMock

import pytest

from scripts.gamebridge.input.keyboard import (
    Key,
    _EXTENDED_KEYS,
    _VK,
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    press_key,
)


# ---------------------------------------------------------------------------
# Key constants
# ---------------------------------------------------------------------------

class TestKeyConstants:
    def test_all_constants_are_in_vk_table(self):
        """Every Key.* value must resolve to a VK code — no silent typos."""
        constants = {
            k: v for k, v in vars(Key).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        assert constants, "Key class has no string constants"
        for name, value in constants.items():
            assert value in _VK, (
                f"Key.{name} = {value!r} has no entry in _VK — "
                "either the constant is misspelled or _VK needs updating"
            )

    def test_escape(self):
        assert Key.ESCAPE == "escape"

    def test_enter(self):
        assert Key.ENTER == "enter"

    def test_f_keys_defined(self):
        for n in range(1, 13):
            assert hasattr(Key, f"F{n}"), f"Key.F{n} missing"
            assert getattr(Key, f"F{n}") == f"f{n}"

    def test_navigation_keys_defined(self):
        for name in ("LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "PAGE_UP", "PAGE_DOWN", "DELETE"):
            assert hasattr(Key, name), f"Key.{name} missing"


# ---------------------------------------------------------------------------
# Extended-key flag
# ---------------------------------------------------------------------------

class TestExtendedKeys:
    def test_extended_keys_are_subset_of_vk(self):
        """Every extended key must also be in _VK — otherwise the flag is never used."""
        assert _EXTENDED_KEYS <= set(_VK.keys()), (
            f"Keys in _EXTENDED_KEYS missing from _VK: {_EXTENDED_KEYS - set(_VK.keys())}"
        )

    def test_navigation_keys_are_extended(self):
        for key in ("left", "right", "up", "down", "home", "end", "pageup", "pagedown", "delete"):
            assert key in _EXTENDED_KEYS, f"{key!r} should be an extended key"

    def test_escape_is_not_extended(self):
        assert "escape" not in _EXTENDED_KEYS

    def test_enter_is_not_extended(self):
        assert "enter" not in _EXTENDED_KEYS


# ---------------------------------------------------------------------------
# press_key — VK path (named keys)
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard.ctypes")
class TestPressKeyVk:
    def _send_input_calls(self, mock_ctypes):
        return mock_ctypes.windll.user32.SendInput.call_args_list

    def test_escape_sends_two_inputs(self, mock_ctypes):
        """Key-down + key-up = two SendInput calls."""
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)
        assert mock_ctypes.windll.user32.SendInput.call_count == 2

    def test_key_constant_accepted(self, mock_ctypes):
        """Key.ENTER (a string) is handled identically to the bare string."""
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ENTER)
        assert mock_ctypes.windll.user32.SendInput.call_count == 2

    def test_escape_no_extended_flag(self, mock_ctypes):
        """Escape is not an extended key — dwFlags for key-down must be 0."""
        captured_flags = []

        def fake_send(count, ref, size):
            # The INPUT struct is passed by reference; read dwFlags from ki
            inp = ref._obj
            captured_flags.append(inp.ki.dwFlags)

        mock_ctypes.windll.user32.SendInput.side_effect = fake_send
        mock_ctypes.byref.side_effect = lambda x: MagicMock(_obj=x)
        mock_ctypes.sizeof.return_value = 28

        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)

        # key-down flags must not include KEYEVENTF_EXTENDEDKEY
        keydown_flags = captured_flags[0]
        assert not (keydown_flags & KEYEVENTF_EXTENDEDKEY), (
            f"Escape key-down has KEYEVENTF_EXTENDEDKEY set unexpectedly: {keydown_flags:#x}"
        )

    def test_f1_sends_two_inputs(self, mock_ctypes):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.F1)
        assert mock_ctypes.windll.user32.SendInput.call_count == 2


# ---------------------------------------------------------------------------
# press_key — Unicode path (bare characters)
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard.ctypes")
class TestPressKeyUnicode:
    def test_single_char_sends_two_inputs(self, mock_ctypes):
        """A plain character (e.g. '1') should use the Unicode path."""
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key("1")
        assert mock_ctypes.windll.user32.SendInput.call_count == 2
