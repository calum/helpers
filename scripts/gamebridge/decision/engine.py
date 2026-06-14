"""
Decision engine.

Sits between the GameBridge stream and the active Routine.
Each incoming tick message is applied to GameState, then the active
Routine's tick() is called so it can react to the new state.

The engine also handles:
  • Break scheduling (via HumanEmulator.should_take_break)
  • Routine swapping at any time
  • Emergency stop (set_routine(None) or stop())

Ingest vs. drive
────────────────
process_tick() does both steps inline — fine for single-threaded callers
(tests, main.py) where the whole pipeline runs on one thread.

The dashboard instead calls ingest() and drive() from two separate threads
(BridgeTicker / RoutineRunner — see bridge_ticker.py): a Routine's actions
(mouse movement, click pauses, scheduled breaks) block for human-like
durations, and running them on the same thread that reads the TCP stream
would stall GameState updates for as long as the action takes — leaving the
routine to act on stale data. Splitting them means ingestion always keeps
GameState current, and drive() always reacts to the very latest snapshot
rather than one queued behind a backlog of stale ticks.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..state.game_state import GameState
from ..controller.controller import GameController
from ..routines.base import Routine

log = logging.getLogger(__name__)


class DecisionEngine:
    """
    Drives a Routine one tick at a time.

    Usage
    -----
        engine = DecisionEngine(ctrl=ctrl, human=human_emulator)
        engine.set_routine(IronMiningRoutine())

        for msg in client.stream():
            engine.process_tick(msg)
    """

    def __init__(
        self,
        ctrl: GameController,
        human=None,       # HumanEmulator | None
        scheduler=None,   # InterruptionScheduler | None
    ):
        self._ctrl = ctrl
        self._game = GameState()
        self._routine: Optional[Routine] = None
        self._human = human
        self._scheduler = scheduler
        self._session_start = time.monotonic()
        self._on_break = False
        self._break_until: float = 0.0
        self._break_duration: float = 0.0
        # Set by ingest() each time a new GameState snapshot is published;
        # the routine-driver loop waits on this instead of polling so it
        # picks up the latest snapshot as soon as it's available without
        # busy-spinning. See wait_for_snapshot().
        self._new_snapshot = threading.Event()

    # ------------------------------------------------------------------
    # Routine management
    # ------------------------------------------------------------------

    def set_routine(self, routine: Optional[Routine]) -> None:
        """Replace the active routine immediately (or pass None to stop)."""
        # Release any modifier keys (e.g. Shift, held mid drop-sequence) the
        # outgoing routine left down — see GameController.release_all_keys.
        self._ctrl.release_all_keys()

        if routine is None:
            log.info("Routine cleared — engine is idle.")
            self._ctrl.min_click_interval = 0.0
        else:
            interval = getattr(routine, "CLICK_INTERVAL", 0.0)
            self._ctrl.min_click_interval = interval
            log.info(
                "Activating routine: %s (state: %s, click_interval: %.2fs)",
                routine.name, routine.current_state, interval,
            )
        self._routine = routine

    def stop(self) -> None:
        self.set_routine(None)

    # ------------------------------------------------------------------
    # Tick processing
    # ------------------------------------------------------------------

    def ingest(self, msg: dict) -> None:
        """
        Apply a raw tick message and publish the result as the latest snapshot.

        Builds the new GameState on a private clone of the previous one, then
        publishes it with a single attribute assignment — so drive() (running
        on another thread) always sees either the previous, fully-formed
        snapshot or the new one, never one that's mid-update.

        Call this for every message yielded by client.stream(). Never call
        this from the same loop that also runs routine actions — see the
        module docstring.
        """
        new_state = self._game.clone()
        new_state.update(msg)
        self._game = new_state
        self._new_snapshot.set()

    def wait_for_snapshot(self, timeout: Optional[float] = None) -> bool:
        """
        Block until ingest() has published a snapshot since the last call
        (or this is the first call), or timeout elapses.

        Returns True if a new snapshot is available, False on timeout. The
        routine-driver loop uses this to wake exactly when there's fresh
        state to react to, rather than polling on a fixed interval.
        """
        fired = self._new_snapshot.wait(timeout)
        self._new_snapshot.clear()
        return fired

    def drive(self) -> None:
        """
        Run one decision step against the latest published GameState snapshot.

        Captures the active routine in a local variable up front: if
        set_routine() swaps it concurrently mid-call, this call finishes
        against the routine it started with — "finish the current tick, then
        swap" — and the new routine takes over on the next drive() call.
        """
        routine = self._routine
        if routine is None:
            return

        game = self._game
        # Feed the controller's EntityTracker before the routine acts on this
        # snapshot, so click_entity/move_to_entity/right_click_entity can
        # build MovingTarget predictions from up-to-date velocity. Must
        # happen here (not in ingest(), which runs on a different thread) —
        # see GameController.track_entities for the cross-thread rationale.
        self._ctrl.track_entities(game)

        # Interruption management — apply mood multipliers and pause when away
        if self._scheduler is not None:
            session_s = time.monotonic() - self._session_start
            self._scheduler.tick(session_s)
            if self._human is not None:
                self._human.set_interruption_multipliers(
                    reaction=self._scheduler.reaction_multiplier(),
                    click_error=self._scheduler.click_error_multiplier(),
                )
            if self._scheduler.away:
                return  # player is away from desk

        # Break management — non-blocking: check timestamps rather than sleeping
        if self._human is not None:
            now = time.monotonic()
            if self._on_break:
                if now < self._break_until:
                    return  # still resting
                # Break over — recover fatigue proportional to how long we rested
                self._on_break = False
                self._human.rest(self._break_duration)
                self._session_start = now
                log.info("Break over, resuming.")
                return

            session_s = now - self._session_start
            if self._human.should_take_break(session_s):
                duration = self._human.break_duration()
                self._break_duration = duration
                log.info("Scheduled %.0f s break.", duration)
                self._on_break = True
                self._break_until = now + duration
                return

        routine.tick(game, self._ctrl)

    def process_tick(self, msg: dict) -> None:
        """
        Apply a raw tick message and run one step of the active routine.

        Convenience for single-threaded callers (tests, main.py) — equivalent
        to ingest() followed by drive(). The dashboard calls them separately
        from different threads instead; see the module docstring.
        """
        self.ingest(msg)
        self.drive()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def game(self) -> GameState:
        """The current in-memory game state."""
        return self._game

    @property
    def routine(self) -> Optional[Routine]:
        return self._routine

    @property
    def on_break(self) -> bool:
        return self._on_break

    @property
    def break_remaining(self) -> float:
        """Seconds left in the current break (0.0 if not on break)."""
        if not self._on_break:
            return 0.0
        return max(0.0, self._break_until - time.monotonic())

    @property
    def interruption_active(self) -> bool:
        """True when an interruption is currently in any phase."""
        return self._scheduler is not None and self._scheduler.active is not None

    @property
    def interruption_type(self) -> Optional[str]:
        """The active interruption type name, or None."""
        if self._scheduler is not None and self._scheduler.active is not None:
            return self._scheduler.active.config.type.value
        return None
