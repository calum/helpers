"""
Region geometry for region-based pathing.

A `Region` is a named polygon in world-tile (x, y) coordinates. Routines
that travel between a fixed set of areas (e.g. RodFishingRoutine's bank /
fern / tree / fishing-spot commute) define their regions as `Region`
instances and chain them into a `RegionRoute`, instead of hardcoding a
sequence of landmark-entity lookups and Manhattan-distance thresholds for
every leg of the trip.

`Region.sample_point` answers the "where do I click next" question with a
centre-biased, optionally direction-biased random tile — clicking the exact
nearest border tile every lap looks robotic and the request that prompted
this module specifically asked for centre-weighted, randomised waypoints.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

Point = Tuple[float, float]


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    """Ray-casting point-in-polygon test (same algorithm as
    fov._point_in_polygon / recording.resolver._point_in_polygon — duplicated
    rather than imported so this module has no dependency on the
    screen-space hull/FOV code)."""
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


@dataclass(frozen=True)
class Region:
    """A named polygon in world-tile coordinates."""

    name: str
    polygon: Tuple[Point, ...]

    def contains(self, x: float, y: float) -> bool:
        return point_in_polygon(x, y, self.polygon)

    @property
    def centroid(self) -> Point:
        cx = sum(p[0] for p in self.polygon) / len(self.polygon)
        cy = sum(p[1] for p in self.polygon) / len(self.polygon)
        return cx, cy

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) bounding box."""
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return min(xs), min(ys), max(xs), max(ys)

    def sample_point(
        self,
        rng: random.Random,
        direction: Optional[Point] = None,
        center_bias: float = 0.5,
        direction_bias: float = 0.5,
        candidates: int = 20,
    ) -> Tuple[int, int]:
        """
        Pick a tile inside the region, biased toward the centroid and,
        optionally, toward the far edge in `direction`.

        Rejection-samples `candidates` tiles inside the polygon's bounding
        box (retrying up to 20x per candidate so a thin/concave polygon
        still reliably fills the quota), scores each by a weighted mix of
        "how central" and "how far along `direction`" it is, then picks a
        weighted-random candidate rather than always the single best score —
        a deterministic argmax would click the exact same tile every lap.

        `direction`, if given, is a (dx, dy) vector (need not be normalised)
        — e.g. the vector from this region's centroid toward the *next*
        region's centroid, so a transit through this region naturally heads
        toward whichever side is closest to wherever the route goes next,
        instead of stopping at the first tile inside the border.
        """
        min_x, min_y, max_x, max_y = self.bounds
        cx, cy = self.centroid
        max_radius = max(max_x - min_x, max_y - min_y) / 2 or 1.0

        if direction is not None and (direction[0] or direction[1]):
            dlen = math.hypot(direction[0], direction[1])
            unit = (direction[0] / dlen, direction[1] / dlen)
        else:
            unit = (0.0, 0.0)

        points: list[Tuple[float, float]] = []
        attempts = 0
        while len(points) < candidates and attempts < candidates * 20:
            attempts += 1
            x = rng.uniform(min_x, max_x)
            y = rng.uniform(min_y, max_y)
            if self.contains(x, y):
                points.append((x, y))

        if not points:
            return round(cx), round(cy)

        weights = []
        for x, y in points:
            center_score = 1.0 - min(math.hypot(x - cx, y - cy) / max_radius, 1.0)
            dir_score = ((x - cx) * unit[0] + (y - cy) * unit[1]) / max_radius
            dir_score = max(0.0, min(dir_score, 1.0))
            score = center_bias * center_score + direction_bias * dir_score
            weights.append(max(score, 1e-4))  # rng.choices needs positive weights

        x, y = rng.choices(points, weights=weights, k=1)[0]
        return round(x), round(y)


@dataclass(frozen=True)
class Path:
    """A named, ordered sequence of waypoints recorded from an actual walk
    (e.g. via the SessionRecorder, see PLAN.md's "Recording System" notes),
    used to drive `InteractionRoutine.travel_path` instead of clicking a
    randomised point inside a hand-drawn `Region` polygon — a real walked
    route already encodes the legal way around buildings/fences/water that
    a polygon's straight-line interior doesn't account for.
    """

    name: str
    points: Tuple[Point, ...]

    @classmethod
    def from_recording(
        cls,
        name: str,
        raw_points: Sequence[Sequence[float]],
        stride: int = 1,
    ) -> "Path":
        """Build a `Path` from raw recorded points (e.g. `(worldX, worldY,
        plane)` triples straight out of a recording) — only the first two
        elements of each point are used, so extra columns like `plane` are
        ignored.

        Consecutive duplicate points (the player stood still for more than
        one recorded tick) are collapsed to one. After deduping, every
        `stride`-th point is kept to thin out an overly dense recording;
        the final point is always kept even if it doesn't land on the
        stride, so the recorded endpoint is never lost.
        """
        deduped: list[Point] = []
        for raw in raw_points:
            point = (float(raw[0]), float(raw[1]))
            if not deduped or deduped[-1] != point:
                deduped.append(point)

        if stride <= 1:
            decimated = list(deduped)
        else:
            decimated = deduped[::stride]
            if decimated and decimated[-1] != deduped[-1]:
                decimated.append(deduped[-1])

        return cls(name, tuple(decimated))

    def nearest_index(self, x: float, y: float) -> int:
        """Index of the path point closest to (x, y)."""
        return min(
            range(len(self.points)),
            key=lambda i: math.hypot(self.points[i][0] - x, self.points[i][1] - y),
        )

    def click_target(
        self,
        current_pos: Point,
        rng: random.Random,
        max_distance: float,
        lateral_jitter: float = 1.0,
        reverse: bool = False,
        min_fraction: float = 0.4,
    ) -> Tuple[int, int]:
        """
        Pick the next click target while walking this path: locate the
        waypoint nearest `current_pos`, then walk forward (toward the end)
        by default, or backward (toward the start) if `reverse`, as far as
        `max_distance` tiles allows — clamping at whichever end is reached
        first. `max_distance` is normally the player's actual reach for a
        single click (e.g. how far the minimap currently extends, see
        `InteractionRoutine.travel_path`), so this clicks as far ahead as
        possible rather than a fixed number of waypoints.

        The distance actually used is randomised between `min_fraction` and
        1.0 of what's reachable, so the routine doesn't click the maximum
        distance every single time (a human doesn't always walk to the exact
        edge of their minimap) — but always advances at least one waypoint
        toward the destination, even if `max_distance` is smaller than the
        gap to the very next one.

        A small jitter perpendicular to the local path direction is added on
        top so every lap doesn't click the exact same pixel-equivalent tile.
        """
        idx = self.nearest_index(*current_pos)
        last = len(self.points) - 1
        step = -1 if reverse else 1

        farthest_idx = idx
        travelled = 0.0
        i = idx
        while 0 <= i + step <= last:
            nxt = i + step
            travelled += math.hypot(
                self.points[nxt][0] - self.points[i][0],
                self.points[nxt][1] - self.points[i][1],
            )
            if travelled > max_distance:
                break
            farthest_idx = nxt
            i = nxt

        if farthest_idx == idx and 0 <= idx + step <= last:
            # max_distance didn't even reach the next waypoint — still take
            # one step rather than standing still.
            farthest_idx = idx + step

        span = abs(farthest_idx - idx)
        if span == 0:
            target_idx = idx
        else:
            fraction = rng.uniform(min_fraction, 1.0)
            steps = max(1, round(fraction * span))
            target_idx = max(0, min(last, idx + step * steps))

        tx, ty = self.points[target_idx]

        prev_idx = max(0, target_idx - 1)
        next_idx = min(last, target_idx + 1)
        dx = self.points[next_idx][0] - self.points[prev_idx][0]
        dy = self.points[next_idx][1] - self.points[prev_idx][1]
        length = math.hypot(dx, dy)
        if length > 0:
            perp = (-dy / length, dx / length)
            jitter = rng.uniform(-lateral_jitter, lateral_jitter)
            tx += perp[0] * jitter
            ty += perp[1] * jitter

        return round(tx), round(ty)

    def is_at_end(
        self,
        x: float,
        y: float,
        reverse: bool = False,
        tolerance_tiles: float = 3.0,
    ) -> bool:
        """True if (x, y) is within `tolerance_tiles` of whichever end of
        the path is the destination — the start if `reverse`, else the end."""
        end_x, end_y = self.points[0] if reverse else self.points[-1]
        return math.hypot(x - end_x, y - end_y) <= tolerance_tiles


@dataclass(frozen=True)
class RegionRoute:
    """An ordered chain of regions a routine commutes back and forth along,
    e.g. [BANK_REGION, LOWER_EDGEVILLE, UPPER_BARBARIAN_VILLAGE,
    FISHING_REGION] for RodFishingRoutine's bank <-> fishing-spot commute.

    Travel is always along this fixed chain — there is no branching — so
    "the next region toward a destination" is just "the adjacent index in
    the direction of that destination".
    """

    regions: Tuple[Region, ...]

    def index_of(self, region: Region) -> int:
        return self.regions.index(region)

    def locate(self, x: float, y: float) -> Optional[Region]:
        """Return the first region in the chain containing (x, y), or None
        if the position isn't inside any region on the route."""
        for region in self.regions:
            if region.contains(x, y):
                return region
        return None

    def next_region(self, current: Region, toward_end: bool) -> Optional[Region]:
        """Return the region adjacent to `current` in the given direction
        along the chain, or None if `current` is already the terminal
        region in that direction."""
        idx = self.index_of(current) + (1 if toward_end else -1)
        if 0 <= idx < len(self.regions):
            return self.regions[idx]
        return None
