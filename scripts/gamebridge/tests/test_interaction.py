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

from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.routines.base import initial_state
from scripts.gamebridge.routines.interaction import DropMode, InteractionRoutine, MenuClick, OCCLUSION_NUDGE_YAW
from scripts.gamebridge.widget_ids import Inventory


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
