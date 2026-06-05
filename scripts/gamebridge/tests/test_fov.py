"""
Tests for the FOV helpers in scripts.gamebridge.fov.

Calibration reference (CAMERA_FOV.md §9):
  pitch=229: back 3 tiles, front 6 tiles, half-width 4 / 6
  pitch=320: back 3 tiles, front 3 tiles, half-width 5 / 7

Yaw convention (OSRS CCW): North=0, West=512, South=1024, East=1536.
All tile coords relative to player at (3200, 3200).
"""
import math
import pytest
from scripts.gamebridge.state.game_state import GameState
from scripts.gamebridge.fov import (
    _fov_params,
    angular_offset,
    entity_in_fov,
    fov_polygon_world,
    decide_camera_action,
    _CAL_PITCH_LOW,
    _CAL_PITCH_HIGH,
    _CAL_BACK_FWD,
    _CAL_FRONT_LOW,
    _CAL_FRONT_HIGH,
    _CAL_BACK_W_LOW,
    _CAL_BACK_W_HIGH,
    _CAL_FRONT_W_LOW,
    _CAL_FRONT_W_HIGH,
)

PLAYER_X, PLAYER_Y = 3200, 3200


def _player(x=PLAYER_X, y=PLAYER_Y):
    return {"name": "Test", "worldX": x, "worldY": y, "plane": 0,
            "animation": -1, "hp": 99, "prayer": 50}


def _base_msg(tick=1, **kwargs):
    msg = {"tick": tick, "events": []}
    msg.update(kwargs)
    return msg


def _game(player_x=PLAYER_X, player_y=PLAYER_Y, yaw=0, pitch=300):
    g = GameState()
    g.update(_base_msg(
        player=_player(player_x, player_y),
        camera={"yaw": yaw, "pitch": pitch, "x": 0, "y": 0, "z": 0},
    ))
    return g


# ---------------------------------------------------------------------------
# _fov_params — interpolation and clamping
# ---------------------------------------------------------------------------

class TestFovParams:
    def test_at_low_anchor(self):
        back, front, bw, fw = _fov_params(_CAL_PITCH_LOW)
        assert back  == _CAL_BACK_FWD
        assert front == _CAL_FRONT_LOW
        assert bw    == _CAL_BACK_W_LOW
        assert fw    == _CAL_FRONT_W_LOW

    def test_at_high_anchor(self):
        back, front, bw, fw = _fov_params(_CAL_PITCH_HIGH)
        assert back  == _CAL_BACK_FWD
        assert front == _CAL_FRONT_HIGH
        assert bw    == _CAL_BACK_W_HIGH
        assert fw    == _CAL_FRONT_W_HIGH

    def test_midpoint(self):
        mid = (_CAL_PITCH_LOW + _CAL_PITCH_HIGH) // 2
        back, front, bw, fw = _fov_params(mid)
        assert back  == _CAL_BACK_FWD
        assert _CAL_FRONT_HIGH < front < _CAL_FRONT_LOW
        assert _CAL_BACK_W_LOW  < bw   < _CAL_BACK_W_HIGH
        assert _CAL_FRONT_W_LOW < fw   < _CAL_FRONT_W_HIGH

    def test_below_low_anchor_clamps(self):
        back, front, bw, fw = _fov_params(50)
        assert front == _CAL_FRONT_LOW
        assert bw    == _CAL_BACK_W_LOW

    def test_above_high_anchor_clamps(self):
        back, front, bw, fw = _fov_params(600)
        assert front == _CAL_FRONT_HIGH
        assert bw    == _CAL_BACK_W_HIGH


# ---------------------------------------------------------------------------
# fov_polygon_world — geometry checks
# ---------------------------------------------------------------------------

class TestFovPolygonWorld:
    def test_returns_four_vertices(self):
        poly = fov_polygon_world(229, 0, PLAYER_X, PLAYER_Y)
        assert len(poly) == 4

    def test_facing_north_at_cal_low_pitch(self):
        # pitch=229, yaw=0 (North): exactly matches calibration anchor
        poly = fov_polygon_world(229, 0, PLAYER_X, PLAYER_Y)
        # forward = +Y, right = +X
        # back-left:  (-4, 3197), back-right: (4, 3197)
        # front-left: (-6, 3206), front-right: (6, 3206)
        back_l, back_r, front_r, front_l = poly

        # X coords (right/left)
        assert math.isclose(back_l[0],  PLAYER_X - _CAL_BACK_W_LOW,  abs_tol=1e-9)
        assert math.isclose(back_r[0],  PLAYER_X + _CAL_BACK_W_LOW,  abs_tol=1e-9)
        assert math.isclose(front_r[0], PLAYER_X + _CAL_FRONT_W_LOW, abs_tol=1e-9)
        assert math.isclose(front_l[0], PLAYER_X - _CAL_FRONT_W_LOW, abs_tol=1e-9)

        # Y coords (forward/back)
        assert math.isclose(back_l[1],  PLAYER_Y + _CAL_BACK_FWD,   abs_tol=1e-9)
        assert math.isclose(front_r[1], PLAYER_Y + _CAL_FRONT_LOW,  abs_tol=1e-9)

    def test_facing_east_rotates_correctly(self):
        # yaw=1536 (East): forward = +X, right = -Y
        poly = fov_polygon_world(229, 1536, PLAYER_X, PLAYER_Y)
        back_l, back_r, front_r, front_l = poly

        # back edge: 3 tiles West of player → x ≈ PLAYER_X + CAL_BACK_FWD = PLAYER_X - 3
        assert math.isclose(back_l[0], PLAYER_X + _CAL_BACK_FWD, abs_tol=0.01)
        assert math.isclose(back_r[0], PLAYER_X + _CAL_BACK_FWD, abs_tol=0.01)

        # front edge: 6 tiles East of player → x ≈ PLAYER_X + 6
        assert math.isclose(front_r[0], PLAYER_X + _CAL_FRONT_LOW, abs_tol=0.01)

    def test_symmetric_about_forward_axis(self):
        # Left and right vertices should be symmetric around the forward axis
        poly = fov_polygon_world(300, 0, PLAYER_X, PLAYER_Y)
        back_l, back_r, front_r, front_l = poly
        assert math.isclose(back_l[0] + back_r[0],   2 * PLAYER_X, abs_tol=1e-9)
        assert math.isclose(front_l[0] + front_r[0], 2 * PLAYER_X, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# angular_offset
# ---------------------------------------------------------------------------

class TestAngularOffset:
    def test_same_bearing(self):
        assert angular_offset(0, 0) == 0

    def test_quarter_turn(self):
        assert angular_offset(512, 0) == 512

    def test_symmetry(self):
        assert angular_offset(512, 0) == angular_offset(0, 512)

    def test_half_turn_is_1024(self):
        assert angular_offset(1024, 0) == 1024

    def test_short_path_taken_past_half(self):
        # 1537 CCW = 511 CW — shortest path is 511
        assert angular_offset(1537, 0) == 511

    def test_wrap_around_zero(self):
        assert angular_offset(2047, 1) == 2


# ---------------------------------------------------------------------------
# entity_in_fov — trapezoid containment
#
# All tests: player at (3200, 3200), camera facing North (yaw=0), pitch=300.
# At pitch=300 (t≈0.78): front≈3.66 tiles, back=-3 tiles,
#   back_half_w≈4.78, front_half_w≈6.78.
# ---------------------------------------------------------------------------

class TestEntityInFov:
    def test_entity_directly_ahead_inside(self):
        # 3 tiles North — within the front boundary (≈3.66 tiles)
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 3}
        assert entity_in_fov(entity, g) is True

    def test_entity_too_far_ahead_outside(self):
        # 5 tiles North — beyond front boundary at pitch=300 (≈3.66 tiles)
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 5}
        assert entity_in_fov(entity, g) is False

    def test_entity_behind_outside(self):
        # 4 tiles South — beyond back boundary (-3 tiles)
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y - 4}
        assert entity_in_fov(entity, g) is False

    def test_entity_far_to_side_outside(self):
        # 10 tiles East, at player's N-S level — well outside any half-width
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X + 10, "worldY": PLAYER_Y}
        assert entity_in_fov(entity, g) is False

    def test_entity_at_low_pitch_sees_further(self):
        # At pitch=229 the front boundary is 6 tiles; 5 tiles ahead should be inside
        g = _game(yaw=0, pitch=229)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 5}
        assert entity_in_fov(entity, g) is True

    def test_no_camera_data_returns_false(self):
        g = GameState()
        g.update(_base_msg(player=_player()))
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 3}
        assert entity_in_fov(entity, g) is False

    def test_facing_east_sees_east(self):
        # Camera facing East (yaw=1536), entity 3 tiles East
        g = _game(yaw=1536, pitch=300)
        entity = {"worldX": PLAYER_X + 3, "worldY": PLAYER_Y}
        assert entity_in_fov(entity, g) is True

    def test_facing_east_does_not_see_behind(self):
        # Camera facing East, entity 4 tiles West (directly behind) — outside FOV.
        # In camera space: fwd = -4 < back_fwd (-3) → behind the back boundary.
        g = _game(yaw=1536, pitch=300)
        entity = {"worldX": PLAYER_X - 4, "worldY": PLAYER_Y}
        assert entity_in_fov(entity, g) is False


# ---------------------------------------------------------------------------
# decide_camera_action
# ---------------------------------------------------------------------------

class TestDecidemCameraAction:
    def test_on_screen_flag_returns_on_screen(self):
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 3, "onScreen": True}
        assert decide_camera_action(entity, g) == "on_screen"

    def test_entity_in_fov_returns_on_screen(self):
        # Inside trapezoid, onScreen flag absent/False — FOV check catches it
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y + 3, "onScreen": False}
        assert decide_camera_action(entity, g) == "on_screen"

    def test_close_offset_returns_rotate(self):
        # Camera facing East (yaw=1536), entity at dx=5, dy=4 from player.
        # camera_yaw_to → ≈1756; angular_offset(1756, 1536) ≈ 220 units ≈ 38.7°.
        # front_fwd at pitch=300 ≈ 3.66 tiles; fwd-component = 5 > 3.66 → outside FOV.
        # offset_deg < 45 and distance=9 ≤ 15 → "rotate".
        g = _game(yaw=1536, pitch=300)
        entity = {"worldX": PLAYER_X + 5, "worldY": PLAYER_Y + 4, "onScreen": False}
        assert decide_camera_action(entity, g) == "rotate"

    def test_far_entity_returns_walk(self):
        # 30 tiles South, camera facing North → outside FOV, 180° offset, distance 30 > 15
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X, "worldY": PLAYER_Y - 30, "onScreen": False}
        assert decide_camera_action(entity, g) == "walk"

    def test_entity_90deg_off_close_returns_walk(self):
        # Camera facing North, entity 10 tiles East → 90° offset > 45° → "walk"
        g = _game(yaw=0, pitch=300)
        entity = {"worldX": PLAYER_X + 10, "worldY": PLAYER_Y, "onScreen": False}
        assert decide_camera_action(entity, g) == "walk"
