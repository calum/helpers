"""
Tests for the FishAndCookRoutine state machine.

Covers:
  - find_spot: target selection + "verify before you click" (mirrors melee_fighter's find_target)
  - fishing: inventory-full branching (logs present/absent), spot tracking by
    unique index, idle re-click timeout
  - find_fire: reusing a Fire already standing within FIRE_SEARCH_RADIUS
    tiles (walk to it / cook immediately if adjacent), falling back to
    step_aside when nothing is in range
  - step_aside: one minimap-walk gesture, settle-then-advance
  - light_fire: two-tick "use logs on tinderbox" gesture, out-of-logs guard
  - confirm_fire: xp-then-settle wait, fire detection, retry on failure
  - cooking: one "use fish on fire" gesture per raw-fish type, Space on the
    Skillmulti dialog, waiting for a batch to finish before the next gesture,
    and re-finding a fire if it despawns mid-batch with raw fish remaining
  - dropping: shift-held, one click per item (DropMode.SHIFT_CLICK)
  - stopped: terminal state
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.fish_and_cook import FishAndCookRoutine
from scripts.gamebridge.routines.interaction import InteractionRoutine
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_INVENTORY_RAW_SHRIMP = [{"slot": i, "itemId": 317, "qty": 1} for i in range(28)]
EMPTY_INVENTORY = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]


def _make_game(
    tick: int = 100,
    player_x: int = 3220,
    player_y: int = 3218,
    inventory: list | None = None,
    npcs: list | None = None,
    objects: list | None = None,
    widgets: list | None = None,
    interfaces: list | None = None,
    last_xp_tick: dict | None = None,
) -> GameState:
    game = GameState()
    game.tick = tick
    game.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
    game.inventory = inventory if inventory is not None else [dict(s) for s in EMPTY_INVENTORY]
    game.npcs = npcs if npcs is not None else []
    game.objects = objects if objects is not None else []
    game.widgets = widgets if widgets is not None else []
    game.interfaces = interfaces if interfaces is not None else []
    game.camera = {"yaw": 0, "pitch": 256}
    game.last_xp_tick = last_xp_tick if last_xp_tick is not None else {}
    return game


def _ctrl() -> MagicMock:
    return MagicMock()


def _routine() -> FishAndCookRoutine:
    return FishAndCookRoutine()


def _inventory_with(*item_ids: int) -> list:
    """28 slots — the given item ids first, the rest empty."""
    slots = [{"slot": i, "itemId": item_id, "qty": 1} for i, item_id in enumerate(item_ids)]
    slots += [{"slot": i, "itemId": -1, "qty": 0} for i in range(len(item_ids), 28)]
    return slots


JUNK_ITEM_ID = 1931  # arbitrary real item id used purely to pad a "full inventory" out to 28 slots


def _full_inventory_with(*item_ids: int) -> list:
    """28 slots, every one occupied — the given item ids first, padded out with junk."""
    slots = [{"slot": i, "itemId": item_id, "qty": 1} for i, item_id in enumerate(item_ids)]
    slots += [{"slot": i, "itemId": JUNK_ITEM_ID, "qty": 1} for i in range(len(item_ids), 28)]
    return slots


def _inv_widget(item_id: int, child_id: int = 0, x: int = 550, y: int = 210) -> dict:
    return {"groupId": 149, "childId": child_id, "itemId": item_id, "quantity": 1,
            "bounds": {"x": x, "y": y, "width": 32, "height": 32}, "text": ""}


SPOT = {
    "id": 1530, "name": "Fishing spot", "index": 55,
    "worldX": 3243, "worldY": 3148, "plane": 0,
    "onScreen": True, "canvasX": 480, "canvasY": 320,
    "hull": [[470, 310], [490, 310], [490, 330], [470, 330]],
}

FIRE = {
    "id": 26185, "name": "Fire", "worldX": 3220, "worldY": 3219, "plane": 0,
    "onScreen": True, "canvasX": 450, "canvasY": 300,
    "hull": [[440, 290], [460, 290], [460, 310], [440, 310]],
}

FIRE_FAR = {**FIRE, "worldX": 3300, "worldY": 3300}

FIRE_NEARBY = {**FIRE, "worldX": 3225, "worldY": 3218}  # 5 tiles away — within search radius, not adjacent

MINIMAP_WIDGET = {
    "groupId": 160, "childId": 0, "itemId": -1, "quantity": 0,
    "bounds": {"x": 550, "y": 30, "width": 150, "height": 150}, "text": "",
}

COOK_DIALOG_INTERFACE = {
    "groupId": 270, "childId": 38, "itemId": -1, "quantity": 0,
    "bounds": {"x": 400, "y": 250, "width": 200, "height": 30}, "text": "Cook 27 Raw shrimps",
}


# ---------------------------------------------------------------------------
# find_spot — target selection + "verify before you click"
# ---------------------------------------------------------------------------

class TestFindSpotInventoryBranches:
    def test_full_with_logs_goes_to_find_fire(self):
        game = _make_game(inventory=_full_inventory_with(590, 1511))
        assert _routine().find_spot(game, _ctrl()) == "find_fire"

    def test_full_without_logs_also_goes_to_find_fire(self):
        """find_spot no longer special-cases missing logs — find_fire decides
        whether to cook (fire reused/lit) or drop the raw catch instead."""
        game = _make_game(inventory=_full_inventory_with(590, 315, 315))
        assert _routine().find_spot(game, _ctrl()) == "find_fire"

    def test_full_check_short_circuits_targeting(self):
        """Inventory-full branch must win even with a spot in the scene — no clicks issued."""
        game = _make_game(inventory=_full_inventory_with(590, 1511), npcs=[SPOT])
        ctrl = _ctrl()
        _routine().find_spot(game, ctrl)
        ctrl.right_click_entity.assert_not_called()


class TestFindSpotTargeting:
    def test_no_click_when_no_spot_in_scene(self):
        game = _make_game(npcs=[])
        ctrl = _ctrl()
        result = _routine().find_spot(game, ctrl)
        ctrl.right_click_entity.assert_not_called()
        assert result is None

    def test_right_clicks_nearest_spot_once_settled(self):
        game = _make_game(npcs=[SPOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_spot(game, ctrl)            # tick 100: idle-settle buffer starts
        game.tick = 101
        r.find_spot(game, ctrl)            # tick 101: settled — right-click issued

        ctrl.right_click_entity.assert_called_once_with(SPOT, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._spot_target == SPOT


class TestFindSpotMenuVerification:
    def _mid_gesture_routine(self) -> FishAndCookRoutine:
        r = _routine()
        r._spot_target = SPOT
        return r

    def test_pending_menu_keeps_gesture_alive(self):
        game = _make_game(tick=5)
        game.menu = {"open": True, "entries": []}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        r = self._mid_gesture_routine()

        result = r.find_spot(game, ctrl)

        assert r._spot_target == SPOT
        assert result is None

    def test_abandons_when_menu_closes_without_a_match(self):
        game = _make_game(tick=5)
        game.menu = {"open": False, "entries": []}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = False
        r = self._mid_gesture_routine()

        result = r.find_spot(game, ctrl)

        assert r._spot_target is None
        assert result is None

    def test_confirmed_click_commits_and_starts_fishing(self):
        game = _make_game(tick=5)
        game.menu = {"open": True, "entries": [
            {"option": "Net", "target": "Fishing spot",
             "bounds": {"x": 100, "y": 50, "width": 80, "height": 15}},
        ]}
        ctrl = _ctrl()
        ctrl.click_menu_entry.return_value = True
        r = self._mid_gesture_routine()

        result = r.find_spot(game, ctrl)

        ctrl.click_menu_entry.assert_called_once_with(game, "Net", r.FISHING_SPOT_NAME)
        assert result == "fishing"
        assert r._spot_index == SPOT["index"]
        assert r._fish_start_tick == 5
        assert r._spot_target is None


# ---------------------------------------------------------------------------
# fishing — wait for the inventory to fill, tracking the spot by index
# ---------------------------------------------------------------------------

class TestFishing:
    def _routine_tracking(self) -> FishAndCookRoutine:
        r = _routine()
        r._spot_index = SPOT["index"]
        r._fish_start_tick = 100
        return r

    def test_full_with_logs_goes_to_find_fire(self):
        game = _make_game(tick=105, inventory=_full_inventory_with(590, 1511), npcs=[SPOT])
        assert self._routine_tracking().fishing(game, _ctrl()) == "find_fire"

    def test_full_without_logs_also_goes_to_find_fire(self):
        """fishing no longer special-cases missing logs — find_fire decides
        whether to cook (fire reused/lit) or drop the raw catch instead."""
        game = _make_game(tick=105, inventory=_full_inventory_with(590, 315), npcs=[SPOT])
        assert self._routine_tracking().fishing(game, _ctrl()) == "find_fire"

    def test_spot_gone_retargets(self):
        game = _make_game(tick=105, npcs=[])
        assert self._routine_tracking().fishing(game, _ctrl()) == "find_spot"

    def test_animating_resets_idle_timer_and_stays(self):
        game = _make_game(tick=105, npcs=[SPOT])
        game.player["animation"] = 619  # netting animation
        r = self._routine_tracking()

        result = r.fishing(game, _ctrl())

        assert result is None
        assert r._fish_start_tick == 105

    def test_idle_within_timeout_stays(self):
        game = _make_game(tick=104, npcs=[SPOT])  # 4 ticks idle — under the 6-tick timeout
        r = self._routine_tracking()
        assert r.fishing(game, _ctrl()) is None
        assert r._fish_start_tick == 100

    def test_idle_past_timeout_retargets(self):
        game = _make_game(tick=106, npcs=[SPOT])  # 6 ticks idle — at the timeout
        assert self._routine_tracking().fishing(game, _ctrl()) == "find_spot"


# ---------------------------------------------------------------------------
# find_fire — reuse a Fire already standing nearby instead of lighting our own
# ---------------------------------------------------------------------------

class TestFindFire:
    def test_no_fire_in_scene_lights_own(self):
        game = _make_game(objects=[], inventory=_inventory_with(FishAndCookRoutine.LOGS_ID))
        assert _routine().find_fire(game, _ctrl()) == "step_aside"

    def test_fire_beyond_search_radius_lights_own(self):
        game = _make_game(objects=[FIRE_FAR], inventory=_inventory_with(FishAndCookRoutine.LOGS_ID))
        assert _routine().find_fire(game, _ctrl()) == "step_aside"

    def test_adjacent_fire_in_range_starts_cooking(self):
        game = _make_game(objects=[FIRE])
        ctrl = _ctrl()

        result = _routine().find_fire(game, ctrl)

        assert result == "cooking"
        ctrl.click_entity.assert_not_called()

    def test_walks_to_a_fire_in_range_but_not_adjacent(self):
        game = _make_game(tick=1, objects=[FIRE_NEARBY])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        result = r.find_fire(game, ctrl)        # tick 1: idle-settle buffer starts
        ctrl.click_entity.assert_not_called()
        assert result is None

        game.tick = 2
        result = r.find_fire(game, ctrl)        # tick 2: settled — clicks to walk over
        ctrl.click_entity.assert_called_once_with(FIRE_NEARBY, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert result is None

    def test_picks_the_nearest_fire_in_range(self):
        farther = {**FIRE_NEARBY, "worldX": 3228}  # 8 tiles away — also in range
        game = _make_game(objects=[farther, FIRE_NEARBY])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True

        _routine().find_fire(game, ctrl)

        assert ctrl.bring_entity_on_screen.call_args.args[0] == FIRE_NEARBY


class TestNearestFireInRange:
    def test_returns_none_when_nothing_in_range(self):
        game = _make_game(objects=[FIRE_FAR])
        assert _routine()._nearest_fire_in_range(game) is None

    def test_returns_nearest_within_radius(self):
        farther = {**FIRE_NEARBY, "worldX": 3228}
        game = _make_game(objects=[FIRE_FAR, farther, FIRE_NEARBY])
        assert _routine()._nearest_fire_in_range(game) == FIRE_NEARBY


class TestFindFireNoLogs:
    """No Fire nearby and nothing to light one with — drop the raw catch
    instead of getting stuck (the routine no longer stops outright)."""

    def test_no_fire_no_logs_drops_raw_fish(self):
        game = _make_game(objects=[], inventory=_inventory_with(FishAndCookRoutine.RAW_SHRIMP_ID))
        assert _routine().find_fire(game, _ctrl()) == "dropping"

    def test_fire_beyond_search_radius_no_logs_drops_raw_fish(self):
        game = _make_game(objects=[FIRE_FAR], inventory=_inventory_with(FishAndCookRoutine.RAW_SHRIMP_ID))
        assert _routine().find_fire(game, _ctrl()) == "dropping"

    def test_fire_in_range_still_cooks_even_without_logs(self):
        """A reusable Fire doesn't need logs at all — cook regardless."""
        game = _make_game(objects=[FIRE], inventory=_inventory_with(FishAndCookRoutine.RAW_SHRIMP_ID))
        assert _routine().find_fire(game, _ctrl()) == "cooking"


# ---------------------------------------------------------------------------
# step_aside — one minimap-walk gesture, then settle before lighting a fire
# ---------------------------------------------------------------------------

class TestStepAside:
    def test_no_minimap_does_not_record_a_click(self):
        game = _make_game(tick=100, interfaces=[])
        r = _routine()
        r.step_aside(game, _ctrl())
        assert r._step_clicked_tick is None

    def test_issues_one_walk_and_records_the_tick(self):
        game = _make_game(tick=100, interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True
        r = _routine()

        result = r.step_aside(game, ctrl)

        ctrl.click_minimap_entity.assert_called_once()
        assert r._step_clicked_tick == 100
        assert result is None

    def test_does_not_advance_before_min_ticks_even_if_idle(self):
        game = _make_game(tick=101, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        r._step_clicked_tick = 100
        assert r.step_aside(game, _ctrl()) is None

    def test_does_not_advance_while_still_moving(self):
        game = _make_game(tick=103, interfaces=[MINIMAP_WIDGET])
        game.player["animation"] = 1   # not idle — still walking
        r = _routine()
        r._step_clicked_tick = 100
        assert r.step_aside(game, _ctrl()) is None

    def test_advances_to_light_fire_once_settled(self):
        game = _make_game(tick=103, interfaces=[MINIMAP_WIDGET])
        r = _routine()
        r._step_clicked_tick = 100

        result = r.step_aside(game, _ctrl())

        assert result == "light_fire"
        assert r._step_clicked_tick is None


class TestWalkToRandomNearbyTile:
    def test_returns_false_without_a_minimap(self):
        game = _make_game(interfaces=[])
        assert _routine()._walk_to_random_nearby_tile(game, _ctrl()) is False

    def test_clicks_a_point_within_the_minimap_bounds(self):
        game = _make_game(interfaces=[MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True

        result = _routine()._walk_to_random_nearby_tile(game, ctrl)

        assert result is True
        ctrl.click_minimap_entity.assert_called_once()
        target, passed_game = ctrl.click_minimap_entity.call_args.args
        assert passed_game is game

        b = MINIMAP_WIDGET["bounds"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        max_radius = FishAndCookRoutine.RANDOM_STEP_MAX_RATIO * (min(b["width"], b["height"]) / 2)
        assert abs(target["minimapX"] - cx) <= max_radius + 1e-6
        assert abs(target["minimapY"] - cy) <= max_radius + 1e-6

    def test_picks_the_largest_widget_in_the_group(self):
        small = {**MINIMAP_WIDGET, "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}}
        game = _make_game(interfaces=[small, MINIMAP_WIDGET])
        ctrl = _ctrl()
        ctrl.click_minimap_entity.return_value = True

        _routine()._walk_to_random_nearby_tile(game, ctrl)

        target, _ = ctrl.click_minimap_entity.call_args.args
        b = MINIMAP_WIDGET["bounds"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        # Within the larger widget's radius — couldn't be if the 10x10 one had been picked.
        assert abs(target["minimapX"] - cx) < b["width"] / 2
        assert abs(target["minimapY"] - cy) < b["height"] / 2


# ---------------------------------------------------------------------------
# light_fire — "use logs on tinderbox", spread across two ticks
# ---------------------------------------------------------------------------

class TestLightFire:
    def test_no_logs_stops(self):
        game = _make_game(inventory=_inventory_with(590))
        assert _routine().light_fire(game, _ctrl()) == "stopped"

    def test_first_tick_selects_logs(self):
        logs_widget = _inv_widget(1511, child_id=1)
        game = _make_game(inventory=_inventory_with(590, 1511),
                          widgets=[_inv_widget(590, child_id=0), logs_widget])
        ctrl = _ctrl()
        r = _routine()

        result = r.light_fire(game, ctrl)

        ctrl.click_widget.assert_called_once_with(logs_widget)
        assert r._used_logs is True
        assert result is None

    def test_second_tick_selects_tinderbox_and_advances(self):
        tinderbox_widget = _inv_widget(590, child_id=0)
        game = _make_game(tick=200, inventory=_inventory_with(590, 1511),
                          widgets=[tinderbox_widget, _inv_widget(1511, child_id=1)])
        ctrl = _ctrl()
        r = _routine()
        r._used_logs = True

        result = r.light_fire(game, ctrl)

        ctrl.click_widget.assert_called_once_with(tinderbox_widget)
        assert r._used_logs is False
        assert r._fire_attempt_tick == 200
        assert result == "confirm_fire"

    def test_does_not_advance_until_tinderbox_widget_is_found(self):
        game = _make_game(inventory=_inventory_with(590, 1511), widgets=[])
        r = _routine()
        r._used_logs = True

        result = r.light_fire(game, _ctrl())

        assert r._used_logs is True
        assert result is None


# ---------------------------------------------------------------------------
# confirm_fire — wait for xp, then settle ticks, then look for the fire
# ---------------------------------------------------------------------------

class TestConfirmFire:
    def _routine_waiting(self, attempt_tick: int = 100) -> FishAndCookRoutine:
        r = _routine()
        r._fire_attempt_tick = attempt_tick
        return r

    def test_no_xp_within_timeout_keeps_waiting(self):
        game = _make_game(tick=110)  # 10 ticks since the attempt — under the 20-tick timeout
        r = self._routine_waiting(100)
        assert r.confirm_fire(game, _ctrl()) is None
        assert r._fire_attempt_tick == 100

    def test_no_xp_past_timeout_retries_on_a_new_tile(self):
        game = _make_game(tick=120)  # 20 ticks since the attempt — at the timeout
        r = self._routine_waiting(100)

        result = r.confirm_fire(game, _ctrl())

        assert result == "step_aside"
        assert r._fire_attempt_tick is None

    def test_xp_received_but_settle_ticks_not_elapsed_keeps_waiting(self):
        game = _make_game(tick=101, last_xp_tick={"FIREMAKING": 101})
        r = self._routine_waiting(100)
        assert r.confirm_fire(game, _ctrl()) is None

    def test_fire_found_nearby_after_settling_advances_to_cooking(self):
        game = _make_game(tick=104, last_xp_tick={"FIREMAKING": 100}, objects=[FIRE])
        r = self._routine_waiting(100)

        result = r.confirm_fire(game, _ctrl())

        assert result == "cooking"
        assert r._fire_attempt_tick is None

    def test_no_fire_after_settling_retries_on_a_new_tile(self):
        game = _make_game(tick=104, last_xp_tick={"FIREMAKING": 100}, objects=[])
        r = self._routine_waiting(100)

        result = r.confirm_fire(game, _ctrl())

        assert result == "step_aside"
        assert r._fire_attempt_tick is None

    def test_fire_too_far_away_counts_as_no_fire(self):
        game = _make_game(tick=104, last_xp_tick={"FIREMAKING": 100}, objects=[FIRE_FAR])
        r = self._routine_waiting(100)
        assert r.confirm_fire(game, _ctrl()) == "step_aside"


# ---------------------------------------------------------------------------
# cooking — one "use fish on fire" gesture per raw-fish type, Space on the dialog
# ---------------------------------------------------------------------------

class TestCooking:
    def test_no_raw_fish_left_moves_to_dropping(self):
        game = _make_game(inventory=_inventory_with(590))
        r = _routine()
        r._cook_selected = True
        r._cook_started_tick = 50

        result = r.cooking(game, _ctrl())

        assert result == "dropping"
        assert r._cook_selected is False
        assert r._cook_started_tick is None

    def test_presses_space_when_dialog_appears(self):
        game = _make_game(tick=120, inventory=_inventory_with(317, 317), interfaces=[COOK_DIALOG_INTERFACE])
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        result = r.cooking(game, ctrl)

        ctrl.press_key.assert_called_once_with(Key.SPACE)
        assert r._cook_selected is False
        assert r._cook_started_tick == 120
        assert result is None

    def test_dialog_lookup_checks_interfaces_not_the_limited_widget_list(self):
        """
        Regression: the Skillmulti cook dialog (G270:38) is an interface
        group, not one of the limited `exposeWidgets` — looking it up via
        `find_widget`/`game.widgets` never matches, so Space never gets
        pressed and the routine just spams "use fish on fire" forever.
        """
        game = _make_game(tick=120, inventory=_inventory_with(317, 317),
                          widgets=[COOK_DIALOG_INTERFACE], interfaces=[])
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        r.cooking(game, ctrl)

        ctrl.press_key.assert_not_called()

    def test_selects_raw_shrimp_first_when_both_present(self):
        shrimp_widget = _inv_widget(317, child_id=0)
        game = _make_game(inventory=_inventory_with(317, 321), widgets=[shrimp_widget, _inv_widget(321, child_id=1)])
        ctrl = _ctrl()
        r = _routine()

        r.cooking(game, ctrl)

        ctrl.click_widget.assert_called_once_with(shrimp_widget)
        assert r._cook_selected is True

    def test_clicks_fire_after_fish_is_selected(self):
        game = _make_game(inventory=_inventory_with(317), objects=[FIRE])
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        result = r.cooking(game, ctrl)

        ctrl.click_entity.assert_called_once_with(FIRE, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._cook_selected is False
        assert result is None

    def test_does_not_start_a_new_gesture_while_batch_is_cooking(self):
        game = _make_game(tick=121, inventory=_inventory_with(317))
        game.player["animation"] = 897  # cooking animation — not idle
        ctrl = _ctrl()
        r = _routine()
        r._cook_started_tick = 120

        result = r.cooking(game, ctrl)

        ctrl.click_widget.assert_not_called()
        assert result is None

    def test_starts_a_fresh_gesture_once_the_batch_settles(self):
        anchovy_widget = _inv_widget(321, child_id=0)
        game = _make_game(tick=130, inventory=_inventory_with(321), widgets=[anchovy_widget])
        ctrl = _ctrl()
        r = _routine()
        r._cook_started_tick = 120  # well past COOKING_GESTURE_TICKS, player now idle

        result = r.cooking(game, ctrl)

        ctrl.click_widget.assert_called_once_with(anchovy_widget)
        assert r._cook_selected is True
        assert r._cook_started_tick is None
        assert result is None


class TestCookingFireDespawn:
    """A Fire can despawn mid-batch, stranding a selected fish with nothing to click it onto."""

    def test_fire_gone_when_about_to_click_it_finds_another(self):
        game = _make_game(inventory=_inventory_with(317), objects=[])
        r = _routine()
        r._cook_selected = True
        r._cook_started_tick = 50

        result = r.cooking(game, _ctrl())

        assert result == "find_fire"
        assert r._cook_selected is False
        assert r._cook_started_tick is None

    def test_still_moving_keeps_waiting_before_declaring_it_gone(self):
        """A settle-in-progress moment isn't proof the fire's gone — wait for idle first."""
        game = _make_game(inventory=_inventory_with(317), objects=[])
        game.player["animation"] = 1  # still settling — not idle yet
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        result = r.cooking(game, ctrl)

        assert result is None
        ctrl.click_entity.assert_not_called()
        assert r._cook_selected is True

    def test_fire_still_on_screen_clicks_it_normally(self):
        """The ordinary path — fish selected, fire still standing — must not be mistaken for a despawn."""
        game = _make_game(inventory=_inventory_with(317), objects=[FIRE])
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        result = r.cooking(game, ctrl)

        ctrl.click_entity.assert_called_once_with(FIRE, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID)
        assert r._cook_selected is False
        assert result is None


# ---------------------------------------------------------------------------
# dropping — shift-held, one click per item (DropMode.SHIFT_CLICK)
# ---------------------------------------------------------------------------

class TestDropping:
    def test_no_matching_item_returns_to_find_spot(self):
        game = _make_game(widgets=[_inv_widget(590), _inv_widget(1511)])
        assert _routine().dropping(game, _ctrl()) == "find_spot"

    def test_no_matching_item_releases_shift(self):
        game = _make_game(widgets=[_inv_widget(590), _inv_widget(1511)])
        ctrl = _ctrl()
        _routine().dropping(game, ctrl)
        ctrl.release_key.assert_called_once_with(Key.SHIFT)

    def test_holds_shift_and_clicks_first_matching_item(self):
        cooked = _inv_widget(315, child_id=2)
        game = _make_game(widgets=[_inv_widget(590), cooked])
        ctrl = _ctrl()
        r = _routine()

        result = r.dropping(game, ctrl)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(cooked)
        assert result is None

    def test_holds_shift_and_clicks_burnt_fish(self):
        """
        Burnt shrimp and burnt anchovies both turn into the same generic
        "Burnt fish" item (id 7954) — not the shrimp/anchovy-specific ids
        guessed earlier — so this id has to be in DROP_ITEM_IDS for burnt
        catches to ever get cleared out.
        """
        burnt = _inv_widget(FishAndCookRoutine.BURNT_FISH_ID, child_id=5)
        game = _make_game(widgets=[_inv_widget(590), burnt])
        ctrl = _ctrl()
        r = _routine()

        result = r.dropping(game, ctrl)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(burnt)
        assert result is None

    def test_holds_shift_and_clicks_raw_fish(self):
        """
        Raw shrimp/anchovies are now in DROP_ITEM_IDS — when find_fire sends
        us here with no fire and no logs, the raw catch must get dropped
        instead of stalling the routine forever.
        """
        raw = _inv_widget(FishAndCookRoutine.RAW_SHRIMP_ID, child_id=3)
        game = _make_game(widgets=[_inv_widget(590), raw])
        ctrl = _ctrl()
        r = _routine()

        result = r.dropping(game, ctrl)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(raw)
        assert result is None

    def test_stays_in_dropping_while_items_remain(self):
        game = _make_game(widgets=[_inv_widget(315, child_id=2)])
        ctrl = _ctrl()

        assert _routine().dropping(game, ctrl) is None
        ctrl.release_key.assert_not_called()

    def test_queues_all_matching_items_for_one_pass(self):
        cooked = _inv_widget(315, child_id=2)
        burnt = _inv_widget(FishAndCookRoutine.BURNT_FISH_ID, child_id=5)
        raw = _inv_widget(FishAndCookRoutine.RAW_SHRIMP_ID, child_id=3)
        game = _make_game(widgets=[_inv_widget(590), cooked, burnt, raw])
        ctrl = _ctrl()
        r = _routine()

        assert r.dropping(game, ctrl) is None

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_has_calls([
            ((cooked,),),
            ((burnt,),),
            ((raw,),),
        ])
        assert r._drop_queue == []

    def test_retry_if_items_remain_after_clicks(self):
        cooked = _inv_widget(315, child_id=2)
        game = _make_game(widgets=[_inv_widget(590), cooked])
        ctrl = _ctrl()
        r = _routine()

        assert r.dropping(game, ctrl) is None
        assert r._drop_queue == []

        # Item still present on the next tick: queue and click again.
        game.widgets = [_inv_widget(590), cooked]
        assert r.dropping(game, ctrl) is None
        assert ctrl.click_widget.call_count == 2


# ---------------------------------------------------------------------------
# stopped — terminal state
# ---------------------------------------------------------------------------

class TestStopped:
    def test_stays_stopped_forever(self):
        game = _make_game()
        ctrl = _ctrl()
        r = _routine()
        assert r.stopped(game, ctrl) is None
        ctrl.click_entity.assert_not_called()
        ctrl.click_widget.assert_not_called()
        ctrl.right_click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# Helpers — _next_raw_fish / _click_inventory_item
# ---------------------------------------------------------------------------

class TestNextRawFish:
    def test_prefers_raw_shrimp(self):
        game = _make_game(inventory=_inventory_with(317, 321))
        assert _routine()._next_raw_fish(game) == FishAndCookRoutine.RAW_SHRIMP_ID

    def test_falls_back_to_raw_anchovies(self):
        game = _make_game(inventory=_inventory_with(321))
        assert _routine()._next_raw_fish(game) == FishAndCookRoutine.RAW_ANCHOVIES_ID

    def test_none_when_neither_present(self):
        game = _make_game(inventory=_inventory_with(590, 315))
        assert _routine()._next_raw_fish(game) is None


class TestClickInventoryItem:
    def test_clicks_first_matching_widget(self):
        match = _inv_widget(317, child_id=4)
        game = _make_game(widgets=[_inv_widget(590, child_id=0), match])
        ctrl = _ctrl()

        result = _routine()._click_inventory_item(game, ctrl, 317)

        assert result is True
        ctrl.click_widget.assert_called_once_with(match)

    def test_returns_false_when_absent(self):
        game = _make_game(widgets=[_inv_widget(590, child_id=0)])
        ctrl = _ctrl()

        result = _routine()._click_inventory_item(game, ctrl, 317)

        assert result is False
        ctrl.click_widget.assert_not_called()


# ---------------------------------------------------------------------------
# Live clickbox subscriptions — find_spot/find_fire/cooking subscribe for
# fresh hull updates on the entity they're about to click
# ---------------------------------------------------------------------------

class TestLiveHullSubscriptions:
    def test_find_spot_subscribes_to_spot_before_netting(self):
        game = _make_game(npcs=[SPOT])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_spot(game, ctrl)            # tick 100: idle-settle buffer starts
        game.tick = 101
        r.find_spot(game, ctrl)            # tick 101: settled — right-click issued

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "npc",
            name=SPOT["name"], id=SPOT["id"],
        )

    def test_find_fire_subscribes_to_fire_before_walking_to_it(self):
        game = _make_game(tick=1, objects=[FIRE_NEARBY])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = True
        r = _routine()

        r.find_fire(game, ctrl)        # tick 1: idle-settle buffer starts
        game.tick = 2
        r.find_fire(game, ctrl)        # tick 2: settled — clicks to walk over

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object",
            name=FIRE_NEARBY["name"], id=FIRE_NEARBY["id"],
        )

    def test_cooking_subscribes_to_fire_before_using_fish_on_it(self):
        game = _make_game(inventory=_inventory_with(317), objects=[FIRE])
        ctrl = _ctrl()
        r = _routine()
        r._cook_selected = True

        r.cooking(game, ctrl)

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object",
            name=FIRE["name"], id=FIRE["id"],
        )
