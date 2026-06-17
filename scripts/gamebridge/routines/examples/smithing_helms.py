"""
SmithingHelms routine.

Smith Bronze full helms from Bronze bars at an Anvil, bank the helms, withdraw
fresh bars, and repeat.

State flow
──────────

  banking        → (has bars, no helms)                        → walk_to_anvil
  banking        → (opens bank, deposits helms, withdraws bars) → walk_to_anvil

  walk_to_anvil  → (player near anvil)                         → smith

  smith          → (clicks anvil, picks helm in dialog)        → smithing

  smithing       → (bars depleted, player idle)                → banking
  smithing       → (player idle with bars remaining)           → smith  (restart)

How to use
──────────
    from scripts.gamebridge.routines.examples.smithing_helms import SmithingHelmsRoutine
    engine.set_routine(SmithingHelmsRoutine())

Requirements
────────────
- Plugin object filter must include "Anvil" and "Bank booth" (or
  sendAllNamedObjects=true).
- exposeInterfaces must be enabled (the default).
- The bank must be stocked with Bronze bars (id 2349).
- The bank withdraw quantity for Bronze bars should be set to "Withdraw All"
  so each click fetches a full batch.

Recording basis
───────────────
Derived from recording-20260617-192309.jsonl (player: Pongs Bongos).
Observed: animation 898 for smithing; G312 (SMITHING, "What would you like to
make?") opens on anvil click and closes immediately once the helm item is
clicked; no G270 skillmulti dialog appears — smithing starts directly.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from ..base import initial_state
from ..interaction import InteractionRoutine
from ...input.keyboard import Key
from ...widget_ids import Bankmain, Smithing

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class SmithingHelmsRoutine(InteractionRoutine):
    """Smith Bronze full helms at the anvil, bank them, withdraw bars, repeat."""

    ANVIL_NAME     = "Anvil"
    BANK_BOOTH_NAME = "Bank booth"

    BRONZE_BAR_ID  = 2349
    BRONZE_HELM_ID = 1155  # Bronze full helm
    BARS_PER_HELM  = 2     # Bronze bars consumed per helm

    ANVIL_NEAR_TILES           = 2   # max Manhattan distance to consider "at anvil"
    DEPOSIT_THROTTLE_TICKS     = 8   # ticks between deposit-button clicks
    WITHDRAW_THROTTLE_TICKS    = 4   # ticks between bar-withdrawal clicks
    BANK_OPEN_GRACE_TICKS      = 4   # ticks to wait after clicking the booth before retrying
    ANVIL_DIALOG_TIMEOUT_TICKS = 8   # ticks to wait for G312 to open after clicking anvil
    SMITH_GRACE_TICKS          = 6   # ticks after clicking the helm before checking idle

    def __init__(self) -> None:
        super().__init__()
        self._deposit_clicked_tick: int      = -99
        self._withdraw_tick: int             = -99
        self._bank_clicked_tick: int         = -99
        self._anvil_clicked: bool            = False
        self._anvil_clicked_tick: int        = -99
        self._smith_start_tick: Optional[int] = None

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def banking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Drive the bank cycle tick-by-tick:

        1. Inventory has bars and no helms (ready to smith) → walk to anvil.
        2. Bank not open → approach the bank booth and open it.
        3. Bank open, has helms → deposit inventory (throttled).
        4. Bank open, no bars → find and click the Bronze bar slot.
        5. Bank open, has bars and no helms → press Esc and walk to anvil.
        """
        bank_open = game.is_interface_open("bank")
        has_bars  = game.inventory_count(self.BRONZE_BAR_ID) >= self.BARS_PER_HELM
        has_helms = game.inventory_has_item(self.BRONZE_HELM_ID)

        # Bars loaded and ready — close any drifted-open bank, then head to anvil.
        if has_bars and not has_helms:
            if bank_open:
                ctrl.press_key(Key.ESCAPE)
            return "walk_to_anvil"

        # ── Open the bank ──────────────────────────────────────────────
        if not bank_open:
            if (self._bank_clicked_tick >= 0
                    and game.tick - self._bank_clicked_tick < self.BANK_OPEN_GRACE_TICKS):
                return None

            bank = game.nearest_object(self.BANK_BOOTH_NAME)
            if bank is None:
                log.warning("No %s found — are you near a bank?", self.BANK_BOOTH_NAME)
                return None

            if not self.approach(game, ctrl, bank):
                return None

            if self.click_live(ctrl, bank, "object"):
                self._bank_clicked_tick = game.tick
            return None

        # ── Bank is open ───────────────────────────────────────────────

        if has_helms:
            deposit_btn = game.find_interface_widget(*Bankmain.DEPOSITINV)
            if deposit_btn is not None:
                if game.tick - self._deposit_clicked_tick >= self.DEPOSIT_THROTTLE_TICKS:
                    ctrl.click_widget(deposit_btn)
                    self._deposit_clicked_tick = game.tick
            return None

        if not has_bars:
            bar_slot = self._find_bank_bar(game)
            if bar_slot is None:
                log.warning("No Bronze bars (id %d) in bank — please restock.", self.BRONZE_BAR_ID)
                return None
            if game.tick - self._withdraw_tick >= self.WITHDRAW_THROTTLE_TICKS:
                ctrl.click_widget(bar_slot)
                self._withdraw_tick = game.tick
            return None

        # has_bars, no helms, bank somehow still open
        ctrl.press_key(Key.ESCAPE)
        return "walk_to_anvil"

    def walk_to_anvil(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Walk to the Anvil.  Uses approach() so camera rotation and minimap
        walking are handled transparently.  Transitions to smith once the
        player is within ANVIL_NEAR_TILES.
        """
        anvil = game.nearest_object(self.ANVIL_NAME)
        if anvil is None:
            log.warning("No %s in scene — check the plugin object filter.", self.ANVIL_NAME)
            return None

        if game.player_near(anvil, tiles=self.ANVIL_NEAR_TILES):
            return "smith"

        if not self.approach(game, ctrl, anvil):
            return None

        self.click_live(ctrl, anvil, "object")
        return None

    def smith(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Click the Anvil to open the smithing production dialog (G312, "What
        would you like to make?"), then click the Bronze full helm slot to
        start smithing.

        The dialog closes and animation 898 starts on the same tick as the
        item click — no G270 "How many?" sub-prompt appears for anvil smithing.
        The routine transitions immediately to smithing so the grace period can
        absorb the animation start-up lag.
        """
        if game.is_interface_open("smithing"):
            helm = next(
                (w for w in game.interfaces_for_group(Smithing.GROUP)
                 if w.get("itemId") == self.BRONZE_HELM_ID),
                None,
            )
            if helm is not None:
                ctrl.click_widget(helm)
                self._smith_start_tick = game.tick
                self._anvil_clicked = False
                return "smithing"
            # Dialog open but Bronze full helm not yet visible — wait one tick.
            return None

        # Dialog not open — click the anvil once and wait for it to appear.
        if self._anvil_clicked:
            if game.tick - self._anvil_clicked_tick >= self.ANVIL_DIALOG_TIMEOUT_TICKS:
                log.debug("Smithing dialog did not open after %d ticks — retrying anvil click",
                          self.ANVIL_DIALOG_TIMEOUT_TICKS)
                self._anvil_clicked = False
            return None

        anvil = game.nearest_object(self.ANVIL_NAME)
        if anvil is None:
            log.warning("Anvil not in scene — returning to walk state")
            return "walk_to_anvil"

        if not self.approach(game, ctrl, anvil):
            return None

        if self.click_live(ctrl, anvil, "object"):
            self._anvil_clicked = True
            self._anvil_clicked_tick = game.tick
        return None

    def smithing(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait for the smithing animation (id 898) to consume all bars.
        Bronze full helm takes ~3 ticks each; a full batch of 14 bars (7 helms)
        takes ~21 ticks.

        - Bars depleted AND player idle → return to banking.
        - Player idle with bars remaining AND past startup grace period
          → something interrupted smithing; retry from smith.
        """
        has_bars = game.inventory_count(self.BRONZE_BAR_ID) >= self.BARS_PER_HELM

        if not has_bars:
            if game.player_idle():
                log.info("Smithing batch complete — returning to bank")
                return "banking"
            return None

        # Enough bars remain — check for premature stop.
        if (game.player_idle()
                and self._smith_start_tick is not None
                and game.tick - self._smith_start_tick >= self.SMITH_GRACE_TICKS):
            log.debug("Player idle with bars remaining after %d ticks — retrying smith",
                      game.tick - self._smith_start_tick)
            return "smith"

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_bank_bar(self, game: "GameState") -> Optional[dict]:
        """Return the first G12 interface widget whose itemId is Bronze bar, or None."""
        return next(
            (w for w in game.interfaces
             if w.get("groupId") == Bankmain.GROUP and w.get("itemId") == self.BRONZE_BAR_ID),
            None,
        )
