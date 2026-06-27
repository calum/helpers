"""
Rod-fishing at Barbarian Village — Fish, Cook, Bank routine.

Catches Trout/Salmon at a Rod Fishing Spot south of Barbarian Village,
cooks two batches over a nearby Fire, banks the cooked fish at the
Barbarian Village bank booth, and repeats.

Route outbound:  Bank booth → Fern (3098, 3458) → Tree (3100, 3436) → Rod Fishing Spot
Route inbound:   Rod Fishing Spot → Tree → Fern → Bank booth

State flow
──────────

  resume (entry point — picks up wherever the player/inventory are)
    → inventory full, raw fish left to cook                       → cooking
    → inventory full, nothing left to cook                        → banking / walk_to_bank_fern / walk_to_bank_tree
    → inventory not full, already near the Tree                   → find_spot
    → inventory not full, within minimap range of the Tree        → walk_to_tree
    → inventory not full, far from the Tree                       → walk_to_fern

  banking           → (inventory clear)                          → walk_to_fern
  banking           → (cooked fish: deposits, closes bank)       → walk_to_fern

  walk_to_fern      → (Tree landmark visible on minimap)         → walk_to_tree
  walk_to_tree      → (player within 12 tiles of Tree)           → find_spot

  find_spot         → (left-clicks Rod Fishing Spot)             → fishing
  fishing           → (inventory full)                           → cooking

  cooking           → (batch 1 done, no raw fish)                → drop_burnt
  drop_burnt        → (burnt fish cleared)                       → find_spot

  fishing (batch 2) → (inventory full)                           → cooking
  cooking           → (batch 2 done, no raw fish)                → drop_and_return
  drop_and_return   → (raw + burnt cleared, cooked fish kept)    → walk_to_bank_tree

  walk_to_bank_tree → (player north of Tree y-coord)             → walk_to_bank_fern
  walk_to_bank_fern → (player north of Fern y-coord)             → banking

How to use
──────────
    from scripts.gamebridge.routines.examples.rod_fishing import RodFishingRoutine
    engine.set_routine(RodFishingRoutine())

Requirements
────────────
- objectFilter must include "Fern", "Tree", "Fire", "Bank booth"
  OR sendAllNamedObjects=true.
- exposeNpcs=true (default) — for "Rod Fishing Spot".
- exposeInterfaces=true (default) — for cooking dialog (G270:38) and bank.
- exposeWidgets=true — for inventory drop (shift-click).
- A fly fishing rod and feathers must be in the inventory or equipped.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, TYPE_CHECKING

from ..base import initial_state
from ..interaction import InteractionRoutine
from ...input.keyboard import Key
from ... import item_ids

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class RodFishingRoutine(InteractionRoutine):
    """Fish, cook two batches, bank at Barbarian Village, repeat."""

    # Entity names
    FISHING_SPOT_NAME = "Rod Fishing Spot"
    FIRE_NAME         = "Fire"
    BANK_BOOTH_NAME   = "Bank booth"
    FERN_NAME         = "Fern"
    TREE_NAME         = "Tree"

    # Item IDs
    RAW_TROUT_ID     = item_ids.RAW_TROUT
    RAW_SALMON_ID    = item_ids.RAW_SALMON
    COOKED_TROUT_ID  = item_ids.COOKED_TROUT
    COOKED_SALMON_ID = item_ids.COOKED_SALMON
    BURNT_FISH_ID    = item_ids.BURNT_FISH_ROD

    BANKABLE_IDS   = (item_ids.RAW_TROUT, item_ids.RAW_SALMON,
                      item_ids.COOKED_TROUT, item_ids.COOKED_SALMON,
                      item_ids.BURNT_FISH_ROD)
    DROP_BURNT_IDS = (item_ids.BURNT_FISH_ROD,)
    DROP_ALL_IDS   = (item_ids.RAW_TROUT, item_ids.RAW_SALMON, item_ids.BURNT_FISH_ROD)

    # Route waypoints (Barbarian Village)
    FERN_WORLD_X = 3098
    FERN_WORLD_Y = 3458
    TREE_WORLD_X = 3100
    TREE_WORLD_Y = 3436

    # Minimap widget group ID
    MINIMAP_GROUP = 160

    # Cooking dialog: G270:38 — "How many would you like to cook?"
    COOK_WIDGET = (270, 38)

    # Tuning constants
    MINIMAP_RANGE              = 20   # tiles — minimap visibility radius; used to decide when to switch waypoints
    TREE_NEAR_TILES           = 12   # arrival threshold near Tree waypoint (outbound)
    FIRE_SEARCH_RADIUS        = 8    # tiles — look for a Fire within this distance
    FISHING_IDLE_TIMEOUT_TICKS = 6   # idle ticks without XP before re-clicking spot
    COOKING_GESTURE_TICKS     = 3    # min ticks to wait after clicking the fire before re-clicking if no dialog appears
    BANK_OPEN_GRACE_TICKS     = 4
    DEPOSIT_THROTTLE_TICKS    = 8

    def __init__(self) -> None:
        super().__init__()
        self._spot_index: Optional[int] = None
        self._fish_start_tick: int = -99
        self._cook_started_tick: Optional[int] = None
        self._batches_cooked: int = 0

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def resume(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """One-shot entry point — a freshly constructed routine has no memory
        of which leg of the loop the player was on (script restart, dashboard
        reload, manual repositioning, etc.), so figure out where to rejoin
        the cycle from the player's current position and inventory instead
        of always replaying the post-bank leg from the top.

        Mirrors the same thresholds the rest of the state machine already
        uses to hand legs off to one another (TREE_NEAR_TILES/MINIMAP_RANGE
        outbound, TREE_WORLD_Y/FERN_WORLD_Y inbound) so the resumed leg is
        the same one the normal flow would already be in.
        """
        log.info("Resuming from %s with inventory %s", game.player_pos, game.inventory)
        if game.inventory_full():
            if self._next_raw_fish(game) is not None:
                log.info("Raw fish left to cook — resuming toward cooking")
                return "cooking"
            log.info("Inventory full — resuming toward bank")
            return self._resume_toward_bank(game)
        log.info("Inventory not full — resuming toward fishing spot")
        return self._resume_toward_spot(game)

    def banking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Deposit all fish at the bank booth, then head south for the next cycle."""
        has_bankable = any(game.inventory_has_item(i) for i in self.BANKABLE_IDS)

        if not has_bankable:
            if game.is_interface_open("bank"):
                ctrl.press_key(Key.ESCAPE)
                return None
            self._batches_cooked = 0
            return "walk_to_fern"

        if not self.open_bank(game, ctrl, self.BANK_BOOTH_NAME, self.BANK_OPEN_GRACE_TICKS):
            return None

        self.deposit_inventory(game, ctrl, self.DEPOSIT_THROTTLE_TICKS)
        return None

    def walk_to_fern(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Walk south toward the Fern waypoint (3098, 3458).

        Transitions to walk_to_tree once the player is within MINIMAP_RANGE
        tiles of the Tree waypoint coordinates (3100, 3436).
        """
        px, py = game.player_pos
        if abs(px - self.TREE_WORLD_X) + abs(py - self.TREE_WORLD_Y) <= self.MINIMAP_RANGE:
            return "walk_to_tree"

        self._walk_toward_world(game, ctrl, self.FERN_WORLD_X, self.FERN_WORLD_Y)
        return None

    def walk_to_tree(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Walk south toward the Tree waypoint (3100, 3436).

        Transitions to find_spot once the player is within TREE_NEAR_TILES
        of the tree (close enough to see and click a Rod Fishing Spot).
        """
        px, py = game.player_pos
        if abs(px - self.TREE_WORLD_X) + abs(py - self.TREE_WORLD_Y) <= self.TREE_NEAR_TILES:
            return "find_spot"

        self._walk_toward_world(game, ctrl, self.TREE_WORLD_X, self.TREE_WORLD_Y)
        return None

    def find_spot(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Locate the nearest Rod Fishing Spot and left-click it to begin fishing."""
        if game.inventory_full():
            return "cooking"

        spot = game.nearest_npc(self.FISHING_SPOT_NAME)
        if spot is None:
            log.info("No %s in scene — waiting", self.FISHING_SPOT_NAME)
            return None

        if not self.approach(game, ctrl, spot):
            return None

        if self.click_live(ctrl, spot, "npc"):
            self._spot_index = spot.get("index")
            self._fish_start_tick = game.tick
            return "fishing"
        return None

    def fishing(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Wait for the inventory to fill, tracking the spot by its unique index.

        Re-targets if the spot wanders off, or if the player goes idle for
        FISHING_IDLE_TIMEOUT_TICKS without filling the inventory.
        """
        if game.inventory_full():
            return "cooking"

        live_spot = next(
            (n for n in game.npcs if n.get("index") == self._spot_index),
            None,
        )
        if live_spot is None:
            log.info("%s wandered off — re-targeting", self.FISHING_SPOT_NAME)
            return "find_spot"

        if game.player_idle():
            if game.tick - self._fish_start_tick >= self.FISHING_IDLE_TIMEOUT_TICKS:
                log.info("Stopped fishing — re-clicking spot")
                return "find_spot"
        else:
            self._fish_start_tick = game.tick

        return None

    def cooking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Cook all raw trout and salmon by left-clicking the nearest Fire.
        Presses Space on the Skillmulti dialog.

        Tracks batches via _batches_cooked: after batch 1 → drop_burnt,
        after batch 2 → drop_and_return.
        """
        if self._next_raw_fish(game) is None:
            self._cook_started_tick = None
            self._batches_cooked += 1
            return "drop_and_return" if self._batches_cooked >= 2 else "drop_burnt"

        cook_widget = game.find_interface_widget(*self.COOK_WIDGET)
        if cook_widget is not None:
            ctrl.press_key(Key.SPACE)
            self._cook_started_tick = game.tick
            return None

        if self._cook_started_tick is not None:
            if (not game.player_idle()
                    or game.tick - self._cook_started_tick < self.COOKING_GESTURE_TICKS):
                return None
            self._cook_started_tick = None

        fire = self._nearest_fire_in_range(game)
        if fire is None:
            log.info("No %s within %d tiles — waiting", self.FIRE_NAME, self.FIRE_SEARCH_RADIUS)
            return None

        if not self.approach(game, ctrl, fire):
            return None

        if self.click_live(ctrl, fire, "object"):
            self._cook_started_tick = game.tick
        return None

    def drop_burnt(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Drop burnt fish, then return to fishing for the second batch."""
        if self.drop_items_shift_click(game, ctrl, self.DROP_BURNT_IDS):
            return None
        return "find_spot"

    def drop_and_return(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Drop remaining raw and burnt fish (keeping cooked fish for banking),
        then walk back to the bank."""
        if self.drop_items_shift_click(game, ctrl, self.DROP_ALL_IDS):
            return None
        return "walk_to_bank_tree"

    def walk_to_bank_tree(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Walk north from the fishing spot, using the Tree as a waypoint.
        Transitions once the player has reached the Tree's y-coordinate."""
        _, py = game.player_pos
        if py >= self.TREE_WORLD_Y:
            return "walk_to_bank_fern"

        self._walk_toward_world(game, ctrl, self.TREE_WORLD_X, self.TREE_WORLD_Y + 5)
        return None

    def walk_to_bank_fern(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Walk north toward the Fern waypoint. Once past the Fern's
        y-coordinate the bank booth is within scene range and the banking
        state handles the final approach."""
        _, py = game.player_pos
        if py >= self.FERN_WORLD_Y:
            return "banking"

        self._walk_toward_world(game, ctrl, self.FERN_WORLD_X, self.FERN_WORLD_Y + 5)
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resume_toward_bank(self, game: "GameState") -> str:
        """Pick the inbound leg matching the player's current position,
        using the same y-coordinate thresholds walk_to_bank_tree/
        walk_to_bank_fern already use to hand off to one another."""
        log.info("Resuming toward bank from %s", game.player_pos)
        _, py = game.player_pos
        if py >= self.FERN_WORLD_Y:
            log.info("Resuming at or north of Fern y=%d → banking", self.FERN_WORLD_Y)
            return "banking"
        if py >= self.TREE_WORLD_Y:
            log.info("Resuming at or north of Tree y=%d → walk_to_bank_fern", self.TREE_WORLD_Y)
            return "walk_to_bank_fern"
        log.info("Resuming south of Tree y=%d → walk_to_bank_tree", self.TREE_WORLD_Y)
        return "walk_to_bank_tree"

    def _resume_toward_spot(self, game: "GameState") -> str:
        """Pick the outbound leg matching the player's current position,
        using the same distance thresholds find_spot/walk_to_tree/
        walk_to_fern already use to hand off to one another."""
        log.info("Resuming toward fishing spot from %s", game.player_pos)
        px, py = game.player_pos
        dist_to_tree = abs(px - self.TREE_WORLD_X) + abs(py - self.TREE_WORLD_Y)
        if dist_to_tree <= self.TREE_NEAR_TILES:
            log.info("Resuming within %d tiles of Tree → find_spot", self.TREE_NEAR_TILES)
            return "find_spot"
        if dist_to_tree <= self.MINIMAP_RANGE:
            log.info("Resuming within minimap range → walk_to_tree", self.MINIMAP_RANGE)
            return "walk_to_tree"
        log.info("Resuming outside minimap range → walk_to_fern")
        return "walk_to_fern"

    def _nearest_fire_in_range(self, game: "GameState") -> Optional[dict]:
        return min(
            (o for o in game.objects_named(self.FIRE_NAME)
             if game.distance_to(o) <= self.FIRE_SEARCH_RADIUS),
            key=game.distance_to,
            default=None,
        )

    def _next_raw_fish(self, game: "GameState") -> Optional[int]:
        if game.inventory_has_item(self.RAW_TROUT_ID):
            return self.RAW_TROUT_ID
        if game.inventory_has_item(self.RAW_SALMON_ID):
            return self.RAW_SALMON_ID
        return None

    def _walk_toward_world(
        self,
        game: "GameState",
        ctrl: "GameController",
        target_x: int,
        target_y: int,
    ) -> None:
        """Click the minimap toward the given world coordinate.

        Prefers a real scene entity at (target_x, target_y) — its
        minimapX/Y is computed by the game engine and is accurate regardless
        of minimap zoom or compass rotation. Falls back to a synthetic
        position when no matching entity is in minimap range.
        """
        target = (self._real_minimap_entity(game, target_x, target_y)
                  or self._synthetic_minimap_entity(game, target_x, target_y))
        if target is not None:
            ctrl.click_minimap_entity(target, game)

    def _real_minimap_entity(
        self,
        game: "GameState",
        target_x: int,
        target_y: int,
    ) -> Optional[dict]:
        """Return the first scene object at (target_x, target_y) that has
        valid minimapX/Y coordinates, or None if none is present or in range.

        Matches by world tile coordinate rather than name, so a same-named
        but differently-positioned object elsewhere in the scene cannot
        interfere.
        """
        for obj in game.objects:
            if (obj.get("worldX") == target_x
                    and obj.get("worldY") == target_y
                    and obj.get("minimapX") is not None
                    and obj.get("minimapY") is not None):
                return obj
        return None

    def _synthetic_minimap_entity(
        self,
        game: "GameState",
        target_x: int,
        target_y: int,
    ) -> Optional[dict]:
        """Build a fake entity dict with minimapX/minimapY pointing at the
        given world tile.

        Assumes a ~20-tile minimap radius and that canvas Y decreases going
        north (higher worldY = up = lower canvasY). The result is clamped to
        90% of the minimap circle's radius so the click stays within the
        interactive area.
        """
        minimap = game.interfaces_for_group(self.MINIMAP_GROUP)
        if not minimap:
            return None

        widget = max(minimap, key=lambda w: w["bounds"]["width"] * w["bounds"]["height"])
        b = widget["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        half_extent = min(b["width"], b["height"]) / 2

        px, py = game.player_pos
        dx = target_x - px
        dy = target_y - py

        pixels_per_tile = half_extent / 20.0
        mx = cx + dx * pixels_per_tile
        my = cy - dy * pixels_per_tile  # canvas Y: up = north = decreasing

        dist = math.sqrt((mx - cx) ** 2 + (my - cy) ** 2)
        cap = half_extent * 0.9
        if dist > cap:
            scale = cap / dist
            mx = cx + (mx - cx) * scale
            my = cy + (my - cy) * scale

        return {"name": "waypoint", "minimapX": mx, "minimapY": my}
