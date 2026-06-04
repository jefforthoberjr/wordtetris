from enum import Enum


class SquareDominoType(Enum):
    SINGLE = 1
    DOUBLE = 2


SQUARE_DOMINO_SHAPES = {
    SquareDominoType.SINGLE: [
        (0, 0)
    ],
    SquareDominoType.DOUBLE: [
        (0, 0), (1, 0)
    ],
}

# Rotation states for each domino (4 states: 0, 90, 180, 270 degrees CW)
# IMPORTANT: Each index must represent the same logical cell across all states
# so that letters stay attached to the correct cell when rotating
# Pieces spawn at state 0
SQUARE_DOMINO_ROTATIONS = {
    # Single piece: just one cell, rotation has no visual effect but cells cycle position
    SquareDominoType.SINGLE: [
        [(0, 0)],  # state 0
        [(0, 0)],  # state 1 (90 CW)
        [(0, 0)],  # state 2 (180)
        [(0, 0)],  # state 3 (270 CW)
    ],
    # Double piece: horizontal or vertical
    SquareDominoType.DOUBLE: [
        [(0, 0), (1, 0)],  # state 0: horizontal
        [(0, 0), (0, 1)],  # state 1: vertical (90 CW)
        [(1, 0), (0, 0)],  # state 2: horizontal (180)
        [(0, 1), (0, 0)],  # state 3: vertical (270 CW)
    ],
}
