"""
Unit tests for wind_mouse_to_prediction — the moving-target WindMouse variant.

Hardware calls (move_to, time.sleep, time.monotonic) are mocked at module
level — no real input is produced and no wall-clock time is consumed.

Run with:
    python -m pytest scripts/gamebridge/tests/test_mouse.py -v
"""
import random
import statistics
from unittest.mock import MagicMock, call, patch

import pytest

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


# ---------------------------------------------------------------------------
# Pluggable backend — see GameController.use_bridge_input()
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_backend_after_each_test():
    """Guarantee no test leaks a backend into the next one — set_backend()
    mutates module-level state shared across the whole test session."""
    yield
    mouse.clear_backend()


class TestBackendDelegation:
    def test_get_position_delegates_to_backend_when_set(self):
        backend = MagicMock()
        backend.get_position.return_value = (12, 34)
        mouse.set_backend(backend)

        assert mouse.get_position() == (12, 34)

    def test_move_to_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.move_to(5, 6)

        backend.move_to.assert_called_once_with(5, 6)

    def test_click_left_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.click_left(7, 8)

        backend.click_left.assert_called_once_with(7, 8)

    def test_click_right_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.click_right()

        backend.click_right.assert_called_once_with(None, None)

    def test_clear_backend_restores_os_sendinput_path(self):
        backend = MagicMock()
        mouse.set_backend(backend)
        mouse.clear_backend()

        with patch.object(mouse, "_send_mouse_event") as mock_send, \
                patch.object(mouse, "_to_absolute", return_value=(0, 0)):
            mouse.move_to(1, 1)

        mock_send.assert_called_once()
        backend.move_to.assert_not_called()

    def test_no_backend_uses_os_sendinput_path(self):
        with patch.object(mouse, "_send_mouse_event") as mock_send, \
                patch.object(mouse, "_to_absolute", return_value=(0, 0)):
            mouse.move_to(1, 1)

        mock_send.assert_called_once()

    def test_button_down_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.button_down(mouse.BUTTON_LEFT)

        backend.button_down.assert_called_once_with(mouse.BUTTON_LEFT)

    def test_button_up_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.button_up(mouse.BUTTON_RIGHT)

        backend.button_up.assert_called_once_with(mouse.BUTTON_RIGHT)

    def test_scroll_delegates_to_backend_when_set(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.scroll(-2)

        backend.scroll.assert_called_once_with(-2)


# ---------------------------------------------------------------------------
# _step_wait — WindMouse timing realism (item 1)
# ---------------------------------------------------------------------------

class TestStepWait:
    def test_occasionally_produces_a_stutter_outlier(self):
        rng = random.Random(7)
        waits = [mouse._step_wait(0.5, 0.3, rng) for _ in range(500)]

        assert max(waits) > 2 * statistics.median(waits)

    def test_zero_stutter_chance_never_stutters(self):
        rng = random.Random(7)
        with patch.object(mouse, "STUTTER_CHANCE", 0.0):
            waits = [mouse._step_wait(0.5, 0.3, rng) for _ in range(500)]

        # Without the stutter branch, the only variance is the small
        # Gaussian jitter — never more than a few times the median.
        assert max(waits) < 3 * statistics.median(waits)

    def test_wait_is_never_negative_or_zero(self):
        rng = random.Random(3)
        for _ in range(200):
            assert mouse._step_wait(0.5, 0.3, rng) > 0.0


# ---------------------------------------------------------------------------
# button_down / button_up / drag_to (item 2)
# ---------------------------------------------------------------------------

class TestDrag:
    def test_button_down_os_path_sends_left_down(self):
        with patch.object(mouse, "_send_mouse_event") as mock_send:
            mouse.button_down(mouse.BUTTON_LEFT)

        mock_send.assert_called_once_with(mouse.MOUSEEVENTF_LEFTDOWN)

    def test_button_up_os_path_sends_right_up(self):
        with patch.object(mouse, "_send_mouse_event") as mock_send:
            mouse.button_up(mouse.BUTTON_RIGHT)

        mock_send.assert_called_once_with(mouse.MOUSEEVENTF_RIGHTUP)

    def test_drag_to_calls_button_down_wind_mouse_button_up_in_order(self):
        manager = MagicMock()
        with patch.object(mouse, "button_down", manager.button_down), \
                patch.object(mouse, "button_up", manager.button_up), \
                patch.object(mouse, "wind_mouse", manager.wind_mouse):
            mouse.drag_to(0, 0, 10, 10, button=mouse.BUTTON_LEFT)

        assert manager.mock_calls == [
            call.button_down(mouse.BUTTON_LEFT),
            call.wind_mouse(0, 0, 10, 10),
            call.button_up(mouse.BUTTON_LEFT),
        ]

    def test_drag_to_uses_bridge_backend_for_both_button_calls_and_movement(self):
        backend = MagicMock()
        mouse.set_backend(backend)

        mouse.drag_to(0, 0, 10, 10)

        backend.button_down.assert_called_once_with(mouse.BUTTON_LEFT)
        backend.button_up.assert_called_once_with(mouse.BUTTON_LEFT)
        assert backend.move_to.called


# ---------------------------------------------------------------------------
# scroll (item 5)
# ---------------------------------------------------------------------------

class TestScroll:
    def test_scroll_os_path_sends_wheel_event_with_negated_delta(self):
        with patch.object(mouse, "_send_mouse_event") as mock_send:
            mouse.scroll(1)

        mock_send.assert_called_once_with(mouse.MOUSEEVENTF_WHEEL, mouse_data=-mouse.WHEEL_DELTA)

    def test_scroll_os_path_negative_amount(self):
        with patch.object(mouse, "_send_mouse_event") as mock_send:
            mouse.scroll(-2)

        mock_send.assert_called_once_with(mouse.MOUSEEVENTF_WHEEL, mouse_data=2 * mouse.WHEEL_DELTA)
