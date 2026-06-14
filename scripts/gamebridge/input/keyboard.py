"""
Hardware keyboard emulation via raw SendInput scan codes.

Windows SendInput supports two keyboard injection modes:

- Virtual-key mode (wVk set, KEYEVENTF_SCANCODE clear) — what libraries such
  as pynput use by default for named keys (e.g. Key.shift -> VK_LSHIFT).
- Scan-code mode (wVk=0, KEYEVENTF_SCANCODE set, wScan = the PS/2 Set-1
  hardware scan code) — what a real keyboard driver reports.

Both generate WM_KEYDOWN/WM_KEYUP messages, but the RuneLite/RS client's
held-modifier tracking (used for e.g. shift-click-to-drop) only picks up a
key held via scan-code injection — the same as a physical keyboard.
Virtual-key injection (pynput's default) is invisible to it: holding Shift
that way leaves the client's left-click default unchanged. See PLAN.md,
"drop_item not registering Shift".

No external dependencies — mirrors input/mouse.py's raw-ctypes SendInput
approach, so ctypes.windll is only touched inside functions (safe to import
on non-Windows platforms).
"""
from __future__ import annotations

import ctypes
import time
from typing import List, Optional

# ------------------------------------------------------------------ #
# Windows INPUT structures
# ------------------------------------------------------------------ #

INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_SCANCODE    = 0x0008

MAPVK_VK_TO_VSC = 0


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    # The real Win32 INPUT union is sized to its largest member (MOUSEINPUT,
    # 32 bytes on x64), giving sizeof(INPUT) == 40. KEYBDINPUT alone is only
    # 24 bytes, which would make sizeof(_INPUT) == 32 — SendInput validates
    # cbSize against the real 40-byte INPUT size and rejects anything else
    # with ERROR_INVALID_PARAMETER (87). Pad the union to MOUSEINPUT's size
    # so the struct layout matches what SendInput expects.
    _fields_ = [("ki", _KEYBDINPUT), ("_padding", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


# ------------------------------------------------------------------ #
# Named keys -> PS/2 Set-1 hardware scan codes
# ------------------------------------------------------------------ #
# (scan code, is_extended) — extended keys carry the 0xE0 prefix a real
# keyboard sends for the navigation cluster and right-hand modifiers.

_NAMED_SCANCODES: dict[str, tuple[int, bool]] = {
    "escape":    (0x01, False),
    "enter":     (0x1C, False),
    "backspace": (0x0E, False),
    "tab":       (0x0F, False),
    "space":     (0x39, False),
    "shift":     (0x2A, False),  # left shift
    "ctrl":      (0x1D, False),  # left ctrl
    "alt":       (0x38, False),  # left alt
    "capslock":  (0x3A, False),
    "delete":    (0x53, True),
    "home":      (0x47, True),
    "end":       (0x4F, True),
    "pageup":    (0x49, True),
    "pagedown":  (0x51, True),
    "left":      (0x4B, True),
    "right":     (0x4D, True),
    "up":        (0x48, True),
    "down":      (0x50, True),
    "f1":  (0x3B, False), "f2":  (0x3C, False), "f3":  (0x3D, False), "f4":  (0x3E, False),
    "f5":  (0x3F, False), "f6":  (0x40, False), "f7":  (0x41, False), "f8":  (0x42, False),
    "f9":  (0x43, False), "f10": (0x44, False), "f11": (0x57, False), "f12": (0x58, False),
}


class Key:
    """Named key constants for use with press_key() / GameController.press_key():

        ctrl.press_key(Key.ESCAPE)   # close a dialog
        ctrl.press_key(Key.ENTER)    # confirm a prompt
        ctrl.press_key(Key.F5)       # function key
    """
    ESCAPE    = "escape"
    ENTER     = "enter"
    BACKSPACE = "backspace"
    TAB       = "tab"
    SPACE     = "space"
    SHIFT     = "shift"
    CTRL      = "ctrl"
    ALT       = "alt"
    CAPSLOCK  = "capslock"
    DELETE    = "delete"
    HOME      = "home"
    END       = "end"
    PAGE_UP   = "pageup"
    PAGE_DOWN = "pagedown"
    LEFT      = "left"
    RIGHT     = "right"
    UP        = "up"
    DOWN      = "down"
    F1  = "f1"
    F2  = "f2"
    F3  = "f3"
    F4  = "f4"
    F5  = "f5"
    F6  = "f6"
    F7  = "f7"
    F8  = "f8"
    F9  = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


# ------------------------------------------------------------------ #
# Low-level SendInput
# ------------------------------------------------------------------ #

def _send_scan(scan: int, extended: bool, key_up: bool) -> tuple[int, int]:
    """Inject one hardware scan-code key event via SendInput.

    Returns (SendInput return value, GetLastError()) — used by
    sendinput_diagnostics() to surface injection failures; other callers
    ignore the result.
    """
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP

    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    result = ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    error = ctypes.windll.kernel32.GetLastError()
    return result, error


def _char_scan(ch: str) -> tuple[int, bool]:
    """Resolve a single character to (scan code, needs_shift) using the
    active keyboard layout. Returns (0, False) if the layout has no
    mapping for `ch`."""
    user32 = ctypes.windll.user32
    user32.VkKeyScanW.restype = ctypes.c_short
    vk_shift = user32.VkKeyScanW(ord(ch))
    if vk_shift == -1:
        return 0, False
    vk = vk_shift & 0xFF
    needs_shift = bool((vk_shift >> 8) & 0x01)
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    return scan, needs_shift


def _resolve(key: str) -> tuple[int, bool, bool]:
    """Resolve a Key constant, named string, or single character to
    (scan code, is_extended, needs_shift)."""
    if not key:
        return 0, False, False
    named = _NAMED_SCANCODES.get(key.lower())
    if named is not None:
        return named[0], named[1], False
    if len(key) != 1:
        return 0, False, False
    scan, needs_shift = _char_scan(key)
    return scan, False, needs_shift


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def press_key(key: str, hold_ms: float = 50.0) -> None:
    """Press and release a key.

    key: a Key constant, a named string ("escape", "enter", "f1", …),
         or a single character.
    hold_ms: how long to hold the key down in milliseconds.
    """
    scan, extended, needs_shift = _resolve(key)
    if scan == 0:
        return
    if needs_shift:
        _send_scan(*_NAMED_SCANCODES["shift"], key_up=False)
    _send_scan(scan, extended, key_up=False)
    time.sleep(hold_ms / 1000.0)
    _send_scan(scan, extended, key_up=True)
    if needs_shift:
        _send_scan(*_NAMED_SCANCODES["shift"], key_up=True)


def key_down(key: str) -> None:
    """Press a key and hold it down — pair with `key_up` to release it.

    Used for modifier keys (e.g. Shift) that need to stay held across a
    separate mouse action, unlike `press_key` which presses and releases
    in one go.

    key: a Key constant, a named string ("escape", "enter", "f1", …),
         or a single character.
    """
    scan, extended, _ = _resolve(key)
    if scan == 0:
        return
    _send_scan(scan, extended, key_up=False)


def key_up(key: str) -> None:
    """Release a key previously held down with `key_down`.

    key: a Key constant, a named string, or a single character — must match
         the value passed to `key_down`.
    """
    scan, extended, _ = _resolve(key)
    if scan == 0:
        return
    _send_scan(scan, extended, key_up=True)


def type_text(text: str, delays: Optional[List[float]] = None) -> None:
    """Type a string character by character.

    delays: per-character pause after key-up in seconds.  Defaults to 0.10 s.
    """
    for i, ch in enumerate(text):
        press_key(ch, hold_ms=30.0)
        time.sleep(delays[i] if delays else 0.10)


def sendinput_diagnostics() -> dict:
    """Low-level SendInput health check, for the dashboard's Testing tab.

    Sends a harmless Shift down/up via the same scan-code path as
    key_down/key_up to whatever window currently has focus, and reports that
    window plus SendInput's return value and GetLastError(). This is the
    signal needed to tell "RuneLite isn't the focused window" (events go
    somewhere else entirely) apart from "SendInput itself is being blocked"
    (UIPI / BlockInput / antivirus) — neither of which is visible from the
    Java client side. Mirrors the interactive checks formerly in
    tools/debug_keyboard.py (removed), as a single reusable function.
    """
    user32 = ctypes.windll.user32

    hwnd = user32.GetForegroundWindow()
    title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buf, 256)
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)

    scan, extended = _NAMED_SCANCODES["shift"]
    result, error = _send_scan(scan, extended, key_up=False)
    _send_scan(scan, extended, key_up=True)

    return {
        "struct_size": ctypes.sizeof(_INPUT()),
        "foreground_hwnd": hwnd,
        "foreground_title": title_buf.value,
        "foreground_class": class_buf.value,
        "sendinput_result": result,
        "last_error": error,
    }
