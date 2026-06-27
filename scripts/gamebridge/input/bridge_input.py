"""
BridgeInputBackend — routes mouse/keyboard primitives through the live
BridgeConnection as synthetic AWT events dispatched directly onto the game's
Canvas (see GameBridgePlugin.processIncoming / InputEventDispatcher.java),
instead of OS-level SendInput.

Implements the same primitive surface as input.mouse / input.keyboard
(get_position/move_to/click_left/click_right and press_key/key_down/key_up)
so GameController.use_bridge_input() can swap it in via
mouse.set_backend()/keyboard.set_backend() — see the `_backend` hook in
those two modules. WindMouse and HumanEmulator are unaware of which backend
is active; only the transport (OS SendInput vs. Game Bridge canvas
injection) changes.

Positions here are canvas-local coordinates (the same space `canvasX`/
`canvasY` and `hull` use in tick messages) — NOT OS screen pixels, since the
Java side dispatches mouseEvent x/y straight onto the canvas with no window
offset applied. There is no real OS cursor when this backend is active, so
get_position() just returns the last position this backend itself moved to.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from ..client import BridgeConnection

# AWT button identifiers (java.awt.event.MouseEvent.BUTTON1/2/3) — must
# match InputEventDispatcher.buildMouseEvents' button handling.
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2
BUTTON_RIGHT = 3

# Named keys -> AWT VK_* keyCodes (java.awt.event.KeyEvent), matching what
# InputEventDispatcher.buildKeyEvent expects for press/release actions.
# Single characters resolve via ord(key.upper()) below — VK_A..VK_Z and
# VK_0..VK_9 are defined to equal the ASCII codes of the uppercase
# letter/digit, so no separate table entry is needed for those.
_NAMED_VK_CODES: dict[str, int] = {
    "escape":    0x1B,
    "enter":     0x0A,
    "backspace": 0x08,
    "tab":       0x09,
    "space":     0x20,
    "shift":     0x10,
    "ctrl":      0x11,
    "alt":       0x12,
    "capslock":  0x14,
    "delete":    0x7F,
    "home":      0x24,
    "end":       0x23,
    "pageup":    0x21,
    "pagedown":  0x22,
    "left":      0x25,
    "right":     0x27,
    "up":        0x26,
    "down":      0x28,
    "f1":  0x70, "f2":  0x71, "f3":  0x72, "f4":  0x73,
    "f5":  0x74, "f6":  0x75, "f7":  0x76, "f8":  0x77,
    "f9":  0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _vk_for(key: str) -> Optional[int]:
    """Resolve a Key constant, named string, or single character to an AWT
    VK_* keyCode. Returns None if unresolvable (caller no-ops)."""
    if not key:
        return None
    named = _NAMED_VK_CODES.get(key.lower())
    if named is not None:
        return named
    if len(key) == 1:
        return ord(key.upper())
    return None


_DOUBLE_CLICK_MS = 500.0   # matches Windows' default GetDoubleClickTime
_DOUBLE_CLICK_RADIUS = 4.0  # px


class BridgeInputBackend:
    """Drop-in replacement for the input.mouse / input.keyboard module
    functions, transporting events over `connection` instead of SendInput."""

    def __init__(self, connection: BridgeConnection):
        self._connection = connection
        self._pos: tuple[float, float] = (0.0, 0.0)
        # Button currently held down via button_down() — see button_down/
        # button_up/move_to. None when no button is held.
        self._held_button: Optional[int] = None
        # (timestamp, button, x, y, clickCount) of the last completed click —
        # see _click/_click_count_for, which use this to decide clickCount
        # for the next one (matching Windows' GetDoubleClickTime semantics).
        self._last_click: Optional[tuple[float, int, float, float, int]] = None

    # ------------------------------------------------------------------
    # Mouse — mirrors input.mouse.get_position/move_to/click_left/click_right
    # ------------------------------------------------------------------

    def get_position(self) -> tuple[float, float]:
        return self._pos

    def move_to(self, x: float, y: float) -> None:
        self._pos = (x, y)
        action = "drag" if self._held_button is not None else "move"
        msg = {"type": "mouseEvent", "action": action, "x": round(x), "y": round(y)}
        if self._held_button is not None:
            msg["button"] = self._held_button
        self._connection.send(msg)

    def click_left(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        self._click(BUTTON_LEFT, x, y)

    def click_right(self, x: Optional[float] = None, y: Optional[float] = None) -> None:
        self._click(BUTTON_RIGHT, x, y)

    def button_down(self, button: int = BUTTON_LEFT, click_count: int = 1) -> None:
        """Press and hold a mouse button — pair with `button_up` for a drag.

        Subsequent move_to() calls send `action: "drag"` (with `button`)
        instead of `action: "move"` until the button is released.
        """
        px, py = round(self._pos[0]), round(self._pos[1])
        self._connection.send({
            "type": "mouseEvent", "action": "press",
            "x": px, "y": py, "button": button, "clickCount": click_count,
        })
        self._held_button = button

    def button_up(self, button: int = BUTTON_LEFT, click_count: int = 1) -> None:
        """Release a mouse button previously held down with `button_down`."""
        px, py = round(self._pos[0]), round(self._pos[1])
        self._connection.send({
            "type": "mouseEvent", "action": "release",
            "x": px, "y": py, "button": button, "clickCount": click_count,
        })
        if self._held_button == button:
            self._held_button = None

    def scroll(self, amount: int) -> None:
        """Scroll the mouse wheel `amount` notches at the current position —
        AWT wheelRotation convention (negative = up/away, positive =
        down/toward), matching InputEventDispatcher's `action: "wheel"`.
        """
        px, py = round(self._pos[0]), round(self._pos[1])
        self._connection.send({
            "type": "mouseEvent", "action": "wheel",
            "x": px, "y": py, "rotation": amount,
        })

    def _click(self, button: int, x: Optional[float], y: Optional[float]) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
        px, py = round(self._pos[0]), round(self._pos[1])
        click_count = self._click_count_for(button, px, py)

        self.button_down(button, click_count=click_count)
        time.sleep(random.uniform(0.040, 0.090))
        self.button_up(button, click_count=click_count)

        self._last_click = (time.monotonic(), button, px, py, click_count)

    def _click_count_for(self, button: int, x: float, y: float) -> int:
        if self._last_click is None:
            return 1
        last_time, last_button, last_x, last_y, last_count = self._last_click
        if button != last_button:
            return 1
        if (time.monotonic() - last_time) * 1000.0 > _DOUBLE_CLICK_MS:
            return 1
        if abs(x - last_x) > _DOUBLE_CLICK_RADIUS or abs(y - last_y) > _DOUBLE_CLICK_RADIUS:
            return 1
        return last_count + 1

    # ------------------------------------------------------------------
    # Keyboard — mirrors input.keyboard.press_key/key_down/key_up
    # ------------------------------------------------------------------

    def press_key(self, key: str, hold_ms: float = 50.0) -> None:
        vk = _vk_for(key)
        if vk is None:
            return
        # Mirrors input.keyboard.press_key's shift-wrap for an uppercase
        # single letter — punctuation needing shift (e.g. "!") isn't
        # supported here; use type_text via keyEvent "type" for arbitrary text.
        needs_shift = len(key) == 1 and key.isalpha() and key.isupper()
        if needs_shift:
            self.key_down("shift")
        self._connection.send({"type": "keyEvent", "action": "press", "keyCode": vk})
        time.sleep(hold_ms / 1000.0)
        self._connection.send({"type": "keyEvent", "action": "release", "keyCode": vk})
        if needs_shift:
            self.key_up("shift")

    def key_down(self, key: str) -> None:
        vk = _vk_for(key)
        if vk is None:
            return
        self._connection.send({"type": "keyEvent", "action": "press", "keyCode": vk})

    def key_up(self, key: str) -> None:
        vk = _vk_for(key)
        if vk is None:
            return
        self._connection.send({"type": "keyEvent", "action": "release", "keyCode": vk})
