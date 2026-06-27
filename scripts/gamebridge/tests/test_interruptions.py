"""Tests for human.interruptions — scheduler, phase transitions, config overrides."""
from __future__ import annotations

import random
import time
from unittest.mock import patch

import pytest

from scripts.gamebridge.human.interruptions import (
	DEFAULT_INTERRUPTION_CONFIGS,
	ActiveInterruption,
	InterruptionConfig,
	InterruptionScheduler,
	InterruptionType,
	build_configs_from_settings,
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _always_trigger_rng() -> random.Random:
	"""RNG whose random() always returns 0.0 — guarantees a trigger roll."""
	rng = random.Random()
	rng.random = lambda: 0.0
	rng.shuffle = lambda lst: None  # keep order stable
	return rng


def _never_trigger_rng() -> random.Random:
	"""RNG whose random() always returns 1.0 — never triggers."""
	rng = random.Random()
	rng.random = lambda: 1.0
	rng.shuffle = lambda lst: None
	return rng


def _instant_config(
	itype: InterruptionType = InterruptionType.DISCORD_MESSAGE,
	pre: float = 0.0,
	main_min: float = 0.0,
	main_max: float = 0.0,
	post: float = 0.0,
	away: bool = False,
	min_gap_s: float = 0.0,
) -> dict[InterruptionType, InterruptionConfig]:
	cfg = InterruptionConfig(
		type=itype,
		prob_per_hour=3600.0,   # triggers almost every tick
		min_gap_s=min_gap_s,
		min_duration_s=main_min,
		max_duration_s=main_max,
		away=away,
		pre_duration_s=pre,
		pre_reaction_multiplier=0.8,
		post_duration_s=post,
		post_reaction_multiplier=1.3,
		post_click_error_multiplier=0.9,
		reaction_multiplier=1.5,
		click_error_multiplier=1.2,
	)
	return {itype: cfg}


# ------------------------------------------------------------------ #
# No trigger when prob is zero
# ------------------------------------------------------------------ #

def test_no_trigger_when_prob_zero():
	configs = {
		t: InterruptionConfig(type=t, prob_per_hour=0.0)
		for t in InterruptionType
	}
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	for _ in range(1000):
		result = scheduler.tick(0.0)
	assert result is None


# ------------------------------------------------------------------ #
# Trigger when RNG rolls 0 and prob is high
# ------------------------------------------------------------------ #

def test_triggers_on_first_tick_when_forced():
	scheduler = InterruptionScheduler(
		configs=_instant_config(),
		rng=_always_trigger_rng(),
	)
	result = scheduler.tick(0.0)
	assert result is not None
	assert result.config.type == InterruptionType.DISCORD_MESSAGE


# ------------------------------------------------------------------ #
# Minimum gap prevents double-trigger
# ------------------------------------------------------------------ #

def test_min_gap_prevents_immediate_retrigger():
	cfg = InterruptionConfig(
		type=InterruptionType.DISCORD_MESSAGE,
		prob_per_hour=3600.0,
		min_gap_s=999999.0,   # very long gap
		min_duration_s=0.0,
		max_duration_s=0.0,
	)
	scheduler = InterruptionScheduler(
		configs={InterruptionType.DISCORD_MESSAGE: cfg},
		rng=_always_trigger_rng(),
	)
	# First tick — triggers and immediately clears (0-duration main phase)
	scheduler.tick(0.0)
	# Clear the active so scheduler can re-evaluate
	scheduler._active = None

	# Second immediate tick — min_gap_s not yet elapsed, should not trigger
	result = scheduler.tick(0.0)
	assert result is None


# ------------------------------------------------------------------ #
# Phase transitions: pre → main → post → None
# ------------------------------------------------------------------ #

def test_pre_main_post_phase_transitions():
	"""Use a mock clock so phase durations are deterministic and instant."""
	itype = InterruptionType.TOILET_BREAK
	configs = _instant_config(
		itype=itype,
		pre=10.0,
		main_min=10.0,
		main_max=10.0,
		post=10.0,
		away=True,
		min_gap_s=9999.0,
	)
	rng = random.Random(42)
	rng.random = lambda: 0.0
	rng.shuffle = lambda lst: None
	rng.uniform = lambda a, b: a

	fake_time = [20000.0]   # > min_gap_s=9999 so first trigger is eligible

	with patch("scripts.gamebridge.human.interruptions.time") as mock_time:
		mock_time.monotonic = lambda: fake_time[0]

		scheduler = InterruptionScheduler(configs=configs, rng=rng)

		# t=20000 — trigger; pre phase ends at 20010
		scheduler.tick(0.0)
		assert scheduler.active is not None
		assert scheduler.active.phase == "pre"

		# t=20015 — pre has expired; transitions to main (ends at 20025)
		fake_time[0] = 20015.0
		scheduler.tick(0.0)
		assert scheduler.active is not None
		assert scheduler.active.phase == "main"

		# t=20030 — main has expired; transitions to post (ends at 20040)
		fake_time[0] = 20030.0
		scheduler.tick(0.0)
		assert scheduler.active is not None
		assert scheduler.active.phase == "post"

		# t=20050 — post has expired; interruption clears
		fake_time[0] = 20050.0
		scheduler.tick(0.0)
		assert scheduler.active is None


def test_no_pre_goes_direct_to_main():
	configs = _instant_config(pre=0.0, main_min=0.001, main_max=0.001)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	assert scheduler.active is not None
	assert scheduler.active.phase == "main"


# ------------------------------------------------------------------ #
# away property
# ------------------------------------------------------------------ #

def test_away_true_only_during_main_phase_of_away_config():
	"""Use a mock clock so phase durations are deterministic."""
	configs = _instant_config(
		pre=10.0, main_min=10.0, main_max=10.0, post=10.0, away=True,
		min_gap_s=9999.0,
	)
	rng = random.Random(0)
	rng.random = lambda: 0.0
	rng.shuffle = lambda lst: None
	rng.uniform = lambda a, b: a

	fake_time = [20000.0]   # > min_gap_s=9999 so first trigger is eligible

	with patch("scripts.gamebridge.human.interruptions.time") as mock_time:
		mock_time.monotonic = lambda: fake_time[0]

		scheduler = InterruptionScheduler(configs=configs, rng=rng)
		scheduler.tick(0.0)

		# pre phase — not away
		assert scheduler.active.phase == "pre"
		assert scheduler.away is False

		fake_time[0] = 20015.0
		scheduler.tick(0.0)
		# main phase — away
		assert scheduler.active.phase == "main"
		assert scheduler.away is True

		fake_time[0] = 20030.0
		scheduler.tick(0.0)
		# post phase — not away
		assert scheduler.active.phase == "post"
		assert scheduler.away is False


def test_away_false_for_non_away_config():
	configs = _instant_config(away=False, main_min=0.001, main_max=0.001)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	assert scheduler.active.phase == "main"
	assert scheduler.away is False


# ------------------------------------------------------------------ #
# Multiplier accessors
# ------------------------------------------------------------------ #

def test_reaction_multiplier_pre_phase():
	configs = _instant_config(pre=0.001, main_min=0.001, main_max=0.001)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	assert scheduler.active.phase == "pre"
	assert scheduler.reaction_multiplier() == pytest.approx(0.8)


def test_reaction_multiplier_main_phase():
	configs = _instant_config(main_min=0.001, main_max=0.001)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	assert scheduler.active.phase == "main"
	assert scheduler.reaction_multiplier() == pytest.approx(1.5)


def test_reaction_multiplier_no_active_is_one():
	scheduler = InterruptionScheduler(configs={}, rng=_never_trigger_rng())
	assert scheduler.reaction_multiplier() == pytest.approx(1.0)


def test_click_error_multiplier_main_phase():
	configs = _instant_config(main_min=0.001, main_max=0.001)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	assert scheduler.click_error_multiplier() == pytest.approx(1.2)


def test_click_error_multiplier_no_active_is_one():
	scheduler = InterruptionScheduler(rng=_never_trigger_rng())
	assert scheduler.click_error_multiplier() == pytest.approx(1.0)


# ------------------------------------------------------------------ #
# prime_cold_hands
# ------------------------------------------------------------------ #

def test_prime_cold_hands_activates_immediately():
	scheduler = InterruptionScheduler(rng=_never_trigger_rng())
	scheduler.prime_cold_hands(600.0)
	assert scheduler.active is not None
	assert scheduler.active.config.type == InterruptionType.COLD_HANDS
	assert scheduler.active.phase == "main"


def test_prime_cold_hands_not_away():
	scheduler = InterruptionScheduler(rng=_never_trigger_rng())
	scheduler.prime_cold_hands(600.0)
	assert scheduler.away is False


def test_prime_cold_hands_does_nothing_if_active():
	configs = _instant_config(main_min=9999.0, main_max=9999.0)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)
	active_before = scheduler.active
	scheduler.prime_cold_hands(600.0)
	assert scheduler.active is active_before  # unchanged


def test_prime_cold_hands_expires():
	fake_time = [20000.0]
	with patch("scripts.gamebridge.human.interruptions.time") as mock_time:
		mock_time.monotonic = lambda: fake_time[0]
		scheduler = InterruptionScheduler(rng=_never_trigger_rng())
		scheduler.prime_cold_hands(600.0)   # expires at t=20600
		assert scheduler.active is not None

		fake_time[0] = 21000.0
		scheduler.tick(9999.0)
		assert scheduler.active is None


# ------------------------------------------------------------------ #
# next_interruption_estimate
# ------------------------------------------------------------------ #

def test_next_interruption_estimate_none_when_active():
	configs = _instant_config(main_min=9999.0, main_max=9999.0)
	scheduler = InterruptionScheduler(configs=configs, rng=_always_trigger_rng())
	scheduler.tick(0.0)   # triggers and stays active (long main phase)
	assert scheduler.active is not None
	assert scheduler.next_interruption_estimate() is None


def test_next_interruption_estimate_none_when_no_type_can_trigger():
	configs = {
		t: InterruptionConfig(type=t, prob_per_hour=0.0)
		for t in InterruptionType
	}
	scheduler = InterruptionScheduler(configs=configs, rng=_never_trigger_rng())
	assert scheduler.next_interruption_estimate() is None


def test_next_interruption_estimate_is_mean_wait_when_gap_already_elapsed():
	"""No prior trigger, so the only component is the Poisson mean wait
	(3600 / prob_per_hour)."""
	cfg = InterruptionConfig(type=InterruptionType.DISCORD_MESSAGE, prob_per_hour=3600.0)
	scheduler = InterruptionScheduler(
		configs={InterruptionType.DISCORD_MESSAGE: cfg},
		rng=_never_trigger_rng(),
	)
	itype, eta = scheduler.next_interruption_estimate()
	assert itype == InterruptionType.DISCORD_MESSAGE
	assert eta == pytest.approx(1.0)   # 3600 / 3600


def test_next_interruption_estimate_picks_soonest_type():
	soon = InterruptionConfig(type=InterruptionType.DISCORD_MESSAGE, prob_per_hour=3600.0)
	later = InterruptionConfig(type=InterruptionType.WIKI_READING, prob_per_hour=1.0)
	scheduler = InterruptionScheduler(
		configs={InterruptionType.DISCORD_MESSAGE: soon, InterruptionType.WIKI_READING: later},
		rng=_never_trigger_rng(),
	)
	itype, eta = scheduler.next_interruption_estimate()
	assert itype == InterruptionType.DISCORD_MESSAGE
	assert eta == pytest.approx(1.0)


def test_next_interruption_estimate_includes_remaining_min_gap():
	fake_time = [10000.0]
	with patch("scripts.gamebridge.human.interruptions.time") as mock_time:
		mock_time.monotonic = lambda: fake_time[0]
		cfg = InterruptionConfig(
			type=InterruptionType.DISCORD_MESSAGE, prob_per_hour=3600.0, min_gap_s=500.0,
		)
		scheduler = InterruptionScheduler(
			configs={InterruptionType.DISCORD_MESSAGE: cfg},
			rng=_never_trigger_rng(),
		)
		scheduler._last_triggered[InterruptionType.DISCORD_MESSAGE] = 10000.0
		fake_time[0] = 10100.0   # 400s of the 500s gap still remaining

		itype, eta = scheduler.next_interruption_estimate()
		assert itype == InterruptionType.DISCORD_MESSAGE
		assert eta == pytest.approx(400.0 + 1.0)


# ------------------------------------------------------------------ #
# build_configs_from_settings
# ------------------------------------------------------------------ #

def test_build_configs_override_prob():
	configs = build_configs_from_settings({"discord_message": {"prob_per_hour": 3.0}})
	assert configs[InterruptionType.DISCORD_MESSAGE].prob_per_hour == pytest.approx(3.0)


def test_build_configs_other_defaults_preserved():
	configs = build_configs_from_settings({"discord_message": {"prob_per_hour": 3.0}})
	assert configs[InterruptionType.TOILET_BREAK].prob_per_hour == pytest.approx(
		DEFAULT_INTERRUPTION_CONFIGS[InterruptionType.TOILET_BREAK].prob_per_hour
	)


def test_build_configs_unknown_type_no_exception():
	configs = build_configs_from_settings({"nonexistent_type": {"prob_per_hour": 5.0}})
	assert len(configs) == len(DEFAULT_INTERRUPTION_CONFIGS)


def test_build_configs_unknown_field_no_exception():
	configs = build_configs_from_settings({"discord_message": {"not_a_real_field": 42}})
	assert configs[InterruptionType.DISCORD_MESSAGE].prob_per_hour == pytest.approx(
		DEFAULT_INTERRUPTION_CONFIGS[InterruptionType.DISCORD_MESSAGE].prob_per_hour
	)


def test_build_configs_does_not_mutate_defaults():
	build_configs_from_settings({"discord_message": {"prob_per_hour": 999.0}})
	assert DEFAULT_INTERRUPTION_CONFIGS[InterruptionType.DISCORD_MESSAGE].prob_per_hour != 999.0
