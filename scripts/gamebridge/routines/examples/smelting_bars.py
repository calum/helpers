"""
SmeltingBars routine.

Smelt Bronze bars from Tin ore and Copper ore at a Furnace, bank the bars,
withdraw fresh ores, and repeat.

State flow
──────────

  banking       → (has ores, no bars)                        → walk_to_furnace
  banking       → (opens bank, deposits bars, withdraws ores) → walk_to_furnace

  walk_to_furnace → (player near furnace)                    → smelt

  smelt         → (clicks furnace, Space on dialog)          → smelting

  smelting      → (ores depleted, player idle)               → banking
  smelting      → (player idle with ores remaining)          → smelt  (restart)

How to use
──────────
    from scripts.gamebridge.routines.examples.smelting_bars import SmeltingBarsRoutine
    engine.set_routine(SmeltingBarsRoutine())

Requirements
────────────
- Plugin object filter must include "Furnace" and "Bank booth" (or
  sendAllNamedObjects=true).
- exposeInterfaces must be enabled (the default).
- The bank must be stocked with Tin ore (id 438) and Copper ore (id 436).
- The bank's withdraw quantity for both ore types should be set to "Withdraw All"
  (or a value that fills half the inventory) so each click fetches a full batch.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from ..base import initial_state
from ..interaction import InteractionRoutine
from ...input.keyboard import Key
from ... import item_ids

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class SmeltingBarsRoutine(InteractionRoutine):
    """Smelt Bronze bars at the furnace, bank them, withdraw ores, repeat."""

    FURNACE_NAME = "Furnace"
    BANK_BOOTH_NAME = "Bank booth"

    TIN_ORE_ID    = item_ids.TIN_ORE
    COPPER_ORE_ID = item_ids.COPPER_ORE
    BRONZE_BAR_ID = item_ids.BRONZE_BAR

    # G270:38 — the Skillmulti item slot used by both smelting and cooking
    # (same widget as FishAndCookRoutine.COOK_WIDGET).  itemId discriminates.
    SMELT_WIDGET = (270, 38)

    FURNACE_NEAR_TILES     = 2   # max Manhattan distance to consider "at furnace"
    DEPOSIT_THROTTLE_TICKS = 8   # ticks between deposit-button clicks (server takes 2-3 to process)
    WITHDRAW_THROTTLE_TICKS = 4  # ticks between bank-withdrawal clicks
    BANK_OPEN_GRACE_TICKS  = 4   # ticks to wait after clicking the booth before retrying
    SMELT_GRACE_TICKS      = 6   # ticks after pressing Space before checking idle (animation startup lag)

    def __init__(self) -> None:
        super().__init__()
        self._withdraw_tin_tick: int       = -99
        self._withdraw_copper_tick: int    = -99
        self._smelt_start_tick: Optional[int] = None
        self._furnace_clicked: bool        = False

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def banking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Drive the full bank cycle tick-by-tick:

        1. Ores loaded, no bars → walk to furnace.
        2. Bank not open → open_bank() approaches and clicks the booth.
        3. Bank open, has bars → deposit_inventory() (throttled).
        4. Bank open, no tin → find and click the Tin ore slot.
        5. Bank open, no copper → find and click the Copper ore slot.
        6. Both ores present, bank somehow still open → Esc, walk to furnace.
        """
        bank_open  = game.is_interface_open("bank")
        has_bars   = game.inventory_has_item(self.BRONZE_BAR_ID)
        has_tin    = game.inventory_has_item(self.TIN_ORE_ID)
        has_copper = game.inventory_has_item(self.COPPER_ORE_ID)

        if has_tin and has_copper and not has_bars:
            if bank_open:
                ctrl.press_key(Key.ESCAPE)
            return "walk_to_furnace"

        if not self.open_bank(game, ctrl, self.BANK_BOOTH_NAME, self.BANK_OPEN_GRACE_TICKS):
            return None

        if has_bars:
            self.deposit_inventory(game, ctrl, self.DEPOSIT_THROTTLE_TICKS)
            return None

        if not has_tin:
            tin_slot = self.find_bank_item(game, self.TIN_ORE_ID)
            if tin_slot is None:
                log.warning("No Tin ore (id %d) found in bank — please restock.", self.TIN_ORE_ID)
                return None
            if game.tick - self._withdraw_tin_tick >= self.WITHDRAW_THROTTLE_TICKS:
                ctrl.click_widget(tin_slot)
                self._withdraw_tin_tick = game.tick
            return None

        if not has_copper:
            copper_slot = self.find_bank_item(game, self.COPPER_ORE_ID)
            if copper_slot is None:
                log.warning("No Copper ore (id %d) found in bank — please restock.", self.COPPER_ORE_ID)
                return None
            if game.tick - self._withdraw_copper_tick >= self.WITHDRAW_THROTTLE_TICKS:
                ctrl.click_widget(copper_slot)
                self._withdraw_copper_tick = game.tick
            return None

        ctrl.press_key(Key.ESCAPE)
        return "walk_to_furnace"

    def walk_to_furnace(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Walk to the Furnace, transitioning to smelt once adjacent."""
        if self.walk_to_object(game, ctrl, self.FURNACE_NAME, self.FURNACE_NEAR_TILES):
            return "smelt"
        return None

    def smelt(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Click the Furnace to open the "How many would you like to smelt?"
        Skillmulti dialog (G270), then press Space to smelt all Bronze bars.

        G270:38 is the item-slot widget shared with the cooking dialog; here
        it carries itemId=2349 (Bronze bar) once the game has resolved the
        definition — typically 2-3 ticks after the dialog opens.
        """
        smelt_widget = game.find_interface_widget(*self.SMELT_WIDGET)
        if smelt_widget is not None and smelt_widget.get("itemId") == self.BRONZE_BAR_ID:
            ctrl.press_key(Key.SPACE)
            self._smelt_start_tick = game.tick
            self._furnace_clicked  = False
            return "smelting"

        # Dialog not open (or item not yet resolved) — click the furnace once
        # and wait; _furnace_clicked prevents re-clicking every tick.
        if self._furnace_clicked:
            return None

        furnace = game.nearest_object(self.FURNACE_NAME)
        if furnace is None:
            log.warning("Furnace not in scene — returning to walk state")
            return "walk_to_furnace"

        if not self.approach(game, ctrl, furnace):
            return None

        if self.click_live(ctrl, furnace, "object"):
            self._furnace_clicked = True
        return None

    def smelting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait for the smelting animation (id 899) to consume all ores.
        Bronze bar takes ~3 ticks each; a full batch of 14 pairs takes ~42 ticks.

        - Ores depleted AND player idle → return to banking.
        - Player idle with ores remaining AND past the startup grace period
          → something interrupted smelting; retry from smelt.
        """
        has_ores = (game.inventory_has_item(self.TIN_ORE_ID)
                    and game.inventory_has_item(self.COPPER_ORE_ID))

        if not has_ores:
            if game.player_idle():
                log.info("Smelting batch complete — returning to bank")
                return "banking"
            return None

        # Ores remain — check for premature stop.
        if (game.player_idle()
                and self._smelt_start_tick is not None
                and game.tick - self._smelt_start_tick >= self.SMELT_GRACE_TICKS):
            log.debug("Player idle with ores remaining after %d ticks — retrying smelt",
                      game.tick - self._smelt_start_tick)
            return "smelt"

        return None

