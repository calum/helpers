"""
Tests for RodFishingRoutine.

Covers:
  - resume: full + raw fish → cooking; full + no raw fish → banking/
    walk_to_bank_fern/walk_to_bank_tree depending on position; not full →
    find_spot/walk_to_tree/walk_to_fern depending on distance to Tree
  - banking: no bankable items → walk_to_fern; cooked fish → opens bank; full
    deposit cycle; bank open after deposit → Escape; _batches_cooked reset
  - walk_to_fern: Tree on minimap → walk_to_tree; real Fern entity used when in range; synthetic fallback when out of range
  - walk_to_tree: player near Tree → find_spot; real Tree entity used when in range; synthetic fallback when out of range
  - find_spot: inventory full → cooking; no NPC → None; approach + click → fishing
  - fishing: inventory full → cooking; spot gone → find_spot; idle timeout → find_spot
  - cooking: batch 1 → drop_burnt; batch 2 → drop_and_return; dialog → Space;
    left-click fire directly; gesture guard prevents reclick; no fire → wait
  - drop_burnt: nothing to drop → find_spot
  - drop_and_return: nothing to drop → walk_to_bank_tree
  - walk_to_bank_tree: player y >= TREE_WORLD_Y → walk_to_bank_fern; real Tree entity used when in range; synthetic fallback
  - walk_to_bank_fern: player y >= FERN_WORLD_Y → banking; real Fern entity used when in range; synthetic fallback
  - _real_minimap_entity: exact tile match, no minimap coords, wrong tile, empty scene
  - _synthetic_minimap_entity: geometry and clamping
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock, call

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.rod_fishing import RodFishingRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine
from scripts.gamebridge.state.game_state import GameState

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EMPTY_INVENTORY = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
JUNK = 1931  # arbitrary real item id used to pad a full inventory


def _inv(*item_ids: int) -> list:
    slots = [{"slot": i, "itemId": iid, "qty": 1} for i, iid in enumerate(item_ids)]
    slots += [{"slot": i, "itemId": -1, "qty": 0} for i in range(len(item_ids), 28)]
    return slots


def _full_inv(*item_ids: int) -> list:
    slots = [{"slot": i, "itemId": iid, "qty": 1} for i, iid in enumerate(item_ids)]
    slots += [{"slot": i, "itemId": JUNK, "qty": 1} for i in range(len(item_ids), 28)]
    return slots


def _inv_widget(item_id: int, child_id: int = 0, x: int = 550, y: int = 210) -> dict:
    return {"groupId": 149, "childId": child_id, "itemId": item_id, "quantity": 1,
            "bounds": {"x": x, "y": y, "width": 32, "height": 32}, "text": ""}


def _make_game(
    tick: int = 100,
    player_x: int = 3100,
    player_y: int = 3425,
    inventory: list | None = None,
    npcs: list | None = None,
    objects: list | None = None,
    widgets: list | None = None,
    interfaces: list | None = None,
) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
    game.inventory = inventory if inventory is not None else list(EMPTY_INVENTORY)
    game.npcs = npcs if npcs is not None else []
    game.objects = objects if objects is not None else []
    game.widgets = widgets if widgets is not None else []
    game.interfaces = interfaces if interfaces is not None else []
    game.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 4.0}
    return game


class _AnyStr(str):
    def __contains__(self, item):
        return True

    def lower(self):
        return self


def _ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.tooltip.return_value = _AnyStr()
    return ctrl


def _routine() -> RodFishingRoutine:
    return RodFishingRoutine()


R = RodFishingRoutine  # shorthand for class constants

MINIMAP_WIDGET = {
    "groupId": 160, "childId": 0, "itemId": -1, "quantity": 0,
    "bounds": {"x": 550, "y": 30, "width": 150, "height": 150}, "text": "",
}

ROD_SPOT = {
    "id": 1525, "name": "Rod Fishing Spot", "index": 77,
    "worldX": 3104, "worldY": 3422, "plane": 0,
    "onScreen": True, "canvasX": 480, "canvasY": 320,
    "hull": [[470, 310], [490, 310], [490, 330], [470, 330]],
    "minimapX": 610, "minimapY": 95,
}

FIRE_NEAR = {
    "id": 26185, "name": "Fire",
    "worldX": 3101, "worldY": 3426, "plane": 0,  # 4 tiles away — within search radius
    "onScreen": True, "canvasX": 450, "canvasY": 300,
    "hull": [[440, 290], [460, 290], [460, 310], [440, 310]],
    "minimapX": 605, "minimapY": 92,
}

FIRE_FAR = {**FIRE_NEAR, "worldX": 3200, "worldY": 3400}  # > 8 tiles

FERN_OBJ_INRANGE = {
    "id": 1234, "name": "Fern",
    "worldX": 3098, "worldY": 3458, "plane": 0,
    "onScreen": False, "canvasX": None, "canvasY": None,
    "minimapX": 601, "minimapY": 68,
}

FERN_OBJ_OUTOFRANGE = {**FERN_OBJ_INRANGE, "minimapX": None, "minimapY": None}

TREE_OBJ_INRANGE = {
    "id": 1276, "name": "Tree",
    "worldX": 3100, "worldY": 3436, "plane": 0,
    "onScreen": False, "canvasX": None, "canvasY": None,
    "minimapX": 603, "minimapY": 75,
}

TREE_OBJ_OUTOFRANGE = {**TREE_OBJ_INRANGE, "minimapX": None, "minimapY": None}

BANK_BOOTH = {
    "id": 10355, "name": "Bank booth",
    "worldX": 3094, "worldY": 3494, "plane": 0,
    "onScreen": False, "canvasX": None, "canvasY": None,
    "minimapX": None, "minimapY": None,
}

COOK_DIALOG = {
    "groupId": 270, "childId": 38, "itemId": -1, "quantity": 0,
    "bounds": {"x": 400, "y": 250, "width": 200, "height": 30}, "text": "Cook 27 Raw Trout",
}


# ---------------------------------------------------------------------------
# resume (entry point)
# ---------------------------------------------------------------------------

class TestResume:
    def test_fresh_routine_starts_in_resume_state(self):
        assert _routine().current_state == "resume"

    def test_full_inventory_with_raw_fish_goes_to_cooking(self):
        game = _make_game(inventory=_full_inv(R.RAW_TROUT_ID))
        assert _routine().resume(game, _ctrl()) == "cooking"

    def test_full_inventory_with_raw_salmon_goes_to_cooking(self):
        game = _make_game(inventory=_full_inv(R.RAW_SALMON_ID))
        assert _routine().resume(game, _ctrl()) == "cooking"

    def test_full_inventory_no_raw_fish_near_bank_goes_to_banking(self):
        # player_y >= FERN_WORLD_Y (3458)
        game = _make_game(player_y=3460, inventory=_full_inv(R.COOKED_TROUT_ID))
        assert _routine().resume(game, _ctrl()) == "banking"

    def test_full_inventory_no_raw_fish_between_tree_and_fern_goes_to_walk_to_bank_fern(self):
        # TREE_WORLD_Y (3436) <= player_y < FERN_WORLD_Y (3458)
        game = _make_game(player_y=3440, inventory=_full_inv(R.COOKED_TROUT_ID))
        assert _routine().resume(game, _ctrl()) == "walk_to_bank_fern"

    def test_full_inventory_no_raw_fish_south_of_tree_goes_to_walk_to_bank_tree(self):
        # player_y < TREE_WORLD_Y (3436)
        game = _make_game(player_y=3420, inventory=_full_inv(R.COOKED_TROUT_ID))
        assert _routine().resume(game, _ctrl()) == "walk_to_bank_tree"

    def test_not_full_already_near_tree_goes_to_find_spot(self):
        # player at the Tree itself — within TREE_NEAR_TILES (12)
        game = _make_game(player_x=3100, player_y=3436)
        assert _routine().resume(game, _ctrl()) == "find_spot"

    def test_not_full_within_minimap_range_of_tree_goes_to_walk_to_tree(self):
        # 18 tiles from Tree (3100, 3436) — beyond TREE_NEAR_TILES, within MINIMAP_RANGE (20)
        game = _make_game(player_x=3100, player_y=3454)
        assert _routine().resume(game, _ctrl()) == "walk_to_tree"

    def test_not_full_far_from_tree_goes_to_walk_to_fern(self):
        # 34 tiles from Tree (3100, 3436) — beyond MINIMAP_RANGE
        game = _make_game(player_x=3100, player_y=3470)
        assert _routine().resume(game, _ctrl()) == "walk_to_fern"


# ---------------------------------------------------------------------------
# _resume_toward_bank / _resume_toward_spot
# ---------------------------------------------------------------------------

class TestResumeTowardBank:
    def test_at_fern_y_returns_banking(self):
        game = _make_game(player_y=3458)
        assert _routine()._resume_toward_bank(game) == "banking"

    def test_at_tree_y_returns_walk_to_bank_fern(self):
        game = _make_game(player_y=3436)
        assert _routine()._resume_toward_bank(game) == "walk_to_bank_fern"

    def test_south_of_tree_returns_walk_to_bank_tree(self):
        game = _make_game(player_y=3000)
        assert _routine()._resume_toward_bank(game) == "walk_to_bank_tree"


class TestResumeTowardSpot:
    def test_at_tree_near_threshold_returns_find_spot(self):
        # exactly TREE_NEAR_TILES (12) away
        game = _make_game(player_x=3100, player_y=3448)
        assert _routine()._resume_toward_spot(game) == "find_spot"

    def test_just_beyond_near_threshold_returns_walk_to_tree(self):
        # 13 tiles away — beyond TREE_NEAR_TILES, within MINIMAP_RANGE
        game = _make_game(player_x=3100, player_y=3449)
        assert _routine()._resume_toward_spot(game) == "walk_to_tree"

    def test_at_minimap_range_threshold_returns_walk_to_tree(self):
        # exactly MINIMAP_RANGE (20) away
        game = _make_game(player_x=3100, player_y=3456)
        assert _routine()._resume_toward_spot(game) == "walk_to_tree"

    def test_just_beyond_minimap_range_returns_walk_to_fern(self):
        # 21 tiles away — beyond MINIMAP_RANGE
        game = _make_game(player_x=3100, player_y=3457)
        assert _routine()._resume_toward_spot(game) == "walk_to_fern"


# ---------------------------------------------------------------------------
# banking
# ---------------------------------------------------------------------------

class TestBanking:
    def test_no_bankable_items_goes_to_walk_to_fern(self):
        game = _make_game(inventory=_inv(590))  # only tinderbox — not bankable
        r = _routine()
        assert r.banking(game, _ctrl()) == "walk_to_fern"

    def test_no_bankable_items_resets_batches_cooked(self):
        game = _make_game()
        r = _routine()
        r._batches_cooked = 2
        r.banking(game, _ctrl())
        assert r._batches_cooked == 0

    def test_no_bankable_bank_still_open_presses_escape_and_waits(self):
        game = _make_game(interfaces=[{"groupId": 12, "childId": 0, "itemId": -1,
                                       "bounds": {"x": 0, "y": 0, "width": 500, "height": 300},
                                       "text": ""}])
        ctrl = _ctrl()
        result = _routine().banking(game, ctrl)
        ctrl.press_key.assert_called_once_with(Key.ESCAPE)
        assert result is None

    def test_cooked_fish_in_inventory_opens_bank(self):
        game = _make_game(inventory=_inv(R.COOKED_TROUT_ID), objects=[BANK_BOOTH])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        r = _routine()
        result = r.banking(game, ctrl)
        assert result is None

    def test_raw_fish_in_inventory_triggers_banking(self):
        game = _make_game(inventory=_inv(R.RAW_TROUT_ID), objects=[BANK_BOOTH])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        assert _routine().banking(game, ctrl) is None

    def test_bank_open_with_fish_calls_deposit_inventory(self):
        bank_iface = {"groupId": 12, "childId": 0, "itemId": -1,
                      "bounds": {"x": 0, "y": 0, "width": 500, "height": 300}, "text": ""}
        deposit_btn = {"groupId": 12, "childId": 0x30, "itemId": -1,
                       "bounds": {"x": 100, "y": 250, "width": 80, "height": 20}, "text": ""}
        game = _make_game(inventory=_inv(R.COOKED_SALMON_ID),
                          interfaces=[bank_iface, deposit_btn])
        ctrl = _ctrl()
        r = _routine()
        r.banking(game, ctrl)
        ctrl.click_widget.assert_called()


# ---------------------------------------------------------------------------
# walk_to_fern
# ---------------------------------------------------------------------------

class TestWalkToFern:
    def test_within_minimap_range_of_tree_goes_to_walk_to_tree(self):
        # player at (3100, 3425): 11 tiles from Tree (3100, 3436) — within MINIMAP_RANGE=20
        game = _make_game(player_x=3100, player_y=3425)
        assert _routine().walk_to_fern(game, _ctrl()) == "walk_to_tree"

    def test_beyond_minimap_range_of_tree_issues_minimap_click(self):
        # player at (3100, 3470): 34 tiles from Tree (3100, 3436) — beyond
        # MINIMAP_RANGE=20 — and 14 tiles from Fern (3098, 3458) — beyond the
        # near-Fern shortcut's 4-tile threshold, so this should still walk.
        game = _make_game(player_x=3100, player_y=3470, interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        result = _routine().walk_to_fern(game, ctrl)
        ctrl.click_minimap_entity.assert_called_once()
        assert result is None

    def test_uses_real_fern_minimap_when_in_range(self):
        game = _make_game(player_x=3100, player_y=3470, objects=[FERN_OBJ_INRANGE])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_fern(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target is FERN_OBJ_INRANGE

    def test_falls_back_to_synthetic_when_fern_out_of_range(self):
        game = _make_game(player_x=3100, player_y=3470, objects=[FERN_OBJ_OUTOFRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_fern(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target["name"] == "waypoint"

    def test_no_minimap_widget_does_not_crash(self):
        game = _make_game(player_x=3100, player_y=3470, interfaces=[])
        _routine().walk_to_fern(game, _ctrl())  # should not raise

    def test_near_fern_but_far_from_tree_transitions_without_reclicking(self):
        # player at (3100, 3460): 4 tiles from Fern (3098, 3458) but 24 tiles
        # from Tree — beyond Fern alone would never satisfy the
        # within-MINIMAP_RANGE-of-Tree check, so this must transition to
        # walk_to_tree directly instead of re-clicking the same Fern tile.
        game = _make_game(player_x=3100, player_y=3460, interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        result = _routine().walk_to_fern(game, ctrl)
        ctrl.click_minimap_entity.assert_not_called()
        assert result == "walk_to_tree"


# ---------------------------------------------------------------------------
# walk_to_tree
# ---------------------------------------------------------------------------

class TestWalkToTree:
    def test_player_near_tree_goes_to_find_spot(self):
        # Player within 12 tiles of TREE (3100, 3436): player at (3102, 3438) = 4 tiles
        game = _make_game(player_x=3102, player_y=3438, objects=[TREE_OBJ_INRANGE],
                          interfaces=[MINIMAP_WIDGET])
        assert _routine().walk_to_tree(game, _ctrl()) == "find_spot"

    def test_player_far_issues_minimap_click(self):
        # Player at (3098, 3458) = 24 tiles from tree
        game = _make_game(player_x=3098, player_y=3458, objects=[TREE_OBJ_INRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        result = _routine().walk_to_tree(game, ctrl)
        ctrl.click_minimap_entity.assert_called_once()
        assert result is None

    def test_uses_real_tree_minimap_when_in_range(self):
        game = _make_game(player_x=3098, player_y=3458, objects=[TREE_OBJ_INRANGE])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_tree(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target is TREE_OBJ_INRANGE

    def test_falls_back_to_synthetic_when_tree_out_of_range(self):
        game = _make_game(player_x=3098, player_y=3458, objects=[TREE_OBJ_OUTOFRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_tree(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target["name"] == "waypoint"


# ---------------------------------------------------------------------------
# find_spot
# ---------------------------------------------------------------------------

class TestFindSpot:
    def test_inventory_full_goes_to_cooking(self):
        game = _make_game(inventory=_full_inv(R.RAW_TROUT_ID))
        assert _routine().find_spot(game, _ctrl()) == "cooking"

    def test_no_npc_in_scene_returns_none(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        result = _routine().find_spot(game, ctrl)
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_approach_settle_tick_before_clicking(self):
        game = _make_game(npcs=[ROD_SPOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()
        result = r.find_spot(game, ctrl)  # tick 100: settle buffer starts
        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_click_live_after_settle_transitions_to_fishing(self):
        game = _make_game(npcs=[ROD_SPOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_entity.return_value = True
        r = _routine()

        r.find_spot(game, ctrl)   # tick 100: settle buffer
        game.tick = 101
        result = r.find_spot(game, ctrl)  # tick 101: settled → click

        ctrl.click_entity.assert_called_once_with(
            ROD_SPOT,
            sub_id=InteractionRoutine.LIVE_HULL_SUB_ID,
            verify_name=ROD_SPOT["name"],
        )
        assert result == "fishing"
        assert r._spot_index == ROD_SPOT["index"]
        assert r._fish_start_tick == 101

    def test_click_live_false_stays_in_find_spot(self):
        game = _make_game(npcs=[ROD_SPOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        ctrl.click_entity.return_value = False
        r = _routine()

        r.find_spot(game, ctrl)   # settle
        game.tick = 101
        result = r.find_spot(game, ctrl)

        assert result is None


# ---------------------------------------------------------------------------
# fishing
# ---------------------------------------------------------------------------

class TestFishing:
    def _tracking(self, start_tick: int = 100) -> RodFishingRoutine:
        r = _routine()
        r._spot_index = ROD_SPOT["index"]
        r._fish_start_tick = start_tick
        return r

    def test_inventory_full_goes_to_cooking(self):
        game = _make_game(tick=105, inventory=_full_inv(R.RAW_TROUT_ID), npcs=[ROD_SPOT])
        assert self._tracking().fishing(game, _ctrl()) == "cooking"

    def test_spot_gone_retargets(self):
        game = _make_game(tick=105, npcs=[])
        assert self._tracking().fishing(game, _ctrl()) == "find_spot"

    def test_animating_resets_timer_and_stays(self):
        game = _make_game(tick=105, npcs=[ROD_SPOT])
        game.player["animation"] = 623  # fishing animation
        r = self._tracking(start_tick=100)
        assert r.fishing(game, _ctrl()) is None
        assert r._fish_start_tick == 105

    def test_idle_within_timeout_stays(self):
        game = _make_game(tick=104, npcs=[ROD_SPOT])
        assert self._tracking(start_tick=100).fishing(game, _ctrl()) is None

    def test_idle_past_timeout_retargets(self):
        game = _make_game(tick=106, npcs=[ROD_SPOT])
        assert self._tracking(start_tick=100).fishing(game, _ctrl()) == "find_spot"


# ---------------------------------------------------------------------------
# cooking
# ---------------------------------------------------------------------------

class TestCooking:
    def test_no_raw_fish_batch_1_goes_to_drop_burnt(self):
        game = _make_game(inventory=_inv(R.COOKED_TROUT_ID))
        r = _routine()
        r._batches_cooked = 0
        assert r.cooking(game, _ctrl()) == "drop_burnt"
        assert r._batches_cooked == 1

    def test_no_raw_fish_batch_2_goes_to_drop_and_return(self):
        game = _make_game(inventory=_inv(R.COOKED_TROUT_ID))
        r = _routine()
        r._batches_cooked = 1
        assert r.cooking(game, _ctrl()) == "drop_and_return"
        assert r._batches_cooked == 2

    def test_dialog_open_presses_space(self):
        game = _make_game(tick=120, inventory=_inv(R.RAW_TROUT_ID),
                          interfaces=[COOK_DIALOG])
        ctrl = _ctrl()
        r = _routine()

        result = r.cooking(game, ctrl)

        ctrl.press_key.assert_called_once_with(Key.SPACE)
        assert r._cook_started_tick == 120
        assert result is None

    def test_clicks_fire_directly_after_approach_settles(self):
        game = _make_game(tick=120, inventory=_inv(R.RAW_TROUT_ID), objects=[FIRE_NEAR])
        ctrl = _ctrl()
        ctrl.click_entity.return_value = True
        r = _routine()

        r.cooking(game, ctrl)  # tick 120: approach settle buffer — no click yet
        ctrl.click_entity.assert_not_called()

        game.tick = 121
        r.cooking(game, ctrl)  # tick 121: settled — click fires

        ctrl.click_entity.assert_called_once_with(
            FIRE_NEAR,
            sub_id=InteractionRoutine.LIVE_HULL_SUB_ID,
            verify_name=FIRE_NEAR["name"],
        )
        assert r._cook_started_tick == 121

    def test_fire_off_screen_does_not_click_or_mark_gesture_started(self):
        """Regression: clicking the fire without first calling `approach` meant
        an off-screen fire (the common case right after leaving the fishing
        spot) was clicked blindly and never actually reached — the routine
        would mark the gesture as started and stall forever waiting for a
        dialog that could never open."""
        game = _make_game(tick=120, inventory=_inv(R.RAW_TROUT_ID), objects=[FIRE_NEAR])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        r = _routine()

        result = r.cooking(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None
        assert r._cook_started_tick is None

    def test_gesture_guard_prevents_early_reclick(self):
        game = _make_game(tick=122, inventory=_inv(R.RAW_TROUT_ID), objects=[FIRE_NEAR])
        game.player["animation"] = 897  # cooking animation
        ctrl = _ctrl()
        r = _routine()
        r._cook_started_tick = 120

        result = r.cooking(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_no_fire_in_range_waits(self):
        game = _make_game(inventory=_inv(R.RAW_TROUT_ID), objects=[FIRE_FAR])
        ctrl = _ctrl()

        result = _routine().cooking(game, ctrl)

        ctrl.click_entity.assert_not_called()
        assert result is None

    def test_fire_clicked_when_raw_fish_present_and_no_dialog(self):
        game = _make_game(tick=120, inventory=_inv(R.RAW_TROUT_ID), objects=[FIRE_NEAR],
                          interfaces=[])
        ctrl = _ctrl()
        r = _routine()

        r.cooking(game, ctrl)  # settle
        game.tick = 121
        r.cooking(game, ctrl)  # click

        ctrl.click_entity.assert_called_once()

    def test_resets_cook_started_tick_on_transition_out(self):
        game = _make_game(inventory=_inv(R.COOKED_TROUT_ID))
        r = _routine()
        r._cook_started_tick = 95
        r._batches_cooked = 0

        r.cooking(game, _ctrl())

        assert r._cook_started_tick is None


# ---------------------------------------------------------------------------
# drop_burnt / drop_and_return
# ---------------------------------------------------------------------------

class TestDropBurnt:
    def test_no_burnt_fish_goes_to_find_spot(self):
        game = _make_game(widgets=[_inv_widget(R.COOKED_TROUT_ID)])
        assert _routine().drop_burnt(game, _ctrl()) == "find_spot"

    def test_holds_shift_and_drops_burnt(self):
        burnt = _inv_widget(R.BURNT_FISH_ID, child_id=3)
        game = _make_game(widgets=[burnt])
        ctrl = _ctrl()

        result = _routine().drop_burnt(game, ctrl)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(burnt)
        assert result is None


class TestDropAndReturn:
    def test_nothing_to_drop_goes_to_walk_to_bank_tree(self):
        game = _make_game(widgets=[_inv_widget(R.COOKED_TROUT_ID)])
        assert _routine().drop_and_return(game, _ctrl()) == "walk_to_bank_tree"

    def test_drops_raw_trout(self):
        raw = _inv_widget(R.RAW_TROUT_ID, child_id=1)
        game = _make_game(widgets=[raw])
        ctrl = _ctrl()
        result = _routine().drop_and_return(game, ctrl)
        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(raw)
        assert result is None

    def test_drops_raw_salmon(self):
        raw = _inv_widget(R.RAW_SALMON_ID, child_id=2)
        game = _make_game(widgets=[raw])
        ctrl = _ctrl()
        _routine().drop_and_return(game, ctrl)
        ctrl.click_widget.assert_called_once_with(raw)

    def test_drops_burnt_fish(self):
        burnt = _inv_widget(R.BURNT_FISH_ID, child_id=5)
        game = _make_game(widgets=[burnt])
        ctrl = _ctrl()
        _routine().drop_and_return(game, ctrl)
        ctrl.click_widget.assert_called_once_with(burnt)

    def test_cooked_fish_not_dropped(self):
        cooked = _inv_widget(R.COOKED_TROUT_ID, child_id=0)
        game = _make_game(widgets=[cooked])
        ctrl = _ctrl()
        result = _routine().drop_and_return(game, ctrl)
        ctrl.click_widget.assert_not_called()
        assert result == "walk_to_bank_tree"


# ---------------------------------------------------------------------------
# walk_to_bank_tree / walk_to_bank_fern
# ---------------------------------------------------------------------------

class TestWalkToBankTree:
    def test_player_north_of_tree_goes_to_walk_to_bank_fern(self):
        # player_y >= TREE_WORLD_Y (3436)
        game = _make_game(player_y=3436)
        assert _routine().walk_to_bank_tree(game, _ctrl()) == "walk_to_bank_fern"

    def test_player_south_of_tree_issues_minimap_click(self):
        # player_y < 3436
        game = _make_game(player_y=3420, objects=[TREE_OBJ_INRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        result = _routine().walk_to_bank_tree(game, ctrl)
        ctrl.click_minimap_entity.assert_called_once()
        assert result is None

    def test_uses_real_tree_minimap_when_in_range(self):
        # walk_to_bank_tree aims 5 tiles past the Tree (TREE_WORLD_Y + 5) to
        # avoid oscillating right at the boundary, so the matching real
        # entity must sit at that tile, not the Tree's own coordinates.
        waypoint_obj = {**TREE_OBJ_INRANGE, "worldY": R.TREE_WORLD_Y + 5}
        game = _make_game(player_y=3420, objects=[waypoint_obj])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_bank_tree(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target is waypoint_obj

    def test_falls_back_to_synthetic_when_tree_out_of_range(self):
        game = _make_game(player_y=3420, objects=[TREE_OBJ_OUTOFRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_bank_tree(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target["name"] == "waypoint"


class TestWalkToBankFern:
    def test_player_north_of_fern_goes_to_banking(self):
        game = _make_game(player_y=3458)
        assert _routine().walk_to_bank_fern(game, _ctrl()) == "banking"

    def test_player_south_of_fern_issues_minimap_click(self):
        game = _make_game(player_y=3438, objects=[FERN_OBJ_INRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        result = _routine().walk_to_bank_fern(game, ctrl)
        ctrl.click_minimap_entity.assert_called_once()
        assert result is None

    def test_uses_real_fern_minimap_when_in_range(self):
        # walk_to_bank_fern aims 5 tiles past the Fern (FERN_WORLD_Y + 5) to
        # avoid oscillating right at the boundary, so the matching real
        # entity must sit at that tile, not the Fern's own coordinates.
        waypoint_obj = {**FERN_OBJ_INRANGE, "worldY": R.FERN_WORLD_Y + 5}
        game = _make_game(player_y=3438, objects=[waypoint_obj])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_bank_fern(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target is waypoint_obj

    def test_falls_back_to_synthetic_when_fern_out_of_range(self):
        game = _make_game(player_y=3438, objects=[FERN_OBJ_OUTOFRANGE],
                          interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        _routine().walk_to_bank_fern(game, ctrl)
        target, _ = ctrl.click_minimap_entity.call_args.args
        assert target["name"] == "waypoint"


# ---------------------------------------------------------------------------
# _synthetic_minimap_entity — geometry
# ---------------------------------------------------------------------------

class TestSyntheticMinimapEntity:
    def test_returns_none_without_minimap_widget(self):
        game = _make_game(interfaces=[])
        assert _routine()._synthetic_minimap_entity(game, 3100, 3450) is None

    def test_target_directly_north_has_lower_canvas_y(self):
        # player at (3100, 3440), target at (3100, 3460) — 20 tiles north
        game = _make_game(player_x=3100, player_y=3440, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        entity = r._synthetic_minimap_entity(game, 3100, 3460)
        assert entity is not None
        b = MINIMAP_WIDGET["bounds"]
        cy = b["y"] + b["height"] / 2
        assert entity["minimapY"] < cy  # north = up = lower canvas Y

    def test_target_directly_south_has_higher_canvas_y(self):
        game = _make_game(player_x=3100, player_y=3460, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        entity = r._synthetic_minimap_entity(game, 3100, 3440)
        b = MINIMAP_WIDGET["bounds"]
        cy = b["y"] + b["height"] / 2
        assert entity["minimapY"] > cy

    def test_very_distant_target_is_clamped_within_radius(self):
        # 1000 tiles away — should be clamped to ~90% of half_extent
        game = _make_game(player_x=3100, player_y=3200, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        entity = r._synthetic_minimap_entity(game, 3100, 4200)
        assert entity is not None
        b = MINIMAP_WIDGET["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        half_extent = min(b["width"], b["height"]) / 2
        dist = math.sqrt((entity["minimapX"] - cx) ** 2 + (entity["minimapY"] - cy) ** 2)
        assert dist <= half_extent + 1e-6

    def test_nearby_target_not_clamped(self):
        # 5 tiles north — well inside the 20-tile minimap radius
        game = _make_game(player_x=3100, player_y=3435, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        entity = r._synthetic_minimap_entity(game, 3100, 3440)
        b = MINIMAP_WIDGET["bounds"]
        cx = b["x"] + b["width"] / 2
        half_extent = min(b["width"], b["height"]) / 2
        dist_x = abs(entity["minimapX"] - cx)
        assert dist_x < half_extent * 0.9  # not pushed to the edge

    def test_returns_none_without_camera(self):
        game = _make_game(interfaces=[MINIMAP_WIDGET])
        game.camera = {}
        assert _routine()._synthetic_minimap_entity(game, 3100, 3460) is None

    def test_rotated_compass_shifts_target_off_the_north_south_axis(self):
        # Player at (3100, 3440), target due north at (3100, 3450) — with the
        # compass facing west (yawTarget=512) the minimap is rotated 90°, so
        # a due-north target lands offset in X, not Y. The old north-up-only
        # formula would have placed this directly above centre regardless of
        # compass orientation — exactly the bug this conversion fixes.
        game = _make_game(player_x=3100, player_y=3440, interfaces=[MINIMAP_WIDGET])
        game.camera = {"yaw": 512, "yawTarget": 512, "pitch": 256, "minimapZoom": 4.0}
        r = _routine()
        entity = r._synthetic_minimap_entity(game, 3100, 3450)
        b = MINIMAP_WIDGET["bounds"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        assert entity["minimapX"] - cx == pytest.approx(40.0)
        assert entity["minimapY"] - cy == pytest.approx(0.0, abs=1e-6)

    def test_minimap_zoom_scales_offset_distance(self):
        # Same 20-tile-north target at two different zoom levels should
        # produce proportionally different pixel offsets.
        game_zoomed_in = _make_game(player_x=3100, player_y=3440, interfaces=[MINIMAP_WIDGET])
        game_zoomed_in.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 2.0}
        entity_zoomed_in = _routine()._synthetic_minimap_entity(game_zoomed_in, 3100, 3450)

        game_zoomed_out = _make_game(player_x=3100, player_y=3440, interfaces=[MINIMAP_WIDGET])
        game_zoomed_out.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 4.0}
        entity_zoomed_out = _routine()._synthetic_minimap_entity(game_zoomed_out, 3100, 3450)

        b = MINIMAP_WIDGET["bounds"]
        cy = b["y"] + b["height"] / 2
        dist_zoomed_in = abs(entity_zoomed_in["minimapY"] - cy)
        dist_zoomed_out = abs(entity_zoomed_out["minimapY"] - cy)
        assert dist_zoomed_out == pytest.approx(dist_zoomed_in * 2)


# ---------------------------------------------------------------------------
# _real_minimap_entity
# ---------------------------------------------------------------------------

class TestRealMinimapEntity:
    def test_returns_object_at_exact_tile_with_minimap_coords(self):
        game = _make_game(objects=[FERN_OBJ_INRANGE])
        assert _routine()._real_minimap_entity(game, 3098, 3458) is FERN_OBJ_INRANGE

    def test_returns_none_when_object_has_no_minimap_coords(self):
        game = _make_game(objects=[FERN_OBJ_OUTOFRANGE])
        assert _routine()._real_minimap_entity(game, 3098, 3458) is None

    def test_returns_none_when_no_object_at_tile(self):
        game = _make_game(objects=[FERN_OBJ_INRANGE])
        assert _routine()._real_minimap_entity(game, 3100, 3436) is None  # different tile

    def test_returns_none_when_objects_empty(self):
        game = _make_game(objects=[])
        assert _routine()._real_minimap_entity(game, 3098, 3458) is None

    def test_ignores_objects_at_different_y(self):
        obj = {**FERN_OBJ_INRANGE, "worldY": 3459}
        game = _make_game(objects=[obj])
        assert _routine()._real_minimap_entity(game, 3098, 3458) is None

    def test_ignores_objects_at_different_x(self):
        obj = {**FERN_OBJ_INRANGE, "worldX": 3099}
        game = _make_game(objects=[obj])
        assert _routine()._real_minimap_entity(game, 3098, 3458) is None
