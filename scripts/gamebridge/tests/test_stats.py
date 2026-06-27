"""
Tests for AntiBanStats — the rolling click-telemetry recorder behind the
dashboard's Anti-Ban tab.

Run with:
    python -m pytest scripts/gamebridge/tests/test_stats.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.gamebridge.human.stats import AntiBanStats, ClickSample


def _record(stats: AntiBanStats, **kwargs):
    defaults = dict(error_px=1.0, move_speed_px_s=100.0, down_up_ms=60.0, double_click=False)
    defaults.update(kwargs)
    return stats.record_click(**defaults)


class TestRecordClick:
    def test_first_sample_has_no_inter_click_interval(self):
        stats = AntiBanStats()
        sample = _record(stats)
        assert sample.inter_click_s is None

    def test_second_sample_computes_inter_click_interval(self):
        stats = AntiBanStats()
        with patch("scripts.gamebridge.human.stats.time.monotonic", side_effect=[100.0, 100.4]):
            _record(stats)
            second = _record(stats)
        assert second.inter_click_s == pytest.approx(0.4)

    def test_returns_the_recorded_sample(self):
        stats = AntiBanStats()
        sample = _record(stats, error_px=3.5, move_speed_px_s=250.0, down_up_ms=70.0, double_click=True)
        assert sample == ClickSample(
            t=sample.t, error_px=3.5, move_speed_px_s=250.0,
            down_up_ms=70.0, inter_click_s=None, double_click=True,
        )

    def test_fields_are_stored_verbatim(self):
        stats = AntiBanStats()
        _record(stats, error_px=2.0, move_speed_px_s=300.0, down_up_ms=55.0, double_click=True)
        sample = stats.samples()[0]
        assert sample.error_px == 2.0
        assert sample.move_speed_px_s == 300.0
        assert sample.down_up_ms == 55.0
        assert sample.double_click is True


class TestSamplesAndMaxlen:
    def test_samples_returns_oldest_first(self):
        stats = AntiBanStats()
        _record(stats, error_px=1.0)
        _record(stats, error_px=2.0)
        _record(stats, error_px=3.0)
        assert [s.error_px for s in stats.samples()] == [1.0, 2.0, 3.0]

    def test_maxlen_evicts_oldest(self):
        stats = AntiBanStats(maxlen=2)
        _record(stats, error_px=1.0)
        _record(stats, error_px=2.0)
        _record(stats, error_px=3.0)
        assert [s.error_px for s in stats.samples()] == [2.0, 3.0]

    def test_samples_returns_independent_list(self):
        """Mutating the returned list must not affect internal state."""
        stats = AntiBanStats()
        _record(stats)
        snapshot = stats.samples()
        snapshot.clear()
        assert len(stats.samples()) == 1


class TestClear:
    def test_clear_removes_all_samples(self):
        stats = AntiBanStats()
        _record(stats)
        stats.clear()
        assert stats.samples() == []

    def test_clear_resets_inter_click_tracking(self):
        stats = AntiBanStats()
        _record(stats)
        stats.clear()
        sample = _record(stats)
        assert sample.inter_click_s is None


class TestSummary:
    def test_empty_summary_has_zero_count_and_none_fields(self):
        stats = AntiBanStats()
        summary = stats.summary()
        assert summary["count"] == 0
        assert summary["error_px_mean"] is None
        assert summary["error_px_std"] is None
        assert summary["move_speed_mean"] is None
        assert summary["down_up_ms_mean"] is None
        assert summary["down_up_ms_std"] is None
        assert summary["inter_click_mean"] is None
        assert summary["double_click_rate"] is None

    def test_count_matches_number_of_samples(self):
        stats = AntiBanStats()
        _record(stats)
        _record(stats)
        assert stats.summary()["count"] == 2

    def test_error_px_mean_and_std(self):
        stats = AntiBanStats()
        _record(stats, error_px=2.0)
        _record(stats, error_px=4.0)
        summary = stats.summary()
        assert summary["error_px_mean"] == pytest.approx(3.0)
        assert summary["error_px_std"] == pytest.approx(1.0)

    def test_single_sample_std_is_zero(self):
        stats = AntiBanStats()
        _record(stats, error_px=5.0)
        assert stats.summary()["error_px_std"] == 0.0

    def test_move_speed_mean(self):
        stats = AntiBanStats()
        _record(stats, move_speed_px_s=100.0)
        _record(stats, move_speed_px_s=300.0)
        assert stats.summary()["move_speed_mean"] == pytest.approx(200.0)

    def test_down_up_ms_mean_and_std(self):
        stats = AntiBanStats()
        _record(stats, down_up_ms=40.0)
        _record(stats, down_up_ms=60.0)
        summary = stats.summary()
        assert summary["down_up_ms_mean"] == pytest.approx(50.0)
        assert summary["down_up_ms_std"] == pytest.approx(10.0)

    def test_inter_click_mean_excludes_first_none_sample(self):
        stats = AntiBanStats()
        with patch("scripts.gamebridge.human.stats.time.monotonic", side_effect=[100.0, 100.5, 101.5]):
            _record(stats)
            _record(stats)
            _record(stats)
        # intervals: None, 0.5, 1.0 -> mean of [0.5, 1.0]
        assert stats.summary()["inter_click_mean"] == pytest.approx(0.75)

    def test_inter_click_mean_is_none_with_only_one_sample(self):
        stats = AntiBanStats()
        _record(stats)
        assert stats.summary()["inter_click_mean"] is None

    def test_double_click_rate(self):
        stats = AntiBanStats()
        _record(stats, double_click=True)
        _record(stats, double_click=False)
        _record(stats, double_click=False)
        _record(stats, double_click=False)
        assert stats.summary()["double_click_rate"] == pytest.approx(0.25)

    def test_double_click_rate_zero_when_none_are_double_clicks(self):
        stats = AntiBanStats()
        _record(stats, double_click=False)
        assert stats.summary()["double_click_rate"] == 0.0

    def test_summary_reflects_maxlen_eviction(self):
        stats = AntiBanStats(maxlen=2)
        _record(stats, error_px=1.0)
        _record(stats, error_px=2.0)
        _record(stats, error_px=100.0)
        # the error_px=1.0 sample should have been evicted
        assert stats.summary()["error_px_mean"] == pytest.approx(51.0)
