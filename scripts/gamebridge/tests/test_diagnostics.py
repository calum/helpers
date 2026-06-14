"""
Tests for the dashboard Testing-tab helpers in diagnostics.py.

These are pure functions (no Qt) so they're exercised directly with a real
GameState and a mocked GameController — covering the happy path and the
"can't be done right now" edge case for each check.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.gamebridge import diagnostics
from scripts.gamebridge.state.game_state import GameState

ORE = {
    "id": 440,
    "name": "Iron rocks",
    "worldX": 3221,
    "worldY": 3219,
    "plane": 0,
    "onScreen": True,
    "canvasX": 300,
    "canvasY": 300,
    "minimapX": 640,
    "minimapY": 80,
    "hull": [[285, 285], [315, 285], [315, 315], [285, 315]],
}

ORE_OFF_SCREEN = {
    **ORE,
    "onScreen": False,
    "canvasX": None,
    "canvasY": None,
    "minimapX": None,
    "minimapY": None,
}

# groupId 149 = inventory — a real, separate occluding panel (see
# state/interfaces.py). The toplevel viewport container (161) is excluded
# from occlusion checks, so fixtures must use an actual panel group here.
OCCLUDING_PANEL = {
    "groupId": 149,
    "childId": 0,
    "bounds": {"x": 280, "y": 280, "width": 60, "height": 60},
}


def _game(objects=None, npcs=None, interfaces=None) -> GameState:
    game = GameState()
    game.player = {"worldX": 3220, "worldY": 3218, "plane": 0, "animation": -1}
    game.objects = objects or []
    game.npcs = npcs or []
    game.interfaces = interfaces or []
    return game


# ---------------------------------------------------------------------------
# find_entity
# ---------------------------------------------------------------------------

class TestFindEntity:
    def test_finds_object_by_name(self):
        game = _game(objects=[ORE])
        assert diagnostics.find_entity(game, "Iron rocks") is ORE

    def test_falls_back_to_npc_when_no_object_matches(self):
        npc = {"name": "Man", "worldX": 3221, "worldY": 3218}
        game = _game(npcs=[npc])
        assert diagnostics.find_entity(game, "Man") is npc

    def test_returns_none_when_nothing_matches(self):
        game = _game(objects=[ORE])
        assert diagnostics.find_entity(game, "Dragon") is None


# ---------------------------------------------------------------------------
# describe_move_into_view
# ---------------------------------------------------------------------------

class TestDescribeMoveIntoView:
    def test_already_on_screen(self):
        ctrl = MagicMock()
        msg = diagnostics.describe_move_into_view(ctrl, _game(), ORE)
        assert "already on screen" in msg
        ctrl.bring_entity_on_screen.assert_not_called()

    def test_brought_into_view(self):
        ctrl = MagicMock()
        ctrl.bring_entity_on_screen.return_value = True
        game = _game()
        msg = diagnostics.describe_move_into_view(ctrl, game, ORE_OFF_SCREEN)
        assert "in view" in msg
        ctrl.bring_entity_on_screen.assert_called_once_with(ORE_OFF_SCREEN, game)

    def test_camera_adjustment_in_progress(self):
        ctrl = MagicMock()
        ctrl.bring_entity_on_screen.return_value = False
        msg = diagnostics.describe_move_into_view(ctrl, _game(), ORE_OFF_SCREEN)
        assert "Adjusting the camera" in msg


# ---------------------------------------------------------------------------
# describe_move_towards
# ---------------------------------------------------------------------------

class TestDescribeMoveTowards:
    def test_clicks_entity_when_on_screen(self):
        ctrl = MagicMock()
        msg = diagnostics.describe_move_towards(ctrl, ORE)
        assert "Clicked 'Iron rocks'" in msg
        ctrl.click_entity.assert_called_once_with(ORE)

    def test_no_op_when_off_screen(self):
        ctrl = MagicMock()
        msg = diagnostics.describe_move_towards(ctrl, ORE_OFF_SCREEN)
        assert "off screen" in msg
        ctrl.click_entity.assert_not_called()


# ---------------------------------------------------------------------------
# describe_click_minimap
# ---------------------------------------------------------------------------

class TestDescribeClickMinimap:
    def test_clicks_minimap_when_coords_present(self):
        ctrl = MagicMock()
        ctrl.click_minimap_entity.return_value = True
        game = _game()
        msg = diagnostics.describe_click_minimap(ctrl, game, ORE)
        assert "Clicked the minimap" in msg
        ctrl.click_minimap_entity.assert_called_once_with(ORE, game)

    def test_reports_out_of_range_when_no_coords(self):
        ctrl = MagicMock()
        ctrl.click_minimap_entity.return_value = False
        msg = diagnostics.describe_click_minimap(ctrl, _game(), ORE_OFF_SCREEN)
        assert "no minimap coordinates" in msg


# ---------------------------------------------------------------------------
# describe_is_occluded
# ---------------------------------------------------------------------------

class TestDescribeIsOccluded:
    def test_reports_occluding_panel_by_name_and_bounds(self):
        """groupId 149 is registered as "inventory" — the friendly name plus
        bounds is what lets you tell a real panel from a bogus registry hit."""
        game = _game(interfaces=[OCCLUDING_PANEL])
        msg = diagnostics.describe_is_occluded(game, ORE)
        assert "occluded by inventory (G149:0)" in msg
        assert "(280, 280) 60×60" in msg

    def test_reports_a_different_panel_by_its_own_name(self):
        """Sanity check that the label tracks the actual matching widget, not a fixed one."""
        chatbox_panel = {"groupId": 162, "childId": 0, "bounds": {"x": 280, "y": 280, "width": 60, "height": 60}}
        game = _game(interfaces=[chatbox_panel])
        msg = diagnostics.describe_is_occluded(game, ORE)
        assert "occluded by chatbox (G162:0)" in msg

    def test_ignores_sub_widget_bounds(self):
        """Only a panel's root (childId 0) should ever be reported — its
        children report their own small, often-stale bounds that produced
        "occluded" reports for entities nowhere near the visible panel."""
        sub_widget = {"groupId": 149, "childId": 12, "bounds": {"x": 300, "y": 300, "width": 5, "height": 5}}
        game = _game(interfaces=[sub_widget])
        msg = diagnostics.describe_is_occluded(game, ORE)
        assert "clear of any UI panel" in msg

    def test_reports_clear(self):
        game = _game(interfaces=[])
        msg = diagnostics.describe_is_occluded(game, ORE)
        assert "clear of any UI panel" in msg

    def test_reports_no_canvas_position_when_off_screen(self):
        msg = diagnostics.describe_is_occluded(_game(), ORE_OFF_SCREEN)
        assert "cannot test occlusion" in msg


# ---------------------------------------------------------------------------
# describe_is_on_screen / describe_is_on_minimap
# ---------------------------------------------------------------------------

class TestDescribeIsOnScreen:
    def test_on_screen(self):
        assert "is on screen" in diagnostics.describe_is_on_screen(ORE)

    def test_off_screen(self):
        assert "is off screen" in diagnostics.describe_is_on_screen(ORE_OFF_SCREEN)


class TestDescribeIsOnMinimap:
    def test_visible_on_minimap(self):
        assert "is visible" in diagnostics.describe_is_on_minimap(ORE)

    def test_not_visible_on_minimap(self):
        assert "is not visible" in diagnostics.describe_is_on_minimap(ORE_OFF_SCREEN)


# ---------------------------------------------------------------------------
# Keyboard checks
# ---------------------------------------------------------------------------

def _make_ctrl(held_keys=None) -> MagicMock:
    """A GameController stub with a real `_held_keys` set, kept in sync by
    hold_key/release_key/release_all_keys side effects (as the real
    controller does), so describe_* messages reflect the resulting state."""
    ctrl = MagicMock()
    ctrl._held_keys = set(held_keys or [])
    ctrl.hold_key.side_effect = ctrl._held_keys.add
    ctrl.release_key.side_effect = ctrl._held_keys.discard
    ctrl.release_all_keys.side_effect = ctrl._held_keys.clear
    return ctrl


class TestDescribePressKey:
    def test_presses_key(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_press_key(ctrl, "enter")
        assert "'enter'" in msg
        ctrl.press_key.assert_called_once_with("enter")

    def test_empty_key_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_press_key(ctrl, "   ")
        assert "Enter a key" in msg
        ctrl.press_key.assert_not_called()


class TestDescribeHoldKey:
    def test_holds_key_not_already_held(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_hold_key(ctrl, "shift")
        assert "Holding 'shift'" in msg
        assert "shift" in ctrl._held_keys
        ctrl.hold_key.assert_called_once_with("shift")

    def test_already_held_is_noop(self):
        ctrl = _make_ctrl(held_keys=["shift"])
        msg = diagnostics.describe_hold_key(ctrl, "shift")
        assert "already held" in msg
        ctrl.hold_key.assert_not_called()

    def test_empty_key_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_hold_key(ctrl, "")
        assert "Enter a key" in msg
        ctrl.hold_key.assert_not_called()


class TestDescribeReleaseKey:
    def test_releases_held_key(self):
        ctrl = _make_ctrl(held_keys=["shift"])
        msg = diagnostics.describe_release_key(ctrl, "shift")
        assert "Released 'shift'" in msg
        assert "shift" not in ctrl._held_keys
        ctrl.release_key.assert_called_once_with("shift")

    def test_not_held_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_release_key(ctrl, "shift")
        assert "not currently held" in msg
        ctrl.release_key.assert_not_called()

    def test_empty_key_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_release_key(ctrl, "")
        assert "Enter a key" in msg
        ctrl.release_key.assert_not_called()


class TestDescribeReleaseAllKeys:
    def test_releases_all_held_keys(self):
        ctrl = _make_ctrl(held_keys=["shift", "ctrl"])
        msg = diagnostics.describe_release_all_keys(ctrl)
        assert "ctrl" in msg
        assert "shift" in msg
        assert ctrl._held_keys == set()
        ctrl.release_all_keys.assert_called_once()

    def test_nothing_held_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_release_all_keys(ctrl)
        assert "No keys are currently held" in msg
        ctrl.release_all_keys.assert_not_called()


class TestDescribeTypeText:
    def test_types_text(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_type_text(ctrl, "hello")
        assert "5 character" in msg
        assert "'hello'" in msg
        ctrl.type_text.assert_called_once_with("hello")

    def test_empty_text_is_noop(self):
        ctrl = _make_ctrl()
        msg = diagnostics.describe_type_text(ctrl, "")
        assert "Enter some text" in msg
        ctrl.type_text.assert_not_called()


# ---------------------------------------------------------------------------
# describe_sendinput_diagnostics
# ---------------------------------------------------------------------------

def _sendinput_info(**overrides) -> dict:
    info = {
        "struct_size": 28,
        "foreground_hwnd": 0x1234,
        "foreground_title": "RuneLite - Calum",
        "foreground_class": "SunAwtFrame",
        "sendinput_result": 1,
        "last_error": 0,
    }
    info.update(overrides)
    return info


class TestDescribeSendInputDiagnostics:
    def test_reports_success_when_runelite_focused(self):
        with patch("scripts.gamebridge.diagnostics._settings.get", return_value="RuneLite"), \
             patch("scripts.gamebridge.diagnostics.kb_input.sendinput_diagnostics",
                   return_value=_sendinput_info()):
            msg = diagnostics.describe_sendinput_diagnostics()
        assert "SendInput call itself succeeded" in msg
        assert "WARNING" not in msg

    def test_warns_when_runelite_not_focused(self):
        with patch("scripts.gamebridge.diagnostics._settings.get", return_value="RuneLite"), \
             patch("scripts.gamebridge.diagnostics.kb_input.sendinput_diagnostics",
                   return_value=_sendinput_info(foreground_title="Discord", foreground_class="Chrome_WidgetWin_1")):
            msg = diagnostics.describe_sendinput_diagnostics()
        assert "WARNING" in msg
        assert "isn't focused" in msg

    def test_reports_access_denied(self):
        with patch("scripts.gamebridge.diagnostics._settings.get", return_value="RuneLite"), \
             patch("scripts.gamebridge.diagnostics.kb_input.sendinput_diagnostics",
                   return_value=_sendinput_info(sendinput_result=0, last_error=5)):
            msg = diagnostics.describe_sendinput_diagnostics()
        assert "ERROR_ACCESS_DENIED" in msg

    def test_reports_blockinput_suspicion(self):
        with patch("scripts.gamebridge.diagnostics._settings.get", return_value="RuneLite"), \
             patch("scripts.gamebridge.diagnostics.kb_input.sendinput_diagnostics",
                   return_value=_sendinput_info(sendinput_result=0, last_error=0)):
            msg = diagnostics.describe_sendinput_diagnostics()
        assert "BlockInput" in msg
