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

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class IronMiningRoutine(Routine):
    """Mine iron ore rocks, bank when full, repeat."""

    ORE_NAME = "Iron rocks"
    BANK_NAME = "Mine cart"

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
        return "mining"

    def mining(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait while the player swings their pickaxe.
        Transition to banking if the inventory fills up,
        or back to find_ore when the animation ends (ore depleted).
        """
        if game.inventory_full():
            return "walk_to_bank"

        if not game.player_animating():
            # Animation ended — ore depleted or click missed
            return "find_ore"

        return None  # still mining

    def walk_to_bank(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Click the nearest bank deposit box to walk toward it.
        Transition to deposit once we're adjacent.
        """
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
        Right-click the deposit box and choose 'Deposit inventory'.
        Returns to find_ore once slots are free.
        """
        box = game.nearest_object(self.BANK_NAME)

        if box is None or not game.player_near(box, tiles=2):
            # Walked too far or box disappeared — try again
            return "walk_to_bank"

        if box.get("onScreen"):
            ctrl.right_click_entity(box)
            # Wait briefly for the context menu / deposit animation
            ctrl.wait(1.2)

        if game.inventory_free_slots() > 0:
            log.info("Deposited ores. Free slots: %d", game.inventory_free_slots())
            return "find_ore"

        # Inventory still full — try depositing again next tick
        return None
