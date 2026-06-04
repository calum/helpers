"""
Session mood model.

Derives a MoodProfile for the session from today's local weather via wttr.in.
Falls back to a deterministic hash of today's date if the API is unavailable.

The MoodProfile carries multipliers that are applied to HumanEmulator parameters
once at session startup via HumanEmulator.apply_mood().
"""
from __future__ import annotations

import copy
import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Mood types and profiles
# ------------------------------------------------------------------ #

class MoodType(Enum):
	EXCITED    = "excited"
	HAPPY      = "happy"
	NEUTRAL    = "neutral"
	BORED      = "bored"
	SAD        = "sad"
	DISTRACTED = "distracted"


@dataclass
class MoodProfile:
	"""Multipliers applied to HumanEmulator base parameters at session start."""
	mood: MoodType
	reaction_multiplier: float        # scales reaction_mean (<1 = faster, >1 = slower)
	click_error_multiplier: float     # scales click_error_px
	fatigue_rate_multiplier: float    # scales accumulate_fatigue delta
	break_frequency_multiplier: float # scales break threshold (>1 = breaks come sooner)
	cold_hands: bool = False
	cold_hands_duration_s: float = 0.0


MOOD_PROFILES: dict[MoodType, MoodProfile] = {
	MoodType.EXCITED: MoodProfile(
		mood=MoodType.EXCITED,
		reaction_multiplier=0.85,
		click_error_multiplier=0.90,
		fatigue_rate_multiplier=1.10,
		break_frequency_multiplier=0.80,
	),
	MoodType.HAPPY: MoodProfile(
		mood=MoodType.HAPPY,
		reaction_multiplier=0.95,
		click_error_multiplier=0.95,
		fatigue_rate_multiplier=1.00,
		break_frequency_multiplier=0.90,
	),
	MoodType.NEUTRAL: MoodProfile(
		mood=MoodType.NEUTRAL,
		reaction_multiplier=1.00,
		click_error_multiplier=1.00,
		fatigue_rate_multiplier=1.00,
		break_frequency_multiplier=1.00,
	),
	MoodType.BORED: MoodProfile(
		mood=MoodType.BORED,
		reaction_multiplier=1.15,
		click_error_multiplier=1.10,
		fatigue_rate_multiplier=1.20,
		break_frequency_multiplier=1.30,
	),
	MoodType.SAD: MoodProfile(
		mood=MoodType.SAD,
		reaction_multiplier=1.25,
		click_error_multiplier=1.15,
		fatigue_rate_multiplier=1.30,
		break_frequency_multiplier=1.50,
	),
	MoodType.DISTRACTED: MoodProfile(
		mood=MoodType.DISTRACTED,
		reaction_multiplier=1.40,
		click_error_multiplier=1.30,
		fatigue_rate_multiplier=1.00,
		break_frequency_multiplier=1.60,
	),
}


# ------------------------------------------------------------------ #
# Weather code → mood mapping (wttr.in / WMO condition codes)
# ------------------------------------------------------------------ #

_WEATHER_CODE_MOOD: dict[int, MoodType] = {
	# Clear / sunny
	113: MoodType.EXCITED,
	# Partly cloudy
	116: MoodType.HAPPY,
	# Cloudy
	119: MoodType.NEUTRAL,
	# Overcast
	122: MoodType.BORED,
	# Mist
	143: MoodType.BORED,
	# Thunder / lightning
	200: MoodType.DISTRACTED,
	386: MoodType.DISTRACTED,
	389: MoodType.DISTRACTED,
	392: MoodType.DISTRACTED,
	395: MoodType.DISTRACTED,
	# Blowing snow / blizzard
	227: MoodType.SAD,
	230: MoodType.BORED,
	# Fog
	248: MoodType.BORED,
	260: MoodType.BORED,
	# Drizzle
	263: MoodType.SAD,
	266: MoodType.SAD,
	281: MoodType.BORED,
	284: MoodType.SAD,
	# Patchy rain / snow / sleet
	176: MoodType.SAD,
	179: MoodType.SAD,
	182: MoodType.BORED,
	185: MoodType.BORED,
	# Rain
	293: MoodType.SAD,
	296: MoodType.SAD,
	299: MoodType.BORED,
	302: MoodType.BORED,
	305: MoodType.SAD,
	308: MoodType.SAD,
	# Freezing rain / sleet
	311: MoodType.BORED,
	314: MoodType.SAD,
	317: MoodType.BORED,
	320: MoodType.BORED,
	# Snow
	323: MoodType.BORED,
	326: MoodType.BORED,
	329: MoodType.SAD,
	332: MoodType.SAD,
	335: MoodType.SAD,
	338: MoodType.SAD,
	# Ice pellets
	350: MoodType.BORED,
	374: MoodType.BORED,
	377: MoodType.SAD,
	# Rain showers
	353: MoodType.SAD,
	356: MoodType.BORED,
	359: MoodType.SAD,
	# Sleet / snow showers
	362: MoodType.BORED,
	365: MoodType.BORED,
	368: MoodType.BORED,
	371: MoodType.SAD,
}


def _mood_from_weather_code(code: int) -> MoodType:
	return _WEATHER_CODE_MOOD.get(code, MoodType.NEUTRAL)


def _mood_from_date_hash(seed: str) -> MoodType:
	h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
	moods = sorted(MoodType, key=lambda m: m.value)
	return moods[h % len(moods)]


# ------------------------------------------------------------------ #
# WeatherMoodSeeder
# ------------------------------------------------------------------ #

class WeatherMoodSeeder:
	"""
	Derives a session MoodProfile from today's local weather.

	Primary source: wttr.in JSON API (no key required, stdlib-only fetch).
	Fallback: deterministic SHA-256 hash of today's ISO date string.
	Cold-day detection: if temp_C < COLD_THRESHOLD_C, activates cold-hands
	modifier lasting 10–20 minutes.
	"""

	COLD_THRESHOLD_C: float = 10.0

	def seed(
		self,
		location: str = "auto",
		rng: Optional[random.Random] = None,
	) -> MoodProfile:
		"""Return a MoodProfile for this session."""
		_rng = rng or random.Random()

		weather_data = self._fetch_weather(location)

		if weather_data is not None:
			code = weather_data["condition_code"]
			temp_c = weather_data["temp_c"]
			mood_type = _mood_from_weather_code(code)
			log.info(
				"Weather: code=%d, temp=%.1f°C → mood=%s",
				code, temp_c, mood_type.value,
			)
		else:
			temp_c = 20.0
			mood_type = _mood_from_date_hash(date.today().isoformat())
			log.info("Weather API unavailable; date-hash fallback → mood=%s", mood_type.value)

		profile = copy.copy(MOOD_PROFILES[mood_type])

		if temp_c < self.COLD_THRESHOLD_C:
			profile.cold_hands = True
			profile.cold_hands_duration_s = _rng.uniform(600.0, 1200.0)
			log.info(
				"Cold day (%.1f°C): cold-hands modifier active for %.0fs",
				temp_c, profile.cold_hands_duration_s,
			)

		return profile

	def _fetch_weather(self, location: str) -> Optional[dict]:
		"""Fetch condition code and temperature from wttr.in. Returns None on any failure."""
		try:
			import json as _json
			import urllib.request

			url = f"https://wttr.in/{location}?format=j1"
			with urllib.request.urlopen(url, timeout=5) as resp:
				data = _json.loads(resp.read().decode())
			condition_code = int(data["current_condition"][0]["weatherCode"])
			temp_c = float(data["current_condition"][0]["temp_C"])
			return {"condition_code": condition_code, "temp_c": temp_c}
		except Exception as exc:
			log.warning("Weather fetch failed: %s", exc)
			return None
