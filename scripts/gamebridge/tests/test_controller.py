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
    MINIMAP_WALK_START_TICKS,
    MINIMAP_WALK_SETTLE_TICKS,
    MINIMAP_WALK_MAX_TICKS,
    ON_SCREEN_SETTLE_TICKS,
)
from scripts.gamebridge.client import BridgeConnection
from scripts.gamebridge.human.emulator import KeyHoldIntent
from scripts.gamebridge.input.keyboard import Key
from scripts.gamebridge.state.moving_target import TICK_DURATION_S

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
    """An NPC-shaped entity dict — has the `id`/`index` fields EntityTracker's
    generic velocity() dispatcher needs to route without KeyError (it's never
    actually fed through tracker.update(), so the lookup always misses and
    returns None — i.e. "no velocity data", same as any freshly-tracked
    entity gets on its first tick)."""
    return {"name": name, "onScreen": on_screen, "canvasX": cx, "canvasY": cy, "id": 1, "index": 1}


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
# screen_to_canvas / is_screen_point_in_window
#
# Used by the session recorder (recording.recording_tab) to translate raw
# OS click coordinates into the canvas space entity hulls / widget bounds use,
# and to ignore clicks made on other windows (the dashboard, browser, ...)
# while a recording is in progress. WINDOW = (left=100, top=200, right=1100,
# bottom=800).
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
class TestScreenToCanvas:
    def test_inverts_canvas_to_screen(self, mock_settings):
        mock_settings.get.return_value = 0
        ctrl = _ctrl()
        # canvas_to_screen(50, 50) == (150, 250); the inverse must round-trip.
        assert ctrl.screen_to_canvas(150, 250) == (50, 50)
        assert ctrl._canvas_to_screen(*ctrl.screen_to_canvas(150, 250)) == (150, 250)

    def test_applies_hull_y_offset(self, mock_settings):
        mock_settings.get.return_value = 10
        ctrl = _ctrl()
        # cy = sy - top + y_off
        assert ctrl.screen_to_canvas(150, 250) == (50, 60)

    def test_returns_none_when_window_not_found(self, mock_settings):
        mock_settings.get.return_value = 0
        ctrl = GameController(human=_human())
        ctrl._window = None
        with patch.object(ctrl, "refresh_window", return_value=False):
            assert ctrl.screen_to_canvas(150, 250) is None


class TestIsScreenPointInWindow:
    def test_point_inside_window_is_true(self):
        assert _ctrl().is_screen_point_in_window(600, 400)

    def test_point_at_top_left_corner_is_true(self):
        assert _ctrl().is_screen_point_in_window(100, 200)

    def test_point_at_bottom_right_edge_is_false(self):
        # window is (100, 200, 1100, 800) — right/bottom are exclusive
        assert not _ctrl().is_screen_point_in_window(1100, 800)

    def test_point_left_of_window_is_false(self):
        assert not _ctrl().is_screen_point_in_window(50, 400)

    def test_point_above_window_is_false(self):
        assert not _ctrl().is_screen_point_in_window(600, 100)

    def test_no_window_returns_false(self):
        ctrl = GameController(human=_human())
        ctrl._window = None
        with patch.object(ctrl, "refresh_window", return_value=False):
            assert not ctrl.is_screen_point_in_window(600, 400)


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
# _onscreen_canvas_pos — shared guard for move/click/right-click
# ---------------------------------------------------------------------------

class TestOnscreenCanvasPos:
    def test_returns_canvas_pos_when_valid_and_on_screen(self):
        pos = _ctrl()._onscreen_canvas_pos(_entity(500, 300, on_screen=True), "click_entity")
        assert pos == (500, 300)

    def test_returns_none_when_off_screen(self):
        assert _ctrl()._onscreen_canvas_pos(_entity(500, 300, on_screen=False), "click_entity") is None

    def test_returns_none_when_outside_viewport(self):
        assert _ctrl()._onscreen_canvas_pos(_entity(-50, 300, on_screen=True), "click_entity") is None

    def test_off_screen_logs_debug_with_action_and_name(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="scripts.gamebridge.controller.controller"):
            _ctrl()._onscreen_canvas_pos(_entity(500, 300, on_screen=False, name="Goblin"), "move_to_entity")
        assert any(
            "move_to_entity" in r.message and "Goblin" in r.message and "off-screen" in r.message
            for r in caplog.records
        )

    def test_outside_viewport_logs_warning_with_action_and_name(self, caplog):
        with caplog.at_level(logging.WARNING, logger="scripts.gamebridge.controller.controller"):
            _ctrl()._onscreen_canvas_pos(_entity(-50, 300, on_screen=True, name="Mine cart"), "right_click_entity")
        assert any(
            "right_click_entity" in r.message and "Mine cart" in r.message and "outside viewport" in r.message
            for r in caplog.records
        )


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
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]
        actual_x, actual_y = predict(0.0)
        assert actual_x <= 1099   # right - 1
        assert actual_y <= 799    # bottom - 1
        mock_mouse.click_left.assert_called_once()

    def test_wind_mouse_not_called_when_blocked(self, mock_mouse, mock_settings):
        """No mouse movement at all when the entity is rejected."""
        self._setup(mock_mouse, mock_settings)
        _ctrl().click_entity(_entity(cx=-50, cy=300, on_screen=True))
        mock_mouse.wind_mouse_to_prediction.assert_not_called()


# ---------------------------------------------------------------------------
# click_entity / move_to_entity / right_click_entity — moving-target prediction
#
# All three route through _plan_moving_click, so exercising it via click_entity
# covers the shared behaviour; TestMoveToEntityGuard/TestRightClickEntityGuard
# above already confirm the other two also call wind_mouse_to_prediction.
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestPlanMovingClick:
    """Verify the predict() callable handed to wind_mouse_to_prediction tracks
    the entity using EntityTracker-derived canvas velocity."""

    def _setup(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)

    def test_tracker_queried_in_canvas_space_for_this_entity(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = None

        entity = _entity(500, 300, on_screen=True)
        ctrl.click_entity(entity)

        ctrl._tracker.velocity.assert_called_once_with(entity, "canvas")

    def test_stationary_entity_predicts_a_fixed_point(self, mock_mouse, mock_settings):
        """No velocity data -> MovingTarget is static -> predict() always
        returns the same (clamped, error-offset) screen point, exactly like
        the pre-Phase-4 one-shot wind_mouse aim point."""
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = None

        ctrl.click_entity(_entity(500, 300, on_screen=True))
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == predict(1000.0) == pytest.approx((700.0, 450.0))

    def test_moving_entity_is_extrapolated_by_tracker_velocity(self, mock_mouse, mock_settings):
        """With known canvas velocity, predict(at_time) must extrapolate
        linearly by elapsed ticks — proportionally, in screen space, with the
        human's click-error preserved as a constant offset (see
        _plan_moving_click)."""
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = (10.0, -4.0)   # px/tick, canvas space

        with patch("scripts.gamebridge.controller.controller.time.monotonic", return_value=1000.0):
            ctrl.click_entity(_entity(500, 300, on_screen=True))

        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]
        x0, y0 = predict(1000.0)
        x1, y1 = predict(1000.0 + TICK_DURATION_S)
        x2, y2 = predict(1000.0 + TICK_DURATION_S * 2)

        assert (x1 - x0, y1 - y0) == pytest.approx((10.0, -4.0))
        assert (x2 - x0, y2 - y0) == pytest.approx((20.0, -8.0))

    def test_predict_result_stays_clamped_to_window_as_target_moves(self, mock_mouse, mock_settings):
        """Even far-future predictions that would extrapolate outside the
        viewport must stay inside the window — the same guarantee
        click error clamping gives a stationary target."""
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = (500.0, 500.0)  # wildly fast

        with patch("scripts.gamebridge.controller.controller.time.monotonic", return_value=1000.0):
            ctrl.click_entity(_entity(500, 300, on_screen=True))

        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]
        x, y = predict(1000.0 + TICK_DURATION_S * 50)
        assert 100 <= x <= 1099
        assert 200 <= y <= 799


# ---------------------------------------------------------------------------
# click_entity / right_click_entity with sub_id — live hullUpdate tracking
#
# _plan_live_click differs from _plan_moving_click only in what predict()
# does: on every call it re-checks ctrl.hull_update(sub_id) and, if a fresh
# matching/on-screen entity is there, tracks that canvas position directly;
# otherwise it falls back to the same MovingTarget extrapolation as
# _plan_moving_click. With WINDOW=(100,200,1100,800) and the stationary
# MovingTarget seeded at canvas (500,300), _canvas_to_screen(500,300) =
# (600,500) and _human().plan_click always returns actual_x/y=(700,450), so
# the fallback err offset is (+100,-50) — see TestPlanMovingClick.
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestPlanLiveClick:
    FALLBACK = pytest.approx((700.0, 450.0))

    def _setup(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)

    def _ctrl_with_connection(self, hull_updates=None) -> GameController:
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = None
        conn = MagicMock(spec=BridgeConnection)
        conn.hull_updates = {} if hull_updates is None else hull_updates
        ctrl.set_connection(conn)
        return ctrl

    def test_no_connection_falls_back_to_moving_target(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = _ctrl()
        ctrl._tracker = MagicMock()
        ctrl._tracker.velocity.return_value = None

        ctrl.click_entity(_entity(500, 300, on_screen=True), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == self.FALLBACK

    def test_no_hull_update_yet_falls_back_to_moving_target(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection()

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == self.FALLBACK

    def test_hull_update_not_found_falls_back_to_moving_target(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection({"click_target": {"found": False}})

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == self.FALLBACK

    def test_hull_update_off_screen_falls_back_to_moving_target(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection({
            "click_target": {"found": True, "name": "Fishing spot", "onScreen": False},
        })

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == self.FALLBACK

    def test_hull_update_for_different_entity_falls_back_to_moving_target(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection({
            "click_target": {
                "found": True, "name": "Gold rocks",
                "onScreen": True, "canvasX": 999, "canvasY": 999,
            },
        })

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == self.FALLBACK

    def test_tracks_live_hull_position_when_available(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection({
            "click_target": {
                "found": True, "name": "Fishing spot",
                "onScreen": True, "canvasX": 520, "canvasY": 340,
            },
        })

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        # canvas (520,340) -> screen (620,540) -> + fallback err (100,-50)
        assert predict(0.0) == pytest.approx((720.0, 490.0))

    def test_predict_repolls_hull_update_on_every_call(self, mock_mouse, mock_settings):
        """The whole point of _plan_live_click: predict() must reflect a
        hullUpdate that arrives *after* the click was planned, not just a
        one-shot snapshot taken up front."""
        self._setup(mock_mouse, mock_settings)
        hull_updates = {
            "click_target": {
                "found": True, "name": "Fishing spot",
                "onScreen": True, "canvasX": 520, "canvasY": 340,
            },
        }
        ctrl = self._ctrl_with_connection(hull_updates)

        ctrl.click_entity(_entity(500, 300, on_screen=True, name="Fishing spot"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == pytest.approx((720.0, 490.0))

        # A fresher hullUpdate arrives mid-flight.
        hull_updates["click_target"] = {
            "found": True, "name": "Fishing spot",
            "onScreen": True, "canvasX": 560, "canvasY": 380,
        }

        assert predict(1.0) == pytest.approx((760.0, 530.0))

    def test_right_click_entity_with_sub_id_tracks_live_hull_position(self, mock_mouse, mock_settings):
        self._setup(mock_mouse, mock_settings)
        ctrl = self._ctrl_with_connection({
            "click_target": {
                "found": True, "name": "Goblin",
                "onScreen": True, "canvasX": 520, "canvasY": 340,
            },
        })

        ctrl.right_click_entity(_entity(500, 300, on_screen=True, name="Goblin"), sub_id="click_target")
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]

        assert predict(0.0) == pytest.approx((720.0, 490.0))
        mock_mouse.click_right.assert_called_once()


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
        mock_mouse.wind_mouse_to_prediction.assert_not_called()

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
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]
        actual_x, actual_y = predict(0.0)
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
        mock_mouse.wind_mouse_to_prediction.assert_not_called()

    def test_off_screen_no_mouse_move(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().move_to_entity(_entity(500, 300, on_screen=False))
        mock_mouse.wind_mouse_to_prediction.assert_not_called()

    def test_valid_entity_mouse_moves(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().move_to_entity(_entity(500, 300, on_screen=True))
        mock_mouse.wind_mouse_to_prediction.assert_called_once()

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
        predict = mock_mouse.wind_mouse_to_prediction.call_args.args[2]
        actual_x, actual_y = predict(0.0)
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
# right_click_at / right_click_widget — viewport guard
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestRightClickAtGuard:
    def test_negative_x_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_at(-10, 300)
        mock_mouse.click_right.assert_not_called()

    def test_beyond_canvas_width_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_at(CANVAS_W + 100, 300)
        mock_mouse.click_right.assert_not_called()

    def test_valid_coord_right_clicked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl._human.plan_click.return_value = MagicMock(
            pre_move_pause=0.0, post_move_pause=0.0, double_click=False,
            actual_x=650.0, actual_y=450.0,
        )
        ctrl.right_click_at(500, 300)
        mock_mouse.click_right.assert_called_once()
        mock_mouse.click_left.assert_not_called()

    def test_wind_mouse_not_called_when_blocked(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        _ctrl().right_click_at(-10, 300)
        mock_mouse.wind_mouse.assert_not_called()

    def test_right_click_widget_uses_bounds_centre(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl.right_click_at = MagicMock()
        widget = {"groupId": 149, "childId": 3, "bounds": {"x": 100, "y": 200, "width": 32, "height": 32}}
        ctrl.right_click_widget(widget)
        ctrl.right_click_at.assert_called_once_with(100 + 32 / 2, 200 + 32 / 2)

    def test_right_click_widget_without_bounds_does_nothing(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        ctrl.right_click_at = MagicMock()
        ctrl.right_click_widget({"groupId": 149, "childId": 3})
        ctrl.right_click_at.assert_not_called()


# ---------------------------------------------------------------------------
# click_menu_entry — finds a matching context-menu entry and clicks its bounds
# ---------------------------------------------------------------------------

def _menu_entry_dict(option="Attack", target="Goblin (level-2)", x=480, y=379, w=140, h=15):
    return {"option": option, "target": target, "identifier": 21, "type": 9,
            "bounds": {"x": x, "y": y, "width": w, "height": h}}


def _game_state_with_menu_entry(entry):
    """A minimal game-state stub whose menu_entry_matching returns `entry` (or None)."""
    stub = MagicMock()
    stub.menu_entry_matching.return_value = entry
    return stub


class TestClickMenuEntry:
    def test_no_match_returns_false_and_does_not_click(self):
        ctrl = _ctrl()
        ctrl.click_at = MagicMock()
        game = _game_state_with_menu_entry(None)

        result = ctrl.click_menu_entry(game, "Attack", "Goblin")

        assert result is False
        ctrl.click_at.assert_not_called()

    def test_match_clicks_centre_of_entry_bounds(self):
        ctrl = _ctrl()
        ctrl.click_at = MagicMock()
        entry = _menu_entry_dict(x=480, y=379, w=140, h=15)
        game = _game_state_with_menu_entry(entry)

        result = ctrl.click_menu_entry(game, "Attack", "Goblin")

        assert result is True
        ctrl.click_at.assert_called_once_with(480 + 140 / 2, 379 + 15 / 2)

    def test_lookup_forwards_option_and_target_substrings(self):
        ctrl = _ctrl()
        ctrl.click_at = MagicMock()
        game = _game_state_with_menu_entry(_menu_entry_dict())

        ctrl.click_menu_entry(game, "Attack", "Goblin")

        game.menu_entry_matching.assert_called_once_with("Attack", "Goblin")

    def test_target_substr_optional(self):
        ctrl = _ctrl()
        ctrl.click_at = MagicMock()
        game = _game_state_with_menu_entry(_menu_entry_dict(option="Walk here", target=""))

        result = ctrl.click_menu_entry(game, "Walk here")

        assert result is True
        game.menu_entry_matching.assert_called_once_with("Walk here", None)


# ---------------------------------------------------------------------------
# dismiss_menu — moves the cursor clear of an open context menu so the
# client closes it (menus don't time out on their own — see melee_fighter's
# "menu open without a match" hazard)
# ---------------------------------------------------------------------------

def _game_state_with_menu(x, y, width, height):
    stub = MagicMock()
    stub.menu = {"open": True, "x": x, "y": y, "width": width, "height": height}
    return stub


@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestDismissMenu:
    def test_moves_mouse_clear_of_menu(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        game = _game_state_with_menu(x=480, y=379, width=140, height=64)

        ctrl.dismiss_menu(game)

        mock_mouse.wind_mouse.assert_called_once()

    def test_aims_left_when_menu_hugs_right_edge(self, mock_mouse, mock_settings):
        """Canvas is 1000px wide; a menu at x=900 w=80 has ~900px clearance to
        its left and ~20px to its right — dismiss_menu should aim left, landing
        outside (left of) the menu's bounds."""
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        game = _game_state_with_menu(x=900, y=100, width=80, height=64)

        ctrl.dismiss_menu(game)

        sx, sy = ctrl._human.plan_click.call_args.args[:2]
        canvas_x, _ = ctrl.screen_to_canvas(sx, sy)
        assert canvas_x < 900

    def test_aims_right_when_menu_hugs_left_edge(self, mock_mouse, mock_settings):
        """A menu at x=10 w=80 has ~10px clearance to its left and ~910px to
        its right — dismiss_menu should aim right, landing outside (right of)
        the menu's bounds."""
        mock_settings.get.return_value = 0
        mock_mouse.get_position.return_value = (600, 400)
        ctrl = _ctrl()
        game = _game_state_with_menu(x=10, y=100, width=80, height=64)

        ctrl.dismiss_menu(game)

        sx, sy = ctrl._human.plan_click.call_args.args[:2]
        canvas_x, _ = ctrl.screen_to_canvas(sx, sy)
        assert canvas_x > 90

    def test_no_window_does_not_move_mouse(self, mock_mouse, mock_settings):
        mock_settings.get.return_value = 0
        ctrl = GameController(human=_human())
        ctrl._window = None
        game = _game_state_with_menu(x=480, y=379, width=140, height=64)

        with patch.object(ctrl, "refresh_window", return_value=False):
            ctrl.dismiss_menu(game)

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
# bring_entity_on_screen
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller.decide_camera_action")
class TestBringEntityOnScreen:
    """bring_entity_on_screen: delegates to decide_camera_action then rotates (yaw only) if needed."""

    def _ctrl_spied(self, click_minimap_result=False):
        """Controller whose rotate/minimap methods are replaced with no-op mocks."""
        ctrl = _ctrl_with_mock_human()
        ctrl.rotate_camera_to = MagicMock(return_value=False)
        ctrl.click_minimap_entity = MagicMock(return_value=click_minimap_result)
        return ctrl

    def test_on_screen_first_tick_not_yet_settled_returns_false(self, mock_dca):
        """The tick the entity first reports on-screen, canvas coords may still be
        mid-rotation/transient — wait rather than click immediately (see
        ON_SCREEN_SETTLE_TICKS)."""
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        result = ctrl.bring_entity_on_screen({"worldX": 3225, "worldY": 3218}, MagicMock(tick=10))
        assert result is False
        ctrl.rotate_camera_to.assert_not_called()
        ctrl.click_minimap_entity.assert_not_called()

    def test_on_screen_settles_after_settle_ticks_then_returns_true(self, mock_dca):
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        entity = {"worldX": 3225, "worldY": 3218}

        first = ctrl.bring_entity_on_screen(entity, MagicMock(tick=10))
        second = ctrl.bring_entity_on_screen(entity, MagicMock(tick=10 + ON_SCREEN_SETTLE_TICKS))

        assert first is False
        assert second is True
        ctrl.rotate_camera_to.assert_not_called()

    def test_on_screen_settle_tracking_persists_across_calls(self, mock_dca):
        """Once settled, staying on-screen keeps returning True without re-waiting."""
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        entity = {"worldX": 3225, "worldY": 3218}

        ctrl.bring_entity_on_screen(entity, MagicMock(tick=10))
        ctrl.bring_entity_on_screen(entity, MagicMock(tick=11))
        result = ctrl.bring_entity_on_screen(entity, MagicMock(tick=12))

        assert result is True

    def test_rotate_action_calls_rotation_returns_false(self, mock_dca):
        mock_dca.return_value = "rotate"
        ctrl = self._ctrl_spied()
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218}
        game = MagicMock(tick=10)
        result = ctrl.bring_entity_on_screen(entity, game)
        assert result is False
        ctrl.rotate_camera_to.assert_called_once_with(entity, game)

    def test_rotation_resets_on_screen_settle_tracking(self, mock_dca):
        """A fresh adjustment must force the entity to re-settle before the next click —
        otherwise a rotation triggered mid-state could let a stale on-screen streak
        carry over and produce an immediate (mis-)click."""
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        entity = {"worldX": 3225, "worldY": 3218}
        ctrl.bring_entity_on_screen(entity, MagicMock(tick=10))
        ctrl.bring_entity_on_screen(entity, MagicMock(tick=11))
        assert ctrl.bring_entity_on_screen(entity, MagicMock(tick=12)) is True

        mock_dca.return_value = "rotate"
        ctrl.bring_entity_on_screen(entity, MagicMock(tick=13))

        mock_dca.return_value = "on_screen"
        result = ctrl.bring_entity_on_screen(entity, MagicMock(tick=14))
        assert result is False  # must settle again, not reuse the old streak

    def test_walk_action_clicks_minimap_and_skips_rotation(self, mock_dca):
        """For 'walk' (too far / off-bearing) walk via the minimap — rotation alone never converges."""
        mock_dca.return_value = "walk"
        ctrl = self._ctrl_spied(click_minimap_result=True)
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218, "minimapX": 640, "minimapY": 80}
        game = MagicMock(tick=10)
        result = ctrl.bring_entity_on_screen(entity, game)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once_with(entity, game)
        ctrl.rotate_camera_to.assert_not_called()

    def test_walk_action_falls_back_to_rotation_without_minimap_coords(self, mock_dca):
        """If the entity has no minimap coordinates, fall back to rotating toward it."""
        mock_dca.return_value = "walk"
        ctrl = self._ctrl_spied(click_minimap_result=False)
        entity = {"onScreen": False, "worldX": 3225, "worldY": 3218, "minimapX": None, "minimapY": None}
        game = MagicMock(tick=10)
        result = ctrl.bring_entity_on_screen(entity, game)
        assert result is False
        ctrl.click_minimap_entity.assert_called_once_with(entity, game)
        ctrl.rotate_camera_to.assert_called_once_with(entity, game)

    def test_passes_entity_and_game_to_decide(self, mock_dca):
        mock_dca.return_value = "on_screen"
        ctrl = self._ctrl_spied()
        entity = {"onScreen": True, "worldX": 3225, "worldY": 3218}
        game = MagicMock(tick=10)
        ctrl.bring_entity_on_screen(entity, game)
        mock_dca.assert_called_once_with(entity, game)


# ---------------------------------------------------------------------------
# click_minimap_entity
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestClickMinimapEntity:
    """click_minimap_entity issues a click at minimapX/Y, or returns False when absent.

    The walk-tracking/throttling behaviour itself is covered separately by
    TestMinimapWalkInProgress — these tests use a fresh controller (no walk
    yet tracked) so every call here issues an immediate click.
    """

    def _ctrl(self, mock_settings, window=WINDOW) -> GameController:
        mock_settings.get.side_effect = lambda k: 0 if k == "hull_y_offset" else "RuneLite"
        ctrl = GameController(human=_human())
        ctrl._window = window
        return ctrl

    def test_returns_true_and_clicks_when_minimap_coords_present(self, mock_mouse, mock_settings):
        mock_mouse.get_position.return_value = (500.0, 400.0)
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": 90}
        result = ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        assert result is True
        mock_mouse.click_left.assert_called_once()

    def test_returns_false_when_minimap_x_is_none(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": None, "minimapY": 90}
        result = ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_returns_false_when_minimap_y_is_none(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": None}
        result = ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_returns_false_when_minimap_keys_absent(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks"}
        result = ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        assert result is False
        mock_mouse.click_left.assert_not_called()

    def test_click_uses_minimap_canvas_coords(self, mock_mouse, mock_settings):
        mock_mouse.get_position.return_value = (500.0, 400.0)
        mock_settings.get.side_effect = lambda k: 0 if k == "hull_y_offset" else "RuneLite"
        human = _human()
        ctrl = GameController(human=human)
        ctrl._window = WINDOW
        entity = {"name": "Iron rocks", "minimapX": 650, "minimapY": 90}
        ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        # plan_click should have been called with screen coords derived from (650, 90)
        left, top, _, _ = WINDOW
        call_args = human.plan_click.call_args[0]
        assert call_args[0] == left + 650   # screen_x
        assert call_args[1] == top + 90     # screen_y (y_off=0)

    def test_no_walk_is_tracked_when_no_minimap_coords(self, mock_mouse, mock_settings):
        """No click was issued, so there's nothing to track/throttle."""
        ctrl = self._ctrl(mock_settings)
        entity = {"name": "Iron rocks", "minimapX": None, "minimapY": None}
        ctrl.click_minimap_entity(entity, _WalkGameState(tick=10))
        assert ctrl._minimap_walk is None


# ---------------------------------------------------------------------------
# click_minimap_entity — non-blocking walk tracking (prevents spam-clicking)
# ---------------------------------------------------------------------------

class _WalkGameState:
    """Minimal stand-in for GameState driving _minimap_walk_in_progress tests.

    Exposes a settable ``tick`` and ``player_idle()`` so a test can advance
    the walk state machine one tick at a time, exactly as the engine does by
    calling routine.tick() with a freshly-updated game_state each message.
    """

    def __init__(self, tick: int = 0, idle: bool = False):
        self.tick = tick
        self.idle = idle

    def player_idle(self) -> bool:
        return self.idle


@patch("scripts.gamebridge.controller.controller._settings")
@patch("scripts.gamebridge.controller.controller.mouse_input")
class TestMinimapWalkInProgress:
    """
    A minimap click kicks off a multi-tick walk. Re-clicking every tick would
    queue up redundant walk requests ("spam clicking", which a human never
    does) — and, critically, the engine drives routine.tick() synchronously
    inside the very loop that polls game state (process_tick → game.update()
    → routine.tick()), so a *blocking* wait here would freeze the engine on
    stale data: it would see the same dead minimap position forever (this is
    exactly the live bug recorded in PLAN.md "Session: 2026-06-07 (4)").
    _minimap_walk_in_progress must therefore be a pure, non-blocking check of
    the already-updated game_state handed to it on each tick.

    Phases tracked after the initial click at tick T:
      1. registration — ticks T .. T+START_TICKS-1: assume the walk is just
         starting, don't check idle yet, don't re-click;
      2. walking — once registration elapses, wait for player_idle();
      3. settling — once idle, wait SETTLE_TICKS consecutive idle ticks
         before allowing a re-click (idle streak resets if the player moves
         again, e.g. continuing along a multi-tile path).
    MAX_TICKS is a safety cap: if the walk never settles (e.g. a blocked
    path), the tracked state is dropped and a re-click is allowed.
    """

    def _ctrl(self, mock_settings, mock_mouse, window=WINDOW) -> GameController:
        mock_settings.get.side_effect = lambda k: 0 if k == "hull_y_offset" else "RuneLite"
        mock_mouse.get_position.return_value = (500.0, 400.0)
        ctrl = GameController(human=_human())
        ctrl._window = window
        return ctrl

    def _entity(self):
        return {"name": "Iron rocks", "minimapX": 650, "minimapY": 90}

    def test_first_call_clicks_and_starts_tracking(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)

        result = ctrl.click_minimap_entity(self._entity(), game)

        assert result is True
        mock_mouse.click_left.assert_called_once()
        assert ctrl._minimap_walk == {"clicked_tick": 10, "idle_since_tick": None}

    def test_does_not_reclick_during_registration(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)
        ctrl.click_minimap_entity(self._entity(), game)
        mock_mouse.click_left.reset_mock()

        for offset in range(MINIMAP_WALK_START_TICKS):
            game.tick = 10 + offset
            assert ctrl.click_minimap_entity(self._entity(), game) is True
            mock_mouse.click_left.assert_not_called()

    def test_does_not_reclick_while_walking(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)
        ctrl.click_minimap_entity(self._entity(), game)
        mock_mouse.click_left.reset_mock()

        # Past registration, but the player is still animating/moving
        game.tick = 10 + MINIMAP_WALK_START_TICKS
        game.idle = False
        result = ctrl.click_minimap_entity(self._entity(), game)

        assert result is True
        mock_mouse.click_left.assert_not_called()
        assert ctrl._minimap_walk["idle_since_tick"] is None

    def test_reclicks_only_after_settle_ticks_of_idle(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)
        ctrl.click_minimap_entity(self._entity(), game)
        mock_mouse.click_left.reset_mock()

        # Past registration and now idle — settling starts counting this tick
        idle_start = 10 + MINIMAP_WALK_START_TICKS
        game.tick = idle_start
        game.idle = True
        assert ctrl.click_minimap_entity(self._entity(), game) is True
        mock_mouse.click_left.assert_not_called()

        # Fewer than SETTLE_TICKS of consecutive idle so far — still tracked
        for offset in range(1, MINIMAP_WALK_SETTLE_TICKS):
            game.tick = idle_start + offset
            assert ctrl.click_minimap_entity(self._entity(), game) is True
            mock_mouse.click_left.assert_not_called()

        # SETTLE_TICKS of idle have elapsed — walk settled, re-click allowed
        game.tick = idle_start + MINIMAP_WALK_SETTLE_TICKS
        result = ctrl.click_minimap_entity(self._entity(), game)

        assert result is True
        mock_mouse.click_left.assert_called_once()
        assert ctrl._minimap_walk == {"clicked_tick": game.tick, "idle_since_tick": None}

    def test_idle_streak_resets_if_player_moves_again(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)
        ctrl.click_minimap_entity(self._entity(), game)

        idle_start = 10 + MINIMAP_WALK_START_TICKS
        game.tick = idle_start
        game.idle = True
        ctrl.click_minimap_entity(self._entity(), game)
        assert ctrl._minimap_walk["idle_since_tick"] == idle_start

        # Player resumes walking (e.g. continuing along a multi-tile path)
        game.tick = idle_start + 1
        game.idle = False
        ctrl.click_minimap_entity(self._entity(), game)
        assert ctrl._minimap_walk["idle_since_tick"] is None

    def test_gives_up_and_reclicks_after_max_ticks(self, mock_mouse, mock_settings):
        ctrl = self._ctrl(mock_settings, mock_mouse)
        game = _WalkGameState(tick=10)
        ctrl.click_minimap_entity(self._entity(), game)
        mock_mouse.click_left.reset_mock()

        # Player never settles (e.g. stuck on a blocked path) — cap kicks in
        game.tick = 10 + MINIMAP_WALK_MAX_TICKS
        game.idle = False
        result = ctrl.click_minimap_entity(self._entity(), game)

        assert result is True
        mock_mouse.click_left.assert_called_once()
        assert ctrl._minimap_walk == {"clicked_tick": game.tick, "idle_since_tick": None}


# ---------------------------------------------------------------------------
# Live clickbox subscriptions — set_connection / subscribe_to / unsubscribe / hull_update
# ---------------------------------------------------------------------------

class TestSubscriptions:
    def test_subscribe_to_without_connection_logs_warning_and_noops(self, caplog):
        ctrl = _ctrl()
        with caplog.at_level(logging.WARNING):
            ctrl.subscribe_to("fish_spot", "object", name="Fishing spot")
        assert "fish_spot" in caplog.text

    def test_unsubscribe_without_connection_logs_warning_and_noops(self, caplog):
        ctrl = _ctrl()
        with caplog.at_level(logging.WARNING):
            ctrl.unsubscribe("fish_spot")
        assert "fish_spot" in caplog.text

    def test_hull_update_without_connection_returns_none(self):
        ctrl = _ctrl()
        assert ctrl.hull_update("fish_spot") is None

    def test_subscribe_to_delegates_to_connection(self):
        ctrl = _ctrl()
        conn = MagicMock(spec=BridgeConnection)
        ctrl.set_connection(conn)

        ctrl.subscribe_to("fish_spot", "object", name="Fishing spot", id=1497, ttl_ticks=5)

        conn.subscribe.assert_called_once_with(
            "fish_spot", "object", name="Fishing spot", id=1497, ttl_ticks=5
        )

    def test_unsubscribe_delegates_to_connection(self):
        ctrl = _ctrl()
        conn = MagicMock(spec=BridgeConnection)
        ctrl.set_connection(conn)

        ctrl.unsubscribe("fish_spot")

        conn.unsubscribe.assert_called_once_with("fish_spot")

    def test_hull_update_returns_value_from_connection(self):
        ctrl = _ctrl()
        conn = MagicMock(spec=BridgeConnection)
        conn.hull_updates = {"fish_spot": {"found": True, "canvasX": 1}}
        ctrl.set_connection(conn)

        assert ctrl.hull_update("fish_spot") == {"found": True, "canvasX": 1}

    def test_hull_update_missing_sub_id_returns_none(self):
        ctrl = _ctrl()
        conn = MagicMock(spec=BridgeConnection)
        conn.hull_updates = {}
        ctrl.set_connection(conn)

        assert ctrl.hull_update("fish_spot") is None

    def test_set_connection_none_clears_connection(self):
        ctrl = _ctrl()
        conn = MagicMock(spec=BridgeConnection)
        ctrl.set_connection(conn)
        ctrl.set_connection(None)


# ---------------------------------------------------------------------------
# hold_key / release_key / release_all_keys
# ---------------------------------------------------------------------------

@patch("scripts.gamebridge.controller.controller.kb_input")
class TestHoldKey:
    def test_presses_key_down(self, mock_kb):
        _ctrl().hold_key(Key.SHIFT)
        mock_kb.key_down.assert_called_once_with(Key.SHIFT)

    def test_tracks_key_as_held(self, mock_kb):
        ctrl = _ctrl()
        ctrl.hold_key(Key.SHIFT)
        assert Key.SHIFT in ctrl._held_keys

    def test_second_hold_is_a_noop(self, mock_kb):
        """Holding an already-held key must not press it again."""
        ctrl = _ctrl()
        ctrl.hold_key(Key.SHIFT)
        ctrl.hold_key(Key.SHIFT)
        mock_kb.key_down.assert_called_once_with(Key.SHIFT)


@patch("scripts.gamebridge.controller.controller.kb_input")
class TestReleaseKey:
    def test_releases_held_key(self, mock_kb):
        ctrl = _ctrl()
        ctrl.hold_key(Key.SHIFT)
        ctrl.release_key(Key.SHIFT)
        mock_kb.key_up.assert_called_once_with(Key.SHIFT)

    def test_removes_key_from_held_set(self, mock_kb):
        ctrl = _ctrl()
        ctrl.hold_key(Key.SHIFT)
        ctrl.release_key(Key.SHIFT)
        assert Key.SHIFT not in ctrl._held_keys

    def test_releasing_unheld_key_is_a_noop(self, mock_kb):
        ctrl = _ctrl()
        ctrl.release_key(Key.SHIFT)
        mock_kb.key_up.assert_not_called()


@patch("scripts.gamebridge.controller.controller.kb_input")
class TestReleaseAllKeys:
    def test_releases_every_held_key(self, mock_kb):
        ctrl = _ctrl()
        ctrl.hold_key(Key.SHIFT)
        ctrl.hold_key(Key.CTRL)

        ctrl.release_all_keys()

        mock_kb.key_up.assert_any_call(Key.SHIFT)
        mock_kb.key_up.assert_any_call(Key.CTRL)
        assert ctrl._held_keys == set()

    def test_noop_when_nothing_held(self, mock_kb):
        ctrl = _ctrl()
        ctrl.release_all_keys()
        mock_kb.key_up.assert_not_called()

        assert ctrl.hull_update("fish_spot") is None
