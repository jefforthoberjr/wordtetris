"""A bottom-up fill overlay: cells that fill from the floor up as some 0-1
fraction rises.

Extracted from views/moving_mode.SandTimerField, which drew the omniswap sand
timers this way and is now the second caller rather than the only one. Two things
changed in the move:

  * The polygon is clipped against the cell's OWN outline, asked of the grid
    (cell_vertices), instead of hardcoding a flat-top hexagon -- so it works on
    the square, hex and triangle boards, and rises through a jumbo hexagon as one
    shape rather than filling its anchor triangle.
  * The fraction is supplied by the caller, so a timer can drive it continuously
    while cell health drives it in discrete steps per hit.

The overlay owns nothing but its shapes: callers set a cell's fraction, and the
overlay creates / rebuilds / drops the polygon to match.
"""

import pyglet
from views.shaders import get_shape_shader


def clip_below(verts, y_line):
    """Sutherland-Hodgman clip of a convex polygon to the half-plane y <= y_line
    -- the part of a cell filled from the bottom up. Returns the clipped vertex
    list (< 3 points when nothing is filled)."""
    out = []
    n = len(verts)
    for i in range(n):
        cur, nxt = verts[i], verts[(i + 1) % n]
        cur_in, nxt_in = cur[1] <= y_line, nxt[1] <= y_line
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:   # edge crosses the fill line -> add the crossing point
            t = (y_line - cur[1]) / (nxt[1] - cur[1])
            out.append((cur[0] + t * (nxt[0] - cur[0]), y_line))
    return out


class RisingFill:
    """Per-cell bottom-up fill polygons, drawn into a caller-supplied batch.

    `board` supplies each cell's outline (cell_vertices); `color` and `opacity`
    style the fill -- translucent, so the cell's gram still reads through it."""

    def __init__(self, board, batch, color, opacity):
        self._board = board
        self._batch = batch
        self._color = color
        self._opacity = opacity
        self._shapes = {}     # cell -> its fill Polygon

    def set_fraction(self, cell, fraction):
        """Fill `cell` to `fraction` (0-1) of its height. 0 or less removes the
        fill entirely; the polygon is rebuilt rather than resized, since the
        clipped outline changes shape as the line rises."""
        old = self._shapes.pop(cell, None)
        if old is not None:
            old.delete()
        if fraction is None or fraction <= 0.0:
            return
        verts = self._board.cell_vertices(*cell)
        ys = [v[1] for v in verts]
        bottom, top = min(ys), max(ys)
        clipped = clip_below(verts, bottom + min(fraction, 1.0) * (top - bottom))
        if len(clipped) < 3:                 # nothing filled yet -- no polygon
            return
        poly = pyglet.shapes.Polygon(
            *clipped, color=self._color, batch=self._batch,
            program=get_shape_shader())
        poly.opacity = self._opacity
        self._shapes[cell] = poly

    def positions(self):
        """The cells currently carrying a fill. Lets a caller whose own tracking
        is the source of truth (the sand timers) drop the fills of cells it has
        stopped tracking, without keeping a parallel set."""
        return list(self._shapes)

    def remove(self, cell):
        """Drop `cell`'s fill (it left the board, or stopped being tracked)."""
        self.set_fraction(cell, 0.0)

    def clear(self):
        """Drop every fill (a new game)."""
        for poly in self._shapes.values():
            poly.delete()
        self._shapes = {}
