from enum import Enum


class TriangleDominoType(Enum):
    # SINGLE (1-cell) lives in TriangleUnimoType, mirroring the hex set: the
    # domino table here only spawns 2-cell pieces. Kept commented in case we ever
    # want mixed 1+2 cell domino spawning.
    # SINGLE = 1
    DOUBLE = 2


# A triangle piece is a primary cell plus zero or more satellite cells, each
# given as a DIRECTION index (0..2) from the primary. Like the hex grid we cannot
# store fixed (dx, dy) offsets: a triangle's third neighbor is below it when the
# triangle points up and above it when it points down, so the grid step depends
# on the cell's own parity. Directions are resolved live via triangle_neighbor().
TRIANGLE_DOMINO_DIRECTIONS = {
    # TriangleDominoType.SINGLE: [],   # just the primary cell (disabled; see enum)
    TriangleDominoType.DOUBLE: [0],    # primary + its right-hand neighbor (dir 0)
}

# Named direction indices (also used by the movement controls).
# A triangle has exactly three edges, so exactly three neighbors: the two it
# shares its slanted edges with (left / right, always in the same row) and the
# one across its horizontal edge (BASE), which is below an up-pointing triangle
# and above a down-pointing one.
TRIANGLE_RIGHT = 0
TRIANGLE_BASE = 1
TRIANGLE_LEFT = 2

TRIANGLE_ALL_DIRECTIONS = (TRIANGLE_RIGHT, TRIANGLE_BASE, TRIANGLE_LEFT)


def triangle_points_up(col, row):
    """True when cell (col, row) is drawn point-up. Rows alternate, and within a
    row every other triangle flips, so the whole board is one checkerboard of
    orientations keyed by (col + row) parity. Cell (0, 0) points up."""
    return (col + row) % 2 == 0


def triangle_neighbor(col, row, direction):
    """The (col, row) neighbor of a cell across one of its three edges.

    Left/right neighbors sit in the same row (columns overlap by half a triangle,
    so col +/- 1 shares a slanted edge). The BASE neighbor is the cell sharing the
    horizontal edge: row - 1 for an up-pointing triangle (its base is at the
    bottom), row + 1 for a down-pointing one.
    """
    if direction == TRIANGLE_RIGHT:
        return col + 1, row
    if direction == TRIANGLE_LEFT:
        return col - 1, row
    if triangle_points_up(col, row):
        return col, row - 1
    return col, row + 1
