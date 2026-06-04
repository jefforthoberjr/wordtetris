from enum import Enum


class HexUnimoType(Enum):
    SINGLE = 1


# A hex piece is a primary cell plus zero or more satellite cells, each given as
# a DIRECTION index (0..5) from the primary (see hex_domino for the rationale).
# The unimo is just the primary cell, so it has no satellites.
HEX_UNIMO_DIRECTIONS = {
    HexUnimoType.SINGLE: [],   # just the primary cell
}
