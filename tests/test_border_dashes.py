"""The border-slot geometry (views/border_dashes.polyline_between) behind the
dashed / fading damage indicators.

Only the pure geometry is tested -- BorderDashes itself builds pyglet Lines,
which need a GL context. The interesting property is that a slot spanning a
polygon CORNER bends around it instead of cutting across the cell.
"""
import math

import pytest

from views.border_dashes import polyline_between

# A unit square, counter-clockwise from the origin. Perimeter 4, one unit per side.
_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def test_a_slot_inside_one_edge_is_a_straight_segment():
    # The first quarter of the perimeter is exactly the bottom edge.
    points = polyline_between(_SQUARE, 0.0, 0.25)
    assert points == [(0.0, 0.0), (1.0, 0.0)]


def test_a_slot_spanning_a_corner_includes_the_corner():
    # 12.5%-37.5% straddles the bottom-right corner: the run must bend at (1,0)
    # rather than cutting diagonally across the cell.
    points = polyline_between(_SQUARE, 0.125, 0.375)
    assert points == [(0.5, 0.0), (1.0, 0.0), (1.0, 0.5)]
    assert _length(points) == pytest.approx(1.0)   # 25% of the perimeter


def test_slot_length_is_proportional_to_the_perimeter_share():
    # Any slot covering a third of the perimeter measures a third of it, corners
    # included -- which is what makes equal-health slots look equal on the board.
    for t0 in (0.0, 0.1, 0.4, 0.6):
        points = polyline_between(_SQUARE, t0, t0 + 1 / 3)
        assert _length(points) == pytest.approx(4.0 / 3.0)


def test_works_on_a_triangle_outline():
    # The triangle board's cells: 3 unequal-looking edges, still evenly divided
    # by arc length.
    tri = [(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)]
    perimeter = 2.0 + 2 * math.hypot(1.0, 2.0)
    points = polyline_between(tri, 0.0, 0.5)
    assert _length(points) == pytest.approx(perimeter / 2)
