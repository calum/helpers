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
    """Minimal controller stub with the attributes/methods DecisionEngine
    writes to or calls each drive() cycle."""
    def __init__(self):
        self.min_click_interval: float = 0.0
        self.tracked_states: list = []
        self.release_all_keys_calls: int = 0

    def track_entities(self, game_state) -> None:
        self.tracked_states.append(game_state)

    def release_all_keys(self) -> None:
        self.release_all_keys_calls += 1


def _engine(human=None, scheduler=None) -> DecisionEngine:
    return DecisionEngine(ctrl=_Ctrl(), human=human, scheduler=scheduler)


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

    def test_set_routine_releases_any_held_keys(self):
        """A routine swap (or stop) releases any modifier key (e.g. Shift)
        the outgoing routine left held mid drop-sequence."""
        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.set_routine(_NopRoutine())
        assert ctrl.release_all_keys_calls == 1
        e.set_routine(None)
        assert ctrl.release_all_keys_calls == 2


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
# ingest() / drive() split — see DecisionEngine module docstring.
#
# The dashboard runs these on separate threads (BridgeTicker / RoutineRunner)
# so a routine's blocking actions never stall game-state ingestion.
# process_tick() remains ingest()+drive() for single-threaded callers.
# ---------------------------------------------------------------------------

class TestIngestDriveSplit:
    def test_ingest_publishes_a_new_snapshot(self):
        e = _engine()
        original = e.game
        e.ingest(_msg(tick=5))
        assert e.game is not original
        assert e.game.tick == 5

    def test_ingest_does_not_run_the_routine(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        e.ingest(_msg(tick=1))
        assert r.tick_count == 0

    def test_drive_runs_against_the_latest_ingested_snapshot(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        e.ingest(_msg(tick=7))
        e.drive()
        assert r.tick_count == 1
        assert e.game.tick == 7

    def test_drive_without_a_prior_ingest_uses_initial_snapshot(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        e.drive()
        assert r.tick_count == 1
        assert e.game.tick == 0

    def test_process_tick_is_ingest_then_drive(self):
        e = _engine()
        r = _NopRoutine()
        e.set_routine(r)
        e.process_tick(_msg(tick=3))
        assert r.tick_count == 1
        assert e.game.tick == 3

    def test_drive_feeds_the_controllers_entity_tracker_with_the_current_snapshot(self):
        """drive() must hand the controller the same snapshot the routine is
        about to react to — and do it before routine.tick() runs, so any
        MovingTarget predictions the routine triggers use up-to-date
        velocity. See GameController.track_entities / PLAN.md "Phase 4"."""
        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        r = _NopRoutine()
        e.set_routine(r)

        e.ingest(_msg(tick=11))
        e.drive()

        assert len(ctrl.tracked_states) == 1
        assert ctrl.tracked_states[0] is e.game
        assert ctrl.tracked_states[0].tick == 11

    def test_drive_does_not_feed_the_tracker_when_idle(self):
        """No routine -> nothing will click -> no point tracking yet."""
        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.ingest(_msg(tick=1))
        e.drive()
        assert ctrl.tracked_states == []

    def test_tracker_is_fed_before_the_routine_runs(self):
        """The routine (and any clicks it triggers) must see a tracker that
        already knows about *this* snapshot — not the previous one."""
        class _Recorder(Routine):
            tracked_count_at_tick = None

            @initial_state
            def watch(self, game, ctrl):
                _Recorder.tracked_count_at_tick = len(ctrl.tracked_states)
                return None

        ctrl = _Ctrl()
        e = DecisionEngine(ctrl=ctrl)
        e.set_routine(_Recorder())
        e.ingest(_msg(tick=1))
        e.drive()

        assert _Recorder.tracked_count_at_tick == 1


class TestWaitForSnapshot:
    def test_true_after_ingest(self):
        e = _engine()
        e.ingest(_msg(tick=1))
        assert e.wait_for_snapshot(timeout=0) is True

    def test_false_when_already_consumed(self):
        e = _engine()
        e.ingest(_msg(tick=1))
        e.wait_for_snapshot(timeout=0)
        assert e.wait_for_snapshot(timeout=0) is False

    def test_true_again_after_a_further_ingest(self):
        e = _engine()
        e.ingest(_msg(tick=1))
        e.wait_for_snapshot(timeout=0)
        e.ingest(_msg(tick=2))
        assert e.wait_for_snapshot(timeout=0) is True

    def test_false_with_no_ingest_at_all(self):
        e = _engine()
        assert e.wait_for_snapshot(timeout=0) is False


# ---------------------------------------------------------------------------
# Routine-swap timing — "finish the current tick, then swap"
#
# drive() captures the active routine in a local variable up front, so a
# concurrent set_routine() call can never interrupt a routine mid-tick.
# ---------------------------------------------------------------------------

class TestRoutineSwapTiming:
    def test_swap_requested_mid_tick_completes_current_routine_first(self):
        e = _engine()
        r2 = _NopRoutine()

        class _SwapsMidTick(Routine):
            def __init__(self):
                self.ticked = False
                super().__init__()

            @initial_state
            def run(self, game, ctrl):
                e.set_routine(r2)   # simulate a concurrent swap request
                self.ticked = True  # this call must still finish against r1
                return None

        r1 = _SwapsMidTick()
        e.set_routine(r1)
        e.ingest(_msg(tick=1))
        e.drive()

        assert r1.ticked is True
        assert r2.tick_count == 0
        assert e.routine is r2  # set_routine() itself is still immediate/visible

        e.ingest(_msg(tick=2))
        e.drive()
        assert r2.tick_count == 1  # swap takes effect starting from the next drive()


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


class TestNextBreakEstimate:
    def test_none_without_human_or_scheduler(self):
        e = _engine()
        assert e.next_break_estimate is None

    def test_none_while_on_break(self):
        human = MagicMock()
        human.should_take_break.return_value = True
        human.break_duration.return_value = 60.0
        e = _engine(human=human)
        e.set_routine(_NopRoutine())
        e.process_tick(_msg())  # triggers the break
        assert e.on_break is True
        assert e.next_break_estimate is None

    def test_uses_human_eta_labelled_rest(self):
        human = MagicMock()
        human.should_take_break.return_value = False
        human.break_eta_seconds.return_value = 123.0
        e = _engine(human=human)
        label, eta = e.next_break_estimate
        assert label == "Rest"
        assert eta == pytest.approx(123.0)

    def test_picks_soonest_of_human_and_scheduler(self):
        human = MagicMock()
        human.should_take_break.return_value = False
        human.break_eta_seconds.return_value = 500.0

        scheduler = MagicMock()
        from scripts.gamebridge.human.interruptions import InterruptionType
        scheduler.next_interruption_estimate.return_value = (InterruptionType.DISCORD_MESSAGE, 50.0)

        e = _engine(human=human, scheduler=scheduler)
        label, eta = e.next_break_estimate
        assert label == "discord_message"
        assert eta == pytest.approx(50.0)

    def test_falls_back_to_human_when_scheduler_has_no_estimate(self):
        human = MagicMock()
        human.should_take_break.return_value = False
        human.break_eta_seconds.return_value = 200.0

        scheduler = MagicMock()
        scheduler.next_interruption_estimate.return_value = None

        e = _engine(human=human, scheduler=scheduler)
        label, eta = e.next_break_estimate
        assert label == "Rest"
        assert eta == pytest.approx(200.0)
