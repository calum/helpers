"""
Decision engine.

Sits between the GameBridge stream and the active Routine.
Each incoming tick message is applied to GameState, then the active
Routine's tick() is called so it can react to the new state.

The engine also handles:
  • Break scheduling (via HumanEmulator.should_take_break)
  • Routine swapping at any time
  • Emergency stop (set_routine(None) or stop())
"""
from __future__ import annotations

import logging
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
        human=None,   # HumanEmulator | None
    ):
        self._ctrl = ctrl
        self._game = GameState()
        self._routine: Optional[Routine] = None
        self._human = human
        self._session_start = time.monotonic()
        self._on_break = False
        self._break_until: float = 0.0  # monotonic timestamp when break ends

    # ------------------------------------------------------------------
    # Routine management
    # ------------------------------------------------------------------

    def set_routine(self, routine: Optional[Routine]) -> None:
        """Replace the active routine immediately (or pass None to stop)."""
        if routine is None:
            log.info("Routine cleared — engine is idle.")
        else:
            log.info("Activating routine: %s (state: %s)", routine.name, routine.current_state)
        self._routine = routine

    def stop(self) -> None:
        self.set_routine(None)

    # ------------------------------------------------------------------
    # Tick processing
    # ------------------------------------------------------------------

    def process_tick(self, msg: dict) -> None:
        """
        Apply a raw tick message and run one step of the active routine.

        Call this for every message yielded by client.stream().
        """
        self._game.update(msg)

        if self._routine is None:
            return

        # Break management — non-blocking: check timestamps rather than sleeping
        if self._human is not None:
            now = time.monotonic()
            if self._on_break:
                if now < self._break_until:
                    return  # still resting
                # Break over
                self._on_break = False
                self._human.rest(self._break_until - (self._break_until - now))
                self._session_start = now
                log.info("Break over, resuming.")
                return

            session_s = now - self._session_start
            if self._human.should_take_break(session_s):
                duration = self._human.break_duration()
                log.info("Scheduled %.0f s break.", duration)
                self._on_break = True
                self._break_until = now + duration
                return

        self._routine.tick(self._game, self._ctrl)

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
