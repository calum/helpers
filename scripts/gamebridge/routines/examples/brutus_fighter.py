"""
Brutus Fighter routine.

Brutus is a 3x3 aggressive melee NPC (ids 15626/15627) that, after every
4-5 basic attacks, telegraphs one of two special attacks with a distinct
animation a few ticks before it actually lands:

  - "Charge" (telegraph: *growls*)
  - "Slam"   (telegraph: *snorts*, repeated 3 times)

Both specials ignore protection prayers but can be fully avoided by moving
off the tile before the attack resolves. The telegraph animation IDs below
(13785, 13778) were read directly off a recorded fight (see
~/.gamebridge/recordings/recording-20260628-152254.jsonl) by diffing
Brutus's per-tick `animation` field against player HP loss: 13783 is his
basic melee swing (correlates with -1..-3 HP most ticks it fires), while
13785/13778 never correlate with any HP loss in that recording — the player
was dodging them, matching the in-game special-attack tells.

State diagram
─────────────

  ┌──────────────┐
  │ find_target  │◄─────────────────────────────────────┐
  └──────┬───────┘                                      │
         │ NPC clicked                                  │
         ▼                                              │
  ┌──────────────┐   special telegraphed    ┌──────────┐│
  │   fighting   │──────────────────────────►│ dodging  ││
  └──────┬───────┘◄──────────────────────────└──────────┘│
         │ NPC vanished — assume dead                    │
         ▼                                               │
  ┌──────────────┐                                       │
  │   looting    │───────────────────────────────────────┘
  └──────────────┘

`healing` is reachable from find_target/fighting/dodging/looting whenever
HP drops to/below HEAL_HP_THRESHOLD and food remains, returning to whichever
state it interrupted.

This routine declares itself "high-attention" (ATTENTION_LEVEL = "combat",
applied every tick via GameController.set_attention_level) — Brutus aggros
instantly and his specials only give a 3-4 tick window to dodge, so every
click here uses HumanEmulator's faster combat reflex/movement multipliers
instead of the default relaxed-skilling pacing. All clicks happen directly
in the game viewport; the dodge step in particular never reaches for the
minimap, since no human would for a one-tile sidestep.

How to use
──────────
    from scripts.gamebridge.routines.examples.brutus_fighter import BrutusFighterRoutine

    engine.set_routine(BrutusFighterRoutine())
"""
from __future__ import annotations

import logging
from typing import Optional, Set, Tuple, TYPE_CHECKING

from ... import item_ids
from ..base import initial_state
from ..interaction import InteractionRoutine, OCCLUSION_NUDGE_YAW
from ...input.keyboard import Key

if TYPE_CHECKING:
    from ...state.game_state import GameState
    from ...controller.controller import GameController

log = logging.getLogger(__name__)


class BrutusFighterRoutine(InteractionRoutine):
    """Fight Brutus, dodging his telegraphed specials, healing on low HP,
    and looting his drops with a plain left-click once he dies."""

    NPC_NAME = "Brutus"

    # Declares this routine "high-attention" — see HumanEmulator.set_attention_level.
    # Set every tick from every state (cheap, idempotent): Brutus can punish
    # a slow reaction anywhere near him, not just mid-swing, so there's no
    # "safe" state to relax the reflex model in.
    ATTENTION_LEVEL = "combat"

    # Persistent subscription kept alive for the whole fight (renewed every
    # tick from every combat-adjacent state) so Brutus's clickbox/coordinates
    # stay accurate even between attack-click gestures — separate from
    # InteractionRoutine.LIVE_HULL_SUB_ID, which only tracks whatever is
    # about to be clicked right now (the attack target or a loot item).
    BRUTUS_SUB_ID = "brutus"
    BRUTUS_SUB_TTL_TICKS = 10

    # Reused for every dodge — re-subscribing with the same subId just
    # renews it, no need to unsubscribe between dodges. Short TTL since it's
    # only ever needed for the few ticks around a single dodge gesture.
    DODGE_TILE_SUB_ID = "brutus_dodge_tile"
    DODGE_TILE_SUB_TTL_TICKS = 5

    # Telegraph animation IDs for Brutus's two specials — see module docstring.
    BASIC_ATTACK_ANIM = 13783
    SPECIAL_TELL_ANIMS = frozenset({13785, 13778})

    # How long (ticks) to wait after issuing the dodge-tile click before
    # re-engaging — both specials' windows are 3-4 ticks; this just needs to
    # clear the player from the danger tile before stepping back in.
    DODGE_WAIT_TICKS = 3

    MISCLICK_TIMEOUT_TICKS = 10
    COMBAT_XP_SKILLS = ("ATTACK", "STRENGTH", "DEFENCE", "HITPOINTS")

    LOOT_WINDOW_TICKS = 5

    HEAL_HP_THRESHOLD = 6
    FOOD_ITEM_IDS = (item_ids.COOKED_TROUT, item_ids.COOKED_SALMON)
    EAT_COOLDOWN_TICKS = 3  # roughly OSRS's own eat-delay — avoid spamming the slot every tick

    def __init__(self):
        super().__init__()
        self._target_index: Optional[int] = None
        self._target: Optional[dict] = None
        self._target_pos: Optional[Tuple[int, int]] = None
        self._death_tick: Optional[int] = None
        self._looted_keys: Set[Tuple[int, int, int]] = set()
        self._fight_start_tick: Optional[int] = None
        self._attack_target: Optional[dict] = None
        self._loot_target: Optional[dict] = None
        self._dodge_clicked: bool = False
        self._dodge_tick: int = -1
        self._return_state: str = "find_target"
        self._last_eat_tick: int = -99

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------

    @initial_state
    def find_target(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Register Brutus's live clickbox subscription up front, then find
        him and engage with a single fast left-click the moment he's visible
        and unobstructed.

        Deliberately skips InteractionRoutine.approach()'s idle-settle
        buffer and the verify-before-click right-click/menu gesture both use
        elsewhere in this codebase: those add whole extra ticks of pure
        waiting (camera settle, then a tick for the menu to open, then a
        tick to click the row) before the very first attack ever lands —
        fine for a stationary rock or tree, fatal against an instantly
        aggressive boss. Brutus is the only "Brutus" in his arena, so there's
        no ambiguous target to verify a menu against; click_live's tooltip
        check already confirms the cursor is over him before the click
        commits, which is enough.
        """
        self._renew_brutus_subscription(ctrl)
        ctrl.set_attention_level(self.ATTENTION_LEVEL)

        if self._needs_heal(game):
            self._return_state = "find_target"
            return "healing"

        target = game.nearest_npc(self.NPC_NAME)
        if target is None:
            log.debug("Brutus not in scene — waiting for respawn")
            return None

        if not ctrl.bring_entity_on_screen(target, game):
            return None

        if game.is_occluded(target["canvasX"], target["canvasY"]):
            ctrl.rotate_camera(Key.RIGHT, OCCLUSION_NUDGE_YAW)
            return None

        if self.click_live(ctrl, target, "npc"):
            self._target_index = target["index"]
            self._target = target
            self._fight_start_tick = game.tick
            return "fighting"

        return None

    def fighting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Keep fighting Brutus, watching for the special-attack telegraph
        and miss-clicks, same shape as MeleeFighterRoutine.fighting().

        The dodge click is fired right here, the instant the telegraph is
        seen — not deferred to the first tick of the "dodging" state. A
        Routine only re-evaluates its *current* state method once per tick
        (see base.py); returning "dodging" without acting first would waste
        a full ~600ms tick doing nothing before the dodge click could go
        out, eating into the 3-4 tick window the telegraph gives us.
        """
        self._renew_brutus_subscription(ctrl)
        ctrl.set_attention_level(self.ATTENTION_LEVEL)

        if self._needs_heal(game):
            self._return_state = "fighting"
            return "healing"

        live_target = next((n for n in game.npcs if n.get("index") == self._target_index), None)

        if live_target is None:
            self._target_pos = (self._target["worldX"], self._target["worldY"])
            log.debug("Brutus (index=%d) is gone — assuming it died at %s",
                      self._target_index, self._target_pos)
            self._death_tick = game.tick
            self._looted_keys.clear()
            return "looting"

        self._target = live_target

        if live_target.get("animation") in self.SPECIAL_TELL_ANIMS:
            log.debug("Brutus telegraphing a special (anim=%d) — dodging now", live_target["animation"])
            tile = self._compute_dodge_tile(game, ctrl, live_target)
            self._click_dodge_tile(game, ctrl, tile)
            self._dodge_clicked = True
            self._dodge_tick = game.tick
            return "fighting"
        
        if self._dodge_clicked and (game.tick - self._dodge_tick < self.DODGE_WAIT_TICKS):
            return None

        if self._dodge_clicked and self.click_live(ctrl, live_target, "npc"):
            self._dodge_clicked = False
            return "fighting"

        got_xp_drop = any(
            game.last_xp_tick.get(skill, -1) >= self._fight_start_tick
            for skill in self.COMBAT_XP_SKILLS
        )
        ticks_since_click = game.tick - self._fight_start_tick

        if not got_xp_drop and ticks_since_click > self.MISCLICK_TIMEOUT_TICKS:
            log.debug("No combat xp within %d ticks of attacking Brutus — assuming a "
                      "miss-click, re-targeting", ticks_since_click)
            return "find_target"

        return None

    def healing(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Eat one food item and resume whatever state was interrupted.
        If HP is still low next tick, this state is re-entered and eats
        again — mirrors a player eating repeatedly while taking damage."""
        ctrl.set_attention_level(self.ATTENTION_LEVEL)

        if game.tick - self._last_eat_tick >= self.EAT_COOLDOWN_TICKS:
            for food_id in self.FOOD_ITEM_IDS:
                if game.inventory_has_item(food_id) and self.click_inventory_item(game, ctrl, food_id):
                    self._last_eat_tick = game.tick
                    break

        return self._return_state

    def looting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Plain left-click looting (no menu verification, per requirement)
        across Brutus's whole 3x3 corpse footprint."""
        ctrl.set_attention_level(self.ATTENTION_LEVEL)

        if self._needs_heal(game):
            self._return_state = "looting"
            return "healing"

        sw_x, sw_y = self._target_pos
        items = self._ground_items_in_footprint(game, sw_x, sw_y)

        log.debug("Watching for loot in Brutus's footprint at SW (%d, %d): %s", sw_x, sw_y, items)

        if self._loot_target is not None:
            self._looted_keys.add(self._loot_key(self._loot_target))
            self._loot_target = None
            return None

        if game.player_idle():
            for item in items:
                key = self._loot_key(item)
                if key in self._looted_keys:
                    continue
                if not item.get("onScreen"):
                    continue  # wait for it to come into view before attempting

                if self.click_live(ctrl, item, "groundItem"):
                    self._loot_target = item
                return None  # one pickup gesture at a time

        if game.tick - self._death_tick >= self.LOOT_WINDOW_TICKS:
            return "find_target"

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _renew_brutus_subscription(self, ctrl: "GameController") -> None:
        """Keep a live clickbox subscription on Brutus alive for the whole
        fight, independent of whatever's currently being clicked — see
        BRUTUS_SUB_ID."""
        ctrl.subscribe_to(self.BRUTUS_SUB_ID, "npc", name=self.NPC_NAME, ttl_ticks=self.BRUTUS_SUB_TTL_TICKS)

    def _needs_heal(self, game: "GameState") -> bool:
        return game.player_hp() <= self.HEAL_HP_THRESHOLD and any(
            game.inventory_has_item(food_id) for food_id in self.FOOD_ITEM_IDS
        )

    def _loot_key(self, item: dict) -> Tuple[int, int, int]:
        return (item["id"], item["worldX"], item["worldY"])

    def _ground_items_in_footprint(self, game: "GameState", sw_x: int, sw_y: int) -> list:
        """Ground items anywhere within Brutus's 3x3 footprint, whose
        south-west tile is (sw_x, sw_y) — drops can land on any of his nine
        tiles, not just the south-west corner."""
        return [
            item for item in game.ground_items
            if sw_x <= item.get("worldX", -1) <= sw_x + 2
            and sw_y <= item.get("worldY", -1) <= sw_y + 2
        ]

    def _live_brutus_pos(self, ctrl: "GameController", npc: dict) -> Tuple[int, int]:
        """Freshest known world position for Brutus: the BRUTUS_SUB_ID hull
        update if one has arrived, else the tick snapshot's worldX/Y. Used
        to compute the dodge tile against where Brutus actually is right
        now rather than a possibly-600ms-stale tick position."""
        update = ctrl.hull_update(self.BRUTUS_SUB_ID)
        if update and update.get("found") and update.get("worldX") is not None:
            return update["worldX"], update["worldY"]
        return npc["worldX"], npc["worldY"]

    def _compute_dodge_tile(self, game: "GameState", ctrl: "GameController", npc: dict) -> Tuple[int, int]:
        """One tile further from Brutus's centre along the line from his
        centre through the player's current tile — moves off both the
        charge lane and the slam's adjacent-tile splash regardless of
        whether the player is standing orthogonal or diagonal to him (see
        module docstring / GAMEBRIDGE.md for the mechanic). Brutus's
        worldX/worldY is his south-west tile (he is 3x3), so his centre is
        one tile north-east of that corner.

        BRUTUS
        ┌───┬───┬───┐
        │   │   │   │
        ├───┼───┼───┤
        │   │ C │   │
        ├───┼───┼───┤
        │   │   │ T │
        └───┴───┴───┘
        C = Brutus's centre tile (bx+1, by+1)
        T = Brutus's south-west tile (bx, by) = npc["worldX"], npc["worldY"]

        All the tiles next to any of Brutus's 3x3 footprint are unsafe.

        The only safe tiles for both specials are the four diagonal tiles at least 3 tiles
        away from Brutus's centre (the four corners of the 5x5 square around him).
        """
        # True tile South-West corner of Brutus's 3x3 footprint
        bx, by = self._live_brutus_pos(ctrl, npc)

        # Brutus full 3 tile square footprint: SW=(bx,by), SE=(bx+2,by), NW=(bx,by+2), NE=(bx+2,by+2)
        brutus_centre = (bx + 1, by + 1)  # NE of SW corner

        # Player tile
        player_tile = (game.player_pos[0], game.player_pos[1])

        # Safe tiles are the four diagonal tiles at least 3 tiles away from Brutus's centre
        safe_tiles = {
            (brutus_centre[0] - 3, brutus_centre[1] - 3),  # NW
            (brutus_centre[0] + 3, brutus_centre[1] - 3),  # NE
            (brutus_centre[0] - 3, brutus_centre[1] + 3),  # SW
            (brutus_centre[0] + 3, brutus_centre[1] + 3),  # SE
        }

        # Compute the player's nearest safe tile
        nearest_safe_tile = min(safe_tiles, key=lambda t: (abs(t[0] - player_tile[0]) + abs(t[1] - player_tile[1])))

        return nearest_safe_tile

    def _click_dodge_tile(
        self, game: "GameState", ctrl: "GameController", tile: Tuple[int, int],
    ) -> None:
        """Click the dodge tile directly in the game viewport — never the
        minimap. No human steps one tile sideways by reaching for the
        minimap; a real player's eyes and cursor stay on the 3D view for a
        dodge this close.

        Uses the real, plugin-computed canvas clickbox for the dodge tile
        (a `kind: "tile"` live-clickbox subscription — see GAMEBRIDGE.md)
        rather than any geometric estimate: subscribing renews/overwrites
        DODGE_TILE_SUB_ID, so re-subscribing every dodge is cheap and never
        needs an explicit unsubscribe. If the subscription's first push
        hasn't arrived yet, or the tile isn't currently on-screen, the dodge
        click is skipped entirely (no minimap fallback) — the next
        telegraph/tick will retry.
        """
        tx, ty = tile
        ctrl.subscribe_to_tile(self.DODGE_TILE_SUB_ID, tx, ty, game.plane,
                                ttl_ticks=self.DODGE_TILE_SUB_TTL_TICKS)
        update = ctrl.hull_update(self.DODGE_TILE_SUB_ID)
        if not update or not update.get("found") or not update.get("onScreen") \
                or update.get("canvasX") is None:
            log.debug("Dodge tile (%d, %d) not yet on-screen — skipping this dodge click", tx, ty)
            return
        ctrl.click_walk_target(update["canvasX"], update["canvasY"], game)
