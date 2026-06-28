"""
Tests for InteractionRoutine — the shared "approach" and "verified menu
click" helpers reused by routines that click on game entities (mining,
fighting, looting, banking).

These exercise the helpers directly, in isolation from any concrete
routine, with `game`/`ctrl` mocked — the same gating behaviour iron_mining
and melee_fighter relied on before being refactored to share it (see
test_iron_mining.py / test_melee_fighter.py for the integration-level
coverage of those routines using these helpers).
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.regions import Path, Region
from scripts.gamebridge.routines.base import initial_state
from scripts.gamebridge.routines.interaction import DropMode, InteractionRoutine, MenuClick, OCCLUSION_NUDGE_YAW
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.widget_ids import Bankmain, Inventory


class _DummyRoutine(InteractionRoutine):
    """Minimal concrete routine — InteractionRoutine has no states of its own."""

    @initial_state
    def idling(self, game, ctrl):
        return None


ENTITY = {
    "id": 1, "name": "Iron rocks", "worldX": 3221, "worldY": 3219,
    "onScreen": True, "canvasX": 400, "canvasY": 300,
}


def _game(tick: int = 1, idle: bool = True, occluded: bool = False) -> MagicMock:
    game = MagicMock()
    game.tick = tick
    game.player_idle.return_value = idle
    game.is_occluded.return_value = occluded
    return game


def _ctrl(on_screen: bool = True) -> MagicMock:
    ctrl = MagicMock()
    ctrl.bring_entity_on_screen.return_value = on_screen
    return ctrl


def _routine() -> _DummyRoutine:
    return _DummyRoutine()


# ---------------------------------------------------------------------------
# approach — camera / occlusion / idle gating, with a one-tick settle buffer
# ---------------------------------------------------------------------------

class TestApproachCamera:
    def test_not_ready_when_entity_not_on_screen(self):
        game, ctrl = _game(), _ctrl(on_screen=False)
        assert _routine().approach(game, ctrl, ENTITY) is False
        ctrl.bring_entity_on_screen.assert_called_once_with(ENTITY, game)

    def test_resets_buffer_when_camera_adjustment_needed(self):
        game, ctrl = _game(), _ctrl(on_screen=True)
        r = _routine()
        r._approach_idle_since_tick = 1
        ctrl.bring_entity_on_screen.return_value = False

        assert r.approach(game, ctrl, ENTITY) is False
        assert r._approach_idle_since_tick == -1


class TestApproachOcclusion:
    def test_not_ready_when_occluded(self):
        game, ctrl = _game(occluded=True), _ctrl()
        assert _routine().approach(game, ctrl, ENTITY) is False

    def test_nudges_camera_when_occluded(self):
        """
        An on-screen-but-occluded entity needs an actual camera rotation to
        shift its projected position out from behind the panel —
        `bring_entity_on_screen`/`rotate_camera_to` both bail out as soon as
        `onScreen` is true, so calling either here would be a no-op and the
        entity would sit behind the panel forever.
        """
        game, ctrl = _game(occluded=True), _ctrl()
        _routine().approach(game, ctrl, ENTITY)
        ctrl.rotate_camera.assert_called_once_with(Key.RIGHT, OCCLUSION_NUDGE_YAW)

    def test_resets_buffer_when_occluded(self):
        game, ctrl = _game(occluded=True), _ctrl()
        r = _routine()
        r._approach_idle_since_tick = 1
        r.approach(game, ctrl, ENTITY)
        assert r._approach_idle_since_tick == -1

    def test_does_not_check_occlusion_when_entity_off_screen(self):
        """canvasX/canvasY are None while off-screen — is_occluded must not
        be called with them (it would blow up resolving screen coordinates)."""
        off_screen = {**ENTITY, "onScreen": False, "canvasX": None, "canvasY": None}
        game, ctrl = _game(), _ctrl(on_screen=True)
        _routine().approach(game, ctrl, off_screen)
        game.is_occluded.assert_not_called()


class TestApproachIdleSettleBuffer:
    def test_not_ready_while_player_moving(self):
        game, ctrl = _game(idle=False), _ctrl()
        assert _routine().approach(game, ctrl, ENTITY) is False

    def test_resets_buffer_while_player_moving(self):
        game, ctrl = _game(idle=False), _ctrl()
        r = _routine()
        r._approach_idle_since_tick = 1
        r.approach(game, ctrl, ENTITY)
        assert r._approach_idle_since_tick == -1

    def test_records_settle_tick_on_first_idle_tick(self):
        game, ctrl = _game(tick=5, idle=True), _ctrl()
        r = _routine()
        assert r.approach(game, ctrl, ENTITY) is False
        assert r._approach_idle_since_tick == 5

    def test_ready_one_tick_after_settling(self):
        ctrl = _ctrl()
        r = _routine()

        game = _game(tick=5, idle=True)
        assert r.approach(game, ctrl, ENTITY) is False  # records settle tick

        game = _game(tick=6, idle=True)
        assert r.approach(game, ctrl, ENTITY) is True   # settle complete

    def test_buffer_resets_to_fresh_after_becoming_ready(self):
        """Once `approach` returns True it clears its buffer so a subsequent
        approach (e.g. the next entity) starts its own settle cycle."""
        ctrl = _ctrl()
        r = _routine()

        r.approach(_game(tick=5, idle=True), ctrl, ENTITY)
        assert r.approach(_game(tick=6, idle=True), ctrl, ENTITY) is True
        assert r._approach_idle_since_tick == -1


# ---------------------------------------------------------------------------
# verified_menu_click — confirm-then-click / abandon / dismiss-and-retry
# ---------------------------------------------------------------------------

class TestVerifiedMenuClick:
    def test_confirmed_when_entry_present_and_clicked(self):
        game = MagicMock()
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = True

        result = _routine().verified_menu_click(game, ctrl, "Attack", "Goblin")

        assert result is MenuClick.CONFIRMED
        ctrl.click_menu_entry.assert_called_once_with(game, "Attack", "Goblin")
        ctrl.dismiss_menu.assert_not_called()

    def test_abandoned_when_menu_closed_without_match(self):
        game = MagicMock()
        game.menu_open.return_value = False
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False

        result = _routine().verified_menu_click(game, ctrl, "Attack", "Goblin")

        assert result is MenuClick.ABANDONED
        ctrl.dismiss_menu.assert_not_called()

    def test_pending_and_dismisses_when_menu_open_without_match(self):
        """Right-click menus don't time out — a menu open without the row we
        need has to be actively dismissed or the routine would stall forever."""
        game = MagicMock()
        game.menu_open.return_value = True
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False

        result = _routine().verified_menu_click(game, ctrl, "Take", "Bones")

        assert result is MenuClick.PENDING
        ctrl.dismiss_menu.assert_called_once_with(game)


# ---------------------------------------------------------------------------
# click_live / right_click_live — subscribe for fresh clickboxes, then click
# using the freshest available position
# ---------------------------------------------------------------------------

class TestClickLive:
    def test_subscribes_with_entity_name_and_id(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().click_live(ctrl, ENTITY, "object")

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "object", name=ENTITY["name"], id=ENTITY["id"]
        )

    def test_clicks_original_entity_when_no_hull_update_yet(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().click_live(ctrl, ENTITY, "object")

        ctrl.click_entity.assert_called_once_with(
            ENTITY, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID, verify_name=ENTITY["name"]
        )

    def test_clicks_original_entity_when_hull_update_not_found(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = {"found": False}

        _routine().click_live(ctrl, ENTITY, "object")

        ctrl.click_entity.assert_called_once_with(
            ENTITY, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID, verify_name=ENTITY["name"]
        )

    def test_clicks_original_entity_when_hull_update_for_different_entity(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = {
            "found": True, "name": "Gold rocks", "canvasX": 999, "canvasY": 999,
        }

        _routine().click_live(ctrl, ENTITY, "object")

        ctrl.click_entity.assert_called_once_with(
            ENTITY, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID, verify_name=ENTITY["name"]
        )

    def test_clicks_with_refreshed_position_when_hull_update_matches(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = {
            "found": True, "name": ENTITY["name"],
            "onScreen": True, "canvasX": 555, "canvasY": 444,
            "hull": [[550, 440], [560, 440], [560, 450], [550, 450]],
            "worldX": ENTITY["worldX"], "worldY": ENTITY["worldY"], "plane": 0,
        }

        _routine().click_live(ctrl, ENTITY, "object")

        call = ctrl.click_entity.call_args
        clicked = call[0][0]
        assert clicked["canvasX"] == 555
        assert clicked["canvasY"] == 444
        assert clicked["hull"] == [[550, 440], [560, 440], [560, 450], [550, 450]]
        # Fields outside _LIVE_HULL_FIELDS (e.g. id) are preserved from entity.
        assert clicked["id"] == ENTITY["id"]
        assert call.kwargs["sub_id"] == InteractionRoutine.LIVE_HULL_SUB_ID
        assert call.kwargs["verify_name"] == ENTITY["name"]

    def test_name_match_is_case_insensitive(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = {
            "found": True, "name": ENTITY["name"].upper(),
            "canvasX": 111, "canvasY": 222,
        }

        _routine().click_live(ctrl, ENTITY, "object")

        clicked = ctrl.click_entity.call_args[0][0]
        assert clicked["canvasX"] == 111
        assert clicked["canvasY"] == 222


class TestRightClickLive:
    def test_subscribes_with_entity_name_and_id(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().right_click_live(ctrl, ENTITY, "npc")

        ctrl.subscribe_to.assert_called_once_with(
            InteractionRoutine.LIVE_HULL_SUB_ID, "npc", name=ENTITY["name"], id=ENTITY["id"]
        )

    def test_right_clicks_original_entity_when_no_hull_update_yet(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().right_click_live(ctrl, ENTITY, "npc")

        ctrl.right_click_entity.assert_called_once_with(
            ENTITY, sub_id=InteractionRoutine.LIVE_HULL_SUB_ID, verify_name=ENTITY["name"]
        )

    def test_right_clicks_with_refreshed_position_when_hull_update_matches(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = {
            "found": True, "name": ENTITY["name"],
            "onScreen": True, "canvasX": 321, "canvasY": 123,
        }

        _routine().right_click_live(ctrl, ENTITY, "npc")

        call = ctrl.right_click_entity.call_args
        clicked = call[0][0]
        assert clicked["canvasX"] == 321
        assert clicked["canvasY"] == 123
        assert call.kwargs["sub_id"] == InteractionRoutine.LIVE_HULL_SUB_ID
        assert call.kwargs["verify_name"] == ENTITY["name"]


# ---------------------------------------------------------------------------
# click_live / right_click_live — verify_name delegation
#
# Tooltip verification is now inside GameController.click_entity/
# right_click_entity (tested in test_controller.py). These tests confirm
# click_live/right_click_live pass the right verify_name kwarg through.
# ---------------------------------------------------------------------------

class TestClickLiveVerifyName:
    def test_passes_entity_name_as_verify_name_by_default(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().click_live(ctrl, ENTITY, "object")

        assert ctrl.click_entity.call_args.kwargs["verify_name"] == ENTITY["name"]

    def test_passes_none_as_verify_name_when_verify_tooltip_false(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().click_live(ctrl, ENTITY, "object", verify_tooltip=False)

        assert ctrl.click_entity.call_args.kwargs["verify_name"] is None

    def test_passes_none_when_entity_has_no_name(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None
        entity = {k: v for k, v in ENTITY.items() if k != "name"}

        _routine().click_live(ctrl, entity, "object")

        assert ctrl.click_entity.call_args.kwargs["verify_name"] is None

    def test_returns_result_of_click_entity(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None
        ctrl.click_entity.return_value = False

        result = _routine().click_live(ctrl, ENTITY, "object")

        assert result is False


class TestRightClickLiveVerifyName:
    def test_passes_entity_name_as_verify_name_by_default(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().right_click_live(ctrl, ENTITY, "npc")

        assert ctrl.right_click_entity.call_args.kwargs["verify_name"] == ENTITY["name"]

    def test_passes_none_as_verify_name_when_verify_tooltip_false(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None

        _routine().right_click_live(ctrl, ENTITY, "npc", verify_tooltip=False)

        assert ctrl.right_click_entity.call_args.kwargs["verify_name"] is None

    def test_passes_none_when_entity_has_no_name(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None
        entity = {k: v for k, v in ENTITY.items() if k != "name"}

        _routine().right_click_live(ctrl, entity, "npc")

        assert ctrl.right_click_entity.call_args.kwargs["verify_name"] is None

    def test_returns_result_of_right_click_entity(self):
        ctrl = MagicMock()
        ctrl.hull_update.return_value = None
        ctrl.right_click_entity.return_value = False

        result = _routine().right_click_live(ctrl, ENTITY, "npc")

        assert result is False


# ---------------------------------------------------------------------------
# drop_item — SHIFT_CLICK (hold-once-per-sequence) and RIGHT_CLICK
# (verified-menu-click, multi-tick per item) drop gestures
# ---------------------------------------------------------------------------

def _inv_widget(item_id: int, group_id: int = Inventory.GROUP) -> dict:
    return {"groupId": group_id, "itemId": item_id, "quantity": 1}


DROP_ITEM_IDS = (315, 319, 7954)


class TestDropItemShiftClick:
    def test_holds_shift_and_clicks_first_matching_item(self):
        cooked = _inv_widget(315)
        game = _game()
        game.widgets = [_inv_widget(590), cooked]
        ctrl = MagicMock()

        result = _routine().drop_item(game, ctrl, DROP_ITEM_IDS)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_called_once_with(cooked)
        assert result is True

    def test_does_not_release_shift_while_items_remain(self):
        game = _game()
        game.widgets = [_inv_widget(315)]
        ctrl = MagicMock()

        _routine().drop_item(game, ctrl, DROP_ITEM_IDS)

        ctrl.release_key.assert_not_called()

    def test_releases_shift_and_returns_false_when_nothing_left(self):
        game = _game()
        game.widgets = [_inv_widget(590), _inv_widget(317)]
        ctrl = MagicMock()

        result = _routine().drop_item(game, ctrl, DROP_ITEM_IDS)

        ctrl.release_key.assert_called_once_with(Key.SHIFT)
        ctrl.click_widget.assert_not_called()
        ctrl.hold_key.assert_not_called()
        assert result is False

    def test_default_mode_is_shift_click(self):
        """drop_item with no `mode` argument behaves like DropMode.SHIFT_CLICK."""
        game = _game()
        game.widgets = [_inv_widget(315)]
        ctrl = MagicMock()

        _routine().drop_item(game, ctrl, DROP_ITEM_IDS)

        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.right_click_widget.assert_not_called()

    def test_only_considers_widgets_in_given_group(self):
        game = _game()
        game.widgets = [_inv_widget(315, group_id=999)]
        ctrl = MagicMock()

        result = _routine().drop_item(game, ctrl, DROP_ITEM_IDS)

        ctrl.click_widget.assert_not_called()
        assert result is False


class TestDropItemRightClick:
    def test_right_clicks_first_matching_item_and_sets_target(self):
        cooked = _inv_widget(315)
        game = _game()
        game.widgets = [_inv_widget(590), cooked]
        ctrl = MagicMock()
        r = _routine()

        result = r.drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        ctrl.right_click_widget.assert_called_once_with(cooked)
        assert r._drop_target == cooked
        assert result is True

    def test_no_matching_item_returns_false(self):
        game = _game()
        game.widgets = [_inv_widget(590), _inv_widget(317)]
        ctrl = MagicMock()

        result = _routine().drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        ctrl.right_click_widget.assert_not_called()
        assert result is False

    def test_confirmed_drop_clears_target_and_stays(self):
        game = _game(tick=5)
        game.menu_open.return_value = True
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = True
        r = _routine()
        r._drop_target = _inv_widget(315)

        result = r.drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        ctrl.click_menu_entry.assert_called_once_with(game, "Drop", None)
        assert r._drop_target is None
        assert result is True

    def test_abandoned_drop_clears_target_and_retries(self):
        game = _game(tick=5)
        game.menu_open.return_value = False
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False
        r = _routine()
        r._drop_target = _inv_widget(315)

        result = r.drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        assert r._drop_target is None
        assert result is True

    def test_pending_menu_keeps_target(self):
        game = _game(tick=5)
        game.menu_open.return_value = True
        ctrl = MagicMock()
        ctrl.click_menu_entry.return_value = False
        r = _routine()
        target = _inv_widget(315)
        r._drop_target = target

        result = r.drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        assert r._drop_target == target
        ctrl.dismiss_menu.assert_called_once_with(game)
        assert result is True

    def test_does_not_touch_shift(self):
        """RIGHT_CLICK mode never holds/releases Shift — that's SHIFT_CLICK-only."""
        game = _game()
        game.widgets = [_inv_widget(315)]
        ctrl = MagicMock()

        _routine().drop_item(game, ctrl, DROP_ITEM_IDS, mode=DropMode.RIGHT_CLICK)

        ctrl.hold_key.assert_not_called()
        ctrl.release_key.assert_not_called()


# ---------------------------------------------------------------------------
# drop_items_shift_click — batch shift-drop, with per-item "Drop" tooltip
# verification spanning two calls (move, then check + click/skip)
# ---------------------------------------------------------------------------

def _drop_widget(item_id: int, child_id: int, group_id: int = Inventory.GROUP) -> dict:
    return {
        "groupId": group_id, "childId": child_id, "itemId": item_id, "quantity": 1,
        "bounds": {"x": child_id * 40, "y": 0, "width": 32, "height": 32},
    }


class TestDropItemsShiftClick:
    def test_no_matching_items_releases_shift_and_returns_false(self):
        game = _game()
        game.widgets = [_drop_widget(590, 0)]
        ctrl = MagicMock()

        result = _routine().drop_items_shift_click(game, ctrl, DROP_ITEM_IDS)

        assert result is False
        ctrl.release_key.assert_called_once_with(Key.SHIFT)
        ctrl.hold_key.assert_not_called()

    def test_verify_tooltip_false_clicks_all_queued_widgets_in_one_call(self):
        a, b = _drop_widget(315, 0), _drop_widget(319, 1)
        game = _game()
        game.widgets = [a, b]
        ctrl = MagicMock()

        result = _routine().drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=False)

        assert result is True
        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        assert ctrl.click_widget.call_count == 2
        ctrl.click_widget.assert_any_call(a)
        ctrl.click_widget.assert_any_call(b)
        ctrl.move_to_widget.assert_not_called()
        ctrl.tooltip.assert_not_called()

    def test_first_call_moves_to_widget_without_clicking(self):
        widget = _drop_widget(315, 0)
        game = _game()
        game.widgets = [widget]
        ctrl = MagicMock()
        r = _routine()

        result = r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)

        assert result is True
        ctrl.hold_key.assert_called_once_with(Key.SHIFT)
        ctrl.move_to_widget.assert_called_once_with(widget)
        ctrl.click_widget.assert_not_called()
        assert r._drop_pending == widget

    def test_second_call_clicks_when_tooltip_says_drop(self):
        widget = _drop_widget(315, 0)
        game = _game()
        game.widgets = [widget]
        ctrl = MagicMock()
        ctrl.tooltip.return_value = "Drop Logs"
        r = _routine()

        r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)
        result = r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)

        assert result is True
        ctrl.click_widget.assert_called_once_with(widget)
        assert r._drop_pending is None

    def test_second_call_skips_when_tooltip_does_not_say_drop(self):
        widget = _drop_widget(315, 0)
        game = _game()
        game.widgets = [widget]
        ctrl = MagicMock()
        ctrl.tooltip.return_value = "Wield Logs"
        r = _routine()

        r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)
        result = r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)

        assert result is True
        ctrl.click_widget.assert_not_called()
        assert r._drop_pending is None
        assert 0 in r._drop_skipped

    def test_skipped_items_excluded_from_requeue_then_cleared_on_release(self):
        widget = _drop_widget(315, 0)
        game = _game()
        game.widgets = [widget]
        ctrl = MagicMock()
        ctrl.tooltip.return_value = "Wield Logs"
        r = _routine()

        r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)  # move to widget
        r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)  # skip — tooltip mismatch

        result = r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)  # queue empty -> release

        assert result is False
        ctrl.release_key.assert_called_once_with(Key.SHIFT)
        assert r._drop_skipped == set()

    def test_logs_tooltip_before_drop_click(self, caplog):
        widget = _drop_widget(315, 0)
        game = _game()
        game.widgets = [widget]
        ctrl = MagicMock()
        ctrl.tooltip.return_value = "Drop Logs"
        r = _routine()

        r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)
        with caplog.at_level(logging.DEBUG, logger="scripts.gamebridge.routines.interaction"):
            r.drop_items_shift_click(game, ctrl, DROP_ITEM_IDS, verify_tooltip=True)

        assert "Drop Logs" in caplog.text


# ---------------------------------------------------------------------------
# walk_to_entity — near/approach/click-live gating on an entity dict
# ---------------------------------------------------------------------------

_OBJ = {
    "id": 24009, "name": "Furnace",
    "worldX": 2976, "worldY": 3369, "plane": 0,
    "onScreen": True, "canvasX": 350, "canvasY": 250,
    "minimapX": 630, "minimapY": 85,
}


def _game_state(player_x: int = 2947, player_y: int = 3368, tick: int = 10) -> GameState:
    gs = GameState()
    gs.tick = tick
    gs.player = {"worldX": player_x, "worldY": player_y, "plane": 0, "animation": -1}
    gs.camera = {"yaw": 0, "pitch": 362}
    gs.interfaces = []
    return gs


def _live_ctrl() -> MagicMock:
    ctrl = MagicMock()
    ctrl.bring_entity_on_screen.return_value = True
    ctrl.hull_update.return_value = None
    ctrl.tooltip.return_value = _OBJ["name"]
    return ctrl


class TestWalkToEntity:
    def test_returns_true_when_player_already_within_near_tiles(self):
        """If the player is adjacent (distance ≤ near_tiles) nothing is clicked."""
        game = _game_state(player_x=2975, player_y=3369)  # distance 1
        ctrl = _live_ctrl()
        result = _routine().walk_to_entity(game, ctrl, _OBJ, near_tiles=2)
        assert result is True
        ctrl.click_entity.assert_not_called()

    def test_returns_false_when_too_far(self):
        game = _game_state(player_x=2947, player_y=3368)  # distance > 2
        result = _routine().walk_to_entity(_game_state(), _live_ctrl(), _OBJ)
        assert result is False

    def test_approach_gates_click_for_one_settle_tick(self):
        """First idle tick sets the settle buffer; no click yet."""
        game = _game_state(tick=10)
        ctrl = _live_ctrl()
        _routine().walk_to_entity(game, ctrl, _OBJ)
        ctrl.click_entity.assert_not_called()

    def test_click_fires_after_settle_tick(self):
        """Second consecutive idle tick clears the buffer and fires click_live."""
        game = _game_state(tick=10)
        ctrl = _live_ctrl()
        r = _routine()
        r.walk_to_entity(game, ctrl, _OBJ)       # tick 10: settle
        game.tick = 11
        r.walk_to_entity(game, ctrl, _OBJ)       # tick 11: click
        ctrl.click_entity.assert_called_once()

    def test_near_tiles_param_respected(self):
        """With near_tiles=5 a player 3 tiles away is already 'arrived'."""
        game = _game_state(player_x=2973, player_y=3369)  # distance 3
        result = _routine().walk_to_entity(game, _live_ctrl(), _OBJ, near_tiles=5)
        assert result is True


# ---------------------------------------------------------------------------
# walk_to_object — name lookup wrapping walk_to_entity
# ---------------------------------------------------------------------------

_OBJECTS_SCENE = [_OBJ]


class TestWalkToObject:
    def test_returns_false_and_logs_warning_when_not_found(self, caplog):
        game = _game_state()
        game.objects = []
        with caplog.at_level("WARNING"):
            result = _routine().walk_to_object(game, _live_ctrl(), "Furnace")
        assert result is False
        assert "furnace" in caplog.text.lower()

    def test_returns_true_when_near_found_object(self):
        game = _game_state(player_x=2975, player_y=3369)  # distance 1
        game.objects = _OBJECTS_SCENE
        result = _routine().walk_to_object(game, _live_ctrl(), "Furnace", near_tiles=2)
        assert result is True

    def test_returns_false_and_approaches_when_far(self):
        game = _game_state(tick=10)
        game.objects = _OBJECTS_SCENE
        result = _routine().walk_to_object(game, _live_ctrl(), "Furnace")
        assert result is False


# ---------------------------------------------------------------------------
# click_inventory_item — left-click the first matching inventory slot
# ---------------------------------------------------------------------------

def _inv_item(item_id: int, child_id: int = 0) -> dict:
    return {
        "groupId": Inventory.GROUP, "childId": child_id, "itemId": item_id,
        "quantity": 1, "bounds": {"x": child_id * 40, "y": 0, "width": 32, "height": 32},
    }


class TestClickInventoryItem:
    def test_clicks_first_matching_slot_and_returns_true(self):
        game = _game()
        game.widgets = [_inv_item(590, 0), _inv_item(1511, 1)]
        ctrl = MagicMock()
        result = _routine().click_inventory_item(game, ctrl, 1511)
        ctrl.click_widget.assert_called_once_with(_inv_item(1511, 1))
        assert result is True

    def test_returns_false_when_item_not_in_inventory(self):
        game = _game()
        game.widgets = [_inv_item(590, 0)]
        ctrl = MagicMock()
        result = _routine().click_inventory_item(game, ctrl, 1511)
        ctrl.click_widget.assert_not_called()
        assert result is False

    def test_respects_custom_group_id(self):
        """A widget in a different group is ignored even if item_id matches."""
        game = _game()
        game.widgets = [{"groupId": 999, "childId": 0, "itemId": 1511, "quantity": 1}]
        ctrl = MagicMock()
        result = _routine().click_inventory_item(game, ctrl, 1511, group_id=Inventory.GROUP)
        ctrl.click_widget.assert_not_called()
        assert result is False


# ---------------------------------------------------------------------------
# find_bank_item — search open-bank interfaces for a specific item
# ---------------------------------------------------------------------------

def _bank_widget(item_id: int, child_id: int = 5) -> dict:
    return {
        "groupId": Bankmain.GROUP, "childId": child_id,
        "itemId": item_id, "quantity": 50,
        "bounds": {"x": 361, "y": 155, "width": 36, "height": 32}, "text": "",
    }


class TestFindBankItem:
    def test_returns_widget_when_item_present_in_bank(self):
        game = _game()
        widget = _bank_widget(438)
        game.interfaces = [widget]
        result = _routine().find_bank_item(game, 438)
        assert result == widget

    def test_returns_none_when_item_absent(self):
        game = _game()
        game.interfaces = [_bank_widget(436)]
        result = _routine().find_bank_item(game, 438)
        assert result is None

    def test_ignores_non_bank_groups(self):
        game = _game()
        game.interfaces = [{"groupId": 149, "childId": 0, "itemId": 438, "quantity": 1}]
        result = _routine().find_bank_item(game, 438)
        assert result is None


# ---------------------------------------------------------------------------
# open_bank — approach + click booth, grace period, returns True when open
# ---------------------------------------------------------------------------

_BANK_BOOTH_OBJ = {
    "id": 24101, "name": "Bank booth",
    "worldX": 2947, "worldY": 3367, "plane": 0,
    "onScreen": True, "canvasX": 250, "canvasY": 190,
    "hull": [[240, 180], [260, 180], [260, 200], [240, 200]],
    "minimapX": 600, "minimapY": 83,
}

_BANK_IFACE_ROOT = {
    "groupId": 12, "childId": 0,
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 4, "y": 4, "width": 512, "height": 334},
    "text": "",
}


def _bank_game(tick: int = 100, bank_open: bool = False) -> GameState:
    game = _game_state(tick=tick)
    game.objects = [_BANK_BOOTH_OBJ]
    game.interfaces = [_BANK_IFACE_ROOT] if bank_open else []
    game.widgets = []
    return game


class TestOpenBank:
    def test_returns_true_when_bank_already_open(self):
        game = _bank_game(bank_open=True)
        result = _routine().open_bank(game, _live_ctrl())
        assert result is True

    def test_returns_false_during_grace_period(self):
        r = _routine()
        r._bank_clicked_tick = 100
        game = _bank_game(tick=102)
        result = r.open_bank(game, _live_ctrl(), grace_ticks=4)
        assert result is False

    def test_retries_after_grace_period_expires(self):
        r = _routine()
        r._bank_clicked_tick = 100
        ctrl = _live_ctrl()
        r.open_bank(_bank_game(tick=104), ctrl, grace_ticks=4)    # settle
        r.open_bank(_bank_game(tick=105), ctrl, grace_ticks=4)    # click
        ctrl.click_entity.assert_called_once()

    def test_returns_false_and_logs_when_no_booth(self, caplog):
        game = _bank_game()
        game.objects = []
        with caplog.at_level("WARNING"):
            result = _routine().open_bank(game, _live_ctrl())
        assert result is False
        assert "bank" in caplog.text.lower()

    def test_records_bank_clicked_tick_after_click(self):
        r = _routine()
        ctrl = _live_ctrl()
        r.open_bank(_bank_game(tick=10), ctrl)   # settle
        r.open_bank(_bank_game(tick=11), ctrl)   # click
        assert r._bank_clicked_tick == 11


# ---------------------------------------------------------------------------
# deposit_inventory — throttled "Deposit inventory" button click
# ---------------------------------------------------------------------------

_DEPOSIT_BTN = {
    "groupId": Bankmain.GROUP,
    "childId": Bankmain.DEPOSITINV[1],
    "itemId": -1, "quantity": 0,
    "bounds": {"x": 347, "y": 301, "width": 29, "height": 22},
    "text": "",
}


def _deposit_game(tick: int = 100, has_btn: bool = True) -> GameState:
    game = _game_state(tick=tick)
    game.interfaces = [_DEPOSIT_BTN] if has_btn else []
    game.widgets = []
    return game


class TestDepositInventory:
    def test_clicks_deposit_button_and_returns_true(self):
        ctrl = MagicMock()
        result = _routine().deposit_inventory(_deposit_game(tick=100), ctrl)
        ctrl.click_widget.assert_called_once_with(_DEPOSIT_BTN)
        assert result is True

    def test_throttled_within_throttle_ticks(self):
        r = _routine()
        ctrl = MagicMock()
        r.deposit_inventory(_deposit_game(tick=100), ctrl)
        ctrl.reset_mock()
        for delta in (1, 4, 7):
            r.deposit_inventory(_deposit_game(tick=100 + delta), ctrl)
        ctrl.click_widget.assert_not_called()

    def test_allowed_at_throttle_tick_boundary(self):
        r = _routine()
        ctrl = MagicMock()
        r.deposit_inventory(_deposit_game(tick=100), ctrl)
        ctrl.reset_mock()
        r.deposit_inventory(_deposit_game(tick=108), ctrl)
        ctrl.click_widget.assert_called_once()

    def test_returns_false_when_no_deposit_button(self):
        ctrl = MagicMock()
        result = _routine().deposit_inventory(_deposit_game(has_btn=False), ctrl)
        ctrl.click_widget.assert_not_called()
        assert result is False

    def test_skips_banked_item_at_same_child_id_picks_button(self):
        # G12:48 can hold a banked item slot (itemId >= 0) *and* the deposit button
        # (itemId == -1). The fix must select the button, not the banked slot.
        banked_slot = {
            "groupId": Bankmain.GROUP,
            "childId": Bankmain.DEPOSITINV[1],
            "itemId": 995, "quantity": 1000,
            "bounds": {"x": 347, "y": 301, "width": 29, "height": 22},
            "text": "",
        }
        game = _game_state(tick=100)
        game.interfaces = [banked_slot, _DEPOSIT_BTN]
        game.widgets = []
        ctrl = MagicMock()
        result = _routine().deposit_inventory(game, ctrl)
        ctrl.click_widget.assert_called_once_with(_DEPOSIT_BTN)
        assert result is True

    def test_returns_false_when_only_banked_item_at_child_id(self):
        # If the only G12:48 widget is a banked item (no button present), return False.
        banked_slot = {
            "groupId": Bankmain.GROUP,
            "childId": Bankmain.DEPOSITINV[1],
            "itemId": 995, "quantity": 1000,
            "bounds": {"x": 347, "y": 301, "width": 29, "height": 22},
            "text": "",
        }
        game = _game_state(tick=100)
        game.interfaces = [banked_slot]
        game.widgets = []
        ctrl = MagicMock()
        result = _routine().deposit_inventory(game, ctrl)
        ctrl.click_widget.assert_not_called()
        assert result is False


# ---------------------------------------------------------------------------
# synthetic_minimap_entity — minimap waypoint geometry
# ---------------------------------------------------------------------------

MINIMAP_WIDGET = {
    "groupId": 160, "childId": 0, "itemId": -1, "quantity": 0,
    "bounds": {"x": 550, "y": 30, "width": 150, "height": 150}, "text": "",
}


def _minimap_game(player_x: int = 3100, player_y: int = 3440, with_widget: bool = True) -> GameState:
    game = _game_state(player_x=player_x, player_y=player_y)
    game.interfaces = [MINIMAP_WIDGET] if with_widget else []
    game.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 4.0}
    return game


class TestSyntheticMinimapEntity:
    def test_returns_none_without_minimap_widget(self):
        game = _minimap_game(with_widget=False)
        assert _routine().synthetic_minimap_entity(game, 3100, 3460) is None

    def test_returns_none_without_camera(self):
        game = _minimap_game()
        game.camera = {}
        assert _routine().synthetic_minimap_entity(game, 3100, 3460) is None

    def test_target_directly_north_has_lower_canvas_y(self):
        game = _minimap_game(player_x=3100, player_y=3440)
        entity = _routine().synthetic_minimap_entity(game, 3100, 3460)
        b = MINIMAP_WIDGET["bounds"]
        cy = b["y"] + b["height"] / 2
        assert entity is not None
        assert entity["minimapY"] < cy

    def test_very_distant_target_is_clamped_within_radius(self):
        game = _minimap_game(player_x=3100, player_y=3200)
        entity = _routine().synthetic_minimap_entity(game, 3100, 4200)
        b = MINIMAP_WIDGET["bounds"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        half_extent = min(b["width"], b["height"]) / 2
        dist = ((entity["minimapX"] - cx) ** 2 + (entity["minimapY"] - cy) ** 2) ** 0.5
        assert dist <= half_extent + 1e-6


# ---------------------------------------------------------------------------
# travel_path — step toward one end of a recorded Path
# ---------------------------------------------------------------------------

# A straight-line path along x at y=0, waypoints 0..30 — long enough that a
# single PATH_RESAMPLE_WAYPOINTS-sized step doesn't immediately reach the end.
STRAIGHT_PATH = Path("straight", tuple((float(i), 0.0) for i in range(31)))

# A game viewport widget — without one in a test's `game.interfaces`,
# `_viewport_click_canvas` always returns None, so travel_path falls back to
# a minimap click regardless of distance (see TestTravelPathGameViewClick
# below for the game-view branch itself).
RESIZABLE_VIEWPORT_WIDGET = {
    "groupId": 161, "childId": 0, "itemId": -1, "quantity": 0,
    "bounds": {"x": 0, "y": 0, "width": 700, "height": 500}, "text": "",
}


def _travel_game(player_x: float, player_y: float, tick: int = 10) -> GameState:
    game = _game_state(player_x=int(player_x), player_y=int(player_y), tick=tick)
    game.player["worldX"], game.player["worldY"] = player_x, player_y
    game.interfaces = [MINIMAP_WIDGET]
    game.camera = {"yaw": 0, "yawTarget": 0, "pitch": 256, "minimapZoom": 4.0}
    return game


class TestTravelPath:
    def test_returns_true_immediately_when_already_at_destination(self):
        game = _travel_game(30, 0)
        ctrl = MagicMock()
        assert _routine().travel_path(game, ctrl, STRAIGHT_PATH) is True
        ctrl.click_minimap_entity.assert_not_called()

    def test_clicks_toward_destination_when_not_yet_arrived(self):
        game = _travel_game(0, 0)
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, STRAIGHT_PATH)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once()

    def test_caches_target_across_calls_without_enough_movement(self):
        """While the player's nearest waypoint hasn't moved far enough,
        repeated calls must target the same cached point rather than
        resampling a new random waypoint every tick."""
        game = _travel_game(0, 0)
        ctrl = MagicMock()
        r = _routine()
        r.travel_path(game, ctrl, STRAIGHT_PATH)
        first_target = ctrl.click_minimap_entity.call_args.args[0]
        r.travel_path(game, ctrl, STRAIGHT_PATH)
        second_target = ctrl.click_minimap_entity.call_args.args[0]
        assert first_target == second_target

    def test_resamples_after_nearest_waypoint_moves_far_enough(self):
        ctrl = MagicMock()
        r = _routine()
        r.travel_path(_travel_game(0, 0), ctrl, STRAIGHT_PATH)
        cached_index_near_start = r._path_cached_index

        r.travel_path(_travel_game(20, 0), ctrl, STRAIGHT_PATH)
        cached_index_after_move = r._path_cached_index

        assert cached_index_near_start != cached_index_after_move

    def test_resets_cache_on_arrival(self):
        game = _travel_game(0, 0)
        ctrl = MagicMock()
        r = _routine()
        r.travel_path(game, ctrl, STRAIGHT_PATH)
        assert r._path_cached_index is not None

        game_arrived = _travel_game(30, 0)
        r.travel_path(game_arrived, ctrl, STRAIGHT_PATH)
        assert r._path_cached_index is None

    def test_travels_in_reverse_direction(self):
        game = _travel_game(30, 0)  # at the forward end, heading back to the start
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, STRAIGHT_PATH, reverse=True)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once()

    def test_arrival_uses_reverse_end(self):
        """With reverse=True, arrival is checked against the *start* of the
        path, not the end."""
        game = _travel_game(0, 0)
        ctrl = MagicMock()
        assert _routine().travel_path(game, ctrl, STRAIGHT_PATH, reverse=True) is True
        ctrl.click_minimap_entity.assert_not_called()

    def test_respects_custom_arrival_tolerance(self):
        game = _travel_game(28, 0)
        ctrl = MagicMock()
        assert _routine().travel_path(game, ctrl, STRAIGHT_PATH, arrival_tolerance=5) is True

    def test_player_far_off_path_still_clicks_toward_nearest_waypoint(self):
        """Unlike travel_route's RegionRoute.locate, Path.nearest_index always
        resolves to *some* waypoint — a player far from the path is handled
        like any other in-progress leg, not a special "off route" case."""
        game = _travel_game(0, 1000)
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, STRAIGHT_PATH)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once()

    def test_no_click_when_no_minimap_widget_available(self):
        """synthetic_minimap_entity returns None without a minimap widget —
        travel_path must not crash and must skip the click."""
        game = _travel_game(0, 0)
        game.interfaces = []
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, STRAIGHT_PATH)
        assert result is False
        ctrl.click_minimap_entity.assert_not_called()


# ---------------------------------------------------------------------------
# travel_path — game-view click for short (<GAME_VIEW_CLICK_MAX_TILES) hops
# ---------------------------------------------------------------------------

# Short enough that click_target's randomised distance (40%-100% of however
# far the minimap could reach) always lands under GAME_VIEW_CLICK_MAX_TILES
# (10), and — facing East (yaw=1536, forward=+X) — always within the
# pitch=256 FOV's ≈5.1 tile forward extent too.
NEAR_PATH = Path("near", tuple((float(i), 0.0) for i in range(5)))  # 0..4

# Long enough that the minimum randomised step (round(0.4*9)=4 tiles) still
# keeps the whole reachable range under GAME_VIEW_CLICK_MAX_TILES, while
# every point in that range sits behind a West-facing camera (forward=-X),
# i.e. always outside the FOV trapezoid.
FAR_SIDE_PATH = Path("far_side", tuple((float(i), 0.0) for i in range(10)))  # 0..9


def _game_view_game(player_x: float, player_y: float, yaw: int, tick: int = 10) -> GameState:
    game = _game_state(player_x=int(player_x), player_y=int(player_y), tick=tick)
    game.player["worldX"], game.player["worldY"] = player_x, player_y
    game.interfaces = [MINIMAP_WIDGET, RESIZABLE_VIEWPORT_WIDGET]
    game.camera = {"yaw": yaw, "yawTarget": yaw, "pitch": 256, "minimapZoom": 4.0}
    return game


class TestTravelPathGameViewClick:
    def test_clicks_in_viewport_instead_of_minimap_when_close_and_in_fov(self):
        # yaw=1536 (East) faces directly down the path (+X) — well within FOV.
        game = _game_view_game(0, 0, yaw=1536)
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, NEAR_PATH)
        assert result is False
        ctrl.click_walk_target.assert_called_once()
        ctrl.click_minimap_entity.assert_not_called()

    def test_falls_back_to_minimap_when_close_target_is_outside_fov(self):
        # yaw=512 (West) faces away from the path — every reachable waypoint
        # sits behind the camera, outside the calibrated FOV trapezoid.
        game = _game_view_game(0, 0, yaw=512)
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, FAR_SIDE_PATH)
        assert result is False
        ctrl.click_walk_target.assert_not_called()
        ctrl.click_minimap_entity.assert_called_once()

    def test_falls_back_to_minimap_without_viewport_widget(self):
        game = _game_view_game(0, 0, yaw=1536)
        game.interfaces = [MINIMAP_WIDGET]
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, NEAR_PATH)
        assert result is False
        ctrl.click_walk_target.assert_not_called()
        ctrl.click_minimap_entity.assert_called_once()

    def test_far_target_uses_minimap_even_with_viewport_widget_present(self):
        # STRAIGHT_PATH (0..30) easily clicks beyond GAME_VIEW_CLICK_MAX_TILES.
        game = _game_view_game(0, 0, yaw=1536)
        ctrl = MagicMock()
        result = _routine().travel_path(game, ctrl, STRAIGHT_PATH)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once()


# ---------------------------------------------------------------------------
# _minimap_cap_tiles — reachable tile radius for a single minimap click
# ---------------------------------------------------------------------------

class TestMinimapCapTiles:
    def test_computes_tile_radius_from_zoom(self):
        game = _minimap_game()
        # bounds 150x150 -> half_extent=75, cap=0.9*75=67.5px; zoom=4.0 -> 16.875 tiles
        assert _routine()._minimap_cap_tiles(game) == pytest.approx(16.875)

    def test_smaller_zoom_value_means_larger_tile_radius(self):
        game = _minimap_game()
        game.camera["minimapZoom"] = 2.0
        assert _routine()._minimap_cap_tiles(game) == pytest.approx(33.75)

    def test_none_without_minimap_widget(self):
        game = _minimap_game(with_widget=False)
        assert _routine()._minimap_cap_tiles(game) is None

    def test_none_without_camera_zoom(self):
        game = _minimap_game()
        game.camera = {}
        assert _routine()._minimap_cap_tiles(game) is None


# ---------------------------------------------------------------------------
# outside_container — safety-exit check used by routines with a CONTAINER_REGION
# ---------------------------------------------------------------------------

CONTAINER = Region("CONTAINER", ((0, 0), (100, 0), (100, 100), (0, 100)))


class TestOutsideContainer:
    def test_false_when_inside(self):
        game = _game_state(player_x=50, player_y=50)
        assert _routine().outside_container(game, CONTAINER) is False

    def test_true_when_outside(self):
        game = _game_state(player_x=1000, player_y=1000)
        assert _routine().outside_container(game, CONTAINER) is True

    def test_false_before_login(self):
        """game.player is empty before the first tick message arrives —
        player_pos defaults to (0, 0), which must not trip the safety exit
        before a real position is known."""
        game = _game_state()
        game.player = {}
        assert _routine().outside_container(game, CONTAINER) is False
