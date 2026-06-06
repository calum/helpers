"""
Tests for GameController — canvas bounds validation, click safety, and camera rotation.

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

from scripts.gamebridge.controller.controller import (
    GameController,
    CAMERA_YAW_SPEED,
    CAMERA_PITCH_SPEED,
    _ideal_pitch,
    _PITCH_OVERHEAD,
    _PITCH_HORIZON,
    _PITCH_TOLERANCE,
    _PITCH_NEAR_DIST,
    _PITCH_FAR_DIST,
)
from scripts.gamebridge.human.emulator import KeyHoldIntent
from scripts.gamebridge.input.keyboard import Key

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


# ---------------------------------------------------------------------------
# rotate_camera_to
# ---------------------------------------------------------------------------

def _game_state_stub(current_yaw: int, target_yaw: int):
    """A minimal game-state stub for rotate_camera_to tests."""
    stub = MagicMock()
    stub.camera = {"yaw": current_yaw}
    stub.camera_yaw_to.return_value = target_yaw
    return stub


def _ctrl_with_mock_human(hold_ms_out: float = 300.0) -> GameController:
    """GameController whose human emulator returns a deterministic KeyHoldIntent."""
    ctrl = _ctrl()
    ctrl._human.plan_key_hold.return_value = KeyHoldIntent(
        hold_ms=hold_ms_out,
        pre_hold_pause=0.0,
        post_hold_pause=0.0,
    )
    return ctrl


@patch("scripts.gamebridge.controller.controller.kb_input")
class TestRotateCameraTo:
    """rotate_camera_to: direction selection, hold duration, and human-emulator wiring."""

    def test_already_on_screen_returns_true_no_key(self, mock_kb):
        entity = {"onScreen": True, "name": "Iron rocks"}
        result = _ctrl_with_mock_human().rotate_camera_to(entity, _game_state_stub(0, 512))
        assert result is True
        mock_kb.press_key.assert_not_called()

    def test_rotates_right_when_delta_le_1024(self, mock_kb):
        # current=0, target=256 → delta=256 ≤ 1024 → RIGHT
        entity = {"onScreen": False, "name": "Iron rocks"}
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to(entity, _game_state_stub(current_yaw=0, target_yaw=256))
        args = mock_kb.press_key.call_args
        assert args[0][0] == Key.RIGHT

    def test_rotates_left_when_delta_gt_1024(self, mock_kb):
        # current=0, target=1800 → delta=1800 > 1024 → LEFT
        entity = {"onScreen": False, "name": "Iron rocks"}
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to(entity, _game_state_stub(current_yaw=0, target_yaw=1800))
        args = mock_kb.press_key.call_args
        assert args[0][0] == Key.LEFT

    def test_hold_ms_proportional_to_delta(self, mock_kb):
        # delta=512 → intended_hold_ms = 512 / 0.256 = 2000 ms
        entity = {"onScreen": False, "name": "Iron rocks"}
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to(entity, _game_state_stub(current_yaw=0, target_yaw=512))
        called_hold_ms = ctrl._human.plan_key_hold.call_args[0][0]
        expected = 512 / CAMERA_YAW_SPEED
        assert called_hold_ms == pytest.approx(expected, rel=0.01)

    def test_returns_false_after_rotation(self, mock_kb):
        entity = {"onScreen": False, "name": "Iron rocks"}
        result = _ctrl_with_mock_human().rotate_camera_to(
            entity, _game_state_stub(current_yaw=0, target_yaw=256)
        )
        assert result is False

    def test_uses_human_emulator_plan_key_hold(self, mock_kb):
        entity = {"onScreen": False, "name": "Iron rocks"}
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to(entity, _game_state_stub(current_yaw=0, target_yaw=256))
        ctrl._human.plan_key_hold.assert_called_once()

    def test_hold_ms_from_intent_passed_to_kb(self, mock_kb):
        """The hold_ms on the KeyHoldIntent (not the raw computed value) is passed to kb_input."""
        entity = {"onScreen": False, "name": "Iron rocks"}
        ctrl = _ctrl_with_mock_human(hold_ms_out=777.0)
        ctrl.rotate_camera_to(entity, _game_state_stub(current_yaw=0, target_yaw=256))
        _, kwargs = mock_kb.press_key.call_args
        assert kwargs["hold_ms"] == pytest.approx(777.0)


# ---------------------------------------------------------------------------
# adjust_camera_pitch_for
# ---------------------------------------------------------------------------

def _pitch_state_stub(current_pitch: int, distance: int):
    """Minimal game-state stub for adjust_camera_pitch_for tests."""
    stub = MagicMock()
    stub.camera = {"yaw": 0, "pitch": current_pitch}
    stub.distance_to.return_value = distance
    return stub


@patch("scripts.gamebridge.controller.controller.kb_input")
class TestAdjustCameraPitchFor:
    """adjust_camera_pitch_for: key selection, hold duration, tolerance, and edge cases."""

    def _ctrl(self, hold_ms_out: float = 300.0) -> GameController:
        ctrl = _ctrl_with_mock_human(hold_ms_out)
        return ctrl

    def test_within_tolerance_returns_true_no_key(self, mock_kb):
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        pitch = _PITCH_OVERHEAD  # ideal for near distance
        result = self._ctrl().adjust_camera_pitch_for(
            entity, _pitch_state_stub(current_pitch=pitch, distance=_PITCH_NEAR_DIST)
        )
        assert result is True
        mock_kb.press_key.assert_not_called()

    def test_within_tolerance_band_no_key(self, mock_kb):
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        # Target for near dist = _PITCH_OVERHEAD; current is _PITCH_TOLERANCE below → still OK
        result = self._ctrl().adjust_camera_pitch_for(
            entity, _pitch_state_stub(
                current_pitch=_PITCH_OVERHEAD - _PITCH_TOLERANCE,
                distance=_PITCH_NEAR_DIST,
            )
        )
        assert result is True
        mock_kb.press_key.assert_not_called()

    def test_presses_up_when_pitch_too_low(self, mock_kb):
        """Pitch needs increasing (more overhead) → UP key."""
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        # Near distance → target=_PITCH_OVERHEAD; current far below that
        result = self._ctrl().adjust_camera_pitch_for(
            entity, _pitch_state_stub(current_pitch=200, distance=_PITCH_NEAR_DIST)
        )
        assert result is False
        key_pressed = mock_kb.press_key.call_args[0][0]
        assert key_pressed == Key.UP

    def test_presses_down_when_pitch_too_high(self, mock_kb):
        """Pitch needs decreasing (more horizontal to see further) → DOWN key."""
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        # Far distance → target=_PITCH_HORIZON; current far above that
        result = self._ctrl().adjust_camera_pitch_for(
            entity, _pitch_state_stub(current_pitch=450, distance=_PITCH_FAR_DIST)
        )
        assert result is False
        key_pressed = mock_kb.press_key.call_args[0][0]
        assert key_pressed == Key.DOWN

    def test_hold_ms_proportional_to_pitch_delta(self, mock_kb):
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        delta = 200  # well above tolerance
        pitch_target = _ideal_pitch(_PITCH_NEAR_DIST)  # = _PITCH_OVERHEAD for near dist
        current = pitch_target - delta  # needs UP
        ctrl = self._ctrl()
        ctrl.adjust_camera_pitch_for(
            entity, _pitch_state_stub(current_pitch=current, distance=_PITCH_NEAR_DIST)
        )
        called_hold_ms = ctrl._human.plan_key_hold.call_args[0][0]
        assert called_hold_ms == pytest.approx(delta / CAMERA_PITCH_SPEED, rel=0.01)

    def test_no_camera_data_returns_true_no_key(self, mock_kb):
        """If camera is None/empty, skip adjustment without pressing anything."""
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        stub = MagicMock()
        stub.camera = None
        result = self._ctrl().adjust_camera_pitch_for(entity, stub)
        assert result is True
        mock_kb.press_key.assert_not_called()

    def test_missing_pitch_key_returns_true_no_key(self, mock_kb):
        """Camera dict without 'pitch' key → skip adjustment."""
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        stub = MagicMock()
        stub.camera = {"yaw": 0}  # no pitch
        result = self._ctrl().adjust_camera_pitch_for(entity, stub)
        assert result is True
        mock_kb.press_key.assert_not_called()


# ---------------------------------------------------------------------------
# bring_entity_on_screen
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller.decide_camera_action")
class TestBringEntityOnScreen:
    """bring_entity_on_screen: delegates to decide_camera_action then rotates if needed."""

    def _ctrl_spied(self):
        """Controller whose rotate/pitch methods are replaced with no-op mocks."""
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to = MagicMock(return_value=False)
        ctrl.adjust_camera_pitch_for = MagicMock(return_value=False)
        return ctrl

    def test_on_screen_action_returns_true_no_keys(self, mock_dca):
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        result = ctrl.bring_entity_on_screen({"worldX": 3225, "worldY": 3218}, MagicMock())
        assert result is True
        ctrl.rotate_camera_to.assert_not_called()
        ctrl.adjust_camera_pitch_for.assert_not_called()

    def test_rotate_action_calls_rotation_returns_false(self, mock_dca):
        mock_dca.return_value = "rotate"
        ctrl = self._ctrl_spied()
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        game = MagicMock()
        result = ctrl.bring_entity_on_screen(entity, game)
        assert result is False
        ctrl.rotate_camera_to.assert_called_once_with(entity, game)
        ctrl.adjust_camera_pitch_for.assert_called_once_with(entity, game)

    def test_walk_action_calls_rotation_returns_false(self, mock_dca):
        """For 'walk' (too far / off-bearing) still rotate toward target as best single-tick action."""
        mock_dca.return_value = "walk"
        ctrl = self._ctrl_spied()
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        game = MagicMock()
        result = ctrl.bring_entity_on_screen(entity, game)
        assert result is False
        ctrl.rotate_camera_to.assert_called_once_with(entity, game)
        ctrl.adjust_camera_pitch_for.assert_called_once_with(entity, game)

    def test_passes_entity_and_game_to_decide(self, mock_dca):
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        entity = {"onScreen": True, "worldX": 3225, "worldY": 3218}
        game = MagicMock()
        ctrl.bring_entity_on_screen(entity, game)
        mock_dca.assert_called_once_with(entity, game)


# ---------------------------------------------------------------------------
# click_minimap_entity
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestClickMinimapEntity:
    """click_minimap_entity issues a click at minimapX/Y, or returns False when absent."""

    def _ctrl(self, mock_settings, window=WINDOW) -> GameController:
        mock_settings.get.side_effect = lambda k: 0 if k == "hull_y_offset" else "RuneLite"
        ctrl = GameController(human=_human())
        ctrl._window = window
        return ctrl

    def test_returns_true_and_clicks_when_minimap_coords_present(self, mock_mouse, mock_settings):
        mock_mouse.get_position.return_value = (500.0, 400.0)
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": 90}
        result = ctrl.click_minimap_entity(entity)
        assert result is True
        mock_mouse.click_left.assert_called_once()

    def test_returns_false_when_minimap_x_is_none(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": None, "minimapY": 90}
        result = ctrl.click_minimap_entity(entity)
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_returns_false_when_minimap_y_is_none(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": None}
        result = ctrl.click_minimap_entity(entity)
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_returns_false_when_minimap_keys_absent(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks"}
        result = ctrl.click_minimap_entity(entity)
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_click_uses_minimap_canvas_coords(self, mock_mouse, mock_settings):
        mock_mouse.get_position.return_value = (500.0, 400.0)
        mock_settings.get.side_effect = lambda k: 0 if k == "hull_y_offset" else "RuneLite"
        human = _human()
        ctrl = GameController(human=human)
        ctrl._window = WINDOW
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": 90}
        ctrl.click_minimap_entity(entity)
        # plan_click should have been called with screen coords derived from (650, 90)
        left, top, _, _ = WINDOW
        call_args = human.plan_click.call_args[0]
        assert call_args[0] == left + 650   # screen_x
        assert call_args[1] == top + 90     # screen_y (y_off=0)
