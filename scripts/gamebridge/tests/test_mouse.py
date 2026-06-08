"""
Unit tests for wind_mouse_to_prediction — the moving-target WindMouse variant.

Hardware calls (move_to, time.sleep, time.monotonic) are mocked at module
level — no real input is produced and no wall-clock time is consumed.

Run with:
    python -m pytest scripts/gamebridge/tests/test_mouse.py -v
"""
import random
from unittest.mock import patch

from scripts.gamebridge.input import mouse


class _PredictStub:
    """Cycles through a fixed list of (x, y) positions on each call, recording
    the wall-clock instant it was invoked with."""

    def __init__(self, *positions):
        self._positions = list(positions)
        self.calls = []

    def __call__(self, at_time):
        self.calls.append(at_time)
        return self._positions[(len(self.calls) - 1) % len(self._positions)]

    @property
    def last_returned(self):
        return self._positions[(len(self.calls) - 1) % len(self._positions)]


class TestWindMouseToPrediction:
    def test_lands_on_a_stationary_target(self):
        predict = _PredictStub((500.0, 400.0))
        with patch.object(mouse, "move_to") as mock_move_to, \
                patch.object(mouse.time, "sleep"):
            mouse.wind_mouse_to_prediction(0.0, 0.0, predict, rng=random.Random(1))

        assert mock_move_to.called
        assert mock_move_to.call_args.args == (500.0, 400.0)

    def test_lock_on_correction_lands_on_freshest_prediction(self):
        """The final move must match whatever predict() returns on its very
        last call — not a value captured earlier in the approach, which could
        be stale by the time the cursor arrives."""
        predict = _PredictStub((500.0, 400.0), (502.0, 398.0), (498.0, 402.0), (501.0, 399.0))
        with patch.object(mouse, "move_to") as mock_move_to, \
                patch.object(mouse.time, "sleep"):
            mouse.wind_mouse_to_prediction(0.0, 0.0, predict, rng=random.Random(2))

        assert mock_move_to.call_args.args == predict.last_returned

    def test_destination_is_re_evaluated_every_step(self):
        """Confirms predict() is queried repeatedly through the approach —
        not captured once up front — which is the entire point of this
        variant over plain wind_mouse."""
        predict = _PredictStub((500.0, 400.0), (502.0, 398.0), (498.0, 402.0), (501.0, 399.0))
        with patch.object(mouse, "move_to"), \
                patch.object(mouse.time, "sleep"):
            mouse.wind_mouse_to_prediction(0.0, 0.0, predict, rng=random.Random(3))

        assert len(predict.calls) > 10

    def test_predict_is_called_with_monotonic_wallclock_time(self):
        predict = _PredictStub((500.0, 400.0))
        with patch.object(mouse, "move_to"), \
                patch.object(mouse.time, "sleep"), \
                patch.object(mouse.time, "monotonic", return_value=12345.5):
            mouse.wind_mouse_to_prediction(0.0, 0.0, predict, rng=random.Random(4))

        assert predict.calls
        assert all(t == 12345.5 for t in predict.calls)

    def test_terminates_well_within_the_step_cap(self):
        predict = _PredictStub((500.0, 400.0))
        with patch.object(mouse, "move_to"), \
                patch.object(mouse.time, "sleep"):
            mouse.wind_mouse_to_prediction(0.0, 0.0, predict, rng=random.Random(5))

        assert len(predict.calls) < 10_000
