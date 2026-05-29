from enum import Enum

class TetriminoType(Enum):
    I = 1
    O = 2
    T = 3
    S = 4
    Z = 5
    J = 6
    L = 7

TETRIMINO_SHAPES = {
    TetriminoType.I: [
        (0, 0), (1, 0), (2, 0), (3, 0)
    ],
    TetriminoType.O: [
        (0, 0), (1, 0), (0, 1), (1, 1)
    ],
    TetriminoType.T: [
        (0, 0), (1, 0), (2, 0), (1, 1)
    ],
    TetriminoType.S: [
        (0, 0), (1, 0), (1, 1), (2, 1)
    ],
    TetriminoType.Z: [
        (1, 0), (2, 0), (0, 1), (1, 1)
    ],
    TetriminoType.J: [
        (0, 0), (0, 1), (1, 1), (2, 1)
    ],
    TetriminoType.L: [
        (2, 0), (0, 1), (1, 1), (2, 1)
    ],
}

# Rotation states for each tetrimino (4 states: 0, 90, 180, 270 degrees CW)
# IMPORTANT: Each index must represent the same logical cell across all states
# so that letters stay attached to the correct cell when rotating
# Pieces spawn at state 0
TETRIMINO_ROTATIONS = {
    # I piece: pivot around cell 1 which stays at (1,1)
    TetriminoType.I: [
        [(0, 1), (1, 1), (2, 1), (3, 1)],  # state 0: horizontal
        [(1, 0), (1, 1), (1, 2), (1, 3)],  # state 1: vertical (90 CW)
        [(2, 1), (1, 1), (0, 1), (-1, 1)], # state 2: horizontal (180)
        [(1, 2), (1, 1), (1, 0), (1, -1)], # state 3: vertical (270 CW)
    ],
    # O piece: cells rotate CW around center
    # cell 0=bottom-left, 1=bottom-right, 2=top-right, 3=top-left
    TetriminoType.O: [
        [(0, 0), (1, 0), (1, 1), (0, 1)],  # state 0
        [(1, 0), (1, 1), (0, 1), (0, 0)],  # state 1 (90 CW)
        [(1, 1), (0, 1), (0, 0), (1, 0)],  # state 2 (180)
        [(0, 1), (0, 0), (1, 0), (1, 1)],  # state 3 (270 CW)
    ],
    # T piece: pivot around cell 1 (center at 1,1)
    TetriminoType.T: [
        [(0, 1), (1, 1), (2, 1), (1, 2)],  # state 0: stem up
        [(1, 0), (1, 1), (1, 2), (0, 1)],  # state 1: stem left (90 CW)
        [(2, 1), (1, 1), (0, 1), (1, 0)],  # state 2: stem down (180)
        [(1, 2), (1, 1), (1, 0), (2, 1)],  # state 3: stem right (270 CW)
    ],
    # S piece: pivot around cell 1 at (1,1)
    TetriminoType.S: [
        [(0, 0), (1, 0), (1, 1), (2, 1)],  # state 0: horizontal
        [(2, 0), (2, 1), (1, 1), (1, 2)],  # state 1: vertical (90 CW)
        [(2, 2), (1, 2), (1, 1), (0, 1)],  # state 2: horizontal (180)
        [(0, 2), (0, 1), (1, 1), (1, 0)],  # state 3: vertical (270 CW)
    ],
    # Z piece: pivot around cell 2 at (1,1)
    TetriminoType.Z: [
        [(0, 2), (1, 2), (1, 1), (2, 1)],  # state 0: horizontal
        [(0, 0), (0, 1), (1, 1), (1, 2)],  # state 1: vertical (90 CW)
        [(2, 0), (1, 0), (1, 1), (0, 1)],  # state 2: horizontal (180)
        [(2, 2), (2, 1), (1, 1), (1, 0)],  # state 3: vertical (270 CW)
    ],
    # J piece: cell 0=corner, 1,2,3=bar from corner outward
    TetriminoType.J: [
        [(0, 0), (0, 1), (1, 1), (2, 1)],  # state 0
        [(2, 0), (1, 0), (1, 1), (1, 2)],  # state 1 (90 CW)
        [(2, 2), (2, 1), (1, 1), (0, 1)],  # state 2 (180)
        [(0, 2), (1, 2), (1, 1), (1, 0)],  # state 3 (270 CW)
    ],
    # L piece: cell 0=corner, 1,2,3=bar from corner outward
    TetriminoType.L: [
        [(2, 0), (0, 1), (1, 1), (2, 1)],  # state 0
        [(2, 2), (1, 0), (1, 1), (1, 2)],  # state 1 (90 CW)
        [(0, 2), (2, 1), (1, 1), (0, 1)],  # state 2 (180)
        [(0, 0), (1, 2), (1, 1), (1, 0)],  # state 3 (270 CW)
    ],
}
