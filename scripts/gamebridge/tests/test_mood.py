"""Tests for human.mood — WeatherMoodSeeder, profile mapping, hash fallback."""
from __future__ import annotations

import random
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from scripts.gamebridge.human.mood import (
	MOOD_PROFILES,
	MoodProfile,
	MoodType,
	WeatherMoodSeeder,
	_mood_from_date_hash,
	_mood_from_weather_code,
)


# ------------------------------------------------------------------ #
# Weather code mapping
# ------------------------------------------------------------------ #

def test_weather_code_clear_maps_to_excited():
	assert _mood_from_weather_code(113) == MoodType.EXCITED


def test_weather_code_partly_cloudy_maps_to_happy():
	assert _mood_from_weather_code(116) == MoodType.HAPPY


def test_weather_code_rain_maps_to_sad():
	assert _mood_from_weather_code(293) == MoodType.SAD


def test_weather_code_thunder_maps_to_distracted():
	assert _mood_from_weather_code(200) == MoodType.DISTRACTED


def test_weather_code_unknown_maps_to_neutral():
	assert _mood_from_weather_code(9999) == MoodType.NEUTRAL


def test_weather_code_zero_maps_to_neutral():
	assert _mood_from_weather_code(0) == MoodType.NEUTRAL


# ------------------------------------------------------------------ #
# Date-hash fallback
# ------------------------------------------------------------------ #

def test_date_hash_is_stable_for_same_seed():
	result_a = _mood_from_date_hash("2026-01-01")
	result_b = _mood_from_date_hash("2026-01-01")
	assert result_a == result_b


def test_date_hash_returns_valid_mood_type():
	for day in ("2026-01-01", "2026-06-15", "2025-12-31"):
		result = _mood_from_date_hash(day)
		assert isinstance(result, MoodType)
		assert result in list(MoodType)


def test_date_hash_varies_across_dates():
	results = {_mood_from_date_hash(f"2026-01-{d:02d}") for d in range(1, 29)}
	assert len(results) > 1, "Expected different moods across different dates"


# ------------------------------------------------------------------ #
# WeatherMoodSeeder.seed — weather available
# ------------------------------------------------------------------ #

def test_seed_uses_weather_when_available():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value={"condition_code": 113, "temp_c": 20.0}):
		profile = seeder.seed()
	assert profile.mood == MoodType.EXCITED
	assert profile.cold_hands is False


def test_seed_falls_back_on_api_failure():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value=None):
		profile = seeder.seed()
	assert isinstance(profile.mood, MoodType)
	assert profile.cold_hands is False


def test_seed_no_exception_on_api_failure():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value=None):
		profile = seeder.seed()  # must not raise


# ------------------------------------------------------------------ #
# Cold-hands detection
# ------------------------------------------------------------------ #

def test_cold_day_sets_cold_hands():
	seeder = WeatherMoodSeeder()
	rng = random.Random(42)
	with patch.object(seeder, "_fetch_weather", return_value={"condition_code": 113, "temp_c": 5.0}):
		profile = seeder.seed(rng=rng)
	assert profile.cold_hands is True
	assert 600.0 <= profile.cold_hands_duration_s <= 1200.0


def test_warm_day_no_cold_hands():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value={"condition_code": 113, "temp_c": 20.0}):
		profile = seeder.seed()
	assert profile.cold_hands is False
	assert profile.cold_hands_duration_s == 0.0


def test_exactly_at_threshold_no_cold_hands():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value={"condition_code": 113, "temp_c": WeatherMoodSeeder.COLD_THRESHOLD_C}):
		profile = seeder.seed()
	assert profile.cold_hands is False


# ------------------------------------------------------------------ #
# Profile integrity
# ------------------------------------------------------------------ #

def test_all_mood_types_have_profiles():
	for mood in MoodType:
		assert mood in MOOD_PROFILES, f"Missing profile for {mood}"


def test_seed_returns_copy_not_original():
	seeder = WeatherMoodSeeder()
	with patch.object(seeder, "_fetch_weather", return_value={"condition_code": 113, "temp_c": 20.0}):
		profile = seeder.seed()
	profile.reaction_multiplier = 999.0
	assert MOOD_PROFILES[MoodType.EXCITED].reaction_multiplier != 999.0
