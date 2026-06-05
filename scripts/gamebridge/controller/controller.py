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
from ..input.keyboard import Key
from .. import settings as _settings
from ..fov import decide_camera_action

log = logging.getLogger(__name__)

# Approximate OSRS camera rotation rate when holding an arrow key.
# Measured in yaw-units per millisecond (full circle = 2048 units).
# Tune this constant empirically if rotations consistently over- or under-shoot.
# Measured 10 full rotations in 36.6 seconds → 2048 units / (36600 ms / 10) ≈ 0.56 units/ms.
CAMERA_YAW_SPEED: float = 0.56

# Camera pitch control.  OSRS pitch: higher value = more top-down (overhead view).
# UP arrow increases pitch (more overhead); DOWN arrow decreases pitch (more horizontal).
# Tune CAMERA_PITCH_SPEED empirically; the pitch range in practice is roughly 128–512.
CAMERA_PITCH_SPEED: float = 0.256   # pitch-units per millisecond
_PITCH_NEAR_DIST: int = 6           # tiles; at or closer → use overhead pitch
_PITCH_FAR_DIST: int = 11           # tiles; at or farther → use horizon pitch
_PITCH_OVERHEAD: int = 512          # target pitch for nearby objects (top-down view)
_PITCH_HORIZON: int = 240           # target pitch for distant objects (see further)
_PITCH_TOLERANCE: int = 40          # acceptable deviation before pressing a key


def _ideal_pitch(distance: int) -> int:
    """Return the ideal camera pitch for a given Manhattan tile distance."""
    clamped = max(_PITCH_NEAR_DIST, min(distance, _PITCH_FAR_DIST))
    t = (clamped - _PITCH_NEAR_DIST) / (_PITCH_FAR_DIST - _PITCH_NEAR_DIST)
    return int(_PITCH_OVERHEAD + t * (_PITCH_HORIZON - _PITCH_OVERHEAD))


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
        """Press a named key (Key constant, named string, or single character)."""
        time.sleep(self._human.random_pause(0.02, 0.08))
        kb_input.press_key(key)
        log.debug("Pressed key '%s'", key)

    def rotate_camera_to(self, entity: dict, game_state) -> bool:
        """
        Rotate the camera toward an off-screen entity using arrow keys.

        Computes the shortest-arc yaw delta, asks the HumanEmulator for a
        human-like key-hold intent, then holds LEFT or RIGHT until the estimated
        angle is covered.  The caller should return None from its routine state
        after this call so the next tick delivers fresh game state to verify.

        Returns True if the entity was already on-screen (no rotation performed),
        False if a rotation was executed.
        """
        if entity.get("onScreen"):
            return True

        target_yaw = game_state.camera_yaw_to(entity)
        current_yaw = game_state.camera.get("yaw", 0)
        delta = (target_yaw - current_yaw + 2048) % 2048

        if delta > 1024:
            key = Key.LEFT
            actual_delta = 2048 - delta
        else:
            key = Key.RIGHT
            actual_delta = delta

        intended_hold_ms = actual_delta / CAMERA_YAW_SPEED
        intent = self._human.plan_key_hold(intended_hold_ms)

        time.sleep(intent.pre_hold_pause)
        kb_input.press_key(key, hold_ms=intent.hold_ms)
        time.sleep(intent.post_hold_pause)

        log.debug(
            "Rotated camera %s by ~%d yaw units (intended %.0f ms, actual %.0f ms)",
            "LEFT" if key == Key.LEFT else "RIGHT",
            actual_delta,
            intended_hold_ms,
            intent.hold_ms,
        )
        return False

    def adjust_camera_pitch_for(self, entity: dict, game_state) -> bool:
        """
        Press UP or DOWN to bring the camera pitch close to the ideal for the
        entity's tile distance.

        Returns True if pitch was already within tolerance (no key pressed),
        False if an adjustment was made.

        Call this after rotate_camera_to when an entity is off-screen — combining
        yaw rotation and pitch adjustment gives the best chance of bringing a
        distant entity into view on the next tick.
        """
        current_pitch = game_state.camera.get("pitch") if game_state.camera else None
        if current_pitch is None:
            return True

        distance = game_state.distance_to(entity)
        target_pitch = _ideal_pitch(distance)
        pitch_delta = target_pitch - current_pitch

        if abs(pitch_delta) <= _PITCH_TOLERANCE:
            return True

        if pitch_delta > 0:
            key = Key.UP      # increase pitch → more overhead
            hold_ms = pitch_delta / CAMERA_PITCH_SPEED
        else:
            key = Key.DOWN    # decrease pitch → more horizontal (see further)
            hold_ms = (-pitch_delta) / CAMERA_PITCH_SPEED

        intent = self._human.plan_key_hold(hold_ms)
        time.sleep(intent.pre_hold_pause)
        kb_input.press_key(key, hold_ms=intent.hold_ms)
        time.sleep(intent.post_hold_pause)

        log.debug(
            "Adjusted camera pitch %s by ~%d units (current=%d, target=%d, distance=%d tiles)",
            "UP" if key == Key.UP else "DOWN",
            abs(pitch_delta),
            current_pitch,
            target_pitch,
            distance,
        )
        return False

    def bring_entity_on_screen(self, entity: dict, game_state) -> bool:
        """
        Bring an entity into the camera's visible area using FOV-aware logic.

        Uses decide_camera_action() to check whether the entity is already
        visible (on-screen flag OR inside the FOV trapezoid), needs a yaw
        rotation, or is so far off-bearing that walking would normally be
        required. In all off-screen cases, rotates and adjusts pitch — the
        combined correction converges in the fewest ticks.

        Returns True  if the entity is already visible (caller may click it).
        Returns False if a camera adjustment was made (caller should return
                      None and wait for the next tick).
        """
        action = decide_camera_action(entity, game_state)
        if action == "on_screen":
            return True
        self.rotate_camera_to(entity, game_state)
        self.adjust_camera_pitch_for(entity, game_state)
        return False

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
