"""
InteractionRoutine — shared helpers for routines that click on game entities.

Two gating patterns recur across every routine that interacts with the
world (mining, fighting, looting, banking — see iron_mining.py and
melee_fighter.py):

1. **Approach** — before clicking an entity, bring it on screen, steer the
   camera clear of occluding UI panels, and wait for the player to stop
   moving. A one-tick settle buffer ensures the click lands once the
   walk/camera-pan has visually resolved rather than mid-motion (firing the
   instant `player_idle()` flips true can still land while the camera is
   still panning).

2. **Verify before you click** — right-click an entity, read the context
   menu back to confirm the option you actually want is present (a blind
   left-click can land on a tile or another entity in a crowd), then click
   that exact row. Right-click menus don't time out, so one that opens
   without the wanted row has to be dismissed explicitly or the routine
   would sit there forever.

`InteractionRoutine` factors both into reusable, tick-driven helpers so
individual routines describe *what* to interact with, not *how* to wait
for the game to be ready. Subclass it instead of `Routine` to use them.
"""
from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

from .base import Routine
from ..input.keyboard import Key

if TYPE_CHECKING:
    from ..state.game_state import GameState
    from ..controller.controller import GameController

log = logging.getLogger(__name__)

OCCLUSION_NUDGE_YAW = 128.0  # ~1/16 turn — enough to shift an entity's canvas position out from behind a fixed UI panel


class MenuClick(Enum):
    """Outcome of one tick's attempt to confirm-and-click a context menu row."""

    CONFIRMED = auto()  # the row was present and clicked — gesture complete
    ABANDONED = auto()  # menu closed without the row — give up, retarget fresh
    PENDING = auto()    # menu still open without the row — dismissed, keep waiting


class InteractionRoutine(Routine):
    """Routine base class adding `approach` and `verified_menu_click`."""

    def __init__(self) -> None:
        super().__init__()
        self._approach_idle_since_tick: int = -1

    # ------------------------------------------------------------------
    # Approach
    # ------------------------------------------------------------------

    def approach(self, game: "GameState", ctrl: "GameController", entity: dict) -> bool:
        """
        Drive the camera/movement gating needed before interacting with
        `entity`. Call once per tick while approaching it; returns True on
        the single tick it's safe to click — on screen, unoccluded, and the
        player idle for a full settle tick — and resets its internal buffer
        so the next approach starts fresh. Returns False on every other
        tick, so callers can simply:

            if not self.approach(game, ctrl, entity):
                return None
            ctrl.click_entity(entity)
        """
        name = entity.get("name", "entity")

        if not ctrl.bring_entity_on_screen(entity, game):
            log.debug("%s not visible — adjusting camera", name)
            self._approach_idle_since_tick = -1
            return False

        if entity.get("onScreen") and game.is_occluded(entity["canvasX"], entity["canvasY"]):
            # `bring_entity_on_screen`/`rotate_camera_to` both bail out as
            # soon as `onScreen` is true — exactly the state we're in here,
            # so calling either is a no-op and the entity sits behind the
            # panel forever. UI panels live at fixed canvas positions, so
            # rotating the camera is what actually moves the entity's
            # projected position out from behind one.
            log.debug("%s is hidden behind a UI panel — nudging camera clear", name)
            ctrl.rotate_camera(Key.RIGHT, OCCLUSION_NUDGE_YAW)
            self._approach_idle_since_tick = -1
            return False

        if not game.player_idle():
            self._approach_idle_since_tick = -1
            return False

        if self._approach_idle_since_tick == -1:
            self._approach_idle_since_tick = game.tick
            return False

        self._approach_idle_since_tick = -1
        return True

    # ------------------------------------------------------------------
    # Verify before you click
    # ------------------------------------------------------------------

    def verified_menu_click(
        self,
        game: "GameState",
        ctrl: "GameController",
        verb: str,
        target_name: Optional[str],
    ) -> MenuClick:
        """
        Attempt to confirm-and-click a "`verb` `target_name`" row in an
        already-open right-click context menu (the gesture must have been
        started with `ctrl.right_click_entity(...)` beforehand). Call once
        per tick while the gesture is pending — it never blocks:

        - CONFIRMED: the row was there and got clicked — gesture done.
        - ABANDONED: the menu closed without the row — give up and retry
          with a fresh target next tick.
        - PENDING: the menu is still open without the row — it has been
          dismissed (menus don't time out) so the gesture can be retried
          once it closes.
        """
        if ctrl.click_menu_entry(game, verb, target_name):
            return MenuClick.CONFIRMED

        if not game.menu_open():
            log.debug("Menu closed without a %s %s entry — retrying", verb, target_name)
            return MenuClick.ABANDONED

        log.debug("Menu open without a %s %s entry — dismissing it", verb, target_name)
        ctrl.dismiss_menu(game)
        return MenuClick.PENDING
