"""
AntiBanStats — rolling telemetry for click timing, mouse-button hold
duration, cursor speed, and click accuracy.

Purely an in-memory recorder: GameController appends a ClickSample after
every click it actually issues (see GameController._record_click_stats);
the dashboard's Anti-Ban tab polls samples()/summary() to draw graphs. No
persistence, no I/O — this never influences routine behaviour, it only
observes it.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional


@dataclass(frozen=True)
class ClickSample:
    """One recorded click — see AntiBanStats.record_click."""
    t: float                        # time.monotonic() timestamp the click fired
    error_px: float                 # distance between the aimed point and where the click landed
    move_speed_px_s: float          # average cursor speed during the approach (px/s)
    down_up_ms: float               # mouse-down to mouse-up duration, in ms
    inter_click_s: Optional[float]  # seconds since the previous recorded click (None for the first)
    double_click: bool


class AntiBanStats:
    """Bounded rolling window of click telemetry, for the dashboard's Anti-Ban tab."""

    def __init__(self, maxlen: int = 300):
        self._samples: Deque[ClickSample] = deque(maxlen=maxlen)
        self._last_click_t: Optional[float] = None

    def record_click(
        self,
        *,
        error_px: float,
        move_speed_px_s: float,
        down_up_ms: float,
        double_click: bool = False,
    ) -> ClickSample:
        """Append one click's telemetry. Returns the recorded sample."""
        now = time.monotonic()
        inter_click_s = None if self._last_click_t is None else now - self._last_click_t
        sample = ClickSample(
            t=now,
            error_px=error_px,
            move_speed_px_s=move_speed_px_s,
            down_up_ms=down_up_ms,
            inter_click_s=inter_click_s,
            double_click=double_click,
        )
        self._samples.append(sample)
        self._last_click_t = now
        return sample

    def samples(self) -> List[ClickSample]:
        """Snapshot of all currently-retained samples, oldest first."""
        return list(self._samples)

    def clear(self) -> None:
        """Drop all recorded samples and reset inter-click tracking."""
        self._samples.clear()
        self._last_click_t = None

    def summary(self) -> dict:
        """
        Mean/stdev for each metric plus sample count and double-click rate.

        Returns count=0 and None for every other field if nothing has been
        recorded yet — callers should treat that as "no data" rather than
        try to render zeros.
        """
        samples = self._samples
        n = len(samples)
        if n == 0:
            return {
                "count": 0,
                "error_px_mean": None, "error_px_std": None,
                "move_speed_mean": None,
                "down_up_ms_mean": None, "down_up_ms_std": None,
                "inter_click_mean": None,
                "double_click_rate": None,
            }

        errors = [s.error_px for s in samples]
        speeds = [s.move_speed_px_s for s in samples]
        holds = [s.down_up_ms for s in samples]
        intervals = [s.inter_click_s for s in samples if s.inter_click_s is not None]

        return {
            "count": n,
            "error_px_mean": _mean(errors), "error_px_std": _std(errors),
            "move_speed_mean": _mean(speeds),
            "down_up_ms_mean": _mean(holds), "down_up_ms_std": _std(holds),
            "inter_click_mean": _mean(intervals) if intervals else None,
            "double_click_rate": sum(1 for s in samples if s.double_click) / n,
        }


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))
