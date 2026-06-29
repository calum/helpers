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


@dataclass
class KeyHoldIntent:
    """Describes how a human would hold a key (e.g. for camera rotation)."""
    hold_ms: float          # actual hold duration (with jitter applied)
    pre_hold_pause: float   # reaction time before pressing (seconds)
    post_hold_pause: float  # hesitation after releasing (seconds)


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
        # Multiplier layer — mood sets baseline at startup; interruptions add temporary overrides
        self._reaction_mult: float = 1.0
        self._error_mult: float = 1.0
        self._fatigue_rate_mult: float = 1.0
        self._break_freq_mult: float = 1.0
        # Attention layer — see set_attention_level(). Separate from the
        # interruption multipliers above: interruptions model a *distracted*
        # player (slower, sloppier), attention models how much focus a
        # routine demands right now (a fast-paced boss fight vs. idle
        # skilling) — the two can be active independently.
        self._attention_reaction_mult: float = 1.0
        self._attention_speed_mult: float = 1.0
        self._attention_pause_mult: float = 1.0

    # ------------------------------------------------------------------
    # Attention level — how much focus the current routine demands
    # ------------------------------------------------------------------

    # (reaction_mult, move_speed_mult, pause_mult) — all multiply the
    # corresponding base value; lower = faster. "combat" keeps every
    # source of randomness (reaction_time's gauss/floor, plan_click's
    # click-error gauss, WindMouse jitter) — it's a locked-in, fast-twitch
    # player, not a robot with zero variance.
    _ATTENTION_PRESETS: dict = {
        "normal": (1.0, 1.0, 1.0),
        "combat": (0.4, 0.45, 0.35),
    }

    def set_attention_level(self, level: str = "normal") -> None:
        """
        Adjust reaction/movement multipliers for how much attention the
        player is paying right now.

        'normal' (the default) models relaxed skilling/banking pacing.
        'combat' models a player locked onto a dangerous, fast-paced fight
        (e.g. dodging a boss's telegraphed special) — much quicker reflexes
        and more direct mouse movement, but still sampled from the same
        distributions, so it stays human rather than instant/robotic.

        Routines call this once per tick from every state that needs it
        (cheap, idempotent) via GameController.set_attention_level —
        there's no separate "end of combat" call required, since the next
        tick that doesn't call it simply leaves the last-set level in place
        until something sets it back to 'normal'.
        """
        if level not in self._ATTENTION_PRESETS:
            raise ValueError(f"Unknown attention level: {level!r}")
        reaction_mult, speed_mult, pause_mult = self._ATTENTION_PRESETS[level]
        self._attention_reaction_mult = reaction_mult
        self._attention_speed_mult = speed_mult
        self._attention_pause_mult = pause_mult

    # ------------------------------------------------------------------
    # Mood and interruption multipliers
    # ------------------------------------------------------------------

    def apply_mood(self, profile: "MoodProfile") -> None:  # type: ignore[name-defined]
        """
        Scale base emulator parameters by the session's MoodProfile.

        Called once at session startup after the mood is seeded. Permanently
        adjusts reaction_mean and click_error_px so all subsequent sampling
        reflects the player's emotional state for the day.

        TODO: Add mood to the dashboard
        """
        self.reaction_mean *= profile.reaction_multiplier
        self.click_error_px *= profile.click_error_multiplier
        self._fatigue_rate_mult = profile.fatigue_rate_multiplier
        self._break_freq_mult = profile.break_frequency_multiplier

    def set_interruption_multipliers(
        self,
        reaction: float = 1.0,
        click_error: float = 1.0,
    ) -> None:
        """
        Apply temporary per-tick overrides while an interruption is active.

        Called by the DecisionEngine each tick based on InterruptionScheduler
        state. Pass 1.0 for both to clear any active override.
        """
        self._reaction_mult = reaction
        self._error_mult = click_error

    # ------------------------------------------------------------------
    # Fatigue management
    # ------------------------------------------------------------------

    def accumulate_fatigue(self, delta: float = 0.0001) -> None:
        """Small incremental fatigue added each tick / action."""
        self.fatigue = min(1.0, self.fatigue + delta * self._fatigue_rate_mult)

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
        mean = (self.reaction_mean * self._reaction_mult * self._attention_reaction_mult
                * (1.0 + self.fatigue * 0.6))
        raw = self._rng.gauss(mean, self.reaction_std)
        return max(0.08 * self._attention_reaction_mult, raw)

    def random_pause(self, lo: float = 0.05, hi: float = 0.25) -> float:
        """A random pause within [lo, hi], scaled by fatigue and the current
        attention level (see set_attention_level)."""
        scale = (1.0 + self.fatigue * 0.4) * self._attention_pause_mult
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

        err = self.click_error_px * self._error_mult * (1.0 + self.fatigue * 0.5)
        actual_x = canvas_x + self._rng.gauss(0.0, err)
        actual_y = canvas_y + self._rng.gauss(0.0, err)

        pre_move_pause = self.reaction_time()

        # Move speed: further = slower and more deliberate; fatigue adds more drag.
        # Divisor tuned so typical in-game clicks (100–400 px) land in 0.1–0.5 range.
        #
        # Distance is capped before scaling: a human's deliberateness reflects
        # how precisely they need to land on the target, not how far the cursor
        # physically has to travel to get there. Without the cap, the very first
        # move of a session — starting whenever the OS cursor happens to be
        # (e.g. resting over a dashboard button hundreds of px outside the game
        # viewport) — saturates move_speed at 1.0. WindMouse then takes its
        # smallest steps and longest per-step waits over a long haul, which
        # looks like the cursor crawls, stalls near the target, then snaps to
        # place on the final move_to() — see PLAN.md, "Session: 2026-06-07 (6)".
        capped_dist = min(dist, 400.0)
        base_speed = max(0.05, capped_dist / 800.0)
        move_speed = min(1.0, base_speed * (1.0 + self.fatigue * 0.3) * self._attention_speed_mult)

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
    # Key hold intent
    # ------------------------------------------------------------------

    def plan_key_hold(self, intended_hold_ms: float) -> KeyHoldIntent:
        """
        Produce a KeyHoldIntent for holding a key (e.g. an arrow key for camera rotation).

        Applies Gaussian jitter to the duration and reaction-time modelling to the
        pre/post pauses — consistent with how plan_click models mouse actions.
        """
        jitter = self._rng.gauss(1.0, 0.12)
        jitter = max(0.7, min(1.3, jitter))
        hold_ms = max(20.0, intended_hold_ms * jitter)
        pre_hold_pause = self.reaction_time()
        post_hold_pause = self.random_pause(0.02, 0.08)
        return KeyHoldIntent(
            hold_ms=hold_ms,
            pre_hold_pause=pre_hold_pause,
            post_hold_pause=post_hold_pause,
        )

    # ------------------------------------------------------------------
    # Break modelling
    # ------------------------------------------------------------------

    # should_take_break() rolls once per DecisionEngine.drive() call, which
    # runs roughly once per published GameState snapshot (~one game tick).
    # break_eta_seconds() uses these to turn that roll into an expected wait.
    BREAK_ROLL_INTERVAL_S: float = 0.6
    BREAK_ROLL_PROB: float = 0.05

    def _break_threshold(self) -> float:
        """Session length (seconds) after which break rolls become possible."""
        return (1800.0 - self.fatigue * 600.0) / self._break_freq_mult

    def should_take_break(self, session_duration_s: float) -> bool:
        """
        Return True if the model decides the player should pause.

        Threshold drops from 30 min to ~20 min as fatigue climbs.
        A small random roll prevents completely predictable behaviour.
        """
        if session_duration_s < self._break_threshold():
            return False
        # 5 % chance per tick once over the threshold
        return self._rng.random() < self.BREAK_ROLL_PROB

    def break_duration(self) -> float:
        """Sample a break length in seconds (20 s – 5 min)."""
        return self._rng.uniform(20.0, 300.0)

    def break_eta_seconds(self, session_duration_s: float) -> float:
        """
        Estimate seconds remaining until the fatigue-driven break triggers.

        should_take_break() is a random process, not a fixed schedule — once
        session_duration_s crosses the fatigue threshold it's only a 5%
        chance per roll — so this is an expected value: time left to reach
        the threshold, plus the mean wait of that roll (1 / BREAK_ROLL_PROB
        rolls, BREAK_ROLL_INTERVAL_S apart) once eligible.
        """
        remaining_to_threshold = max(0.0, self._break_threshold() - session_duration_s)
        expected_roll_wait = self.BREAK_ROLL_INTERVAL_S / self.BREAK_ROLL_PROB
        return remaining_to_threshold + expected_roll_wait

