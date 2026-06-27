"""
Tests for keyboard.py — hardware scan-code key injection via SendInput.

The lowest-level call (_send_scan, which wraps raw ctypes SendInput) is
patched out for press_key/key_down/key_up/type_text tests — no real input is
produced — mirroring test_mouse.py's pattern of not exercising the raw
SendInput call directly. _char_scan's VkKeyScanW/MapVirtualKeyW lookups are
covered separately by mocking ctypes.windll.

Run with:
    python -m pytest scripts/gamebridge/tests/test_keyboard.py -v
"""
from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.gamebridge.input import keyboard
from scripts.gamebridge.input.keyboard import (
    Key,
    _INPUT,
    _NAMED_SCANCODES,
    _char_scan,
    _resolve,
    key_down,
    key_up,
    press_key,
    sendinput_diagnostics,
    type_text,
)


# ---------------------------------------------------------------------------
# Key constants
# ---------------------------------------------------------------------------

class TestKeyConstants:
    def test_all_constants_have_scancodes(self):
        """Every Key.* value must resolve to a named scan code — no silent typos."""
        constants = {
            k: v for k, v in vars(Key).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        assert constants, "Key class has no string constants"
        for name, value in constants.items():
            assert value in _NAMED_SCANCODES, (
                f"Key.{name} = {value!r} has no entry in _NAMED_SCANCODES"
            )

    def test_escape(self):
        assert Key.ESCAPE == "escape"
        assert _NAMED_SCANCODES["escape"] == (0x01, False)

    def test_enter(self):
        assert Key.ENTER == "enter"
        assert _NAMED_SCANCODES["enter"] == (0x1C, False)

    def test_shift_scancode(self):
        assert Key.SHIFT == "shift"
        assert _NAMED_SCANCODES["shift"] == (0x2A, False)

    def test_f_keys_defined(self):
        for n in range(1, 13):
            assert hasattr(Key, f"F{n}"), f"Key.F{n} missing"
            assert getattr(Key, f"F{n}") == f"f{n}"
            assert f"f{n}" in _NAMED_SCANCODES

    def test_navigation_keys_are_extended(self):
        for name in ("LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "PAGE_UP", "PAGE_DOWN", "DELETE"):
            assert hasattr(Key, name), f"Key.{name} missing"
            value = getattr(Key, name)
            _, extended = _NAMED_SCANCODES[value]
            assert extended is True, f"Key.{name} should be an extended-key scan code"


# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------

class TestResolve:
    def test_named_key_resolves_without_shift(self):
        scan, extended, needs_shift = _resolve(Key.ESCAPE)
        assert (scan, extended) == _NAMED_SCANCODES["escape"]
        assert needs_shift is False

    def test_extended_key_resolves_extended_flag(self):
        scan, extended, needs_shift = _resolve(Key.LEFT)
        assert (scan, extended) == _NAMED_SCANCODES["left"]
        assert extended is True
        assert needs_shift is False

    def test_key_lookup_is_case_insensitive(self):
        scan, extended, _ = _resolve("ESCAPE")
        assert (scan, extended) == _NAMED_SCANCODES["escape"]

    def test_unnamed_char_falls_back_to_char_scan(self):
        with patch("scripts.gamebridge.input.keyboard._char_scan", return_value=(0x1E, True)) as mock_char_scan:
            scan, extended, needs_shift = _resolve("A")
        mock_char_scan.assert_called_once_with("A")
        assert scan == 0x1E
        assert extended is False
        assert needs_shift is True


# ---------------------------------------------------------------------------
# _char_scan
# ---------------------------------------------------------------------------

class TestCharScan:
    def test_lowercase_letter_no_shift(self):
        mock_user32 = MagicMock()
        mock_user32.VkKeyScanW.return_value = 0x0041  # vk='A' (0x41), no shift bits
        mock_user32.MapVirtualKeyW.return_value = 0x1E
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32 = mock_user32
            scan, needs_shift = _char_scan("a")
        assert scan == 0x1E
        assert needs_shift is False
        mock_user32.MapVirtualKeyW.assert_called_once_with(0x41, 0)

    def test_uppercase_letter_needs_shift(self):
        mock_user32 = MagicMock()
        mock_user32.VkKeyScanW.return_value = 0x0141  # shift bit set + vk 0x41
        mock_user32.MapVirtualKeyW.return_value = 0x1E
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32 = mock_user32
            scan, needs_shift = _char_scan("A")
        assert scan == 0x1E
        assert needs_shift is True

    def test_unmappable_char_returns_zero(self):
        mock_user32 = MagicMock()
        mock_user32.VkKeyScanW.return_value = -1
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32 = mock_user32
            scan, needs_shift = _char_scan("é")
        assert scan == 0
        assert needs_shift is False
        mock_user32.MapVirtualKeyW.assert_not_called()


# ---------------------------------------------------------------------------
# press_key
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard._send_scan")
class TestPressKey:
    def test_named_key_sends_down_then_up(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.ESCAPE)
        scan, extended = _NAMED_SCANCODES["escape"]
        assert mock_send.call_args_list == [
            call(scan, extended, key_up=False),
            call(scan, extended, key_up=True),
        ]

    def test_extended_key_sets_extended_flag(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard.time"):
            press_key(Key.LEFT)
        for c in mock_send.call_args_list:
            assert c.args[1] is True

    def test_lowercase_char_no_shift_wrap(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard._char_scan", return_value=(0x1E, False)):
            with patch("scripts.gamebridge.input.keyboard.time"):
                press_key("a")
        assert mock_send.call_args_list == [
            call(0x1E, False, key_up=False),
            call(0x1E, False, key_up=True),
        ]

    def test_uppercase_char_wrapped_in_shift(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard._char_scan", return_value=(0x1E, True)):
            with patch("scripts.gamebridge.input.keyboard.time"):
                press_key("A")
        shift_scan, shift_extended = _NAMED_SCANCODES["shift"]
        assert mock_send.call_args_list == [
            call(shift_scan, shift_extended, key_up=False),
            call(0x1E, False, key_up=False),
            call(0x1E, False, key_up=True),
            call(shift_scan, shift_extended, key_up=True),
        ]

    def test_holds_for_requested_duration(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard.time") as mock_time:
            press_key(Key.ESCAPE, hold_ms=120.0)
        mock_time.sleep.assert_called_once_with(0.12)


# ---------------------------------------------------------------------------
# key_down / key_up
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard._send_scan")
class TestKeyDown:
    def test_named_key_sends_down_only(self, mock_send):
        key_down(Key.SHIFT)
        scan, extended = _NAMED_SCANCODES["shift"]
        mock_send.assert_called_once_with(scan, extended, key_up=False)

    def test_single_char_uses_char_scan(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard._char_scan", return_value=(0x1E, False)):
            key_down("a")
        mock_send.assert_called_once_with(0x1E, False, key_up=False)


@patch("scripts.gamebridge.input.keyboard._send_scan")
class TestKeyUp:
    def test_named_key_sends_up_only(self, mock_send):
        key_up(Key.SHIFT)
        scan, extended = _NAMED_SCANCODES["shift"]
        mock_send.assert_called_once_with(scan, extended, key_up=True)

    def test_single_char_uses_char_scan(self, mock_send):
        with patch("scripts.gamebridge.input.keyboard._char_scan", return_value=(0x1E, False)):
            key_up("a")
        mock_send.assert_called_once_with(0x1E, False, key_up=True)


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.input.keyboard.press_key")
class TestTypeText:
    def test_each_char_pressed_in_order(self, mock_press):
        with patch("scripts.gamebridge.input.keyboard.time"):
            type_text("hi")
        assert mock_press.call_args_list == [
            call("h", hold_ms=30.0),
            call("i", hold_ms=30.0),
        ]

    def test_empty_string_sends_nothing(self, mock_press):
        with patch("scripts.gamebridge.input.keyboard.time"):
            type_text("")
        mock_press.assert_not_called()

    def test_default_delay_between_chars(self, mock_press):
        with patch("scripts.gamebridge.input.keyboard.time") as mock_time:
            type_text("ab")
        assert mock_time.sleep.call_args_list == [call(0.10), call(0.10)]

    def test_custom_delays_used(self, mock_press):
        with patch("scripts.gamebridge.input.keyboard.time") as mock_time:
            type_text("ab", delays=[0.5, 1.0])
        assert mock_time.sleep.call_args_list == [call(0.5), call(1.0)]


# ---------------------------------------------------------------------------
# sendinput_diagnostics
# ---------------------------------------------------------------------------

def _mock_windll(*, sendinput_result=1, last_error=0,
                  title="RuneLite - Calum", cls="SunAwtFrame", hwnd=0x1234):
    mock_user32 = MagicMock()
    mock_user32.GetForegroundWindow.return_value = hwnd

    def _set_title(_hwnd, buf, _n):
        buf.value = title
        return 1

    def _set_class(_hwnd, buf, _n):
        buf.value = cls
        return 1

    mock_user32.GetWindowTextW.side_effect = _set_title
    mock_user32.GetClassNameW.side_effect = _set_class
    mock_user32.SendInput.return_value = sendinput_result

    mock_kernel32 = MagicMock()
    mock_kernel32.GetLastError.return_value = last_error

    mock_windll = MagicMock()
    mock_windll.user32 = mock_user32
    mock_windll.kernel32 = mock_kernel32
    return mock_windll


class TestSendInputDiagnostics:
    def test_reports_foreground_window_and_sendinput_result(self):
        mock_windll = _mock_windll()
        with patch("ctypes.windll", mock_windll, create=True):
            info = sendinput_diagnostics()

        assert info["foreground_hwnd"] == 0x1234
        assert info["foreground_title"] == "RuneLite - Calum"
        assert info["foreground_class"] == "SunAwtFrame"
        assert info["sendinput_result"] == 1
        assert info["last_error"] == 0
        # The real Win32 INPUT struct is sized to its largest union member
        # (MOUSEINPUT): 40 bytes on 64-bit Windows, 28 on 32-bit. A mismatch
        # here means SendInput will reject every call with
        # ERROR_INVALID_PARAMETER (87) — see PLAN.md.
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        assert info["struct_size"] == expected_size
        assert ctypes.sizeof(_INPUT) == expected_size

    def test_sends_shift_down_then_up(self):
        mock_windll = _mock_windll()
        with patch("ctypes.windll", mock_windll, create=True):
            sendinput_diagnostics()

        assert mock_windll.user32.SendInput.call_count == 2

    def test_reports_access_denied(self):
        mock_windll = _mock_windll(sendinput_result=0, last_error=5)
        with patch("ctypes.windll", mock_windll, create=True):
            info = sendinput_diagnostics()

        assert info["sendinput_result"] == 0
        assert info["last_error"] == 5

    def test_reports_when_runelite_not_foreground(self):
        mock_windll = _mock_windll(title="Discord", cls="Chrome_WidgetWin_1")
        with patch("ctypes.windll", mock_windll, create=True):
            info = sendinput_diagnostics()

        assert info["foreground_title"] == "Discord"
        assert info["foreground_class"] == "Chrome_WidgetWin_1"


# ---------------------------------------------------------------------------
# _send_scan return value
# ---------------------------------------------------------------------------

class TestSendScanReturnsResultAndError:
    def test_returns_sendinput_result_and_last_error(self):
        mock_windll = _mock_windll(sendinput_result=1, last_error=0)
        with patch("ctypes.windll", mock_windll, create=True):
            from scripts.gamebridge.input.keyboard import _send_scan
            result, error = _send_scan(0x2A, False, key_up=False)

        assert (result, error) == (1, 0)


# ---------------------------------------------------------------------------
# Pluggable backend — see GameController.use_bridge_input()
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_backend_after_each_test():
    """Guarantee no test leaks a backend into the next one — set_backend()
    mutates module-level state shared across the whole test session."""
    yield
    keyboard.clear_backend()


class TestBackendDelegation:
    def test_press_key_delegates_to_backend_when_set(self):
        backend = MagicMock()
        keyboard.set_backend(backend)

        press_key(Key.ESCAPE, hold_ms=75.0)

        backend.press_key.assert_called_once_with(Key.ESCAPE, hold_ms=75.0)

    def test_key_down_delegates_to_backend_when_set(self):
        backend = MagicMock()
        keyboard.set_backend(backend)

        key_down(Key.SHIFT)

        backend.key_down.assert_called_once_with(Key.SHIFT)

    def test_key_up_delegates_to_backend_when_set(self):
        backend = MagicMock()
        keyboard.set_backend(backend)

        key_up(Key.SHIFT)

        backend.key_up.assert_called_once_with(Key.SHIFT)

    def test_type_text_routes_each_char_through_backend(self):
        """type_text() itself is unchanged — it only calls press_key()
        per character, so a backend swap is all it takes to retarget it."""
        backend = MagicMock()
        keyboard.set_backend(backend)

        with patch.object(keyboard, "time"):
            type_text("hi")

        assert backend.press_key.call_args_list == [
            call("h", hold_ms=30.0),
            call("i", hold_ms=30.0),
        ]

    def test_clear_backend_restores_os_sendinput_path(self):
        backend = MagicMock()
        keyboard.set_backend(backend)
        keyboard.clear_backend()

        with patch.object(keyboard, "_send_scan") as mock_send, \
                patch.object(keyboard, "time"):
            press_key(Key.ESCAPE)

        mock_send.assert_called()
        backend.press_key.assert_not_called()
