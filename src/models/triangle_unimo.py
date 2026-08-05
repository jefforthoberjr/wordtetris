from enum import Enum


class TriangleUnimoType(Enum):
    SINGLE = 1


# A triangle piece is a primary cell plus zero or more satellite cells, each
# given as a DIRECTION index (0..2) from the primary (see triangle_domino for the
# rationale). The unimo is just the primary cell, so it has no satellites.
TRIANGLE_UNIMO_DIRECTIONS = {
    TriangleUnimoType.SINGLE: [],   # just the primary cell
}
