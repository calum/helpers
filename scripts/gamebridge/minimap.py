"""
Minimap coordinate conversion helpers.

The in-game minimap is not north-up and not a fixed scale: it rotates with
the camera (`camera['yawTarget']`, 0-2047 CCW from North — see GAMEBRIDGE.md)
and scales by `camera['minimapZoom']` (pixels per tile, default 4.0, changes
live when the player scrolls the mouse wheel over the minimap). Any synthetic
minimap target built from a world-tile delta must replicate this rotation +
zoom transform (mirrors `Perspective.localToMinimap` in runelite-api) or it
will silently point in the wrong direction whenever the compass isn't
pointing north, or land short/long of the target whenever the minimap isn't
at its default zoom.
"""
from __future__ import annotations

import math


def world_delta_to_minimap_offset(
    dx_tiles: float,
    dy_tiles: float,
    yaw_target: int,
    minimap_zoom: float,
) -> tuple[float, float]:
    """Convert a world-tile delta (dx, dy) to a (canvas_dx, canvas_dy) minimap
    pixel offset, accounting for compass rotation and zoom.

    dx_tiles / dy_tiles: target world tile minus player world tile.
    yaw_target: camera['yawTarget'] (0-2047 CCW from North) — NOT camera['yaw'].
    minimap_zoom: camera['minimapZoom'] (pixels per tile).

    Returns (canvas_dx, canvas_dy) — the pixel offset from the minimap
    widget's centre to the target tile.
    """
    x = dx_tiles * minimap_zoom
    y = dy_tiles * minimap_zoom
    angle = (yaw_target % 2048) / 2048.0 * 2 * math.pi
    sin, cos = math.sin(angle), math.cos(angle)
    rx = cos * x + sin * y
    ry = sin * x - cos * y
    return rx, ry
