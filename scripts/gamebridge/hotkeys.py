"""Global hotkey monitor using Win32 GetAsyncKeyState polling."""
from __future__ import annotations

import ctypes
import threading
import time

_VK_F10   = 0x79
_VK_CTRL  = 0x11
_VK_SHIFT = 0x10
_VK_Q     = 0x51

HOTKEY_STOP = "F10"
HOTKEY_KILL = "Ctrl+Shift+Q"


def start_hotkey_monitor(stop_cb, kill_cb) -> threading.Thread:
    """
    Start a daemon thread that polls for global hotkeys.
    stop_cb is called when F10 is pressed.
    kill_cb is called when Ctrl+Shift+Q is pressed.
    """
    def _loop():
        active: set[str] = set()
        while True:
            f10   = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_F10)  & 0x8000)
            q     = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_Q)    & 0x8000)
            ctrl  = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_CTRL) & 0x8000)
            shift = bool(ctypes.windll.user32.GetAsyncKeyState(_VK_SHIFT)& 0x8000)

            if f10 and "f10" not in active:
                active.add("f10")
                try:
                    stop_cb()
                except Exception:
                    pass
            elif not f10:
                active.discard("f10")

            if ctrl and shift and q and "csq" not in active:
                active.add("csq")
                try:
                    kill_cb()
                except Exception:
                    pass
            elif not (ctrl and shift and q):
                active.discard("csq")

            time.sleep(0.05)

    t = threading.Thread(target=_loop, daemon=True, name="hotkey-monitor")
    t.start()
    return t
