"""Painting a run of slots around a cell's border -- the machinery behind the two
border-style damage indicators.

A cell's outline is drawn as part of its SHAPE (the square's BorderedRectangle
border, the hex's outer polygon behind the inner one), so an overlay cannot erase
it. It can only paint over it. That single fact gives the two indicators their
character, and both are the same operation with a different color and span:

  * DASHED -- paint in the BOARD BACKGROUND color, over part of each slot. The
    painted stretches read as gaps, so the solid outline visibly breaks into
    dashes as damage mounts.
  * FADE -- paint in the DAMAGE color, over the whole slot. The outline turns red
    a slot at a time.

The border is divided into `total` equal slots by ARC LENGTH around the cell's own
outline (asked of the grid via cell_vertices), so it works on the square, hex and
triangle boards alike, and a slot spanning a corner bends around it correctly.
Slots are painted from the first, so the run grows as one contiguous arc.
"""

import math
import pyglet
from views.shaders import get_shape_shader


def _edges(verts):
    """The closed polygon's edges as (start, end, length), plus the perimeter."""
    edges = []
    total = 0.0
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        edges.append((a, b, length))
        total += length
    return edges, total


def _point_at(edges, perimeter, t):
    """The point a fraction `t` (0-1) of the way around the perimeter."""
    target = (t % 1.0) * perimeter
    for (ax, ay), (bx, by), length in edges:
        if target <= length or length == 0.0:
            if length == 0.0:
                return (ax, ay)
            f = target / length
            return (ax + f * (bx - ax), ay + f * (by - ay))
        target -= length
    return edges[-1][1]


def polyline_between(verts, t0, t1):
    """The polyline running along the outline from perimeter fraction `t0` to
    `t1`. Any polygon CORNERS between them are included in order, so the run
    bends around the cell instead of cutting the corner."""
    edges, perimeter = _edges(verts)
    if perimeter <= 0.0:
        return []
    points = [_point_at(edges, perimeter, t0)]
    # Corner positions as perimeter fractions, in order.
    walked = 0.0
    for (_a, b, length) in edges:
        walked += length
        corner_t = walked / perimeter
        if t0 < corner_t < t1:
            points.append(b)
    points.append(_point_at(edges, perimeter, t1))
    return points


class BorderDashes:
    """Per-cell runs of painted border slots, drawn into a caller-supplied batch.

    `board` supplies each cell's outline (cell_vertices). `span` is how much of
    each slot is actually painted (1.0 = the whole slot, edge to edge; less leaves
    a visible break at each slot boundary, which is what makes gaps read as
    dashes)."""

    def __init__(self, board, batch, color, thickness, span=1.0):
        self._board = board
        self._batch = batch
        self._color = color
        self._thickness = thickness
        self._span = span
        self._lines = {}      # cell -> its Line segments

    def set_marked(self, cell, marked, total):
        """Paint the first `marked` of `total` slots around `cell`'s border.
        marked <= 0 (or a total of 0) leaves the border untouched."""
        self.remove(cell)
        if not marked or marked <= 0 or not total or total <= 0:
            return
        verts = self._board.cell_vertices(*cell)
        if len(verts) < 3:
            return
        shader = get_shape_shader()
        segments = []
        # Center each painted stretch in its slot, so the untouched remainder
        # splits evenly between the two neighboring boundaries.
        pad = (1.0 - self._span) / 2.0 / total
        for i in range(min(marked, total)):
            t0 = i / total + pad
            t1 = (i + 1) / total - pad
            points = polyline_between(verts, t0, t1)
            for a, b in zip(points, points[1:]):
                line = pyglet.shapes.Line(
                    a[0], a[1], b[0], b[1],
                    thickness=self._thickness, color=self._color,
                    batch=self._batch, program=shader,
                )
                segments.append(line)
        self._lines[cell] = segments

    def remove(self, cell):
        """Drop `cell`'s painted slots."""
        for line in self._lines.pop(cell, ()):
            line.delete()

    def clear(self):
        """Drop every painted slot (a new game)."""
        for segments in self._lines.values():
            for line in segments:
                line.delete()
        self._lines = {}
