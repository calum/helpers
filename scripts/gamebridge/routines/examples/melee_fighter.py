"""
Melee Fighter routine.

State diagram
─────────────

  ┌──────────────┐
  │ find_target  │◄─────────────────────────────┐
  └──────┬───────┘                              │
         │ NPC clicked                          │
         ▼                                      │
  ┌──────────────┐                              │
  │   fighting   │──[NPC vanished — assume dead]┤
  └──────┬───────┘                              │
         │                                      │
         ▼                                      │
  ┌──────────────┐                              │
  │   looting    │──[loot window elapsed]───────┘
  └──────────────┘

How to use
──────────
    from scripts.gamebridge.routines.examples.melee_fighter import MeleeFighterRoutine

    engine.set_routine(MeleeFighterRoutine())
"""
from __future__ import annotations

import logging
from typing import Optional, Set, Tuple, TYPE_CHECKING

from ..base import Routine, initial_state

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class MeleeFighterRoutine(Routine):
    """Attack the nearest uncontested NPC by name, loot its drops, repeat."""

    # TODO: read this from the dashboard's NPC-name text box input instead of
    # hardcoding it — for now we always target "GoblinMeleeFighter".
    NPC_NAME = "Goblin"

    LOOT_WINDOW_TICKS = 3       # how long after a kill to watch the corpse tile for drops
    PLAYER_EXCLUSION_TILES = 1  # skip NPCs standing this close to another player

    def __init__(self):
        super().__init__()
        self._target_index: Optional[int] = None
        self._target_pos: Optional[Tuple[int, int]] = None
        self._death_tick: Optional[int] = None
        self._looted_keys: Set[Tuple[int, int, int]] = set()
        self._idle_since_tick: int = -1

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def find_target(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Pick the nearest NPC matching NPC_NAME that isn't standing next to
        another player (avoids contested/kill-stolen targets), bring it on
        screen, and attack it once the camera/player have settled.
        """
        target = self._nearest_available_npc(game)

        if target is None:
            log.debug("No available %s in scene, waiting…", self.NPC_NAME)
            return None

        if not ctrl.bring_entity_on_screen(target, game):
            self._idle_since_tick = -1
            return None

        if target.get("onScreen") and game.is_occluded(target["canvasX"], target["canvasY"]):
            log.debug("%s is hidden behind a UI panel — adjusting camera", self.NPC_NAME)
            ctrl.bring_entity_on_screen(target, game)
            self._idle_since_tick = -1
            return None

        if not game.player_idle():
            self._idle_since_tick = -1
            return None

        if self._idle_since_tick == -1:
            self._idle_since_tick = game.tick
            return None

        ctrl.click_entity(target)
        self._idle_since_tick = -1
        self._target_index = target["index"]
        self._target_pos = (target["worldX"], target["worldY"])
        return "fighting"

    def fighting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait while we fight the target, tracking it by its unique world
        index (its composition `id` is shared with every NPC of the same
        type, so it can't tell two Goblins apart).  Once it's no longer in
        the `npcs` list we assume it died — corpses despawn quickly and we
        don't get an explicit death event — and start watching its tile for
        loot.
        """
        if any(n.get("index") == self._target_index for n in game.npcs):
            return None  # still alive — keep fighting

        log.debug("%s (index=%d) is gone — assuming it died at %s",
                  self.NPC_NAME, self._target_index, self._target_pos)
        self._death_tick = game.tick
        self._looted_keys.clear()
        return "looting"

    def looting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        For LOOT_WINDOW_TICKS ticks after the kill, watch the corpse's tile
        for drops and click each one exactly once — the first successful
        pickup walks the player onto the tile, shifting every subsequent
        item's canvas position, so we re-resolve from live game state on
        every tick rather than caching coordinates. Each item is recorded in
        _looted_keys the moment we click it (not when it disappears) so a
        failed pickup is never retried — "click and move on" mirrors how a
        human would treat a stuck item.
        """
        x, y = self._target_pos

        for item in game.ground_items_at(x, y):
            key = (item["id"], x, y)
            if key in self._looted_keys:
                continue
            if not item.get("onScreen"):
                continue  # wait for it to come into view before attempting

            ctrl.click_entity(item)
            self._looted_keys.add(key)
            return None  # one pickup attempt per tick — let the walk settle before the next

        if game.tick - self._death_tick >= self.LOOT_WINDOW_TICKS:
            return "find_target"

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _nearest_available_npc(self, game: "GameState") -> Optional[dict]:
        """Nearest NPC matching NPC_NAME that isn't within PLAYER_EXCLUSION_TILES
        of another player."""
        candidates = [
            n for n in game.npcs_named(self.NPC_NAME)
            if not game.entity_near_other_player(n, tiles=self.PLAYER_EXCLUSION_TILES)
        ]
        if not candidates:
            return None
        return min(candidates, key=game.distance_to)
