"""
Human behaviour emulator.

This is a pure model — it produces timing, precision, and movement parameters
that mimic a real player.  It never performs any I/O itself; the controller
consumes its output to drive actual input.

The model has several tunable axes:
  • Reaction time   — how long before the player acts on a stimulus
  • Click precision — how far from the intended target clicks land
  • Fatigue         — degrades all other parameters over time
  • Break behaviour — decides when to take micro-breaks
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import List


# ------------------------------------------------------------------ #
# Output dataclasses — consumed by the controller
# ------------------------------------------------------------------ #

@dataclass
class ClickIntent:
    """Describes how a human would perform a single click."""
    target_x: float         # intended canvas X (centre of entity)
    target_y: float         # intended canvas Y
    actual_x: float         # where the cursor ends up (with human error)
    actual_y: float
    pre_move_pause: float   # seconds to wait before starting to move
    move_speed: float       # 0.0 (fast) – 1.0 (slow); passed to WindMouse
    post_move_pause: float  # hesitation between arriving and clicking (seconds)
    double_click: bool      # occasional accidental double-click


@dataclass
class TypingIntent:
    """Describes how a human would type a string."""
    text: str
    key_delays: List[float]  # per-character delay after key-up (seconds)


# ------------------------------------------------------------------ #
# HumanEmulator
# ------------------------------------------------------------------ #

class HumanEmulator:
    """
    Models the imprecise, variable behaviour of a human player.

    All methods are pure (no side effects) and thread-safe as long as
    you don't share an instance across threads without a lock.
    """

    def __init__(
        self,
        reaction_mean: float = 0.25,    # seconds, mean reaction time
        reaction_std: float = 0.07,     # seconds, std-dev of reaction time
        click_error_px: float = 4.0,    # std-dev of click offset from target
        overshoot_chance: float = 0.12, # probability of mouse overshoot
        wpm: float = 65.0,              # approximate typing speed
        fatigue: float = 0.0,           # 0.0 = fresh, 1.0 = exhausted
        rng_seed: int | None = None,
    ):
        self.reaction_mean = reaction_mean
        self.reaction_std = reaction_std
        self.click_error_px = click_error_px
        self.overshoot_chance = overshoot_chance
        self.wpm = wpm
        self.fatigue = fatigue
        self._rng = random.Random(rng_seed)

    # ------------------------------------------------------------------
    # Fatigue management
    # ------------------------------------------------------------------

    def accumulate_fatigue(self, delta: float = 0.0001) -> None:
        """Small incremental fatigue added each tick / action."""
        self.fatigue = min(1.0, self.fatigue + delta)

    def rest(self, duration_s: float) -> None:
        """Reduce fatigue proportional to break length."""
        recovery = duration_s / 300.0   # 5 minutes restores ~1.0
        self.fatigue = max(0.0, self.fatigue - recovery)

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    def reaction_time(self) -> float:
        """
        Sample a reaction time from a log-normal distribution.
        Fatigue inflates the mean; still clamped to a floor of 80 ms.
        """
        mean = self.reaction_mean * (1.0 + self.fatigue * 0.6)
        raw = self._rng.gauss(mean, self.reaction_std)
        return max(0.08, raw)

    def random_pause(self, lo: float = 0.05, hi: float = 0.25) -> float:
        """A random pause within [lo, hi], scaled by fatigue."""
        scale = 1.0 + self.fatigue * 0.4
        return self._rng.uniform(lo * scale, hi * scale)

    # ------------------------------------------------------------------
    # Click intent
    # ------------------------------------------------------------------

    def plan_click(
        self,
        canvas_x: float,
        canvas_y: float,
        current_mouse_x: float = 0.0,
        current_mouse_y: float = 0.0,
    ) -> ClickIntent:
        """
        Produce a ClickIntent for clicking on (canvas_x, canvas_y).

        The controller moves to (actual_x, actual_y) and then clicks.
        """
        dist = math.hypot(canvas_x - current_mouse_x, canvas_y - current_mouse_y)

        err = self.click_error_px * (1.0 + self.fatigue * 0.5)
        actual_x = canvas_x + self._rng.gauss(0.0, err)
        actual_y = canvas_y + self._rng.gauss(0.0, err)

        pre_move_pause = self.reaction_time()

        # Move speed: further = slower and more deliberate; fatigue adds more drag.
        # Divisor tuned so typical in-game clicks (100–400 px) land in 0.1–0.5 range.
        base_speed = max(0.05, dist / 800.0)
        move_speed = min(1.0, base_speed * (1.0 + self.fatigue * 0.3))

        post_move_pause = self.random_pause(0.03, 0.14)

        # Occasional accidental double-click (rarer when fresh)
        double_click = self._rng.random() < (0.01 + 0.04 * self.fatigue)

        return ClickIntent(
            target_x=canvas_x,
            target_y=canvas_y,
            actual_x=actual_x,
            actual_y=actual_y,
            pre_move_pause=pre_move_pause,
            move_speed=move_speed,
            post_move_pause=post_move_pause,
            double_click=double_click,
        )

    # ------------------------------------------------------------------
    # Typing intent
    # ------------------------------------------------------------------

    def plan_typing(self, text: str) -> TypingIntent:
        """
        Produce per-character delays for typing text.

        Base speed derives from WPM; fatigue slows it.  Spaces are
        slightly slower; repeated characters are slightly faster.
        """
        base_delay = 60.0 / (self.wpm * 5.0)   # seconds per character
        base_delay *= 1.0 + self.fatigue * 0.5

        delays: List[float] = []
        for i, ch in enumerate(text):
            d = self._rng.gauss(base_delay, base_delay * 0.2)
            if ch in " \t\n":
                d += self._rng.uniform(0.05, 0.12)
            if i > 0 and text[i - 1] == ch:
                d *= 0.85   # slightly faster repeating same key
            delays.append(max(0.03, d))

        return TypingIntent(text=text, key_delays=delays)

    # ------------------------------------------------------------------
    # Break modelling
    # ------------------------------------------------------------------

    def should_take_break(self, session_duration_s: float) -> bool:
        """
        Return True if the model decides the player should pause.

        Threshold drops from 30 min to ~20 min as fatigue climbs.
        A small random roll prevents completely predictable behaviour.
        """
        threshold = 1800.0 - self.fatigue * 600.0
        if session_duration_s < threshold:
            return False
        # 5 % chance per tick once over the threshold
        return self._rng.random() < 0.05

    def break_duration(self) -> float:
        """Sample a break length in seconds (20 s – 5 min)."""
        return self._rng.uniform(20.0, 300.0)

