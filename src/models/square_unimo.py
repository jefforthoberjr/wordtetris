from enum import Enum


class SquareUnimoType(Enum):
    SINGLE = 1


SQUARE_UNIMO_SHAPES = {
    SquareUnimoType.SINGLE: [
        (0, 0)
    ],
}

# Rotation states for the unimo (4 states: 0, 90, 180, 270 degrees CW)
# IMPORTANT: Each index must represent the same logical cell across all states
# so that letters stay attached to the correct cell when rotating
# Pieces spawn at state 0
SQUARE_UNIMO_ROTATIONS = {
    # Single cell: rotation has no visual effect (one cell), but states are
    # listed so the rotate logic has all four to cycle through.
    SquareUnimoType.SINGLE: [
        [(0, 0)],  # state 0
        [(0, 0)],  # state 1 (90 CW)
        [(0, 0)],  # state 2 (180)
        [(0, 0)],  # state 3 (270 CW)
    ],
}
