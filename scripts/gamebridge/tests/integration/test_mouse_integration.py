from __future__ import annotations

import os
import sys
import time

import pytest

from scripts.gamebridge.input import mouse as mouse_input
from scripts.gamebridge.tests.integration.harness_client import HarnessProcess

pytestmark = pytest.mark.skipif(
    os.environ.get("GAMEBRIDGE_INTEGRATION") != "1" or sys.platform != "win32",
    reason="Windows-only integration test gated by GAMEBRIDGE_INTEGRATION=1",
)


def _approx(value: float, expected: float, tolerance: float = 4.0) -> bool:
    return abs(value - expected) <= tolerance


def test_left_click_at_canvas_center_reports_canvas_coordinates() -> None:
    with HarnessProcess() as harness:
        x, y = harness.canvas_screen_pos
        harness.click_canvas_left(x, y)
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "mouse" and ev["phase"] == "down" and ev["button"] == 1,
            timeout=2.0,
        )
        expected_x = (harness.canvas_box["right"] - harness.canvas_box["left"]) / 2
        expected_y = (harness.canvas_box["bottom"] - harness.canvas_box["top"]) / 2
        assert _approx(event["canvasX"], expected_x)
        assert _approx(event["canvasY"], expected_y)


def test_right_click_at_canvas_center_reports_button_three() -> None:
    with HarnessProcess() as harness:
        x, y = harness.canvas_screen_pos
        harness.click_canvas_right(x, y)
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "mouse" and ev["phase"] == "down" and ev["button"] == 3,
            timeout=2.0,
        )
        expected_x = (harness.canvas_box["right"] - harness.canvas_box["left"]) / 2
        expected_y = (harness.canvas_box["bottom"] - harness.canvas_box["top"]) / 2
        assert _approx(event["canvasX"], expected_x)
        assert _approx(event["canvasY"], expected_y)


def test_drag_reports_start_and_end_coordinates() -> None:
    with HarnessProcess() as harness:
        start_x = harness.canvas_box["left"] + 40
        start_y = harness.canvas_box["top"] + 40
        end_x = harness.canvas_box["left"] + 140
        end_y = harness.canvas_box["top"] + 120
        harness.drag_canvas(start_x, start_y, end_x, end_y)

        down_event = harness.wait_for_event(
            lambda ev: ev["type"] == "mouse" and ev["phase"] == "down" and ev["button"] == 1,
            timeout=2.0,
        )
        up_event = harness.wait_for_event(
            lambda ev: ev["type"] == "mouse" and ev["phase"] == "up" and ev["button"] == 1,
            timeout=2.0,
        )
        assert _approx(down_event["canvasX"], 40.0)
        assert _approx(down_event["canvasY"], 40.0)
        assert _approx(up_event["canvasX"], 140.0)
        assert _approx(up_event["canvasY"], 120.0)


def test_click_at_canvas_corner_reports_boundary_coordinates() -> None:
    with HarnessProcess() as harness:
        corner_x = harness.canvas_box["left"] + 2
        corner_y = harness.canvas_box["top"] + 2
        harness.click_canvas_left(corner_x, corner_y)
        event = harness.wait_for_event(
            lambda ev: ev["type"] == "mouse" and ev["phase"] == "down" and ev["button"] == 1,
            timeout=2.0,
        )
        assert _approx(event["canvasX"], 2.0, tolerance=8.0)
        assert _approx(event["canvasY"], 2.0, tolerance=8.0)
