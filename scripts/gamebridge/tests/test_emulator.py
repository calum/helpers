"""Tests for HumanEmulator mood and interruption multiplier features."""
from __future__ import annotations

import pytest

from scripts.gamebridge.human.emulator import HumanEmulator
from scripts.gamebridge.human.mood import MOOD_PROFILES, MoodType


# ------------------------------------------------------------------ #
# apply_mood — scales base parameters
# ------------------------------------------------------------------ #

def test_apply_mood_scales_reaction_mean():
	human = HumanEmulator(reaction_mean=0.25, rng_seed=0)
	human.apply_mood(MOOD_PROFILES[MoodType.EXCITED])   # multiplier = 0.85
	assert human.reaction_mean == pytest.approx(0.25 * 0.85)


def test_apply_mood_scales_click_error():
	human = HumanEmulator(click_error_px=4.0, rng_seed=0)
	human.apply_mood(MOOD_PROFILES[MoodType.SAD])   # multiplier = 1.15
	assert human.click_error_px == pytest.approx(4.0 * 1.15)


def test_apply_mood_neutral_leaves_params_unchanged():
	human = HumanEmulator(reaction_mean=0.25, click_error_px=4.0, rng_seed=0)
	human.apply_mood(MOOD_PROFILES[MoodType.NEUTRAL])
	assert human.reaction_mean == pytest.approx(0.25)
	assert human.click_error_px == pytest.approx(4.0)


def test_apply_mood_sets_fatigue_rate_mult():
	human = HumanEmulator(rng_seed=0)
	human.apply_mood(MOOD_PROFILES[MoodType.BORED])   # fatigue_rate = 1.20
	assert human._fatigue_rate_mult == pytest.approx(1.20)


def test_apply_mood_sets_break_freq_mult():
	human = HumanEmulator(rng_seed=0)
	human.apply_mood(MOOD_PROFILES[MoodType.SAD])   # break_frequency = 1.50
	assert human._break_freq_mult == pytest.approx(1.50)


# ------------------------------------------------------------------ #
# set_interruption_multipliers — temporary override
# ------------------------------------------------------------------ #

def test_set_interruption_multipliers_increases_reaction_time():
	human_base = HumanEmulator(reaction_mean=0.25, rng_seed=42)
	human_mult = HumanEmulator(reaction_mean=0.25, rng_seed=42)
	human_mult.set_interruption_multipliers(reaction=2.0)

	samples_base = [human_base.reaction_time() for _ in range(50)]
	samples_mult = [human_mult.reaction_time() for _ in range(50)]

	assert sum(samples_mult) > sum(samples_base)


def test_set_interruption_multipliers_below_one_decreases_reaction_time():
	human_base = HumanEmulator(reaction_mean=0.25, rng_seed=42)
	human_fast = HumanEmulator(reaction_mean=0.25, rng_seed=42)
	human_fast.set_interruption_multipliers(reaction=0.5)

	samples_base = [human_base.reaction_time() for _ in range(50)]
	samples_fast = [human_fast.reaction_time() for _ in range(50)]

	assert sum(samples_fast) < sum(samples_base)


def test_set_interruption_multipliers_increases_click_error():
	human_base = HumanEmulator(click_error_px=4.0, rng_seed=99)
	human_mult = HumanEmulator(click_error_px=4.0, rng_seed=99)
	human_mult.set_interruption_multipliers(click_error=3.0)

	errors_base = [
		abs(human_base.plan_click(100, 100).actual_x - 100)
		for _ in range(100)
	]
	errors_mult = [
		abs(human_mult.plan_click(100, 100).actual_x - 100)
		for _ in range(100)
	]

	assert sum(errors_mult) > sum(errors_base)


def test_clear_interruption_multipliers_restores_default():
	human = HumanEmulator(reaction_mean=0.25, rng_seed=0)
	human.set_interruption_multipliers(reaction=5.0, click_error=5.0)
	human.set_interruption_multipliers()   # clear to 1.0
	assert human._reaction_mult == pytest.approx(1.0)
	assert human._error_mult == pytest.approx(1.0)


# ------------------------------------------------------------------ #
# fatigue_rate_mult applied in accumulate_fatigue
# ------------------------------------------------------------------ #

def test_fatigue_rate_mult_doubles_accumulation():
	human = HumanEmulator(rng_seed=0)
	human._fatigue_rate_mult = 2.0
	for _ in range(5):
		human.accumulate_fatigue(0.0001)
	assert human.fatigue == pytest.approx(0.001, abs=1e-9)


def test_fatigue_rate_mult_one_is_default_behaviour():
	human = HumanEmulator(rng_seed=0)
	for _ in range(5):
		human.accumulate_fatigue(0.0001)
	assert human.fatigue == pytest.approx(0.0005, abs=1e-9)


# ------------------------------------------------------------------ #
# break_freq_mult applied in should_take_break
# ------------------------------------------------------------------ #

def test_break_freq_mult_two_halves_threshold():
	"""With break_freq_mult=2, breaks trigger at half the normal session length."""
	human = HumanEmulator(rng_seed=0)
	human._break_freq_mult = 2.0

	# Normally needs 1800s, with x2 multiplier threshold is 900s
	# 5% chance per tick after threshold — use a long session to ensure it fires
	triggered = any(human.should_take_break(950.0) for _ in range(200))
	assert triggered


def test_break_freq_mult_one_normal_threshold():
	"""With default multiplier, 900s should not trigger breaks (threshold is 1800s)."""
	human = HumanEmulator(rng_seed=42)
	triggered = any(human.should_take_break(900.0) for _ in range(100))
	assert not triggered


# ------------------------------------------------------------------ #
# New instance variables have correct defaults
# ------------------------------------------------------------------ #

def test_new_multiplier_defaults_are_one():
	human = HumanEmulator()
	assert human._reaction_mult == pytest.approx(1.0)
	assert human._error_mult == pytest.approx(1.0)
	assert human._fatigue_rate_mult == pytest.approx(1.0)
	assert human._break_freq_mult == pytest.approx(1.0)
