"""
Fish & Cook routine.

Nets shrimp/anchovies at a fishing spot, then heads off to cook the catch
once the inventory fills up — using any `Fire` already standing within
`FIRE_SEARCH_RADIUS` tiles, or lighting a fresh one with logs and a
tinderbox if none is found. Drops the results, then goes back to fishing.
Stops outright if it ever runs out of logs — without them it can't make a
fire and the loop can't continue.

State flow
──────────

  find_spot    → (spot netted)                          → fishing
  fishing      → (inventory full, no logs)              → stopped
  fishing      → (inventory full, has logs)             → find_fire

  find_fire    → (Fire within FIRE_SEARCH_RADIUS tiles) → cooking
  find_fire    → (no Fire nearby)                       → step_aside

  step_aside   → (settled on a fresh tile)              → light_fire
  light_fire   → (logs + tinderbox combined)            → confirm_fire
  confirm_fire → (Fire spawned and confirmed nearby)    → cooking
  confirm_fire → (xp timeout / no Fire appeared)        → step_aside

  cooking      → (raw fish remain, but the Fire is      → find_fire
                  gone — fires can despawn mid-batch)
  cooking      → (no raw fish left)                     → dropping

  dropping     → (nothing left to drop)                 → find_spot

How to use
──────────
    from scripts.gamebridge.routines.examples.fish_and_cook import FishAndCookRoutine

    engine.set_routine(FishAndCookRoutine())

Requires `Fishing spot` (NPC) and `Fire` (object) to be visible to the
bridge — make sure the plugin's NPC/object filters include them (see
ARCHITECTURE.md, "Object list performance — restrict by filter").
"""
from __future__ import annotations

import logging
import math
import random
from typing import Optional, TYPE_CHECKING

from ..base import initial_state
from ..interaction import InteractionRoutine, MenuClick
from ...input.keyboard import Key

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class FishAndCookRoutine(InteractionRoutine):
    """Net-fish shrimp/anchovies, fire them up, cook, drop, repeat."""

    FISHING_SPOT_NAME = "Fishing spot"
    FIRE_NAME = "Fire"
    MINIMAP_GROUP = 160
    INVENTORY_GROUP = 149

    TINDERBOX_ID     = 590
    LOGS_ID          = 1511
    RAW_SHRIMP_ID    = 317
    COOKED_SHRIMP_ID = 315
    RAW_ANCHOVIES_ID = 321
    ANCHOVIES_ID     = 319
    BURNT_FISH_ID    = 7954  # generic "Burnt fish" — shared by burnt shrimp AND burnt anchovies

    DROP_ITEM_IDS = (COOKED_SHRIMP_ID, ANCHOVIES_ID, BURNT_FISH_ID)

    COOK_WIDGET = (270, 38)  # Skillmulti — "How many would you like to cook?" dialog

    FIRE_SEARCH_RADIUS = 10  # tiles — reuse a Fire already standing this close instead of lighting our own

    FISHING_IDLE_TIMEOUT_TICKS  = 6    # ticks of idleness before assuming netting stopped — re-click
    STEP_ASIDE_MIN_TICKS        = 2    # ticks to let a minimap walk begin before checking idle
    FIREMAKING_XP_TIMEOUT_TICKS = 20   # max ticks to wait for a firemaking xp drop before assuming the click missed —
                                       # generous: a too-tight timeout misjudges slow-but-real successes as failures,
                                       # and each "retry" after a real success burns another log on a fire we abandon
    FIREMAKING_SETTLE_TICKS     = 4   # extra ticks to wait after the xp drop before checking for a fire (per spec)
    COOKING_GESTURE_TICKS       = 3   # min ticks between "use fish on fire" gestures — lets the dialog/animation begin

    RANDOM_STEP_MIN_RATIO = 0.10  # fraction of the minimap's half-extent to step away — keeps clicks inside the circle
    RANDOM_STEP_MAX_RATIO = 0.20

    def __init__(self) -> None:
        super().__init__()
        self._spot_index: Optional[int] = None
        self._spot_target: Optional[dict] = None
        self._fish_start_tick: int = -99

        self._step_clicked_tick: Optional[int] = None

        self._used_logs: bool = False
        self._fire_attempt_tick: Optional[int] = None

        self._cook_selected: bool = False
        self._cook_started_tick: Optional[int] = None

        self._drop_target: Optional[dict] = None

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def find_spot(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Locate the nearest Fishing spot and start netting it.

        Targeting follows the same "verify before you click" pattern as
        `MeleeFighterRoutine.find_target`: right-click the spot, confirm a
        "Net Fishing spot" entry is actually in the menu (a spot can also
        offer "Bait"/"Cage"/"Harpoon" entries depending on location), then
        click that exact row.
        """
        if game.inventory_full():
            if not game.inventory_has_item(self.LOGS_ID):
                log.info("Inventory full and no logs to cook with — stopping.")
                return "stopped"
            return "find_fire"

        if self._spot_target is not None:
            outcome = self.verified_menu_click(game, ctrl, "Net", self.FISHING_SPOT_NAME)

            if outcome is MenuClick.CONFIRMED:
                self._spot_index = self._spot_target.get("index")
                self._fish_start_tick = game.tick
                self._spot_target = None
                return "fishing"

            if outcome is MenuClick.ABANDONED:
                self._spot_target = None

            return None

        spot = game.nearest_npc(self.FISHING_SPOT_NAME)

        if spot is None:
            log.debug("No %s in scene, waiting…", self.FISHING_SPOT_NAME)
            return None

        if not self.approach(game, ctrl, spot):
            return None

        ctrl.right_click_entity(spot)
        self._spot_target = spot
        return None

    def fishing(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait while the player nets shrimp/anchovies, tracking the spot by its
        unique world index (its composition id is shared by every spot of the
        same type — see `MeleeFighterRoutine.fighting` for the same concern
        with Goblins). Re-clicks if the spot wanders off, or if the player
        goes idle for `FISHING_IDLE_TIMEOUT_TICKS` without the inventory
        being full (the spot moved out of range mid-action and netting
        silently stopped). Moves on to finding a fire (existing or new)
        once the inventory fills.
        """
        if game.inventory_full():
            if not game.inventory_has_item(self.LOGS_ID):
                log.info("Inventory full and no logs to cook with — stopping.")
                return "stopped"
            return "find_fire"

        live_spot = next((n for n in game.npcs if n.get("index") == self._spot_index), None)

        if live_spot is None:
            log.debug("%s wandered off — re-targeting", self.FISHING_SPOT_NAME)
            return "find_spot"

        if game.player_idle():
            if game.tick - self._fish_start_tick >= self.FISHING_IDLE_TIMEOUT_TICKS:
                log.debug("Stopped netting — re-clicking %s", self.FISHING_SPOT_NAME)
                return "find_spot"
        else:
            self._fish_start_tick = game.tick

        return None

    def find_fire(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Look for a `Fire` already standing within `FIRE_SEARCH_RADIUS` tiles
        before lighting our own — saves a log and avoids littering the area
        with abandoned fires. Walks over to the nearest one in range (same
        "approach, then click to walk" shape as `IronMiningRoutine.walk_to_bank`)
        and starts cooking once adjacent; falls back to `step_aside` to light
        a fresh one if nothing is in range.
        """
        fire = self._nearest_fire_in_range(game)

        if fire is None:
            return "step_aside"

        if game.player_near(fire, tiles=1):
            return "cooking"

        if not self.approach(game, ctrl, fire):
            return None

        ctrl.click_entity(fire)
        return None

    def step_aside(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Walk a few random tiles away before lighting a fire — clears the
        fishing spot's tile and any earlier failed-fire debris, and varies
        where fires get lit run to run. Issues exactly one minimap-walk
        gesture (tracked across ticks — see `_walk_to_random_nearby_tile`)
        and waits for the player to settle before moving on.
        """
        if self._step_clicked_tick is None:
            if self._walk_to_random_nearby_tile(game, ctrl):
                self._step_clicked_tick = game.tick
            return None

        if (game.tick - self._step_clicked_tick >= self.STEP_ASIDE_MIN_TICKS
                and game.player_idle()):
            self._step_clicked_tick = None
            return "light_fire"

        return None

    def light_fire(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Use a log on the tinderbox to light a fire on the current tile.
        Both are inventory items — selecting one ("Use Logs"), then clicking
        the other to complete the combination, needs the gesture spread
        across two ticks (`_used_logs`), the same shape `IronMiningRoutine`
        uses to space its click-then-verify steps.
        """
        if not game.inventory_has_item(self.LOGS_ID):
            log.info("Ran out of logs — stopping.")
            return "stopped"

        if not self._used_logs:
            if self._click_inventory_item(game, ctrl, self.LOGS_ID):
                self._used_logs = True
            return None

        if self._click_inventory_item(game, ctrl, self.TINDERBOX_ID):
            self._used_logs = False
            self._fire_attempt_tick = game.tick
            return "confirm_fire"

        return None

    def confirm_fire(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Wait for the firemaking XP drop, then `FIREMAKING_SETTLE_TICKS` more
        ticks (per spec — gives the fire object time to actually spawn after
        the animation completes), then check whether a `Fire` appeared next
        to the player. Falls back to `step_aside` — a fresh tile and a fresh
        attempt — on either a timed-out XP drop (the "use" gesture missed)
        or no fire materialising (the tile was unsuitable).
        """
        xp_tick = game.last_xp_tick.get("FIREMAKING", -1)

        if xp_tick < self._fire_attempt_tick:
            if game.tick - self._fire_attempt_tick >= self.FIREMAKING_XP_TIMEOUT_TICKS:
                log.debug("No firemaking xp — fire attempt missed, trying another tile")
                self._fire_attempt_tick = None
                return "step_aside"
            return None

        if game.tick - xp_tick < self.FIREMAKING_SETTLE_TICKS:
            return None

        self._fire_attempt_tick = None
        fire = game.nearest_object_on_screen(self.FIRE_NAME)

        if fire is not None and game.player_near(fire, tiles=1):
            return "cooking"

        log.debug("No fire appeared nearby — trying another tile")
        return "step_aside"

    def cooking(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Use each raw fish type on the fire in turn. One "use on fire"
        gesture opens the "How many would you like to cook?" dialog
        (Skillmulti, G270:38); pressing Space confirms its highlighted
        "Cook all" option, and the game auto-cooks the entire stack of that
        type — so one gesture per fish type already in the inventory is
        enough. Moves on to dropping once neither raw shrimp nor raw
        anchovies remain.

        A fire can despawn mid-batch and strand us with raw fish selected
        and nothing to click it onto — caught the moment we go looking for
        it to complete the gesture (on screen and gone, player settled back
        to idle), sending us back to `find_fire` for another one.
        """
        raw_id = self._next_raw_fish(game)

        if raw_id is None:
            self._cook_selected = False
            self._cook_started_tick = None
            return "dropping"

        cook_widget = game.find_interface_widget(*self.COOK_WIDGET)

        if cook_widget is not None:
            ctrl.press_key(Key.SPACE)
            self._cook_selected = False
            self._cook_started_tick = game.tick
            return None

        if self._cook_selected:
            fire = game.nearest_object_on_screen(self.FIRE_NAME)

            if fire is not None:
                ctrl.click_entity(fire)
                self._cook_selected = False
                self._cook_started_tick = game.tick
                return None

            if game.player_idle():
                log.debug("Fire vanished mid-cook with raw fish remaining — finding another")
                self._cook_selected = False
                self._cook_started_tick = None
                return "find_fire"

            return None

        if self._cook_started_tick is not None:
            # A gesture is in flight — wait for the dialog (handled above) or
            # for the current cook-all batch to finish (player goes idle)
            # before starting a fresh "use fish on fire" gesture.
            if (not game.player_idle()
                    or game.tick - self._cook_started_tick < self.COOKING_GESTURE_TICKS):
                return None
            self._cook_started_tick = None

        if self._click_inventory_item(game, ctrl, raw_id):
            self._cook_selected = True

        return None

    def dropping(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """
        Right-click and drop every cooked and burnt fish, one at a time.
        Same "verify before you click" shape as `MeleeFighterRoutine.looting`
        — a blind left-click on food eats it rather than dropping it, so the
        "Drop" entry is read back from the menu before it's clicked. Heads
        back to fishing once nothing matching `DROP_ITEM_IDS` remains.
        """
        if self._drop_target is not None:
            outcome = self.verified_menu_click(game, ctrl, "Drop", None)

            if outcome is not MenuClick.PENDING:
                self._drop_target = None

            return None

        widget = next(
            (w for w in game.widgets
             if w.get("groupId") == self.INVENTORY_GROUP and w.get("itemId") in self.DROP_ITEM_IDS),
            None,
        )

        if widget is None:
            return "find_spot"

        ctrl.right_click_widget(widget)
        self._drop_target = widget
        return None

    def stopped(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Terminal state — out of logs, so no more fires can be lit. The routine halts here."""
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _nearest_fire_in_range(self, game: "GameState") -> Optional[dict]:
        """Nearest `Fire` within `FIRE_SEARCH_RADIUS` tiles of the player, or None."""
        return min(
            (o for o in game.objects_named(self.FIRE_NAME) if game.distance_to(o) <= self.FIRE_SEARCH_RADIUS),
            key=game.distance_to,
            default=None,
        )

    def _next_raw_fish(self, game: "GameState") -> Optional[int]:
        """The next raw-fish item id to cook, or None if neither remains."""
        if game.inventory_has_item(self.RAW_SHRIMP_ID):
            return self.RAW_SHRIMP_ID
        if game.inventory_has_item(self.RAW_ANCHOVIES_ID):
            return self.RAW_ANCHOVIES_ID
        return None

    def _click_inventory_item(self, game: "GameState", ctrl: "GameController", item_id: int) -> bool:
        """Left-click the first inventory slot holding `item_id` (selects it for "Use")."""
        for w in game.widgets:
            if w.get("groupId") == self.INVENTORY_GROUP and w.get("itemId") == item_id:
                ctrl.click_widget(w)
                return True
        return False

    def _walk_to_random_nearby_tile(self, game: "GameState", ctrl: "GameController") -> bool:
        """
        Click a random point near the centre of the minimap — always the
        player's own position — to step a few tiles in a random direction.

        Hands the synthetic point to `click_minimap_entity` as a fake
        "entity" carrying `minimapX`/`minimapY` so its existing walk
        tracking (start-up grace period, idle-settle, timeout — see
        `Controller._minimap_walk_in_progress`) gets reused; that function
        only reads those two fields plus `name` for logging.
        """
        minimap = game.interfaces_for_group(self.MINIMAP_GROUP)

        if not minimap:
            return False

        widget = max(minimap, key=lambda w: w["bounds"]["width"] * w["bounds"]["height"])
        b = widget["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        half_extent = min(b["width"], b["height"]) / 2
        radius = random.uniform(self.RANDOM_STEP_MIN_RATIO, self.RANDOM_STEP_MAX_RATIO) * half_extent
        angle = random.uniform(0, 2 * math.pi)

        target = {
            "name": "random nearby tile",
            "minimapX": cx + radius * math.cos(angle),
            "minimapY": cy + radius * math.sin(angle),
        }
        return ctrl.click_minimap_entity(target, game)
