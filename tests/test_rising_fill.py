"""The bottom-up fill geometry (views/rising_fill.clip_below) and the grids'
cell_vertices, which the damage display and the sand timers both clip against.

Only the pure geometry is tested here -- RisingFill itself builds pyglet Polygons,
which need a GL context.
"""
import pytest

from views.rising_fill import clip_below

# A unit square, counter-clockwise from the bottom-left.
_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_at_the_floor_every_shape_collapses_to_zero_height():
    # Clipping at the floor keeps whatever vertices sit exactly ON it, so the
    # result degenerates differently per shape -- 4 collapsed points for a square,
    # 2 for a triangle's flat base, 3 for a triangle's apex (both crossing edges
    # contribute the same point). The POINT COUNT is therefore no guide to
    # "nothing to draw", which is why RisingFill.set_fraction guards on
    # fraction <= 0: otherwise an undamaged cell would carry an invisible,
    # zero-area polygon around for the whole game.
    up = [(-1.0, 0.0), (1.0, 0.0), (0.0, 2.0)]      # flat base on the floor
    down = [(-1.0, 2.0), (1.0, 2.0), (0.0, 0.0)]    # apex on the floor
    for shape in (_SQUARE, up, down):
        clipped = clip_below(shape, 0.0)
        assert {y for _x, y in clipped} == {0.0}, shape


def test_half_fill_keeps_the_bottom_half():
    clipped = clip_below(_SQUARE, 0.5)
    assert len(clipped) == 4
    assert max(y for _x, y in clipped) == pytest.approx(0.5)
    assert min(y for _x, y in clipped) == pytest.approx(0.0)


def test_full_fill_keeps_the_whole_cell():
    clipped = clip_below(_SQUARE, 1.0)
    assert set(clipped) == set(_SQUARE)


def test_clip_of_a_triangle_crosses_both_slanted_edges():
    # An up-pointing triangle: a fill line partway up crosses the two slanted
    # edges, so the filled region is a trapezoid (4 points), not a triangle.
    up = [(-1.0, 0.0), (1.0, 0.0), (0.0, 2.0)]
    clipped = clip_below(up, 1.0)
    assert len(clipped) == 4
    assert max(y for _x, y in clipped) == pytest.approx(1.0)
    # Half the height of a triangle is HALF the width across, so the fill line
    # spans x in [-0.5, 0.5] -- the property a naive bounding-box fill gets wrong.
    top = sorted(x for x, y in clipped if y == pytest.approx(1.0))
    assert top == [pytest.approx(-0.5), pytest.approx(0.5)]
