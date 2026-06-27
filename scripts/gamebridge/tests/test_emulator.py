"""Tests for HumanEmulator mood and interruption multiplier features."""
from __future__ import annotations

import pytest

from scripts.gamebridge.human.emulator import HumanEmulator, KeyHoldIntent
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
# break_eta_seconds
# ------------------------------------------------------------------ #

def test_break_eta_before_threshold_includes_remaining_wait():
	"""Below the 1800s threshold, ETA is time-to-threshold plus the roll wait."""
	human = HumanEmulator(rng_seed=0)
	eta = human.break_eta_seconds(1700.0)
	expected_roll_wait = human.BREAK_ROLL_INTERVAL_S / human.BREAK_ROLL_PROB
	assert eta == pytest.approx(100.0 + expected_roll_wait)


def test_break_eta_past_threshold_is_just_the_roll_wait():
	"""Once past the threshold, only the expected roll wait remains."""
	human = HumanEmulator(rng_seed=0)
	eta = human.break_eta_seconds(2000.0)
	expected_roll_wait = human.BREAK_ROLL_INTERVAL_S / human.BREAK_ROLL_PROB
	assert eta == pytest.approx(expected_roll_wait)


def test_break_eta_shrinks_as_fatigue_lowers_the_threshold():
	"""Higher fatigue lowers the threshold, so the same session length yields
	a smaller (or equal) ETA."""
	fresh = HumanEmulator(rng_seed=0, fatigue=0.0)
	tired = HumanEmulator(rng_seed=0, fatigue=1.0)
	assert tired.break_eta_seconds(900.0) < fresh.break_eta_seconds(900.0)


def test_break_eta_respects_break_freq_mult():
	"""Doubling break_freq_mult halves the threshold, shrinking the ETA."""
	human = HumanEmulator(rng_seed=0)
	baseline = human.break_eta_seconds(900.0)
	human._break_freq_mult = 2.0
	assert human.break_eta_seconds(900.0) < baseline


# ------------------------------------------------------------------ #
# New instance variables have correct defaults
# ------------------------------------------------------------------ #

def test_new_multiplier_defaults_are_one():
	human = HumanEmulator()
	assert human._reaction_mult == pytest.approx(1.0)
	assert human._error_mult == pytest.approx(1.0)
	assert human._fatigue_rate_mult == pytest.approx(1.0)
	assert human._break_freq_mult == pytest.approx(1.0)


# ------------------------------------------------------------------ #
# plan_key_hold
# ------------------------------------------------------------------ #

class TestPlanKeyHold:
	def test_returns_key_hold_intent(self):
		human = HumanEmulator(rng_seed=0)
		result = human.plan_key_hold(500.0)
		assert isinstance(result, KeyHoldIntent)

	def test_hold_ms_within_jitter_bounds(self):
		"""hold_ms must stay within ±30% of intended (jitter clamped to [0.7, 1.3])."""
		human = HumanEmulator(rng_seed=0)
		for _ in range(100):
			result = human.plan_key_hold(500.0)
			assert 350.0 <= result.hold_ms <= 650.0

	def test_hold_ms_floor_at_20ms(self):
		"""Very small intended durations must be floored at 20 ms."""
		human = HumanEmulator(rng_seed=0)
		result = human.plan_key_hold(1.0)
		assert result.hold_ms >= 20.0

	def test_pre_hold_pause_at_least_80ms(self):
		"""pre_hold_pause uses reaction_time() which is floored at 80 ms."""
		human = HumanEmulator(rng_seed=0)
		for _ in range(50):
			result = human.plan_key_hold(500.0)
			assert result.pre_hold_pause >= 0.08

	def test_post_hold_pause_positive(self):
		human = HumanEmulator(rng_seed=0)
		for _ in range(50):
			result = human.plan_key_hold(500.0)
			assert result.post_hold_pause >= 0.02

	def test_fatigue_increases_pre_hold_pause(self):
		"""A fatigued player has a longer mean reaction time before the key hold."""
		fresh = HumanEmulator(rng_seed=7, fatigue=0.0)
		tired = HumanEmulator(rng_seed=7, fatigue=0.9)
		fresh_total = sum(fresh.plan_key_hold(500.0).pre_hold_pause for _ in range(50))
		tired_total = sum(tired.plan_key_hold(500.0).pre_hold_pause for _ in range(50))
		assert tired_total > fresh_total


# ------------------------------------------------------------------ #
# plan_click — move_speed distance scaling
# ------------------------------------------------------------------ #

class TestPlanClickMoveSpeed:
	"""
	move_speed paces WindMouse: near 1.0 it takes its smallest steps and
	longest per-step waits (see wind_mouse). Distance fed into the formula
	must be capped — otherwise a long "homing" move (the cursor starting far
	outside the game viewport, e.g. over a dashboard button) saturates
	move_speed at 1.0 and crawls the whole way, which looks like a freeze
	followed by a snap onto the target. See PLAN.md, "Session: 2026-06-07 (6)".
	"""

	def test_typical_in_game_distance_lands_in_tuned_range(self):
		"""100-400 px clicks should land in the documented 0.1-0.5 range."""
		human = HumanEmulator(rng_seed=0)
		assert 0.1 <= human.plan_click(100, 0, 0, 0).move_speed <= 0.2
		assert 0.4 <= human.plan_click(400, 0, 0, 0).move_speed <= 0.5

	def test_long_homing_distance_does_not_saturate_move_speed(self):
		"""
		A move starting far outside the viewport (e.g. 1500 px away, as when
		the cursor rests over a dashboard button before a routine starts)
		must be paced the same as a typical in-game click, not maxed out.
		"""
		human = HumanEmulator(rng_seed=0)
		near = human.plan_click(400, 0, 0, 0)
		far = human.plan_click(1500, 0, 0, 0)
		assert far.move_speed == pytest.approx(near.move_speed)
		assert far.move_speed < 1.0

	def test_move_speed_capped_distance_matches_400px(self):
		"""Distances beyond the cap are clamped to the same pacing as 400 px."""
		human_a = HumanEmulator(rng_seed=3)
		human_b = HumanEmulator(rng_seed=3)
		at_cap = human_a.plan_click(400, 0, 0, 0)
		beyond_cap = human_b.plan_click(2000, 0, 0, 0)
		assert beyond_cap.move_speed == pytest.approx(at_cap.move_speed)
