"""
Iron mining routine.

State diagram
─────────────

  ┌─────────────┐
  │  find_ore   │◄──────────────────────────────┐
  └──────┬──────┘                               │
         │ ore on screen                        │
         ▼                                      │
  ┌─────────────┐                               │
  │   mining    │──[inventory full]──┐          │
  └──────┬──────┘                   │          │
         │ animation ended,         │          │
         │ inventory not full       │          │
         └──────────────────────────┼──────────┘ (deposit done)
                                    ▼
                           ┌────────────────┐
                           │ walk_to_bank   │
                           └───────┬────────┘
                                   │ near deposit box
                                   ▼
                           ┌────────────────┐
                           │    deposit     │
                           └────────────────┘

How to use
──────────
    from scripts.gamebridge.routines.examples.iron_mining import IronMiningRoutine

    engine.set_routine(IronMiningRoutine())

Customisation
─────────────
Override ORE_NAME and BANK_NAME at the class level, or subclass to change
any single state without rewriting the whole routine.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from ..base import Routine, initial_state
from ...input.keyboard import Key
from ...ui.widgets import BankDepositBox

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class IronMiningRoutine(Routine):
    """Mine iron ore rocks, bank when full, repeat."""

    ORE_NAME = "Iron rocks"
    BANK_NAME = "Mine cart"
    CLICK_INTERVAL = 1.5  # casual routine — minimum 1.5 s between entity clicks
    MINING_XP_TIMEOUT_MS = 3000  # max time to wait for mining XP drop before checking idle (3 seconds)

    def __init__(self):
        super().__init__()
        self.mining_start_tick: Optional[int] = None
        self._deposit_clicked_tick: int = -99

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def find_ore(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Scan for the nearest iron ore rock.
        If inventory is already full, skip straight to banking.
        """
        if game.inventory_full():
            return "walk_to_bank"

        ore = game.nearest_object(self.ORE_NAME)

        if ore is None:
            # No ore in scene — ore may have just been mined; wait for respawn.
            log.debug("No %s in scene, waiting…", self.ORE_NAME)
            return None

        if not ore.get("onScreen"):
            # Rock exists but camera isn't facing it.
            # A real routine would rotate the camera or walk toward it;
            # for now just wait a tick and let the scene update.
            log.debug("%s at (%d,%d) is off-screen", self.ORE_NAME, ore["worldX"], ore["worldY"])
            return None

        ctrl.click_entity(ore)
        self.mining_start_tick = game.tick
        return "mining"

    def mining(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait while the player swings their pickaxe.
        Check for a mining XP drop (with 3-second timeout) to detect ore depletion,
        then verify the player is idle before looking for ore again.
        Transition to banking if the inventory fills up.
        """
        if game.inventory_full():
            return "walk_to_bank"

        if self.mining_start_tick is None:
            # Safety fallback in case mining_start_tick wasn't set
            return "find_ore"

        # Calculate elapsed time since mining started
        ticks_elapsed = game.tick - self.mining_start_tick
        time_elapsed_ms = ticks_elapsed * 600  # ~600ms per game tick

        # Check if we received a mining XP drop since mining started
        last_mining_xp_tick = game.last_xp_tick.get("MINING", -1)
        got_xp_drop = last_mining_xp_tick >= self.mining_start_tick

        # Transition to find_ore if either:
        # 1. We got a mining XP drop and player is idle, OR
        # 2. 3 seconds have elapsed and player is idle (timeout fallback)
        if (got_xp_drop or time_elapsed_ms >= self.MINING_XP_TIMEOUT_MS):
            if game.player_idle():
                log.debug(
                    "Mining ended after %.1fs (xp=%s, timeout=%s)",
                    time_elapsed_ms / 1000.0,
                    got_xp_drop,
                    time_elapsed_ms >= self.MINING_XP_TIMEOUT_MS,
                )
                return "find_ore"

        return None  # still mining

    def walk_to_bank(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Click the nearest bank deposit box to walk toward it.
        Transition to deposit once we're adjacent.
        """
        if game.inventory_empty():
            return "find_ore"

        box = game.nearest_object(self.BANK_NAME)

        if box is None:
            log.warning("No %s found — are you near a bank?", self.BANK_NAME)
            return None

        if game.player_near(box, tiles=2):
            return "deposit"

        if box.get("onScreen"):
            ctrl.click_entity(box)
        else:
            log.debug("%s is off-screen, waiting…", self.BANK_NAME)

        return None  # walking

    def deposit(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Click the Mine cart to open the deposit UI, then click the
        'Deposit inventory' button (widget 192:31) to empty the pack.
        Returns to find_ore once slots are free.

        Uses tick-based polling rather than blocking sleeps so the game state
        stays live between deposit click and confirmation.  We always press Esc
        on exit to close the deposit box — pressing Esc when nothing is open is
        a harmless no-op.  We throttle clicks to one per 8 ticks (~4.8 s) so a
        single deposit attempt can fully process before we retry.
        """
        deposit_btn = game.find_widget(*BankDepositBox.DEPOSIT_INV)

        if game.inventory_free_slots() > 0:
            # Always close the deposit box before returning — Esc is a no-op if
            # the interface already closed, and avoids leaving it open on screen.
            ctrl.press_key(Key.ESCAPE)
            return "find_ore"

        box = game.nearest_object(self.BANK_NAME)

        if box is None or not game.player_near(box, tiles=2):
            return "walk_to_bank"

        if deposit_btn is not None:
            # One click per 8 ticks — the server takes ~2-3 ticks to process a
            # deposit, so 8 ticks gives plenty of headroom before we retry.
            if game.tick - self._deposit_clicked_tick >= 8:
                ctrl.click_widget(deposit_btn)
                self._deposit_clicked_tick = game.tick
        elif box.get("onScreen"):
            # UI not open yet — click the Mine cart to open it
            ctrl.click_entity(box)

        return None
