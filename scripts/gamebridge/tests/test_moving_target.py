"""
Unit tests for MovingTarget — canvas-position prediction for moving entities.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import pytest

from scripts.gamebridge.state.moving_target import MovingTarget, TICK_DURATION_S


def _entity(canvas_x=412.0, canvas_y=380.0):
    return {"name": "Goblin", "onScreen": True, "canvasX": canvas_x, "canvasY": canvas_y}


# ---------------------------------------------------------------------------
# predict() with no velocity data — degrades to a stationary target
# ---------------------------------------------------------------------------

class TestPredictWithoutVelocity:
    def test_returns_static_position_at_as_of(self):
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=None, as_of=1000.0)
        assert target.predict(1000.0) == (400.0, 300.0)

    def test_returns_static_position_for_any_future_time(self):
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=None, as_of=1000.0)
        assert target.predict(1010.0) == (400.0, 300.0)


# ---------------------------------------------------------------------------
# predict() with velocity — extrapolates by elapsed ticks
# ---------------------------------------------------------------------------

class TestPredictWithVelocity:
    def test_returns_current_position_when_at_time_equals_as_of(self):
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=(2.0, -1.0), as_of=1000.0)
        assert target.predict(1000.0) == (400.0, 300.0)

    def test_extrapolates_one_tick_forward(self):
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=(2.0, -1.0), as_of=1000.0)
        x, y = target.predict(1000.0 + TICK_DURATION_S)
        assert x == pytest.approx(402.0)
        assert y == pytest.approx(299.0)

    def test_extrapolates_proportionally_to_elapsed_ticks(self):
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=(2.0, -1.0), as_of=1000.0)
        x, y = target.predict(1000.0 + TICK_DURATION_S * 2.5)
        assert x == pytest.approx(400.0 + 2.0 * 2.5)
        assert y == pytest.approx(300.0 - 1.0 * 2.5)

    def test_extrapolates_backwards_for_times_before_as_of(self):
        """Pure linear extrapolation — no special-casing of the past."""
        target = MovingTarget(canvas_pos=(400.0, 300.0), canvas_velocity=(2.0, -1.0), as_of=1000.0)
        x, y = target.predict(1000.0 - TICK_DURATION_S)
        assert x == pytest.approx(398.0)
        assert y == pytest.approx(301.0)


# ---------------------------------------------------------------------------
# from_entity()
# ---------------------------------------------------------------------------

class TestFromEntity:
    def test_builds_canvas_pos_from_entity(self):
        target = MovingTarget.from_entity(_entity(canvas_x=412.0, canvas_y=380.0),
                                           canvas_velocity=(1.0, 0.5), as_of=500.0)
        assert target.canvas_pos == (412.0, 380.0)
        assert target.canvas_velocity == (1.0, 0.5)
        assert target.as_of == 500.0

    def test_builds_with_no_velocity_data(self):
        target = MovingTarget.from_entity(_entity(), canvas_velocity=None, as_of=500.0)
        assert target.canvas_velocity is None
        assert target.predict(999.0) == target.canvas_pos
