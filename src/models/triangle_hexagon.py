from enum import Enum


class TriangleHexagonType(Enum):
    HEXAGON = 6


# The six triangles that meet at one vertex, which together tile a regular
# hexagon: three in the anchor's own row, three in the row across its horizontal
# edge. The anchor is the LEFTMOST cell of its row, so the piece extends right
# and across (down from a point-up anchor, up from a point-down one).
#
# Unlike the unimo/domino tables, whose satellites are a SINGLE direction index
# from the primary, these are direction PATHS -- ordered walks, because a cell of
# a hexagon can be up to three edges away from the anchor and no single index
# reaches it. TrianglePiece accepts either form (an int is read as a one-step
# path), so all three shapes share one class.
#
# Paths are parity-robust: walked from a point-up anchor they give offsets
# (0,0) (1,0) (2,0) (0,-1) (1,-1) (2,-1); from a point-down anchor, (0,0) (1,0)
# (2,0) (0,1) (1,1) (2,1). Both are the same hexagon, mirrored across the row --
# which is what makes ONE table correct for every board position.
TRIANGLE_HEXAGON_DIRECTIONS = {
    TriangleHexagonType.HEXAGON: [
        [0],          # right
        [0, 0],       # right, right
        [1],          # across the flat edge
        [1, 0],       # across, then right
        [1, 0, 0],    # across, then right, right
    ],
}

# Rotation states. A hexagon maps onto ITSELF under the lattice's 120-degree
# turns, so all three states are the same cell set and rotating is a visual no-op
# (the letters keep their cells, which is what the player expects of a symmetric
# piece).
#
# This table exists because the generic index-cycling rotation TrianglePiece uses
# for the unimo/domino -- add 1 to every direction -- is WRONG for a multi-step
# path: rotating [1, 1] ("across, across") walks back onto the anchor, collapsing
# the six cells to four. Any future multi-cell triangle shape needs its rotations
# listed here rather than derived.
TRIANGLE_HEXAGON_ROTATIONS = {
    TriangleHexagonType.HEXAGON: [
        TRIANGLE_HEXAGON_DIRECTIONS[TriangleHexagonType.HEXAGON],  # state 0
        TRIANGLE_HEXAGON_DIRECTIONS[TriangleHexagonType.HEXAGON],  # state 1 (120 CW)
        TRIANGLE_HEXAGON_DIRECTIONS[TriangleHexagonType.HEXAGON],  # state 2 (240 CW)
    ],
}
