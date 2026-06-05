"""
Field-of-view helpers for the GameBridge camera system.

The FOV is modelled as a trapezoid (quadrilateral) in camera-relative tile space,
calibrated from two empirical measurements at the user's preferred zoom level:

  pitch=229 (near-horizon): 3 tiles back, 6 tiles front, half-width 4/6
  pitch=320 (overhead):     3 tiles back, 3 tiles front, half-width 5/7

Parameters interpolate linearly between these anchors; clamped outside the range.
The trapezoid is defined in (right, forward) camera-relative coordinates and
rotated into world tile space by the camera yaw before use.

Requires camera_yaw_to() in GameState to use the fixed atan2(-dx, dy) formula
(CAMERA_FOV.md §4).
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state.game_state import GameState

# Calibration anchors — measured empirically at the user's preferred zoom.
# Adjust these constants if zoom level changes (see CAMERA_FOV.md §7d/7e).
_CAL_PITCH_LOW  = 229   # near-horizon anchor pitch
_CAL_PITCH_HIGH = 320   # overhead anchor pitch

# All distances in tiles. "forward" = positive toward front, negative toward back.
_CAL_BACK_FWD       = -3   # back-edge distance (same at both pitches)
_CAL_FRONT_LOW      =  6   # forward extent at low pitch
_CAL_FRONT_HIGH     =  3   # forward extent at high pitch
_CAL_BACK_W_LOW     =  4   # half-width at back edge, low pitch
_CAL_BACK_W_HIGH    =  5   # half-width at back edge, high pitch
_CAL_FRONT_W_LOW    =  6   # half-width at front edge, low pitch
_CAL_FRONT_W_HIGH   =  7   # half-width at front edge, high pitch


def _fov_params(pitch: int) -> tuple[float, float, float, float]:
    """
    Return (back_fwd, front_fwd, back_half_w, front_half_w) in tiles for pitch.

    Interpolates linearly between calibration anchors; clamps outside that range.
    """
    t = (pitch - _CAL_PITCH_LOW) / (_CAL_PITCH_HIGH - _CAL_PITCH_LOW)
    t = max(0.0, min(1.0, t))
    front   = _CAL_FRONT_LOW   + t * (_CAL_FRONT_HIGH   - _CAL_FRONT_LOW)
    back_w  = _CAL_BACK_W_LOW  + t * (_CAL_BACK_W_HIGH  - _CAL_BACK_W_LOW)
    front_w = _CAL_FRONT_W_LOW + t * (_CAL_FRONT_W_HIGH - _CAL_FRONT_W_LOW)
    return (float(_CAL_BACK_FWD), front, back_w, front_w)


def fov_polygon_world(
    pitch: int,
    yaw: int,
    player_x: float,
    player_y: float,
) -> list[tuple[float, float]]:
    """
    Return the 4 vertices of the FOV trapezoid in world tile coordinates.

    Vertex order: back-left, back-right, front-right, front-left.

    yaw convention: 0=North, 512=West, 1024=South, 1536=East (OSRS CCW).
    player_x/y are world tile coordinates (may be float for sub-tile precision).
    """
    back_fwd, front_fwd, back_half_w, front_half_w = _fov_params(pitch)

    θ = yaw / 2048.0 * 2 * math.pi
    # Unit vectors in world tile space:
    #   forward  = direction the camera faces
    #   right    = 90° CW from forward (to the right of the facing direction)
    fwd_x, fwd_y = -math.sin(θ), math.cos(θ)
    rgt_x, rgt_y =  math.cos(θ), math.sin(θ)

    def _to_world(r: float, f: float) -> tuple[float, float]:
        return (player_x + r * rgt_x + f * fwd_x,
                player_y + r * rgt_y + f * fwd_y)

    return [
        _to_world(-back_half_w,  back_fwd),    # back-left
        _to_world(+back_half_w,  back_fwd),    # back-right
        _to_world(+front_half_w, front_fwd),   # front-right
        _to_world(-front_half_w, front_fwd),   # front-left
    ]


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def angular_offset(bearing_a: int, bearing_b: int) -> int:
    """Shortest angular distance in yaw-units between two bearings (0–2047)."""
    delta = (bearing_a - bearing_b + 2048) % 2048
    return min(delta, 2048 - delta)


def entity_in_fov(entity: dict, game: "GameState") -> bool:
    """
    Return True if the entity is likely within the camera's visible trapezoid.

    Uses the calibrated trapezoid model (CAMERA_FOV.md §9).
    camera_yaw_to() must use the fixed atan2(-dx, dy) formula.
    """
    camera = game.camera
    if not camera:
        return False

    pitch = camera.get("pitch", 300)
    yaw   = camera.get("yaw",   0)
    px, py = game.player_pos
    polygon = fov_polygon_world(pitch, yaw, px, py)
    return _point_in_polygon(entity["worldX"], entity["worldY"], polygon)


def decide_camera_action(entity: dict, game: "GameState") -> str:
    """
    Return 'on_screen', 'rotate', or 'walk'.

    on_screen — entity is already visible; click it.
    rotate    — small angular correction will bring it into view this tick.
    walk      — entity is too far or too far off-bearing; walk toward it.
    """
    if entity.get("onScreen") or entity_in_fov(entity, game):
        return "on_screen"

    camera = game.camera or {}
    yaw = camera.get("yaw", 0)
    target_yaw = game.camera_yaw_to(entity)
    offset_units = angular_offset(target_yaw, yaw)
    offset_deg = offset_units / 2048.0 * 360.0
    distance = game.distance_to(entity)

    if offset_deg < 45 and distance <= 15:
        return "rotate"
    return "walk"
