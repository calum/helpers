"""Tests for the dashboard's pure display-formatting helpers in ui.theme."""
from __future__ import annotations

import pytest

from scripts.gamebridge.ui.theme import (
    _break_label, _fatigue_rate_label, _fatigue_rate_per_min,
)


# ------------------------------------------------------------------ #
# _break_label
# ------------------------------------------------------------------ #

def test_break_label_none_estimate():
    assert _break_label(None) == "Next break: —"


def test_break_label_formats_type_and_duration():
    label = _break_label(("Rest", 125.0))
    assert label == "Next break: ~Rest in 02m 05s"


def test_break_label_title_cases_underscored_type():
    label = _break_label(("discord_message", 30.0))
    assert label == "Next break: ~Discord Message in 00m 30s"


def test_break_label_formats_hours():
    label = _break_label(("Rest", 3725.0))
    assert label == "Next break: ~Rest in 1h 02m 05s"


# ------------------------------------------------------------------ #
# _fatigue_rate_per_min
# ------------------------------------------------------------------ #

def test_fatigue_rate_per_min_none_with_fewer_than_two_samples():
    assert _fatigue_rate_per_min([]) is None
    assert _fatigue_rate_per_min([(0.0, 0.1)]) is None


def test_fatigue_rate_per_min_none_with_no_elapsed_time():
    assert _fatigue_rate_per_min([(10.0, 0.1), (10.0, 0.2)]) is None


def test_fatigue_rate_per_min_computes_percent_per_minute():
    # Fatigue rises 0.10 (10%) over 60s -> 10%/min
    rate = _fatigue_rate_per_min([(0.0, 0.0), (60.0, 0.10)])
    assert rate == pytest.approx(10.0)


def test_fatigue_rate_per_min_negative_when_resting():
    rate = _fatigue_rate_per_min([(0.0, 0.5), (60.0, 0.2)])
    assert rate == pytest.approx(-30.0)


def test_fatigue_rate_per_min_uses_oldest_and_newest_only():
    history = [(0.0, 0.0), (30.0, 999.0), (60.0, 0.10)]
    rate = _fatigue_rate_per_min(history)
    assert rate == pytest.approx(10.0)


# ------------------------------------------------------------------ #
# _fatigue_rate_label
# ------------------------------------------------------------------ #

def test_fatigue_rate_label_none():
    assert _fatigue_rate_label(None) == "Fatigue trend: —"


def test_fatigue_rate_label_steady_near_zero():
    assert _fatigue_rate_label(0.01) == "Fatigue trend: steady"
    assert _fatigue_rate_label(-0.01) == "Fatigue trend: steady"


def test_fatigue_rate_label_positive_has_plus_sign():
    assert _fatigue_rate_label(2.5) == "Fatigue trend: +2.5%/min"


def test_fatigue_rate_label_negative_has_minus_sign():
    assert _fatigue_rate_label(-1.25) == "Fatigue trend: -1.2%/min"
