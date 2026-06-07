"""
Tests for the dashboard Testing-tab helpers in diagnostics.py.

These are pure functions (no Qt) so they're exercised directly with a real
GameState and a mocked GameController — covering the happy path and the
"can't be done right now" edge case for each check.
"""
from __future__ import annotations

from unittest.mock import MagicMock

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
    def test_reports_occluded(self):
        game = _game(interfaces=[OCCLUDING_PANEL])
        msg = diagnostics.describe_is_occluded(game, ORE)
        assert "occluded by a UI panel" in msg

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
