"""
Tests for the BrutusFighterRoutine state machine.

Covers what's specific to Brutus (the shared targeting/approach/miss-click
machinery is already exercised by test_melee_fighter.py / test_interaction.py,
which BrutusFighterRoutine reuses unchanged via InteractionRoutine):

  - a persistent live-clickbox subscription on Brutus, renewed every tick
    from every combat-adjacent state
  - detecting his special-attack telegraph animations and dodging one tile
    away from his 3x3 centre, then re-engaging with a plain left-click
  - healing (eating trout/salmon) below the HP threshold, with a cooldown,
    returning to whichever state it interrupted
  - footprint-wide, left-click-only looting (no "verify before you click"
    menu gesture, per the left-click looting requirement) across all nine
    of his corpse tiles
"""
from __future__ import annotations

from unittest.mock import ANY, MagicMock

from scripts.gamebridge.item_ids import COOKED_SALMON, COOKED_TROUT
from scripts.gamebridge.routines.examples.brutus_fighter import BrutusFighterRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(
    tick: int = 1,
    player_x: int = 13278,
    player_y: int = 7227,
    npcs: list | None = None,
    ground_items: list | None = None,
    inventory: list | None = None,
    widgets: list | None = None,
    hp: int = 15,
) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1, "hp": hp}
    game.npcs = npcs if npcs is not None else []
    game.ground_items = ground_items if ground_items is not None else []
    game.inventory = inventory if inventory is not None else []
    game.widgets = widgets if widgets is not None else []
    game.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 4.0}
    return game


class _AnyTooltip(str):
    """Tooltip stub that satisfies `name in tooltip` for any name."""

    def __contains__(self, item):
        return True

    def lower(self):
        return self


_ANY_TOOLTIP = _AnyTooltip()


def _ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.tooltip.return_value = _ANY_TOOLTIP
    ctrl.click_entity.return_value = True
    ctrl.hull_update.return_value = None
    return ctrl


def _routine() -> BrutusFighterRoutine:
    return BrutusFighterRoutine()


# Brutus's worldX/worldY is his south-west tile (he is 3x3).
BRUTUS_SW = (13278, 7228)

BRUTUS = {
    "id": 15626, "index": 99, "name": "Brutus",
    "worldX": BRUTUS_SW[0], "worldY": BRUTUS_SW[1], "plane": 0,
    "animation": -1, "combatLevel": 30, "onScreen": True,
    "canvasX": 400, "canvasY": 300,
    "hull": [[390, 290], [410, 290], [410, 310], [390, 310]],
}

BRUTUS_TELEGRAPH_GROWL = {**BRUTUS, "animation": 13785}
BRUTUS_TELEGRAPH_SNORT = {**BRUTUS, "animation": 13778}
BRUTUS_BASIC_SWING = {**BRUTUS, "animation": 13783}

COINS_ON_BRUTUS_TILE = {
    "id": 995, "name": "Coins", "quantity": 60,
    "worldX": BRUTUS_SW[0] + 1, "worldY": BRUTUS_SW[1] + 1, "plane": 0,
    "onScreen": True, "canvasX": 405, "canvasY": 305,
    "hull": [[395, 295], [415, 295], [415, 315], [395, 315]],
}

BONES_OFF_CORPSE_FOOTPRINT = {
    "id": 526, "name": "Bones", "quantity": 1,
    "worldX": BRUTUS_SW[0] + 10, "worldY": BRUTUS_SW[1], "plane": 0,
    "onScreen": True, "canvasX": 500, "canvasY": 300, "hull": None,
}

TROUT_SLOT = {"groupId": 149, "childId": 0, "itemId": COOKED_TROUT, "quantity": 1, "bounds": {"x": 0, "y": 0, "width": 32, "height": 32}, "text": ""}
SALMON_SLOT = {"groupId": 149, "childId": 1, "itemId": COOKED_SALMON, "quantity": 1, "bounds": {"x": 32, "y": 0, "width": 32, "height": 32}, "text": ""}


# ---------------------------------------------------------------------------
# Brutus subscription — registered/renewed every tick, every combat state
# ---------------------------------------------------------------------------

class TestBrutusSubscription:
    def test_find_target_renews_subscription(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        _routine().find_target(game, ctrl)
        ctrl.subscribe_to.assert_any_call(
            BrutusFighterRoutine.BRUTUS_SUB_ID, "npc",
            name="Brutus", ttl_ticks=BrutusFighterRoutine.BRUTUS_SUB_TTL_TICKS,
        )

    def test_fighting_renews_subscription(self):
        game = _make_game(npcs=[BRUTUS])
        ctrl = _ctrl()
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = game.tick
        r.fighting(game, ctrl)
        ctrl.subscribe_to.assert_any_call(
            BrutusFighterRoutine.BRUTUS_SUB_ID, "npc",
            name="Brutus", ttl_ticks=BrutusFighterRoutine.BRUTUS_SUB_TTL_TICKS,
        )


# ---------------------------------------------------------------------------
# find_target — fast engagement: on-screen + unoccluded -> single left-click
# ---------------------------------------------------------------------------

class TestFindTarget:
    def test_no_click_when_brutus_not_in_scene(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        result = _routine().find_target(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_adjusts_camera_when_off_screen_without_clicking(self):
        off_screen = {**BRUTUS, "onScreen": False, "canvasX": None, "canvasY": None}
        game = _make_game(npcs=[off_screen])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        result = _routine().find_target(game, ctrl)
        ctrl.bring_entity_on_screen.assert_called_once_with(off_screen, game)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_nudges_camera_when_occluded_without_clicking(self):
        game = _make_game(npcs=[BRUTUS])
        game.interfaces = [
            {"groupId": 149, "childId": 0, "itemId": -1, "quantity": 0,
             "bounds": {"x": 350, "y": 250, "width": 150, "height": 150}, "text": ""},
        ]
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        result = _routine().find_target(game, ctrl)
        ctrl.click_entity.assert_not_called()
        ctrl.rotate_camera.assert_called_once()
        assert result is None

    def test_engages_with_a_single_left_click_no_settle_buffer_no_menu(self):
        """Engagement must take exactly one tick — no idle-settle buffer and
        no right-click/verify-menu round trip, both of which would waste
        ticks against an instantly aggressive boss."""
        game = _make_game(tick=3, npcs=[BRUTUS])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        r = _routine()
        result = r.find_target(game, ctrl)

        ctrl.click_entity.assert_called_once()
        ctrl.right_click_entity.assert_not_called()
        assert result == "fighting"
        assert r._target_index == BRUTUS["index"]
        assert r._fight_start_tick == 3

    def test_stays_in_find_target_when_left_click_does_not_land(self):
        game = _make_game(tick=3, npcs=[BRUTUS])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_entity.return_value = False

        result = _routine().find_target(game, ctrl)

        assert result is None

    def test_eats_then_still_engages_in_the_same_tick_if_hp_is_low(self):
        """Eating must not cost a tick before engaging — both the eat click
        and the attack click fire from within this single find_target() call."""
        game = _make_game(tick=3, hp=3, npcs=[BRUTUS],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}],
                           widgets=[TROUT_SLOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        result = _routine().find_target(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)
        ctrl.click_entity.assert_called_once()
        assert result == "fighting"


# ---------------------------------------------------------------------------
# "high-attention" — every state declares combat-speed reflexes
# ---------------------------------------------------------------------------

class TestAttentionLevel:
    def test_find_target_sets_combat_attention(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        _routine().find_target(game, ctrl)
        ctrl.set_attention_level.assert_called_once_with("combat")

    def test_fighting_sets_combat_attention(self):
        game = _make_game(tick=5, npcs=[BRUTUS_BASIC_SWING])
        ctrl = _ctrl()
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = 4
        r.fighting(game, ctrl)
        ctrl.set_attention_level.assert_called_once_with("combat")

    def test_fighting_sets_combat_attention_while_reengaging_after_a_dodge(self):
        """Attention must stay "combat" on the re-engage tick too, not just
        on the first telegraph sighting."""
        game = _make_game(tick=5, npcs=[BRUTUS_BASIC_SWING])
        ctrl = _ctrl()
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS_BASIC_SWING
        r._fight_start_tick = 4
        r._dodge_clicked = True
        r.fighting(game, ctrl)
        ctrl.set_attention_level.assert_called_once_with("combat")

    def test_looting_sets_combat_attention(self):
        game = _make_game(tick=11, ground_items=[])
        ctrl = _ctrl()
        r = _routine()
        r._target_pos = BRUTUS_SW
        r._death_tick = 10
        r.looting(game, ctrl)
        ctrl.set_attention_level.assert_called_once_with("combat")


# ---------------------------------------------------------------------------
# fighting — telegraph detection -> dodging
# ---------------------------------------------------------------------------

class TestFightingTelegraphDetection:
    def _engaged_routine(self, fight_start_tick: int = 4) -> BrutusFighterRoutine:
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = fight_start_tick
        return r

    def test_stays_fighting_on_basic_swing(self):
        game = _make_game(tick=5, npcs=[BRUTUS_BASIC_SWING])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result is None

    def test_dodges_on_growl_telegraph(self):
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result == "fighting"

    def test_dodges_on_snort_telegraph(self):
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_SNORT])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result == "fighting"

    def test_issues_dodge_click_immediately_on_telegraph_not_next_tick(self):
        """The dodge click must fire from within fighting() itself, the same
        tick the telegraph is seen — a Routine only re-evaluates its state
        once per tick (base.py), so deferring the click to a separate
        "dodging" state would waste a full ~600ms tick of an already-tight
        window. There is no separate "dodging" state — dodging is handled
        entirely inside fighting()."""
        r = self._engaged_routine()
        r._click_dodge_tile = MagicMock()
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])

        result = r.fighting(game, _ctrl())

        r._click_dodge_tile.assert_called_once()
        assert r._dodge_clicked is True
        assert result == "fighting"

    def test_keeps_targeting_the_same_dodge_tile_while_telegraph_animation_persists(self):
        """Brutus's telegraphs hold their animation for several ticks (and
        Slam's repeats in pulses). The dodge click is retried every tick the
        player hasn't yet reached the chosen tile (see module docstring), but
        which tile is being aimed at must stay locked across those retries —
        not recomputed from "nearest" each tick, which could flip-flop mid-walk."""
        r = self._engaged_routine()
        r._click_dodge_tile = MagicMock()
        ctrl = _ctrl()

        r.fighting(_make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_SNORT]), ctrl)
        first_key = r._dodge_tile_key
        result = r.fighting(_make_game(tick=6, npcs=[BRUTUS_TELEGRAPH_SNORT]), ctrl)

        assert r._dodge_tile_key == first_key
        assert r._click_dodge_tile.call_count == 2
        assert result == "fighting"

    def test_stays_dodging_no_matter_how_long_the_telegraph_persists(self):
        """Regardless of how many ticks the telegraph animation has been
        showing, fighting() must keep returning "fighting" without ever
        attempting to re-engage (no click_entity call) while still
        telegraphing."""
        r = self._engaged_routine()
        ctrl = _ctrl()

        for tick in range(5, 15):
            result = r.fighting(_make_game(tick=tick, npcs=[BRUTUS_TELEGRAPH_SNORT]), ctrl)
            assert result == "fighting"

        ctrl.click_entity.assert_not_called()

    def test_transitions_to_looting_when_brutus_vanishes(self):
        game = _make_game(tick=5, npcs=[])
        r = self._engaged_routine()
        result = r.fighting(game, _ctrl())
        assert result == "looting"
        assert r._target_pos == (BRUTUS["worldX"], BRUTUS["worldY"])

    def test_misclick_timeout_returns_to_find_target(self):
        game = _make_game(tick=20, npcs=[BRUTUS_BASIC_SWING])
        r = self._engaged_routine(fight_start_tick=5)  # 15 ticks, no xp drop
        result = r.fighting(game, _ctrl())
        assert result == "find_target"

    def test_keeps_fighting_past_timeout_once_xp_drop_seen(self):
        game = _make_game(tick=20, npcs=[BRUTUS_BASIC_SWING])
        game.last_xp_tick["STRENGTH"] = 7
        r = self._engaged_routine(fight_start_tick=5)
        result = r.fighting(game, _ctrl())
        assert result is None


# ---------------------------------------------------------------------------
# _compute_dodge_tile — pure geometry, no routine state involved
# ---------------------------------------------------------------------------

class TestComputeDodgeTile:
    def test_computes_tile_away_from_brutus_centre(self):
        # Brutus centre is (13279, 7229) — player one tile south-west of it.
        # The four candidate safe tiles are the corners 3 tiles out from
        # centre; nearest to the player (Manhattan distance) is the
        # north-west corner, (13276, 7226).
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        tile = _routine()._compute_dodge_tile(game, _ctrl(), BRUTUS_TELEGRAPH_GROWL)
        assert tile == (13276, 7226)

    def test_safe_tiles_returns_all_four_corners(self):
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        safe_tiles = _routine()._safe_tiles(game, _ctrl(), BRUTUS_TELEGRAPH_GROWL)
        assert safe_tiles == {
            "nw": (13276, 7226),
            "ne": (13282, 7226),
            "sw": (13276, 7232),
            "se": (13282, 7232),
        }

    def test_nearest_safe_tile_key_picks_nw_for_fixture_player_position(self):
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        r = _routine()
        safe_tiles = r._safe_tiles(game, _ctrl(), BRUTUS_TELEGRAPH_GROWL)
        assert r._nearest_safe_tile_key(game, safe_tiles) == "nw"

    def test_prefers_live_hull_position_over_stale_tick_position(self):
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {"found": True, "worldX": 13300, "worldY": 7300}
        tile = _routine()._compute_dodge_tile(game, ctrl, BRUTUS_TELEGRAPH_GROWL)
        # Centre now far north-east at (13301, 7301) — of the four corners
        # 3 tiles out from it, the nearest to the (unchanged) player position
        # is still the north-west one, (13298, 7298).
        assert tile == (13298, 7298)


# ---------------------------------------------------------------------------
# fighting() — dodge-tile subscription warm-up (every tick, not reactive)
# ---------------------------------------------------------------------------

class TestDodgeTileWarmup:
    def _engaged_routine(self) -> BrutusFighterRoutine:
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = 0
        return r

    def test_subscribes_to_all_four_dodge_tiles_even_without_a_telegraph(self):
        """Subscriptions must be kept warm every tick of fighting(),
        regardless of whether a telegraph is currently showing — this is
        what gives the Java plugin's hullUpdate push lead time before the
        very first telegraph of a fight ever appears (see module docstring/
        bug this fixes)."""
        game = _make_game(tick=5, npcs=[BRUTUS_BASIC_SWING])
        ctrl = _ctrl()

        self._engaged_routine().fighting(game, ctrl)

        for key, coords in {
            "nw": (13276, 7226), "ne": (13282, 7226),
            "sw": (13276, 7232), "se": (13282, 7232),
        }.items():
            ctrl.subscribe_to_tile.assert_any_call(
                BrutusFighterRoutine.DODGE_TILE_SUB_IDS[key], *coords,
                game.plane, ttl_ticks=BrutusFighterRoutine.DODGE_TILE_SUB_TTL_TICKS,
            )

    def test_does_not_reproduce_cold_start_miss_on_first_ever_telegraph(self):
        """Regression test for the reported bug: subscriptions warmed up
        over several preceding ticks of fighting() (no telegraph yet) must
        already have hullUpdate data by the time the first telegraph of the
        fight appears, so the dodge click is not skipped."""
        ctrl = _ctrl()
        r = self._engaged_routine()

        for tick in range(5, 10):
            r.fighting(_make_game(tick=tick, npcs=[BRUTUS_BASIC_SWING]), ctrl)

        ctrl.hull_update.return_value = {
            "subId": BrutusFighterRoutine.DODGE_TILE_SUB_IDS["nw"], "found": True,
            "onScreen": True, "canvasX": 386.0, "canvasY": 320.0,
        }
        result = r.fighting(_make_game(tick=10, npcs=[BRUTUS_TELEGRAPH_GROWL]), ctrl)

        ctrl.click_walk_target.assert_called_once_with(386.0, 320.0, ANY)
        assert result == "fighting"


# ---------------------------------------------------------------------------
# fighting() — dodge-tile click plumbing (first telegraph sighting)
# ---------------------------------------------------------------------------

class TestDodgeTileClickPlumbing:
    def _telegraphed_routine(self) -> BrutusFighterRoutine:
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS_TELEGRAPH_GROWL
        r._fight_start_tick = 0
        return r

    def test_clicks_canvas_position_from_tile_hull_update_when_onscreen(self):
        """Once the tile subscription's hullUpdate shows it on-screen, click
        its real canvas position — never the minimap."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {
            "subId": BrutusFighterRoutine.DODGE_TILE_SUB_IDS["nw"], "found": True,
            "onScreen": True, "canvasX": 386.0, "canvasY": 320.0,
        }

        self._telegraphed_routine().fighting(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_called_once_with(386.0, 320.0, game)

    def test_skips_click_without_minimap_fallback_when_tile_not_found(self):
        """No hullUpdate yet (or found: false) -> skip the click entirely.
        Must never fall back to a minimap click."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {"subId": BrutusFighterRoutine.DODGE_TILE_SUB_IDS["nw"], "found": False}

        self._telegraphed_routine().fighting(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_not_called()

    def test_skips_click_without_minimap_fallback_when_tile_not_onscreen(self):
        """found: true but onScreen: false -> still skip, no minimap fallback."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {
            "subId": BrutusFighterRoutine.DODGE_TILE_SUB_IDS["nw"], "found": True,
            "onScreen": False, "canvasX": None, "canvasY": None,
        }

        self._telegraphed_routine().fighting(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_not_called()

    def test_skips_click_when_no_hull_update_has_arrived_yet(self):
        """hull_update() returning None (subscription just registered, no
        push yet) must also be treated as skip-this-dodge, not an error."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = None

        self._telegraphed_routine().fighting(game, ctrl)

        ctrl.click_walk_target.assert_not_called()

    def test_retries_dodge_click_next_tick_if_first_attempt_missed(self):
        """A dodge click that misses because the tile's hullUpdate isn't
        `found` yet must be retried on the next tick — not abandoned. This is
        the bug: the old one-shot dodge click marked itself "done" the
        instant it was attempted, regardless of whether it actually landed."""
        r = self._telegraphed_routine()
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {"found": False}

        r.fighting(_make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL]), ctrl)
        ctrl.click_walk_target.assert_not_called()

        ctrl.hull_update.return_value = {
            "found": True, "onScreen": True, "canvasX": 386.0, "canvasY": 320.0,
        }
        result = r.fighting(_make_game(tick=6, npcs=[BRUTUS_TELEGRAPH_GROWL]), ctrl)

        ctrl.click_walk_target.assert_called_once_with(386.0, 320.0, ANY)
        assert result == "fighting"

    def test_stops_clicking_once_player_has_reached_the_dodge_tile(self):
        """Once `game.player_pos` matches the locked dodge tile, no further
        click fires even while still telegraphing — "wait if already on the
        dodge tile" rather than spamming the same destination forever."""
        r = self._telegraphed_routine()
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {
            "found": True, "onScreen": True, "canvasX": 386.0, "canvasY": 320.0,
        }

        game1 = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        r.fighting(game1, ctrl)
        ctrl.click_walk_target.assert_called_once()

        ctrl.click_walk_target.reset_mock()
        nw_tile = r._safe_tiles(game1, ctrl, BRUTUS_TELEGRAPH_GROWL)[r._dodge_tile_key]
        game2 = _make_game(tick=6, player_x=nw_tile[0], player_y=nw_tile[1],
                            npcs=[BRUTUS_TELEGRAPH_GROWL])
        result = r.fighting(game2, ctrl)

        ctrl.click_walk_target.assert_not_called()
        assert result == "fighting"


# ---------------------------------------------------------------------------
# fighting() — re-engaging once the telegraph animation has cleared
# ---------------------------------------------------------------------------

class TestReengageAfterDodge:
    def _post_dodge_routine(self, fight_start_tick: int = 0) -> BrutusFighterRoutine:
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = fight_start_tick
        r._dodge_clicked = True
        return r

    def test_reengages_with_plain_left_click_once_animation_clears(self):
        """No extra fixed wait — re-engaging is safe the same tick the
        telegraph animation stops, confirmed against a recorded fight (see
        module docstring)."""
        game = _make_game(tick=6, npcs=[BRUTUS_BASIC_SWING])
        ctrl = _ctrl()
        r = self._post_dodge_routine()

        result = r.fighting(game, ctrl)

        ctrl.click_entity.assert_called_once()
        assert result == "fighting"
        assert r._dodge_clicked is False

    def test_stays_dodging_if_reengage_click_does_not_land(self):
        game = _make_game(tick=6, npcs=[BRUTUS_BASIC_SWING])
        ctrl = _ctrl()
        ctrl.click_entity.return_value = False
        r = self._post_dodge_routine()

        result = r.fighting(game, ctrl)

        assert result is None
        assert r._dodge_clicked is True

    def test_transitions_to_looting_if_brutus_dies_mid_dodge(self):
        """The vanished-NPC check runs before the telegraph/re-engage logic,
        so it must win outright regardless of dodge state."""
        game = _make_game(tick=6, npcs=[])
        ctrl = _ctrl()
        r = self._post_dodge_routine()

        result = r.fighting(game, ctrl)

        assert result == "looting"


# ---------------------------------------------------------------------------
# _maybe_eat — inline healing: eat below threshold, cooldown-gated, then the
# caller's own state logic continues in the same tick (see module docstring)
# ---------------------------------------------------------------------------

class TestMaybeEat:
    def test_needs_heal_false_above_threshold(self):
        game = _make_game(hp=10, inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        assert _routine()._needs_heal(game) is False

    def test_needs_heal_false_without_food(self):
        game = _make_game(hp=3, inventory=[])
        assert _routine()._needs_heal(game) is False

    def test_needs_heal_true_at_threshold_with_food(self):
        game = _make_game(hp=6, inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        assert _routine()._needs_heal(game) is True

    def test_fighting_eats_inline_without_costing_a_tick(self):
        """Eating must happen in the same fighting() call that detects low
        HP, not via a detour that costs a tick before the click fires."""
        game = _make_game(tick=5, hp=4, npcs=[BRUTUS_BASIC_SWING],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}],
                           widgets=[TROUT_SLOT])
        ctrl = _ctrl()
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = 4

        result = r.fighting(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)
        assert r._last_eat_tick == 5
        assert result is None

    def test_eats_trout_then_salmon_when_trout_exhausted(self):
        game = _make_game(tick=5, hp=4, widgets=[SALMON_SLOT],
                           inventory=[{"slot": 1, "itemId": COOKED_SALMON, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()

        result = r._maybe_eat(game, ctrl)

        ctrl.click_widget.assert_called_once_with(SALMON_SLOT)
        assert result is True
        assert r._last_eat_tick == 5

    def test_prefers_trout_when_both_present(self):
        game = _make_game(tick=5, hp=4, widgets=[TROUT_SLOT, SALMON_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1},
                                      {"slot": 1, "itemId": COOKED_SALMON, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()

        r._maybe_eat(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)

    def test_does_not_eat_again_within_cooldown(self):
        game = _make_game(tick=6, hp=4, widgets=[TROUT_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()
        r._last_eat_tick = 5  # 1 tick ago < EAT_COOLDOWN_TICKS

        result = r._maybe_eat(game, ctrl)

        ctrl.click_widget.assert_not_called()
        assert result is False

    def test_eats_again_once_cooldown_elapses(self):
        game = _make_game(tick=8, hp=4, widgets=[TROUT_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()
        r._last_eat_tick = 5  # 3 ticks ago == EAT_COOLDOWN_TICKS

        r._maybe_eat(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)

    def test_does_nothing_when_hp_is_fine(self):
        game = _make_game(tick=5, hp=15, widgets=[TROUT_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        result = _routine()._maybe_eat(game, ctrl)
        ctrl.click_widget.assert_not_called()
        assert result is False

    def test_returns_false_with_no_food_left(self):
        game = _make_game(tick=5, hp=4, widgets=[], inventory=[])
        ctrl = _ctrl()
        result = _routine()._maybe_eat(game, ctrl)
        ctrl.click_widget.assert_not_called()
        assert result is False


# ---------------------------------------------------------------------------
# looting — left-click only (no menu verification), whole 3x3 footprint
# ---------------------------------------------------------------------------

class TestLooting:
    def _looting_routine(self, death_tick: int = 10) -> BrutusFighterRoutine:
        r = _routine()
        r._target_pos = BRUTUS_SW
        r._death_tick = death_tick
        return r

    def test_left_clicks_item_anywhere_in_the_3x3_footprint(self):
        game = _make_game(tick=11, ground_items=[COINS_ON_BRUTUS_TILE])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.subscribe_to.assert_any_call(
            InteractionRoutine.LIVE_HULL_SUB_ID, "groundItem",
            name=COINS_ON_BRUTUS_TILE["name"], id=COINS_ON_BRUTUS_TILE["id"],
        )
        ctrl.click_entity.assert_called_once()
        # No menu verification gesture for looting Brutus's drops.
        ctrl.right_click_entity.assert_not_called()
        ctrl.click_menu_entry.assert_not_called()
        assert r._loot_target == COINS_ON_BRUTUS_TILE
        assert result is None

    def test_records_loot_unconditionally_after_the_click_tick(self):
        """Left-click looting is fire-and-forget — unlike the verified
        right-click gesture, there's no menu entry to confirm, so the item is
        marked looted on the tick after the click regardless of outcome."""
        game = _make_game(tick=12, ground_items=[COINS_ON_BRUTUS_TILE])
        ctrl = _ctrl()
        r = self._looting_routine()
        r._loot_target = COINS_ON_BRUTUS_TILE

        result = r.looting(game, ctrl)

        assert (COINS_ON_BRUTUS_TILE["id"], COINS_ON_BRUTUS_TILE["worldX"], COINS_ON_BRUTUS_TILE["worldY"]) in r._looted_keys
        assert r._loot_target is None
        assert result is None

    def test_ignores_items_outside_the_footprint(self):
        game = _make_game(tick=11, ground_items=[BONES_OFF_CORPSE_FOOTPRINT])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_does_not_reattempt_already_looted_item(self):
        game = _make_game(tick=11, ground_items=[COINS_ON_BRUTUS_TILE])
        ctrl = _ctrl()
        r = self._looting_routine()
        r._looted_keys = {(COINS_ON_BRUTUS_TILE["id"], COINS_ON_BRUTUS_TILE["worldX"], COINS_ON_BRUTUS_TILE["worldY"])}

        result = r.looting(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_eats_then_still_loots_in_the_same_tick_if_hp_drops(self):
        """Eating must not cost a tick before looting resumes — both the eat
        click and the loot click fire from within this single looting() call."""
        game = _make_game(tick=11, hp=3, ground_items=[COINS_ON_BRUTUS_TILE],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}],
                           widgets=[TROUT_SLOT])
        ctrl = _ctrl()
        r = self._looting_routine()

        result = r.looting(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)
        ctrl.click_entity.assert_called_once()
        assert r._loot_target == COINS_ON_BRUTUS_TILE
        assert result is None

    def test_returns_to_find_target_once_loot_window_elapses(self):
        game = _make_game(tick=15, ground_items=[])  # 15 - 10 = 5 >= LOOT_WINDOW_TICKS
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result == "find_target"

    def test_stays_looting_before_window_elapses(self):
        game = _make_game(tick=12, ground_items=[])  # 12 - 10 = 2 < LOOT_WINDOW_TICKS
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result is None
