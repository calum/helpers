"""
Routine base class — a minimal state-machine framework for game automation.

Concepts
────────
A Routine is a class whose methods are states.  Each state method is called
once per game tick.  It returns the name of the next state to transition to,
or None / nothing to remain in the current state.

One method must be decorated with @initial_state — that is where execution
begins when the routine starts (or is reset).

A state method receives two arguments: the current GameState and the
GameController.  It should be fast (it runs on the game tick thread) — long
waits should be expressed as repeated tick calls that return None until a
condition is satisfied, rather than blocking sleep calls inside the method.

Example
───────
    from scripts.gamebridge.routines.base import Routine, initial_state
    from scripts.gamebridge.state.game_state import GameState
    from scripts.gamebridge.controller.controller import GameController

    class LogPlayerPos(Routine):

        @initial_state
        def watching(self, game: GameState, ctrl: GameController) -> None:
            print(f"Tick {game.tick}: player at {game.player_pos}")
            # Return None → stay in 'watching' forever

Error handling
──────────────
If a state method raises an exception it is logged and the routine stays
in the current state (it does not crash the engine).  This lets transient
errors (e.g. an entity momentarily disappearing) self-heal on the next tick.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..state.game_state import GameState
    from ..controller.controller import GameController

log = logging.getLogger(__name__)

_INITIAL_ATTR = "__routine_initial__"


def initial_state(fn: Callable) -> Callable:
    """Decorator — mark a state method as the entry point of the routine."""
    setattr(fn, _INITIAL_ATTR, True)
    return fn


class Routine:
    """
    Base class for all game automation routines.

    Subclass this, define state methods, and decorate one with @initial_state.
    The DecisionEngine calls tick() once per game tick.
    """

    def __init__(self) -> None:
        self._current: str = self._discover_initial()
        self._previous: str = ""
        self._state_enter_tick: int = 0
        log.info("[%s] Ready — initial state: %s", self.name, self._current)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_initial(self) -> str:
        for attr in dir(self):
            if attr.startswith("_"):
                continue
            method = getattr(self.__class__, attr, None)
            if callable(method) and getattr(method, _INITIAL_ATTR, False):
                return attr
        raise RuntimeError(
            f"{self.__class__.__name__} has no @initial_state method. "
            "Decorate exactly one state method with @initial_state."
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def current_state(self) -> str:
        return self._current

    @property
    def previous_state(self) -> str:
        return self._previous

    def ticks_in_state(self, game: "GameState") -> int:
        """How many ticks have elapsed since entering the current state."""
        return game.tick - self._state_enter_tick

    def tick(self, game: "GameState", ctrl: "GameController") -> None:
        """
        Called by the DecisionEngine once per game tick.

        Dispatches to the current state method.  If the method returns a
        string, that becomes the new state.  None (or no return) keeps the
        current state.
        """
        method = getattr(self, self._current, None)
        if method is None:
            raise RuntimeError(f"[{self.name}] Unknown state '{self._current}'")

        try:
            result: Optional[str] = method(game, ctrl)
        except Exception:
            log.exception("[%s] Exception in state '%s'", self.name, self._current)
            return

        if result is not None and result != self._current:
            if not hasattr(self, result) or not callable(getattr(self, result)):
                log.error(
                    "[%s] State '%s' tried to transition to unknown state '%s'",
                    self.name, self._current, result,
                )
                return
            log.info("[%s] %s → %s  (tick %d)", self.name, self._current, result, game.tick)
            self._previous = self._current
            self._current = result
            self._state_enter_tick = game.tick

    def reset(self) -> None:
        """Return to the initial state."""
        self._current = self._discover_initial()
        self._previous = ""
        log.info("[%s] Reset to initial state: %s", self.name, self._current)
