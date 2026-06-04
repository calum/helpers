"""
Human interruption model.

Simulates real-world distractions that temporarily alter behaviour:
  • DISCORD_MESSAGE  — distracted for 30–180 s; slower reactions, less precise
  • DOOR_KNOCK       — away from desk for 30–120 s
  • TOILET_BREAK     — pre-phase (rushed), away phase, post-phase (relaxed)
  • WIKI_READING     — reading wiki / watching YouTube for 2–10 min
  • COLD_HANDS       — startup penalty on cold days; primed manually, not scheduled

All probabilities and durations live in DEFAULT_INTERRUPTION_CONFIGS and can be
overridden per-user in ~/.gamebridge/settings.json under
  "human_behaviour" → "interruptions" → "<type_name>" → {field: value}
via build_configs_from_settings().
"""
from __future__ import annotations

import copy
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Interruption types
# ------------------------------------------------------------------ #

class InterruptionType(Enum):
	DISCORD_MESSAGE = "discord_message"
	DOOR_KNOCK      = "door_knock"
	TOILET_BREAK    = "toilet_break"
	WIKI_READING    = "wiki_reading"
	COLD_HANDS      = "cold_hands"


# ------------------------------------------------------------------ #
# Configuration dataclass
# ------------------------------------------------------------------ #

@dataclass
class InterruptionConfig:
	"""
	All tunable parameters for one interruption type.

	Fields have defaults so partial JSON overrides can be applied without
	specifying every field (see build_configs_from_settings).
	"""
	type: InterruptionType
	prob_per_hour: float = 0.0           # expected occurrences per hour; 0 = never auto-triggers
	min_gap_s: float = 0.0               # minimum seconds between same-type triggers
	min_duration_s: float = 0.0          # shortest main-phase duration
	max_duration_s: float = 0.0          # longest main-phase duration
	reaction_multiplier: float = 1.0     # applied during main phase
	click_error_multiplier: float = 1.0  # applied during main phase
	away: bool = False                   # True = routine pauses during main phase
	pre_duration_s: float = 0.0          # pre-phase duration (e.g. rushing before toilet)
	pre_reaction_multiplier: float = 1.0
	post_duration_s: float = 0.0         # post-phase duration (e.g. relaxed after toilet)
	post_reaction_multiplier: float = 1.0
	post_click_error_multiplier: float = 1.0


DEFAULT_INTERRUPTION_CONFIGS: dict[InterruptionType, InterruptionConfig] = {
	InterruptionType.DISCORD_MESSAGE: InterruptionConfig(
		type=InterruptionType.DISCORD_MESSAGE,
		prob_per_hour=1.5,
		min_gap_s=300.0,
		min_duration_s=30.0,
		max_duration_s=180.0,
		reaction_multiplier=1.5,
		click_error_multiplier=1.2,
	),
	InterruptionType.DOOR_KNOCK: InterruptionConfig(
		type=InterruptionType.DOOR_KNOCK,
		prob_per_hour=0.5,
		min_gap_s=1800.0,
		min_duration_s=30.0,
		max_duration_s=120.0,
		away=True,
	),
	InterruptionType.TOILET_BREAK: InterruptionConfig(
		type=InterruptionType.TOILET_BREAK,
		prob_per_hour=1.0,
		min_gap_s=1800.0,
		min_duration_s=60.0,
		max_duration_s=180.0,
		away=True,
		pre_duration_s=15.0,
		pre_reaction_multiplier=0.8,      # rushed — acts quickly before leaving
		post_duration_s=30.0,
		post_reaction_multiplier=1.3,     # relaxed — slower on return
		post_click_error_multiplier=0.9,  # slightly steadier hands
	),
	InterruptionType.WIKI_READING: InterruptionConfig(
		type=InterruptionType.WIKI_READING,
		prob_per_hour=0.8,
		min_gap_s=600.0,
		min_duration_s=120.0,
		max_duration_s=600.0,
		away=True,
	),
	InterruptionType.COLD_HANDS: InterruptionConfig(
		type=InterruptionType.COLD_HANDS,
		prob_per_hour=0.0,          # never auto-triggered; primed manually at startup
		min_gap_s=0.0,
		min_duration_s=0.0,
		max_duration_s=0.0,
		reaction_multiplier=1.3,
		click_error_multiplier=2.5,
		away=False,
	),
}


# ------------------------------------------------------------------ #
# Settings override helper
# ------------------------------------------------------------------ #

def build_configs_from_settings(
	overrides: dict,
) -> dict[InterruptionType, InterruptionConfig]:
	"""
	Merge per-user settings overrides into DEFAULT_INTERRUPTION_CONFIGS.

	overrides format (from settings.json):
	    {"discord_message": {"prob_per_hour": 3.0}, "door_knock": {"min_gap_s": 900}}
	Unknown type names and unknown field names are logged as warnings and skipped.
	"""
	configs = copy.deepcopy(DEFAULT_INTERRUPTION_CONFIGS)
	for key, override_dict in overrides.items():
		try:
			itype = InterruptionType(key)
		except ValueError:
			log.warning("Unknown interruption type in settings: %s", key)
			continue
		cfg = configs[itype]
		for field_name, value in override_dict.items():
			if hasattr(cfg, field_name):
				setattr(cfg, field_name, value)
			else:
				log.warning("Unknown config field '%s' for interruption '%s'", field_name, key)
	return configs


# ------------------------------------------------------------------ #
# Active interruption state
# ------------------------------------------------------------------ #

@dataclass
class ActiveInterruption:
	config: InterruptionConfig
	started_at: float           # monotonic timestamp when current phase started
	phase_ends_at: float        # monotonic timestamp when current phase ends
	phase: str                  # "pre" | "main" | "post"
	session_elapsed_s: float    # session elapsed when the interruption was triggered


# ------------------------------------------------------------------ #
# Scheduler
# ------------------------------------------------------------------ #

class InterruptionScheduler:
	"""
	Decides when interruptions fire and manages their phase lifecycle.

	Call tick() once per game tick. It handles:
	  • Rolling for new interruptions (Poisson process, per-type min-gap enforced)
	  • Phase transitions (pre → main → post → done)
	  • Exposing current multipliers to the engine

	Thread-safety: tick() must be called from a single thread.
	"""

	TICK_DURATION_S: float = 0.6

	def __init__(
		self,
		configs: Optional[dict[InterruptionType, InterruptionConfig]] = None,
		rng: Optional[random.Random] = None,
	):
		self._configs = configs if configs is not None else copy.deepcopy(DEFAULT_INTERRUPTION_CONFIGS)
		self._rng = rng or random.Random()
		self._active: Optional[ActiveInterruption] = None
		self._last_triggered: dict[InterruptionType, float] = {}

	# ------------------------------------------------------------------
	# Main interface
	# ------------------------------------------------------------------

	def tick(self, session_elapsed_s: float) -> Optional[ActiveInterruption]:
		"""
		Advance the scheduler by one game tick.

		Returns the active ActiveInterruption, or None if the player is undisturbed.
		"""
		now = time.monotonic()

		if self._active is not None:
			self._advance_phase(now)

		if self._active is None:
			self._maybe_trigger(now, session_elapsed_s)

		return self._active

	def prime_cold_hands(self, duration_s: float) -> None:
		"""
		Immediately activate the COLD_HANDS interruption for the given duration.

		Called at session startup on cold days (temp < 10°C). Does nothing if
		another interruption is already active.
		"""
		if self._active is not None:
			return
		now = time.monotonic()
		cfg = self._configs.get(InterruptionType.COLD_HANDS)
		if cfg is None:
			return
		self._active = ActiveInterruption(
			config=cfg,
			started_at=now,
			phase_ends_at=now + duration_s,
			phase="main",
			session_elapsed_s=0.0,
		)
		log.info("Cold-hands startup modifier active for %.0fs.", duration_s)

	# ------------------------------------------------------------------
	# State accessors
	# ------------------------------------------------------------------

	@property
	def active(self) -> Optional[ActiveInterruption]:
		return self._active

	@property
	def away(self) -> bool:
		"""True when the routine should pause (away config + main phase)."""
		if self._active is None:
			return False
		return self._active.config.away and self._active.phase == "main"

	def reaction_multiplier(self) -> float:
		"""Current reaction-time multiplier from the active interruption phase."""
		if self._active is None:
			return 1.0
		phase = self._active.phase
		cfg = self._active.config
		if phase == "pre":
			return cfg.pre_reaction_multiplier
		if phase == "main":
			return cfg.reaction_multiplier
		if phase == "post":
			return cfg.post_reaction_multiplier
		return 1.0

	def click_error_multiplier(self) -> float:
		"""Current click-error multiplier from the active interruption phase."""
		if self._active is None:
			return 1.0
		phase = self._active.phase
		cfg = self._active.config
		if phase == "main":
			return cfg.click_error_multiplier
		if phase == "post":
			return cfg.post_click_error_multiplier
		return 1.0

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _advance_phase(self, now: float) -> None:
		if self._active is None:
			return
		if now < self._active.phase_ends_at:
			return

		phase = self._active.phase
		cfg = self._active.config

		if phase == "pre":
			duration = self._rng.uniform(cfg.min_duration_s, cfg.max_duration_s)
			self._active.phase = "main"
			self._active.phase_ends_at = now + duration
			log.info("Interruption %s → main phase (%.0fs).", cfg.type.value, duration)
		elif phase == "main":
			if cfg.post_duration_s > 0:
				self._active.phase = "post"
				self._active.phase_ends_at = now + cfg.post_duration_s
				log.info("Interruption %s → post phase (%.0fs).", cfg.type.value, cfg.post_duration_s)
			else:
				self._clear()
		elif phase == "post":
			self._clear()

	def _clear(self) -> None:
		if self._active is not None:
			log.info("Interruption %s ended.", self._active.config.type.value)
		self._active = None

	def _maybe_trigger(self, now: float, session_elapsed_s: float) -> None:
		tick_prob_scale = self.TICK_DURATION_S / 3600.0

		eligible = [
			cfg for cfg in self._configs.values()
			if cfg.prob_per_hour > 0
			and now - self._last_triggered.get(cfg.type, 0.0) >= cfg.min_gap_s
		]
		self._rng.shuffle(eligible)

		for cfg in eligible:
			prob = cfg.prob_per_hour * tick_prob_scale
			if self._rng.random() < prob:
				self._trigger(cfg, now, session_elapsed_s)
				return

	def _trigger(
		self,
		cfg: InterruptionConfig,
		now: float,
		session_elapsed_s: float,
	) -> None:
		self._last_triggered[cfg.type] = now

		if cfg.pre_duration_s > 0:
			phase = "pre"
			ends_at = now + cfg.pre_duration_s
		else:
			phase = "main"
			duration = self._rng.uniform(cfg.min_duration_s, cfg.max_duration_s)
			ends_at = now + duration

		self._active = ActiveInterruption(
			config=cfg,
			started_at=now,
			phase_ends_at=ends_at,
			phase=phase,
			session_elapsed_s=session_elapsed_s,
		)
		log.info(
			"Interruption triggered: %s (phase=%s, ends in %.0fs).",
			cfg.type.value, phase, ends_at - now,
		)
