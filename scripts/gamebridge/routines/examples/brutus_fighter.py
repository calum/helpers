"""
Brutus Fighter routine.

Brutus is a 3x3 aggressive melee NPC (ids 15626/15627) that, after every
4-5 basic attacks, telegraphs one of two special attacks with a distinct
animation several ticks before it actually lands:

  - "Charge" (telegraph anim 13778)
  - "Slam"   (telegraph anim 13785, animation repeats in pulses)

Both specials ignore protection prayers but can be fully avoided by moving
off the tile before the attack resolves. The telegraph animation IDs above
were read directly off a recorded fight (see
~/.gamebridge/recordings/recording-20260628-152254.jsonl) by diffing
Brutus's per-tick `animation` field against player HP loss: 13783 is his
basic melee swing (correlates with -1..-3 HP most ticks it fires); 13778 and
13785 never correlate with any HP loss while the player keeps off the danger
tile, matching the in-game special-attack tells. A closer per-tick read of
that recording shows each telegraph holds its animation for several ticks,
drops to -1 briefly, and (for Slam) can restart — re-engaging is only safe
once the animation has actually cleared, not a fixed number of ticks after
it first appears.

State diagram
─────────────

  ┌──────────────┐
  │ find_target  │◄─────────────────────────────────────┐
  └──────┬───────┘                                      │
         │ NPC clicked                                  │
         ▼                                              │
  ┌──────────────┐                                       │
  │   fighting   │── special telegraphed: dodge, wait ───┘
  └──────┬───────┘   for the animation to clear, re-engage
         │ NPC vanished — assume dead
         ▼
  ┌──────────────┐
  │   looting    │
  └──────────────┘

Dodging a telegraphed special is handled entirely inside `fighting()` —
there is no separate "dodging" state, since a `Routine` only re-evaluates
its current state once per tick (see base.py), and deferring the dodge click
to a separate state would waste a full tick of an already-tight window.

The dodge click is level-triggered, not one-shot: every tick the telegraph
animation is showing and the player hasn't yet reached the chosen corner
tile (`game.player_pos != target_tile`), the click is re-issued. An earlier
version clicked once and unconditionally assumed it landed, so a single
missed click (e.g. the tile's hull_update not yet `found`/`onScreen` on
that exact tick) was never retried — the player stood still for the rest of
the telegraph and ate the hit. The chosen corner (`_dodge_tile_key`) is
locked for the duration of one telegraph episode so retries keep aiming at
the same tile instead of recomputing "nearest" mid-walk.

All 4 candidate dodge tiles (the corners _compute_dodge_tile can ever pick)
are kept subscribed continuously, every tick of `fighting()`, regardless of
whether a telegraph is currently showing — not only at the moment one
appears. An earlier version subscribed reactively (only inside the dodge
click itself), which left the very first dodge of every fight with zero lead
time for the Java plugin's hullUpdate push to arrive, causing a logged
"not yet on-screen — skipping this dodge click" and a real hit taken.
Warming all 4 up-front from the start of the fight means the relevant
clickbox is already known well before any telegraph fires.

Healing is handled inline, not via a separate "healing" state: `_maybe_eat`
is called at the top of find_target/fighting/looting and, whenever HP drops
to/below HEAL_HP_THRESHOLD and food remains, clicks a food item immediately
and then falls straight through into that same call's normal logic — still
attacking/dodging/looting in the same tick the eat click fires. An earlier
version returned a "healing" state and waited for the next tick to actually
click the food, costing a full ~600ms tick of pure detection-only delay
before the eat click ever fired — a real player eats and keeps fighting in
the same reaction, not eats-then-freezes-for-a-tick.

This routine declares itself "high-attention" (ATTENTION_LEVEL = "combat",
applied every tick via GameController.set_attention_level) — Brutus aggros
instantly and his specials only give a few ticks to dodge, so every click
here uses HumanEmulator's faster combat reflex/movement multipliers instead
of the default relaxed-skilling pacing. All clicks happen directly in the
game viewport; the dodge step in particular never reaches for the minimap,
since no human would for a one-tile sidestep.

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

    # The 4 candidate dodge tiles (see _safe_tiles) each get their own fixed
    # subId, kept subscribed continuously every tick of fighting() — not just
    # reactively when a telegraph appears. Renewing every tick is cheap (one
    # plugin-side clickbox computation per subscription per ~20ms ClientTick)
    # and gives the Java plugin's hullUpdate push many ticks of lead time
    # before any telegraph ever shows, so a dodge click never has to wait on
    # a cold subscription. See module docstring for the bug this fixes.
    DODGE_TILE_SUB_IDS = {
        "nw": "brutus_dodge_nw",
        "ne": "brutus_dodge_ne",
        "sw": "brutus_dodge_sw",
        "se": "brutus_dodge_se",
    }
    DODGE_TILE_SUB_TTL_TICKS = 5  # renewed every fighting() tick, just needs to outlive one tick

    # Telegraph animation IDs for Brutus's two specials — see module docstring.
    BASIC_ATTACK_ANIM = 13783
    SPECIAL_TELL_ANIMS = frozenset({13785, 13778})

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
        self._dodge_tile_key: Optional[str] = None
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
        self._maybe_eat(game, ctrl)

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

        Dodging is handled entirely within this one state — there is no
        separate "dodging" state (see module docstring). The dodge click is
        level-triggered: it fires every tick the telegraph is showing and
        the player hasn't yet reached the locked `_dodge_tile_key` corner,
        so a single missed click (clickbox not yet ready) gets retried
        instead of being silently treated as done. The telegraph check runs
        first and always returns "fighting" while the animation is still
        telegraphing, so the re-engage check below it is never reached until
        the animation actually clears — re-engaging is safe the instant that
        happens (the danger is exactly and only `animation in
        SPECIAL_TELL_ANIMS`), with no extra fixed wait needed.
        """
        self._renew_brutus_subscription(ctrl)
        ctrl.set_attention_level(self.ATTENTION_LEVEL)
        self._maybe_eat(game, ctrl)

        live_target = next((n for n in game.npcs if n.get("index") == self._target_index), None)

        if live_target is None:
            self._target_pos = (self._target["worldX"], self._target["worldY"])
            log.debug("Brutus (index=%d) is gone — assuming it died at %s",
                      self._target_index, self._target_pos)
            self._death_tick = game.tick
            self._looted_keys.clear()
            return "looting"

        self._target = live_target

        safe_tiles = self._safe_tiles(game, ctrl, live_target)
        self._renew_dodge_tile_subscriptions(ctrl, game, safe_tiles)

        if live_target.get("animation") in self.SPECIAL_TELL_ANIMS:
            if self._dodge_tile_key is None:
                log.debug("Brutus telegraphing a special (anim=%d) — dodging now", live_target["animation"])
                self._dodge_tile_key = self._nearest_safe_tile_key(game, safe_tiles)
            target_tile = safe_tiles[self._dodge_tile_key]
            if (game.player_pos[0], game.player_pos[1]) != target_tile:
                self._click_dodge_tile(game, ctrl, self._dodge_tile_key, target_tile)
            self._dodge_clicked = True
            return "fighting"

        if self._dodge_clicked and self.click_live(ctrl, live_target, "npc", False):
            self._dodge_clicked = False
            self._dodge_tile_key = None
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

    def looting(self, game: "GameState", ctrl: "GameController") -> Optional[str]:
        """Plain left-click looting (no menu verification, per requirement)
        across Brutus's whole 3x3 corpse footprint."""
        ctrl.set_attention_level(self.ATTENTION_LEVEL)
        self._maybe_eat(game, ctrl)

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

    def _maybe_eat(self, game: "GameState", ctrl: "GameController") -> bool:
        """Eat one food item immediately if HP is low and food remains, then
        let the caller's own state logic run in the same call — see module
        docstring for why eating is inlined here rather than detouring
        through a separate "healing" state. Cooldown-gated by
        EAT_COOLDOWN_TICKS/_last_eat_tick so a routine that's still below
        threshold next tick eats again, mirroring a player eating repeatedly
        while taking damage. Returns True if a food click actually fired."""
        if not self._needs_heal(game):
            return False
        if game.tick - self._last_eat_tick < self.EAT_COOLDOWN_TICKS:
            return False
        for food_id in self.FOOD_ITEM_IDS:
            if game.inventory_has_item(food_id) and self.click_inventory_item(game, ctrl, food_id):
                self._last_eat_tick = game.tick
                return True
        return False

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

    def _safe_tiles(self, game: "GameState", ctrl: "GameController", npc: dict) -> dict:
        """The 4 candidate dodge tiles, keyed "nw"/"ne"/"sw"/"se" to match
        DODGE_TILE_SUB_IDS — one tile further from Brutus's centre along
        each diagonal, clearing both the charge lane and the slam's
        adjacent-tile splash regardless of whether the player is standing
        orthogonal or diagonal to him (see module docstring / GAMEBRIDGE.md
        for the mechanic). Brutus's worldX/worldY is his south-west tile (he
        is 3x3), so his centre is one tile north-east of that corner.

        BRUTUS
        ┌───┬───┬───┐
        │   │   │   │
        ├───┼───┼───┤
        │   │ C │   │
        ├───┼───┼───┤
        │ T │   │   │
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

        return {
            "nw": (brutus_centre[0] - 3, brutus_centre[1] - 3),
            "ne": (brutus_centre[0] + 3, brutus_centre[1] - 3),
            "sw": (brutus_centre[0] - 3, brutus_centre[1] + 3),
            "se": (brutus_centre[0] + 3, brutus_centre[1] + 3),
        }

    def _nearest_safe_tile_key(self, game: "GameState", safe_tiles: dict) -> str:
        """Which of the 4 safe_tiles keys is nearest the player right now (Manhattan distance)."""
        player_tile = (game.player_pos[0], game.player_pos[1])
        return min(safe_tiles, key=lambda k: abs(safe_tiles[k][0] - player_tile[0]) + abs(safe_tiles[k][1] - player_tile[1]))

    def _compute_dodge_tile(self, game: "GameState", ctrl: "GameController", npc: dict) -> Tuple[int, int]:
        """The single nearest safe dodge tile — thin wrapper over
        _safe_tiles/_nearest_safe_tile_key kept for callers (and tests) that
        only care about the chosen tile's coordinates."""
        safe_tiles = self._safe_tiles(game, ctrl, npc)
        key = self._nearest_safe_tile_key(game, safe_tiles)
        return safe_tiles[key]

    def _renew_dodge_tile_subscriptions(self, ctrl: "GameController", game: "GameState", safe_tiles: dict) -> None:
        """Keep all 4 candidate dodge tiles' live clickboxes warm every tick
        of fighting() — see DODGE_TILE_SUB_IDS and the module docstring for
        why this can't wait until a telegraph is actually seen."""
        for key, (tx, ty) in safe_tiles.items():
            ctrl.subscribe_to_tile(self.DODGE_TILE_SUB_IDS[key], tx, ty, game.plane,
                                    ttl_ticks=self.DODGE_TILE_SUB_TTL_TICKS)

    def _click_dodge_tile(
        self, game: "GameState", ctrl: "GameController", key: str, tile: Tuple[int, int],
    ) -> None:
        """Click the dodge tile directly in the game viewport — never the
        minimap. No human steps one tile sideways by reaching for the
        minimap; a real player's eyes and cursor stay on the 3D view for a
        dodge this close.

        Uses the real, plugin-computed canvas clickbox for the dodge tile
        (a `kind: "tile"` live-clickbox subscription — see GAMEBRIDGE.md)
        rather than any geometric estimate. The subscription itself is kept
        warm by _renew_dodge_tile_subscriptions every tick, not here — by
        the time this is called, the relevant subId should already have a
        recent hullUpdate. If it doesn't (or the tile isn't currently
        on-screen), the dodge click is skipped entirely (no minimap
        fallback) — the next telegraph/tick will retry.
        """
        update = ctrl.hull_update(self.DODGE_TILE_SUB_IDS[key])
        if not update or not update.get("found") or not update.get("onScreen") \
                or update.get("canvasX") is None:
            tx, ty = tile
            log.debug("Dodge tile %s (%d, %d) not yet on-screen — skipping this dodge click", key, tx, ty)
            return
        ctrl.click_walk_target(update["canvasX"], update["canvasY"], game)
