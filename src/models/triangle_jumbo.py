from enum import Enum
from models.triangle_domino import triangle_neighbor
from models.triangle_hexagon import (
    TriangleHexagonType, TRIANGLE_HEXAGON_DIRECTIONS,
)


class TriangleJumboType(Enum):
    JUMBO_HEX = 1


# JUMBO cells: one cell whose shape spans several grid coordinates. JUMBO_HEX --
# the first and so far only one -- covers the same six-triangle area as
# TriangleHexagonType.HEXAGON, but as ONE cell holding ONE gram instead of six
# cells holding six.
#
# This is the board's first cell that is not the size of a grid coordinate, and
# the whole point of it is the trade it offers: it spends six coordinates' worth
# of board on a single gram, and in exchange that gram sits on a cell with SIX
# edge-neighbors instead of a triangle's three -- a hub words can route through
# from twice as many directions. It counts as one cell everywhere it matters (one
# node in a word path, one cell for the min-cell rules, one for scoring), and
# clears whole.
#
# The footprint is expressed with the same direction PATHS as the six-cell
# hexagon piece, so both shapes cover exactly the same coordinates and stay in
# step if that shape is ever changed. The grid layer that makes one cell span
# them is TriangleGrid.place_jumbo / resolve / footprint.
TRIANGLE_JUMBO_DIRECTIONS = {
    TriangleJumboType.JUMBO_HEX:
        TRIANGLE_HEXAGON_DIRECTIONS[TriangleHexagonType.HEXAGON],
}

# Rotation-symmetric, like the six-cell hexagon: all three states are the same
# footprint, so turning it is a visual no-op.
TRIANGLE_JUMBO_ROTATIONS = {
    TriangleJumboType.JUMBO_HEX: [
        TRIANGLE_JUMBO_DIRECTIONS[TriangleJumboType.JUMBO_HEX],
        TRIANGLE_JUMBO_DIRECTIONS[TriangleJumboType.JUMBO_HEX],
        TRIANGLE_JUMBO_DIRECTIONS[TriangleJumboType.JUMBO_HEX],
    ],
}

# Piece types drawn as ONE oversized cell rather than one cell per coordinate.
# TrianglePiece checks this to decide which of its two rendering / cell-data
# forms to use, and the settle path checks piece.jumbo_cell to route through
# TriangleGrid.place_jumbo. Add future jumbo shapes here.
JUMBO_CELL_TYPES = frozenset({TriangleJumboType.JUMBO_HEX})


# Anchor offsets from one JUMBO_HEX to the six that TOUCH it edge-to-edge -- the
# hexagon lattice, not the triangle one.
#
# Two jumbos are neighbors when their centers sit sqrt(3) * side apart (flat-top
# hexagons of circumradius `side`). Worked in anchor coordinates that comes out
# as the offsets below, and -- this is the part worth stating -- they are
# PARITY-FREE: they hold for a point-up and a point-down anchor alike, because a
# jumbo's center is derived from its anchor with the same parity correction that
# jumbo_hex_center applies (see triangle_grid).
#
# Order is counter-clockwise from due north, so a ring built from it reads
# around the mission rather than jumping about.
#
# This is why a jumbo ring CANNOT be built from TriangleGrid.neighbors(): those
# are the anchor triangle's three edge-neighbors, one triangle away, and a jumbo
# placed on one would overlap four of the center jumbo's six coordinates. That
# overlap was the original mission_center_obstacle_ring bug.
JUMBO_HEX_RING_OFFSETS = (
    (0, 2),     # N
    (-3, 1),    # NW
    (-3, -1),   # SW
    (0, -2),    # S
    (3, -1),    # SE
    (3, 1),     # NE
)


def jumbo_hex_footprint(col, row):
    """The six coordinates a JUMBO_HEX anchored at (col, row) covers.

    Walks the same direction PATHS the piece does (TrianglePiece resolves them
    identically), so a formation asking "does this fit on the board?" is asking
    about the real shape rather than a second copy of the offsets that could drift
    out of step with it. Coordinates are not range-checked -- an anchor near an
    edge yields off-board entries, which is exactly what the fit test looks for."""
    cells = [(col, row)]
    for path in TRIANGLE_JUMBO_DIRECTIONS[TriangleJumboType.JUMBO_HEX]:
        x, y = col, row
        for direction in path:
            x, y = triangle_neighbor(x, y, direction)
        cells.append((x, y))
    return cells


def jumbo_hex_ring_anchors(col, row):
    """The six anchor coordinates of the jumbo hexes surrounding the jumbo
    anchored at (col, row) -- edge-to-edge, no overlap, no gaps.

    Coordinates are NOT range-checked: an anchor near a board edge yields
    off-board entries, and even an on-board anchor may have a footprint that runs
    off. Callers filter with the board (see _jumbo_fits in game_screen_setup)."""
    return [(col + dx, row + dy) for dx, dy in JUMBO_HEX_RING_OFFSETS]
