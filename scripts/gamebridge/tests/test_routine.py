"""
Tests for the Routine state-machine base class.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import logging
from unittest.mock import MagicMock

import pytest

from scripts.gamebridge.routines.base import Routine, initial_state
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Minimal test routines
# ---------------------------------------------------------------------------

class _Trivial(Routine):
    """Stays in 'watching' forever."""
    @initial_state
    def watching(self, game, ctrl):
        return None


class _TwoState(Routine):
    """Transitions a → b on the first tick, stays in b thereafter."""
    @initial_state
    def a(self, game, ctrl):
        return "b"

    def b(self, game, ctrl):
        return None


class _SelfLoop(Routine):
    """Explicitly returns its own state name — should not re-enter or log."""
    @initial_state
    def idle(self, game, ctrl):
        return "idle"


class _Raises(Routine):
    """Raises in its initial state every tick."""
    @initial_state
    def boom(self, game, ctrl):
        raise RuntimeError("intentional test error")


class _BadTransition(Routine):
    """Returns a non-existent state name."""
    @initial_state
    def start(self, game, ctrl):
        return "nonexistent_state"


class _Counting(Routine):
    """Counts how many times tick() dispatches to each state."""
    counts: dict

    def __init__(self):
        self.counts = {"start": 0, "done": 0}
        super().__init__()

    @initial_state
    def start(self, game, ctrl):
        self.counts["start"] += 1
        return "done"

    def done(self, game, ctrl):
        self.counts["done"] += 1
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game(tick: int = 1) -> GameState:
    g = GameState()
    g.tick = tick
    return g


def _tick(routine: Routine, tick: int = 1) -> None:
    routine.tick(_game(tick), ctrl=None)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestRoutineInit:
    def test_initial_state_discovered(self):
        r = _Trivial()
        assert r.current_state == "watching"

    def test_two_state_initial_is_a(self):
        r = _TwoState()
        assert r.current_state == "a"

    def test_no_initial_state_raises(self):
        class Bad(Routine):
            def some_state(self, game, ctrl):
                pass

        with pytest.raises(RuntimeError, match="no @initial_state"):
            Bad()

    def test_name_is_class_name(self):
        assert _Trivial().name == "_Trivial"
        assert _TwoState().name == "_TwoState"

    def test_previous_state_starts_empty(self):
        assert _Trivial().previous_state == ""


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestRoutineTransitions:
    def test_none_return_stays_in_state(self):
        r = _Trivial()
        _tick(r)
        assert r.current_state == "watching"

    def test_string_return_transitions(self):
        r = _TwoState()
        _tick(r)
        assert r.current_state == "b"

    def test_previous_state_recorded_on_transition(self):
        r = _TwoState()
        _tick(r)
        assert r.previous_state == "a"

    def test_stays_in_terminal_state(self):
        r = _TwoState()
        _tick(r)
        _tick(r)
        _tick(r)
        assert r.current_state == "b"

    def test_self_loop_does_not_change_previous(self):
        r = _SelfLoop()
        _tick(r)
        # Returning own state name is a no-op
        assert r.current_state == "idle"
        assert r.previous_state == ""  # no real transition occurred

    def test_state_enter_tick_recorded(self):
        r = _TwoState()
        r.tick(_game(tick=5), ctrl=None)
        assert r._state_enter_tick == 5

    def test_ticks_in_state_increases(self):
        r = _Trivial()
        # Entered at tick 0 (default), now at tick 10
        assert r.ticks_in_state(_game(tick=10)) == 10

    def test_ticks_in_state_resets_after_transition(self):
        r = _TwoState()
        r.tick(_game(tick=7), ctrl=None)  # transitions a→b at tick 7
        assert r.ticks_in_state(_game(tick=8)) == 1

    def test_dispatches_each_tick(self):
        r = _Counting()
        _tick(r, tick=1)  # start → done
        _tick(r, tick=2)  # done → None (stay)
        _tick(r, tick=3)
        assert r.counts["start"] == 1
        assert r.counts["done"] == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestRoutineErrors:
    def test_exception_does_not_crash_caller(self):
        r = _Raises()
        _tick(r)  # must not raise

    def test_state_unchanged_after_exception(self):
        r = _Raises()
        _tick(r)
        assert r.current_state == "boom"

    def test_exception_logged(self, caplog):
        r = _Raises()
        with caplog.at_level(logging.ERROR, logger="scripts.gamebridge.routines.base"):
            _tick(r)
        # caplog.text includes the formatted traceback; the exception message appears there
        assert "intentional test error" in caplog.text

    def test_bad_transition_stays_in_state(self, caplog):
        r = _BadTransition()
        with caplog.at_level(logging.ERROR, logger="scripts.gamebridge.routines.base"):
            _tick(r)
        assert r.current_state == "start"

    def test_bad_transition_logs_error(self, caplog):
        r = _BadTransition()
        with caplog.at_level(logging.ERROR, logger="scripts.gamebridge.routines.base"):
            _tick(r)
        assert any("nonexistent_state" in r.message for r in caplog.records)

    def test_exception_releases_held_keys(self):
        """A held modifier key (e.g. Shift mid drop-sequence) must not be
        left stuck down if the current state raises."""
        r = _Raises()
        ctrl = MagicMock()
        r.tick(_game(1), ctrl=ctrl)
        ctrl.release_all_keys.assert_called_once()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestRoutineReset:
    def test_reset_returns_to_initial(self):
        r = _TwoState()
        _tick(r)
        assert r.current_state == "b"
        r.reset()
        assert r.current_state == "a"

    def test_reset_clears_previous(self):
        r = _TwoState()
        _tick(r)
        r.reset()
        assert r.previous_state == ""

    def test_state_machine_runs_normally_after_reset(self):
        r = _TwoState()
        _tick(r)
        r.reset()
        _tick(r)
        assert r.current_state == "b"
        assert r.previous_state == "a"
