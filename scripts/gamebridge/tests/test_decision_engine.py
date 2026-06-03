"""
Tests for DecisionEngine.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
import time
import pytest
from unittest.mock import MagicMock

from scripts.gamebridge.decision.engine import DecisionEngine
from scripts.gamebridge.routines.base import Routine, initial_state
from scripts.gamebridge.state.game_state import GameState


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _Ctrl:
    """Minimal controller stub with the one attribute DecisionEngine writes."""
    def __init__(self):
        self.min_click_interval: float = 0.0


def _engine(human=None) -> DecisionEngine:
    return DecisionEngine(ctrl=_Ctrl(), human=human)


def _msg(tick: int = 1) -> dict:
    return {
        "tick": tick,
        "player": {
            "name": "Test", "worldX": 3221, "worldY": 3218, "plane": 0,
            "animation": -1, "hp": 99, "prayer": 50,
        },
        "events": [],
    }


class _NopRoutine(Routine):
    """Counts how many times tick() is called; never transitions."""
    def __init__(self):
        self.tick_count = 0
        super().__init__()

    CLICK_INTERVAL = 1.5

    @initial_state
    def idle(self, game, ctrl):
        self.tick_count += 1
        return None


class _TransitionRoutine(Routine):
    """Transitions once then stays."""
    def __init__(self):
        self.states_visited = []
        super().__init__()

    @initial_state
    def first(self, game, ctrl):
        self.states_visited.append("first")
        return "second"

    def second(self, game, ctrl):
        self.states_visited.append("second")
        return None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestDecisionEngineInit:
    def test_game_state_accessible(self):
        e = _engine()
        assert isinstance(e.game, GameState)

    def test_no_routine_initially(self):
        e = _engine()
        assert e.routine is None

    def test_not_on_break_initially(self):
        e = _engine()
        assert e.on_break is False

    def test_break_remaining_zero_initially(self):
        e = _engine()
        assert e.break_remaining == 0.0


# ---------------------------------------------------------------------------
# Routine management
# ---------------------------------------------------------------------------

class TestRoutineManagement:
    def test_set_routine_activates_it(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        assert e.routine is r

    def test_stop_clears_routine(self):
        e = _engine()
        e.set_routine(_NopRoutine())
        e.stop()
        assert e.routine is None

    def test_set_routine_applies_click_interval(self):
        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.set_routine(_NopRoutine())
        assert ctrl.min_click_interval == 1.5

    def test_stop_resets_click_interval_to_zero(self):
        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.set_routine(_NopRoutine())
        e.stop()
        assert ctrl.min_click_interval == 0.0

    def test_set_routine_none_is_same_as_stop(self):
        e = _engine()
        e.set_routine(_NopRoutine())
        e.set_routine(None)
        assert e.routine is None

    def test_replace_routine_mid_run(self):
        e = _engine()
        r1 = _NopRoutine()
        r2 = _NopRoutine()
        e.set_routine(r1)
        e.process_tick(_msg(1))
        e.set_routine(r2)
        e.process_tick(_msg(2))
        assert r1.tick_count == 1
        assert r2.tick_count == 1


# ---------------------------------------------------------------------------
# process_tick — game-state integration
# ---------------------------------------------------------------------------

class TestProcessTickState:
    def test_updates_game_tick(self):
        e = _engine()
        e.process_tick(_msg(tick=42))
        assert e.game.tick == 42

    def test_updates_player_pos(self):
        e = _engine()
        e.process_tick(_msg(tick=1))
        assert e.game.player_pos == (3221, 3218)

    def test_no_routine_does_not_raise(self):
        e = _engine()
        e.process_tick(_msg())  # engine is idle — must not crash

    def test_game_state_persists_across_ticks(self):
        e = _engine()
        e.process_tick({"tick": 1, "events": [
            {"type": "xp", "skill": "MINING", "xp": 500, "level": 10, "boostedLevel": 10},
        ]})
        e.process_tick({"tick": 2, "events": []})
        assert e.game.xp["MINING"] == 500  # not cleared on second tick


# ---------------------------------------------------------------------------
# process_tick — routine dispatch
# ---------------------------------------------------------------------------

class TestProcessTickRoutine:
    def test_routine_tick_called_each_message(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        for i in range(5):
            e.process_tick(_msg(tick=i))
        assert r.tick_count == 5

    def test_routine_receives_updated_game_state(self):
        class _Recorder(Routine):
            last_tick = -1

            @initial_state
            def watch(self, game, ctrl):
                _Recorder.last_tick = game.tick
                return None

        e = _engine()
        e.set_routine(_Recorder())
        e.process_tick(_msg(tick=99))
        assert _Recorder.last_tick == 99

    def test_routine_state_machine_runs(self):
        e = _engine()
        r = _TransitionRoutine()
        e.set_routine(r)
        e.process_tick(_msg(tick=1))
        e.process_tick(_msg(tick=2))
        assert r.states_visited == ["first", "second"]

    def test_routine_ctrl_passed_through(self):
        class _CtrlCapture(Routine):
            received_ctrl = None

            @initial_state
            def run(self, game, ctrl):
                _CtrlCapture.received_ctrl = ctrl
                return None

        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.set_routine(_CtrlCapture())
        e.process_tick(_msg())
        assert _CtrlCapture.received_ctrl is ctrl


# ---------------------------------------------------------------------------
# Break logic
# ---------------------------------------------------------------------------

class TestBreakLogic:
    def _human(self, should_break: bool, duration: float = 30.0):
        h = MagicMock()
        h.should_take_break.return_value = should_break
        h.break_duration.return_value = duration
        return h

    def test_break_triggered_when_human_says_so(self):
        human = self._human(should_break=True)
        e = _engine(human=human)
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg())
        assert e.on_break is True

    def test_routine_not_ticked_when_break_starts(self):
        human = self._human(should_break=True)
        e = _engine(human=human)
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg())
        assert r.tick_count == 0

    def test_routine_suppressed_while_on_break(self):
        human = self._human(should_break=True, duration=9999.0)
        e = _engine(human=human)
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg(1))  # triggers break
        # Subsequent ticks during the break
        human.should_take_break.return_value = False
        for i in range(3):
            e.process_tick(_msg(i + 2))
        assert r.tick_count == 0

    def test_break_remaining_nonzero_during_break(self):
        human = self._human(should_break=True, duration=60.0)
        e = _engine(human=human)
        e.set_routine(_NopRoutine())
        e.process_tick(_msg())
        assert e.break_remaining > 0.0

    def test_no_break_without_human_emulator(self):
        e = _engine(human=None)
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg())
        assert e.on_break is False
        assert r.tick_count == 1

    def test_routine_runs_when_human_says_no_break(self):
        human = self._human(should_break=False)
        e = _engine(human=human)
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg())
        assert r.tick_count == 1
        assert e.on_break is False
