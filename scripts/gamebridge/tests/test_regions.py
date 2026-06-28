"""
Tests for regions.py — Region polygon geometry, centre/direction-biased
point sampling, and RegionRoute chain traversal.
"""
from __future__ import annotations

import random

import pytest

from scripts.gamebridge.regions import Path, Region, RegionRoute, point_in_polygon

SQUARE = (
    (0, 0), (10, 0), (10, 10), (0, 10),
)


# ---------------------------------------------------------------------------
# point_in_polygon
# ---------------------------------------------------------------------------

class TestPointInPolygon:
    def test_point_inside_square(self):
        assert point_in_polygon(5, 5, SQUARE) is True

    def test_point_outside_square(self):
        assert point_in_polygon(15, 5, SQUARE) is False

    def test_point_outside_concave_notch(self):
        # An L-shaped polygon — the notch carved out of the square's top-right quadrant.
        l_shape = ((0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10))
        assert point_in_polygon(7, 7, l_shape) is False
        assert point_in_polygon(2, 2, l_shape) is True


# ---------------------------------------------------------------------------
# Region.contains / centroid / bounds
# ---------------------------------------------------------------------------

class TestRegionBasics:
    def test_contains_inside_point(self):
        region = Region("square", SQUARE)
        assert region.contains(5, 5) is True

    def test_contains_outside_point(self):
        region = Region("square", SQUARE)
        assert region.contains(-1, -1) is False

    def test_centroid_of_square(self):
        region = Region("square", SQUARE)
        assert region.centroid == (5.0, 5.0)

    def test_bounds_of_square(self):
        region = Region("square", SQUARE)
        assert region.bounds == (0, 0, 10, 10)


# ---------------------------------------------------------------------------
# Region.sample_point
# ---------------------------------------------------------------------------

class TestSamplePoint:
    def test_sampled_point_is_always_inside_region(self):
        region = Region("square", SQUARE)
        rng = random.Random(1)
        for _ in range(50):
            x, y = region.sample_point(rng)
            assert region.contains(x, y)

    def test_no_direction_bias_stays_near_centre_on_average(self):
        """With center_bias=1 / direction_bias=0, sampled points should
        cluster closer to the centroid than a uniform sample would."""
        region = Region("square", SQUARE)
        rng = random.Random(2)
        samples = [region.sample_point(rng, center_bias=1.0, direction_bias=0.0) for _ in range(200)]
        avg_dist = sum(((x - 5) ** 2 + (y - 5) ** 2) ** 0.5 for x, y in samples) / len(samples)
        # Uniform-in-square expected distance from centre is ~3.8; a strong
        # centre bias should pull the average well below that.
        assert avg_dist < 3.0

    def test_direction_bias_pulls_points_toward_target_edge(self):
        """A direction pointing due 'east' (+x) should bias samples toward
        the right-hand edge of the square, i.e. higher average x."""
        region = Region("square", SQUARE)
        rng = random.Random(3)
        biased = [region.sample_point(rng, direction=(1, 0), center_bias=0.0, direction_bias=1.0)
                  for _ in range(200)]
        unbiased_rng = random.Random(3)
        unbiased = [region.sample_point(unbiased_rng, direction=None, center_bias=1.0, direction_bias=0.0)
                    for _ in range(200)]
        avg_biased_x = sum(x for x, _ in biased) / len(biased)
        avg_unbiased_x = sum(x for x, _ in unbiased) / len(unbiased)
        assert avg_biased_x > avg_unbiased_x

    def test_zero_direction_vector_does_not_crash(self):
        region = Region("square", SQUARE)
        rng = random.Random(4)
        x, y = region.sample_point(rng, direction=(0, 0))
        assert region.contains(x, y)

    def test_falls_back_to_centroid_when_polygon_too_thin_to_sample(self):
        """A degenerate (zero-area) polygon can never satisfy contains() for
        any randomly sampled point, so sample_point must fall back rather
        than looping forever."""
        degenerate = Region("line", ((0, 0), (10, 0), (0, 0)))
        rng = random.Random(5)
        x, y = degenerate.sample_point(rng, candidates=5)
        assert (x, y) == (round(degenerate.centroid[0]), round(degenerate.centroid[1]))

    def test_introduces_randomness_across_calls(self):
        region = Region("square", SQUARE)
        rng = random.Random(6)
        points = {region.sample_point(rng) for _ in range(20)}
        assert len(points) > 1


# ---------------------------------------------------------------------------
# RegionRoute
# ---------------------------------------------------------------------------

A = Region("A", ((0, 0), (10, 0), (10, 10), (0, 10)))
B = Region("B", ((10, 0), (20, 0), (20, 10), (10, 10)))
C = Region("C", ((20, 0), (30, 0), (30, 10), (20, 10)))
D = Region("D", ((30, 0), (40, 0), (40, 10), (30, 10)))

ROUTE = RegionRoute((A, B, C, D))


class TestRegionRoute:
    def test_index_of(self):
        assert ROUTE.index_of(C) == 2

    def test_locate_finds_containing_region(self):
        assert ROUTE.locate(5, 5) is A
        assert ROUTE.locate(25, 5) is C

    def test_locate_returns_none_when_not_on_route(self):
        assert ROUTE.locate(1000, 1000) is None

    def test_next_region_toward_end(self):
        assert ROUTE.next_region(A, toward_end=True) is B
        assert ROUTE.next_region(C, toward_end=True) is D

    def test_next_region_toward_start(self):
        assert ROUTE.next_region(D, toward_end=False) is C
        assert ROUTE.next_region(B, toward_end=False) is A

    def test_next_region_none_past_the_end(self):
        assert ROUTE.next_region(D, toward_end=True) is None

    def test_next_region_none_past_the_start(self):
        assert ROUTE.next_region(A, toward_end=False) is None


# ---------------------------------------------------------------------------
# Path.from_recording
# ---------------------------------------------------------------------------

# A straight line of 21 waypoints at (0,0)..(20,0), as (x, y, plane) triples
# (plane is always 0, matching real recordings, and must be ignored).
LINE_POINTS = tuple((float(i), 0.0, 0) for i in range(21))
LINE_WITH_DUPES = (LINE_POINTS[0], LINE_POINTS[0], LINE_POINTS[0]) + LINE_POINTS[1:]

# Direct construction for tests that don't care about from_recording.
STRAIGHT = tuple((float(i), 0.0) for i in range(21))


class TestPathFromRecording:
    def test_dedupes_consecutive_duplicate_points(self):
        path = Path.from_recording("line", LINE_WITH_DUPES)
        assert path.points[0] == (0.0, 0.0)
        assert path.points[1] == (1.0, 0.0)
        assert len(path.points) == len(LINE_POINTS)

    def test_no_stride_keeps_every_deduped_point(self):
        path = Path.from_recording("line", LINE_POINTS)
        assert len(path.points) == len(LINE_POINTS)

    def test_stride_decimates_points(self):
        path = Path.from_recording("line", LINE_POINTS, stride=4)
        assert len(path.points) < len(LINE_POINTS)

    def test_stride_always_keeps_final_point_even_if_off_stride(self):
        path = Path.from_recording("line", LINE_POINTS, stride=6)
        assert path.points[-1] == (20.0, 0.0)
        assert len(path.points) == 5  # indices 0, 6, 12, 18, 20

    def test_extra_columns_in_raw_points_are_ignored(self):
        path = Path.from_recording("line", LINE_POINTS)
        assert all(len(p) == 2 for p in path.points)

    def test_empty_input_returns_empty_path(self):
        path = Path.from_recording("empty", ())
        assert path.points == ()


# ---------------------------------------------------------------------------
# Path.nearest_index
# ---------------------------------------------------------------------------

class TestPathNearestIndex:
    def test_finds_exact_match(self):
        path = Path("line", STRAIGHT)
        assert path.nearest_index(10.0, 0.0) == 10

    def test_finds_closest_point_off_path(self):
        path = Path("line", STRAIGHT)
        assert path.nearest_index(7.4, 3.0) == 7

    def test_clamps_to_nearest_end_beyond_path(self):
        path = Path("line", STRAIGHT)
        assert path.nearest_index(-50.0, 0.0) == 0
        assert path.nearest_index(50.0, 0.0) == 20


# ---------------------------------------------------------------------------
# Path.click_target
# ---------------------------------------------------------------------------

class TestPathClickTarget:
    def test_reaches_full_max_distance_with_min_fraction_one(self):
        """min_fraction=1.0 forces the randomised fraction to always be 1.0,
        i.e. click as far as max_distance allows — deterministic for testing."""
        path = Path("line", STRAIGHT)
        rng = random.Random(1)
        tx, _ = path.click_target((0.0, 0.0), rng, max_distance=5, lateral_jitter=0.0, min_fraction=1.0)
        assert tx == 5

    def test_reaches_full_max_distance_reverse(self):
        path = Path("line", STRAIGHT)
        rng = random.Random(1)
        tx, _ = path.click_target(
            (20.0, 0.0), rng, max_distance=5, lateral_jitter=0.0, reverse=True, min_fraction=1.0,
        )
        assert tx == 15

    def test_randomness_sometimes_picks_less_than_the_max(self):
        """Without forcing min_fraction=1.0, repeated calls should not
        always click the farthest reachable point."""
        path = Path("line", STRAIGHT)
        rng = random.Random(2)
        targets = {path.click_target((0.0, 0.0), rng, max_distance=10, lateral_jitter=0.0)[0]
                   for _ in range(30)}
        assert len(targets) > 1
        assert max(targets) <= 10

    def test_always_advances_at_least_one_waypoint(self):
        """Even if max_distance is smaller than the gap to the very next
        waypoint, the target must still move forward rather than standing
        still."""
        path = Path("line", STRAIGHT)
        rng = random.Random(3)
        tx, _ = path.click_target((0.0, 0.0), rng, max_distance=0.1, lateral_jitter=0.0)
        assert tx == 1

    def test_jitter_is_bounded_and_perpendicular_to_path(self):
        """The path runs along the x-axis, so jitter (perpendicular to the
        local path direction) should only ever perturb y, never x."""
        path = Path("line", STRAIGHT)
        rng = random.Random(4)
        for _ in range(50):
            tx, ty = path.click_target((0.0, 0.0), rng, max_distance=5, lateral_jitter=2.0, min_fraction=1.0)
            assert tx == 5
            assert abs(ty) <= 2

    def test_clamps_at_end_of_path(self):
        path = Path("line", STRAIGHT)
        rng = random.Random(5)
        tx, _ = path.click_target((18.0, 0.0), rng, max_distance=10, lateral_jitter=0.0, min_fraction=1.0)
        assert tx == 20

    def test_clamps_at_start_of_path_reverse(self):
        path = Path("line", STRAIGHT)
        rng = random.Random(6)
        tx, _ = path.click_target(
            (2.0, 0.0), rng, max_distance=10, lateral_jitter=0.0, reverse=True, min_fraction=1.0,
        )
        assert tx == 0

    def test_returns_int_coordinates(self):
        path = Path("line", STRAIGHT)
        rng = random.Random(7)
        tx, ty = path.click_target((0.0, 0.0), rng, max_distance=5)
        assert isinstance(tx, int)
        assert isinstance(ty, int)


# ---------------------------------------------------------------------------
# Path.is_at_end
# ---------------------------------------------------------------------------

class TestPathIsAtEnd:
    def test_at_forward_end_within_tolerance(self):
        path = Path("line", STRAIGHT)
        assert path.is_at_end(19.0, 0.0, reverse=False, tolerance_tiles=2) is True

    def test_not_at_forward_end_outside_tolerance(self):
        path = Path("line", STRAIGHT)
        assert path.is_at_end(10.0, 0.0, reverse=False, tolerance_tiles=2) is False

    def test_at_reverse_end_within_tolerance(self):
        path = Path("line", STRAIGHT)
        assert path.is_at_end(1.0, 0.0, reverse=True, tolerance_tiles=2) is True

    def test_not_at_reverse_end_outside_tolerance(self):
        path = Path("line", STRAIGHT)
        assert path.is_at_end(10.0, 0.0, reverse=True, tolerance_tiles=2) is False
