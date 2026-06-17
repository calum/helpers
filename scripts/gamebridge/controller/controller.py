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

from ..client import BridgeConnection
from ..human.emulator import ClickIntent, HumanEmulator
from ..input import mouse as mouse_input
from ..input import keyboard as kb_input
from ..input.keyboard import Key
from .. import settings as _settings
from ..fov import decide_camera_action
from ..state.entity_tracker import EntityTracker
from ..state.moving_target import MovingTarget

log = logging.getLogger(__name__)

# Approximate OSRS camera rotation rate when holding an arrow key.
# Measured in yaw-units per millisecond (full circle = 2048 units).
# Tune this constant empirically if rotations consistently over- or under-shoot.
# Measured 10 full rotations in 36.6 seconds → 2048 units / (36600 ms / 10) ≈ 0.56 units/ms.
CAMERA_YAW_SPEED: float = 0.56

# Minimap-walk settling — see click_minimap_entity / _minimap_walk_in_progress.
# These are tracked across ticks (not blocking sleeps): the engine is a
# single-threaded message loop (process_tick → routine.tick → controller),
# so blocking here would stall game-state updates and freeze the bot facing
# stale data — exactly the "click the same dead spot forever" bug this
# mechanism exists to prevent.
MINIMAP_WALK_START_TICKS: int = 2    # ticks to allow the walk to begin before checking idle
MINIMAP_WALK_SETTLE_TICKS: int = 1   # consecutive idle ticks required before re-clicking
MINIMAP_WALK_MAX_TICKS: int = 100    # ~60s safety cap — give up waiting & allow a re-click

# On-screen settling — see bring_entity_on_screen. The tick a camera
# rotation/walk first reports the entity as "on_screen", its canvasX/Y can
# still reflect a transient mid-adjustment frame; clicking immediately lands
# on a stale position (e.g. "Mining ended after 3.0s (xp=False, timeout=True)"
# from a missed click — see PLAN.md, "Session: 2026-06-07 (5)"). Waiting this
# many extra ticks lets the polled coordinates settle before we click.
ON_SCREEN_SETTLE_TICKS: int = 1


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
        # Cross-tick velocity for moving targets — see track_entities() and
        # _plan_moving_click(). Owned and driven entirely by this controller
        # (fed once per drive() cycle), never touched from the ingest thread.
        self._tracker = EntityTracker()
        self._window: Optional[tuple[int, int, int, int]] = None
        self.min_click_interval: float = 0.0
        self._last_entity_click: float = 0.0
        self._session_start: float = time.monotonic()
        # Tracks an in-progress minimap walk across ticks — see
        # click_minimap_entity / _minimap_walk_in_progress. None when no walk
        # is being tracked; otherwise {"clicked_tick", "idle_since_tick"}.
        self._minimap_walk: Optional[dict] = None
        # Tick the entity was first reported "on_screen" by bring_entity_on_screen
        # — see ON_SCREEN_SETTLE_TICKS. Reset to None whenever a rotation or
        # minimap walk is issued (the entity is no longer considered settled).
        self._on_screen_since_tick: Optional[int] = None
        # Live BridgeConnection for hull-update subscriptions — see
        # set_connection/subscribe_to/hull_update. None until main.py's
        # connect() loop hands one over.
        self._connection: Optional[BridgeConnection] = None
        # Modifier keys currently held down via hold_key() — see hold_key/
        # release_key/release_all_keys.
        self._held_keys: set[str] = set()

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

    def screen_to_canvas(self, sx: float, sy: float) -> Optional[tuple[float, float]]:
        """Inverse of `_canvas_to_screen` — maps an OS screen coordinate back to
        canvas space (the coordinate system `canvasX/Y` and `hull` use).

        Used by the session recorder to translate a raw mouse-click position
        into the same space as entity hulls / widget bounds, so the click can
        be hit-tested against live game-state geometry. Returns None if the
        RuneLite window can't be found.
        """
        if self._window is None:
            self.refresh_window()
        if self._window is None:
            return None
        left, top, _, _ = self._window
        y_off = int(_settings.get("hull_y_offset") or 0)
        return sx - left, sy - top + y_off

    def is_screen_point_in_window(self, sx: float, sy: float) -> bool:
        """Return True if the OS screen point lies within the RuneLite client area.

        Used by the session recorder to ignore clicks made on other windows
        (the dashboard, browser, etc.) while a recording is in progress —
        only in-game clicks are meaningful for reverse-engineering a routine.
        """
        if self._window is None:
            self.refresh_window()
        if self._window is None:
            return False
        left, top, right, bottom = self._window
        return left <= sx < right and top <= sy < bottom

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
    # Entity tracking — feeds MovingTarget predictions in click paths below
    # ------------------------------------------------------------------

    def track_entities(self, game_state) -> None:
        """Feed the latest snapshot to the internal EntityTracker.

        click_entity / move_to_entity / right_click_entity use the resulting
        per-tick canvas velocity (via _plan_moving_click → MovingTarget) to
        predict where a moving target will be by the time the cursor arrives,
        rather than aiming at its now-stale last-seen position.

        Call this exactly once per tick, from DecisionEngine.drive() — the
        same single thread that goes on to run routine.tick() and (via it)
        the click methods. Never call it from ingest(): that runs on a
        different thread, and EntityTracker is a plain mutable object with
        none of GameState.clone()'s cross-thread snapshot guarantees: a
        concurrent update()/lookup pair would race. EntityTracker.update()
        normalises velocity by the actual tick delta, so it tolerates
        drive() skipping snapshots under load — calling it only when drive()
        actually has a routine to run is correct, not lossy.
        """
        self._tracker.update(game_state)

    def _plan_moving_click(
        self, entity: dict, cur_x: float, cur_y: float,
    ) -> tuple[ClickIntent, Callable[[float], tuple[float, float]]]:
        """Plan a click on a possibly-moving entity.

        Builds a MovingTarget from the entity's current canvas position and
        the tracker's canvas velocity (None if untracked/stationary — the
        target then predicts as static), and returns:

          - `intent`: timing/manner (pauses, move_speed, double_click) planned
            against the target's *currently* predicted screen position. These
            are properties of how the human acts, not tied to a specific point
            in space, so one ClickIntent for the whole action is correct.
          - `predict`: a screen-space callable for wind_mouse_to_prediction.
            It re-evaluates MovingTarget.predict on every call, converts
            canvas → screen, and adds intent's Gaussian click-error as a
            *fixed offset* captured once up front — so the cursor consistently
            misses by the same human "miss vector" relative to wherever the
            target ends up, rather than drifting toward a stale snapshot
            position. Clamping to the window is applied per-call too, which
            doubles as a guard against wild over-extrapolation.

        Caller must already have checked entity["onScreen"] and
        _is_canvas_coord_valid — this assumes both hold.
        """
        now = time.monotonic()
        target = MovingTarget.from_entity(entity, self._tracker.velocity(entity, "canvas"), now)
        sx, sy = self._canvas_to_screen(*target.predict(now))
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        err_x, err_y = intent.actual_x - sx, intent.actual_y - sy

        def predict(at_time: float) -> tuple[float, float]:
            px, py = self._canvas_to_screen(*target.predict(at_time))
            return self._clamp_to_window(px + err_x, py + err_y)

        return intent, predict

    def _live_hull_canvas_pos(self, sub_id: str, entity: dict) -> Optional[tuple[float, float]]:
        """Return the freshest known canvas position for `entity` from the
        `sub_id` live hullUpdate subscription (~20ms cadence), or None if no
        fresher position is available right now.

        Falls back to None (caller then uses the MovingTarget extrapolation)
        when there's no connection, no hullUpdate has arrived yet, the update
        is for a different entity (a retarget is in flight), or the live
        entity is currently off-screen — all normal transient states that
        shouldn't make a click aim at nothing.
        """
        update = self.hull_update(sub_id)
        if not update or not update.get("found") or not update.get("onScreen"):
            return None
        if (update.get("name") or "").lower() != (entity.get("name") or "").lower():
            return None
        cx, cy = update.get("canvasX"), update.get("canvasY")
        if cx is None or cy is None:
            return None
        return cx, cy

    def _plan_live_click(
        self, entity: dict, sub_id: str, cur_x: float, cur_y: float,
    ) -> tuple[ClickIntent, Callable[[float], tuple[float, float]]]:
        """Like _plan_moving_click, but predict() also polls the `sub_id`
        live hullUpdate subscription (~20ms cadence) on every call, tracking
        that position directly whenever a fresh one is available and falling
        back to the MovingTarget tick-velocity extrapolation otherwise.

        This is what makes click_live/right_click_live actually "live": the
        per-tick MovingTarget extrapolation alone can drift over the course
        of a multi-step wind_mouse approach, but re-checking the live hullbox
        on every step lets the cursor continuously re-aim at the entity's
        true current position. See InteractionRoutine.click_live /
        right_click_live, which subscribe `entity` under `sub_id` before
        calling click_entity/right_click_entity with this `sub_id`.
        """
        now = time.monotonic()
        target = MovingTarget.from_entity(entity, self._tracker.velocity(entity, "canvas"), now)
        sx, sy = self._canvas_to_screen(*target.predict(now))
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        err_x, err_y = intent.actual_x - sx, intent.actual_y - sy

        def predict(at_time: float) -> tuple[float, float]:
            live = self._live_hull_canvas_pos(sub_id, entity)
            cx, cy = live if live is not None else target.predict(at_time)
            px, py = self._canvas_to_screen(cx, cy)
            return self._clamp_to_window(px + err_x, py + err_y)

        return intent, predict

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _onscreen_canvas_pos(self, entity: dict, action: str) -> Optional[tuple[float, float]]:
        """Return the entity's canvas position if it's safe to aim at, else None.

        Shared guard for move_to_entity/click_entity/right_click_entity: the
        entity must be flagged on-screen AND its canvas position must fall
        inside the viewport — the plugin can report onScreen=true while the
        projected hull still lands outside canvas bounds (e.g. a sliver of
        an object peeking past the edge), so both checks are needed before
        aiming the mouse at it. Logs why at debug/warning level either way.
        """
        if not entity.get("onScreen"):
            log.debug("%s: %s is off-screen", action, entity.get("name", "?"))
            return None
        cx, cy = entity["canvasX"], entity["canvasY"]
        if not self._is_canvas_coord_valid(cx, cy):
            log.warning("%s: %s canvas (%d, %d) outside viewport — skipping",
                        action, entity.get("name", "?"), cx, cy)
            return None
        return cx, cy

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
        """Move the mouse to an on-screen entity, tracking it if it moves."""
        if self._onscreen_canvas_pos(entity, "move_to_entity") is None:
            return
        cur_x, cur_y = mouse_input.get_position()
        intent, predict = self._plan_moving_click(entity, cur_x, cur_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse_to_prediction(cur_x, cur_y, predict, move_speed=intent.move_speed)

    def click_entity(self, entity: dict, sub_id: Optional[str] = None, verify_name: Optional[str] = None) -> bool:
        """Left-click an on-screen entity, tracking it if it moves.

        If `sub_id` is given, the click also tracks that entity's live
        hullUpdate subscription while the cursor is moving towards it — see
        _plan_live_click and InteractionRoutine.click_live.

        If `verify_name` is given, the tooltip is checked for that name right
        before the click fires — after the mouse has arrived at the entity.
        If not found, the click is skipped and False is returned; the mouse is
        already near the entity, so the caller can retry on the next tick once
        the tooltip catches up.

        Returns True if the click fired, False otherwise.
        """
        pos = self._onscreen_canvas_pos(entity, "click_entity")
        if pos is None:
            return False
        cx, cy = pos
        now = time.monotonic()
        if self.min_click_interval > 0 and now - self._last_entity_click < self.min_click_interval:
            log.debug(
                "click_entity: throttled — %.2fs since last click (min %.2fs)",
                now - self._last_entity_click, self.min_click_interval,
            )
            return False
        cur_x, cur_y = mouse_input.get_position()
        if sub_id is not None:
            intent, predict = self._plan_live_click(entity, sub_id, cur_x, cur_y)
        else:
            intent, predict = self._plan_moving_click(entity, cur_x, cur_y)

        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse_to_prediction(cur_x, cur_y, predict, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)

        if verify_name is not None:
            tooltip = self.tooltip()
            age = self.tooltip_age()
            age_str = f"{age * 1000:.0f}ms" if isinstance(age, (int, float)) else age
            log.debug("Tooltip before click: %r (age=%s)", tooltip, age_str)
            if verify_name.lower() not in tooltip.lower():
                log.debug("%r not found in tooltip %r — skipping click", verify_name, tooltip)
                return False

        mouse_input.click_left()

        if intent.double_click:
            time.sleep(0.055)
            mouse_input.click_left()

        self._last_entity_click = time.monotonic()
        log.debug("Clicked %s (canvas %.0f, %.0f)", entity.get("name", "?"), cx, cy)
        self._after_click()
        return True

    def right_click_entity(self, entity: dict, sub_id: Optional[str] = None, verify_name: Optional[str] = None) -> bool:
        """Right-click an on-screen entity, tracking it if it moves.

        If `sub_id` is given, the click also tracks that entity's live
        hullUpdate subscription while the cursor is moving towards it — see
        _plan_live_click and InteractionRoutine.right_click_live.

        If `verify_name` is given, the tooltip is checked for that name right
        before the click fires — after the mouse has arrived at the entity.
        If not found, the click is skipped and False is returned.

        Returns True if the click fired, False otherwise.
        """
        if self._onscreen_canvas_pos(entity, "right_click_entity") is None:
            return False
        cur_x, cur_y = mouse_input.get_position()
        if sub_id is not None:
            intent, predict = self._plan_live_click(entity, sub_id, cur_x, cur_y)
        else:
            intent, predict = self._plan_moving_click(entity, cur_x, cur_y)

        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse_to_prediction(cur_x, cur_y, predict, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)

        if verify_name is not None:
            tooltip = self.tooltip()
            age = self.tooltip_age()
            age_str = f"{age * 1000:.0f}ms" if isinstance(age, (int, float)) else age
            log.debug("Tooltip before right-click: %r (age=%s)", tooltip, age_str)
            if verify_name.lower() not in tooltip.lower():
                log.debug("%r not found in tooltip %r — skipping right-click", verify_name, tooltip)
                return False

        mouse_input.click_right()

        log.debug("Right-clicked %s", entity.get("name", "?"))
        self._after_click()
        return True

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

    def right_click_widget(self, widget: dict) -> None:
        """Right-click the centre of a UI widget slot — e.g. to open an
        inventory item's context menu and read back a "Drop"/"Use" entry
        with `GameState.menu_entry_matching` before clicking it."""
        b = widget.get("bounds")
        if not b:
            log.debug("right_click_widget: widget has no bounds")
            return
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        self.right_click_at(cx, cy)
        log.debug("Right-clicked widget G%d:%d at canvas (%.0f, %.0f)",
                  widget.get("groupId", -1), widget.get("childId", -1), cx, cy)

    def move_to_widget(self, widget: dict) -> None:
        """Move the mouse to the centre of a UI widget slot without clicking.

        Used by `InteractionRoutine.drop_items_shift_click` to position the
        cursor over an inventory slot so `ctrl.tooltip()` can be checked for
        "Drop" before the click is committed.
        """
        b = widget.get("bounds")
        if not b:
            log.debug("move_to_widget: widget has no bounds")
            return
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        if not self._is_canvas_coord_valid(cx, cy):
            log.warning("move_to_widget: canvas (%.0f, %.0f) outside viewport — skipping", cx, cy)
            return
        sx, sy = self._canvas_to_screen(cx, cy)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        log.debug("Moved to widget G%d:%d at canvas (%.0f, %.0f)",
                  widget.get("groupId", -1), widget.get("childId", -1), cx, cy)

    def click_menu_entry(self, game_state, option_substr: str, target_substr: Optional[str] = None) -> bool:
        """Click a right-click context-menu entry matching the given option/target text.

        Non-blocking — looks for a match in the *currently open* menu
        (``game_state.menu``, via :meth:`GameState.menu_entry_matching`) and
        clicks the centre of its pre-computed screen bounds if found.
        Returns True if a match was found and clicked, False if the menu is
        closed or has no matching entry (the caller should wait for a future
        tick — the menu may not have opened yet — or give up).

        This is the "verify before you click" pattern: right-click an
        entity, confirm the expected option/target text is actually present
        in the menu, then click that exact row — far more reliable than
        blind left-clicking, especially for moving targets (NPCs walking)
        or entities partly hidden behind scenery (e.g. a Goblin standing
        behind a Tree).

        The engine is a single-threaded message loop — like
        ``click_minimap_entity``, this can't block waiting for the menu to
        open without freezing the bot on stale data. Spread the gesture
        across ticks instead, the same "act, then verify next tick" shape
        ``bring_entity_on_screen``/``click_minimap_entity`` use::

            def attack(self, game, ctrl):
                if not self._right_clicked:
                    target = game.nearest_npc_on_screen("Goblin")
                    if target is None:
                        return None
                    ctrl.right_click_entity(target)
                    self._right_clicked = True
                    return None

                if ctrl.click_menu_entry(game, "Attack", "Goblin"):
                    self._right_clicked = False
                    return "fighting"

                if not game.menu_open():
                    self._right_clicked = False  # closed without a match — retry
                return None
        """
        entry = game_state.menu_entry_matching(option_substr, target_substr)
        if entry is None:
            return False

        b = entry["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        self.click_at(cx, cy)
        log.debug("Clicked menu entry '%s %s' at canvas (%.0f, %.0f)",
                  entry.get("option", "?"), entry.get("target", ""), cx, cy)
        return True

    def dismiss_menu(self, game_state) -> None:
        """Move the mouse off an open context menu so the client closes it.

        Right-click menus don't time out on their own — the client only
        closes them once the cursor moves clear of their bounds (then
        auto-closes after a beat) or something else is clicked. When
        ``click_menu_entry`` can't find the row it's looking for (e.g. the
        right-click landed on the wrong entity, or the entity walked off
        mid-gesture), nothing else will ever dismiss that stale menu — a
        caller that just kept waiting for a match would hang forever.

        Picks whichever side of the menu — left or right — has more
        clearance and aims for its midpoint, so the cursor lands well
        outside the menu's bounding box regardless of where it opened on
        screen. Safe to call every tick the menu remains stuck open: once
        the cursor is already at the target point, ``wind_mouse`` is a
        no-op move.
        """
        if self._window is None:
            self.refresh_window()
        if self._window is None:
            return

        left, top, right, bottom = self._window
        canvas_w, canvas_h = right - left, bottom - top

        mx = game_state.menu.get("x", 0)
        my = game_state.menu.get("y", 0)
        mw = game_state.menu.get("width", 0)
        mh = game_state.menu.get("height", 0)

        space_left, space_right = mx, canvas_w - (mx + mw)
        target_x = mx / 2 if space_left >= space_right else mx + mw + space_right / 2
        target_y = min(max(my + mh / 2, 0), canvas_h - 1)

        sx, sy = self._canvas_to_screen(target_x, target_y)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        log.debug("Dismissing menu — moved mouse to canvas (%.0f, %.0f)", target_x, target_y)

    def click_minimap_entity(self, entity: dict, game_state) -> bool:
        """Click the minimap at the entity's pre-computed minimap position.

        The Java plugin calculates ``minimapX``/``minimapY`` for every NPC and
        object each tick via ``Perspective.localToMinimap()``.  Clicking the
        minimap causes the player to walk towards that tile — useful when the
        target is too far to click directly in the viewport.

        A minimap click kicks off a multi-tick walk, so re-clicking every
        tick would just queue up redundant walk requests ("spam clicking",
        which a human never does). Instead this tracks the walk's progress
        across calls (see ``_minimap_walk_in_progress``) and only issues a
        new click once the previous one has fully settled: the player has
        started moving, then stopped both animating and moving, then one
        further tick has passed for the polled game state to catch up.

        This check is intentionally non-blocking — it only inspects the
        already-updated ``game_state`` passed in on this tick. The engine
        drives ``routine.tick()`` synchronously inside the same loop that
        polls game state (see ``DecisionEngine.process_tick``), so sleeping
        or polling here would freeze the engine on stale data: it would keep
        re-clicking the same dead minimap position forever (see PLAN.md,
        "Session: 2026-06-07 (4)" for the live bug this caused).

        Returns ``True`` if a click was issued or a walk is still being
        tracked (the caller should treat the entity as "being walked
        towards" and wait for a future tick), ``False`` if the entity has no
        minimap coordinates (i.e. it is beyond the ~20-tile minimap radius).

        ``bring_entity_on_screen`` already calls this automatically when
        ``decide_camera_action`` decides the target is too far/off-bearing for
        rotation alone ("walk"). Call it directly only when you need to walk
        toward an entity outside that flow, e.g.::

            def find_ore(self, game, ctrl):
                ore = game.nearest_object("Iron rocks")
                if ore is None:
                    return None
                if not ctrl.bring_entity_on_screen(ore, game):
                    return None  # camera rotated or minimap-walk issued — wait a tick
                if game.is_occluded(ore["canvasX"], ore["canvasY"]):
                    return None
                ctrl.click_entity(ore)
                return "mining"
        """
        if self._minimap_walk_in_progress(game_state):
            return True

        mx = entity.get("minimapX")
        my = entity.get("minimapY")
        if mx is None or my is None:
            log.debug(
                "click_minimap_entity: %s has no minimap coordinates (beyond range)",
                entity.get("name", "?"),
            )
            return False
        self.click_at(mx, my)
        log.debug(
            "Clicked minimap for '%s' at canvas (%d, %d)",
            entity.get("name", "?"), mx, my,
        )
        self._minimap_walk = {"clicked_tick": game_state.tick, "idle_since_tick": None}
        return True

    def _minimap_walk_in_progress(self, game_state) -> bool:
        """Non-blocking check for whether a tracked minimap walk is still
        settling, advancing the tracked state for this tick as it goes.

        Mirrors how a human would wait before re-clicking, in three phases:

          1. registration — for ``MINIMAP_WALK_START_TICKS`` ticks after the
             click, assume the walk is starting up and don't check idle yet
             (animation/movement takes a tick or two to register);
          2. walking — once registration has elapsed, wait for the player to
             stop animating AND stop moving (``GameState.player_idle``);
          3. settling — once idle, wait ``MINIMAP_WALK_SETTLE_TICKS`` more
             consecutive idle ticks so the polled game state reflects the
             player's final, settled position before allowing a re-click.

        ``MINIMAP_WALK_MAX_TICKS`` is a safety cap: if the walk hasn't
        settled by then (e.g. the path was blocked), the tracked state is
        dropped and the caller is allowed to click again rather than
        waiting forever.

        Returns True while a walk is still being tracked (caller should not
        click again yet), False once it has settled or been abandoned
        (caller may issue a new click).
        """
        walk = self._minimap_walk
        if walk is None:
            return False

        elapsed = game_state.tick - walk["clicked_tick"]
        if elapsed >= MINIMAP_WALK_MAX_TICKS:
            log.debug(
                "Minimap walk did not settle within %d ticks — giving up and allowing a re-click",
                MINIMAP_WALK_MAX_TICKS,
            )
            self._minimap_walk = None
            return False

        if elapsed < MINIMAP_WALK_START_TICKS:
            return True

        if not game_state.player_idle():
            walk["idle_since_tick"] = None
            return True

        if walk["idle_since_tick"] is None:
            walk["idle_since_tick"] = game_state.tick

        if game_state.tick - walk["idle_since_tick"] >= MINIMAP_WALK_SETTLE_TICKS:
            self._minimap_walk = None
            return False

        return True

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

    def right_click_at(self, canvas_x: float, canvas_y: float) -> None:
        """Right-click at an absolute canvas coordinate."""
        if not self._is_canvas_coord_valid(canvas_x, canvas_y):
            log.warning("right_click_at: canvas (%.0f, %.0f) outside viewport — skipping",
                        canvas_x, canvas_y)
            return
        sx, sy = self._canvas_to_screen(canvas_x, canvas_y)
        cur_x, cur_y = mouse_input.get_position()
        intent = self._human.plan_click(sx, sy, cur_x, cur_y)
        ax, ay = self._clamp_to_window(intent.actual_x, intent.actual_y)
        time.sleep(intent.pre_move_pause)
        mouse_input.wind_mouse(cur_x, cur_y, ax, ay, move_speed=intent.move_speed)
        time.sleep(intent.post_move_pause)
        mouse_input.click_right()
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

    def hold_key(self, key: str) -> None:
        """Press `key` down and hold it — pairs with `release_key`.

        No-op if `key` is already held. Use for modifier keys that need to
        stay down across several clicks spanning multiple ticks — e.g.
        holding Shift for an entire "drop everything" sequence the way a
        real player would, rather than tapping it before every click (see
        `InteractionRoutine.drop_item`, `DropMode.SHIFT_CLICK`).
        """
        if key in self._held_keys:
            return
        kb_input.key_down(key)
        self._held_keys.add(key)
        log.debug("Holding key '%s'", key)

    def release_key(self, key: str) -> None:
        """Release a key previously held via `hold_key`. No-op if not held."""
        if key not in self._held_keys:
            return
        kb_input.key_up(key)
        self._held_keys.discard(key)
        log.debug("Released key '%s'", key)

    def release_all_keys(self) -> None:
        """Release every key currently held via `hold_key`.

        Safety net for a held modifier getting stuck down if a multi-tick
        gesture is interrupted (an exception mid-sequence, or the routine
        being swapped out while Shift is still held for a drop sequence).
        """
        for key in list(self._held_keys):
            kb_input.key_up(key)
        self._held_keys.clear()

    def rotate_camera(self, key: str, yaw_amount: float) -> None:
        """
        Hold a yaw-rotation key (`Key.LEFT`/`Key.RIGHT`) for roughly the hold
        time needed to cover `yaw_amount` yaw units, via the HumanEmulator's
        key-hold intent. Low-level primitive that always rotates — unlike
        `rotate_camera_to`, it has no opinion on whether any particular
        entity is currently on-screen, so it also works for nudging the
        camera to steer an *already on-screen* entity out from behind an
        occluding UI panel (panels sit at fixed canvas positions; rotating
        the camera changes where the entity itself projects to).
        """
        intended_hold_ms = yaw_amount / CAMERA_YAW_SPEED
        intent = self._human.plan_key_hold(intended_hold_ms)

        time.sleep(intent.pre_hold_pause)
        kb_input.press_key(key, hold_ms=intent.hold_ms)
        time.sleep(intent.post_hold_pause)

        log.debug(
            "Rotated camera %s by ~%d yaw units (intended %.0f ms, actual %.0f ms)",
            "LEFT" if key == Key.LEFT else "RIGHT",
            yaw_amount,
            intended_hold_ms,
            intent.hold_ms,
        )

    def rotate_camera_to(self, entity: dict, game_state) -> bool:
        """
        Rotate the camera toward an off-screen entity using arrow keys.

        Computes the shortest-arc yaw delta and hands it to `rotate_camera`.
        The caller should return None from its routine state after this call
        so the next tick delivers fresh game state to verify.

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

        self.rotate_camera(key, actual_delta)
        return False

    def bring_entity_on_screen(self, entity: dict, game_state) -> bool:
        """
        Bring an entity into the camera's visible area using FOV-aware logic.

        Uses decide_camera_action() to check whether the entity is already
        visible (on-screen flag OR inside the FOV trapezoid), needs a yaw
        rotation, or is so far off-bearing/distant that walking is the only
        way to bring it into view.

        For the 'walk' case, camera rotation alone would never converge —
        instead we click the entity's pre-computed minimap position so the
        player walks toward it (see click_minimap_entity). If the entity has
        no minimap coordinates (beyond the ~20-tile minimap radius), we fall
        back to rotating the camera as the best single-tick effort.

        Only LEFT/RIGHT yaw rotation is used — pitch (UP/DOWN) is not adjusted.
        Minimap walking gets the player close enough that yaw rotation alone is
        sufficient to bring the entity on-screen. Zoom in/out via the scroll
        wheel is the planned replacement for pitch adjustment (see TODO.md).

        Settling: the tick an adjustment first reports the entity as
        "on_screen", its canvasX/Y can still reflect a transient mid-rotation
        frame — clicking immediately lands on a stale position (a missed
        click). So the first ON_SCREEN_SETTLE_TICKS ticks of "on_screen" are
        treated like an in-progress adjustment (return False, wait); only once
        the entity has stayed on-screen for that long do we report it ready
        to click. _on_screen_since_tick resets whenever a rotation/walk is
        issued, so a fresh adjustment always re-settles before the next click.

        Returns True  if the entity is on-screen AND has stayed there for at
                      least ON_SCREEN_SETTLE_TICKS ticks (caller may click it).
        Returns False if a camera adjustment or minimap walk was issued, or
                      the entity has only just settled on-screen (caller
                      should return None and wait for the next tick).
        """
        action = decide_camera_action(entity, game_state)
        if action == "on_screen":
            if self._on_screen_since_tick is None:
                self._on_screen_since_tick = game_state.tick
            return game_state.tick - self._on_screen_since_tick >= ON_SCREEN_SETTLE_TICKS

        self._on_screen_since_tick = None
        if action == "walk" and self.click_minimap_entity(entity, game_state):
            return False
        self.rotate_camera_to(entity, game_state)
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

    # ------------------------------------------------------------------
    # Live clickbox subscriptions — high-frequency hull updates pushed by
    # the Game Bridge plugin once per ClientTick (~20ms), independent of
    # the once-per-GameTick (~600ms) snapshot in `game_state`. See
    # GAMEBRIDGE.md "Live clickbox subscriptions".
    # ------------------------------------------------------------------

    # subId for the always-on placeholder subscription set up by
    # set_connection() — see its docstring. id=-1 never matches a real
    # player, so this subscription's own `entities[]` result is always
    # "found": false; it exists purely to keep the plugin pushing
    # hullUpdate (and therefore tooltip()) from the moment a connection is
    # established, independent of any routine-specific subscription.
    TOOLTIP_SUB_ID = "_tooltip"

    # ~1,000,000 game ticks (~7 days) — long enough that this subscription
    # never needs renewing for the lifetime of a session.
    TOOLTIP_SUB_TTL_TICKS = 1_000_000

    def set_connection(self, connection: Optional[BridgeConnection]) -> None:
        """Set (or clear) the live BridgeConnection used for subscriptions.

        Called by main.py's connect() loop once per connection attempt.
        Also establishes the always-on TOOLTIP_SUB_ID placeholder
        subscription so hull_update()/tooltip() are populated immediately,
        without every routine needing its own subscription just to read the
        tooltip.
        """
        self._connection = connection
        if connection is not None:
            self.subscribe_to(self.TOOLTIP_SUB_ID, "player", id=-1, ttl_ticks=self.TOOLTIP_SUB_TTL_TICKS)

    def subscribe_to(
        self,
        sub_id: str,
        kind: str,
        name: Optional[str] = None,
        id: Optional[int] = None,
        ttl_ticks: int = 10,
    ) -> None:
        """Register interest in the nearest entity matching kind/name/id.

        Re-sending with the same sub_id renews/overwrites the subscription.
        No-ops with a warning if no connection is set.
        """
        if self._connection is None:
            log.warning("subscribe_to(%s) called with no active connection", sub_id)
            return
        self._connection.subscribe(sub_id, kind, name=name, id=id, ttl_ticks=ttl_ticks)

    def unsubscribe(self, sub_id: str) -> None:
        """Cancel a previously registered subscription.

        No-ops with a warning if no connection is set.
        """
        if self._connection is None:
            log.warning("unsubscribe(%s) called with no active connection", sub_id)
            return
        self._connection.unsubscribe(sub_id)

    def hull_update(self, sub_id: str) -> Optional[dict]:
        """Return the latest hullUpdate entity for sub_id, or None.

        None means either no connection is set or no hullUpdate for this
        sub_id has arrived yet — both are normal while a subscription is
        still being established, so no warning is logged.
        """
        if self._connection is None:
            return None
        return self._connection.hull_updates.get(sub_id)

    def tooltip(self) -> str:
        """Return the current left-click action text (e.g. "Walk here" or
        "Attack Goblin (level-2)"), or "" if no connection is set or no
        hullUpdate has arrived yet.

        Requires at least one active subscription — hullUpdate (and
        therefore this value) is only pushed while the connection has one.
        """
        if self._connection is None:
            return ""
        return self._connection.tooltip

    def tooltip_age(self) -> Optional[float]:
        """Return how many seconds old the current `tooltip()` value is, or
        None if no connection is set or no hullUpdate has arrived yet.

        Diagnostic for staleness — `tooltip_updated_at` is stamped with
        `time.monotonic()` the moment a hullUpdate's tooltip is received
        (see `BridgeConnection.messages`), independent of when it is read.
        """
        if self._connection is None or self._connection.tooltip_updated_at == 0.0:
            return None
        return time.monotonic() - self._connection.tooltip_updated_at
