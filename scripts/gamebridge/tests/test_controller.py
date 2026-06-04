"""
Tests for GameController — canvas bounds validation and click safety.

Covers:
  - _is_canvas_coord_valid: correct accept/reject of canvas coordinates
  - _clamp_to_window: screen coord clamping to game window bounds
  - click_entity / right_click_entity / move_to_entity / click_at:
      refuse to produce input when canvas coords are outside the viewport,
      and clamp the human-emulator's actual_x/y to the window in all paths

Hardware calls (mouse_input, settings) are fully mocked — no real input is
produced and no RuneLite window detection runs.

Run with:
    python -m pytest scripts/gamebridge/tests/test_controller.py -v
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import MagicMock, patch

from scripts.gamebridge.controller.controller import GameController

# ---------------------------------------------------------------------------
# Window fixture: left=100, top=200, right=1100, bottom=800  →  1000×600 canvas
# ---------------------------------------------------------------------------

WINDOW = (100, 200, 1100, 800)
CANVAS_W, CANVAS_H = 1000, 600   # right-left, bottom-top


def _human() -> MagicMock:
    h = MagicMock()
    h.should_take_break.return_value = False
    h.plan_click.return_value = MagicMock(
        pre_move_pause=0.0,
        post_move_pause=0.0,
        double_click=False,
        actual_x=700.0,    # valid screen coords inside WINDOW
        actual_y=450.0,
    )
    return h


def _ctrl(window=WINDOW) -> GameController:
    """Return a GameController with a hard-coded window — no Win32 calls needed."""
    ctrl = GameController(human=_human())
    ctrl._window = window
    return ctrl


def _entity(cx: int, cy: int, on_screen: bool = True, name: str = "Thing") -> dict:
    return {"name": name, "onScreen": on_screen, "canvasX": cx, "canvasY": cy}


# ---------------------------------------------------------------------------
# _is_canvas_coord_valid
# ---------------------------------------------------------------------------

class TestIsCanvasCoordValid:
    def test_centre_valid(self):
        assert _ctrl()._is_canvas_coord_valid(500, 300)

    def test_origin_valid(self):
        assert _ctrl()._is_canvas_coord_valid(0, 0)

    def test_last_valid_pixel(self):
        assert _ctrl()._is_canvas_coord_valid(CANVAS_W - 1, CANVAS_H - 1)

    def test_negative_x_invalid(self):
        assert not _ctrl()._is_canvas_coord_valid(-1, 300)

    def test_negative_y_invalid(self):
        assert not _ctrl()._is_canvas_coord_valid(500, -1)

    def test_x_at_width_boundary_invalid(self):
        # canvas is 0 … CANVAS_W-1; x == CANVAS_W is one pixel outside
        assert not _ctrl()._is_canvas_coord_valid(CANVAS_W, 300)

    def test_y_at_height_boundary_invalid(self):
        assert not _ctrl()._is_canvas_coord_valid(500, CANVAS_H)

    def test_far_outside_invalid(self):
        assert not _ctrl()._is_canvas_coord_valid(9999, 9999)

    def test_no_window_returns_false(self):
        ctrl = GameController(human=_human())
        ctrl._window = None
        with patch.object(ctrl, "refresh_window", return_value=False):
            assert not ctrl._is_canvas_coord_valid(500, 300)


# ---------------------------------------------------------------------------
# _clamp_to_window
# ---------------------------------------------------------------------------

class TestClampToWindow:
    def test_inside_coord_unchanged(self):
        assert _ctrl()._clamp_to_window(600, 400) == (600, 400)

    def test_at_left_edge_unchanged(self):
        sx, _ = _ctrl()._clamp_to_window(100, 400)
        assert sx == 100

    def test_left_of_window_clamped_to_left(self):
        sx, _ = _ctrl()._clamp_to_window(50, 400)
        assert sx == 100

    def test_right_of_window_clamped(self):
        sx, _ = _ctrl()._clamp_to_window(2000, 400)
        assert sx == 1099   # right - 1

    def test_above_window_clamped(self):
        _, sy = _ctrl()._clamp_to_window(600, 10)
        assert sy == 200    # top

    def test_below_window_clamped(self):
        _, sy = _ctrl()._clamp_to_window(600, 9000)
        assert sy == 799    # bottom - 1

    def test_no_window_returns_original(self):
        ctrl = GameController(human=_human())
        ctrl._window = None
        assert ctrl._clamp_to_window(9999, 9999) == (9999, 9999)


# ---------------------------------------------------------------------------
# click_entity — viewport guard and clamping
# Patch order: innermost decorator → first arg; outermost → last arg.
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestClickEntityGuard:
    """Verify click_entity rejects out-of-bounds canvas coords and clamps error."""

    def _setup(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)

    def test_off_screen_flag_blocks_click(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(500, 300, on_screen=False))
        mock_mouse.click_left.assert_not_called()

    def test_canvas_left_of_viewport_blocked(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=-50, cy=300, on_screen=True))
        mock_mouse.click_left.assert_not_called()

    def test_canvas_right_of_viewport_blocked(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=CANVAS_W + 100, cy=300, on_screen=True))
        mock_mouse.click_left.assert_not_called()

    def test_canvas_above_viewport_blocked(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=500, cy=-10, on_screen=True))
        mock_mouse.click_left.assert_not_called()

    def test_canvas_below_viewport_blocked(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=500, cy=CANVAS_H + 50, on_screen=True))
        mock_mouse.click_left.assert_not_called()

    def test_out_of_bounds_logs_warning(self, mock_mouse, mock_settings, caplog):
        self._setup(mock_mouse, mock_settings)
        with caplog.at_level(logging.WARNING, logger="scripts.gamebridge.controller.controller"):
            _ctrl().click_entity(_entity(cx=-50, cy=300, on_screen=True, name="Mine cart"))
        assert any(
            "Mine cart" in r.message and "outside viewport" in r.message
            for r in caplog.records
        )

    def test_valid_entity_produces_click(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(500, 300, on_screen=True))
        mock_mouse.click_left.assert_called_once()

    def test_human_emulator_error_clamped_to_window(self, mock_mouse, mock_settings):
        """Gaussian click error that would land outside the window is clamped."""
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._human.plan_click.return_value = MagicMock(
            pre_move_pause=0.0, post_move_pause=0.0, double_click=False,
            actual_x=50000.0, actual_y=50000.0,   # far outside
        )
        ctrl.click_entity(_entity(500, 300, on_screen=True))
        wind_args = mock_mouse.wind_mouse.call_args.args
        actual_x, actual_y = wind_args[2], wind_args[3]
        assert actual_x <= 1099   # right - 1
        assert actual_y <= 799    # bottom - 1
        mock_mouse.click_left.assert_called_once()

    def test_wind_mouse_not_called_when_blocked(self, mock_mouse, mock_settings):
        """No mouse movement at all when the entity is rejected."""
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=-50, cy=300, on_screen=True))
        mock_mouse.wind_mouse.assert_not_called()


# ---------------------------------------------------------------------------
# right_click_entity — viewport guard
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestRightClickEntityGuard:
    def test_out_of_bounds_not_right_clicked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_entity(_entity(cx=-50, cy=300, on_screen=True))
        mock_mouse.click_right.assert_not_called()

    def test_wind_mouse_not_called_when_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_entity(_entity(cx=CANVAS_W + 1, cy=300, on_screen=True))
        mock_mouse.wind_mouse.assert_not_called()

    def test_valid_entity_right_clicked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_entity(_entity(500, 300, on_screen=True))
        mock_mouse.click_right.assert_called_once()

    def test_human_emulator_error_clamped_to_window(self, mock_mouse, mock_settings):
        """Gaussian click error that would land outside the window is clamped."""
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl._human.plan_click.return_value = MagicMock(
            pre_move_pause=0.0, post_move_pause=0.0, double_click=False,
            actual_x=50000.0, actual_y=50000.0,
        )
        ctrl.right_click_entity(_entity(500, 300, on_screen=True))
        wind_args = mock_mouse.wind_mouse.call_args.args
        actual_x, actual_y = wind_args[2], wind_args[3]
        assert actual_x <= 1099   # right - 1
        assert actual_y <= 799    # bottom - 1
        mock_mouse.click_right.assert_called_once()


# ---------------------------------------------------------------------------
# move_to_entity — viewport guard
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestMoveToEntityGuard:
    def test_out_of_bounds_no_mouse_move(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().move_to_entity(_entity(cx=5000, cy=300, on_screen=True))
        mock_mouse.wind_mouse.assert_not_called()

    def test_off_screen_no_mouse_move(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().move_to_entity(_entity(500, 300, on_screen=False))
        mock_mouse.wind_mouse.assert_not_called()

    def test_valid_entity_mouse_moves(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().move_to_entity(_entity(500, 300, on_screen=True))
        mock_mouse.wind_mouse.assert_called_once()

    def test_human_emulator_error_clamped_to_window(self, mock_mouse, mock_settings):
        """Gaussian click error that would land outside the window is clamped."""
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl._human.plan_click.return_value = MagicMock(
            pre_move_pause=0.0, post_move_pause=0.0, double_click=False,
            actual_x=50000.0, actual_y=50000.0,
        )
        ctrl.move_to_entity(_entity(500, 300, on_screen=True))
        wind_args = mock_mouse.wind_mouse.call_args.args
        actual_x, actual_y = wind_args[2], wind_args[3]
        assert actual_x <= 1099   # right - 1
        assert actual_y <= 799    # bottom - 1


# ---------------------------------------------------------------------------
# click_at — viewport guard
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestClickAtGuard:
    def test_negative_x_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().click_at(-10, 300)
        mock_mouse.click_left.assert_not_called()

    def test_beyond_canvas_width_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().click_at(CANVAS_W + 100, 300)
        mock_mouse.click_left.assert_not_called()

    def test_beyond_canvas_height_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().click_at(500, CANVAS_H + 100)
        mock_mouse.click_left.assert_not_called()

    def test_valid_coord_clicked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl._human.plan_click.return_value = MagicMock(
            pre_move_pause=0.0, post_move_pause=0.0, double_click=False,
            actual_x=650.0, actual_y=450.0,
        )
        ctrl.click_at(500, 300)
        mock_mouse.click_left.assert_called_once()

    def test_wind_mouse_not_called_when_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().click_at(-10, 300)
        mock_mouse.wind_mouse.assert_not_called()
