"""
Tests for scripts.gamebridge.minimap.world_delta_to_minimap_offset.

Reference values cross-checked against runelite-api's
Perspective.localToMinimap formula (rotation by camera.yawTarget, scale by
camera.minimapZoom pixels-per-tile).
"""
import math

import pytest

from scripts.gamebridge.minimap import world_delta_to_minimap_offset


def test_north_up_compass_offsets_purely_in_y():
    # yawTarget=0 (north up): a due-north target (positive dy) should land
    # directly above centre (negative canvas-Y offset, zero X offset).
    rx, ry = world_delta_to_minimap_offset(0, 20, yaw_target=0, minimap_zoom=4.0)
    assert rx == pytest.approx(0.0)
    assert ry == pytest.approx(-80.0)


def test_north_up_compass_due_east_offsets_purely_in_x():
    rx, ry = world_delta_to_minimap_offset(20, 0, yaw_target=0, minimap_zoom=4.0)
    assert rx == pytest.approx(80.0)
    assert ry == pytest.approx(0.0)


def test_compass_facing_west_rotates_north_target_onto_x_axis():
    # yawTarget=512 (west) — a due-north target should now project onto the
    # X axis instead of the Y axis, since the minimap rotates with the
    # compass. This is the exact scenario the north-up-only formula got wrong.
    rx, ry = world_delta_to_minimap_offset(0, 20, yaw_target=512, minimap_zoom=4.0)
    assert rx == pytest.approx(80.0)
    assert ry == pytest.approx(0.0, abs=1e-9)


def test_compass_facing_south_flips_offset_sign():
    rx, ry = world_delta_to_minimap_offset(0, 20, yaw_target=1024, minimap_zoom=4.0)
    assert rx == pytest.approx(0.0, abs=1e-9)
    assert ry == pytest.approx(80.0)


def test_zoom_scales_offset_linearly():
    rx_lo, ry_lo = world_delta_to_minimap_offset(0, 20, yaw_target=0, minimap_zoom=2.0)
    rx_hi, ry_hi = world_delta_to_minimap_offset(0, 20, yaw_target=0, minimap_zoom=4.0)
    assert rx_hi == pytest.approx(rx_lo * 2)
    assert ry_hi == pytest.approx(ry_lo * 2)


def test_yaw_target_wraps_at_2048():
    rx_a, ry_a = world_delta_to_minimap_offset(0, 20, yaw_target=512, minimap_zoom=4.0)
    rx_b, ry_b = world_delta_to_minimap_offset(0, 20, yaw_target=512 + 2048, minimap_zoom=4.0)
    assert rx_a == pytest.approx(rx_b)
    assert ry_a == pytest.approx(ry_b)


def test_zero_delta_returns_zero_offset():
    rx, ry = world_delta_to_minimap_offset(0, 0, yaw_target=777, minimap_zoom=4.0)
    assert rx == pytest.approx(0.0)
    assert ry == pytest.approx(0.0)
