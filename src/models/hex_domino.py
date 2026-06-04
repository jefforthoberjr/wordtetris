from enum import Enum


class HexDominoType(Enum):
    # SINGLE (1-cell) is disabled so hex dominos only spawn 2-cell pieces; the
    # dedicated HexUnimoType now covers 1-cell hex pieces. Kept commented in case
    # we want to restore mixed 1+2 cell domino spawning.
    # SINGLE = 1
    DOUBLE = 2


# A hex piece is a primary cell plus zero or more satellite cells, each given
# as a DIRECTION index (0..5) from the primary. Unlike the square domino we
# cannot store fixed (dx, dy) offsets: in flat-top offset coordinates the grid
# step for a compass direction depends on the primary column's parity. So we
# store directions and resolve them live via hex_neighbor().
HEX_DOMINO_DIRECTIONS = {
    # HexDominoType.SINGLE: [],   # just the primary cell (disabled; see enum above)
    HexDominoType.DOUBLE: [0],    # primary + its up-right neighbor (dir 0)
}

# Named direction indices (also used by the movement controls).
HEX_UP_RIGHT = 0
HEX_UP = 1
HEX_UP_LEFT = 2
HEX_DOWN_LEFT = 3
HEX_DOWN = 4
HEX_DOWN_RIGHT = 5

# Direction index -> (dcol, drow), one table per column parity.
# Index order around the hex: 0=up-right, 1=up, 2=up-left,
# 3=down-left, 4=down, 5=down-right. Rotating CW advances the index by 1.
# Odd columns sit half a hex higher, so their diagonal neighbors differ.
_EVEN_COL_DIRS = [(1, 0), (0, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
_ODD_COL_DIRS = [(1, 1), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, 0)]


def hex_neighbor(col, row, direction):
    """Return the (col, row) neighbor of a cell in the given direction index."""
    if col % 2 == 0:
        dcol, drow = _EVEN_COL_DIRS[direction]
    else:
        dcol, drow = _ODD_COL_DIRS[direction]
    return col + dcol, row + drow
