"""
Hardware keyboard emulation via pynput.

pynput uses Windows SendInput with the correct INPUT struct layout and
handles extended-key flags, Unicode characters, and platform differences
without any explicit Win32 plumbing in user code.

Install: pip install pynput
"""
from __future__ import annotations

import time
from typing import List, Optional

from pynput.keyboard import Controller as _Controller
from pynput.keyboard import Key as _PKey

_ctrl = _Controller()

# Maps our string key names to pynput Key objects.
# pynput sets KEYEVENTF_EXTENDEDKEY automatically for navigation keys.
_PYNPUT_MAP: dict[str, _PKey] = {
    "escape":    _PKey.esc,
    "enter":     _PKey.enter,
    "return":    _PKey.enter,
    "backspace": _PKey.backspace,
    "tab":       _PKey.tab,
    "space":     _PKey.space,
    "shift":     _PKey.shift,
    "ctrl":      _PKey.ctrl,
    "alt":       _PKey.alt,
    "capslock":  _PKey.caps_lock,
    "delete":    _PKey.delete,
    "home":      _PKey.home,
    "end":       _PKey.end,
    "pageup":    _PKey.page_up,
    "pagedown":  _PKey.page_down,
    "left":      _PKey.left,
    "right":     _PKey.right,
    "up":        _PKey.up,
    "down":      _PKey.down,
    **{f"f{i}": getattr(_PKey, f"f{i}") for i in range(1, 13)},
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
# Public API
# ------------------------------------------------------------------ #

def press_key(key: str, hold_ms: float = 50.0) -> None:
    """Press and release a key.

    key: a Key constant, a named string ("escape", "enter", "f1", …),
         or a single character.
    hold_ms: how long to hold the key down in milliseconds.
    """
    k = key.lower()
    pynput_key = _PYNPUT_MAP.get(k, key[0])
    _ctrl.press(pynput_key)
    time.sleep(hold_ms / 1000.0)
    _ctrl.release(pynput_key)


def type_text(text: str, delays: Optional[List[float]] = None) -> None:
    """Type a string character by character.

    delays: per-character pause after key-up in seconds.  Defaults to 0.10 s.
    """
    for i, ch in enumerate(text):
        _ctrl.press(ch)
        time.sleep(0.030)
        _ctrl.release(ch)
        time.sleep(delays[i] if delays else 0.10)
