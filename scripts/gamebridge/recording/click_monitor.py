"""Global mouse-click monitor using Win32 GetAsyncKeyState polling.

Mirrors `hotkeys.start_hotkey_monitor` — same no-extra-dependency polling
approach, just watching the mouse buttons instead of keyboard keys. Reports
the OS screen coordinate of each button press (button-down transition only,
so a held-down button is reported once, not every poll).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from typing import Callable

_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02

# Polled faster than the hotkey monitor (50ms) — clicks are short, and we want
# the reported position to closely match where the cursor actually was at the
# moment of the press, not several pixels into a drag.
_POLL_INTERVAL_S = 0.01

ClickCallback = Callable[[str, int, int, float], None]
"""on_click(button, screen_x, screen_y, timestamp) — button is "left"/"right",
timestamp is `time.monotonic()` at the moment the press was detected."""


def start_click_monitor(on_click: ClickCallback, stop_event: threading.Event) -> threading.Thread:
    """Start a daemon thread that polls for left/right mouse button presses.

    on_click is invoked on the polling thread (not the GUI thread) once per
    press — callers that touch Qt widgets must marshal back via a signal, the
    same way BridgeTicker does for tick messages.

    stop_event lets the caller end the monitor when recording stops; the
    thread exits its loop once the event is set (checked once per poll).
    """
    def _loop():
        held = {"left": False, "right": False}
        while not stop_event.is_set():
            for button, vk in (("left", _VK_LBUTTON), ("right", _VK_RBUTTON)):
                down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                if down and not held[button]:
                    held[button] = True
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    try:
                        on_click(button, pt.x, pt.y, time.monotonic())
                    except Exception:
                        pass
                elif not down:
                    held[button] = False
            time.sleep(_POLL_INTERVAL_S)

    t = threading.Thread(target=_loop, daemon=True, name="click-monitor")
    t.start()
    return t
