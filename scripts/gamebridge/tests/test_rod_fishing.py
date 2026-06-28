"""
Tests for RodFishingRoutine.

Covers:
  - resume: full + raw fish → cooking; full + no raw fish → travelling
    toward BANK_REGION/banking; not full → travelling toward
    FISHING_REGION/find_spot
  - tick / outside CONTAINER_REGION: jumps to the terminal `stopped` state,
    releases held keys, logs once; `stopped` takes no further action;
    normal dispatch is unaffected while inside the container
  - travelling: delegates to travel_path along BANK_FISHING_PATH, transitions
    to the stored arrival state once arrived
  - banking: no bankable items → travelling toward the fishing spot; cooked
    fish: opens bank; full deposit cycle; bank open after deposit → Escape;
    _batches_cooked reset
  - find_spot: inventory full → cooking; no NPC → None; approach + click → fishing
  - fishing: inventory full → cooking; spot gone → find_spot; idle timeout → find_spot
  - cooking: batch 1 → drop_burnt; batch 2 → drop_and_return; dialog → Space;
    left-click fire directly; gesture guard prevents reclick; no fire → wait
  - drop_burnt: nothing to drop → find_spot
  - drop_and_return: nothing to drop → travelling toward the bank
"""
from __future__ import annotations

from unittest.mock import MagicMock

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.examples.rod_fishing import (
    BANK_REGION,
    CONTAINER_REGION,
    FISHING_REGION,
    LOWER_EDGEVILLE,
    UPPER_BARBARIAN_VILLAGE,
    RodFishingRoutine,
)
from scripts.gamebridge.routines.interaction import InteractionRoutine
from scripts.gamebridge.state.game_state import GameState

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EMPTY_INVENTORY = [{"slot": i, "itemId": -1, "qty": 0} for i in range(28)]
JUNK = 1931  # arbitrary real item id used to pad a full inventory

# A point well inside each region, verified against the actual polygons.
BANK_POS = (3095, 3490)
LOWER_EDGEVILLE_POS = (3092, 3465)
UPPER_BARBARIAN_VILLAGE_POS = (3095, 3440)
FISHING_POS = (3104, 3430)
OUTSIDE_CONTAINER_POS = (3000, 3000)


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
    player_x: int = FISHING_POS[0],
    player_y: int = FISHING_POS[1],
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
    "worldX": FISHING_POS[0] - 3, "worldY": FISHING_POS[1] - 1, "plane": 0,
    "onScreen": True, "canvasX": 450, "canvasY": 300,
    "hull": [[440, 290], [460, 290], [460, 310], [440, 310]],
    "minimapX": 605, "minimapY": 92,
}

FIRE_FAR = {**FIRE_NEAR, "worldX": 3200, "worldY": 3400}  # > 12 tiles

BANK_BOOTH = {
    "id": 10355, "name": "Bank booth",
    "worldX": BANK_POS[0], "worldY": BANK_POS[1], "plane": 0,
    "onScreen": False, "canvasX": None, "canvasY": None,
    "minimapX": None, "minimapY": None,
}

COOK_DIALOG = {
    "groupId": 270, "childId": 38, "itemId": -1, "quantity": 0,
    "bounds": {"x": 400, "y": 250, "width": 200, "height": 30}, "text": "Cook 27 Raw Trout",
}


# ---------------------------------------------------------------------------
# Regions module data sanity
# ---------------------------------------------------------------------------

class TestRegionDefinitions:
    def test_bank_pos_in_bank_region(self):
        assert BANK_REGION.contains(*BANK_POS)

    def test_lower_edgeville_pos_in_region(self):
        assert LOWER_EDGEVILLE.contains(*LOWER_EDGEVILLE_POS)

    def test_upper_barbarian_village_pos_in_region(self):
        assert UPPER_BARBARIAN_VILLAGE.contains(*UPPER_BARBARIAN_VILLAGE_POS)

    def test_fishing_pos_in_fishing_region(self):
        assert FISHING_REGION.contains(*FISHING_POS)

    def test_all_route_positions_inside_container(self):
        for pos in (BANK_POS, LOWER_EDGEVILLE_POS, UPPER_BARBARIAN_VILLAGE_POS, FISHING_POS):
            assert CONTAINER_REGION.contains(*pos)

    def test_outside_pos_not_in_container(self):
        assert not CONTAINER_REGION.contains(*OUTSIDE_CONTAINER_POS)


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

    def test_full_inventory_no_raw_fish_travels_toward_bank(self):
        game = _make_game(inventory=_full_inv(R.COOKED_TROUT_ID))
        r = _routine()
        result = r.resume(game, _ctrl())
        assert result == "travelling"
        assert r._travel_reverse is True
        assert r._arrival_state == "banking"

    def test_not_full_travels_toward_fishing_spot(self):
        game = _make_game(inventory=list(EMPTY_INVENTORY))
        r = _routine()
        result = r.resume(game, _ctrl())
        assert result == "travelling"
        assert r._travel_reverse is False
        assert r._arrival_state == "find_spot"


# ---------------------------------------------------------------------------
# tick / safety exit outside CONTAINER_REGION
# ---------------------------------------------------------------------------

class TestSafetyExit:
    def test_stays_in_normal_dispatch_while_inside_container(self):
        game = _make_game(player_x=FISHING_POS[0], player_y=FISHING_POS[1],
                          inventory=_full_inv(R.RAW_TROUT_ID))
        r = _routine()
        r.tick(game, _ctrl())
        assert r.current_state == "cooking"

    def test_jumps_to_stopped_when_outside_container(self):
        game = _make_game(player_x=OUTSIDE_CONTAINER_POS[0], player_y=OUTSIDE_CONTAINER_POS[1])
        r = _routine()
        ctrl = _ctrl()
        r.tick(game, ctrl)
        assert r.current_state == "stopped"
        ctrl.release_all_keys.assert_called_once()

    def test_logs_critical_once_on_transition(self, caplog):
        game = _make_game(player_x=OUTSIDE_CONTAINER_POS[0], player_y=OUTSIDE_CONTAINER_POS[1])
        r = _routine()
        with caplog.at_level("CRITICAL"):
            r.tick(game, _ctrl())
        assert "CONTAINER_REGION" in caplog.text

    def test_stopped_state_takes_no_further_action_and_stays_stopped(self):
        game = _make_game(player_x=OUTSIDE_CONTAINER_POS[0], player_y=OUTSIDE_CONTAINER_POS[1])
        r = _routine()
        ctrl = _ctrl()
        r.tick(game, ctrl)  # transitions to stopped
        ctrl.reset_mock()
        r.tick(game, ctrl)  # second tick: already stopped
        assert r.current_state == "stopped"
        ctrl.click_entity.assert_not_called()
        ctrl.click_minimap_entity.assert_not_called()

    def test_does_not_trip_before_login(self):
        """game.player empty (no login yet) must not be treated as outside
        the container — (0, 0) is nowhere near CONTAINER_REGION."""
        game = _make_game()
        game.player = {}
        r = _routine()
        r.tick(game, _ctrl())
        assert r.current_state != "stopped"


# ---------------------------------------------------------------------------
# travelling
# ---------------------------------------------------------------------------

class TestTravelling:
    def test_transitions_to_arrival_state_once_in_destination(self):
        end_x, end_y = R.BANK_FISHING_PATH.points[-1]
        game = _make_game(player_x=int(end_x), player_y=int(end_y))
        r = _routine()
        r._travel_reverse = False
        r._arrival_state = "find_spot"
        assert r.travelling(game, _ctrl()) == "find_spot"

    def test_stays_travelling_and_clicks_minimap_while_en_route(self):
        game = _make_game(player_x=BANK_POS[0], player_y=BANK_POS[1],
                          interfaces=[MINIMAP_WIDGET])
        r = _routine()
        r._travel_reverse = False
        r._arrival_state = "find_spot"
        ctrl = _ctrl()
        result = r.travelling(game, ctrl)
        assert result is None
        ctrl.click_minimap_entity.assert_called_once()

    def test_transitions_to_banking_when_reversed_and_at_bank_end(self):
        start_x, start_y = R.BANK_FISHING_PATH.points[0]
        game = _make_game(player_x=int(start_x), player_y=int(start_y))
        r = _routine()
        r._travel_reverse = True
        r._arrival_state = "banking"
        assert r.travelling(game, _ctrl()) == "banking"


# ---------------------------------------------------------------------------
# banking
# ---------------------------------------------------------------------------

class TestBanking:
    def test_no_bankable_items_travels_toward_fishing_spot(self):
        game = _make_game(inventory=_inv(590))  # only tinderbox — not bankable
        r = _routine()
        result = r.banking(game, _ctrl())
        assert result == "travelling"
        assert r._travel_reverse is False
        assert r._arrival_state == "find_spot"

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
        game = _make_game(player_x=BANK_POS[0], player_y=BANK_POS[1],
                          inventory=_inv(R.COOKED_TROUT_ID), objects=[BANK_BOOTH])
        ctrl = _ctrl()
        ctrl.bring_entity_on_screen.return_value = False
        r = _routine()
        result = r.banking(game, ctrl)
        assert result is None

    def test_raw_fish_in_inventory_triggers_banking(self):
        game = _make_game(player_x=BANK_POS[0], player_y=BANK_POS[1],
                          inventory=_inv(R.RAW_TROUT_ID), objects=[BANK_BOOTH])
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
    def test_nothing_to_drop_travels_toward_bank(self):
        game = _make_game(widgets=[_inv_widget(R.COOKED_TROUT_ID)])
        r = _routine()
        result = r.drop_and_return(game, _ctrl())
        assert result == "travelling"
        assert r._travel_reverse is True
        assert r._arrival_state == "banking"

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
        assert result == "travelling"
