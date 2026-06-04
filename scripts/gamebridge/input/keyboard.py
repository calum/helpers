"""
Hardware keyboard emulation for Windows via ctypes SendInput (Unicode path).

Using KEYEVENTF_UNICODE means we send characters directly without having to
map them to virtual-key codes — handles any Unicode text without a layout
lookup table.  Named keys (Enter, Escape, …) use the VK path.
"""
from __future__ import annotations

import ctypes
import time
from typing import List, Optional

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Virtual-key codes for named keys
_VK: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "backspace": 0x08,
    "tab": 0x09,
    "escape": 0x1B,
    "space": 0x20,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "capslock": 0x14,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},  # F1–F12
}

# These keys live on the extended part of the keyboard (not numpad).
# SendInput requires KEYEVENTF_EXTENDEDKEY so the OS generates the right
# scan-code translation; without it some applications receive the wrong key.
_EXTENDED_KEYS = frozenset({
    "delete", "home", "end", "pageup", "pagedown",
    "left", "right", "up", "down",
})


class Key:
    """Named key constants for use with press_key() / GameController.press_key().

    Use these instead of bare strings to catch typos at import time and
    to get IDE completion:

        ctrl.press_key(Key.ESCAPE)   # close a dialog
        ctrl.press_key(Key.ENTER)    # confirm a prompt
        ctrl.press_key(Key.F1)       # function key
    """
    ESCAPE = "escape"
    ENTER = "enter"
    BACKSPACE = "backspace"
    TAB = "tab"
    SPACE = "space"
    SHIFT = "shift"
    CTRL = "ctrl"
    ALT = "alt"
    CAPSLOCK = "capslock"
    DELETE = "delete"
    HOME = "home"
    END = "end"
    PAGE_UP = "pageup"
    PAGE_DOWN = "pagedown"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


def _send_unicode(char: str, key_up: bool = False) -> None:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = ord(char)
    inp.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_vk(vk: int, key_up: bool = False, extended: bool = False) -> None:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = 0
    flags = KEYEVENTF_KEYUP if key_up else 0
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #

def press_key(key: str, hold_ms: float = 50.0) -> None:
    """
    Press and release a key.

    key: a Key constant, a named key string ("enter", "escape", "f1", …),
         or a single character.
    hold_ms: how long to hold the key down (milliseconds).
    """
    k = key.lower()
    vk = _VK.get(k)
    if vk is not None:
        extended = k in _EXTENDED_KEYS
        _send_vk(vk, key_up=False, extended=extended)
        time.sleep(hold_ms / 1000.0)
        _send_vk(vk, key_up=True, extended=extended)
    else:
        ch = key[0]
        _send_unicode(ch, key_up=False)
        time.sleep(hold_ms / 1000.0)
        _send_unicode(ch, key_up=True)


def type_text(text: str, delays: Optional[List[float]] = None) -> None:
    """
    Type a string character by character.

    delays: per-character pause *after* key-up (seconds).
            If None a flat 0.10 s is used.
    """
    for i, ch in enumerate(text):
        _send_unicode(ch, key_up=False)
        time.sleep(0.030)
        _send_unicode(ch, key_up=True)
        wait = delays[i] if delays else 0.10
        time.sleep(wait)
