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

from unittest.mock import MagicMock

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

    def test_redirects_to_healing_before_engaging_if_hp_is_low(self):
        game = _make_game(tick=3, hp=3, npcs=[BRUTUS],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        result = _routine().find_target(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result == "healing"


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

    def test_dodging_sets_combat_attention(self):
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS_TELEGRAPH_GROWL
        r._dodge_clicked = True
        r._dodge_tick = 5
        r.dodging(game, ctrl)
        ctrl.set_attention_level.assert_called_once_with("combat")

    def test_healing_sets_combat_attention(self):
        game = _make_game(tick=5, hp=4)
        ctrl = _ctrl()
        r = _routine()
        r._return_state = "fighting"
        r.healing(game, ctrl)
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
        assert result == "dodging"

    def test_dodges_on_snort_telegraph(self):
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_SNORT])
        result = self._engaged_routine().fighting(game, _ctrl())
        assert result == "dodging"

    def test_issues_dodge_click_immediately_on_telegraph_not_next_tick(self):
        """The dodge click must fire from within fighting() itself, the same
        tick the telegraph is seen — a Routine only re-evaluates its state
        once per tick (base.py), so deferring the click to the first tick of
        "dodging" would waste a full ~600ms tick of the 3-4 tick window."""
        r = self._engaged_routine()
        r._click_dodge_tile = MagicMock()
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])

        result = r.fighting(game, _ctrl())

        r._click_dodge_tile.assert_called_once()
        assert r._dodge_clicked is True
        assert r._dodge_tick == 5
        assert result == "dodging"

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
# dodging — sidestep then re-engage
# ---------------------------------------------------------------------------

class TestDodging:
    def _dodging_routine(self, dodge_tick: int = 5, dodge_clicked: bool = False) -> BrutusFighterRoutine:
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS_TELEGRAPH_GROWL
        r._dodge_clicked = dodge_clicked
        r._dodge_tick = dodge_tick
        return r

    def test_computes_tile_away_from_brutus_centre(self):
        # Brutus centre is (13279, 7229) — player one tile south-west of it.
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        r = self._dodging_routine()
        tile = r._compute_dodge_tile(game, _ctrl(), BRUTUS_TELEGRAPH_GROWL)
        # Player is south of centre (py < cy) and west of centre (px < cx) —
        # dodge should move further south-west, away from Brutus.
        assert tile == (game.player_pos[0] - 1, game.player_pos[1] - 1)

    def test_prefers_live_hull_position_over_stale_tick_position(self):
        game = _make_game(tick=5, player_x=13278, player_y=7227, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {"found": True, "worldX": 13300, "worldY": 7300}
        r = self._dodging_routine()
        tile = r._compute_dodge_tile(game, ctrl, BRUTUS_TELEGRAPH_GROWL)
        # Centre now far north-east at (13301, 7301) — player is south-west
        # of it, so the dodge tile must move further south-west from there.
        assert tile == (game.player_pos[0] - 1, game.player_pos[1] - 1)

    def test_first_tick_issues_dodge_click_and_does_not_reengage(self):
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)
        r._click_dodge_tile = MagicMock()

        result = r.dodging(game, ctrl)

        r._click_dodge_tile.assert_called_once()
        ctrl.click_entity.assert_not_called()
        assert r._dodge_clicked is True
        assert r._dodge_tick == 5
        assert result is None

    def test_waits_out_the_telegraph_window_before_reengaging(self):
        game = _make_game(tick=6, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        r = self._dodging_routine(dodge_tick=5, dodge_clicked=True)  # 1 tick elapsed < DODGE_WAIT_TICKS

        result = r.dodging(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_reengages_with_plain_left_click_once_window_elapses(self):
        game = _make_game(tick=7, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        r = self._dodging_routine(dodge_tick=5, dodge_clicked=True)  # 2 ticks elapsed == DODGE_WAIT_TICKS

        result = r.dodging(game, ctrl)

        ctrl.click_entity.assert_called_once()
        assert result == "fighting"
        assert r._dodge_clicked is False

    def test_stays_dodging_if_reengage_click_does_not_land(self):
        game = _make_game(tick=7, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.click_entity.return_value = False
        r = self._dodging_routine(dodge_tick=5, dodge_clicked=True)

        result = r.dodging(game, ctrl)

        assert result is None
        assert r._dodge_clicked is True

    def test_click_dodge_tile_subscribes_to_the_computed_tile(self):
        """The dodge click must register a `kind: "tile"` live-clickbox
        subscription on the computed tile coordinates — see
        GameController.subscribe_to_tile / GAMEBRIDGE.md."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)

        r.dodging(game, ctrl)

        ctrl.subscribe_to_tile.assert_called_once_with(
            BrutusFighterRoutine.DODGE_TILE_SUB_ID, game.player_pos[0] - 1, game.player_pos[1] - 1,
            game.plane, ttl_ticks=BrutusFighterRoutine.DODGE_TILE_SUB_TTL_TICKS,
        )

    def test_clicks_canvas_position_from_tile_hull_update_when_onscreen(self):
        """Once the tile subscription's hullUpdate shows it on-screen, click
        its real canvas position — never the minimap."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {
            "subId": BrutusFighterRoutine.DODGE_TILE_SUB_ID, "found": True,
            "onScreen": True, "canvasX": 386.0, "canvasY": 320.0,
        }
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)

        r.dodging(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_called_once_with(386.0, 320.0, game)

    def test_skips_click_without_minimap_fallback_when_tile_not_found(self):
        """No hullUpdate yet (or found: false) -> skip the click entirely.
        Must never fall back to a minimap click."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {"subId": BrutusFighterRoutine.DODGE_TILE_SUB_ID, "found": False}
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)

        r.dodging(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_not_called()

    def test_skips_click_without_minimap_fallback_when_tile_not_onscreen(self):
        """found: true but onScreen: false -> still skip, no minimap fallback."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = {
            "subId": BrutusFighterRoutine.DODGE_TILE_SUB_ID, "found": True,
            "onScreen": False, "canvasX": None, "canvasY": None,
        }
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)

        r.dodging(game, ctrl)

        ctrl.click_minimap_entity.assert_not_called()
        ctrl.click_walk_target.assert_not_called()

    def test_skips_click_when_no_hull_update_has_arrived_yet(self):
        """hull_update() returning None (subscription just registered, no
        push yet) must also be treated as skip-this-dodge, not an error."""
        game = _make_game(tick=5, npcs=[BRUTUS_TELEGRAPH_GROWL])
        ctrl = _ctrl()
        ctrl.hull_update.return_value = None
        r = self._dodging_routine(dodge_tick=-1, dodge_clicked=False)

        r.dodging(game, ctrl)

        ctrl.click_walk_target.assert_not_called()

    def test_transitions_to_looting_if_brutus_dies_mid_dodge(self):
        game = _make_game(tick=5, npcs=[])
        ctrl = _ctrl()
        r = self._dodging_routine()
        result = r.dodging(game, ctrl)
        assert result == "looting"
        assert r._dodge_clicked is False


# ---------------------------------------------------------------------------
# healing — eat below threshold, cooldown, resume interrupted state
# ---------------------------------------------------------------------------

class TestHealing:
    def test_needs_heal_false_above_threshold(self):
        game = _make_game(hp=10, inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        assert _routine()._needs_heal(game) is False

    def test_needs_heal_false_without_food(self):
        game = _make_game(hp=3, inventory=[])
        assert _routine()._needs_heal(game) is False

    def test_needs_heal_true_at_threshold_with_food(self):
        game = _make_game(hp=6, inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        assert _routine()._needs_heal(game) is True

    def test_fighting_redirects_to_healing_at_low_hp(self):
        game = _make_game(tick=5, hp=4, npcs=[BRUTUS_BASIC_SWING],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        r = _routine()
        r._target_index = BRUTUS["index"]
        r._target = BRUTUS
        r._fight_start_tick = 4
        result = r.fighting(game, _ctrl())
        assert result == "healing"
        assert r._return_state == "fighting"

    def test_eats_trout_then_salmon_when_trout_exhausted(self):
        game = _make_game(tick=5, hp=4, widgets=[SALMON_SLOT],
                           inventory=[{"slot": 1, "itemId": COOKED_SALMON, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()
        r._return_state = "fighting"

        result = r.healing(game, ctrl)

        ctrl.click_widget.assert_called_once_with(SALMON_SLOT)
        assert result == "fighting"

    def test_prefers_trout_when_both_present(self):
        game = _make_game(tick=5, hp=4, widgets=[TROUT_SLOT, SALMON_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1},
                                      {"slot": 1, "itemId": COOKED_SALMON, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()

        r.healing(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)

    def test_does_not_eat_again_within_cooldown(self):
        game = _make_game(tick=6, hp=4, widgets=[TROUT_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()
        r._last_eat_tick = 5  # 1 tick ago < EAT_COOLDOWN_TICKS

        r.healing(game, ctrl)

        ctrl.click_widget.assert_not_called()

    def test_eats_again_once_cooldown_elapses(self):
        game = _make_game(tick=8, hp=4, widgets=[TROUT_SLOT],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        ctrl = _ctrl()
        r = _routine()
        r._last_eat_tick = 5  # 3 ticks ago == EAT_COOLDOWN_TICKS

        r.healing(game, ctrl)

        ctrl.click_widget.assert_called_once_with(TROUT_SLOT)

    def test_returns_to_return_state_even_with_no_food_left(self):
        game = _make_game(tick=5, hp=4, widgets=[], inventory=[])
        r = _routine()
        r._return_state = "looting"
        result = r.healing(game, _ctrl())
        assert result == "looting"


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

    def test_redirects_to_healing_while_looting_if_hp_drops(self):
        game = _make_game(tick=11, hp=3, ground_items=[COINS_ON_BRUTUS_TILE],
                           inventory=[{"slot": 0, "itemId": COOKED_TROUT, "qty": 1}])
        r = self._looting_routine()
        result = r.looting(game, _ctrl())
        assert result == "healing"
        assert r._return_state == "looting"

    def test_returns_to_find_target_once_loot_window_elapses(self):
        game = _make_game(tick=15, ground_items=[])  # 15 - 10 = 5 >= LOOT_WINDOW_TICKS
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result == "find_target"

    def test_stays_looting_before_window_elapses(self):
        game = _make_game(tick=12, ground_items=[])  # 12 - 10 = 2 < LOOT_WINDOW_TICKS
        result = self._looting_routine(death_tick=10).looting(game, _ctrl())
        assert result is None
