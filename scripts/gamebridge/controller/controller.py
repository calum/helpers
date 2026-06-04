"""
GameController — high-level game actions.

Combines the HumanEmulator (what would a human do?) with the hardware
input modules (actually do it).  Routines call this; they never touch
the input layer directly.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from typing import Callable, Optional

from ..human.emulator import HumanEmulator
from ..input import mouse as mouse_input
from ..input import keyboard as kb_input
from .. import settings as _settings

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Window detection
# ------------------------------------------------------------------ #

def _find_window_by_prefix(prefix: str) -> int:
    """Return HWND of the first top-level window whose title starts with prefix, or 0."""
    found = ctypes.c_size_t(0)
    buf = ctypes.create_unicode_buffer(256)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    def _cb(hwnd: int, _: int) -> bool:
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith(prefix):
            found.value = hwnd
            return False  # stop enumeration
        return True

    ctypes.windll.user32.EnumWindows(_cb, 0)
    return found.value


def _find_runelite_window() -> Optional[tuple[int, int, int, int]]:
    """
    Return (left, top, right, bottom) of the RuneLite client area, or None.

    We use GetClientRect + ClientToScreen so the coords exclude the window
    chrome — (0, 0) in canvas space maps to (left, top) in screen space.

    The window title is read from ~/.gamebridge/settings.json ("window_name").
    Update that value from the dashboard Settings tab if the title differs.
    """
    window_name = _settings.get("window_name")
    hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
    if not hwnd:
        # Try prefix-matching: iterate all top-level windows and check startswith
        hwnd = _find_window_by_prefix(window_name)

    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    return pt.x, pt.y, pt.x + w, pt.y + h


# ------------------------------------------------------------------ #
# Controller
# ------------------------------------------------------------------ #

class GameController:
    """
    Translates high-level game intentions into realistic hardware events.

    Usage
    -----
    ctrl = GameController()
    ctrl.refresh_window()          # find the RuneLite window
    ctrl.click_entity(some_npc)    # move + click like a human
    """

    def __init__(self, human: Optional[HumanEmulator] = None):
        self._human = human or HumanEmulator()
        self._window: Optional[tuple[int, int, int, int]] = None
        self.min_click_interval: float = 0.0
        self._last_entity_click: float = 0.0
        self._session_start: float = time.monotonic()

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def refresh_window(self) -> bool:
        """Re-detect the RuneLite window. Returns True if found."""
        self._window = _find_runelite_window()
        if self._window is None:
            log.warning("RuneLite window not found — is the client running?")
        else:
            l, t, r, b = self._window
            log.info("RuneLite window: (%d, %d) – (%d, %d)", l, t, r, b)
        return self._window is not None

    def _canvas_to_screen(self, cx: float, cy: float) -> tuple[float, float]:
        if self._window is None:
            self.refresh_window()
        if self._window is None:
            raise RuntimeError("RuneLite window not found. Launch the game first.")
        left, top, _, _ = self._window
        y_off = int(_settings.get("hull_y_offset") or 0)
        return left + cx, top + cy - y_off

    def _is_canvas_coord_valid(self, cx: float, cy: float) -> bool:
        """Return True only if the canvas coordinate lies within the game viewport."""
        if self._window is None:
            self.refresh_window()
        if self._window is None:
            return False
        left, top, right, bottom = self._window
        return 0 <= cx < (right - left) and 0 <= cy < (bottom - top)

    def _clamp_to_window(self, sx: float, sy: float) -> tuple[float, float]:
        """Clamp a screen coordinate to lie strictly inside the game window.

        Applied to the human-emulator's actual_x/y so that Gaussian click error
        never carries the cursor outside the game window.
        """
        if self._window is None:
            return sx, sy
        left, top, right, bottom = self._window
        return max(left, min(sx, right - 1)), max(top, min(sy, bottom - 1))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _after_click(self) -> None:
        """Call after every click: accumulate fatigue and take a break if due."""
        self._human.accumulate_fatigue(0.0002)
        session_s = time.monotonic() - self._session_start
        if self._human.should_take_break(session_s):
            duration = self._human.break_duration()
            log.info(
                "Taking a %.0f s micro-break (session %.0f s, fatigue %.2f)",
                duration, session_s, self._human.fatigue,
            )
            self._human.rest(duration)
            time.sleep(duration)

    # ------------------------------------------------------------------
    # Mouse actions
    # ------------------------------------------------------------------

    def move_to_entity(self, entity: dict) -> None:
        """Move the mouse to an on-screen entity with WindMouse movement."""
        if not entity.get("onScreen"):
            return
        cx, cy = entity["canvasX"], entity["canvasY"]
        if not self._is_canvas_coord_valid(cx, cy):
            log.warning("move_to_entity: %s canvas (%d, %d) outside viewport — skipping",
                        entity.get("name", "?"), cx, cy)
            return
        sx, sy = self._canvas_to_screen(cx, cy)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)

    def click_entity(self, entity: dict) -> None:
        """Left-click an on-screen entity."""
        if not entity.get("onScreen"):
            log.debug("click_entity: %s is off-screen", entity.get("name", "?"))
            return
        cx, cy = entity["canvasX"], entity["canvasY"]
        if not self._is_canvas_coord_valid(cx, cy):
            log.warning(
                "click_entity: %s canvas (%d, %d) outside viewport — skipping "
                "(plugin reported onScreen=true but hull projects outside canvas bounds)",
                entity.get("name", "?"), cx, cy,
            )
            return
        now = time.monotonic()
        if self.min_click_interval > 0 and now - self._last_entity_click < self.min_click_interval:
            log.debug(
                "click_entity: throttled — %.2fs since last click (min %.2fs)",
                now - self._last_entity_click, self.min_click_interval,
            )
            return
        sx, sy = self._canvas_to_screen(cx, cy)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)

        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)
        mouse_input.click_left()

        if intent.double_click:
            time.sleep(0.055)
            mouse_input.click_left()

        self._last_entity_click = time.monotonic()
        log.debug("Clicked %s at screen (%.0f, %.0f)", entity.get("name", "?"), sx, sy)
        self._after_click()

    def right_click_entity(self, entity: dict) -> None:
        """Right-click an on-screen entity."""
        if not entity.get("onScreen"):
            return
        cx, cy = entity["canvasX"], entity["canvasY"]
        if not self._is_canvas_coord_valid(cx, cy):
            log.warning("right_click_entity: %s canvas (%d, %d) outside viewport — skipping",
                        entity.get("name", "?"), cx, cy)
            return
        sx, sy = self._canvas_to_screen(cx, cy)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)

        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)
        mouse_input.click_right()

        log.debug("Right-clicked %s", entity.get("name", "?"))
        self._after_click()

    def click_widget(self, widget: dict) -> None:
        """Left-click the centre of a UI widget slot."""
        b = widget.get("bounds")
        if not b:
            log.debug("click_widget: widget has no bounds")
            return
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        self.click_at(cx, cy)
        log.debug("Clicked widget G%d:%d at canvas (%.0f, %.0f)",
                  widget.get("groupId", -1), widget.get("childId", -1), cx, cy)

    def click_at(self, canvas_x: float, canvas_y: float) -> None:
        """Left-click at an absolute canvas coordinate."""
        if not self._is_canvas_coord_valid(canvas_x, canvas_y):
            log.warning("click_at: canvas (%.0f, %.0f) outside viewport — skipping",
                        canvas_x, canvas_y)
            return
        sx, sy = self._canvas_to_screen(canvas_x, canvas_y)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)
        mouse_input.click_left()
        self._after_click()

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------

    def type_text(self, text: str) -> None:
        """Type text with human-like inter-key delays."""
        intent = self._human.plan_typing(text)
        kb_input.type_text(intent.text, intent.key_delays)

    def press_key(self, key: str) -> None:
        """Press a named key (e.g. 'enter', 'escape', 'f1') or character."""
        time.sleep(self._human.random_pause(0.02, 0.08))
        kb_input.press_key(key)

    # ------------------------------------------------------------------
    # Timing helpers
    # ------------------------------------------------------------------

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def wait_for(
        self,
        condition: Callable[[], bool],
        timeout: float = 30.0,
        poll_interval: float = 0.6,
    ) -> bool:
        """
        Block until condition() returns True or timeout elapses.
        Returns True if condition was met, False on timeout.
        poll_interval should not be shorter than one game tick (0.6 s).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(poll_interval)
        log.warning("wait_for timed out after %.1f s", timeout)
        return False

    def wait_ticks(self, game_state, ticks: int) -> None:
        """Wait for a number of game ticks to pass (based on GameState.tick)."""
        target = game_state.tick + ticks
        self.wait_for(lambda: game_state.tick >= target, timeout=ticks * 1.5)
