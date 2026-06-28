"""
Rod-fishing at Barbarian Village — Fish, Cook, Bank routine.

Catches Trout/Salmon at a Rod Fishing Spot south of Barbarian Village,
cooks two batches over a nearby Fire, banks the cooked fish at the
Barbarian Village bank booth, and repeats.

Travel between the bank and the fishing spot follows a recorded path
(BANK_FISHING_PATH — an actual walked route, see `regions.Path`) rather than
clicking random points inside hand-drawn region polygons:
`InteractionRoutine.travel_path` walks the player along it one tick at a
time, forward toward the fishing spot or `reverse=True` back toward the
bank. BANK_REGION/LOWER_EDGEVILLE/UPPER_BARBARIAN_VILLAGE/FISHING_REGION and
ROUTE (a `RegionRoute` chaining them) are kept only as coarse landmarks for
sanity-checking the recorded path's endpoints (see `TestRegionDefinitions`
in test_rod_fishing.py) — they no longer drive travel directly. CONTAINER_REGION
still defines the routine's whole operating area: if the player is ever
found outside it the routine stops itself rather than wandering further
off-route.

State flow
──────────

  resume (entry point — picks up wherever the player/inventory are)
    → inventory full, raw fish left to cook                       → cooking
    → inventory full, nothing left to cook                        → travelling (dest BANK_REGION) → banking
    → inventory not full                                          → travelling (dest FISHING_REGION) → find_spot

  travelling         → (player inside the destination region)     → arrival state (find_spot / banking)

  banking           → (inventory clear)                          → travelling (dest FISHING_REGION)
  banking           → (cooked fish: deposits, closes bank)        → travelling (dest FISHING_REGION)

  find_spot         → (left-clicks Rod Fishing Spot)               → fishing
  fishing           → (inventory full)                             → cooking

  cooking           → (batch 1 done, no raw fish)                  → drop_burnt
  drop_burnt        → (burnt fish cleared)                         → find_spot

  fishing (batch 2) → (inventory full)                              → cooking
  cooking           → (batch 2 done, no raw fish)                   → drop_and_return
  drop_and_return   → (raw + burnt cleared, cooked fish kept)        → travelling (dest BANK_REGION)

  (any state)        → (player outside CONTAINER_REGION)            → stopped (terminal — releases keys, logs once)

How to use
──────────
    from scripts.gamebridge.routines.examples.rod_fishing import RodFishingRoutine
    engine.set_routine(RodFishingRoutine())

Requirements
────────────
- objectFilter must include "Fern", "Tree", "Fire", "Bank booth"
  OR sendAllNamedObjects=true.
- exposeNpcs=true (default) — for "Rod Fishing Spot".
- exposeInterfaces=true (default) — for cooking dialog (G270:38), bank, and
  the minimap widget (group 160) used by `InteractionRoutine.synthetic_minimap_entity`.
- exposeCamera=true (default) — for camera.yawTarget/minimapZoom, used by
  the same minimap-waypoint helper so clicks stay accurate regardless of
  compass rotation or minimap zoom level.
- exposeWidgets=true — for inventory drop (shift-click).
- A fly fishing rod and feathers must be in the inventory or equipped.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from ..base import initial_state
from ..interaction import InteractionRoutine
from ...input.keyboard import Key
from ... import item_ids
from ...regions import Path, Region, RegionRoute

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)

# Regions between the Barbarian Village bank and the rod fishing spot,
# chained south-to-north (decreasing world Y) into the route the player
# commutes back and forth along. Coordinates are world tile (x, y); plane
# is always 0 for this route.
BANK_REGION = Region("BANK_REGION", (
    (3088, 3500), (3087, 3485), (3101, 3483), (3101, 3501),
))

LOWER_EDGEVILLE = Region("LOWER_EDGEVILLE", (
    (3099, 3471), (3095, 3472), (3079, 3471), (3083, 3457), (3099, 3460),
))

UPPER_BARBARIAN_VILLAGE = Region("UPPER_BARBARIAN_VILLAGE", (
    (3104, 3436), (3098, 3448), (3084, 3449), (3097, 3435),
))

FISHING_REGION = Region("FISHING_REGION", (
    (3104, 3435), (3100, 3434), (3100, 3422), (3104, 3423), (3110, 3433), (3109, 3437),
))

# The routine's whole operating area. If the player is ever found outside
# this, the routine stops itself (see RodFishingRoutine.tick / `stopped`).
CONTAINER_REGION = Region("CONTAINER_REGION", (
    (3105, 3505), (3082, 3504), (3076, 3470), (3081, 3445), (3092, 3413),
    (3108, 3411), (3105, 3421), (3109, 3428), (3113, 3433), (3106, 3440),
    (3103, 3449), (3102, 3465), (3105, 3480), (3108, 3487),
))

ROUTE = RegionRoute((BANK_REGION, LOWER_EDGEVILLE, UPPER_BARBARIAN_VILLAGE, FISHING_REGION))

# Raw recorded walk from the bank booth to the fishing spot (bank end
# first), worldX/worldY/plane triples — plane is always 0 along this route.
# `Path.from_recording` collapses the consecutive-duplicate points (the
# player paused) below into a clean waypoint list.
_BANK_FISHING_RAW_POINTS = (
    (3090, 3489, 0), (3090, 3489, 0), (3090, 3488, 0), (3090, 3487, 0),
    (3091, 3486, 0), (3092, 3485, 0), (3093, 3484, 0), (3094, 3483, 0),
    (3095, 3483, 0), (3096, 3483, 0), (3097, 3483, 0), (3098, 3483, 0),
    (3099, 3482, 0), (3100, 3481, 0), (3100, 3481, 0), (3100, 3480, 0),
    (3100, 3479, 0), (3100, 3478, 0), (3099, 3477, 0), (3099, 3476, 0),
    (3099, 3475, 0), (3099, 3474, 0), (3099, 3473, 0), (3099, 3472, 0),
    (3099, 3471, 0), (3099, 3470, 0), (3099, 3469, 0), (3099, 3468, 0),
    (3099, 3467, 0), (3099, 3466, 0), (3099, 3465, 0), (3099, 3464, 0),
    (3099, 3464, 0), (3098, 3464, 0), (3097, 3464, 0), (3096, 3464, 0),
    (3095, 3464, 0), (3094, 3464, 0), (3093, 3464, 0), (3092, 3464, 0),
    (3091, 3464, 0), (3090, 3464, 0), (3089, 3464, 0), (3088, 3464, 0),
    (3088, 3463, 0), (3088, 3462, 0), (3088, 3461, 0), (3088, 3460, 0),
    (3088, 3459, 0), (3088, 3458, 0), (3088, 3457, 0), (3088, 3456, 0),
    (3089, 3456, 0), (3089, 3455, 0), (3089, 3454, 0), (3089, 3453, 0),
    (3090, 3452, 0), (3090, 3451, 0), (3091, 3450, 0), (3091, 3449, 0),
    (3091, 3448, 0), (3091, 3447, 0), (3091, 3446, 0), (3091, 3445, 0),
    (3092, 3444, 0), (3093, 3443, 0), (3093, 3442, 0), (3093, 3441, 0),
    (3093, 3440, 0), (3094, 3439, 0), (3095, 3438, 0), (3096, 3437, 0),
    (3097, 3436, 0), (3098, 3435, 0), (3099, 3435, 0), (3100, 3434, 0),
    (3101, 3433, 0), (3102, 3433, 0), (3103, 3433, 0), (3104, 3433, 0),
    (3104, 3432, 0), (3104, 3431, 0),
)

BANK_FISHING_PATH = Path.from_recording("BANK_FISHING_PATH", _BANK_FISHING_RAW_POINTS)


class RodFishingRoutine(InteractionRoutine):
    """Fish, cook two batches, bank at Barbarian Village, repeat."""

    # Entity names
    FISHING_SPOT_NAME = "Rod Fishing Spot"
    FIRE_NAME         = "Fire"
    BANK_BOOTH_NAME   = "Bank booth"

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

    # Region route between the bank and the fishing spot — kept only for
    # coarse sanity-checking (TestRegionDefinitions); travel itself uses
    # BANK_FISHING_PATH below.
    ROUTE = ROUTE
    CONTAINER_REGION = CONTAINER_REGION

    # Recorded walk between the bank and the fishing spot.
    BANK_FISHING_PATH = BANK_FISHING_PATH

    # Cooking dialog: G270:38 — "How many would you like to cook?"
    COOK_WIDGET = (270, 38)

    # Tuning constants
    FIRE_SEARCH_RADIUS        = 12    # tiles — look for a Fire within this distance
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
        self._travel_reverse: bool = False
        self._arrival_state: Optional[str] = None
        self._stopped_reason: Optional[str] = None

    # ------------------------------------------------------------------
    # Safety exit
    # ------------------------------------------------------------------

    def tick(self, game: "GameState", ctrl: "GameController") -> None:
        """Before dispatching to the current state, check the player hasn't
        wandered outside CONTAINER_REGION — if so, jump straight to the
        terminal `stopped` state instead of letting whatever state we were
        in keep clicking against a route that no longer makes sense."""
        if self._current != "stopped" and self.outside_container(game, self.CONTAINER_REGION):
            self._stopped_reason = f"player left CONTAINER_REGION at {game.player_pos}"
            log.critical("[%s] %s — stopping routine", self.name, self._stopped_reason)
            ctrl.release_all_keys()
            self._previous = self._current
            self._current = "stopped"
            self._state_enter_tick = game.tick
        super().tick(game, ctrl)

    def stopped(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Terminal state — the routine takes no further action until it is
        reset or swapped out from the dashboard."""
        return None

    def _travel_to(self, reverse: bool, arrival_state: str) -> str:
        self._travel_reverse = reverse
        self._arrival_state = arrival_state
        return "travelling"

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

        Path-based travel means resuming doesn't need to pick a specific leg
        by distance thresholds the way the old Fern/Tree waypoints did —
        `travel_path` figures out the nearest waypoint to wherever the
        player already is and walks from there.
        """
        log.info("Resuming from %s with inventory %s", game.player_pos, game.inventory)
        if game.inventory_full():
            if self._next_raw_fish(game) is not None:
                log.info("Raw fish left to cook — resuming toward cooking")
                return "cooking"
            log.info("Inventory full — resuming toward bank")
            return self._travel_to(True, "banking")
        log.info("Inventory not full — resuming toward fishing spot")
        return self._travel_to(False, "find_spot")

    def travelling(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Step along BANK_FISHING_PATH toward whichever end self._travel_reverse selects."""
        if self.travel_path(game, ctrl, self.BANK_FISHING_PATH, reverse=self._travel_reverse):
            return self._arrival_state
        return None

    def banking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Deposit all fish at the bank booth, then head back to the fishing spot."""
        has_bankable = any(game.inventory_has_item(i) for i in self.BANKABLE_IDS)

        if not has_bankable:
            if game.is_interface_open("bank"):
                ctrl.press_key(Key.ESCAPE)
                return None
            self._batches_cooked = 0
            return self._travel_to(False, "find_spot")

        if not self.open_bank(game, ctrl, self.BANK_BOOTH_NAME, self.BANK_OPEN_GRACE_TICKS):
            return None

        self.deposit_inventory(game, ctrl, self.DEPOSIT_THROTTLE_TICKS)
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
        then head back to the bank."""
        if self.drop_items_shift_click(game, ctrl, self.DROP_ALL_IDS):
            return None
        return self._travel_to(True, "banking")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
